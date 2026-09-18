#!/usr/bin/env python3
"""Shadow-only free result federation for overdue FBOS matches.

This module never writes formal result artifacts. It combines:
- Reep CC0 identity data (Wikidata QID -> provider team IDs),
- Wikidata search as a multilingual bootstrap fallback,
- Sofascore and FotMob public match boards.

Promotion into the formal post-match authority is intentionally out of scope.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
TRUST_PATH = BASE_DIR / "data" / "prediction_quality" / "current_champion_trust.json"

REEP_TEAMS_URL = "https://raw.githubusercontent.com/withqwerty/reep/main/data/teams.csv"
REEP_NAMES_URL = "https://raw.githubusercontent.com/withqwerty/reep/main/data/names.csv"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SOFASCORE_BASES = (
    "https://www.sofascore.com/api/v1",
    "https://api.sofascore.com/api/v1",
)
FOTMOB_BASE = "https://www.fotmob.com/api/data"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)
IDENTITY_USER_AGENT = "FBOS-result-shadow/0.1 (+https://github.com/gemini077/football-betting-oneshot)"
OVERDUE_AFTER = timedelta(hours=3)
LOOKBACK = timedelta(days=14)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\s\-_.·'’/()（）]+", "", text)
    return text


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    retries: int = 2,
) -> bytes:
    merged = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
    }
    if headers:
        merged.update(headers)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=merged)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # network errors are evidence in shadow mode
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(1.0 + attempt, 2.0))
    raise RuntimeError(f"GET failed: {url}: {last}")


def _request_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    raw = _request_bytes(url, headers=headers)
    return json.loads(raw.decode("utf-8-sig"))


def _request_text(url: str) -> str:
    raw = _request_bytes(
        url,
        headers={"User-Agent": IDENTITY_USER_AGENT, "Accept": "text/csv,text/plain,*/*"},
        timeout=30,
    )
    return raw.decode("utf-8-sig")


def build_reep_indexes(
    teams_csv: str,
    names_csv: str,
) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    teams: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(teams_csv)):
        qid = str(row.get("key_wikidata") or "").strip()
        if qid:
            teams[qid] = {str(k): str(v or "").strip() for k, v in row.items()}

    aliases: dict[str, set[str]] = {}
    for row in csv.DictReader(io.StringIO(names_csv)):
        qid = str(row.get("key_wikidata") or "").strip()
        if not qid:
            continue
        values = [row.get("name"), row.get("alias")]
        for value in values:
            if not value:
                continue
            for part in re.split(r"[|;]", str(value)):
                key = _norm(part)
                if key:
                    aliases.setdefault(key, set()).add(qid)

    for qid, row in teams.items():
        key = _norm(row.get("name"))
        if key:
            aliases.setdefault(key, set()).add(qid)
    return teams, aliases


def choose_wikidata_candidate(payload: Any, query: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    candidates = []
    query_norm = _norm(query)
    for item in payload.get("search") or []:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or "").casefold()
        if not any(token in desc for token in ("football club", "soccer club", "association football")):
            continue
        label = str(item.get("label") or "")
        match_text = str((item.get("match") or {}).get("text") or "")
        exact = query_norm in {_norm(label), _norm(match_text)}
        candidates.append((1 if exact else 0, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def resolve_qid(
    name: str,
    aliases: dict[str, set[str]],
) -> dict[str, Any]:
    direct = sorted(aliases.get(_norm(name), set()))
    if len(direct) == 1:
        return {"status": "RESOLVED", "qid": direct[0], "source": "reep_alias"}
    if len(direct) > 1:
        return {"status": "AMBIGUOUS", "source": "reep_alias", "candidates": direct}

    query = urllib.parse.urlencode(
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "zh",
            "uselang": "en",
            "format": "json",
            "limit": 8,
            "type": "item",
        }
    )
    try:
        payload = _request_json(
            f"{WIKIDATA_API}?{query}",
            headers={"User-Agent": IDENTITY_USER_AGENT, "Referer": "https://www.wikidata.org/"},
        )
    except Exception as exc:
        return {"status": "ERROR", "source": "wikidata", "error": str(exc)}
    picked = choose_wikidata_candidate(payload, name)
    if not picked:
        return {"status": "UNRESOLVED", "source": "wikidata"}
    return {
        "status": "RESOLVED",
        "qid": str(picked.get("id") or ""),
        "label": picked.get("label"),
        "description": picked.get("description"),
        "source": "wikidata",
    }


def _provider_id(team: dict[str, str] | None, key: str) -> str | None:
    if not team:
        return None
    value = str(team.get(key) or "").strip()
    return value or None


def _event_dt_seconds(value: Any) -> datetime | None:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw > 10_000_000_000:
        raw /= 1000.0
    try:
        return datetime.fromtimestamp(raw, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _within_kickoff(candidate: datetime | None, target: datetime, minutes: int = 45) -> bool:
    if candidate is None:
        return False
    return abs((candidate - target).total_seconds()) <= minutes * 60


def _as_int_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip() or None


def match_sofascore_event(
    events: list[Any],
    *,
    home_id: str,
    away_id: str,
    kickoff: datetime,
) -> dict[str, Any] | None:
    matches = []
    for event in events:
        if not isinstance(event, dict):
            continue
        h = _as_int_text((event.get("homeTeam") or {}).get("id"))
        a = _as_int_text((event.get("awayTeam") or {}).get("id"))
        if h != _as_int_text(home_id) or a != _as_int_text(away_id):
            continue
        start = _event_dt_seconds(event.get("startTimestamp"))
        if not _within_kickoff(start, kickoff):
            continue
        matches.append(event)
    return matches[0] if len(matches) == 1 else None


def _fotmob_team_id(row: dict[str, Any], side: str) -> str | None:
    for key in (side, f"{side}Team"):
        value = row.get(key)
        if isinstance(value, dict) and value.get("id") not in (None, ""):
            return _as_int_text(value.get("id"))
    return None


def _fotmob_kickoff(row: dict[str, Any]) -> datetime | None:
    for value in (row.get("timeTS"), row.get("startTimestamp")):
        parsed = _event_dt_seconds(value)
        if parsed:
            return parsed
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    return _parse_dt(status.get("utcTime") or row.get("utcTime"))


def match_fotmob_event(
    rows: list[Any],
    *,
    home_id: str,
    away_id: str,
    kickoff: datetime,
) -> dict[str, Any] | None:
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _fotmob_team_id(row, "home") != _as_int_text(home_id):
            continue
        if _fotmob_team_id(row, "away") != _as_int_text(away_id):
            continue
        if not _within_kickoff(_fotmob_kickoff(row), kickoff):
            continue
        matches.append(row)
    return matches[0] if len(matches) == 1 else None


def sofascore_summary(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {"identity": "NO_MATCH"}
    status = str((event.get("status") or {}).get("type") or "").lower()
    mapped = {
        "finished": "FINISHED",
        "postponed": "POSTPONED",
        "canceled": "CANCELLED",
        "cancelled": "CANCELLED",
        "abandoned": "ABANDONED",
        "interrupted": "INTERRUPTED",
        "inprogress": "LIVE",
        "notstarted": "SCHEDULED",
    }.get(status, status.upper() or "UNKNOWN")
    hs = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    aws = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    home = hs.get("normaltime")
    away = aws.get("normaltime")
    score = None
    if home is not None and away is not None:
        score = f"{int(home)}-{int(away)}"
    elif mapped == "FINISHED" and hs.get("current") is not None and aws.get("current") is not None:
        if hs.get("overtime") is None and aws.get("overtime") is None and hs.get("penalties") is None and aws.get("penalties") is None:
            score = f"{int(hs['current'])}-{int(aws['current'])}"
    return {
        "identity": "MATCHED",
        "event_id": event.get("id"),
        "status": mapped,
        "score_90m_candidate": score,
        "score_basis": "normaltime" if home is not None and away is not None else "current_without_overtime",
        "home": (event.get("homeTeam") or {}).get("name"),
        "away": (event.get("awayTeam") or {}).get("name"),
    }


def _parse_score(value: Any) -> str | None:
    match = re.search(r"(\d+)\s*[-:]\s*(\d+)", str(value or ""))
    return f"{int(match.group(1))}-{int(match.group(2))}" if match else None


def fotmob_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"identity": "NO_MATCH"}
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    reason = status.get("reason") if isinstance(status.get("reason"), dict) else {}
    reason_text = str(reason.get("short") or reason.get("long") or "").upper()
    if status.get("cancelled") is True:
        mapped = "CANCELLED"
    elif status.get("finished") is True:
        mapped = "FINISHED"
    elif status.get("started") is True:
        mapped = "LIVE"
    elif "POSTPON" in reason_text:
        mapped = "POSTPONED"
    else:
        mapped = "SCHEDULED"
    score = _parse_score(status.get("scoreStr") or row.get("scoreStr")) if mapped == "FINISHED" else None
    return {
        "identity": "MATCHED",
        "event_id": row.get("id") or row.get("matchId"),
        "status": mapped,
        "score_fulltime_candidate": score,
        "score_basis": "fotmob_scoreStr",
        "status_reason": reason_text or None,
        "home": (row.get("home") or row.get("homeTeam") or {}).get("name")
        if isinstance(row.get("home") or row.get("homeTeam"), dict)
        else None,
        "away": (row.get("away") or row.get("awayTeam") or {}).get("name")
        if isinstance(row.get("away") or row.get("awayTeam"), dict)
        else None,
    }


def adjudicate(sofa: dict[str, Any], fotmob: dict[str, Any]) -> dict[str, Any]:
    s_status, f_status = sofa.get("status"), fotmob.get("status")
    s_score = sofa.get("score_90m_candidate")
    f_score = fotmob.get("score_fulltime_candidate")
    non_played = {"POSTPONED", "CANCELLED", "ABANDONED", "INTERRUPTED"}

    if s_status == "FINISHED" and f_status == "FINISHED":
        if s_score and f_score and s_score == f_score:
            return {"decision": "CONSENSUS_FINISHED_SCORE", "score_90m_candidate": s_score}
        return {"decision": "CONFLICT", "reason": "finished_score_mismatch_or_scope_unknown"}
    if s_status in non_played and f_status in non_played:
        return {"decision": "CONSENSUS_NON_PLAYED", "statuses": [s_status, f_status]}
    if (s_status == "FINISHED" and f_status in non_played) or (f_status == "FINISHED" and s_status in non_played):
        return {"decision": "CONFLICT", "reason": "finished_vs_non_played"}
    if s_status == "FINISHED" and s_score:
        return {"decision": "SINGLE_SOURCE_FINISHED", "provider": "sofascore", "score_90m_candidate": s_score}
    if f_status == "FINISHED" and f_score:
        return {"decision": "SINGLE_SOURCE_FINISHED", "provider": "fotmob", "score_fulltime_candidate": f_score}
    if sofa.get("identity") == "NO_MATCH" and fotmob.get("identity") == "NO_MATCH":
        return {"decision": "NO_PROVIDER_MATCH"}
    return {"decision": "UNRESOLVED_STATUS", "statuses": [s_status, f_status]}


def current_overdue_matches(now: datetime, max_matches: int) -> list[dict[str, Any]]:
    trust = json.loads(TRUST_PATH.read_text(encoding="utf-8"))
    rows = []
    lower = now - LOOKBACK
    for row in trust.get("history") or []:
        if not isinstance(row, dict) or str(row.get("status") or "").upper() != "PENDING":
            continue
        kickoff = _parse_dt(row.get("kickoff_at"))
        if not kickoff or kickoff > now - OVERDUE_AFTER or kickoff < lower:
            continue
        rows.append({
            "match_key": row.get("match_key"),
            "prediction_id": row.get("prediction_id"),
            "home": row.get("home"),
            "away": row.get("away"),
            "kickoff_at": kickoff.isoformat(),
        })
    rows.sort(key=lambda item: str(item.get("kickoff_at") or ""))
    return rows[:max_matches]


def _flatten_fotmob(payload: Any) -> list[Any]:
    rows = []
    if not isinstance(payload, dict):
        return rows
    for league in payload.get("leagues") or []:
        if isinstance(league, dict):
            rows.extend(league.get("matches") or [])
    return rows


def _fetch_sofascore(date: str) -> tuple[list[Any], str | None]:
    errors = []
    for base in SOFASCORE_BASES:
        url = f"{base}/sport/football/scheduled-events/{date}"
        try:
            payload = _request_json(
                url,
                headers={
                    "Referer": "https://www.sofascore.com/",
                    "Origin": "https://www.sofascore.com",
                },
            )
            events = payload.get("events") if isinstance(payload, dict) else None
            if isinstance(events, list):
                return events, None
            errors.append(f"{base}: events_missing")
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    return [], "; ".join(errors)


def _fetch_fotmob(date: str) -> tuple[list[Any], str | None]:
    ymd = date.replace("-", "")
    url = (
        f"{FOTMOB_BASE}/matches?date={ymd}"
        "&timezone=UTC&ccode3=USA"
    )
    try:
        payload = _request_json(
            url,
            headers={"Referer": "https://www.fotmob.com/"},
        )
        return _flatten_fotmob(payload), None
    except Exception as exc:
        return [], str(exc)


def run_shadow(max_matches: int = 12) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    try:
        teams_csv = _request_text(REEP_TEAMS_URL)
        names_csv = _request_text(REEP_NAMES_URL)
        teams, aliases = build_reep_indexes(teams_csv, names_csv)
        identity_error = None
    except Exception as exc:
        teams, aliases = {}, {}
        identity_error = str(exc)

    board_cache: dict[tuple[str, str], tuple[list[Any], str | None]] = {}
    results = []
    for target in current_overdue_matches(now, max_matches):
        kickoff = _parse_dt(target["kickoff_at"])
        assert kickoff is not None
        home_identity = resolve_qid(str(target.get("home") or ""), aliases)
        away_identity = resolve_qid(str(target.get("away") or ""), aliases)
        row: dict[str, Any] = {
            **target,
            "home_identity": home_identity,
            "away_identity": away_identity,
        }
        if home_identity.get("status") != "RESOLVED" or away_identity.get("status") != "RESOLVED":
            row["decision"] = {"decision": "IDENTITY_UNRESOLVED"}
            results.append(row)
            continue

        home_team = teams.get(str(home_identity.get("qid")))
        away_team = teams.get(str(away_identity.get("qid")))
        ids = {
            "sofascore_home": _provider_id(home_team, "key_sofascore"),
            "sofascore_away": _provider_id(away_team, "key_sofascore"),
            "fotmob_home": _provider_id(home_team, "key_fotmob"),
            "fotmob_away": _provider_id(away_team, "key_fotmob"),
        }
        row["provider_team_ids"] = ids

        date = kickoff.date().isoformat()
        sofa: dict[str, Any] = {"identity": "NO_MATCH"}
        fotmob: dict[str, Any] = {"identity": "NO_MATCH"}

        if ids["sofascore_home"] and ids["sofascore_away"]:
            key = ("sofascore", date)
            if key not in board_cache:
                board_cache[key] = _fetch_sofascore(date)
            events, error = board_cache[key]
            event = match_sofascore_event(
                events,
                home_id=str(ids["sofascore_home"]),
                away_id=str(ids["sofascore_away"]),
                kickoff=kickoff,
            )
            sofa = sofascore_summary(event)
            if error:
                sofa["fetch_error"] = error
        else:
            sofa = {"identity": "TEAM_ID_MISSING"}

        if ids["fotmob_home"] and ids["fotmob_away"]:
            key = ("fotmob", date)
            if key not in board_cache:
                board_cache[key] = _fetch_fotmob(date)
            events, error = board_cache[key]
            event = match_fotmob_event(
                events,
                home_id=str(ids["fotmob_home"]),
                away_id=str(ids["fotmob_away"]),
                kickoff=kickoff,
            )
            fotmob = fotmob_summary(event)
            if error:
                fotmob["fetch_error"] = error
        else:
            fotmob = {"identity": "TEAM_ID_MISSING"}

        row["providers"] = {"sofascore": sofa, "fotmob": fotmob}
        row["decision"] = adjudicate(sofa, fotmob)
        results.append(row)

    counts: dict[str, int] = {}
    for row in results:
        decision = str((row.get("decision") or {}).get("decision") or "UNKNOWN")
        counts[decision] = counts.get(decision, 0) + 1
    return {
        "contract_version": "result_federation_shadow.v1",
        "generated_at": now.isoformat(),
        "formal_write_authorized": False,
        "identity_sources": ["reep_cc0", "wikidata"],
        "result_sources": ["sofascore", "fotmob"],
        "identity_bootstrap_error": identity_error,
        "target_count": len(results),
        "decision_counts": counts,
        "matches": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("result_federation_shadow.json"))
    parser.add_argument("--max-matches", type=int, default=12)
    args = parser.parse_args()

    report = run_shadow(max(1, args.max_matches))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "contract_version": report["contract_version"],
        "target_count": report["target_count"],
        "decision_counts": report["decision_counts"],
        "identity_bootstrap_error": report["identity_bootstrap_error"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
