"""Cohort-level serving semantics for the exact-score prediction surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


NORMAL = "NORMAL"
DEGRADED = "DEGRADED"
UNVERIFIED = "UNVERIFIED"

_LABELS = {
    NORMAL: "\u7cfb\u7edf\u9996\u63a8\u6bd4\u5206",
    DEGRADED: "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u964d\u7ea7\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
    UNVERIFIED: "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350",
}
_NOTES = {
    NORMAL: "",
    DEGRADED: "\u5f71\u54cd\u6bd4\u5206\u9884\u6d4b\u63a8\u8350\u8bed\u4e49\uff1b\u4fdd\u7559\u539f\u59cb\u6bd4\u5206\u6982\u7387\uff0c\u4e0d\u4ee3\u8868\u786e\u5b9a\u7ed3\u679c\u3002",
    UNVERIFIED: "\u5f71\u54cd\u6bd4\u5206\u9884\u6d4b\u63a8\u8350\u8bed\u4e49\uff1b\u4fdd\u7559\u539f\u59cb\u6bd4\u5206\u6982\u7387\uff0c\u5f85\u5b8c\u6210\u8d28\u91cf\u786e\u8ba4\u3002",
}


def exact_score_serving_state(health: Mapping[str, Any] | None) -> str:
    """Resolve exact-score serving state from the current-cycle health contract."""

    if not isinstance(health, Mapping):
        return UNVERIFIED

    status = str(health.get("status") or "").strip().upper()
    current_serving = (
        health.get("scope") == "current_serving"
        and health.get("available") is True
    )
    matched = str(health.get("provenance_status") or "").strip().upper() == "MATCHED"

    if current_serving and matched and status == "HEALTHY":
        return NORMAL
    if current_serving and matched and status:
        return DEGRADED
    return UNVERIFIED


def exact_score_serving_presentation(health: Mapping[str, Any] | None) -> dict[str, str]:
    state = exact_score_serving_state(health)
    return {
        "state": state,
        "label": _LABELS[state],
        "note": _NOTES[state],
    }
