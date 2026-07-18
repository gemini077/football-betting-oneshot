#!/usr/bin/env python3
"""Stable, provider-independent match identity helpers.

Provider ids remain aliases.  Automation state is keyed by the two teams and
kickoff time so a later Nowscore/500/Sporttery lookup cannot split one match
into several state machines.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALIAS_PATH = ROOT / "data" / "team_aliases.json"


def _text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _alias_map() -> dict[str, str]:
    if not ALIAS_PATH.exists():
        return {}
    try:
        payload = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, str] = {}
    rows = payload.get("aliases") if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        for canonical, aliases in rows.items():
            result[_text(canonical)] = _text(canonical)
            if isinstance(aliases, list):
                for alias in aliases:
                    result[_text(alias)] = _text(canonical)
            elif aliases:
                result[_text(aliases)] = _text(canonical)
    return result


def canonical_team(value: Any) -> str:
    token = _text(value)
    return _alias_map().get(token, token)


def parse_kickoff(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def canonical_match_id(match: dict[str, Any]) -> str:
    home = canonical_team(match.get("home") or match.get("home_team"))
    away = canonical_team(match.get("away") or match.get("away_team"))
    kickoff = parse_kickoff(match.get("kickoff") or match.get("kickoff_local"))
    stamp = kickoff.strftime("%Y%m%d%H%M") if kickoff else "unknown"
    basis = f"{home}|{away}|{stamp}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"FBOS-{stamp}-{digest}"


def identity_aliases(match: dict[str, Any]) -> set[str]:
    aliases = {canonical_match_id(match)}
    for field in ("id", "match_id", "match_key", "shuju_id", "nowscore_id"):
        value = match.get(field)
        if value not in (None, ""):
            aliases.add(str(value))
            if field == "shuju_id":
                aliases.add(f"shuju:{value}")
    home = match.get("home") or match.get("home_team")
    away = match.get("away") or match.get("away_team")
    if home and away:
        aliases.add(f"{home}|{away}")
        aliases.add(f"{home} vs {away}")
    return aliases
