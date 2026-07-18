#!/usr/bin/env python3
"""Read public 500/SPdex exchange snapshots as a bounded analysis fallback."""

from __future__ import annotations

import html as html_lib
import re
import urllib.request
from typing import Any


INDEX_URL = "https://c.spdex.com/spdex500b"
DETAIL_URL = "https://c.spdex.com/IFrame/IframeViewerQQ.aspx?id={match_id}"


def _text(value: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _number(value: str) -> float | None:
    cleaned = _text(value).replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned) if cleaned not in {"", "-"} else None
    except ValueError:
        return None


def parse_index(page: str) -> list[dict[str, str]]:
    rows = []
    pattern = re.compile(
        r"<h3\s+tid=['\"](?P<id>\d+)['\"]>\[竞彩(?P<date>\d+)期第(?P<num>\d+)场\]\s*\\?"
        r"(?P<home>.*?)\s+VS\s+(?P<away>.*?)</h3>.*?开赛时间：(?P<kickoff>[^<]+)",
        re.I | re.S,
    )
    for match in pattern.finditer(page or ""):
        rows.append({key: _text(value) for key, value in match.groupdict().items()})
    return rows


def parse_detail(page: str) -> dict[str, Any]:
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", page or "", re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.I | re.S)
        if len(cells) < 9:
            continue
        volume = _number(cells[2])
        ratio = _number(cells[3])
        if volume is None or ratio is None:
            continue
        rows.append({
            "team": _text(cells[0]),
            "betfair_index": _number(cells[1]),
            "betfair_volume": int(volume),
            "volume_ratio_pct": ratio,
            "page_simulated_pl": _number(cells[4]),
            "betfair_price": _number(cells[5]),
            "listed_index_pct": _number(cells[6]),
            "euro_average": _number(cells[7]),
            "kelly_variance": _number(cells[8]),
        })
    if len(rows) < 3:
        return {}
    total = re.search(r"交易量总成交：\s*([\d,]+)", page or "")
    updated = re.search(r"更新时间：\s*([^<]+)", page or "")
    return {
        "betfair": dict(zip(("home", "draw", "away"), rows[:3])),
        "total_volume": int(total.group(1).replace(",", "")) if total else sum(row["betfair_volume"] for row in rows[:3]),
        "betfair_metadata": {
            "market_type": "betfair_exchange",
            "source": "500.com_spdex_public_snapshot",
            "completeness": "complete" if all(row.get("betfair_price") is not None for row in rows[:3]) else "partial",
            "volume_scope": "visible_page_exchange_volume",
            "updated_at_source": _text(updated.group(1)) if updated else None,
        },
    }


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://zx.500.com/"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_snapshot(home: str, away: str, match_num: str | None = None) -> dict[str, Any]:
    index = parse_index(_fetch(INDEX_URL))
    digits = re.sub(r"\D+", "", str(match_num or ""))[-3:]
    norm = lambda value: re.sub(r"\W+", "", str(value or "")).casefold()
    selected = next((row for row in index if digits and row["num"].zfill(3) == digits), None)
    if selected is None:
        selected = next((row for row in index if norm(home) in norm(row["home"]) and norm(away) in norm(row["away"])), None)
    if selected is None:
        return {"status": "NO_MATCH"}
    parsed = parse_detail(_fetch(DETAIL_URL.format(match_id=selected["id"])))
    return {**parsed, "status": "OK" if parsed.get("betfair") else "NO_DATA", "spdex_match": selected,
            "source_url": DETAIL_URL.format(match_id=selected["id"])}


def merge_into(deep: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("status") != "OK":
        return deep
    touzhu = deep.setdefault("touzhu", {})
    primary = touzhu.setdefault("betfair", {})
    for outcome, fallback in (snapshot.get("betfair") or {}).items():
        current = primary.setdefault(outcome, {})
        for field, value in fallback.items():
            if current.get(field) in (None, "") and value not in (None, ""):
                current[field] = value
    touzhu["total_volume"] = touzhu.get("total_volume") or snapshot.get("total_volume")
    missing = [outcome for outcome, row in primary.items() if row.get("betfair_price") is None]
    touzhu["betfair_metadata"] = {
        **(touzhu.get("betfair_metadata") or {}),
        "source": "500.com_touzhu_plus_spdex_public_snapshot",
        "fallback_source_url": snapshot.get("source_url"),
        "completeness": "partial" if missing else "complete",
        "missing_price_outcomes": missing,
        "volume_scope": "visible_page_exchange_volume",
    }
    return deep
