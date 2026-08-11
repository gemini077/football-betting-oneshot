"""Competition-season sanity checks for the research-only historical cohort.

This module does not rewrite the historical ledger.  It compares the ledger
with reviewed source manifests, flags source-observation identity splits, and
provides a conservative filter for research cohort construction.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .historical_results import deduplicate_historical_results


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def competition_season_key(competition_id: Any, season_id: Any) -> str:
    return f"{_text(competition_id) or 'unknown'}|{_text(season_id) or 'unknown'}"


def _canonical_competition_id(entry: Mapping[str, Any]) -> str | None:
    value = _text(entry.get("competition_id") or entry.get("canonical_competition_id"))
    if value:
        return value if value.startswith("competition:") else f"competition:{value}"
    value = _text(entry.get("competition_key"))
    if not value:
        return None
    return value if value.startswith("competition:") else f"competition:{value}"


def _canonical_season_id(entry: Mapping[str, Any], competition_id: str | None) -> str | None:
    value = _text(entry.get("season_id") or entry.get("canonical_season_id"))
    if value:
        return value if value.startswith("season:") else f"season:{value}"
    provider_season = _text(entry.get("provider_season_id"))
    if not provider_season or not competition_id:
        return None
    competition_key = competition_id.removeprefix("competition:")
    return f"season:{competition_key}:{provider_season}"


def _source_entry(
    entry: Mapping[str, Any],
    manifest_path: str,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    defaults = defaults or {}

    def value(*names: str) -> Any:
        for name in names:
            if entry.get(name) is not None:
                return entry.get(name)
            if defaults.get(name) is not None:
                return defaults.get(name)
        return None

    competition_id = _canonical_competition_id(entry)
    season_id = _canonical_season_id(entry, competition_id)
    provider = _text(value("provider"))
    source_file = _text(value("source_file"))
    if not competition_id or not season_id or not provider:
        return None
    return {
        "provider": provider,
        "source_file": source_file,
        "competition_id": competition_id,
        "season_id": season_id,
        "provider_competition_id": _text(value("provider_competition_id")),
        "provider_season_id": _text(value("provider_season_id")),
        "provider_season_name": _text(value("provider_season_name")),
        "listed_match_count": int(value("listed_match_count") or 0),
        "parsed_result_count": int(value("parsed_result_count") or 0),
        "source_completeness_status": _text(value("source_completeness_status")) or "UNKNOWN",
        "result_coverage": _text(value("result_coverage")) or "UNKNOWN",
        "raw_sha256": _text(value("raw_sha256")),
        "source_url": _text(value("source_url", "source_url_template")),
        "license": _text(value("license")),
        "commercial_use_review": _text(value("commercial_use_review")),
        "manifest_path": manifest_path,
    }


def load_source_manifest_entries(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load and de-duplicate source-slice entries from compact manifests."""

    entries: dict[tuple[str, ...], dict[str, Any]] = {}
    for path_value in paths:
        path = Path(path_value)
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        try:
            manifest_ref = path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            manifest_ref = path.name
        candidates = document.get("sources") if isinstance(document, Mapping) else None
        if not isinstance(candidates, list):
            candidates = [document]
        defaults = {key: value for key, value in document.items() if key != "sources"} if isinstance(document, Mapping) else {}
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            normalized = _source_entry(candidate, manifest_ref, defaults=defaults)
            if not normalized:
                continue
            key = tuple(
                str(normalized.get(name) or "")
                for name in ("provider", "source_file", "competition_id", "season_id", "raw_sha256", "provider_season_id")
            )
            entries[key] = normalized
    return sorted(
        entries.values(),
        key=lambda row: (row["competition_id"], row["season_id"], row["provider"], row.get("source_file") or ""),
    )


def _source_observation_key(provider: Any, provider_match_id: Any, source_record_ref: Any) -> str | None:
    provider_text = _text(provider)
    match_text = _text(provider_match_id)
    ref_text = _text(source_record_ref)
    if not provider_text or not (match_text or ref_text):
        return None
    return f"{provider_text}|{match_text or ''}|{ref_text or ''}"


def _row_source_ref(row: Mapping[str, Any]) -> str | None:
    return _text(row.get("source_record_ref")) or _text((row.get("provenance") or {}).get("source_record_ref"))


def _normalized_name(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    normalized = re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)
    return normalized or None


def audit_source_observation_duplicates(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Find one source observation represented by multiple canonical records."""

    records = list(records)
    observations: dict[str, set[str]] = defaultdict(set)
    metadata: dict[str, dict[str, Any]] = {}
    for row in records:
        canonical_id = _text(row.get("canonical_match_id"))
        if not canonical_id:
            continue
        confirmations = list(row.get("source_confirmations") or [])
        confirmations.append(
            {
                "provider": row.get("provider"),
                "provider_match_id": row.get("provider_match_id"),
                "source_record_ref": _row_source_ref(row),
            }
        )
        for confirmation in confirmations:
            if not isinstance(confirmation, Mapping):
                continue
            key = _source_observation_key(
                confirmation.get("provider"),
                confirmation.get("provider_match_id"),
                confirmation.get("source_record_ref"),
            )
            if not key:
                continue
            observations[key].add(canonical_id)
            item = metadata.setdefault(
                key,
                {
                    "observation_key": key,
                    "provider": _text(confirmation.get("provider")),
                    "provider_match_ids": set(),
                    "source_record_refs": set(),
                    "canonical_match_ids": set(),
                    "raw_team_names": set(),
                    "kickoffs": set(),
                    "scores": set(),
                    "competition_season_keys": set(),
                },
            )
            if _text(confirmation.get("provider_match_id")):
                item["provider_match_ids"].add(_text(confirmation.get("provider_match_id")))
            if _text(confirmation.get("source_record_ref")):
                item["source_record_refs"].add(_text(confirmation.get("source_record_ref")))
            item["canonical_match_ids"].add(canonical_id)
            item["raw_team_names"].update(
                name for name in (row.get("raw_home_team"), row.get("raw_away_team")) if _text(name)
            )
            if _text(row.get("kickoff_at")):
                item["kickoffs"].add(_text(row.get("kickoff_at")))
            item["scores"].add(f"{row.get('home_goals')}:{row.get('away_goals')}")
            item["competition_season_keys"].add(competition_season_key(row.get("competition_id"), row.get("season_id")))

    groups: list[dict[str, Any]] = []
    canonical_ids_by_key: dict[str, set[str]] = {}
    for key, canonical_ids in observations.items():
        if len(canonical_ids) <= 1:
            continue
        canonical_ids_by_key[key] = canonical_ids
        item = metadata[key]
        groups.append(
            {
                "observation_key": key,
                "detection_method": "same_source_observation",
                "provider": item["provider"],
                "provider_match_ids": sorted(item["provider_match_ids"]),
                "source_record_refs": sorted(item["source_record_refs"]),
                "canonical_match_ids": sorted(canonical_ids),
                "raw_team_names": sorted(item["raw_team_names"]),
                "kickoffs": sorted(item["kickoffs"]),
                "scores": sorted(item["scores"]),
                "competition_season_keys": sorted(item["competition_season_keys"]),
            }
        )

    # A source reference is the strongest signal, but a conservative exact
    # ledger-key audit catches identity splits where two adapters lost the
    # shared reference.  No time window is widened here: source timezone
    # rules must be supplied before a timestamp can be normalized.
    exact_keys: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        canonical_id = _text(row.get("canonical_match_id"))
        kickoff = _text(row.get("kickoff_at"))
        competition = _text(row.get("competition_id"))
        season = _text(row.get("season_id"))
        if not canonical_id or not kickoff or not competition or not season:
            continue
        exact_key = f"{competition}|{season}|{kickoff}|{row.get('home_goals')}:{row.get('away_goals')}"
        exact_keys[exact_key].append(row)
    known_canonical_sets = {frozenset(group["canonical_match_ids"]) for group in groups}
    for exact_key, rows in exact_keys.items():
        canonical_ids = sorted({_text(row.get("canonical_match_id")) for row in rows if _text(row.get("canonical_match_id"))})
        if len(canonical_ids) <= 1 or frozenset(canonical_ids) in known_canonical_sets:
            continue
        # Same kickoff and score alone is not enough: many real fixtures
        # share a matchday kickoff and score.  Require exact normalized
        # source-name overlap as an independent team-identity signal.
        row_name_sets = [
            {
                normalized
                for normalized in (_normalized_name(row.get("raw_home_team")), _normalized_name(row.get("raw_away_team")))
                if normalized
            }
            for row in rows
        ]
        shared_names = {
            name
            for index, names in enumerate(row_name_sets)
            for other_names in row_name_sets[index + 1 :]
            for name in names & other_names
        }
        if not shared_names:
            continue
        groups.append(
            {
                "observation_key": f"ledger_exact_key|{exact_key}",
                "detection_method": "same_competition_season_kickoff_score",
                "provider": None,
                "provider_match_ids": sorted({_text(row.get("provider_match_id")) for row in rows if _text(row.get("provider_match_id"))}),
                "source_record_refs": sorted({_row_source_ref(row) for row in rows if _row_source_ref(row)}),
                "canonical_match_ids": canonical_ids,
                "raw_team_names": sorted({
                    _text(name)
                    for row in rows
                    for name in (row.get("raw_home_team"), row.get("raw_away_team"))
                    if _text(name)
                }),
                "kickoffs": sorted({_text(row.get("kickoff_at")) for row in rows if _text(row.get("kickoff_at"))}),
                "scores": sorted({f"{row.get('home_goals')}:{row.get('away_goals')}" for row in rows}),
                "shared_normalized_source_names": sorted(shared_names),
                "competition_season_keys": sorted({
                    competition_season_key(row.get("competition_id"), row.get("season_id")) for row in rows
                }),
            }
        )
        known_canonical_sets.add(frozenset(canonical_ids))
        canonical_ids_by_key[f"ledger_exact_key|{exact_key}"] = set(canonical_ids)
    groups.sort(key=lambda row: row["observation_key"])
    affected = {canonical_id for group in groups for canonical_id in group["canonical_match_ids"]}
    unique_observation_counts = Counter(key.split("|", 1)[0] for key in observations)
    source_groups = sum(group.get("detection_method") == "same_source_observation" for group in groups)
    exact_groups = sum(group.get("detection_method") == "same_competition_season_kickoff_score" for group in groups)
    return {
        "possible_identity_split_duplicate_count": len(groups),
        "source_observation_identity_split_duplicate_count": source_groups,
        "exact_ledger_key_identity_split_duplicate_count": exact_groups,
        "affected_canonical_record_count": len(affected),
        "unique_source_observation_counts": dict(sorted(unique_observation_counts.items())),
        "merge_action": "exclude_until_review" if groups else "none",
        "groups": sorted(groups, key=lambda row: row["observation_key"]),
        "canonical_ids_by_observation": {
            key: sorted(value) for key, value in sorted(canonical_ids_by_key.items())
        },
    }


def _slice_duplicate_audit(duplicate_audit: Mapping[str, Any], slice_key: str) -> dict[str, Any]:
    groups = [
        group
        for group in duplicate_audit.get("groups", [])
        if slice_key in set(group.get("competition_season_keys") or [])
    ]
    canonical_ids = {match_id for group in groups for match_id in group.get("canonical_match_ids", [])}
    return {
        "possible_identity_split_duplicate_count": len(groups),
        "source_observation_identity_split_duplicate_count": sum(
            group.get("detection_method") == "same_source_observation" for group in groups
        ),
        "exact_ledger_key_identity_split_duplicate_count": sum(
            group.get("detection_method") == "same_competition_season_kickoff_score" for group in groups
        ),
        "affected_canonical_record_count": len(canonical_ids),
        "merge_action": "exclude_until_review" if groups else "none",
        "groups": groups,
    }


def _record_evidence(row: Mapping[str, Any], duplicate_keys: Iterable[str]) -> dict[str, Any]:
    provenance = row.get("provenance") or {}
    return {
        "provider": row.get("provider"),
        "source_record_ref": _row_source_ref(row),
        "canonical_match_id": row.get("canonical_match_id"),
        "kickoff_at": row.get("kickoff_at"),
        "home_team_id": row.get("home_team_id"),
        "away_team_id": row.get("away_team_id"),
        "raw_home_team": row.get("raw_home_team"),
        "raw_away_team": row.get("raw_away_team"),
        "home_goals": row.get("home_goals"),
        "away_goals": row.get("away_goals"),
        "season_id": row.get("season_id"),
        "competition_id": row.get("competition_id"),
        "provider_season_id": row.get("provider_season_id") or provenance.get("provider_season_id"),
        "provider_season_name": row.get("provider_season_name") or provenance.get("provider_season_name"),
        "source_file": row.get("source_file") or provenance.get("source_file"),
        "provider_match_id": row.get("provider_match_id"),
        "resolution_method": row.get("resolution_method"),
        "legacy_migration_provenance": row.get("legacy_migration_provenance") or provenance.get("legacy_migration_provenance"),
        "possible_identity_split_duplicate": bool(list(duplicate_keys)),
        "duplicate_observation_keys": sorted(set(duplicate_keys)),
    }


def audit_competition_season_sanity(
    historical_records: Iterable[Mapping[str, Any]],
    source_manifests: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit ledger population against source completeness without merging rows."""

    records = list(deduplicate_historical_results(historical_records).records)
    source_entries = [dict(entry) for entry in source_manifests]
    source_by_slice: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in source_entries:
        source_by_slice[competition_season_key(entry.get("competition_id"), entry.get("season_id"))].append(entry)
    records_by_slice: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        records_by_slice[competition_season_key(row.get("competition_id"), row.get("season_id"))].append(row)

    duplicate_audit = audit_source_observation_duplicates(records)
    duplicate_keys_by_canonical: dict[str, list[str]] = defaultdict(list)
    for key, canonical_ids in duplicate_audit.get("canonical_ids_by_observation", {}).items():
        for canonical_id in canonical_ids:
            duplicate_keys_by_canonical[canonical_id].append(key)

    slices: dict[str, dict[str, Any]] = {}
    all_keys = sorted(set(records_by_slice) | set(source_by_slice))
    for slice_key in all_keys:
        rows = sorted(records_by_slice.get(slice_key, []), key=lambda row: str(row.get("canonical_match_id") or ""))
        entries = source_by_slice.get(slice_key, [])
        complete_entries = [
            entry for entry in entries if str(entry.get("source_completeness_status", "")).upper() == "COMPLETE"
        ]
        complete_counts = sorted({int(entry.get("parsed_result_count") or 0) for entry in complete_entries})
        known_complete_count = max(complete_counts) if complete_counts else None
        duplicate_slice = _slice_duplicate_audit(duplicate_audit, slice_key)
        ledger_count = len({str(row.get("canonical_match_id")) for row in rows if row.get("canonical_match_id")})
        reasons: list[str] = []
        if known_complete_count is not None and ledger_count > known_complete_count:
            reasons.append("ledger_exceeds_known_complete_source")
        if len(complete_counts) > 1:
            reasons.append("complete_source_counts_disagree")
        if duplicate_slice["possible_identity_split_duplicate_count"]:
            reasons.append("possible_identity_split_duplicate")
        if not entries:
            reasons.append("source_manifest_missing")

        if any(reason in reasons for reason in ("ledger_exceeds_known_complete_source", "complete_source_counts_disagree", "possible_identity_split_duplicate")):
            status = "FAIL"
        elif not entries:
            status = "UNKNOWN"
        else:
            status = "PASS"

        if status == "FAIL":
            population_scope = "UNKNOWN"
            generalization_scope = "excluded: dataset sanity failure"
        elif complete_entries and known_complete_count is not None and ledger_count == known_complete_count:
            population_scope = "COMPLETE_COMPETITION_SEASON"
            generalization_scope = "complete known source population"
        elif complete_entries:
            population_scope = "IDENTITY_MAPPED_SUBSET"
            generalization_scope = "observed identity-mapped subset only"
        elif entries:
            population_scope = "SOURCE_PARTIAL_SUBSET"
            generalization_scope = "observed identity-mapped subset only"
        else:
            population_scope = "UNKNOWN"
            generalization_scope = "unknown"

        duplicate_keys = [
            key
            for key, canonical_ids in duplicate_audit.get("canonical_ids_by_observation", {}).items()
            if any(str(row.get("canonical_match_id")) in canonical_ids for row in rows)
        ]
        record_evidence = [_record_evidence(row, duplicate_keys_by_canonical.get(str(row.get("canonical_match_id")), [])) for row in rows]
        source_listed_by_provider = Counter()
        source_parsed_by_provider = Counter()
        for entry in entries:
            source_listed_by_provider[str(entry["provider"])] += int(entry.get("listed_match_count") or 0)
            source_parsed_by_provider[str(entry["provider"])] += int(entry.get("parsed_result_count") or 0)
        slices[slice_key] = {
            "competition_id": slice_key.split("|", 1)[0],
            "season_id": slice_key.split("|", 1)[1],
            "ledger_fixture_count": ledger_count,
            "ledger_unique_team_count": len({team_id for row in rows for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id}),
            "ledger_provider_counts": dict(sorted(Counter(str(row.get("provider") or "unknown") for row in rows).items())),
            "source_providers": sorted({str(entry["provider"]) for entry in entries}),
            "source_listed_fixture_count": sum(int(entry.get("listed_match_count") or 0) for entry in entries),
            "source_parsed_fixture_count": sum(int(entry.get("parsed_result_count") or 0) for entry in entries),
            "source_listed_by_provider": dict(sorted(source_listed_by_provider.items())),
            "source_parsed_by_provider": dict(sorted(source_parsed_by_provider.items())),
            "source_entries": entries,
            "known_complete_source_fixture_count": known_complete_count,
            "complete_source_fixture_counts": complete_counts,
            "ledger_vs_complete_source_ratio": round(ledger_count / known_complete_count, 6) if known_complete_count else None,
            "source_count_sum_is_not_capacity": True,
            "source_completeness_statuses": sorted({str(entry.get("source_completeness_status")) for entry in entries}),
            "research_population_scope": population_scope,
            "generalization_scope": generalization_scope,
            "sanity_status": status,
            "sanity_reasons": reasons,
            "excluded_from_research": status == "FAIL",
            "research_eligible": status != "FAIL",
            "duplicate_audit": duplicate_slice,
            "record_evidence": record_evidence,
        }

    failed = [key for key, row in slices.items() if row["sanity_status"] == "FAIL"]
    return {
        "contract_version": "competition_season_research_sanity.v1",
        "ledger_record_count": len(records),
        "slice_count": len(slices),
        "failed_slice_count": len(failed),
        "failed_slices": failed,
        "duplicate_audit": duplicate_audit,
        "slices": slices,
    }


def filter_records_by_sanity(
    historical_records: Iterable[Mapping[str, Any]],
    sanity_report: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Keep records whose competition-season slice is not a sanity failure."""

    slices = sanity_report.get("slices") or {}
    return [
        row
        for row in historical_records
        if not (slices.get(competition_season_key(row.get("competition_id"), row.get("season_id")), {}).get("excluded_from_research") is True)
    ]


def compact_sanity_report(sanity_report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove per-record and full duplicate-group evidence for Git-tracked output."""

    compact_slices: dict[str, Any] = {}
    for key, row in (sanity_report.get("slices") or {}).items():
        compact_row = {name: value for name, value in row.items() if name not in {"record_evidence"}}
        duplicate = dict(compact_row.get("duplicate_audit") or {})
        groups = list(duplicate.pop("groups", []) or [])
        duplicate["group_count"] = len(groups)
        duplicate["sample_groups"] = groups[:3]
        compact_row["duplicate_audit"] = duplicate
        compact_slices[key] = compact_row
    compact_duplicate = dict(sanity_report.get("duplicate_audit") or {})
    groups = list(compact_duplicate.pop("groups", []) or [])
    compact_duplicate["group_count"] = len(groups)
    compact_duplicate["sample_groups"] = groups[:3]
    compact_duplicate.pop("canonical_ids_by_observation", None)
    return {
        "contract_version": sanity_report.get("contract_version"),
        "ledger_record_count": sanity_report.get("ledger_record_count"),
        "slice_count": sanity_report.get("slice_count"),
        "failed_slice_count": sanity_report.get("failed_slice_count"),
        "failed_slices": list(sanity_report.get("failed_slices") or []),
        "duplicate_audit": compact_duplicate,
        "slices": compact_slices,
    }


__all__ = [
    "audit_competition_season_sanity",
    "audit_source_observation_duplicates",
    "compact_sanity_report",
    "competition_season_key",
    "filter_records_by_sanity",
    "load_source_manifest_entries",
]
