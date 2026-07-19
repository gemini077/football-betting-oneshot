#!/usr/bin/env python3
"""Fetch and parse post-match evidence without changing frozen predictions."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen


DETAIL_URL = "https://live.nowscore.com/detail/{match_id}cn.html?t=1"


def _text(fragment: Any) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", str(fragment or ""), flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def nowscore_match_id(report: dict, schedule: dict | None = None) -> str | None:
    """Recover a numeric Nowscore id from structured fields or verified URLs."""
    schedule = schedule or {}
    candidates = [
        schedule.get("nowscore_id"),
        schedule.get("shuju_id"),
        (report.get("match") or {}).get("nowscore_id"),
        (report.get("match") or {}).get("shuju_id"),
    ]
    for value in candidates:
        if str(value or "").isdigit():
            return str(value)
    serialized = json.dumps(report, ensure_ascii=False)
    patterns = (
        r"live\.nowscore\.com/(?:detail|analysis|1x2|panlu)/([0-9]+)",
        r"live\.nowscore\.com/(?:info/(?:coach|referee)|odds/match)/([0-9]+)",
        r"3in1Odds\.aspx\?[^\"']*\bid=([0-9]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, serialized, flags=re.I)
        if match:
            return match.group(1)
    return None


def parse_nowscore_detail(content: str, source_url: str) -> dict:
    score_match = re.search(
        r"class=['\"]ky_tit['\"][^>]*>.*?class=['\"]t15['\"]>(\d+)</span>.*?"
        r"class=['\"]t15['\"]>(\d+)</span>",
        content,
        flags=re.I | re.S,
    )
    score = f"{score_match.group(1)}-{score_match.group(2)}" if score_match else None

    venue_match = re.search(r"场地[：:]\s*([^<\r\n]+)", content)
    environment = venue_match.group(1).strip() if venue_match else None

    formations: dict[str, str] = {}
    for side, body in re.findall(r"<div\s+class=['\"](home|guest)['\"]>(.*?)</div>", content, flags=re.I | re.S):
        value = _text(body)
        formation_match = re.search(r"\b(\d(?:-\d){2,4})\b", value)
        if formation_match:
            formations["home" if side.lower() == "home" else "away"] = formation_match.group(1)

    statistics: dict[str, dict[str, str]] = {}
    stat_pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>.*?</td>\s*"
        r"<td[^>]*class=['\"][^'\"]*numberleft[^'\"]*['\"][^>]*>(.*?)</td>\s*"
        r"<td[^>]*>(.*?)</td>\s*"
        r"<td[^>]*class=['\"][^'\"]*numberright[^'\"]*['\"][^>]*>(.*?)</td>",
        flags=re.I | re.S,
    )
    for home_value, label, away_value in stat_pattern.findall(content):
        clean_label = _text(label)
        left, right = _text(home_value), _text(away_value)
        if clean_label and (left or right):
            statistics[clean_label] = {"home": left or "—", "away": right or "—"}

    events = []
    for kind, row_html in re.findall(
        r"<tr[^>]*data-kind=['\"]([^'\"]+)['\"][^>]*>(.*?)</tr>", content, flags=re.I | re.S
    ):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        if len(cells) < 5:
            continue
        minute_match = re.search(r"(\d+(?:\+\d+)?)'", _text(cells[2]))
        title_match = re.search(r"<img[^>]*title=['\"]([^'\"]+)['\"]", row_html, flags=re.I)
        left, right = _text(cells[0]), _text(cells[4])
        side = "home" if left else "away" if right else "unknown"
        event_type = "进球" if kind == "1" else html.unescape(title_match.group(1)) if title_match else f"事件{kind}"
        if kind not in {"1", "2", "3", "7", "8", "9", "11", "12"} and "进球" not in event_type and "红牌" not in event_type:
            continue
        events.append({
            "minute": minute_match.group(1) if minute_match else "—",
            "side": side,
            "type": event_type,
            "detail": left or right or event_type,
        })

    goals = [row for row in events if row.get("type") == "进球" or "入球" in str(row.get("type"))]
    half_home = half_away = 0
    for event in goals:
        try:
            minute = int(str(event.get("minute") or "0").split("+")[0])
        except ValueError:
            continue
        if minute <= 45:
            if event.get("side") == "home":
                half_home += 1
            elif event.get("side") == "away":
                half_away += 1

    return {
        "status": "verified" if score else "partial",
        "source": "Nowscore赛事详情",
        "source_url": source_url,
        "fetched_at": datetime.now().astimezone().isoformat(),
        "score_90m": score,
        "score_half_time": f"{half_home}-{half_away}" if goals else None,
        "environment": environment,
        "formations": formations,
        "key_events": events,
        "statistics": statistics,
        "evidence_rule": "赛后事实只用于验证和复盘，不回写冻结的赛前概率与首推。",
    }


def fetch_postmatch_evidence(report: dict, schedule: dict | None = None, timeout: float = 15.0) -> dict:
    match_id = nowscore_match_id(report, schedule)
    if not match_id:
        return {"status": "unavailable", "reason": "missing_nowscore_match_id"}
    url = DETAIL_URL.format(match_id=match_id)
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 FootballBettingOneShot/1.0"})
        with urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8-sig", errors="replace")
    except Exception as exc:  # keep result verification/review fail-open
        return {"status": "unavailable", "source_url": url, "reason": f"fetch_failed:{type(exc).__name__}"}
    evidence = parse_nowscore_detail(content, url)
    evidence["nowscore_match_id"] = match_id
    return evidence
