#!/usr/bin/env python3
"""Map existing structured legacy analysis into the Slice 1B contract.

This module is intentionally read-only.  It does not import or execute any
prediction/model code, fetch data, infer a market line, or create a new
football judgement.  It only validates an existing artifact and carries
explicit legacy interpretations into a normalized, traceable shape.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # Keep both package imports and direct script execution working.
    from .postmatch_queue import SHANGHAI, parse_datetime as _parse_project_datetime
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from postmatch_queue import SHANGHAI, parse_datetime as _parse_project_datetime


MAPPING_VERSION = "legacy_mapper.v1"
_USABLE = {"USABLE", "PARTIALLY_USABLE"}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first(payload: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_dt(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None

    raw = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        # Legacy timestamps without an offset use the project's business
        # timezone.  Reuse the existing project parser so the host machine's
        # local timezone cannot affect fixture identity or prematch checks.
        return _parse_project_datetime(raw) or parsed.replace(tzinfo=SHANGHAI)
    # Explicit offsets and UTC Z retain their original timezone semantics.
    return parsed


def _normal(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value)).casefold()


def _score(value: Any) -> str | None:
    if isinstance(value, dict):
        value = _first(value, "score", "value")
    match = re.search(r"(?<!\d)(\d+)\s*[-:－–]\s*(\d+)(?!\d)", _text(value))
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _score_list(prediction: dict[str, Any] | None) -> list[str]:
    if not isinstance(prediction, dict):
        return []
    values = prediction.get("top_scores") or prediction.get("score_distribution") or []
    result: list[str] = []
    for value in values:
        parsed = _score(value)
        if parsed and parsed not in result:
            result.append(parsed)
    return result[:3]


def _identity(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("match") or record.get("fixture") or record.get("identity") or record
    if not isinstance(identity, dict):
        identity = record
    return {
        "match_id": _first(identity, "match_id", "matchId", "matchID", "id"),
        "match_key": _first(identity, "match_key", "matchKey", "canonical_match_id", "canonicalMatchId"),
        "business_date": _first(identity, "business_date", "businessDate"),
        "competition": _first(identity, "competition", "league", "leagueName"),
        "home": _first(identity, "home", "homeTeam", "home_team"),
        "away": _first(identity, "away", "awayTeam", "away_team"),
        "kickoff_at": _first(identity, "kickoff_at", "kickoff", "kickoff_local", "kickoffAt"),
        "nowscore_id": _first(identity, "nowscore_id", "nowscoreId", "provider_match_id"),
        "shuju_id": _first(identity, "shuju_id", "shujuId"),
    }


def _target_identity(target: dict[str, Any]) -> dict[str, Any]:
    return _identity(target)


def _identity_reason(target: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    target_key = _text(target.get("match_key"))
    candidate_key = _text(candidate.get("match_key"))
    stable_key_matches = bool(target_key and candidate_key and _normal(target_key) == _normal(candidate_key))
    if target_key and candidate_key and not stable_key_matches:
        return "match_key_mismatch"

    # A stable canonical key is allowed to bridge provider-specific IDs, but
    # without it a directly supplied match_id must still agree.
    if not stable_key_matches:
        for key in ("match_id", "nowscore_id", "shuju_id"):
            left, right = _text(target.get(key)), _text(candidate.get(key))
            if left and right and _normal(left) != _normal(right):
                return f"{key}_mismatch"
    for key in ("home", "away", "business_date", "competition"):
        left, right = _text(target.get(key)), _text(candidate.get(key))
        if left and right and _normal(left) != _normal(right):
            return f"{key}_mismatch"
    target_kickoff = _parse_dt(target.get("kickoff_at"))
    candidate_kickoff = _parse_dt(candidate.get("kickoff_at"))
    if not candidate.get("home") or not candidate.get("away") or not target_kickoff or not candidate_kickoff:
        return "identity_incomplete"
    if abs((candidate_kickoff - target_kickoff).total_seconds()) > 60:
        return "kickoff_mismatch"
    return None


def _report(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("report")
    return value if isinstance(value, dict) else {}


def _analysis_payload(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("analysis_material", "analysis"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _source_model(report: dict[str, Any], record: dict[str, Any]) -> str:
    model_name = _first(report, "model_name", "source_model_family", "model_family")
    model_version = _first(report, "model_version", "source_model_version", "release_version")
    if model_name and model_version:
        return f"{model_name}@{model_version}"
    return _text(model_name or model_version) or "UNKNOWN"


def _source_timestamp(record: dict[str, Any], report: dict[str, Any]) -> tuple[datetime | None, str | None]:
    for key in ("analysis_timestamp", "generated_at", "analysis_at", "created_at", "timestamp"):
        value = _first(report, key, default=_first(record, key))
        if value:
            return _parse_dt(value), _text(value)
    return None, None


def _source_ref(path: Path, key: str, timestamp: str | None, status: str, prediction: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "source_artifact": path.as_posix(),
        "source_key": key,
        "source_timestamp": timestamp,
        "mapping_status": status,
        "source_model_family": None,
        "current_prediction_id": _first(prediction or {}, "prediction_id", "predictionId"),
        "current_frozen_score": _score(_first(prediction or {}, "unique_score", "score_top1")),
    }


def _short_text(value: Any, limit: int = 280) -> str | None:
    text = re.sub(r"\s+", " ", _text(value))
    if not text:
        return None
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    return clipped.rsplit("，", 1)[0].rsplit("；", 1)[0].rstrip("，；。 ") + "。"


def _story_clauses(value: Any) -> list[str]:
    text = re.sub(r"\s+", " ", _text(value))
    if not text:
        return []
    clauses = [part.strip(" ；;。\n") for part in re.split(r"[；;。]", text) if part.strip(" ；;。\n")]
    return clauses


def _short_story(value: Any) -> str | None:
    clauses = _story_clauses(value)
    if not clauses:
        return None
    return "；".join(clauses[:3])


def _explicit_sections(record: dict[str, Any], path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    payload = _analysis_payload(record)
    value = payload.get("sections")
    if isinstance(value, dict):
        value = [dict(item, id=key) for key, item in value.items() if isinstance(item, dict)]
    sections: list[dict[str, Any]] = []
    interpretations: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        section_id = _text(_first(item, "id", "section_id", "key"))
        if not section_id:
            continue
        supports = []
        conflicts = []
        for relation, target_list in (("support", supports), ("conflict", conflicts)):
            raw = item.get(f"{relation}s")
            for evidence in _as_list(raw):
                if not isinstance(evidence, dict) or not evidence.get("text"):
                    continue
                projected = {
                    "type": evidence.get("type") or "分析",
                    "text": _short_text(evidence.get("text"), 420),
                    "source_ref": evidence.get("source_ref") or path.as_posix(),
                    "lineage": _source_ref(path, f"analysis_material.sections.{section_id}.{relation}s", None, "USABLE", None),
                }
                target_list.append(projected)
                interpretations.append({
                    "section_id": section_id,
                    "relation": relation,
                    **projected,
                })
        section = {
            "id": section_id,
            "title": _first(item, "title", "heading"),
            "conclusion": _short_text(_first(item, "conclusion", "judgement", "interpretation"), 520),
            "supports": supports,
            "conflicts": conflicts,
            "explanation": _short_text(_first(item, "explanation", "reason"), 620),
            "score_impact": _short_text(item.get("score_impact"), 260),
            "lineage": [_source_ref(path, f"analysis_material.sections.{section_id}", None, "USABLE", None)],
        }
        if any(section.get(key) for key in ("conclusion", "supports", "conflicts", "explanation", "score_impact")):
            sections.append(section)
    for item in _as_list(payload.get("interpretations")):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        relation = _text(_first(item, "relation", "kind", "role")).lower()
        if relation not in {"support", "conflict", "neutral"}:
            relation = "neutral"
        interpretations.append({
            "section_id": _first(item, "section_id", "section"),
            "relation": relation,
            "type": item.get("type") or "分析",
            "text": _short_text(item.get("text"), 420),
            "source_ref": item.get("source_ref") or path.as_posix(),
            "lineage": [_source_ref(path, "analysis_material.interpretations", None, "USABLE", None)],
        })
    labels: dict[str, str] = {}
    candidate_values = payload.get("candidate_scores")
    if isinstance(candidate_values, dict):
        for score, item in candidate_values.items():
            if isinstance(item, dict) and item.get("script_label"):
                labels[_score(score) or _text(score)] = _short_text(item["script_label"], 180) or ""
    return sections, interpretations, {key: value for key, value in labels.items() if value}


def _trace_candidates(decisions: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trace = decisions.get("score_selection_trace")
    if not isinstance(trace, dict):
        return {}, []
    values = [item for item in _as_list(trace.get("candidates")) if isinstance(item, dict) and _score(item.get("score"))]
    return trace, values


def _trace_label(candidate: dict[str, Any], trace: dict[str, Any]) -> str | None:
    rejection = _short_text(candidate.get("rejection_reason"), 180)
    if rejection:
        return rejection
    factors = trace.get("selected_factors")
    if candidate.get("decision") in {"selected", "challenger_selected", "accepted"} and isinstance(factors, list):
        values = [_text(value) for value in factors if _text(value)]
        return "；".join(values[:2]) if values else None
    return None


def _trace_reasoning(path: Path, candidate: dict[str, Any], trace: dict[str, Any], prediction: dict[str, Any] | None, index: int) -> dict[str, Any]:
    score = _score(candidate.get("score"))
    return {
        "score": score,
        "rank": candidate.get("rank"),
        "scenario_score": candidate.get("scenario_score"),
        "factor_contributions": copy.deepcopy(candidate.get("factor_contributions") or {}),
        "decision": candidate.get("decision"),
        "rejection_reason": _short_text(candidate.get("rejection_reason"), 240),
        "reasoning": _short_text(candidate.get("rejection_reason"), 240) or _trace_label(candidate, trace),
        "source_ref": path.as_posix(),
        "source_key": f"decisions.score_selection_trace.candidates[{index}]",
        "lineage": _source_ref(path, f"decisions.score_selection_trace.candidates[{index}]", None, "USABLE", prediction),
    }


def _primary_outcome(score: str | None) -> str | None:
    if not score:
        return None
    home, away = (int(value) for value in score.split("-", 1))
    return "home" if home > away else "away" if away > home else "draw"


class LegacyStructuredAnalysisMapper:
    """Validate and normalize one already persisted legacy analysis artifact."""

    mapping_version = MAPPING_VERSION

    def map_record(
        self,
        path: Path,
        record: dict[str, Any],
        target: dict[str, Any],
        frozen_prediction: dict[str, Any] | None = None,
        *,
        kind: str = "analysis_reports",
    ) -> dict[str, Any]:
        candidate = _identity(record)
        report = _report(record)
        source_dt, source_timestamp = _source_timestamp(record, report)
        source_model = _source_model(report, record)
        base_lineage = {
            "source_artifact": path.as_posix(),
            "source_key": "record",
            "source_timestamp": source_timestamp,
            "mapping_status": "PENDING_CHECKS",
            "source_model_family": source_model,
            "current_prediction_id": _first(frozen_prediction or {}, "prediction_id", "predictionId"),
            "current_frozen_score": _score(_first(frozen_prediction or {}, "unique_score", "score_top1")),
        }

        def rejected(status: str, reasons: list[str]) -> dict[str, Any]:
            lineage = copy.deepcopy(base_lineage)
            lineage["mapping_status"] = status
            return {
                "status": status,
                "path": path.as_posix(),
                "kind": kind,
                "match_identity": candidate,
                "material_timestamp": source_dt.isoformat() if source_dt else None,
                "report_type": _first(report, "report_type", "type", default=record.get("report_type")),
                "consistency_checks": {
                    "identity": "FIXTURE_MISMATCH" not in reasons,
                    "prematch_timestamp": "MATERIAL_AFTER_KICKOFF" not in reasons and "MATERIAL_TIMESTAMP_UNVERIFIED" not in reasons,
                    "frozen_score": "FROZEN_SCORE_CONFLICT" not in reasons,
                },
                "reasons": list(dict.fromkeys(reasons)),
                "sections": [],
                "interpretations": [],
                "candidate_labels": {},
                "candidate_reasoning": {},
                "hero_script": None,
                "biggest_failure_point": None,
                "market_interpretation": None,
                "risk_evidence": [],
                "decision_evolution": None,
                "analysis_origin": {
                    "type": "LEGACY_STRUCTURED_ANALYSIS",
                    "source_artifact": path.as_posix(),
                    "source_model_family": source_model,
                    "source_timestamp": source_timestamp,
                    "mapping_version": self.mapping_version,
                },
                "lineage": [lineage],
                "source_refs": [path.as_posix()],
            }

        identity_reason = _identity_reason(_target_identity(target), candidate)
        if identity_reason:
            return rejected("FIXTURE_MISMATCH", [identity_reason])

        report_type = _text(_first(report, "report_type", "type", default=record.get("report_type"))).lower()
        if "postmatch" in report_type or "赛后" in report_type:
            return rejected("CONFLICTED", ["POSTMATCH_MATERIAL_NOT_ALLOWED"])
        if kind == "postmatch_reports":
            prematch = next((record.get(key) for key in ("prematch", "prematch_analysis", "prematch_report", "pre_match") if isinstance(record.get(key), dict)), None)
            if prematch is None and "prematch" not in report_type and "pre-match" not in report_type:
                return rejected("CONFLICTED", ["POSTMATCH_MATERIAL_NOT_ALLOWED"])

        kickoff = _parse_dt(_target_identity(target).get("kickoff_at"))
        if source_dt is None:
            return rejected("TIME_UNVERIFIED", ["MATERIAL_TIMESTAMP_UNVERIFIED"])
        if kickoff and source_dt >= kickoff:
            return rejected("TIME_UNVERIFIED", ["MATERIAL_AFTER_KICKOFF"])

        decisions = record.get("decisions") if isinstance(record.get("decisions"), dict) else {}
        legacy_score = _score(_first(record, "unique_score", "score_top1", "formal_unique_score", default=decisions.get("unique_score")))
        frozen_score = _score(_first(frozen_prediction or {}, "unique_score", "score_top1"))
        if legacy_score and frozen_score and legacy_score != frozen_score:
            return rejected("PREDICTION_MISMATCH", ["FROZEN_SCORE_CONFLICT"])

        sections, interpretations, labels = _explicit_sections(record, path)
        story = _short_story(decisions.get("match_story"))
        story_clauses = _story_clauses(decisions.get("match_story"))
        score_reasoning = _short_text(decisions.get("score_reasoning"), 620)
        max_errors = [_short_text(item, 360) for item in _as_list(decisions.get("maximum_error_points")) if _short_text(item, 360)]
        trace, trace_values = _trace_candidates(decisions)
        current_scores = _score_list(frozen_prediction)
        trace_by_score = {_score(item.get("score")): (index, item) for index, item in enumerate(trace_values)}
        candidate_reasoning: dict[str, Any] = {}
        candidate_labels: dict[str, str] = dict(labels)
        for score in current_scores:
            candidate_entry = trace_by_score.get(score)
            if not candidate_entry:
                continue
            candidate_index, candidate = candidate_entry
            candidate_reasoning[score] = _trace_reasoning(path, candidate, trace, frozen_prediction, candidate_index)
            label = _trace_label(candidate, trace)
            if label:
                candidate_labels.setdefault(score, label)

        # Existing explicit sections are canonical legacy interpretations.  For
        # older reports without the newer analysis_material envelope, only
        # explicit prose/trace/risk fields are promoted; raw form stays neutral.
        existing_ids = {section.get("id") for section in sections}
        def add_section(section: dict[str, Any]) -> None:
            section_id = section.get("id")
            if section_id and section_id not in existing_ids:
                sections.append(section)
                existing_ids.add(section_id)

        section_lineage = lambda key: [_source_ref(path, key, source_timestamp, "USABLE", frozen_prediction)]
        if story:
            if "strength" not in existing_ids and story_clauses:
                strength_text = story_clauses[0]
                add_section({
                    "id": "strength",
                    "title": "强弱与主动权",
                    "conclusion": strength_text,
                    "supports": [],
                    "conflicts": [],
                    "explanation": "该结论来自旧赛前报告的比赛剧本字段；近期战绩等原始字段仍保留在审计层。",
                    "score_impact": None,
                    "lineage": section_lineage("decisions.match_story"),
                })
            tempo_clause = next((item for item in story_clauses if any(word in item for word in ("总进球", "节奏", "开放", "受控"))), None)
            if tempo_clause and "tempo" not in existing_ids:
                add_section({
                    "id": "tempo",
                    "title": "节奏与进球环境",
                    "conclusion": tempo_clause,
                    "supports": [],
                    "conflicts": [],
                    "explanation": "该结论来自旧赛前比赛剧本，不是当前投影层根据盘口或 lambda 新算出的方向。",
                    "score_impact": None,
                    "lineage": section_lineage("decisions.match_story"),
                })

        trace_primary = _score(trace.get("selected_score"))
        if score_reasoning and "scoring" not in existing_ids:
            add_section({
                "id": "scoring",
                "title": "得分路径",
                "conclusion": score_reasoning,
                "supports": [],
                "conflicts": [],
                "explanation": "该段只保留旧报告已有的比分理由；未由 mapper 重新计算概率或得分路径。",
                "score_impact": None,
                "lineage": section_lineage("decisions.score_reasoning"),
            })
        if max_errors and "fork" not in existing_ids:
            add_section({
                "id": "fork",
                "title": "关键分叉 / 最大不确定性",
                "conclusion": max_errors[0],
                "supports": [],
                "conflicts": [],
                "explanation": "该风险来自旧报告的 maximum_error_points；没有把它改写成确定会发生的事件。",
                "score_impact": None,
                "lineage": section_lineage("decisions.maximum_error_points"),
            })

        current_three = current_scores[:3]
        trace_complete = bool(
            frozen_score
            and trace_primary == frozen_score
            and len(current_three) == 3
            and all(score in candidate_reasoning for score in current_three)
        )
        if trace_complete and "convergence" not in existing_ids:
            primary_reason = candidate_reasoning[frozen_score].get("reasoning") or "旧 trace 未提供首选摘要。"
            neighbor_lines = []
            for score in current_three[1:]:
                item = candidate_reasoning[score]
                reason = item.get("reasoning") or "旧 trace 只记录了该候选，但没有可压缩理由。"
                neighbor_lines.append(f"{score}：{reason}")
            convergence_explanation = f"首选 {frozen_score}：{primary_reason}；" + "；".join(neighbor_lines)
            add_section({
                "id": "convergence",
                "title": "最终收敛",
                "conclusion": _short_text(score_reasoning or f"旧 trace 明确选择 {frozen_score}。", 620),
                "supports": [{
                    "type": "分析",
                    "text": _short_text(convergence_explanation, 900),
                    "source_ref": path.as_posix(),
                    "lineage": _source_ref(path, "decisions.score_selection_trace", source_timestamp, "USABLE", frozen_prediction),
                }],
                "conflicts": [],
                "explanation": "首选与两个当前冻结邻近候选的比较来自同一份旧 score_selection_trace；没有新增 legacy 候选。",
                "score_impact": _short_text(f"{frozen_score} 的已有 trace 选择理由胜过 {current_three[1]} / {current_three[2]}。", 300),
                "lineage": section_lineage("decisions.score_selection_trace"),
            })

        market = record.get("market") if isinstance(record.get("market"), dict) else {}
        market_interpretation = market.get("interpretation") if isinstance(market.get("interpretation"), dict) else None
        if market_interpretation:
            market_interpretation = copy.deepcopy(market_interpretation)
            market_interpretation["analysis_origin"] = "LEGACY_STRUCTURED_ANALYSIS"
            market_interpretation["source_ref"] = path.as_posix()
            market_interpretation["source_key"] = "market.interpretation"
            market_interpretation["source_timestamp"] = source_timestamp

            impact_code = _text(market_interpretation.get("impact_code")).lower()
            direction = _text(market_interpretation.get("direction")).lower()
            if impact_code in {"confirm", "confirmed", "support"} and direction == _primary_outcome(frozen_score):
                text = _short_text(market_interpretation.get("model_impact") or market_interpretation.get("direction"), 420)
                if text:
                    interpretations.append({
                        "section_id": "strength",
                        "relation": "support",
                        "type": "市场解释",
                        "text": text,
                        "source_ref": path.as_posix(),
                        "lineage": _source_ref(path, "market.interpretation.model_impact", source_timestamp, "USABLE", frozen_prediction),
                    })

        market_conflict = _short_text(decisions.get("market_conflict"), 420)
        if market_conflict:
            interpretations.append({
                "section_id": "fork",
                "relation": "conflict",
                "type": "市场解释",
                "text": market_conflict,
                "source_ref": path.as_posix(),
                "lineage": _source_ref(path, "decisions.market_conflict", source_timestamp, "USABLE", frozen_prediction),
            })

        risk_engine = record.get("risk_engine") if isinstance(record.get("risk_engine"), dict) else {}
        triggered = ((risk_engine.get("traps") or {}).get("triggered") if isinstance(risk_engine.get("traps"), dict) else None) or []
        risk_evidence = [copy.deepcopy(item) for item in triggered if isinstance(item, dict)]

        # Story, score reasoning, trace, market interpretation and explicit
        # sections are analytical material.  Structured form/recent form is
        # deliberately not promoted here.
        usable_section_count = len({section.get("id") for section in sections if section.get("conclusion") or section.get("supports")})
        has_material = bool(story or score_reasoning or candidate_reasoning or interpretations or sections or max_errors)
        if not has_material:
            return rejected("NOT_FOUND", ["NO_EXPLICIT_ANALYTICAL_INTERPRETATION"])
        status = "USABLE" if usable_section_count >= 4 or (story and score_reasoning and candidate_reasoning) else "PARTIALLY_USABLE"
        origin = {
            "type": "LEGACY_STRUCTURED_ANALYSIS",
            "source_artifact": path.as_posix(),
            "source_model_family": source_model,
            "source_timestamp": source_timestamp,
            "mapping_version": self.mapping_version,
        }
        lineage = []
        used_keys = []
        for key, present in (
            ("decisions.match_story", bool(story)),
            ("decisions.score_reasoning", bool(score_reasoning)),
            ("decisions.score_selection_trace", bool(candidate_reasoning)),
            ("decisions.maximum_error_points", bool(max_errors)),
            ("market.interpretation", bool(market_interpretation)),
            ("risk_engine", bool(risk_evidence)),
            ("analysis_material", bool(sections)),
            ("decisions.market_conflict", bool(market_conflict)),
        ):
            if present:
                used_keys.append(key)
                ref = _source_ref(path, key, source_timestamp, status, frozen_prediction)
                ref["source_model_family"] = source_model
                lineage.append(ref)
        return {
            "status": status,
            "path": path.as_posix(),
            "kind": kind,
            "match_identity": candidate,
            "material_timestamp": source_dt.isoformat(),
            "report_type": _first(report, "report_type", "type", default=record.get("report_type")),
            "consistency_checks": {"identity": True, "prematch_timestamp": True, "frozen_score": True},
            "reasons": [],
            "sections": sections,
            "interpretations": interpretations,
            "candidate_labels": candidate_labels,
            "candidate_reasoning": candidate_reasoning,
            "hero_script": story,
            "biggest_failure_point": max_errors[0] if max_errors else None,
            "market_interpretation": market_interpretation,
            "risk_evidence": risk_evidence,
            "decision_evolution": copy.deepcopy(record.get("decision_evolution")) if isinstance(record.get("decision_evolution"), dict) else None,
            "analysis_origin": origin,
            "lineage": lineage,
            "source_keys": used_keys,
            "source_refs": [path.as_posix()],
            "trace_coverage": len(candidate_reasoning),
            "convergence_complete": trace_complete,
        }


__all__ = ["LegacyStructuredAnalysisMapper", "MAPPING_VERSION"]
