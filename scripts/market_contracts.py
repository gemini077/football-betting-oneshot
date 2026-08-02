#!/usr/bin/env python3
"""Shared 90-minute market contract settlement rules.

Every frozen prediction is a contract.  Keeping settlement in one small
module prevents the primary market, the per-market audit and calibration from
silently using different rules.
"""

from __future__ import annotations

import math
import re
from typing import Any


def split_quarter_line(line: float) -> tuple[float, ...]:
    quarter = round(float(line) * 4) / 4
    if int(round(abs(quarter) * 4)) % 2:
        lower = math.floor(quarter * 2) / 2
        return (lower, lower + 0.5)
    return (quarter,)


def settle_contract(contract: dict | None, score: tuple[int, int]) -> dict:
    """Settle one frozen contract against a verified 90-minute score."""
    contract = contract or {}
    family = str(contract.get("family") or "")
    selection = str(contract.get("selection") or "")
    home, away = score
    outcome = "home" if home > away else "draw" if home == away else "away"
    units: float | None

    if family == "1x2":
        units = 1.0 if selection == outcome else -1.0
    elif family == "double_chance":
        covered = {"1x": {"home", "draw"}, "x2": {"draw", "away"}, "12": {"home", "away"}}.get(selection)
        units = (1.0 if outcome in covered else -1.0) if covered else None
    elif family == "btts":
        actual = "yes" if home > 0 and away > 0 else "no"
        units = 1.0 if selection == actual else -1.0
    elif family in {"total", "asian_handicap"}:
        try:
            line = float(contract["line"])
        except (KeyError, TypeError, ValueError):
            units = None
        else:
            parts = []
            for component in split_quarter_line(line):
                if family == "total":
                    delta = home + away - component
                    if selection == "under":
                        delta = -delta
                else:
                    delta = home - away + component
                    if selection == "away":
                        delta = -delta
                parts.append(1.0 if delta > 0 else 0.0 if delta == 0 else -1.0)
            units = sum(parts) / len(parts)
    elif family == "exact_total":
        target = str(contract.get("goals") or "")
        if target == "6+":
            units = 1.0 if home + away >= 6 else -1.0
        else:
            try:
                units = 1.0 if home + away == int(target) else -1.0
            except (TypeError, ValueError):
                units = None
    elif family == "exact_score":
        units = 1.0 if str(contract.get("score") or "") == f"{home}-{away}" else -1.0
    else:
        units = None

    labels = {1.0: "\u8d62", 0.5: "\u534a\u8d62", 0.0: "\u8d70\u76d8", -0.5: "\u534a\u8f93", -1.0: "\u8f93", None: "\u4e0d\u53ef\u7ed3\u7b97"}
    return {
        "contract_id": contract.get("contract_id"),
        "family": family or None,
        "selection": selection or None,
        "label": contract.get("label"),
        "units": units,
        "outcome": labels.get(units, "\u4e0d\u53ef\u7ed3\u7b97"),
        "hit": True if units is not None and units > 0 else False if units is not None and units < 0 else None,
        "actual_score": f"{home}-{away}",
    }


def contract_profit(contract: dict, units: float | None) -> float | None:
    if units is None or not contract.get("price_executable"):
        return None
    try:
        odds = float(contract["odds"])
    except (KeyError, TypeError, ValueError):
        return None
    if odds <= 1:
        return None
    return units * (odds - 1) if units > 0 else units


def legacy_contract(text: Any) -> dict | None:
    """Parse old primary text so reports created before contract IDs settle."""
    value = str(text or "")
    if "\u4e3b\u961f\u4e0d\u8d25" in value or "1X" in value.upper():
        return {"family": "double_chance", "selection": "1x", "label": "\u4e3b\u961f\u4e0d\u8d25\uff081X\uff09"}
    if "\u5ba2\u961f\u4e0d\u8d25" in value or "X2" in value.upper():
        return {"family": "double_chance", "selection": "x2", "label": "\u5ba2\u961f\u4e0d\u8d25\uff08X2\uff09"}
    if "\u4e0d\u5e73" in value or re.search(r"(?<!\w)12(?!\w)", value):
        return {"family": "double_chance", "selection": "12", "label": "\u4e0d\u5e73\uff0812\uff09"}
    labels = {"\u4e3b\u80dc": "home", "\u5e73\u5c40": "draw", "\u5ba2\u80dc": "away"}
    for label, selection in labels.items():
        if label in value:
            return {"family": "1x2", "selection": selection, "label": label}
    total = re.search(r"([\u5927\u5c0f])\s*(\d+(?:\.\d+)?)", value)
    if total:
        return {"family": "total", "selection": "over" if total.group(1) == "\u5927" else "under", "line": float(total.group(2)), "label": f"{total.group(1)}{float(total.group(2)):g}"}
    if "BTTS" in value.upper() or "\u53cc\u65b9\u8fdb\u7403" in value:
        yes = any(token in value for token in ("\u662f", "Yes", "YES"))
        suffix = "\u662f" if yes else "\u5426"
        return {"family": "btts", "selection": "yes" if yes else "no", "label": f"\u53cc\u65b9\u8fdb\u7403{suffix}"}
    return None
