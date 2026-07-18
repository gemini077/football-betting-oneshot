#!/usr/bin/env python3
"""Persistent verified cross-provider match identities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from match_identity import canonical_match_id


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "provider_match_crosswalk.json"


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("matches", {})
    return payload


def lookup(match: dict[str, Any], provider: str, path: Path = REGISTRY_PATH) -> dict[str, Any] | None:
    row = (load_registry(path).get("matches") or {}).get(canonical_match_id(match))
    provider_row = (row or {}).get("providers", {}).get(provider)
    return provider_row if isinstance(provider_row, dict) else None


def record_binding(
    match: dict[str, Any], provider: str, provider_id: Any, *, confidence: float,
    verification: str, provider_home: str = "", provider_away: str = "",
    provider_kickoff: str = "", path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    payload = load_registry(path)
    key = canonical_match_id(match)
    row = (payload["matches"] or {}).setdefault(key, {
        "canonical_match_id": key,
        "home": match.get("home") or match.get("home_team"),
        "away": match.get("away") or match.get("away_team"),
        "kickoff": match.get("kickoff") or match.get("kickoff_local"),
        "providers": {},
    })
    row.setdefault("providers", {})[provider] = {
        "id": provider_id,
        "confidence": round(float(confidence), 6),
        "verification": verification,
        "provider_home": provider_home,
        "provider_away": provider_away,
        "provider_kickoff": provider_kickoff,
        "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return row["providers"][provider]
