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
_STATUS_COPY = {
    "INSUFFICIENT_SAMPLE": {
        "label": "\u6bd4\u5206\u9884\u6d4b\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
        "note": "\u5f53\u524d\u6709\u6548\u6837\u672c\u4e0d\u8db3\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350\uff1b\u539f\u59cb\u6bd4\u5206\u6982\u7387\u7ee7\u7eed\u4fdd\u7559\u3002\u0031X2\u3001\u53cc\u65b9\u8fdb\u7403\u3001\u5927\u5c0f\u0032.5\u6309\u5404\u81ea\u6982\u7387\u5c55\u793a\u3002",
        "local_label": "\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
    },
    "ALERT": {
        "label": "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
        "note": "\u5f53\u524d\u8d28\u91cf\u5f02\u5e38\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350\uff1b\u539f\u59cb\u6bd4\u5206\u6982\u7387\u7ee7\u7eed\u4fdd\u7559\u3002\u0031X2\u3001\u53cc\u65b9\u8fdb\u7403\u3001\u5927\u5c0f\u0032.5\u6309\u5404\u81ea\u6982\u7387\u5c55\u793a\u3002",
        "local_label": "\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
    },
}
_LOCAL_LABELS = {
    DEGRADED: "\u8d28\u91cf\u964d\u7ea7\uff0c\u4ec5\u4f9b\u89c2\u5bdf",
    UNVERIFIED: "\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350",
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
    status = str(health.get("status") or "").strip().upper() if isinstance(health, Mapping) else ""
    copy = _STATUS_COPY.get(status) if state == DEGRADED else None
    return {
        "state": state,
        "label": copy["label"] if copy else _LABELS[state],
        "note": copy["note"] if copy else _NOTES[state],
        "local_label": copy["local_label"] if copy else _LOCAL_LABELS.get(state, ""),
    }
