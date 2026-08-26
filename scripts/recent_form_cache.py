"""Demand-driven, fail-closed OpenFootball recent-form cache.

The cache stores only exact target-team observations needed by the current
prematch demand.  It is not a replacement for the historical ledger: raw
provider names, source lines, canonical target identity, and source provenance
are retained so the runner can reconstruct the four-block form contract
without inventing opponent identities or neutral defaults.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # runner executes with scripts/ on sys.path
    from football_data.providers.openfootball import parse_football_txt_rows
except ModuleNotFoundError:  # tests import the repository as a package
    from scripts.football_data.providers.openfootball import parse_football_txt_rows

try:
    from prediction_quality import recent_form_is_usable
except ModuleNotFoundError:
    from scripts.prediction_quality import recent_form_is_usable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = PROJECT_ROOT / "data" / "product_runtime" / "openfootball_recent_form.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "football_data" / "openfootball" / "espana_source_manifest.json"
RECENCY_RULES_PATH = PROJECT_ROOT / "config" / "team_strength_recency.json"
MAX_WINDOW = 5
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _max_history_age_days() -> int | None:
    try:
        value = json.loads(RECENCY_RULES_PATH.read_text(encoding="utf-8")).get("current_max_history_age_days")
        parsed = int(value)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if parsed >= 0 else None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _aggregate(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    result = {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
    for row in records:
        goals_for = _safe_int(row.get("goals_for"))
        goals_against = _safe_int(row.get("goals_against"))
        if goals_for is None or goals_against is None:
            continue
        result["matches"] += 1
        result["goals_for"] += goals_for
        result["goals_against"] += goals_against
        if goals_for > goals_against:
            result["wins"] += 1
        elif goals_for == goals_against:
            result["draws"] += 1
        else:
            result["losses"] += 1
    return result


def build_recent_form(
    records: Iterable[Mapping[str, Any]],
    *,
    home_team_id: str,
    away_team_id: str,
    cutoff_at: str,
    window_size: int = MAX_WINDOW,
) -> dict[str, Any] | None:
    """Build exact overall/venue blocks from target-team evidence before cutoff."""

    cutoff = _parse_timestamp(cutoff_at)
    if cutoff is None or window_size <= 0:
        return None
    target_ids = {home_team_id, away_team_id}
    by_team: dict[str, list[dict[str, Any]]] = {home_team_id: [], away_team_id: []}
    seen: set[tuple[Any, ...]] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        team_id = str(raw.get("team_id") or "")
        if team_id not in target_ids:
            continue
        kickoff = _parse_timestamp(raw.get("kickoff_at"))
        venue = str(raw.get("venue") or "")
        goals_for = _safe_int(raw.get("goals_for"))
        goals_against = _safe_int(raw.get("goals_against"))
        if kickoff is None or kickoff >= cutoff or venue not in {"home", "away"} or goals_for is None or goals_against is None:
            continue
        key = (
            team_id,
            _iso(kickoff),
            str(raw.get("source_file") or ""),
            str(raw.get("source_line") or ""),
            str(raw.get("raw_home") or ""),
            str(raw.get("raw_away") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        row = dict(raw)
        row.update({"team_id": team_id, "kickoff_at": _iso(kickoff), "venue": venue, "goals_for": goals_for, "goals_against": goals_against})
        by_team[team_id].append(row)

    selected_by_team: dict[str, list[dict[str, Any]]] = {}
    for team_id, rows in by_team.items():
        selected_by_team[team_id] = sorted(rows, key=lambda row: (row["kickoff_at"], str(row.get("source_file") or ""), int(row.get("source_line") or 0)))[-window_size:]
    home_rows = selected_by_team.get(home_team_id, [])
    away_rows = selected_by_team.get(away_team_id, [])
    if not home_rows or not away_rows:
        return None
    form = {
        "home_overall": _aggregate(home_rows),
        "home_home": _aggregate(row for row in home_rows if row["venue"] == "home"),
        "away_overall": _aggregate(away_rows),
        "away_away": _aggregate(row for row in away_rows if row["venue"] == "away"),
    }
    if not recent_form_is_usable(form):
        return None
    return {
        "recent_form": form,
        "records": sorted([*home_rows, *away_rows], key=lambda row: (row["kickoff_at"], row["team_id"])),
        "latest_by_team": {
            home_team_id: home_rows[-1]["kickoff_at"],
            away_team_id: away_rows[-1]["kickoff_at"],
        },
    }


def _fresh_latest(latest_by_team: Mapping[str, Any], *, cutoff: datetime) -> bool:
    max_age = _max_history_age_days()
    if max_age is None:
        return False
    for value in latest_by_team.values():
        latest = _parse_timestamp(value)
        if latest is None or latest >= cutoff:
            return False
        age_days = (cutoff - latest).total_seconds() / 86400
        if age_days < 0 or age_days > max_age:
            return False
    return True


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _provenance_is_reviewed(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("provider") != "openfootball" or value.get("repository") != "openfootball/espana":
        return False
    if not str(value.get("commit_sha") or "").strip():
        return False
    files = value.get("source_files")
    hashes = value.get("raw_sha256")
    if not isinstance(files, list) or not files or not all(isinstance(item, str) and item.strip() for item in files):
        return False
    if not isinstance(hashes, Mapping) or any(not isinstance(hashes.get(item), str) or not _SHA256_RE.fullmatch(hashes[item]) for item in files):
        return False
    return True


def _source_references(provenance: Mapping[str, Any], captured_at: str) -> tuple[list[dict[str, Any]], list[str]]:
    repo = str(provenance["repository"])
    commit = str(provenance["commit_sha"])
    references: list[dict[str, Any]] = []
    source_refs: list[str] = []
    for source_file in provenance["source_files"]:
        ref = f"{repo}@{commit}:{source_file}"
        source_refs.append(ref)
        references.append({"url": f"https://github.com/{repo}/blob/{commit}/{source_file}", "captured_at": captured_at, "source_record_ref": ref})
    return references, source_refs


def load_recent_form_cache(
    job: Mapping[str, Any],
    kickoff_at: str,
    now: datetime | str,
    *,
    cache_path: str | Path = CACHE_PATH,
) -> dict[str, Any] | None:
    """Load one exact fixture entry, recompute form, and fail closed on freshness."""

    payload = _read_json(Path(cache_path))
    kickoff = _parse_timestamp(kickoff_at)
    clock = _parse_timestamp(now)
    if not payload or kickoff is None or clock is None or payload.get("contract_version") != "recent_form_cache.v1":
        return None
    match_id = str(job.get("match_id") or "")
    home = str(job.get("home") or "")
    away = str(job.get("away") or "")
    entry = next((item for item in payload.get("fixtures", []) if isinstance(item, Mapping) and str(item.get("match_id") or "") == match_id and item.get("home") == home and item.get("away") == away), None)
    if not isinstance(entry, Mapping):
        return None
    generated = _parse_timestamp(entry.get("generated_at") or payload.get("generated_at"))
    cutoff = _parse_timestamp(entry.get("cutoff_at"))
    home_team_id = str(entry.get("home_team_id") or "")
    away_team_id = str(entry.get("away_team_id") or "")
    provenance = entry.get("provenance")
    if generated is None or cutoff is None or generated > clock or generated >= kickoff or cutoff > kickoff or not home_team_id or not away_team_id or not _provenance_is_reviewed(provenance):
        return None
    built = build_recent_form(entry.get("records") or [], home_team_id=home_team_id, away_team_id=away_team_id, cutoff_at=_iso(cutoff))
    if not built or not _fresh_latest(built["latest_by_team"], cutoff=cutoff):
        return None
    references, source_refs = _source_references(provenance, _iso(generated))
    return {
        "recent_form": built["recent_form"],
        "records": built["records"],
        "source": "openfootball_recent_form_cache",
        "captured_at": _iso(generated),
        "cutoff_at": _iso(cutoff),
        "references": references,
        "source_refs": source_refs,
        "provenance": dict(provenance),
    }


def _github_request(url: str, *, accept: str) -> bytes:
    headers = {"Accept": accept, "User-Agent": "football-betting-oneshot/recent-form"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def _github_json(url: str) -> dict[str, Any]:
    value = json.loads(_github_request(url, accept="application/vnd.github+json").decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GitHub API response is not an object")
    return value


def _build_provider_records(raw_sources: Iterable[Mapping[str, Any]], targets: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in raw_sources:
        raw_text = str(source["raw_text"])
        for row in parse_football_txt_rows(raw_text):
            for target in targets:
                provider_names = set(str(name) for name in target.get("provider_team_names") or [])
                target_id = str(target.get("canonical_team_id") or "")
                if row["home"] in provider_names:
                    records.append({
                        "team_id": target_id, "kickoff_at": row["kickoff_at"], "venue": "home", "goals_for": row["home_goals"], "goals_against": row["away_goals"],
                        "raw_home": row["home"], "raw_away": row["away"], "source_file": source["source_file"], "source_line": row["line_number"],
                        "provider_season_id": source.get("provider_season_id"),
                    })
                if row["away"] in provider_names:
                    records.append({
                        "team_id": target_id, "kickoff_at": row["kickoff_at"], "venue": "away", "goals_for": row["away_goals"], "goals_against": row["home_goals"],
                        "raw_home": row["home"], "raw_away": row["away"], "source_file": source["source_file"], "source_line": row["line_number"],
                        "provider_season_id": source.get("provider_season_id"),
                    })
    return records


def refresh_recent_form_cache(
    business_date: str,
    *,
    jobs: Iterable[Mapping[str, Any]],
    now: datetime | str | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
    cache_path: str | Path = CACHE_PATH,
) -> bool:
    """Refresh only demand-matched entries; network or quality failures retain cache."""

    clock = _parse_timestamp(now) if now is not None else _utc_now()
    if clock is None:
        return False
    try:
        manifest = _read_json(Path(manifest_path))
        if not manifest or manifest.get("repository") != "openfootball/espana":
            return False
        targets = [row for row in manifest.get("targets", []) if isinstance(row, Mapping)]
        demand = []
        for job in jobs:
            if not isinstance(job, Mapping):
                continue
            home_name = str(job.get("home") or "")
            away_name = str(job.get("away") or "")
            home_known = any(home_name in set(str(x) for x in target.get("project_names") or []) for target in targets)
            away_known = any(away_name in set(str(x) for x in target.get("project_names") or []) for target in targets)
            if not home_known or not away_known:
                continue
            kickoff = _parse_timestamp(job.get("kickoff"))
            if kickoff is not None and kickoff > clock:
                demand.append((job, kickoff))
        if not demand:
            return False
        repo = str(manifest["repository"])
        commit = str(manifest.get("commit_sha") or "").strip()
        if not commit:
            repo_meta = _github_json(f"https://api.github.com/repos/{repo}")
            branch = str(repo_meta.get("default_branch") or manifest.get("default_branch") or "master")
            branch_meta = _github_json(f"https://api.github.com/repos/{repo}/branches/{branch}")
            commit = str(((branch_meta.get("commit") or {}).get("sha") or "")).strip()
        if not commit:
            return False
        raw_sources: list[dict[str, Any]] = []
        for source in manifest.get("sources", []):
            source_file = str(source.get("source_file") or "")
            if not source_file:
                continue
            raw_bytes = _github_request(f"https://raw.githubusercontent.com/{repo}/{commit}/{source_file}", accept="text/plain")
            actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            expected_sha256 = str(source.get("raw_sha256") or "").strip().lower()
            if not expected_sha256 or actual_sha256 != expected_sha256:
                return False
            raw_sources.append({**dict(source), "raw_text": raw_bytes.decode("utf-8"), "raw_sha256": actual_sha256})
        normalized = _build_provider_records(raw_sources, targets)
        cache = _read_json(Path(cache_path)) or {"contract_version": "recent_form_cache.v1", "fixtures": []}
        fixtures = [item for item in cache.get("fixtures", []) if isinstance(item, Mapping)]
        refreshed = False
        for job, kickoff in demand:
            target_home = next((target for target in targets if str(job.get("home") or "") in set(str(x) for x in target.get("project_names") or [])), None)
            target_away = next((target for target in targets if str(job.get("away") or "") in set(str(x) for x in target.get("project_names") or [])), None)
            if not target_home or not target_away:
                continue
            built = build_recent_form(normalized, home_team_id=str(target_home["canonical_team_id"]), away_team_id=str(target_away["canonical_team_id"]), cutoff_at=_iso(kickoff))
            if not built or not _fresh_latest(built["latest_by_team"], cutoff=kickoff):
                continue
            provenance = {
                "provider": "openfootball",
                "repository": repo,
                "commit_sha": commit,
                "source_files": [str(source["source_file"]) for source in raw_sources],
                "raw_sha256": {str(source["source_file"]): str(source["raw_sha256"]) for source in raw_sources},
                "generated_at": _iso(clock),
                "cutoff_at": _iso(kickoff),
            }
            entry = {
                "match_id": str(job.get("match_id") or ""),
                "home": str(job.get("home") or ""), "away": str(job.get("away") or ""),
                "home_team_id": str(target_home["canonical_team_id"]), "away_team_id": str(target_away["canonical_team_id"]),
                "generated_at": _iso(clock), "cutoff_at": _iso(kickoff),
                "latest_by_team": built["latest_by_team"], "recent_form": built["recent_form"], "records": built["records"],
                "provenance": provenance,
            }
            fixtures = [item for item in fixtures if str(item.get("match_id") or "") != entry["match_id"]]
            fixtures.append(entry)
            refreshed = True
        if not refreshed:
            return False
        result = {"contract_version": "recent_form_cache.v1", "generated_at": _iso(clock), "business_date": business_date, "fixtures": fixtures}
        output = Path(cache_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


__all__ = ["build_recent_form", "load_recent_form_cache", "refresh_recent_form_cache"]
