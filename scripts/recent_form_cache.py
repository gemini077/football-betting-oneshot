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
SOUTH_AMERICA_MANIFEST_PATH = PROJECT_ROOT / "data" / "football_data" / "openfootball" / "south_america_brazil_source_manifest.json"
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


_REVIEWED_IDENTITY_METHODS = frozenset({
    "manual_verified",
    "provider_id_exact",
    "existing_crosswalk",
    "exact_alias",
    "cross_source_context_verified",
})
_OPENFOOTBALL_REPOSITORIES = frozenset({"openfootball/espana", "openfootball/south-america"})


def _reviewed_targets(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = [dict(row) for row in manifest.get("targets", []) if isinstance(row, Mapping)]
    evidence_ref = str(manifest.get("identity_evidence_path") or "").strip()
    if not evidence_ref:
        return targets
    relative = Path(evidence_ref)
    if relative.is_absolute():
        return []
    evidence = _read_json(PROJECT_ROOT / relative)
    if not evidence:
        return []
    rows = evidence.get("teams") or evidence.get("mappings") or []
    reviewed = {
        (str(row.get("provider_team_name") or ""), str(row.get("canonical_team_id") or ""))
        for row in rows
        if isinstance(row, Mapping)
        and row.get("verified") is True
        and str(row.get("resolution_method") or "") in _REVIEWED_IDENTITY_METHODS
    }
    return [
        target for target in targets
        if str(target.get("canonical_team_id") or "")
        and all((str(name), str(target["canonical_team_id"])) in reviewed for name in target.get("provider_team_names") or [])
    ]


def _provenance_is_reviewed(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("provider") != "openfootball" or value.get("repository") not in _OPENFOOTBALL_REPOSITORIES:
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
        "source": str(provenance.get("cache_source") or "openfootball_recent_form_cache"),
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


def _manifest_paths(manifest_path: str | Path | None) -> list[Path]:
    if manifest_path is not None:
        return [Path(manifest_path)]
    return [MANIFEST_PATH, SOUTH_AMERICA_MANIFEST_PATH]


def _source_url(manifest: Mapping[str, Any], source: Mapping[str, Any], commit: str) -> str:
    explicit = str(source.get("source_url") or "").strip()
    if explicit:
        return explicit
    template = str(manifest.get("source_url_template") or "").strip()
    if not template:
        template = "https://raw.githubusercontent.com/{repository}/{commit_sha}/{source_file}"
    return template.format(
        repository=str(manifest.get("repository") or ""),
        commit_sha=commit,
        source_file=str(source.get("source_file") or ""),
    )


def _load_manifest_sources(manifest: Mapping[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    provider = str(manifest.get("provider") or "openfootball")
    repository = str(manifest.get("repository") or "")
    commit = str(manifest.get("commit_sha") or "").strip()
    if provider != "openfootball" or repository not in _OPENFOOTBALL_REPOSITORIES or not commit:
        raise ValueError("manifest is not a pinned reviewed OpenFootball source")
    allowed_history = manifest.get("allowed_history_competition_keys")
    if isinstance(allowed_history, list) and any(not isinstance(item, str) for item in allowed_history):
        raise ValueError("manifest history competition allowlist is invalid")
    allowed_history_set = set(allowed_history or [])
    raw_sources: list[dict[str, Any]] = []
    raw_by_url: dict[str, bytes] = {}
    for source in manifest.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        source_file = str(source.get("source_file") or "").strip()
        competition_key = str(source.get("competition_key") or "").strip()
        url = _source_url(manifest, source, commit)
        if allowed_history_set and competition_key not in allowed_history_set:
            raise ValueError("source competition is outside the reviewed history allowlist")
        if not source_file or not url.startswith("https://raw.githubusercontent.com/"):
            raise ValueError("source is not pinned")
        raw_bytes = raw_by_url.get(url)
        if raw_bytes is None:
            raw_bytes = _github_request(url, accept="text/plain")
            raw_by_url[url] = raw_bytes
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        expected_sha256 = str(source.get("raw_sha256") or "").strip().lower()
        if not expected_sha256 or actual_sha256 != expected_sha256:
            raise ValueError("source hash mismatch")
        raw_sources.append({
            **dict(source),
            "provider": provider,
            "source_url": url,
            "raw_text": raw_bytes.decode("utf-8"),
            "raw_sha256": actual_sha256,
        })
    if not raw_sources:
        raise ValueError("manifest has no sources")
    return provider, commit, raw_sources


def _manifest_demand(manifest: Mapping[str, Any], jobs: list[Mapping[str, Any]], clock: datetime) -> list[tuple[Mapping[str, Any], datetime, Mapping[str, Any], Mapping[str, Any]]]:
    targets = _reviewed_targets(manifest)
    allowed_competitions = manifest.get("allowed_fixture_competition_names")
    if isinstance(allowed_competitions, list) and not all(isinstance(item, str) for item in allowed_competitions):
        return []
    demand: list[tuple[Mapping[str, Any], datetime, Mapping[str, Any], Mapping[str, Any]]] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        if allowed_competitions and str(job.get("league") or "") not in set(allowed_competitions):
            continue
        home_name = str(job.get("home") or "")
        away_name = str(job.get("away") or "")
        target_home = next((target for target in targets if home_name in {str(x) for x in target.get("project_names") or []}), None)
        target_away = next((target for target in targets if away_name in {str(x) for x in target.get("project_names") or []}), None)
        kickoff = _parse_timestamp(job.get("kickoff"))
        if target_home and target_away and kickoff is not None and kickoff > clock:
            demand.append((job, kickoff, target_home, target_away))
    return demand


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def refresh_recent_form_cache(
    business_date: str,
    *,
    jobs: Iterable[Mapping[str, Any]],
    now: datetime | str | None = None,
    manifest_path: str | Path | None = None,
    cache_path: str | Path = CACHE_PATH,
) -> bool:
    """Refresh exact target demand from pinned OpenFootball manifests."""

    clock = _parse_timestamp(now) if now is not None else _utc_now()
    if clock is None:
        return False
    jobs_list = [job for job in jobs if isinstance(job, Mapping)]
    cache = _read_json(Path(cache_path)) or {"contract_version": "recent_form_cache.v1", "fixtures": []}
    fixtures = [item for item in cache.get("fixtures", []) if isinstance(item, Mapping)]
    refreshed = False
    try:
        for candidate_path in _manifest_paths(manifest_path):
            manifest = _read_json(candidate_path)
            if not manifest:
                continue
            demand = _manifest_demand(manifest, jobs_list, clock)
            if not demand:
                continue
            try:
                provider, commit, raw_sources = _load_manifest_sources(manifest)
                targets = _reviewed_targets(manifest)
                normalized = _build_provider_records(raw_sources, targets)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                continue
            source_files = _unique_strings(source.get("source_file") for source in raw_sources)
            source_hashes = {str(source["source_file"]): str(source["raw_sha256"]) for source in raw_sources}
            for job, kickoff, target_home, target_away in demand:
                built = build_recent_form(
                    normalized,
                    home_team_id=str(target_home["canonical_team_id"]),
                    away_team_id=str(target_away["canonical_team_id"]),
                    cutoff_at=_iso(kickoff),
                )
                if not built or not _fresh_latest(built["latest_by_team"], cutoff=kickoff):
                    continue
                provenance = {
                    "provider": provider,
                    "repository": str(manifest["repository"]),
                    "commit_sha": commit,
                    "source_files": source_files,
                    "raw_sha256": source_hashes,
                    "generated_at": _iso(clock),
                    "cutoff_at": _iso(kickoff),
                    "cache_source": "openfootball_recent_form_cache",
                    "competition_keys": _unique_strings(source.get("competition_key") for source in raw_sources),
                }
                entry = {
                    "match_id": str(job.get("match_id") or ""),
                    "home": str(job.get("home") or ""),
                    "away": str(job.get("away") or ""),
                    "home_team_id": str(target_home["canonical_team_id"]),
                    "away_team_id": str(target_away["canonical_team_id"]),
                    "generated_at": _iso(clock),
                    "cutoff_at": _iso(kickoff),
                    "latest_by_team": built["latest_by_team"],
                    "recent_form": built["recent_form"],
                    "records": built["records"],
                    "provenance": provenance,
                }
                fixtures = [item for item in fixtures if str(item.get("match_id") or "") != entry["match_id"]]
                fixtures.append(entry)
                refreshed = True
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return refreshed
    if not refreshed:
        return False
    result = {"contract_version": "recent_form_cache.v1", "generated_at": _iso(clock), "business_date": business_date, "fixtures": fixtures}
    output = Path(cache_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


__all__ = ["build_recent_form", "load_recent_form_cache", "refresh_recent_form_cache"]
