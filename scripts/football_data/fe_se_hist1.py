"""Close the Sweden Allsvenskan historical-result completeness gap.

This module is deliberately bounded to FE-SE-HIST-1.  It consumes a caller
supplied Football-Data.co.uk capture, reuses the existing result adapter and
contract, and never fetches data or changes model/production prediction state.
The authoritative DuckDB write is opt-in and is performed by rebuilding a
temporary database from the existing records plus the deduplicated Sweden
2025 target records.  A conflicting match or unresolved identity fails before
any authoritative write is attempted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import validate_record
from .data_home import historical_results_path
from .historical_results import deduplicate_historical_results
from .providers.football_data_uk import FootballDataCoUkHistoricalAdapter
from .providers.openfootball import OpenFootballHistoricalAdapter
from .storage import HistoricalResultStore, content_sha256


ROOT = Path(__file__).resolve().parents[2]
MILESTONE = "FE-SE-HIST-1"
COMPETITION_ID = "competition:sweden-allsvenskan"
TARGET_SEASON_ID = "season:sweden-allsvenskan:2025"
TARGET_SEASON = "2025"
CURRENT_SEASON_ID = "season:sweden-allsvenskan:2026"
SOURCE_PROVIDER = "football-data.co.uk"
SOURCE_URL = "https://www.football-data.co.uk/new/SWE.csv"
SOURCE_FILE = "SWE.csv"
EXPECTED_TARGET_MATCHES = 240

DEFAULT_MANIFEST = ROOT / "data" / "football_data" / "fe_se_hist1" / "source_manifest.json"
DEFAULT_BASE_IDENTITY = ROOT / "data" / "football_data" / "football_data_uk" / "identity_evidence.json"
DEFAULT_IDENTITY_SUPPLEMENT = ROOT / "data" / "football_data" / "fe_se_hist1" / "identity_evidence.json"
DEFAULT_SAMPLE = ROOT / "data" / "football_data" / "historical_result_samples" / "football_data_uk_sweden_2025.json"
DEFAULT_AUDIT = ROOT / "data" / "football_data" / "fe_se_hist1" / "audit.json"
DEFAULT_OPENFOOTBALL_MANIFEST = ROOT / "data" / "football_data" / "openfootball" / "source_manifest.json"
DEFAULT_OPENFOOTBALL_IDENTITY = ROOT / "data" / "football_data" / "openfootball" / "identity_evidence.json"
DEFAULT_DB = historical_results_path()


class ClosureError(ValueError):
    """Raised when the bounded closure cannot pass its fail-closed gates."""


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ClosureError(f"expected JSON object: {path}")
    return value


def _write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _hash_bytes(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    return raw, hashlib.sha256(raw).hexdigest()


def _load_identity_mappings(
    base_path: str | Path,
    supplement_path: str | Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    """Merge exact reviewed mappings and reject conflicting evidence."""

    base = _read_json(base_path)
    supplement = _read_json(supplement_path)
    merged: dict[str, Mapping[str, Any]] = {}
    for source_name, document in (("base", base), ("supplement", supplement)):
        rows = document.get("mappings", [])
        if not isinstance(rows, list):
            raise ClosureError(f"{source_name} identity mappings must be a list")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ClosureError(f"{source_name} identity mapping must be an object")
            provider_name = row.get("provider_team_name")
            canonical_id = row.get("canonical_team_id")
            if not isinstance(provider_name, str) or not provider_name.strip():
                raise ClosureError("identity mapping provider_team_name is required")
            if not isinstance(canonical_id, str) or not canonical_id.strip():
                raise ClosureError(f"identity mapping canonical_team_id is required: {provider_name}")
            if row.get("verified") is not True:
                raise ClosureError(f"identity mapping is not verified: {provider_name}")
            if row.get("resolution_method") not in {"manual_verified", "cross_source_context_verified"}:
                raise ClosureError(f"identity mapping is not a reviewed deterministic mapping: {provider_name}")
            existing = merged.get(provider_name)
            if existing is not None and (
                existing.get("canonical_team_id") != canonical_id
                or existing.get("resolution_method") != row.get("resolution_method")
            ):
                raise ClosureError(f"conflicting identity mapping: {provider_name}")
            merged[provider_name] = row
    return merged, {
        "base_path": str(Path(base_path)),
        "supplement_path": str(Path(supplement_path)),
        "base_mapping_count": len(base.get("mappings", [])),
        "supplement_mapping_count": len(supplement.get("mappings", [])),
        "merged_mapping_count": len(merged),
    }


def _target_source(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if manifest.get("source_url") != SOURCE_URL:
        raise ClosureError("FE-SE-HIST-1 source URL is not Football-Data Sweden SWE.csv")
    if manifest.get("source_file") != SOURCE_FILE:
        raise ClosureError("FE-SE-HIST-1 source file is not SWE.csv")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ClosureError("source manifest sources must be a list")
    matches = [
        source
        for source in sources
        if isinstance(source, Mapping)
        and source.get("competition_key") == "sweden-allsvenskan"
        and str(source.get("provider_season_id")) == TARGET_SEASON
    ]
    if len(matches) != 1:
        raise ClosureError("source manifest must contain exactly one Sweden Allsvenskan 2025 source")
    source = matches[0]
    if source.get("source_completeness_status") != "COMPLETE" or source.get("result_coverage") != "SUPPORTED":
        raise ClosureError("Football-Data 2025 source is not marked complete and supported")
    if int(source.get("listed_match_count", -1)) != EXPECTED_TARGET_MATCHES:
        raise ClosureError("Football-Data 2025 listed match count is not 240")
    if int(source.get("parsed_result_count", -1)) != EXPECTED_TARGET_MATCHES:
        raise ClosureError("Football-Data 2025 parsed result count is not 240")
    return source


def load_target_records(
    raw_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    base_identity_path: str | Path = DEFAULT_BASE_IDENTITY,
    identity_supplement_path: str | Path = DEFAULT_IDENTITY_SUPPLEMENT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse one verified Football-Data capture for Sweden Allsvenskan 2025."""

    raw_file = Path(raw_path)
    raw_bytes, raw_sha256 = _hash_bytes(raw_file)
    manifest = _read_json(manifest_path)
    source = _target_source(manifest)
    expected_hash = manifest.get("raw_sha256")
    if expected_hash != raw_sha256:
        raise ClosureError(
            f"raw capture SHA256 mismatch: manifest={expected_hash!r}, actual={raw_sha256!r}"
        )
    if source.get("raw_sha256") not in (None, raw_sha256):
        raise ClosureError("2025 source entry raw_sha256 does not match the supplied capture")
    mappings, identity_meta = _load_identity_mappings(base_identity_path, identity_supplement_path)
    adapter = FootballDataCoUkHistoricalAdapter(
        competition_id=COMPETITION_ID,
        season_id=TARGET_SEASON_ID,
        provider_competition_id=str(source["provider_competition_id"]),
        provider_competition_name=str(source["provider_competition_name"]),
        provider_season_id=str(source["provider_season_id"]),
        provider_season_name=str(source["provider_season_name"]),
        source_url=str(manifest["source_url"]),
        source_file=str(manifest["source_file"]),
        captured_at=str(manifest["captured_at"]),
        raw_sha256=raw_sha256,
        team_identity_resolver=mappings,
    )
    records = adapter.parse_csv_text(raw_bytes.decode("utf-8-sig"), season_filter=TARGET_SEASON)
    for record in records:
        validate_record("historical_match_result", record)
    metadata = {
        "source_url": manifest["source_url"],
        "source_file": manifest["source_file"],
        "captured_at": manifest["captured_at"],
        "raw_sha256": raw_sha256,
        "raw_bytes": len(raw_bytes),
        "http_last_modified": manifest.get("http_last_modified"),
        "etag": manifest.get("etag"),
        "source_entry": dict(source),
        "identity": identity_meta,
    }
    return records, metadata


def _match_facts(record: Mapping[str, Any]) -> tuple[Any, ...]:
    kickoff = record.get("kickoff_at")
    return (
        record.get("competition_id"),
        record.get("season_id"),
        record.get("home_team_id"),
        record.get("away_team_id"),
        record.get("home_goals"),
        record.get("away_goals"),
        str(kickoff)[:10] if kickoff not in (None, "") else kickoff,
        record.get("entity_type"),
        record.get("match_type"),
    )


def _source_ref(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("source_record_ref"):
        return str(provenance["source_record_ref"])
    return str(record.get("provider_match_id") or "")


def _confirmation(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": record.get("provider"),
        "provider_match_id": record.get("provider_match_id"),
        "source_record_ref": _source_ref(record),
        "kickoff_at": record.get("kickoff_at"),
        "home_goals": record.get("home_goals"),
        "away_goals": record.get("away_goals"),
    }


def _dedupe_dicts(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for value in values:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if encoded not in seen:
            seen.add(encoded)
            output.append(dict(value))
    return output


def _with_existing_confirmation(
    candidate: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    """Retain prior source evidence while selecting the current FD record."""

    merged = dict(candidate)
    old_refs = list(existing.get("duplicate_source_refs") or [])
    old_refs.append(_source_ref(existing))
    merged["duplicate_source_refs"] = sorted({str(value) for value in old_refs if str(value)})
    old_confirmations = existing.get("source_confirmations") or [_confirmation(existing)]
    new_confirmations = merged.get("source_confirmations") or [_confirmation(merged)]
    merged["source_confirmations"] = _dedupe_dicts([*new_confirmations, *old_confirmations])
    validate_record("historical_match_result", merged)
    return merged


def _db_records(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    return HistoricalResultStore(path).records()


def _records_dataset_digest(records: Iterable[Mapping[str, Any]]) -> str:
    """Mirror HistoricalResultStore.dataset_digest for an in-memory rebuild."""

    digests = sorted(content_sha256(dict(record)) for record in records)
    return content_sha256(digests)


def _is_target(record: Mapping[str, Any]) -> bool:
    return record.get("competition_id") == COMPETITION_ID and record.get("season_id") == TARGET_SEASON_ID


def prepare_authoritative_records(
    existing_records: Iterable[Mapping[str, Any]],
    candidate_records: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Prepare a target-only replacement without silent duplicates/conflicts."""

    existing = [dict(record) for record in existing_records]
    candidates = [dict(record) for record in candidate_records]
    if any(not _is_target(record) for record in candidates):
        raise ClosureError("candidate source contains a record outside Sweden Allsvenskan 2025")
    unresolved = sum(record.get("resolution_status") != "resolved" for record in candidates)
    if unresolved:
        raise ClosureError(f"unresolved identity records cannot enter authoritative store: {unresolved}")
    candidate_report = deduplicate_historical_results(candidates)
    if candidate_report.possible_duplicates or candidate_report.conflicts:
        raise ClosureError(
            "candidate source has duplicate/conflict records: "
            f"possible={candidate_report.possible_duplicates}, conflicts={candidate_report.conflicts}"
        )
    target_existing = [record for record in existing if _is_target(record)]
    existing_report = deduplicate_historical_results(target_existing)
    if existing_report.possible_duplicates or existing_report.conflicts:
        raise ClosureError(
            "authoritative target already contains duplicate/conflict records: "
            f"possible={existing_report.possible_duplicates}, conflicts={existing_report.conflicts}"
        )
    existing_by_id: dict[str, dict[str, Any]] = {}
    for record in target_existing:
        canonical_id = record.get("canonical_match_id")
        if not canonical_id:
            raise ClosureError("authoritative target contains a record without canonical_match_id")
        if canonical_id in existing_by_id:
            raise ClosureError(f"authoritative target contains repeated canonical_match_id: {canonical_id}")
        existing_by_id[str(canonical_id)] = record

    selected_target: list[dict[str, Any]] = []
    new_count = 0
    replacement_count = 0
    same_source_count = 0
    existing_overlap_count = 0
    for candidate in sorted(
        candidate_report.records,
        key=lambda record: (str(record.get("kickoff_at") or ""), str(record.get("canonical_match_id") or "")),
    ):
        canonical_id = str(candidate.get("canonical_match_id") or "")
        old = existing_by_id.get(canonical_id)
        if old is None:
            selected_target.append(candidate)
            new_count += 1
            continue
        existing_overlap_count += 1
        if _match_facts(old) != _match_facts(candidate):
            raise ClosureError(f"source conflict for canonical_match_id: {canonical_id}")
        if (
            old.get("provider") == SOURCE_PROVIDER
            and old.get("provider_match_id") == candidate.get("provider_match_id")
        ):
            selected_target.append(old)
            same_source_count += 1
        else:
            selected_target.append(_with_existing_confirmation(candidate, old))
            replacement_count += 1

    non_target = [record for record in existing if not _is_target(record)]
    final_records = [*non_target, *selected_target]
    final_records.sort(
        key=lambda record: (
            str(record.get("kickoff_at") or ""),
            str(record.get("canonical_match_id") or ""),
            str(record.get("provider") or ""),
            str(record.get("provider_match_id") or ""),
        )
    )
    return final_records, {
        "candidate_input_count": len(candidates),
        "candidate_unique_count": len(candidate_report.records),
        "candidate_duplicates_collapsed": candidate_report.duplicates_collapsed,
        "candidate_possible_duplicates": candidate_report.possible_duplicates,
        "candidate_conflicts": candidate_report.conflicts,
        "existing_target_count": len(target_existing),
        "existing_overlap_count": existing_overlap_count,
        "new_record_count": new_count,
        "replacement_record_count": replacement_count,
        "same_source_existing_count": same_source_count,
    }


def _stats(values: Iterable[int]) -> dict[str, int | float | None]:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return {"min": None, "median": None, "max": None}
    median = statistics.median(ordered)
    return {
        "min": ordered[0],
        "median": int(median) if float(median).is_integer() else median,
        "max": ordered[-1],
    }


def _network_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [
        record
        for record in records
        if record.get("eligible_for_team_strength") is True
        and record.get("resolution_status") == "resolved"
        and record.get("home_team_id")
        and record.get("away_team_id")
    ]
    teams = sorted({str(record["home_team_id"]) for record in eligible} | {str(record["away_team_id"]) for record in eligible})
    adjacency: dict[str, set[str]] = {team: set() for team in teams}
    for record in eligible:
        home = str(record["home_team_id"])
        away = str(record["away_team_id"])
        adjacency[home].add(away)
        adjacency[away].add(home)
    seen: set[str] = set()
    if teams:
        stack = [teams[0]]
        while stack:
            team = stack.pop()
            if team in seen:
                continue
            seen.add(team)
            stack.extend(sorted(adjacency[team] - seen))
    return {
        "team_count": len(teams),
        "match_count": len(eligible),
        "edge_count": len({
            tuple(sorted((str(record["home_team_id"]), str(record["away_team_id"]))))
            for record in eligible
        }),
        "connected": bool(teams) and len(seen) == len(teams),
        "isolated_team_count": sum(not neighbors for neighbors in adjacency.values()),
        "team_ids": teams,
    }


def summarize_authoritative(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = [dict(record) for record in records]
    sweden = [record for record in materialized if record.get("competition_id") == COMPETITION_ID]
    target = [record for record in sweden if record.get("season_id") == TARGET_SEASON_ID]
    current = [record for record in sweden if record.get("season_id") == CURRENT_SEASON_ID]

    def season_summary(rows: list[dict[str, Any]], season: str) -> dict[str, Any]:
        teams = sorted({str(row["home_team_id"]) for row in rows if row.get("home_team_id")} | {str(row["away_team_id"]) for row in rows if row.get("away_team_id")})
        appearances = Counter(
            team
            for row in rows
            for team in (row.get("home_team_id"), row.get("away_team_id"))
            if team
        )
        return {
            "season": season,
            "match_count": len(rows),
            "team_count": len(teams),
            "team_match_count_stats": _stats(appearances.values()),
            "providers": dict(sorted(Counter(str(row.get("provider")) for row in rows).items())),
            "earliest_kickoff": min((str(row.get("kickoff_at")) for row in rows if row.get("kickoff_at")), default=None),
            "latest_kickoff": max((str(row.get("kickoff_at")) for row in rows if row.get("kickoff_at")), default=None),
            "network": _network_summary(rows),
        }

    appearances = Counter(
        team
        for row in sweden
        for team in (row.get("home_team_id"), row.get("away_team_id"))
        if team
    )
    return {
        "global_record_count": len(materialized),
        "sweden_allsvenskan_record_count": len(sweden),
        "sweden_allsvenskan_team_count": len(appearances),
        "sweden_allsvenskan_team_match_count_stats": _stats(appearances.values()),
        "earliest_kickoff": min((str(row.get("kickoff_at")) for row in sweden if row.get("kickoff_at")), default=None),
        "latest_kickoff": max((str(row.get("kickoff_at")) for row in sweden if row.get("kickoff_at")), default=None),
        "providers": dict(sorted(Counter(str(row.get("provider")) for row in sweden).items())),
        "seasons": {
            TARGET_SEASON: season_summary(target, TARGET_SEASON),
            "2026": season_summary(current, "2026"),
        },
    }


def _secondary_cross_check(
    candidate_records: Iterable[Mapping[str, Any]],
    *,
    raw_path: str | Path | None,
    manifest_path: str | Path = DEFAULT_OPENFOOTBALL_MANIFEST,
    identity_path: str | Path = DEFAULT_OPENFOOTBALL_IDENTITY,
) -> dict[str, Any]:
    if raw_path is None:
        return {"status": "NOT_RUN"}
    manifest = _read_json(manifest_path)
    source_rows = [
        row
        for row in manifest.get("sources", [])
        if isinstance(row, Mapping)
        and row.get("competition_key") == "sweden-allsvenskan"
        and str(row.get("provider_season_id")) == TARGET_SEASON
    ]
    if len(source_rows) != 1:
        raise ClosureError("OpenFootball cross-check manifest source is ambiguous")
    source = source_rows[0]
    raw_bytes, raw_sha256 = _hash_bytes(Path(raw_path))
    expected_hash = source.get("raw_sha256")
    if expected_hash and expected_hash != raw_sha256:
        raise ClosureError("OpenFootball cross-check raw SHA256 mismatch")
    identities = _read_json(identity_path)
    identity_map = {
        str(row["provider_team_name"]): row
        for row in identities.get("teams", [])
        if isinstance(row, Mapping)
    }
    adapter = OpenFootballHistoricalAdapter(
        competition_id=COMPETITION_ID,
        season_id=TARGET_SEASON_ID,
        provider_competition_id=str(source["provider_competition_id"]),
        provider_competition_name=str(source["provider_competition_name"]),
        provider_season_id=str(source["provider_season_id"]),
        provider_season_name=str(source["provider_season_name"]),
        repository=str(manifest["repository"]),
        commit_sha=str(manifest["commit_sha"]),
        source_file=str(source["source_file"]),
        captured_at=str(manifest["captured_at"]),
        country="Sweden",
        team_identity_resolver=identity_map,
    )
    secondary_records = adapter.parse_text(raw_bytes.decode("utf-8"), raw_sha256=raw_sha256)
    candidate_by_key = {_cross_source_key(row): row for row in candidate_records if row.get("resolution_status") == "resolved"}
    secondary_by_key = {_cross_source_key(row): row for row in secondary_records if row.get("resolution_status") == "resolved"}
    shared = sorted(set(candidate_by_key) & set(secondary_by_key))
    score_disagreements = sum(
        (candidate_by_key[key].get("home_goals"), candidate_by_key[key].get("away_goals"))
        != (secondary_by_key[key].get("home_goals"), secondary_by_key[key].get("away_goals"))
        for key in shared
    )
    return {
        "status": "PASS" if score_disagreements == 0 else "CONFLICT",
        "provider": "openfootball",
        "repository": manifest.get("repository"),
        "commit_sha": manifest.get("commit_sha"),
        "source_file": source.get("source_file"),
        "raw_sha256": raw_sha256,
        "secondary_record_count": len(secondary_records),
        "secondary_resolved_count": sum(row.get("resolution_status") == "resolved" for row in secondary_records),
        "shared_match_count": len(shared),
        "missing_in_secondary_count": len(set(candidate_by_key) - set(secondary_by_key)),
        "missing_in_primary_count": len(set(secondary_by_key) - set(candidate_by_key)),
        "score_disagreement_count": score_disagreements,
        "sample_basis": "calendar date + canonical home/away identity; full-time score compared separately",
    }


def _cross_source_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(record.get("kickoff_at") or "")[:10],
        record.get("home_team_id"),
        record.get("away_team_id"),
    )


def _write_rebuilt_store(
    db_path: str | Path,
    final_records: list[Mapping[str, Any]],
    *,
    backup_path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_created = False
    if target.exists():
        if backup_path is None:
            raise ClosureError("backup_path is required when replacing an existing authoritative store")
        backup = Path(backup_path)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        backup_created = True
    fd, temp_name = tempfile.mkstemp(prefix=f"{target.stem}.fe-se-hist1.", suffix=".duckdb", dir=str(target.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.unlink()
        temp_store = HistoricalResultStore(temp_path)
        inserted = temp_store.append_many(final_records)
        if temp_store.count() != len(final_records):
            raise ClosureError("rebuilt authoritative store record count mismatch")
        os.replace(temp_path, target)
    except Exception:
        for path in (temp_path, Path(f"{temp_path}.wal")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    return {"backup_created": backup_created, "rebuilt_record_count": len(final_records), "inserted_record_count": inserted}


def run_closure(
    raw_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    base_identity_path: str | Path = DEFAULT_BASE_IDENTITY,
    identity_supplement_path: str | Path = DEFAULT_IDENTITY_SUPPLEMENT,
    db_path: str | Path = DEFAULT_DB,
    secondary_raw_path: str | Path | None = None,
    secondary_manifest_path: str | Path = DEFAULT_OPENFOOTBALL_MANIFEST,
    secondary_identity_path: str | Path = DEFAULT_OPENFOOTBALL_IDENTITY,
    write_authoritative: bool = False,
    backup_path: str | Path | None = None,
    sample_output: str | Path | None = DEFAULT_SAMPLE,
    audit_output: str | Path | None = DEFAULT_AUDIT,
) -> dict[str, Any]:
    candidates, source_meta = load_target_records(
        raw_path,
        manifest_path=manifest_path,
        base_identity_path=base_identity_path,
        identity_supplement_path=identity_supplement_path,
    )
    candidate_unresolved = sum(record.get("resolution_status") != "resolved" for record in candidates)
    if len(candidates) != EXPECTED_TARGET_MATCHES:
        raise ClosureError(f"Football-Data 2025 parsed records != 240: {len(candidates)}")
    if candidate_unresolved:
        raise ClosureError(f"Football-Data 2025 unresolved identity count != 0: {candidate_unresolved}")
    candidate_dedup = deduplicate_historical_results(candidates)
    if candidate_dedup.conflicts or candidate_dedup.possible_duplicates:
        raise ClosureError("Football-Data 2025 candidate contains conflicts or possible duplicates")

    existing = _db_records(db_path)
    before = summarize_authoritative(existing)
    before_dataset_sha256 = _records_dataset_digest(existing)
    final_records, merge_meta = prepare_authoritative_records(existing, candidates)
    after_simulated = summarize_authoritative(final_records)
    after_dataset_sha256 = _records_dataset_digest(final_records)
    secondary = _secondary_cross_check(
        candidates,
        raw_path=secondary_raw_path,
        manifest_path=secondary_manifest_path,
        identity_path=secondary_identity_path,
    )
    if secondary.get("status") == "CONFLICT":
        raise ClosureError("secondary public-source cross-check found score conflicts")

    write_meta: dict[str, Any] = {"write_authoritative": False, "backup_created": False}
    after = after_simulated
    if write_authoritative:
        before_digests = {
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for record in existing
        }
        final_digests = {
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for record in final_records
        }
        if before_digests != final_digests:
            write_meta = {
                "write_authoritative": True,
                **_write_rebuilt_store(db_path, final_records, backup_path=backup_path),
            }
        else:
            write_meta = {"write_authoritative": True, "backup_created": False, "idempotent_noop": True}
        after = summarize_authoritative(_db_records(db_path))

    after_dataset_verified_sha256 = _records_dataset_digest(_db_records(db_path)) if write_authoritative else None

    sample = {
        "contract_version": "historical_result_sample.v1",
        "milestone": MILESTONE,
        "provider": SOURCE_PROVIDER,
        "source_file": SOURCE_FILE,
        "competition_id": COMPETITION_ID,
        "season_id": TARGET_SEASON_ID,
        "record_count": len(candidate_dedup.records),
        "eligible_record_count": sum(record.get("eligible_for_team_strength") is True for record in candidate_dedup.records),
        "source_capture": source_meta,
        "records": candidate_dedup.records,
    }
    audit = {
        "milestone": MILESTONE,
        "status": "READY_FOR_ACCEPTANCE",
        "scope": {
            "competition_id": COMPETITION_ID,
            "target_season": TARGET_SEASON,
            "source_provider": SOURCE_PROVIDER,
            "research_only": True,
            "model_parameters_changed": False,
            "production_prediction_changed": False,
            "other_leagues_changed": False,
        },
        "root_cause": {
            "authoritative_2025_before": before["seasons"][TARGET_SEASON]["match_count"],
            "football_data_2025_source_complete": True,
            "football_data_2025_source_rows": len(candidates),
            "existing_2025_provider": before["seasons"][TARGET_SEASON]["providers"],
            "existing_2025_sample_provider": "openfootball_partial_pilot",
            "ingestion_omission": "Football-Data 2025 was present in the source manifest but the checked-in builder/sample/import path was only executed for the 2026 pilot.",
            "identity_gap": "The prior Football-Data identity evidence covered the 2026 team set and omitted exact 2025-only source names Norrkoping, Oster and Varnamo; FE-SE-HIST-1 adds reviewed exact mappings backed by OpenFootball context.",
            "dedup_murder_evidence": "No Football-Data 2025 rows were present in the authoritative store before closure; the existing 16 rows were OpenFootball rows and matched 16 Football-Data fixtures by facts.",
        },
        "source_capture": source_meta,
        "candidate_parse": {
            "listed_match_count": EXPECTED_TARGET_MATCHES,
            "parsed_result_count": len(candidates),
            "resolved_identity_count": len(candidates) - candidate_unresolved,
            "unresolved_identity_count": candidate_unresolved,
            "candidate_duplicate_count": candidate_dedup.duplicates_collapsed,
            "candidate_possible_duplicate_count": candidate_dedup.possible_duplicates,
            "candidate_conflict_count": candidate_dedup.conflicts,
            "team_count": len({team for record in candidates for team in (record.get("home_team_id"), record.get("away_team_id")) if team}),
        },
        "deduplication": merge_meta,
        "secondary_cross_check": secondary,
        "authoritative_before": before,
        "authoritative_after": after,
        "authoritative_store": {
            "path_policy": "${FOOTBALL_DATA_HOME}/historical_results.duckdb",
            "before_dataset_sha256": before_dataset_sha256,
            "after_dataset_sha256": after_dataset_sha256,
            "after_dataset_verified_sha256": after_dataset_verified_sha256,
            "rebuild_digest_matches": after_dataset_verified_sha256 in {None, after_dataset_sha256},
        },
        "network": {
            "target_2025_complete_double_round_robin": after["seasons"][TARGET_SEASON]["match_count"] == EXPECTED_TARGET_MATCHES,
            "target_2025_expected_match_count": EXPECTED_TARGET_MATCHES,
            "target_2025_team_count": after["seasons"][TARGET_SEASON]["team_count"],
            "target_2025_network": after["seasons"][TARGET_SEASON]["network"],
            "authoritative_2025_2026_network": _network_summary([
                record
                for record in final_records
                if record.get("competition_id") == COMPETITION_ID
                and record.get("season_id") in {TARGET_SEASON_ID, CURRENT_SEASON_ID}
            ]),
        },
        "write": write_meta,
        "sample_output": str(sample_output) if sample_output else None,
        "audit_output": str(audit_output) if audit_output else None,
    }
    if sample_output:
        _write_json(sample_output, sample)
    if audit_output:
        _write_json(audit_output, audit)
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_path", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-identity", type=Path, default=DEFAULT_BASE_IDENTITY)
    parser.add_argument("--identity-supplement", type=Path, default=DEFAULT_IDENTITY_SUPPLEMENT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--secondary-raw-path", type=Path)
    parser.add_argument("--secondary-manifest", type=Path, default=DEFAULT_OPENFOOTBALL_MANIFEST)
    parser.add_argument("--secondary-identity", type=Path, default=DEFAULT_OPENFOOTBALL_IDENTITY)
    parser.add_argument("--write-authoritative", action="store_true")
    parser.add_argument("--backup-path", type=Path)
    parser.add_argument("--sample-output", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args(argv)
    try:
        result = run_closure(
            args.raw_path,
            manifest_path=args.manifest,
            base_identity_path=args.base_identity,
            identity_supplement_path=args.identity_supplement,
            db_path=args.db_path,
            secondary_raw_path=args.secondary_raw_path,
            secondary_manifest_path=args.secondary_manifest,
            secondary_identity_path=args.secondary_identity,
            write_authoritative=args.write_authoritative,
            backup_path=args.backup_path,
            sample_output=args.sample_output,
            audit_output=args.audit_output,
        )
    except (ClosureError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
