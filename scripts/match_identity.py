#!/usr/bin/env python3
"""Stable, provider-independent match identity helpers.

Provider ids remain aliases.  Automation state is keyed by the two teams and
kickoff time so a later Nowscore/500/Sporttery lookup cannot split one match
into several state machines.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from team_identity import canonical_team as shared_canonical_team

def canonical_team(value: Any) -> str:
    return shared_canonical_team(value)


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
