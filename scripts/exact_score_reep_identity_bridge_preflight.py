#!/usr/bin/env python3
"""Run a bounded, future-only Reep v1 identity bridge preflight for exact-score evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:  # Direct script execution and package-style imports both work.
    from match_identity import canonical_match_id
    from postmatch_queue import parse_datetime
except ImportError:  # pragma: no cover - package runners use this branch.
    from scripts.match_identity import canonical_match_id
    from scripts.postmatch_queue import parse_datetime


MILESTONE = "EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1"
SCHEMA_VERSION = "exact_score_reep_identity_bridge_preflight_1.v1"
BASELINE_PR179_CANDIDATE_COUNT = 60
PROVIDER_NAME = "the-odds-api.com"
PROVIDER_SITE = "https://the-odds-api.com/"
API_HOST = "https://api.the-odds-api.com"
API_KEY_ENV = "THE_ODDS_API_KEY"
CORRECT_SCORE_MARKET = "correct_score"
PROBE_REGION = "eu"
MAX_CREDITS = 100
KICKOFF_TOLERANCE_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 30
REEP_HOST = "data.reep.football"
REEP_LATEST_URL = "https://data.reep.football/releases/latest.json"
REEP_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
SHANGHAI = ZoneInfo("Asia/Shanghai")

VALID_IDENTITY_STATUSES = {
    "EXACT_MATCH",
    "NO_PROVIDER_SPORT_MAPPING",
    "NO_EVENT_MATCH",
    "IDENTITY_AMBIGUOUS_FAIL_CLOSED",
}
VALID_REEP_RESOLUTION_STATUSES = {
    "UNIQUE_EXACT_REEP_ID",
    "NO_REEP_MATCH",
    "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED",
}
VALID_DECISIONS = {
    "REEP_IDENTITY_AND_CORRECT_SCORE_PILOT_READY",
    "REEP_IDENTITY_BRIDGE_USEFUL_COVERAGE_NOT_ENOUGH",
    "REEP_IDENTITY_COVERAGE_INSUFFICIENT",
    "REEP_BOUNDED_ACCESS_NOT_READY",
    "FAIL_CLOSED",
}
READ_ONLY_CONTROLS = {
    "read_only_preflight": True,
    "result_network_fetch": False,
    "historical_backfill": False,
    "manual_identity_assignment": False,
    "fuzzy_matching": False,
    "translation_or_transliteration": False,
    "frozen_prediction_modified": False,
    "authoritative_result_modified": False,
    "champion_modified": False,
    "challenger_modified": False,
    "model_modified": False,
    "serving_modified": False,
    "promotion_attempted": False,
    "paid_upgrade_attempted": False,
    "raw_feed_published": False,
}
_SCORE_LABEL = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")
_USAGE_HEADERS = ("x-requests-used", "x-requests-remaining", "x-requests-last")
_REEP_REQUIRED_FILES = (
    "csv/teams.csv.gz",
    "csv/aliases.csv.gz",
    "csv/competitions.csv.gz",
    "csv/redirects.csv.gz",
)
_REEP_METADATA_FILES = ("LICENSE.txt", "schema.json", "checksums.txt")


class PreflightError(RuntimeError):
    """A trustworthy preflight cannot be completed."""


class CredentialRequired(PreflightError):
    """The required Actions secret is absent."""


class ProviderRequestError(PreflightError):
    """The provider request failed without retaining secret-bearing details."""


class BoundedAccessNotReady(PreflightError):
    """The official Reep surface does not expose the required bounded CSV files."""


Transport = Callable[[str, Mapping[str, str]], tuple[Any, Mapping[str, Any]]]


def _parse_instant(value: Any, label: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise PreflightError(f"{label} is missing or invalid")
    return parsed.astimezone(timezone.utc)


def _snapshot(value: Any | None) -> datetime:
    return _parse_instant(value, "snapshot_at") if value is not None else datetime.now(timezone.utc)


def _fixture_kickoff(fixture: Mapping[str, Any]) -> datetime:
    raw_kickoff = fixture.get("kickoff_at") or fixture.get("kickoff")
    if raw_kickoff:
        return _parse_instant(raw_kickoff, "fixture kickoff")
    date_text = str(fixture.get("matchDate") or fixture.get("match_date") or "").strip()
    time_text = str(fixture.get("matchTime") or fixture.get("match_time") or "").strip()[:5]
    if not date_text or not time_text:
        raise PreflightError("canonical fixture has no kickoff date/time")
    try:
        local = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise PreflightError("canonical fixture kickoff date/time is invalid") from error
    return local.replace(tzinfo=SHANGHAI).astimezone(timezone.utc)


def _fixture_identity(fixture: Mapping[str, Any]) -> tuple[str, str, str, str, datetime]:
    match_id = str(fixture.get("matchId") or fixture.get("match_id") or "").strip()
    home = str(fixture.get("homeTeam") or fixture.get("home_team") or fixture.get("home") or "").strip()
    away = str(fixture.get("awayTeam") or fixture.get("away_team") or fixture.get("away") or "").strip()
    competition = str(fixture.get("league") or fixture.get("competition") or "").strip()
    if not match_id or not home or not away or not competition:
        raise PreflightError("canonical fixture is missing match id, teams, or competition")
    return match_id, home, away, competition, _fixture_kickoff(fixture)


def _candidate_from_fixture(fixture: Mapping[str, Any], *, source_file: str) -> dict[str, Any]:
    match_id, home, away, competition, kickoff = _fixture_identity(fixture)
    match_key = canonical_match_id({"home": home, "away": away, "kickoff": kickoff.isoformat()})
    return {
        "match_id": match_id,
        "fbos_match_id": match_id,
        "match_key": match_key,
        "kickoff": kickoff.isoformat(),
        "home": home,
        "away": away,
        "home_team_en": str(fixture.get("homeTeamEn") or fixture.get("home_team_en") or "").strip() or None,
        "away_team_en": str(fixture.get("awayTeamEn") or fixture.get("away_team_en") or "").strip() or None,
        "competition": competition,
        "competition_source": "canonical_prediction_universe.league",
        "source_files": [source_file],
    }


def build_candidate_cohort(documents: Iterable[Mapping[str, Any]], *, snapshot_at: Any) -> dict[str, Any]:
    """Build one future candidate per canonical fixture without mutating source documents."""

    snapshot = _snapshot(snapshot_at)
    by_match_id: dict[str, dict[str, Any]] = {}
    raw_future_rows = 0
    past_or_due_rows = 0
    document_count = 0
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            continue
        document_count += 1
        source_file = str(document.get("_source_file") or f"document-{index}")
        if str(document.get("status") or "").strip() not in {"READY", "EMPTY_CONFIRMED"}:
            continue
        fixtures = document.get("fixtures") or []
        if not isinstance(fixtures, list):
            raise PreflightError("canonical prediction-universe fixtures are not a list")
        for fixture in fixtures:
            if not isinstance(fixture, Mapping):
                raise PreflightError("canonical prediction-universe contains a malformed fixture")
            candidate = _candidate_from_fixture(fixture, source_file=source_file)
            if _parse_instant(candidate["kickoff"], "candidate kickoff") <= snapshot:
                past_or_due_rows += 1
                continue
            raw_future_rows += 1
            existing = by_match_id.get(candidate["match_id"])
            if existing is not None:
                fields = ("match_key", "kickoff", "home", "away", "competition")
                if any(existing[field] != candidate[field] for field in fields):
                    raise PreflightError(
                        f"canonical match id has conflicting future identities: {candidate['match_id']}"
                    )
                existing["source_files"] = sorted(set(existing["source_files"] + candidate["source_files"]))
                continue
            by_match_id[candidate["match_id"]] = candidate

    candidates = sorted(
        by_match_id.values(),
        key=lambda row: (row["kickoff"], row["match_key"], row["match_id"]),
    )
    by_key: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        by_key[candidate["match_key"]].append(candidate["match_id"])
    collisions = {key: ids for key, ids in by_key.items() if len(ids) > 1}
    if collisions:
        raise PreflightError("distinct canonical ids collide on one FBOS match key")
    unique_team_names = sorted({name for row in candidates for name in (row["home"], row["away"])})
    return {
        "snapshot_at": snapshot.isoformat(),
        "candidate_count": len(candidates),
        "raw_future_candidate_rows": raw_future_rows,
        "deduplicated_match_count": raw_future_rows - len(candidates),
        "past_or_due_fixture_count": past_or_due_rows,
        "universe_document_count": document_count,
        "unique_fbos_team_names": unique_team_names,
        "competition_labels": sorted({row["competition"] for row in candidates}),
        "baseline_pr179_candidate_count": BASELINE_PR179_CANDIDATE_COUNT,
        "current_main_delta": len(candidates) - BASELINE_PR179_CANDIDATE_COUNT,
        "candidates": candidates,
    }


def load_candidate_cohort(universe_root: Path, *, snapshot_at: Any) -> dict[str, Any]:
    root = Path(universe_root)
    documents: list[dict[str, Any]] = []
    files = sorted(root.glob("*.json"))
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PreflightError(f"cannot read canonical universe snapshot: {path.name}") from error
        if isinstance(document, Mapping):
            documents.append({**document, "_source_file": path.name})
    cohort = build_candidate_cohort(documents, snapshot_at=snapshot_at)
    cohort["universe_files_scanned"] = len(files)
    return cohort


def _name_key(value: Any) -> str:
    """Normalize only Unicode width/case and punctuation; never similarity or translation."""

    import unicodedata

    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(character for character in text if character.isalnum())


def _rank_value(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 999999


def _redirect_resolver(rows: Iterable[Mapping[str, Any]]) -> Callable[[str], str | None]:
    redirects = {
        str(row.get("from_id") or "").strip(): str(row.get("to_id") or "").strip()
        for row in rows
        if isinstance(row, Mapping) and str(row.get("from_id") or "").strip()
    }

    def resolve(value: str) -> str | None:
        current = value
        visited: set[str] = set()
        while current in redirects:
            if current in visited:
                return None
            visited.add(current)
            current = redirects[current]
            if not current:
                return None
        return current or None

    return resolve


def _add_index(index: dict[str, list[dict[str, Any]]], key: str, record: dict[str, Any]) -> None:
    if not key:
        return
    # Duplicate CSV rows do not change the set of candidate Reep IDs. Avoid a
    # quadratic list-membership check for common aliases such as "FC".
    index.setdefault(key, []).append(record)


def _base_resolution(*, input_name: str, status: str, candidate_ids: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "input_name": input_name,
        "reep_id": None,
        "matched_label_or_alias": None,
        "alias_kind": None,
        "language": None,
        "matching_surface": None,
        "existing_alias_evidence": None,
        "resolution_status": status,
        "candidate_reep_ids": sorted(set(candidate_ids)),
    }


class ReepIdentityRegister:
    """In-memory exact lookup over bounded public Reep v1 CSV surfaces."""

    def __init__(
        self,
        *,
        team_index: Mapping[str, list[dict[str, Any]]],
        competition_index: Mapping[str, list[dict[str, Any]]],
        existing_index: Mapping[str, list[dict[str, Any]]],
        team_labels: Mapping[str, str],
        redirect_map: Mapping[str, str | None],
    ) -> None:
        self._team_index = {key: list(value) for key, value in team_index.items()}
        self._competition_index = {key: list(value) for key, value in competition_index.items()}
        self._existing_index = {key: list(value) for key, value in existing_index.items()}
        self.team_labels = dict(team_labels)
        self.redirect_map = dict(redirect_map)

    @classmethod
    def from_rows(
        cls,
        *,
        team_rows: Iterable[Mapping[str, Any]],
        alias_rows: Iterable[Mapping[str, Any]] = (),
        competition_rows: Iterable[Mapping[str, Any]] = (),
        redirect_rows: Iterable[Mapping[str, Any]] = (),
        existing_alias_rows: Iterable[Mapping[str, Any]] = (),
    ) -> "ReepIdentityRegister":
        team_rows = [dict(row) for row in team_rows if isinstance(row, Mapping)]
        competition_rows = [dict(row) for row in competition_rows if isinstance(row, Mapping)]
        alias_rows = [dict(row) for row in alias_rows if isinstance(row, Mapping)]
        redirect_rows = [dict(row) for row in redirect_rows if isinstance(row, Mapping)]
        resolve_redirect = _redirect_resolver(redirect_rows)
        raw_team_ids = {str(row.get("reep_id") or "").strip() for row in team_rows}
        raw_team_ids.discard("")
        raw_competition_ids = {str(row.get("reep_id") or "").strip() for row in competition_rows}
        raw_competition_ids.discard("")
        team_ids = {resolve_redirect(value) or value for value in raw_team_ids}
        competition_ids = {resolve_redirect(value) or value for value in raw_competition_ids}
        team_index: dict[str, list[dict[str, Any]]] = {}
        competition_index: dict[str, list[dict[str, Any]]] = {}
        existing_index: dict[str, list[dict[str, Any]]] = {}
        team_labels: dict[str, str] = {}
        redirect_map: dict[str, str | None] = {}
        for row in redirect_rows:
            source = str(row.get("from_id") or "").strip()
            if source:
                redirect_map[source] = resolve_redirect(source)

        for row in team_rows:
            raw_id = str(row.get("reep_id") or "").strip()
            label = str(row.get("label") or "").strip()
            target = resolve_redirect(raw_id)
            if not raw_id or not target or target not in team_ids or not label:
                continue
            if row.get("status") == "active" or target not in team_labels:
                team_labels[target] = label
            _add_index(team_index, _name_key(label), {
                "reep_id": target,
                "matched_label_or_alias": label,
                "alias_kind": "canonical_label",
                "language": None,
                "matching_surface": "reep_v1_canonical_label",
                "rank": 0,
            })

        for row in competition_rows:
            raw_id = str(row.get("reep_id") or "").strip()
            label = str(row.get("label") or "").strip()
            target = resolve_redirect(raw_id)
            if not raw_id or not target or target not in competition_ids or not label:
                continue
            _add_index(competition_index, _name_key(label), {
                "reep_id": target,
                "matched_label_or_alias": label,
                "alias_kind": "canonical_label",
                "language": None,
                "matching_surface": "reep_v1_competition_label",
                "rank": 0,
            })

        for row in alias_rows:
            raw_id = str(row.get("reep_id") or "").strip()
            alias = str(row.get("alias") or "").strip()
            target = resolve_redirect(raw_id)
            if not raw_id or not target or not alias:
                continue
            record = {
                "reep_id": target,
                "matched_label_or_alias": alias,
                "alias_kind": str(row.get("kind") or "").strip() or None,
                "language": str(row.get("language") or "").strip() or None,
                "matching_surface": "reep_v1_typed_alias",
                "rank": _rank_value(row.get("rank")),
            }
            if target in team_ids:
                _add_index(team_index, _name_key(alias), record)
            if target in competition_ids:
                _add_index(competition_index, _name_key(alias), record)

        direct_names_by_existing_row: list[tuple[Mapping[str, Any], list[str]]] = []
        for row in existing_alias_rows:
            canonical = str(row.get("canonical") or "").strip()
            aliases = [str(value).strip() for value in (row.get("aliases") or []) if str(value).strip()]
            surfaces = [canonical, *aliases]
            ids: set[str] = set()
            for surface in surfaces:
                ids.update(record["reep_id"] for record in team_index.get(_name_key(surface), []))
            if len(ids) == 1:
                direct_names_by_existing_row.append((row, sorted(ids)))
        for row, ids in direct_names_by_existing_row:
            evidence = row.get("evidence")
            for surface in [str(row.get("canonical") or "").strip(), *[str(value).strip() for value in (row.get("aliases") or [])]]:
                key = _name_key(surface)
                if not key:
                    continue
                _add_index(existing_index, key, {
                    "reep_id": ids[0],
                    "matched_label_or_alias": surface,
                    "alias_kind": "existing-confirmed-alias",
                    "language": None,
                    "matching_surface": "existing_data_team_aliases",
                    "existing_alias_evidence": evidence,
                    "rank": 0,
                })

        return cls(
            team_index=team_index,
            competition_index=competition_index,
            existing_index=existing_index,
            team_labels=team_labels,
            redirect_map=redirect_map,
        )

    @staticmethod
    def _choose(records: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
        rows = list(records)
        if not rows:
            return None
        rows.sort(key=lambda row: (int(row.get("rank", 999999)), str(row.get("matching_surface") or ""), str(row.get("matched_label_or_alias") or "")))
        return dict(rows[0])

    def _resolve_index(self, name: Any, index: Mapping[str, list[dict[str, Any]]], *, existing: bool = False) -> dict[str, Any]:
        input_name = str(name or "").strip()
        key = _name_key(input_name)
        direct_records = list(index.get(key, []))
        existing_records = list(self._existing_index.get(key, [])) if existing else []
        all_records = direct_records + existing_records
        ids = sorted({str(record.get("reep_id") or "") for record in all_records if record.get("reep_id")})
        if len(ids) > 1:
            return _base_resolution(
                input_name=input_name,
                status="AMBIGUOUS_REEP_MATCH_FAIL_CLOSED",
                candidate_ids=ids,
            )
        if not ids:
            return _base_resolution(input_name=input_name, status="NO_REEP_MATCH")
        chosen = self._choose(direct_records or existing_records)
        if chosen is None:
            return _base_resolution(input_name=input_name, status="NO_REEP_MATCH")
        return {
            "input_name": input_name,
            "reep_id": ids[0],
            "matched_label_or_alias": chosen.get("matched_label_or_alias"),
            "alias_kind": chosen.get("alias_kind"),
            "language": chosen.get("language"),
            "matching_surface": chosen.get("matching_surface"),
            "existing_alias_evidence": chosen.get("existing_alias_evidence"),
            "resolution_status": "UNIQUE_EXACT_REEP_ID",
            "candidate_reep_ids": ids,
        }

    def resolve_team(self, name: Any) -> dict[str, Any]:
        return self._resolve_index(name, self._team_index, existing=True)

    def resolve_competition(self, name: Any) -> dict[str, Any]:
        return self._resolve_index(name, self._competition_index)


def load_existing_team_alias_rows(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path or ROOT / "data" / "team_aliases.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError("existing FBOS team alias register is unreadable") from error
    rows = payload.get("teams") if isinstance(payload, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_reep_url(value: Any, *, release_prefix: str | None = None) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != REEP_HOST or parsed.query or parsed.fragment:
        raise PreflightError("Reep URL is outside the official HTTPS release host")
    path = parsed.path or ""
    if not path.startswith("/releases/"):
        raise PreflightError("Reep URL is outside the official release prefix")
    if release_prefix and not path.startswith("/releases/" + release_prefix.strip("/") + "/"):
        raise PreflightError("Reep file URL is outside the pinned release")
    return url


def _download_reep_file(url: str, destination: Path) -> None:
    request = Request(
        url,
        headers={
            "Accept": "application/octet-stream, application/json, text/plain",
            "User-Agent": "FBOS-Reep-identity-bridge-preflight/1",
        },
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content = response.read()
    except HTTPError as error:
        raise PreflightError(f"official Reep download failed (HTTP {error.code})") from None
    except (URLError, TimeoutError, OSError):
        raise PreflightError("official Reep download failed (network error)") from None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"official Reep {label} is invalid") from error
    if not isinstance(value, Mapping):
        raise PreflightError(f"official Reep {label} is not an object")
    return dict(value)


def _checksum_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise PreflightError("official Reep checksum file is unreadable") from error
    checksums: dict[str, str] = {}
    for line in lines:
        text = line.strip()
        if not text:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+(.+)", text)
        if not match:
            raise PreflightError("official Reep checksum file has an invalid line")
        checksums[match.group(2).strip()] = match.group(1).lower()
    return checksums


def _schema_records(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    files = schema.get("files") if isinstance(schema, Mapping) else None
    if not isinstance(files, Mapping):
        raise PreflightError("official Reep schema has no files object")
    required_columns = {
        "csv/teams.csv.gz": ["reep_id", "status", "label", "gender", "country"],
        "csv/aliases.csv.gz": ["reep_id", "alias", "kind", "rank", "language"],
        "csv/competitions.csv.gz": ["reep_id", "status", "label", "gender", "country"],
        "csv/redirects.csv.gz": ["from_id", "to_id", "reason"],
    }
    result: dict[str, dict[str, Any]] = {}
    for name, columns in required_columns.items():
        record = files.get(name)
        if not isinstance(record, Mapping) or list(record.get("columns") or []) != columns:
            raise PreflightError(f"official Reep schema for {name} is incompatible")
        result[name] = {
            "schema": record.get("schema"),
            "columns": columns,
        }
    return result


def load_release_provenance(
    *,
    latest: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cache_dir: Path,
    local_files: Mapping[str, Path],
    checksums_path: Path,
    schema: Mapping[str, Any] | None = None,
    latest_pointer_sha256: str | None = None,
    release_manifest_sha256: str | None = None,
    license_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the pinned public release and return only auditable metadata."""

    if latest.get("schema_version") != "reep-public-release-latest-v1":
        raise PreflightError("official Reep latest pointer schema mismatch")
    if latest.get("release_tier") != "public_bridge_v1" or latest.get("release_schema_version") != "bridge-register-v1":
        raise PreflightError("official Reep latest pointer is not current public bridge v1")
    if manifest.get("schema_version") != "bridge-register-v1":
        raise PreflightError("official Reep manifest schema mismatch")
    if manifest.get("tier") != "public_bridge_v1" or manifest.get("projection_mode") != "public_bridge_v1":
        raise PreflightError("official Reep manifest is not the public bridge v1 tier")
    stamp = str(manifest.get("stamp") or latest.get("stamp") or "").strip()
    if not stamp or stamp != str(latest.get("stamp") or "").strip():
        raise PreflightError("official Reep release stamp is not pinned consistently")
    licence = manifest.get("licence") if isinstance(manifest.get("licence"), Mapping) else {}
    if licence.get("spdx") != "CC0-1.0" or licence.get("url") != REEP_LICENSE_URL:
        raise PreflightError("official Reep licence is not the expected CC0 pointer")
    file_meta = manifest.get("files")
    if not isinstance(file_meta, Mapping):
        raise PreflightError("official Reep manifest has no files object")
    release_prefix = stamp
    for name in (*_REEP_REQUIRED_FILES, *_REEP_METADATA_FILES):
        meta = file_meta.get(name)
        if not isinstance(meta, Mapping):
            raise BoundedAccessNotReady(f"official Reep bounded file is missing: {name}")
        _official_reep_url(meta.get("url"), release_prefix=release_prefix)

    checksums = _checksum_file(Path(checksums_path))
    files: dict[str, dict[str, Any]] = {}
    for name in _REEP_REQUIRED_FILES:
        meta = file_meta[name]
        path = Path(local_files[name])
        if not path.is_file():
            raise PreflightError(f"downloaded Reep file is missing: {name}")
        local_bytes = path.stat().st_size
        local_sha = _sha256(path)
        official_bytes = int(meta.get("bytes"))
        official_sha = str(meta.get("sha256") or "").lower()
        checksum_sha = checksums.get(name)
        if local_bytes != official_bytes or local_sha != official_sha or checksum_sha != official_sha:
            raise PreflightError(f"Reep checksum verification failed: {name}")
        files[name] = {
            "url": str(meta["url"]),
            "bytes": official_bytes,
            "official_sha256": official_sha,
            "checksums_sha256": checksum_sha,
            "local_sha256": local_sha,
            "locally_verified": True,
            "role": str(meta.get("role") or "canonical_csv"),
        }

    metadata_files: dict[str, dict[str, Any]] = {}
    for name in _REEP_METADATA_FILES:
        meta = file_meta[name]
        path = Path(local_files.get(name) or (Path(cache_dir) / name.replace("/", "__")))
        if not path.is_file():
            raise PreflightError(f"downloaded Reep metadata file is missing: {name}")
        local_bytes = path.stat().st_size
        local_sha = _sha256(path)
        official_bytes = int(meta.get("bytes"))
        official_sha = str(meta.get("sha256") or "").lower()
        if local_bytes != official_bytes or local_sha != official_sha:
            raise PreflightError(f"Reep metadata checksum verification failed: {name}")
        checksum_sha = checksums.get(name)
        if name != "checksums.txt" and checksum_sha != official_sha:
            raise PreflightError(f"Reep checksum-file entry mismatch: {name}")
        metadata_files[name] = {
            "url": str(meta["url"]),
            "bytes": official_bytes,
            "official_sha256": official_sha,
            "checksums_sha256": checksum_sha,
            "local_sha256": local_sha,
            "locally_verified": True,
            "role": str(meta.get("role") or "metadata"),
        }

    if license_path is None:
        license_path = Path(local_files.get("LICENSE.txt") or (Path(cache_dir) / "LICENSE.txt"))
    try:
        license_text = Path(license_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PreflightError("official Reep licence file is unreadable") from error
    if "CC0 1.0 Universal" not in license_text:
        raise PreflightError("official Reep licence file does not identify CC0 1.0")

    schema_records = _schema_records(schema or {}) if schema is not None else {}
    return {
        "access_status": "BOUNDED_CSV_READY",
        "release_stamp": stamp,
        "latest_pointer_url": REEP_LATEST_URL,
        "latest_pointer_sha256": latest_pointer_sha256,
        "latest_manifest_url": str(latest.get("manifest_url") or ""),
        "manifest_sha256_claimed_by_latest": str(latest.get("manifest_sha256") or ""),
        "manifest_sha256_locally_verified": release_manifest_sha256,
        "release_manifest_url": str(manifest.get("publication", {}).get("release_url") or latest.get("manifest_url") or ""),
        "checksums_url": str(latest.get("checksums_url") or ""),
        "licence": {
            "spdx": licence.get("spdx"),
            "name": licence.get("name"),
            "url": licence.get("url"),
            "file": "LICENSE.txt",
        },
        "files": {**files, **metadata_files},
        "schema": schema_records,
        "relevant_tables": ["teams", "aliases", "competitions", "redirects"],
        "duckdb_downloaded": False,
        "api_key_requested": False,
        "official_release_contract_verified": True,
    }


def _read_gzip_csv(path: Path, expected_columns: list[str]) -> list[dict[str, str]]:
    return list(_iter_gzip_csv(path, expected_columns))


def _iter_gzip_csv(path: Path, expected_columns: list[str]) -> Iterable[dict[str, str]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected_columns:
                raise PreflightError(f"official Reep CSV schema mismatch: {path.name}")
            for row in reader:
                yield dict(row)
    except PreflightError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise PreflightError(f"official Reep CSV is unreadable: {path.name}") from error


def load_reep_release(
    cache_dir: Path,
    *,
    existing_alias_path: Path | None = None,
) -> tuple[ReepIdentityRegister, dict[str, Any]]:
    """Fetch and verify only the official current Reep v1 bounded CSV surface."""

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    latest_path = cache / "latest.json"
    _download_reep_file(REEP_LATEST_URL, latest_path)
    latest = _json_file(latest_path, "latest pointer")
    manifest_url = _official_reep_url(latest.get("manifest_url"))
    stamp = str(latest.get("stamp") or "").strip()
    if not stamp or f"/releases/{stamp}/release.json" != urlparse(manifest_url).path:
        raise PreflightError("official Reep latest pointer has an invalid pinned manifest")
    manifest_path = cache / "release.json"
    _download_reep_file(manifest_url, manifest_path)
    manifest_sha = _sha256(manifest_path)
    if manifest_sha != str(latest.get("manifest_sha256") or "").lower():
        raise PreflightError("official Reep manifest hash does not match latest pointer")
    manifest = _json_file(manifest_path, "release manifest")
    files_meta = manifest.get("files") if isinstance(manifest.get("files"), Mapping) else {}
    if not all(name in files_meta for name in _REEP_REQUIRED_FILES):
        if "duckdb/reep-register-v1.duckdb" in files_meta:
            raise BoundedAccessNotReady("official Reep exposes no complete bounded CSV surface")
        raise PreflightError("official Reep manifest omits required identity CSVs")

    checksums_url = _official_reep_url(latest.get("checksums_url"), release_prefix=stamp)
    checksums_path = cache / "checksums.txt"
    _download_reep_file(checksums_url, checksums_path)
    license_path = cache / "LICENSE.txt"
    schema_path = cache / "schema.json"
    _download_reep_file(_official_reep_url(files_meta["LICENSE.txt"].get("url"), release_prefix=stamp), license_path)
    _download_reep_file(_official_reep_url(files_meta["schema.json"].get("url"), release_prefix=stamp), schema_path)
    local_files: dict[str, Path] = {
        "LICENSE.txt": license_path,
        "schema.json": schema_path,
        "checksums.txt": checksums_path,
    }
    for name in _REEP_REQUIRED_FILES:
        destination = cache / name.replace("/", "__")
        _download_reep_file(_official_reep_url(files_meta[name].get("url"), release_prefix=stamp), destination)
        local_files[name] = destination
    schema = _json_file(schema_path, "schema")
    provenance = load_release_provenance(
        latest=latest,
        manifest=manifest,
        cache_dir=cache,
        local_files=local_files,
        checksums_path=checksums_path,
        schema=schema,
        latest_pointer_sha256=_sha256(latest_path),
        release_manifest_sha256=manifest_sha,
        license_path=license_path,
    )
    team_rows = _read_gzip_csv(local_files["csv/teams.csv.gz"], ["reep_id", "status", "label", "gender", "country"])
    competition_rows = _read_gzip_csv(local_files["csv/competitions.csv.gz"], ["reep_id", "status", "label", "gender", "country"])
    raw_team_ids = {str(row.get("reep_id") or "").strip() for row in team_rows}
    raw_competition_ids = {str(row.get("reep_id") or "").strip() for row in competition_rows}
    relevant_ids = raw_team_ids | raw_competition_ids
    alias_rows = (
        row for row in _iter_gzip_csv(
            local_files["csv/aliases.csv.gz"],
            ["reep_id", "alias", "kind", "rank", "language"],
        ) if str(row.get("reep_id") or "").strip() in relevant_ids
    )
    redirect_rows = _read_gzip_csv(local_files["csv/redirects.csv.gz"], ["from_id", "to_id", "reason"])
    register = ReepIdentityRegister.from_rows(
        team_rows=team_rows,
        alias_rows=alias_rows,
        competition_rows=competition_rows,
        redirect_rows=redirect_rows,
        existing_alias_rows=load_existing_team_alias_rows(existing_alias_path),
    )
    return register, provenance


def parse_regulation_scoreline(label: Any) -> tuple[int, int] | None:
    """Parse only an explicit regulation-time home-away score token."""

    match = _SCORE_LABEL.fullmatch(str(label or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _event_id(event: Mapping[str, Any]) -> str:
    return str(event.get("id") or event.get("event_id") or "").strip()


def _event_sport_key(event: Mapping[str, Any]) -> str:
    return str(event.get("sport_key") or "").strip()


def _event_team(event: Mapping[str, Any], side: str) -> str:
    if side == "home":
        return str(event.get("home_team") or event.get("home") or "").strip()
    return str(event.get("away_team") or event.get("away") or "").strip()


def _event_time(event: Mapping[str, Any]) -> datetime | None:
    try:
        return _parse_instant(event.get("commence_time") or event.get("kickoff_at"), "provider kickoff")
    except PreflightError:
        return None


def _provider_competition(event: Mapping[str, Any]) -> str:
    for field in ("competition", "competition_name", "league", "league_name"):
        value = str(event.get(field) or "").strip()
        if value:
            return value
    return ""


def _competition_context(
    candidate: Mapping[str, Any],
    event: Mapping[str, Any],
    register: ReepIdentityRegister,
) -> dict[str, Any]:
    fbos_competition = str(candidate.get("competition") or "").strip()
    provider_competition = _provider_competition(event)
    if not provider_competition:
        return {
            "status": "NOT_AVAILABLE",
            "fbos_competition": fbos_competition or None,
            "provider_competition": None,
            "fbos_resolution": None,
            "provider_resolution": None,
        }
    if _name_key(fbos_competition) and _name_key(fbos_competition) == _name_key(provider_competition):
        return {
            "status": "CONSISTENT_EXACT_LABEL",
            "fbos_competition": fbos_competition,
            "provider_competition": provider_competition,
            "fbos_resolution": None,
            "provider_resolution": None,
        }
    fbos_resolution = register.resolve_competition(fbos_competition)
    provider_resolution = register.resolve_competition(provider_competition)
    if (
        fbos_resolution["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED"
        or provider_resolution["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED"
    ):
        status = "AMBIGUOUS_FAIL_CLOSED"
    elif (
        fbos_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
        and provider_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
        and fbos_resolution["reep_id"] != provider_resolution["reep_id"]
    ):
        status = "CONTRADICTORY"
    elif (
        fbos_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
        and provider_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
    ):
        status = "CONSISTENT_SAME_REEP_ID"
    else:
        status = "UNRESOLVED_NO_CONTRADICTION"
    return {
        "status": status,
        "fbos_competition": fbos_competition,
        "provider_competition": provider_competition,
        "fbos_resolution": fbos_resolution,
        "provider_resolution": provider_resolution,
    }


def bridge_candidate_to_events(
    candidate: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    register: ReepIdentityRegister,
    *,
    provider_sport_keys: Iterable[str] = (),
) -> dict[str, Any]:
    """Bridge one candidate to provider events using only stable Reep IDs and kickoff."""

    candidate_kickoff = _parse_instant(candidate.get("kickoff"), "candidate kickoff")
    fbos_home = register.resolve_team(candidate.get("home"))
    fbos_away = register.resolve_team(candidate.get("away"))
    overlap_evidence: list[dict[str, Any]] = []
    exact_events: list[dict[str, Any]] = []
    reversed_events: list[str] = []
    team_mismatch_events: list[str] = []
    provider_ambiguity = False
    provider_no_match = False
    competition_contradiction = False
    competition_ambiguity = False
    partial_team_overlap = False
    kickoff_overlap = False
    for raw_event in events:
        if not isinstance(raw_event, Mapping):
            continue
        provider_id = _event_id(raw_event)
        provider_sport = _event_sport_key(raw_event)
        provider_home = _event_team(raw_event, "home")
        provider_away = _event_team(raw_event, "away")
        provider_kickoff = _event_time(raw_event)
        if not provider_id or not provider_sport or not provider_home or not provider_away or provider_kickoff is None:
            continue
        delta = (provider_kickoff - candidate_kickoff).total_seconds()
        if abs(delta) > KICKOFF_TOLERANCE_SECONDS:
            continue
        kickoff_overlap = True
        provider_home_resolution = register.resolve_team(provider_home)
        provider_away_resolution = register.resolve_team(provider_away)
        competition = _competition_context(candidate, raw_event, register)
        if competition["status"] == "CONTRADICTORY":
            competition_contradiction = True
        if competition["status"] == "AMBIGUOUS_FAIL_CLOSED":
            competition_ambiguity = True
        if provider_home_resolution["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED" or provider_away_resolution["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED":
            provider_ambiguity = True
        if provider_home_resolution["resolution_status"] == "NO_REEP_MATCH" or provider_away_resolution["resolution_status"] == "NO_REEP_MATCH":
            provider_no_match = True
        home_same = (
            fbos_home["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_home_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and fbos_home["reep_id"] == provider_home_resolution["reep_id"]
        )
        away_same = (
            fbos_away["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_away_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and fbos_away["reep_id"] == provider_away_resolution["reep_id"]
        )
        reversed_orientation = (
            fbos_home["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and fbos_away["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_home_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_away_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and fbos_home["reep_id"] == provider_away_resolution["reep_id"]
            and fbos_away["reep_id"] == provider_home_resolution["reep_id"]
        )
        if bool(home_same) ^ bool(away_same):
            partial_team_overlap = True
        if reversed_orientation:
            reversed_events.append(provider_id)
        elif (
            fbos_home["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and fbos_away["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_home_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and provider_away_resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
            and not (home_same and away_same)
        ):
            team_mismatch_events.append(provider_id)
        evidence = {
            "provider_event_id": provider_id,
            "provider_sport_key": provider_sport,
            "provider_home": provider_home,
            "provider_away": provider_away,
            "provider_kickoff": provider_kickoff.isoformat(),
            "kickoff_delta_seconds": round(delta, 3),
            "provider_home_resolution": provider_home_resolution,
            "provider_away_resolution": provider_away_resolution,
            "competition_context": competition,
            "orientation_preserved": not reversed_orientation,
            "same_reep_home": home_same,
            "same_reep_away": away_same,
        }
        overlap_evidence.append(evidence)
        if home_same and away_same and competition["status"] not in {"CONTRADICTORY", "AMBIGUOUS_FAIL_CLOSED"}:
            exact_events.append(evidence)

    candidate_ambiguous = (
        fbos_home["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED"
        or fbos_away["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED"
    )
    distinct_exact_ids = sorted({row["provider_event_id"] for row in exact_events})
    if len(distinct_exact_ids) > 1:
        identity_status = "IDENTITY_AMBIGUOUS_FAIL_CLOSED"
        reason_code = "COMPETING_EXACT_PROVIDER_EVENTS"
        exact_event = None
    elif candidate_ambiguous or provider_ambiguity or competition_ambiguity:
        identity_status = "IDENTITY_AMBIGUOUS_FAIL_CLOSED"
        reason_code = "REEP_TEAM_OR_COMPETITION_AMBIGUOUS"
        exact_event = None
    elif len(distinct_exact_ids) == 1:
        identity_status = "EXACT_MATCH"
        reason_code = "EXACT_REEP_IDENTITY"
        exact_event = exact_events[0]
    elif competition_contradiction:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "COMPETITION_CONTRADICTION"
        exact_event = None
    elif reversed_events:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "REVERSED_HOME_AWAY"
        exact_event = None
    elif not kickoff_overlap:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "NO_PROVIDER_KICKOFF_OVERLAP"
        exact_event = None
    elif fbos_home["resolution_status"] == "NO_REEP_MATCH" or fbos_away["resolution_status"] == "NO_REEP_MATCH":
        identity_status = "NO_EVENT_MATCH"
        reason_code = "FBOS_TEAM_NO_REEP_MATCH"
        exact_event = None
    elif provider_no_match:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "PROVIDER_TEAM_NO_REEP_MATCH"
        exact_event = None
    elif team_mismatch_events:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "TEAM_REEP_ID_MISMATCH"
        exact_event = None
    else:
        identity_status = "NO_EVENT_MATCH"
        reason_code = "NO_EXACT_REEP_IDENTITY"
        exact_event = None
    if identity_status not in VALID_IDENTITY_STATUSES:
        raise PreflightError("identity bridge returned a status outside the contract")
    return {
        "identity_status": identity_status,
        "reason_code": reason_code,
        "provider_event_id": exact_event["provider_event_id"] if exact_event else None,
        "provider_sport_key": exact_event["provider_sport_key"] if exact_event else None,
        "provider_home_reep_id": exact_event["provider_home_resolution"]["reep_id"] if exact_event else None,
        "provider_away_reep_id": exact_event["provider_away_resolution"]["reep_id"] if exact_event else None,
        "kickoff_delta_seconds": exact_event["kickoff_delta_seconds"] if exact_event else None,
        "fbos_home_resolution": fbos_home,
        "fbos_away_resolution": fbos_away,
        "provider_sport_keys_considered": sorted(set(provider_sport_keys)),
        "kickoff_only_event_count": len(overlap_evidence),
        "partial_team_overlap": partial_team_overlap,
        "reversed_provider_event_ids": sorted(set(reversed_events)),
        "provider_event_evidence": overlap_evidence,
        "competition_context_status": (
            exact_event["competition_context"]["status"]
            if exact_event
            else next((row["competition_context"]["status"] for row in overlap_evidence if row["competition_context"]["status"] != "NOT_AVAILABLE"), "NOT_AVAILABLE")
        ),
    }


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _header_value(headers: Mapping[str, Any], name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == wanted and value not in (None, ""):
            return str(value)
    return None


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_usage_headers(headers: Mapping[str, Any], secret: str | None = None) -> dict[str, str]:
    output: dict[str, str] = {}
    for name in _USAGE_HEADERS:
        value = _header_value(headers, name)
        if value is not None:
            output[name] = value.replace(secret, "[REDACTED]") if secret else value
    return output


class ProviderClient:
    """Minimal The Odds API client with a one-credit worst-case probe guard."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Transport | None = None,
        max_credits: int = MAX_CREDITS,
    ) -> None:
        if not api_key:
            raise CredentialRequired("FOUNDER_SECRET_REQUIRED")
        self._api_key = api_key
        self._transport = transport or self._http_transport
        self.max_credits = int(max_credits)
        self.credits_reserved = 0
        self._observed_costs: list[int | None] = []
        self.usage_headers: list[dict[str, Any]] = []
        self.probe_paths: list[str] = []

    def _http_transport(self, path: str, params: Mapping[str, str]) -> tuple[Any, Mapping[str, Any]]:
        query = urlencode(dict(params))
        request = Request(
            f"{API_HOST}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "FBOS-Reep-identity-bridge-preflight/1"},
        )
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = dict(response.headers.items())
        except HTTPError as error:
            raise ProviderRequestError(f"provider request failed: {path} (HTTP {error.code})") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderRequestError(f"provider request failed: {path} (network error)") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRequestError(f"provider returned invalid JSON: {path}") from None
        return payload, headers

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> tuple[Any, Mapping[str, Any]]:
        request_params = {str(key): str(value) for key, value in (params or {}).items()}
        request_params["apiKey"] = self._api_key
        try:
            payload, headers = self._transport(path, request_params)
        except ProviderRequestError:
            raise
        except Exception as error:
            raise ProviderRequestError(f"provider transport failed: {path}") from error
        self.usage_headers.append({"path": path, "headers": _safe_usage_headers(headers, self._api_key)})
        return payload, headers

    def discover_sports(self) -> list[dict[str, Any]]:
        payload, _ = self._get("/v4/sports")
        if not isinstance(payload, list):
            raise ProviderRequestError("provider sports response was not a list")
        rows = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("key") or "").strip()
            group = str(row.get("group") or "").strip().casefold()
            if key.startswith("soccer_") and (group == "soccer" or not group):
                rows.append({
                    "key": key,
                    "title": str(row.get("title") or "").strip(),
                    "active": row.get("active") is True,
                })
        return sorted({row["key"]: row for row in rows}.values(), key=lambda row: row["key"])

    def discover_events(self, sport_key: str) -> list[dict[str, Any]]:
        safe_key = quote(sport_key, safe="")
        payload, _ = self._get(f"/v4/sports/{safe_key}/events")
        if not isinstance(payload, list):
            raise ProviderRequestError("provider events response was not a list")
        events = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            event = dict(row)
            event.setdefault("sport_key", sport_key)
            events.append(event)
        return events

    def probe_event_odds(self, sport_key: str, event_id: str) -> tuple[Any, Mapping[str, Any]]:
        if self.credits_reserved + 1 > self.max_credits:
            raise PreflightError("provider correct_score probe credit cap reached before request")
        self.credits_reserved += 1
        safe_sport = quote(sport_key, safe="")
        safe_event = quote(event_id, safe="")
        path = f"/v4/sports/{safe_sport}/events/{safe_event}/odds"
        self.probe_paths.append(path)
        payload, headers = self._get(
            path,
            {"regions": PROBE_REGION, "markets": CORRECT_SCORE_MARKET, "oddsFormat": "decimal"},
        )
        last = _nonnegative_int(_header_value(headers, "x-requests-last"))
        self._observed_costs.append(last)
        if last is not None and last > 1:
            raise ProviderRequestError("one-region correct_score probe exceeded one-credit contract")
        return payload, headers

    def credit_usage(self) -> dict[str, Any]:
        complete = bool(self.probe_paths) and len(self._observed_costs) == len(self.probe_paths) and all(
            value is not None for value in self._observed_costs
        )
        if complete:
            credits_used = sum(value for value in self._observed_costs if value is not None)
            basis = "x-requests-last headers"
        else:
            credits_used = self.credits_reserved
            basis = "one-credit-per-probe conservative upper bound" if self.probe_paths else "no correct_score probes"
        return {
            "cap": self.max_credits,
            "credits_used": credits_used,
            "credits_reserved_upper_bound": self.credits_reserved,
            "credits_used_basis": basis,
            "probes_attempted": len(self.probe_paths),
            "usage_headers": self.usage_headers,
        }


def _price(value: Any) -> float | None:
    number = _safe_number(value)
    return number if number is not None and number > 0 else None


def probe_correct_score_payload(payload: Any) -> dict[str, Any]:
    """Summarize correct-score shape; malformed/non-score labels never count."""

    bookmakers = payload.get("bookmakers") if isinstance(payload, Mapping) else []
    if not isinstance(bookmakers, list):
        bookmakers = []
    bookmaker_summaries: list[dict[str, Any]] = []
    market_count = 0
    outcome_count = 0
    parseable_outcome_count = 0
    last_updates: set[str] = set()
    for bookmaker in bookmakers:
        if not isinstance(bookmaker, Mapping):
            continue
        bookmaker_key = str(bookmaker.get("key") or bookmaker.get("title") or "unknown")
        bookmaker_last_update = str(bookmaker.get("last_update") or "").strip() or None
        if bookmaker_last_update:
            last_updates.add(bookmaker_last_update)
        markets = bookmaker.get("markets") or []
        if not isinstance(markets, list):
            markets = []
        correct_markets = [
            market for market in markets
            if isinstance(market, Mapping) and market.get("key") == CORRECT_SCORE_MARKET
        ]
        for market in correct_markets:
            market_count += 1
            market_last_update = str(market.get("last_update") or "").strip() or None
            if market_last_update:
                last_updates.add(market_last_update)
            outcomes = market.get("outcomes") or []
            if not isinstance(outcomes, list):
                outcomes = []
            valid_outcomes = [outcome for outcome in outcomes if isinstance(outcome, Mapping)]
            market_parseable_count = 0
            implied_sum = 0.0
            for outcome in valid_outcomes:
                if parse_regulation_scoreline(outcome.get("name")) is None:
                    continue
                price = _price(outcome.get("price"))
                if price is None:
                    continue
                market_parseable_count += 1
                implied_sum += 1.0 / price
            outcome_count += len(valid_outcomes)
            parseable_outcome_count += market_parseable_count
            bookmaker_summaries.append({
                "bookmaker_key": bookmaker_key,
                "outcome_count": len(valid_outcomes),
                "parseable_outcome_count": market_parseable_count,
                "implied_probability_sum": round(implied_sum, 9) if market_parseable_count else None,
                "overround": round(implied_sum - 1.0, 9) if market_parseable_count else None,
                "last_update": market_last_update or bookmaker_last_update,
            })
    return {
        "correct_score_returned": market_count > 0,
        "correct_score_covered": parseable_outcome_count > 0,
        "bookmaker_count": len([row for row in bookmakers if isinstance(row, Mapping)]),
        "correct_score_bookmaker_count": len({row["bookmaker_key"] for row in bookmaker_summaries}),
        "market_count": market_count,
        "outcome_count": outcome_count,
        "parseable_outcome_count": parseable_outcome_count,
        "regulation_time_scoreline_parseable": parseable_outcome_count > 0,
        "last_update_timestamps": sorted(last_updates),
        "bookmakers": bookmaker_summaries,
    }


def decide_preflight(
    *,
    exact_event_identity_count: int,
    correct_score_covered_count: int,
    credits_used: int,
    reep_access_status: str = "BOUNDED_CSV_READY",
    provider_query_ok: bool = True,
    provenance_ok: bool = True,
    rights_security_ok: bool = True,
    unresolved_identity_ambiguity_count: int = 0,
) -> str:
    if reep_access_status == "BOUNDED_ACCESS_NOT_READY":
        return "REEP_BOUNDED_ACCESS_NOT_READY"
    if (
        not provider_query_ok
        or not provenance_ok
        or not rights_security_ok
        or credits_used < 0
        or credits_used > MAX_CREDITS
        or unresolved_identity_ambiguity_count < 0
        or reep_access_status != "BOUNDED_CSV_READY"
    ):
        return "FAIL_CLOSED"
    if exact_event_identity_count >= 10 and correct_score_covered_count >= 10:
        return "REEP_IDENTITY_AND_CORRECT_SCORE_PILOT_READY"
    if exact_event_identity_count >= 10:
        return "REEP_IDENTITY_BRIDGE_USEFUL_COVERAGE_NOT_ENOUGH"
    return "REEP_IDENTITY_COVERAGE_INSUFFICIENT"


def _safe_error(error: Exception) -> str:
    text = str(error)
    if "apiKey" in text or "API_KEY" in text or "THE_ODDS_API_KEY" in text:
        return "provider request failed"
    return text


def _fixture_provenance() -> dict[str, Any]:
    return {
        "access_status": "BOUNDED_CSV_READY",
        "release_stamp": "fixture",
        "latest_pointer_url": REEP_LATEST_URL,
        "latest_pointer_sha256": None,
        "latest_manifest_url": None,
        "manifest_sha256_claimed_by_latest": None,
        "manifest_sha256_locally_verified": None,
        "release_manifest_url": None,
        "checksums_url": None,
        "licence": {"spdx": "CC0-1.0", "name": "fixture", "url": REEP_LICENSE_URL, "file": "LICENSE.txt"},
        "files": {},
        "schema": {},
        "relevant_tables": ["teams", "aliases", "competitions", "redirects"],
        "duckdb_downloaded": False,
        "api_key_requested": False,
        "official_release_contract_verified": True,
    }


def _base_summary(
    cohort: Mapping[str, Any],
    *,
    current_ref: str,
    reep_provenance: Mapping[str, Any] | None = None,
    provider_query_ok: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "audit_snapshot_at": cohort["snapshot_at"],
        "source": {
            "current_ref": current_ref,
            "universe_source": "existing canonical prediction-universe fixtures only",
            "universe_root": "data/prediction_universe",
            "provider": PROVIDER_NAME,
            "provider_site": PROVIDER_SITE,
            "api_host": API_HOST,
            "api_key_env": API_KEY_ENV,
        },
        "baseline_pr179": {
            "candidate_count": BASELINE_PR179_CANDIDATE_COUNT,
            "reference": "Issue #178 / PR #179 accepted baseline",
            "current_main_delta": cohort["current_main_delta"],
            "delta_interpretation": "natural current-main cohort delta; not a repair of the PR #179 snapshot",
        },
        "candidate_cohort": dict(cohort),
        "reep_release": dict(reep_provenance or _fixture_provenance()),
        "identity": {
            "unique_fbos_team_count": len(cohort.get("unique_fbos_team_names", [])),
            "unique_provider_team_count": 0,
            "reep_resolved_fbos_team_count": 0,
            "reep_resolved_provider_team_count": 0,
            "team_resolution_status_counts": {},
            "team_resolution_reason_counts": {},
            "event_identity_reason_counts": {},
            "team_resolutions": [],
        },
        "provider_discovery": {
            "sports_endpoint": "/v4/sports",
            "events_endpoint": "/v4/sports/{sport_key}/events",
            "soccer_sport_keys": [],
            "active_soccer_sport_count": 0,
            "events_by_sport": {},
            "provider_event_count": 0,
            "kickoff_overlap_candidate_count": 0,
            "kickoff_overlap_event_count": 0,
            "partial_team_overlap_candidate_count": 0,
        },
        "probes": {
            "market": CORRECT_SCORE_MARKET,
            "region": PROBE_REGION,
            "region_chosen_before_outcome_inspection": True,
            "exact_event_identity_count": 0,
            "correct_score_covered_count": 0,
            "candidate_results": [],
            "errors": [],
        },
        "credits": {
            "cap": MAX_CREDITS,
            "credits_used": 0,
            "credits_reserved_upper_bound": 0,
            "credits_used_basis": "no correct_score probes",
            "probes_attempted": 0,
            "usage_headers": [],
        },
        "controls": dict(READ_ONLY_CONTROLS),
        "provider_query_ok": provider_query_ok,
        "final_decision": "FAIL_CLOSED",
    }


def _resolution_status_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("resolution_status") or "UNKNOWN") for row in rows).items()))


def run_preflight(
    *,
    universe_root: Path,
    current_ref: str,
    snapshot_at: Any,
    api_key: str,
    reep_register: ReepIdentityRegister,
    reep_provenance: Mapping[str, Any] | None = None,
    client: ProviderClient | None = None,
) -> dict[str, Any]:
    cohort = load_candidate_cohort(Path(universe_root), snapshot_at=snapshot_at)
    summary = _base_summary(cohort, current_ref=current_ref, reep_provenance=reep_provenance)
    if not api_key:
        raise CredentialRequired("FOUNDER_SECRET_REQUIRED")
    client = client or ProviderClient(api_key)
    provider_errors: list[str] = []
    all_events: list[dict[str, Any]] = []
    sport_keys: list[str] = []
    try:
        sports = client.discover_sports()
        sport_keys = [row["key"] for row in sports if row.get("active")]
        summary["provider_discovery"]["soccer_sport_keys"] = sport_keys
        summary["provider_discovery"]["active_soccer_sport_count"] = len(sport_keys)
        by_sport: dict[str, int] = {}
        for sport_key in sport_keys:
            events = client.discover_events(sport_key)
            by_sport[sport_key] = len(events)
            all_events.extend(events)
        summary["provider_discovery"]["events_by_sport"] = by_sport
        summary["provider_discovery"]["provider_event_count"] = len(all_events)
    except ProviderRequestError as error:
        provider_errors.append(_safe_error(error))

    candidate_kickoffs = [
        _parse_instant(row["kickoff"], "candidate kickoff")
        for row in cohort["candidates"]
    ]
    overlap_events: list[dict[str, Any]] = []
    provider_team_names: set[str] = set()
    for event in all_events:
        event_time = _event_time(event)
        if event_time is None:
            continue
        deltas = [(event_time - kickoff).total_seconds() for kickoff in candidate_kickoffs]
        if any(abs(delta) <= KICKOFF_TOLERANCE_SECONDS for delta in deltas):
            overlap_events.append(event)
            for side in ("home", "away"):
                team = _event_team(event, side)
                if team:
                    provider_team_names.add(team)
    summary["provider_discovery"]["kickoff_overlap_event_count"] = len(overlap_events)
    summary["provider_discovery"]["kickoff_overlap_candidate_count"] = sum(
        any(
            _event_time(event) is not None
            and abs((_event_time(event) - _parse_instant(candidate["kickoff"], "candidate kickoff")).total_seconds()) <= KICKOFF_TOLERANCE_SECONDS
            for event in all_events
        )
        for candidate in cohort["candidates"]
    )
    team_resolution_rows: list[dict[str, Any]] = []
    resolution_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for side, names in (
        ("FBOS", cohort.get("unique_fbos_team_names", [])),
        ("THE_ODDS_API", sorted(provider_team_names)),
    ):
        for name in names:
            key = (side, name)
            resolution = reep_register.resolve_team(name)
            row = {"side": side, **resolution}
            resolution_cache[key] = resolution
            team_resolution_rows.append(row)
    summary["identity"]["unique_provider_team_count"] = len(provider_team_names)
    summary["identity"]["reep_resolved_fbos_team_count"] = sum(
        row["side"] == "FBOS" and row["resolution_status"] == "UNIQUE_EXACT_REEP_ID" for row in team_resolution_rows
    )
    summary["identity"]["reep_resolved_provider_team_count"] = sum(
        row["side"] == "THE_ODDS_API" and row["resolution_status"] == "UNIQUE_EXACT_REEP_ID" for row in team_resolution_rows
    )
    summary["identity"]["team_resolution_status_counts"] = _resolution_status_counts(team_resolution_rows)
    summary["identity"]["team_resolution_reason_counts"] = dict(sorted(Counter(
        "REEP_MATCH" if row["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
        else row["resolution_status"]
        for row in team_resolution_rows
    ).items()))
    summary["identity"]["team_resolutions"] = team_resolution_rows

    candidate_results: list[dict[str, Any]] = []
    for candidate in cohort["candidates"]:
        if provider_errors:
            bridge = {
                "identity_status": "NO_PROVIDER_SPORT_MAPPING",
                "reason_code": "PROVIDER_DISCOVERY_FAILED",
                "provider_event_id": None,
                "provider_sport_key": None,
                "provider_home_reep_id": None,
                "provider_away_reep_id": None,
                "kickoff_delta_seconds": None,
                "fbos_home_resolution": reep_register.resolve_team(candidate["home"]),
                "fbos_away_resolution": reep_register.resolve_team(candidate["away"]),
                "provider_sport_keys_considered": [],
                "kickoff_only_event_count": 0,
                "partial_team_overlap": False,
                "reversed_provider_event_ids": [],
                "provider_event_evidence": [],
                "competition_context_status": "NOT_AVAILABLE",
            }
        elif not sport_keys:
            bridge = {
                "identity_status": "NO_PROVIDER_SPORT_MAPPING",
                "reason_code": "NO_ACTIVE_SOCCER_SPORT_KEY",
                "provider_event_id": None,
                "provider_sport_key": None,
                "provider_home_reep_id": None,
                "provider_away_reep_id": None,
                "kickoff_delta_seconds": None,
                "fbos_home_resolution": reep_register.resolve_team(candidate["home"]),
                "fbos_away_resolution": reep_register.resolve_team(candidate["away"]),
                "provider_sport_keys_considered": [],
                "kickoff_only_event_count": 0,
                "partial_team_overlap": False,
                "reversed_provider_event_ids": [],
                "provider_event_evidence": [],
                "competition_context_status": "NOT_AVAILABLE",
            }
        else:
            bridge = bridge_candidate_to_events(
                candidate,
                all_events,
                reep_register,
                provider_sport_keys=sport_keys,
            )
        result = {**candidate, **bridge, "correct_score": None, "probe_status": "NOT_PROBED"}
        candidate_results.append(result)

    exact_results = [row for row in candidate_results if row["identity_status"] == "EXACT_MATCH"]
    for result in exact_results:
        try:
            payload, _ = client.probe_event_odds(result["provider_sport_key"], result["provider_event_id"])
            result["correct_score"] = probe_correct_score_payload(payload)
            result["probe_status"] = "PROBED"
        except PreflightError as error:
            result["probe_status"] = "PROBE_ERROR"
            result["probe_error"] = _safe_error(error)
            provider_errors.append(_safe_error(error))
            if "credit cap" in str(error):
                break
    for result in exact_results:
        if result["probe_status"] == "NOT_PROBED":
            result["probe_status"] = "NOT_PROBED_CREDIT_CAP"
    exact_count = len(exact_results)
    covered_count = sum(bool((row.get("correct_score") or {}).get("correct_score_covered")) for row in candidate_results)
    ambiguity_count = sum(row["identity_status"] == "IDENTITY_AMBIGUOUS_FAIL_CLOSED" for row in candidate_results)
    summary["provider_discovery"]["partial_team_overlap_candidate_count"] = sum(
        row.get("partial_team_overlap") is True for row in candidate_results
    )
    summary["identity"]["event_identity_reason_counts"] = dict(sorted(Counter(
        str(row.get("reason_code") or "UNKNOWN") for row in candidate_results
    ).items()))
    summary["probes"]["candidate_results"] = candidate_results
    summary["probes"]["exact_event_identity_count"] = exact_count
    summary["probes"]["correct_score_covered_count"] = covered_count
    summary["probes"]["errors"] = sorted(set(provider_errors))
    summary["credits"] = client.credit_usage()
    summary["provider_query_ok"] = not provider_errors
    summary["decision_conditions"] = {
        "exact_event_identity_count": exact_count,
        "correct_score_covered_count": covered_count,
        "credits_used": summary["credits"]["credits_used"],
        "credit_cap_respected": summary["credits"]["credits_used"] <= MAX_CREDITS,
        "unresolved_identity_ambiguity_count": ambiguity_count,
        "provider_errors": sorted(set(provider_errors)),
        "reep_release_verified": summary["reep_release"].get("official_release_contract_verified") is True,
    }
    summary["final_decision"] = decide_preflight(
        exact_event_identity_count=exact_count,
        correct_score_covered_count=covered_count,
        credits_used=summary["credits"]["credits_used"],
        reep_access_status=str(summary["reep_release"].get("access_status") or "FAIL_CLOSED"),
        provider_query_ok=not provider_errors,
        provenance_ok=summary["reep_release"].get("official_release_contract_verified") is True,
        rights_security_ok=True,
        unresolved_identity_ambiguity_count=ambiguity_count,
    )
    if summary["final_decision"] not in VALID_DECISIONS:
        raise PreflightError("preflight decision is outside Issue #180 contract")
    return summary


def _redact(value: Any, secret: str | None) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _redact(item, secret)
            for key, item in value.items()
            if key not in {"_api_key", "request_secret"}
        }
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_report(summary: Mapping[str, Any]) -> str:
    cohort = summary.get("candidate_cohort", {})
    release = summary.get("reep_release", {})
    identity = summary.get("identity", {})
    discovery = summary.get("provider_discovery", {})
    probes = summary.get("probes", {})
    credits = summary.get("credits", {})
    baseline = summary.get("baseline_pr179", {})
    lines = [
        f"# {MILESTONE}",
        "",
        f"Final decision: **{summary.get('final_decision', 'FAIL_CLOSED')}**",
        "",
        "## Scope and baseline",
        "",
        f"- Current ref: `{summary.get('source', {}).get('current_ref', '')}`; audit snapshot: `{summary.get('audit_snapshot_at', '')}`.",
        f"- Future-only current-main candidates: **{cohort.get('candidate_count', 0)}** unique matches; raw future rows `{cohort.get('raw_future_candidate_rows', 0)}`; deduplicated rows `{cohort.get('deduplicated_match_count', 0)}`.",
        f"- PR #179 accepted baseline: `{baseline.get('candidate_count', BASELINE_PR179_CANDIDATE_COUNT)}` candidates; current-main delta: `{baseline.get('current_main_delta', 0)}`.",
        "- The delta is reported separately as natural current-main growth/shrinkage and is not interpreted as a repair of the PR #179 snapshot.",
        "- Candidate truth is copied only from existing canonical `data/prediction_universe`; no historical results or outcome data are read.",
        "",
        "## Reep v1 release provenance",
        "",
        f"- Release stamp: `{release.get('release_stamp', '')}`; access status: `{release.get('access_status', '')}`; public tier contract verified: `{release.get('official_release_contract_verified', False)}`.",
        f"- Latest pointer: `{release.get('latest_pointer_url', REEP_LATEST_URL)}`; manifest: `{release.get('latest_manifest_url', '')}`.",
        f"- Licence: `{json.dumps(release.get('licence', {}), ensure_ascii=False, sort_keys=True)}`.",
        f"- Relevant schema tables: `{json.dumps(release.get('relevant_tables', []), ensure_ascii=False)}`; DuckDB downloaded: `{release.get('duckdb_downloaded', False)}`.",
        "- The artifact records each official URL, manifest byte size, official checksum, local checksum, and verification status for the bounded CSV/metadata files.",
        "",
        "## Team identity bridge",
        "",
        f"- Unique FBOS teams: `{identity.get('unique_fbos_team_count', 0)}`; unique provider teams considered at kickoff overlap: `{identity.get('unique_provider_team_count', 0)}`.",
        f"- Reep-resolved FBOS teams: `{identity.get('reep_resolved_fbos_team_count', 0)}`; Reep-resolved provider teams: `{identity.get('reep_resolved_provider_team_count', 0)}`.",
        f"- Resolution statuses: `{json.dumps(identity.get('team_resolution_status_counts', {}), ensure_ascii=False, sort_keys=True)}`.",
        f"- Event identity reason counts: `{json.dumps(identity.get('event_identity_reason_counts', {}), ensure_ascii=False, sort_keys=True)}`.",
        "- Resolution accepts only exact canonical labels, exact typed Reep aliases, or an existing confirmed `data/team_aliases.json` surface anchored to one Reep ID. No fuzzy, translation, transliteration, substring, or manual assignment is used.",
        "",
        "## Provider discovery and correct-score probe",
        "",
        f"- Provider: `{summary.get('source', {}).get('provider', PROVIDER_NAME)}`; sports endpoint `{discovery.get('sports_endpoint', '')}` then events endpoint `{discovery.get('events_endpoint', '')}`.",
        f"- Active soccer sport keys: `{json.dumps(discovery.get('soccer_sport_keys', []), ensure_ascii=False)}`; provider events discovered: `{discovery.get('provider_event_count', 0)}`; kickoff-overlap candidates: `{discovery.get('kickoff_overlap_candidate_count', 0)}`.",
        f"- Region `{probes.get('region', PROBE_REGION)}` was fixed before outcome inspection; market `{probes.get('market', CORRECT_SCORE_MARKET)}` is queried only after exact event identity.",
        f"- Exact event identities: `{probes.get('exact_event_identity_count', 0)}`; correct-score covered: `{probes.get('correct_score_covered_count', 0)}`; credits: `{json.dumps(credits, ensure_ascii=False, sort_keys=True)}`.",
        "- Correct-score observations are shape/availability diagnostics only: no de-vigging, tuning, ensemble, result comparison, or publication is performed.",
        "",
        "## Candidate-by-candidate evidence",
        "",
        "The JSON artifact contains complete FBOS and provider Reep resolution evidence for every candidate and every kickoff-overlap provider event. Only `EXACT_MATCH` rows can trigger a correct-score request.",
        "",
        "| FBOS match key | kickoff | FBOS home Reep | FBOS away Reep | provider sport | provider event | identity | reason | correct score | parseable outcomes | probe |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for row in probes.get("candidate_results", []):
        correct = row.get("correct_score") or {}
        lines.append(
            "| " + " | ".join([
                _markdown_cell(row.get("match_key")),
                _markdown_cell(row.get("kickoff")),
                _markdown_cell((row.get("fbos_home_resolution") or {}).get("reep_id")),
                _markdown_cell((row.get("fbos_away_resolution") or {}).get("reep_id")),
                _markdown_cell(row.get("provider_sport_key")),
                _markdown_cell(row.get("provider_event_id")),
                _markdown_cell(row.get("identity_status")),
                _markdown_cell(row.get("reason_code")),
                _markdown_cell(correct.get("correct_score_returned")),
                _markdown_cell(correct.get("parseable_outcome_count")),
                _markdown_cell(row.get("probe_status")),
            ]) + " |"
        )
    lines.extend([
        "",
        "## Decision and safety controls",
        "",
        f"- Decision conditions: `{json.dumps(summary.get('decision_conditions', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Controls: `{json.dumps(summary.get('controls', {}), ensure_ascii=False, sort_keys=True)}`",
        "- No result fetch/backfill, frozen prediction mutation, authoritative result mutation, model/Champion/Challenger change, serving integration, promotion, paid upgrade, provider hopping, or raw-feed publication.",
        "- The API key is secret-injected, never printed, serialized, committed, or uploaded.",
        "",
        "STOP: research-only evidence for independent acceptance. DO NOT MERGE.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(summary: Mapping[str, Any], output_dir: Path, *, secret: str | None = None) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    public_summary = _redact(summary, secret)
    summary_path = output / "summary.json"
    report_path = output / "report.md"
    summary_path.write_text(
        json.dumps(public_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(public_summary), encoding="utf-8")
    return {"summary": summary_path, "report": report_path}


def _failure_summary(
    *,
    universe_root: Path,
    current_ref: str,
    snapshot_at: Any,
    error: Exception,
    decision: str = "FAIL_CLOSED",
) -> dict[str, Any]:
    cohort = load_candidate_cohort(Path(universe_root), snapshot_at=snapshot_at)
    summary = _base_summary(cohort, current_ref=current_ref, provider_query_ok=False)
    summary["reep_release"] = {
        **_fixture_provenance(),
        "access_status": "BOUNDED_ACCESS_NOT_READY" if decision == "REEP_BOUNDED_ACCESS_NOT_READY" else "FAIL_CLOSED",
        "error": _safe_error(error),
        "official_release_contract_verified": False,
    }
    summary["decision_conditions"] = {"error": _safe_error(error)}
    summary["final_decision"] = decision
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-root", type=Path, required=True)
    parser.add_argument("--current-ref", required=True)
    parser.add_argument("--snapshot-at")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reep-cache-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default=API_KEY_ENV)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print("FOUNDER_SECRET_REQUIRED")
        return 2
    snapshot_at = args.snapshot_at or datetime.now(timezone.utc).isoformat()
    try:
        register, provenance = load_reep_release(args.reep_cache_dir)
        summary = run_preflight(
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=snapshot_at,
            api_key=api_key,
            reep_register=register,
            reep_provenance=provenance,
        )
    except CredentialRequired:
        print("FOUNDER_SECRET_REQUIRED")
        return 2
    except BoundedAccessNotReady as error:
        summary = _failure_summary(
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=snapshot_at,
            error=error,
            decision="REEP_BOUNDED_ACCESS_NOT_READY",
        )
    except PreflightError as error:
        summary = _failure_summary(
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=snapshot_at,
            error=error,
        )
    paths = write_artifacts(summary, args.output_dir, secret=api_key)
    print(json.dumps({
        "milestone": MILESTONE,
        "candidate_count": summary["candidate_cohort"]["candidate_count"],
        "reep_resolved_fbos_teams": summary["identity"]["reep_resolved_fbos_team_count"],
        "reep_resolved_provider_teams": summary["identity"]["reep_resolved_provider_team_count"],
        "exact_event_identities": summary["probes"]["exact_event_identity_count"],
        "correct_score_covered": summary["probes"]["correct_score_covered_count"],
        "credits_used": summary["credits"]["credits_used"],
        "final_decision": summary["final_decision"],
        "summary": str(paths["summary"]),
        "report": str(paths["report"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
