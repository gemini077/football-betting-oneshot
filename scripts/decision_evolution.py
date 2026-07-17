#!/usr/bin/env python3
"""Compact, append-only decision evolution for one selected match.

Raw provider snapshots remain audit evidence.  This module stores only the
small set of model and market values needed to explain how the judgement
changed.  Checkpoint names are internal scheduling metadata and are never
required in the user-facing narrative.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from market_intelligence import interpret_market_intent


ROOT = Path(__file__).resolve().parents[1]
TIMELINE_ROOT = ROOT / "data" / "match_archive"
OUTCOMES = ("home", "draw", "away")
OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_probabilities(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        key: number
        for key in OUTCOMES
        if (number := _number(value.get(key))) is not None
    }


def _market_intelligence(analysis: dict, checkpoint: dict | None = None) -> dict:
    market = analysis.get("market") or {}
    intelligence = market.get("intelligence") or analysis.get("market_intelligence") or {}
    inferred = interpret_market_intent(
        {},
        intelligence,
        (analysis.get("model") or {}).get("probabilities"),
        (checkpoint or {}).get("stage"),
    )
    return {
        **inferred,
        "exchange_volume": _number(((intelligence.get("modules") or {}).get("exchange") or {}).get("total_volume")),
    }


def decision_snapshot(analysis: dict, checkpoint: dict | None = None) -> dict:
    model = analysis.get("model") or {}
    decisions = analysis.get("decisions") or {}
    market = analysis.get("market") or {}
    consensus = market.get("consensus") or {}
    probabilities = _clean_probabilities(model.get("probabilities"))
    leader = max(probabilities, key=probabilities.get) if probabilities else None
    intelligence = _market_intelligence(analysis, checkpoint)
    return {
        "probabilities": probabilities,
        "outcome_leader": leader,
        "outcome_leader_label": OUTCOME_LABELS.get(leader),
        "unique_score": decisions.get("unique_score"),
        "primary_dimension": decisions.get("unique_primary_dimension"),
        "value_judgement": decisions.get("value_judgement"),
        "lambda_home": _number(model.get("lambda_home")),
        "lambda_away": _number(model.get("lambda_away")),
        "btts": (model.get("btts") or {}).get("judgement"),
        "total_mode": decisions.get("total_goals_mode") or decisions.get("total_goals"),
        "market_current": consensus.get("current"),
        **intelligence,
    }


def describe_change(previous: dict | None, current: dict) -> dict:
    if not previous:
        leader = current.get("outcome_leader_label") or "胜平负尚未拉开"
        score = current.get("unique_score") or "比分尚未收敛"
        primary = current.get("primary_dimension") or "主维度尚未收敛"
        return {
            "kind": "initial",
            "headline": f"初始判断：{leader}；首推比分{score}",
            "summary": f"模型建立初始比赛剧本，主维度为{primary}。{current.get('market_pressure')}；{current.get('money_flow')}；{current.get('bookmaker_behaviour')}；{current.get('model_impact')}",
            "changed": True,
        }

    changes: list[str] = []
    old_probs = previous.get("probabilities") or {}
    new_probs = current.get("probabilities") or {}
    probability_moves = []
    for key in OUTCOMES:
        old, new = _number(old_probs.get(key)), _number(new_probs.get(key))
        if old is not None and new is not None and abs(new - old) >= 0.015:
            probability_moves.append((abs(new - old), key, new - old))
    if probability_moves:
        _, key, delta = max(probability_moves)
        changes.append(f"{OUTCOME_LABELS[key]}概率{'上调' if delta > 0 else '下调'}{abs(delta) * 100:.1f}个百分点")

    old_primary, new_primary = previous.get("primary_dimension"), current.get("primary_dimension")
    if old_primary and new_primary and old_primary != new_primary:
        changes.append(f"主维度由“{old_primary}”调整为“{new_primary}”")
    old_score, new_score = previous.get("unique_score"), current.get("unique_score")
    if old_score and new_score and old_score != new_score:
        changes.append(f"最可能比分由{old_score}调整为{new_score}")
    if previous.get("market_pressure") != current.get("market_pressure"):
        changes.append(str(current.get("market_pressure")))
    if previous.get("money_flow") != current.get("money_flow"):
        changes.append(str(current.get("money_flow")))
    if previous.get("model_impact") != current.get("model_impact"):
        changes.append(str(current.get("model_impact")))
    if previous.get("bookmaker_behaviour") != current.get("bookmaker_behaviour"):
        changes.append(str(current.get("bookmaker_behaviour")))

    if changes:
        return {
            "kind": "changed",
            "headline": "；".join(changes[:3]),
            "summary": "；".join(changes) + "。模型已按新信息重算，冻结注单不会被事后改写。",
            "changed": True,
        }
    return {
        "kind": "stable",
        "headline": "核心判断维持不变",
        "summary": f"新盘口和球队信息尚不足以越过决策边界；继续维持{current.get('primary_dimension') or '原主维度'}与比分{current.get('unique_score') or '原判断'}。{current.get('model_impact')}",
        "changed": False,
    }


def timeline_path(match_id: Any, root: Path = TIMELINE_ROOT) -> Path:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(match_id or "match"))
    return root / safe / "decision_timeline.jsonl"


def load_timeline(match_id: Any, root: Path = TIMELINE_ROOT) -> list[dict]:
    path = timeline_path(match_id, root)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("captured_at") or ""))


def attach_evolution(
    analysis: dict,
    match_id: Any,
    checkpoint: dict,
    root: Path = TIMELINE_ROOT,
) -> tuple[dict, dict]:
    timeline = load_timeline(match_id, root)
    current = decision_snapshot(analysis, checkpoint)
    previous = timeline[-1].get("decision") if timeline else None
    change = describe_change(previous, current)
    record = {
        "schema_version": "1.0",
        "match_id": str(match_id or ""),
        "captured_at": checkpoint.get("captured_at"),
        "internal_stage": checkpoint.get("stage"),
        "decision": current,
        "change": change,
    }
    visible = [
        {
            "captured_at": row.get("captured_at"),
            "headline": (row.get("change") or {}).get("headline"),
            "summary": (row.get("change") or {}).get("summary"),
            "changed": (row.get("change") or {}).get("changed"),
        }
        for row in timeline
    ]
    visible.append({
        "captured_at": record["captured_at"],
        "headline": change["headline"],
        "summary": change["summary"],
        "changed": change["changed"],
    })
    analysis["decision_evolution"] = {
        "latest": change,
        "history": visible,
        "internal_checkpoints_hidden": True,
    }
    analysis.setdefault("market", {})["interpretation"] = {
        "money_flow": current.get("money_flow"),
        "bookmaker_behaviour": current.get("bookmaker_behaviour"),
        "market_pressure": current.get("market_pressure"),
        "model_impact": current.get("model_impact"),
        "purpose": current.get("purpose"),
        "confidence": current.get("confidence"),
        "late_market_weight": current.get("late_market_weight"),
        "actual_volume_available": current.get("exchange_volume") is not None,
    }
    return analysis, record


def append_record(record: dict, root: Path = TIMELINE_ROOT) -> Path:
    path = timeline_path(record.get("match_id"), root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_timeline(record.get("match_id"), root)
    identity = (record.get("captured_at"), record.get("internal_stage"))
    if any((row.get("captured_at"), row.get("internal_stage")) == identity for row in existing):
        return path
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path
