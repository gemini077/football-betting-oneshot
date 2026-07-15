#!/usr/bin/env python3
"""Bind frozen paper contracts to the first verified user-channel quote."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = PROJECT_ROOT / "data" / "live_odds_bridge" / "first_quotes.json"
DEFAULT_ALIASES = PROJECT_ROOT / "data" / "team_aliases.json"
DEFAULT_OVERRIDES = PROJECT_ROOT / "data" / "paper_ledger" / "initial_price_overrides.json"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value or "").casefold())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _alias_set(name: Any, registry: dict) -> set[str]:
    canonical = str(name or "").strip()
    values = {canonical}
    for row in registry.get("teams") or []:
        candidates = {str(row.get("canonical") or "").strip(), *map(str, row.get("aliases") or [])}
        if canonical in candidates:
            values.update(candidates)
    return {_norm(value) for value in values if _norm(value)}


def _kickoff_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _match_archive(ticket: dict, archive: dict, registry: dict) -> tuple[str, dict] | None:
    home_names = _alias_set(ticket.get("home"), registry)
    away_names = _alias_set(ticket.get("away"), registry)
    kickoff = _kickoff_ms(ticket.get("kickoff_local"))
    tolerance = int((registry.get("safety") or {}).get("maximum_kickoff_difference_minutes", 180)) * 60000
    matches = []
    for match_id, row in (archive.get("matches") or {}).items():
        metadata = row.get("metadata") or {}
        if _norm(metadata.get("home_name")) not in home_names or _norm(metadata.get("away_name")) not in away_names:
            continue
        source_kickoff = _number(metadata.get("kickoff_timestamp"))
        if kickoff is not None and source_kickoff is not None and abs(kickoff - source_kickoff) > tolerance:
            continue
        matches.append((str(match_id), row))
    return matches[0] if len(matches) == 1 else None


def _score_quote(ticket: dict, archive_match: dict) -> dict | None:
    target = str(ticket.get("selection") or "").replace(":", "-").strip()
    candidates = []
    for quote in (archive_match.get("quotes") or {}).values():
        if str(quote.get("market_code") or "") not in {"7", "1100484"}:
            continue
        line = str(quote.get("handicap_line") or quote.get("selection_name") or "").replace(":", "-").strip()
        if line != target:
            continue
        if quote.get("odds_scale_verified") is not True:
            continue
        odds = _number(quote.get("inferred_decimal_odds"))
        if odds is None or odds <= 1:
            continue
        candidates.append(quote)
    return min(candidates, key=lambda row: str(row.get("received_at") or row.get("captured_at") or "")) if candidates else None


def sync_channel_price_overrides(
    tickets: list[dict],
    *,
    archive_path: Path = DEFAULT_ARCHIVE,
    aliases_path: Path = DEFAULT_ALIASES,
    overrides_path: Path = DEFAULT_OVERRIDES,
) -> dict:
    """Add only missing verified first prices; never replace a frozen price."""
    archive = _load(archive_path, {"matches": {}})
    registry = _load(aliases_path, {"teams": [], "safety": {}})
    payload = _load(overrides_path, {"schema_version": "1.0", "tickets": {}})
    overrides = payload.setdefault("tickets", {})
    added = []
    for ticket in tickets:
        ticket_id = str(ticket.get("ticket_id") or "")
        if not ticket_id or ticket_id in overrides or _number(ticket.get("odds")) is not None:
            continue
        if ticket.get("ticket_type") != "correct_score":
            continue
        matched = _match_archive(ticket, archive, registry)
        if not matched:
            continue
        source_match_id, archive_match = matched
        quote = _score_quote(ticket, archive_match)
        if not quote:
            continue
        odds = float(quote["inferred_decimal_odds"])
        probability = _number(ticket.get("probability"))
        overrides[ticket_id] = {
            "odds": odds,
            "probability": probability,
            "ev": round(probability * odds - 1, 8) if probability is not None else None,
            "price_source": f"首次抓取｜用户渠道 全场波胆 {ticket.get('selection')}",
            "price_captured_at": quote.get("received_at") or quote.get("captured_at"),
            "source_match_id": source_match_id,
            "market_code": quote.get("market_code"),
            "odds_scale_verified": True,
        }
        added.append(ticket_id)
    if added:
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = overrides_path.with_name(f".{overrides_path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(overrides_path)
    return {"added": added, "override_count": len(overrides)}
