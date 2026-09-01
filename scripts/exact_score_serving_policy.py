"""Cohort-level serving semantics for the exact-score prediction surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


NORMAL = "NORMAL"
DEGRADED = "DEGRADED"
UNVERIFIED = "UNVERIFIED"

_LABELS = {
    NORMAL: "系统首推比分",
    DEGRADED: "模型原始比分 · 当前不作为推荐",
    UNVERIFIED: "预测质量状态待确认 · 模型原始输出",
}
_NOTES = {
    NORMAL: "",
    DEGRADED: "当前比分推荐能力处于质量降级状态",
    UNVERIFIED: "",
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
