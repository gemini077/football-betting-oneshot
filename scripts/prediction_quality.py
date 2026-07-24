#!/usr/bin/env python3
"""Shared research/formal prediction grading rules."""
from __future__ import annotations

from typing import Any


EXECUTION_ONLY_MISSING = {"用户渠道即时赔率"}


def checkpoint_count(payload: dict[str, Any]) -> int:
    checkpoints = payload.get("market_history") or payload.get("checkpoints") or []
    legacy_count = len(checkpoints) if isinstance(checkpoints, list) else 0
    model = payload.get("model") or {}
    features = ((model.get("calibration") or {}).get("checkpoint_features") or {})
    try:
        feature_count = int(features.get("snapshot_count") or 0)
    except (TypeError, ValueError):
        feature_count = 0
    return max(legacy_count, feature_count)


def classify_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    """Grade evidence without treating missing execution price as model evidence."""
    quality = payload.get("data_quality") or (payload.get("analysis") or {}).get("data_quality") or {}
    missing = [
        str(item) for item in quality.get("missing") or []
        if item and str(item) not in EXECUTION_ONLY_MISSING
    ]
    count = checkpoint_count(payload)
    if not missing and count >= 4:
        grade, weight = "A", 1.0
    elif len(missing) <= 2 and count >= 2:
        grade, weight = "B", 0.7
    else:
        grade, weight = "C", 0.4
    decisions = payload.get("decisions") or {}
    formal = grade in {"A", "B"} and bool(decisions.get("unique_primary_dimension"))
    betting = payload.get("betting") or {}
    return {
        "research": True,
        "data_grade": grade,
        "calibration_weight": weight,
        "formal_pick_eligible": formal,
        "execution_eligible": formal and bool(betting.get("candidates")),
        "checkpoint_count": count,
        "analysis_missing": missing,
    }
