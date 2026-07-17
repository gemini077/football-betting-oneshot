#!/usr/bin/env python3
"""Read-only Nowscore schedule matching and three-in-one market parser.

The public three-in-one page contains, per company, opening/current Asian
handicap, 1X2 and goal-total quotes.  A snapshot is accepted only after the
home team, away team and kickoff have been checked in the same orientation.
"""

from __future__ import annotations

import argparse
import ast
import html as html_lib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "data" / "team_aliases.json"
CACHE_ROOT = ROOT / "data" / "source_cache" / "nowscore"
SCHEDULE_URL = "https://live.nowscore.com/data/bf1.js"
MARKET_URL = "https://live.nowscore.com/odds/match/{match_id}.htm"
ANALYSIS_DATA_URL = "https://live.nowscore.com/analysisJs/data{match_id}.js"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")

# Stable Nowscore company IDs mapped to this project's confirmed canonical
# bookmaker IDs.  The original provider ID is retained on every row.
COMPANIES = {
    1: (5, "澳门"),
    3: (280, "皇冠"),
    4: (2, "立博"),
    8: (3, "bet365"),
    9: (293, "威廉希尔"),
    12: (9, "易胜博"),
    14: (6, "伟德"),
    19: (4, "Interwetten"),
    24: (16, "12bet"),
    31: (651, "利记"),
    47: (1055, "Pinnacle"),
    49: (11, "Bwin"),
}


def _fetch_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/javascript,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "identity",
            "Referer": "https://live.nowscore.com/",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_js_values(raw: str) -> list[object]:
    values: list[str] = []
    current: list[str] = []
    quote = None
    escaped = False
    for char in raw:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quote:
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            current.append(char)
            quote = char
        elif char == ",":
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    values.append("".join(current).strip())

    parsed: list[object] = []
    for token in values:
        if not token or token in ("null", "undefined"):
            parsed.append(None)
        elif len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            parsed.append(token[1:-1].replace("\\'", "'").replace('\\"', '"'))
        else:
            try:
                parsed.append(float(token) if "." in token else int(token))
            except ValueError:
                parsed.append(token)
    return parsed


def parse_schedule_js(text: str) -> list[dict]:
    matches = []
    for found in re.finditer(r"(?m)^A\[\d+\]=\[(.*?)\];\s*$", text):
        row = _split_js_values(found.group(1))
        if len(row) < 12:
            continue
        try:
            date_parts = [int(value) for value in str(row[11]).split(",")]
            kickoff = datetime(
                date_parts[0], date_parts[1] + 1, date_parts[2],
                date_parts[3], date_parts[4], date_parts[5], tzinfo=SHANGHAI,
            )
            match_id = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        matches.append({
            "nowscore_id": match_id,
            "home_team": str(row[4] or "").strip(),
            "home_team_en": str(row[6] or "").strip(),
            "away_team": str(row[7] or "").strip(),
            "away_team_en": str(row[9] or "").strip(),
            "kickoff_local": kickoff.isoformat(timespec="minutes"),
            "schedule_open_handicap": row[25] if len(row) > 25 else None,
            "schedule_total_line": row[29] if len(row) > 29 else None,
        })
    return matches


def _normal(value: object) -> str:
    text = str(value or "").casefold().replace("(主)", "")
    text = text.replace("(主)", "").replace("(中)", "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text)


def _alias_groups() -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    try:
        payload = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return groups
    for team in payload.get("teams") or []:
        names = {_normal(team.get("canonical"))}
        names.update(_normal(item) for item in team.get("aliases") or [])
        names.discard("")
        for name in names:
            groups[name] = names
    return groups


def _names(value: str, groups: dict[str, set[str]]) -> set[str]:
    normalized = _normal(value)
    return set(groups.get(normalized) or {normalized}) - {""}


def _team_score(target: set[str], provider: set[str]) -> float:
    if target & provider:
        return 1.0
    for left in target:
        for right in provider:
            if min(len(left), len(right)) >= 4 and (left in right or right in left):
                return 0.88
    return 0.0


def _parse_kickoff(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def resolve_match(
    home: str,
    away: str,
    kickoff: object,
    schedule: list[dict],
    maximum_kickoff_difference_minutes: int = 180,
) -> dict:
    groups = _alias_groups()
    target_home, target_away = _names(home, groups), _names(away, groups)
    target_time = _parse_kickoff(kickoff)
    candidates = []
    for match in schedule:
        provider_home = _names(match.get("home_team", ""), groups) | _names(match.get("home_team_en", ""), groups)
        provider_away = _names(match.get("away_team", ""), groups) | _names(match.get("away_team_en", ""), groups)
        home_score = _team_score(target_home, provider_home)
        away_score = _team_score(target_away, provider_away)
        provider_time = _parse_kickoff(match.get("kickoff_local"))
        difference = (
            abs((provider_time - target_time).total_seconds()) / 60
            if provider_time and target_time else None
        )
        if home_score < 0.88 or away_score < 0.88:
            continue
        if difference is not None and difference > maximum_kickoff_difference_minutes:
            continue
        candidates.append({
            **match,
            "home_match_score": home_score,
            "away_match_score": away_score,
            "kickoff_difference_minutes": difference,
        })
    candidates.sort(key=lambda row: (row["home_match_score"] + row["away_match_score"], -(row["kickoff_difference_minutes"] or 0)), reverse=True)
    if not candidates:
        return {"status": "NO_EXACT_MATCH", "home": home, "away": away, "kickoff": str(kickoff or "")}
    best = candidates[0]
    if len(candidates) > 1:
        first_key = (best["home_match_score"] + best["away_match_score"], best["kickoff_difference_minutes"])
        second = candidates[1]
        second_key = (second["home_match_score"] + second["away_match_score"], second["kickoff_difference_minutes"])
        if first_key == second_key:
            return {"status": "AMBIGUOUS_MATCH", "candidates": candidates[:5]}
    return {"status": "EXACT_MATCH", **best}


class _OddsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.in_row = False
        self.in_cell = False
        self.cells: list[str] = []
        self.cell_text: list[str] = []
        self.company_id: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr" and "datatr" in str(attributes.get("class") or "").split():
            self.in_row, self.cells, self.company_id = True, [], None
        elif self.in_row and tag == "td":
            self.in_cell, self.cell_text = True, []
        elif self.in_row and tag == "a":
            found = re.search(r"companyid=(\d+)", str(attributes.get("href") or ""), re.I)
            if found and self.company_id is None:
                self.company_id = int(found.group(1))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_row and self.in_cell:
            self.cells.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append({"company_id": self.company_id, "cells": self.cells})
            self.in_row = False


def _number(value: object, minimum: float | None = None) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    return number


def handicap_number(value: object) -> float | None:
    text = str(value or "").strip().replace("球", "")
    if not text:
        return None
    numeric = _number(text)
    if numeric is not None:
        return numeric
    receiving = text.startswith("受")
    text = text.removeprefix("受")
    values = {
        "平手": 0.0, "平/半": 0.25, "半": 0.5, "半/一": 0.75,
        "一": 1.0, "一/球半": 1.25, "球半": 1.5, "球半/两": 1.75,
        "两": 2.0, "两/两球半": 2.25, "两球半": 2.5,
        "两球半/三": 2.75, "三": 3.0, "三/三球半": 3.25,
        "三球半": 3.5, "三球半/四": 3.75, "四": 4.0,
    }
    depth = values.get(text)
    if depth is None:
        return None
    return depth if receiving else -depth


def _identity(html: str) -> dict:
    def find(pattern: str) -> str | None:
        found = re.search(pattern, html, re.I | re.S)
        return html_lib.unescape(re.sub(r"<[^>]+>", "", found.group(1))).strip() if found else None
    return {
        "nowscore_id": int(find(r'id=["\']hide_scheduleId["\'][^>]*value=["\'](\d+)') or 0),
        "kickoff_local": find(r'id=["\']hide_matchTime["\'][^>]*value=["\']([^"\']+)'),
        "home_team": find(r'<div[^>]+id=["\']home["\'][^>]*>.*?<a[^>]+class=["\']name["\'][^>]*>(.*?)</a>'),
        "away_team": find(r'<div[^>]+id=["\']guest["\'][^>]*>.*?<a[^>]+class=["\']name["\'][^>]*>(.*?)</a>'),
    }


def parse_three_in_one(html: str) -> dict:
    parser = _OddsTableParser()
    parser.feed(html)
    bookmakers, asian, totals = [], [], []
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 19:
            continue
        provider_id = row.get("company_id")
        canonical_id, canonical_name = COMPANIES.get(provider_id, (provider_id, cells[0].replace("*", "").strip() or f"Nowscore-{provider_id}"))
        common = {"name": canonical_name, "cid": canonical_id, "source_company_id": provider_id, "source": "nowscore_3in1"}
        spf_open = {"home": _number(cells[7], 1.0), "draw": _number(cells[8], 1.0), "away": _number(cells[9], 1.0)}
        spf_current = {"home": _number(cells[10], 1.0), "draw": _number(cells[11], 1.0), "away": _number(cells[12], 1.0)}
        if any(value is not None for value in (*spf_open.values(), *spf_current.values())):
            bookmakers.append({**common, "spf_open": spf_open, "spf_current": spf_current})
        open_handicap, current_handicap = handicap_number(cells[2]), handicap_number(cells[5])
        if open_handicap is not None or current_handicap is not None:
            asian.append({
                **common,
                "open_handicap": open_handicap, "current_handicap": current_handicap,
                "open_water_home": _number(cells[1]), "open_water_away": _number(cells[3]),
                "current_water_home": _number(cells[4]), "current_water_away": _number(cells[6]),
            })
        open_total, current_total = _number(cells[14]), _number(cells[17])
        if open_total is not None or current_total is not None:
            totals.append({
                **common,
                "open_line": open_total, "current_line": current_total,
                "open_over_water": _number(cells[13]), "open_under_water": _number(cells[15]),
                "current_over_water": _number(cells[16]), "current_under_water": _number(cells[18]),
            })

    valid_current = [row["spf_current"] for row in bookmakers if all((row.get("spf_current") or {}).get(key) for key in ("home", "draw", "away"))]
    summary = {}
    if valid_current:
        summary["avg_spf_current"] = {
            key: round(sum(row[key] for row in valid_current) / len(valid_current), 4)
            for key in ("home", "draw", "away")
        }
    pinnacle_book = next((row for row in bookmakers if row.get("cid") == 1055), None)
    pinnacle_asian = next((row for row in asian if row.get("cid") == 1055), None)
    return {
        "identity": _identity(html),
        "ouzhi": {"bookmakers": bookmakers, "pinnacle": pinnacle_book, "summary": summary, "total": len(bookmakers), "source": "nowscore_3in1"},
        "yazhi": {"companies": asian, "pinnacle": pinnacle_asian, "total": len(asian), "source": "nowscore_3in1"},
        "daxiao": {"companies": totals, "total": len(totals), "source": "nowscore_3in1"},
    }


def _analysis_array(text: str, name: str) -> list[list[object]]:
    """Read one literal match-history array from Nowscore analysis JS."""
    found = re.search(rf"var\s+{re.escape(name)}\s*=\s*(\[.*?\]);\s*var\s+", text, re.S)
    if not found:
        return []
    try:
        value = ast.literal_eval(found.group(1))
    except (SyntaxError, ValueError):
        return []
    return [row for row in value if isinstance(row, list) and len(row) >= 10]


def _target_team_id(rows: list[list[object]]) -> int | None:
    ids: Counter[int] = Counter()
    for row in rows:
        for index in (4, 6):
            try:
                ids[int(row[index])] += 1
            except (TypeError, ValueError, IndexError):
                continue
    return ids.most_common(1)[0][0] if ids else None


def _form_summary(rows: list[list[object]], team_id: int, venue: str | None = None, limit: int = 10) -> dict:
    selected = []
    for row in rows:
        try:
            home_id, away_id = int(row[4]), int(row[6])
            home_goals, away_goals = int(row[8]), int(row[9])
        except (TypeError, ValueError, IndexError):
            continue
        is_home, is_away = home_id == team_id, away_id == team_id
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        selected.append((home_goals, away_goals) if is_home else (away_goals, home_goals))
        if len(selected) >= limit:
            break
    wins = sum(gf > ga for gf, ga in selected)
    draws = sum(gf == ga for gf, ga in selected)
    return {
        "matches": len(selected), "wins": wins, "draws": draws,
        "losses": len(selected) - wins - draws,
        "goals_for": sum(gf for gf, _ in selected),
        "goals_against": sum(ga for _, ga in selected),
    }


def parse_analysis_data(text: str) -> dict:
    """Build the recent-form contract consumed by the deterministic model."""
    home_rows, away_rows = _analysis_array(text, "h_data"), _analysis_array(text, "a_data")
    home_id, away_id = _target_team_id(home_rows), _target_team_id(away_rows)
    if home_id is None or away_id is None:
        return {}
    recent_form = {
        "home_overall": _form_summary(home_rows, home_id),
        "home_home": _form_summary(home_rows, home_id, "home"),
        "away_overall": _form_summary(away_rows, away_id),
        "away_away": _form_summary(away_rows, away_id, "away"),
    }
    if not all(item.get("matches") for item in recent_form.values()):
        return {}
    return {
        "recent_form": recent_form,
        "source_note": "Nowscore analysis recent results; actual goals, not xG",
        "team_ids": {"home": home_id, "away": away_id},
    }


def _verified(target: dict, page_identity: dict, maximum_minutes: int = 180) -> tuple[bool, list[str]]:
    groups = _alias_groups()
    reasons = []
    home_score = _team_score(_names(target.get("home", ""), groups), _names(page_identity.get("home_team", ""), groups))
    away_score = _team_score(_names(target.get("away", ""), groups), _names(page_identity.get("away_team", ""), groups))
    if home_score < 0.88:
        reasons.append("HOME_TEAM_MISMATCH")
    if away_score < 0.88:
        reasons.append("AWAY_TEAM_MISMATCH")
    target_time, page_time = _parse_kickoff(target.get("kickoff")), _parse_kickoff(page_identity.get("kickoff_local"))
    if target_time and page_time and abs((target_time - page_time).total_seconds()) / 60 > maximum_minutes:
        reasons.append("KICKOFF_MISMATCH")
    return not reasons, reasons


def fetch_match_markets(home: str, away: str, kickoff: object, explicit_id: int | None = None, no_cache: bool = False) -> dict:
    fetched_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    try:
        schedule_raw = _fetch_bytes(f"{SCHEDULE_URL}?_={int(time.time())}")
        schedule_text = _decode(schedule_raw)
        schedule = parse_schedule_js(schedule_text)
    except Exception as error:
        schedule, schedule_text = [], ""
        schedule_error = f"{type(error).__name__}: {error}"
    else:
        schedule_error = None

    if explicit_id:
        resolved = {"status": "EXPLICIT_ID", "nowscore_id": int(explicit_id)}
    else:
        resolved = resolve_match(home, away, kickoff, schedule)
    if not resolved.get("nowscore_id"):
        return {
            "source": "nowscore_public_3in1", "status": resolved.get("status"),
            "fetched_at": fetched_at, "target": {"home": home, "away": away, "kickoff": str(kickoff or "")},
            "schedule_count": len(schedule), "schedule_error": schedule_error, "resolution": resolved,
        }

    match_id = int(resolved["nowscore_id"])
    cache_path = CACHE_ROOT / "raw" / f"{match_id}_3in1.html"
    raw = None
    if not no_cache and cache_path.exists() and time.time() - cache_path.stat().st_mtime < 3600:
        raw = cache_path.read_bytes()
    if raw is None:
        try:
            raw = _fetch_bytes(MARKET_URL.format(match_id=match_id))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {
                "source": "nowscore_public_3in1", "status": "FETCH_ERROR", "fetched_at": fetched_at,
                "nowscore_id": match_id, "resolution": resolved, "error": f"{type(error).__name__}: {error}",
            }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
    parsed = parse_three_in_one(_decode(raw))
    target = {"home": home, "away": away, "kickoff": kickoff}
    verified, reasons = _verified(target, parsed["identity"])
    if not verified:
        return {
            "source": "nowscore_public_3in1", "status": "IDENTITY_MISMATCH", "fetched_at": fetched_at,
            "nowscore_id": match_id, "target": target, "page_identity": parsed["identity"],
            "identity_errors": reasons, "resolution": resolved,
        }
    analysis_error = None
    shuju = {}
    analysis_cache = CACHE_ROOT / "raw" / f"{match_id}_analysis.js"
    analysis_raw = None
    if not no_cache and analysis_cache.exists() and time.time() - analysis_cache.stat().st_mtime < 3600:
        analysis_raw = analysis_cache.read_bytes()
    if analysis_raw is None:
        try:
            analysis_raw = _fetch_bytes(ANALYSIS_DATA_URL.format(match_id=match_id))
            analysis_cache.parent.mkdir(parents=True, exist_ok=True)
            analysis_cache.write_bytes(analysis_raw)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            analysis_error = f"{type(error).__name__}: {error}"
    if analysis_raw is not None:
        shuju = parse_analysis_data(_decode(analysis_raw))
        if not shuju:
            analysis_error = "RECENT_FORM_PARSE_EMPTY"
    return {
        "source": "nowscore_public_3in1", "status": "OK", "fetched_at": fetched_at,
        "nowscore_id": match_id, "target": target, "resolution": resolved,
        "identity": parsed["identity"], "source_url": MARKET_URL.format(match_id=match_id),
        "ouzhi": parsed["ouzhi"], "yazhi": parsed["yazhi"], "daxiao": parsed["daxiao"],
        "shuju": shuju,
        "analysis_source_url": ANALYSIS_DATA_URL.format(match_id=match_id),
        "analysis_error": analysis_error,
        "quality": {
            "home_away_kickoff_verified": True,
            "bookmaker_count": parsed["ouzhi"]["total"],
            "asian_count": parsed["yazhi"]["total"],
            "total_count": parsed["daxiao"]["total"],
            "recent_form_complete": bool((shuju.get("recent_form") or {})),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--kickoff", required=True)
    parser.add_argument("--nowscore-id", type=int)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = fetch_match_markets(args.home, args.away, args.kickoff, args.nowscore_id, args.no_cache)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
