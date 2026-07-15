#!/usr/bin/env python3
"""Public, read-only Polymarket football market snapshots.

This module intentionally contains no authentication, wallet, order, position,
or trading code.  Its output is an uncalibrated market-evidence snapshot and is
never an executable price source for Football Betting OneShot.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone


GAMMA_BASE = "https://gamma-api.polymarket.com"
PUBLIC_MARKET_TYPES = (
    "moneyline",
    "totals",
    "spreads",
    "both_teams_to_score",
    "correct_score",
    "soccer_exact_score",
    "soccer_halftime_result",
    "first_half_moneyline",
    "first_half_totals",
    "soccer_team_totals",
    "total_goals",
    "double_chance",
)
USER_AGENT = "FootballBettingOneShot/0.8.0 public-read-only"


def _jsonish(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fold(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_json(path: str, params: dict, timeout: int = 20):
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{GAMMA_BASE}{path}?{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_active_markets(market_types=PUBLIC_MARKET_TYPES, limit_per_type: int = 200) -> list[dict]:
    """Fetch public active markets using GET only."""
    by_id: dict[str, dict] = {}
    for market_type in market_types:
        rows = _get_json(
            "/markets",
            {
                "limit": limit_per_type,
                "active": "true",
                "closed": "false",
                "sports_market_types": market_type,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        for row in rows if isinstance(rows, list) else []:
            by_id[str(row.get("id"))] = row
    return list(by_id.values())


def _event(market: dict) -> dict:
    events = market.get("events") or []
    return events[0] if events and isinstance(events[0], dict) else {}


def match_markets(
    markets: list[dict],
    home: str,
    away: str,
    kickoff: str | None = None,
    tolerance_hours: float = 18.0,
) -> tuple[list[dict], dict]:
    """Bind only an exact home/away event title, optionally constrained by kickoff."""
    target_home, target_away = _fold(home), _fold(away)
    target_time = _parse_time(kickoff)
    groups: dict[str, list[dict]] = {}
    group_meta: dict[str, dict] = {}
    for market in markets:
        event = _event(market)
        group_id = str(event.get("gameId") or event.get("id") or event.get("slug") or "")
        title = event.get("title") or ""
        folded = _fold(title)
        pair_labels = (f"{target_home} vs {target_away}", f"{target_home} v {target_away}")
        exact_pair = any(folded == label or folded.startswith(label + " ") for label in pair_labels)
        if not group_id or not exact_pair:
            continue
        event_time = _parse_time(event.get("startTime") or market.get("gameStartTime") or event.get("endDate"))
        delta_hours = None
        if target_time and event_time:
            delta_hours = abs((event_time - target_time).total_seconds()) / 3600
            if delta_hours > tolerance_hours:
                continue
        groups.setdefault(group_id, []).append(market)
        group_meta[group_id] = {
            "event_id": str(event.get("id")) if event.get("id") is not None else None,
            "game_id": event.get("gameId"),
            "event_slug": event.get("slug"),
            "event_title": title,
            "kickoff_utc": event_time.isoformat().replace("+00:00", "Z") if event_time else None,
            "kickoff_delta_hours": delta_hours,
        }
    if not groups:
        return [], {"status": "NO_EXACT_EVENT_MATCH", "method": "exact_team_pair_and_optional_kickoff"}
    group_id = max(groups, key=lambda key: (len(groups[key]), sum(_float(x.get("liquidityNum")) or 0 for x in groups[key])))
    return groups[group_id], {"status": "EXACT_EVENT_MATCH", "method": "exact_team_pair_and_optional_kickoff", **group_meta[group_id]}


def _scope(market: dict) -> str:
    description = _fold(market.get("description"))
    if (
        "first 90 minutes of regular play plus stoppage time" in description
        or "end of 90 minutes of regulation plus stoppage time" in description
    ):
        return "regulation_90m_plus_stoppage"
    if "including extra time" in description or "penalty shootout" in description:
        return "includes_extra_time_or_penalties"
    return "unverified"


def normalize_market(market: dict) -> dict:
    event = _event(market)
    outcomes = _jsonish(market.get("outcomes"), [])
    outcome_prices = [_float(value) for value in _jsonish(market.get("outcomePrices"), [])]
    token_ids = [str(value) for value in _jsonish(market.get("clobTokenIds"), [])]
    settlement_scope = _scope(market)
    return {
        "market_id": str(market.get("id")),
        "condition_id": market.get("conditionId"),
        "event_id": str(event.get("id")) if event.get("id") is not None else None,
        "event_title": event.get("title"),
        "event_slug": event.get("slug"),
        "game_id": event.get("gameId"),
        "market_type": market.get("sportsMarketType"),
        "question": market.get("question"),
        "selection_label": market.get("groupItemTitle"),
        "line": market.get("line"),
        "outcomes": outcomes,
        "outcome_prices": outcome_prices,
        "clob_token_ids": token_ids,
        "yes_token_id": token_ids[0] if token_ids else None,
        "best_bid": _float(market.get("bestBid")),
        "best_ask": _float(market.get("bestAsk")),
        "last_trade_price": _float(market.get("lastTradePrice")),
        "spread": _float(market.get("spread")),
        "liquidity": _float(market.get("liquidityNum")),
        "volume_24h": _float(market.get("volume24hr")),
        "fees_enabled": bool(market.get("feesEnabled")),
        "fee_schedule": market.get("feeSchedule"),
        "resolution_source": market.get("resolutionSource") or event.get("resolutionSource"),
        "settlement_scope": settlement_scope,
        "eligible_for_90m_comparison": settlement_scope == "regulation_90m_plus_stoppage",
        "active": bool(market.get("active")),
        "closed": bool(market.get("closed")),
        "accepting_orders": bool(market.get("acceptingOrders")),
        "clear_book_on_start": bool(market.get("clearBookOnStart")),
    }


def _mid(row: dict) -> float | None:
    bid, ask = row.get("best_bid"), row.get("best_ask")
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2
    prices = row.get("outcome_prices") or []
    return prices[0] if prices else None


def build_snapshot(raw_markets: list[dict], home: str, away: str, kickoff: str | None = None) -> dict:
    matched, match = match_markets(raw_markets, home, away, kickoff)
    normalized = [normalize_market(row) for row in matched]
    moneyline = [row for row in normalized if row.get("market_type") == "moneyline"]
    three_way: dict[str, dict] = {}
    for row in moneyline:
        label = _fold(row.get("selection_label"))
        if label == _fold(home):
            outcome = "home"
        elif label == _fold(away):
            outcome = "away"
        elif label.startswith("draw"):
            outcome = "draw"
        else:
            continue
        mid = _mid(row)
        three_way[outcome] = {**row, "mid": mid}
    complete = all(key in three_way for key in ("home", "draw", "away"))
    mids = {key: three_way[key]["mid"] for key in ("home", "draw", "away")} if complete else {}
    complete = complete and all(value is not None and value > 0 for value in mids.values())
    normalized_mids = None
    if complete:
        total = sum(mids.values())
        normalized_mids = {key: value / total for key, value in mids.items()}
    score_rows = [
        {**row, "mid": _mid(row)}
        for row in normalized
        if row.get("market_type") in ("correct_score", "soccer_exact_score")
    ]
    has_other_score = any("other" in _fold(row.get("selection_label")) for row in score_rows)
    scope_values = sorted({row.get("settlement_scope") for row in normalized})
    core_rows = [
        row for row in normalized
        if row.get("market_type") in ("moneyline", "correct_score", "soccer_exact_score")
    ]
    scope_compatible = bool(core_rows) and all(row.get("eligible_for_90m_comparison") for row in core_rows)
    return {
        "schema_version": "1.0",
        "source": "polymarket_public_gamma",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analysis_input_only": True,
        "uncalibrated_signal_only": True,
        "used_for_model_probability": False,
        "used_for_ev": False,
        "execution_source": False,
        "authentication_used": False,
        "account_connected": False,
        "trading_enabled": False,
        "target": {"home": home, "away": away, "kickoff": kickoff},
        "match": match,
        "settlement": {
            "required_scope": "regulation_90m_plus_stoppage",
            "observed_scopes": scope_values,
            "compatible": scope_compatible,
        },
        "three_way_consensus": {
            "complete": complete,
            "outcomes": three_way,
            "mid_sum": sum(mids.values()) if complete else None,
            "normalized_mid_probabilities": normalized_mids,
            "usage": "market_consensus_diagnostic_only",
        },
        "correct_score": {
            "contracts": score_rows,
            "has_any_other_score_tail": has_other_score,
            "complete_distribution": bool(score_rows) and has_other_score,
            "usage": "market_consensus_diagnostic_only",
        },
        "markets": normalized,
        "quality_flags": [
            flag
            for flag, present in (
                ("NO_EXACT_EVENT_MATCH", not normalized),
                ("SETTLEMENT_SCOPE_NOT_CONFIRMED", normalized and not scope_compatible),
                ("INCOMPLETE_THREE_WAY_SET", normalized and not complete),
                ("CORRECT_SCORE_TAIL_MISSING", bool(score_rows) and not has_other_score),
            )
            if present
        ],
    }


def fetch_snapshot(home: str, away: str, kickoff: str | None = None) -> dict:
    return build_snapshot(fetch_active_markets(), home, away, kickoff)
