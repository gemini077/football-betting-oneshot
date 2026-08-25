"""Adapt settled prospective pair evidence to the Phase 2C quality gate.

Pair events intentionally keep only immutable member references and hashes.  The
adapter joins those references to the independently frozen prediction records,
checks the captured provenance again, and attaches only the pair's shared
verified regulation-90m result.  It never reads historical reports and never
changes the formal Champion ledger.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from model_governance import prediction_content_hash
from prospective_settlement import FROZEN_STATUSES

from .phase2c1_model import probability_payload
from .prediction_quality_gate import evaluate_shadow_promotion_gate


class PairQualityAdapterError(ValueError):
    """Settled pair evidence cannot be used as a true prospective pair."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _time(value: Any, code: str) -> datetime:
    if value in (None, ""):
        raise PairQualityAdapterError(code)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise PairQualityAdapterError(code) from error
    if parsed.tzinfo is None:
        raise PairQualityAdapterError(code)
    return parsed.astimezone(timezone.utc)


def _identity(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("match_identity")
    return value if isinstance(value, Mapping) else {}


def _match_key(record: Mapping[str, Any]) -> str:
    return _text(record.get("match_key") or _identity(record).get("match_key"))


def _records(values: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if values is None:
        return []
    if isinstance(values, Mapping):
        if "prediction_id" in values:
            values = [values]
        else:
            values = values.values()
    return [value for value in values if isinstance(value, Mapping)]


def _referenced_record(
    values: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    prediction_id: str,
    role: str,
) -> Mapping[str, Any]:
    matches = [row for row in _records(values) if _text(row.get("prediction_id")) == prediction_id]
    if not matches:
        raise PairQualityAdapterError(f"{role.upper()}_REFERENCED_RECORD_MISSING")
    if len(matches) != 1:
        raise PairQualityAdapterError(f"{role.upper()}_REFERENCED_RECORD_DUPLICATE")
    return matches[0]


def _validate_member(
    record: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    role: str,
    match: Mapping[str, Any],
    evidence_cutoff: datetime,
) -> None:
    prefix = role.upper()
    if record.get("model_role") != role:
        raise PairQualityAdapterError(f"{prefix}_ROLE_MISMATCH")
    if record.get("prediction_status") not in FROZEN_STATUSES:
        raise PairQualityAdapterError(f"{prefix}_NOT_FROZEN")
    if "actual" in record or "result" in record:
        raise PairQualityAdapterError(f"{prefix}_POSTMATCH_RECORD_FORBIDDEN")
    for field in ("prediction_id", "prediction_sha256", "model_source_fingerprint", "model_run_fingerprint"):
        if _text(record.get(field)) == "" or _text(record.get(field)) != _text(reference.get(field)):
            raise PairQualityAdapterError(f"{prefix}_{field.upper()}_MISMATCH")
    try:
        computed_hash = prediction_content_hash(dict(record))
    except (TypeError, ValueError, KeyError):
        raise PairQualityAdapterError(f"{prefix}_PREDICTION_CONTENT_HASH_INVALID")
    if computed_hash != _text(record.get("prediction_sha256")):
        raise PairQualityAdapterError(f"{prefix}_PREDICTION_CONTENT_HASH_MISMATCH")
    for field in ("model_family", "model_core_version"):
        expected = reference.get(field)
        if expected not in (None, "") and record.get(field) != expected:
            raise PairQualityAdapterError(f"{prefix}_{field.upper()}_MISMATCH")
    expected_challenger_id = reference.get("challenger_id")
    if role == "challenger" and _text(record.get("challenger_id")) != _text(expected_challenger_id):
        raise PairQualityAdapterError(f"{prefix}_CHALLENGER_ID_MISMATCH")
    if role == "champion" and record.get("challenger_id") not in (None, ""):
        raise PairQualityAdapterError("CHAMPION_CANNOT_HAVE_CHALLENGER_ID")

    match_key = _match_key(record)
    if not match_key or match_key != _text(match.get("match_key")):
        raise PairQualityAdapterError(f"{prefix}_CANONICAL_MATCH_MISMATCH")
    record_kickoff = _time(
        record.get("kickoff_at") or _identity(record).get("kickoff_at"),
        f"{prefix}_KICKOFF_MISSING",
    )
    kickoff = _time(match.get("kickoff_at"), "PAIR_KICKOFF_MISSING")
    if record_kickoff != kickoff:
        raise PairQualityAdapterError(f"{prefix}_KICKOFF_MISMATCH")
    record_cutoff = _time(record.get("source_cutoff_at"), f"{prefix}_SOURCE_CUTOFF_MISSING")
    reference_cutoff = _time(reference.get("source_cutoff_at"), f"{prefix}_REFERENCE_CUTOFF_MISSING")
    if record_cutoff != evidence_cutoff or record_cutoff != reference_cutoff:
        raise PairQualityAdapterError(f"{prefix}_EVIDENCE_CUTOFF_MISMATCH")
    created = _time(record.get("prediction_created_at"), f"{prefix}_CREATED_AT_MISSING")
    reference_created = _time(reference.get("prediction_created_at"), f"{prefix}_REFERENCE_CREATED_MISSING")
    freeze = _time(record.get("freeze_created_at"), f"{prefix}_FREEZE_AT_MISSING")
    reference_freeze = _time(reference.get("freeze_created_at"), f"{prefix}_REFERENCE_FREEZE_MISSING")
    if created != reference_created or freeze != reference_freeze:
        raise PairQualityAdapterError(f"{prefix}_FREEZE_PROVENANCE_MISMATCH")
    if not record_cutoff < created <= freeze < kickoff:
        raise PairQualityAdapterError(f"{prefix}_RETROSPECTIVE_EVIDENCE_FORBIDDEN")


def _settled_pair_state(state: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if state.get("TRUE_PAIRED") is not True:
        raise PairQualityAdapterError("TRUE_PAIRED_SETTLEMENT_REQUIRED")
    capture = state.get("capture")
    settlement = state.get("settlement")
    if not isinstance(capture, Mapping) or capture.get("event_type") != "PAIR_CAPTURED":
        raise PairQualityAdapterError("PAIR_CAPTURE_EVENT_REQUIRED")
    if not isinstance(settlement, Mapping) or settlement.get("event_type") != "PAIR_SETTLED":
        raise PairQualityAdapterError("PAIR_SETTLEMENT_EVENT_REQUIRED")
    pair_id = _text(state.get("pair_id") or capture.get("pair_id"))
    if not pair_id or _text(capture.get("pair_id")) != pair_id or _text(settlement.get("pair_id")) != pair_id:
        raise PairQualityAdapterError("PAIR_ID_MISMATCH")
    if capture.get("research_only") is not True:
        raise PairQualityAdapterError("PAIR_NOT_SHADOW_ONLY")
    match = capture.get("match")
    if not isinstance(match, Mapping) or not _text(match.get("match_key")):
        raise PairQualityAdapterError("PAIR_MATCH_IDENTITY_MISSING")
    if _text(settlement.get("match_key")) != _text(match.get("match_key")):
        raise PairQualityAdapterError("SETTLEMENT_MATCH_MISMATCH")
    evidence_cutoff = _time(capture.get("evidence_cutoff_at"), "PAIR_EVIDENCE_CUTOFF_MISSING")
    kickoff = _time(match.get("kickoff_at"), "PAIR_KICKOFF_MISSING")
    captured_at = _time(capture.get("captured_at"), "PAIR_CAPTURE_TIME_MISSING")
    if not captured_at < kickoff:
        raise PairQualityAdapterError("RETROACTIVE_PAIR_FORBIDDEN")
    shared = settlement.get("shared_result")
    if not isinstance(shared, Mapping) or state.get("shared_result") != shared:
        raise PairQualityAdapterError("SHARED_RESULT_STATE_MISMATCH")
    if shared.get("scope") not in {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}:
        raise PairQualityAdapterError("SHARED_RESULT_NOT_REGULATION_90M")
    verified_at = _time(shared.get("result_verified_at"), "SHARED_RESULT_VERIFIED_AT_MISSING")
    if verified_at < kickoff:
        raise PairQualityAdapterError("SHARED_RESULT_BEFORE_KICKOFF")
    for field in ("home_score_90m", "away_score_90m"):
        score = shared.get(field)
        try:
            numeric_score = float(score)
            integer_score = int(score)
        except (TypeError, ValueError, OverflowError):
            numeric_score = None
            integer_score = -1
        if (
            isinstance(score, bool)
            or numeric_score is None
            or not isfinite(numeric_score)
            or integer_score != numeric_score
            or integer_score < 0
        ):
            raise PairQualityAdapterError("SHARED_RESULT_SCORE_INVALID")
    champion_ref = capture.get("champion")
    challenger_ref = capture.get("challenger")
    if not isinstance(champion_ref, Mapping) or not isinstance(challenger_ref, Mapping):
        raise PairQualityAdapterError("PAIR_MEMBER_REFERENCE_MISSING")
    return pair_id, capture, champion_ref, challenger_ref


def _event_states(evidence: Any) -> list[Mapping[str, Any]]:
    if evidence is None:
        return []
    if isinstance(evidence, Mapping):
        if "capture" in evidence or "event_type" in evidence:
            values: list[Any] = [evidence]
        else:
            values = list(evidence.values())
    else:
        values = list(evidence)
    states = [value for value in values if isinstance(value, Mapping) and "capture" in value]
    events = [
        value for value in values
        if isinstance(value, Mapping) and value.get("event_type") in {"PAIR_CAPTURED", "PAIR_SETTLED"}
    ]
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        pair_id = _text(event.get("pair_id"))
        if not pair_id:
            continue
        state = grouped.setdefault(pair_id, {"pair_id": pair_id})
        if event.get("event_type") == "PAIR_CAPTURED":
            state["capture"] = event
        else:
            state["settlement"] = event
            state["shared_result"] = event.get("shared_result")
        state["TRUE_PAIRED"] = isinstance(state.get("capture"), Mapping) and isinstance(state.get("settlement"), Mapping)
    return [*states, *grouped.values()]


def _prediction_row(
    record: Mapping[str, Any],
    *,
    pair_id: str,
    match_key: str,
    shared_result: Mapping[str, Any],
) -> dict[str, Any]:
    output = record.get("prediction_output")
    output = output if isinstance(output, Mapping) else {}
    raw_probabilities = record.get("probabilities")
    if not isinstance(raw_probabilities, Mapping):
        raw_probabilities = output.get("probabilities")
    if not isinstance(raw_probabilities, Mapping):
        raise PairQualityAdapterError("PREDICTION_PROBABILITIES_MISSING")
    lambda_home = _number(record.get("lambda_home") if record.get("lambda_home") is not None else output.get("lambda_home"))
    lambda_away = _number(record.get("lambda_away") if record.get("lambda_away") is not None else output.get("lambda_away"))
    if lambda_home is None or lambda_away is None or lambda_home < 0 or lambda_away < 0:
        raise PairQualityAdapterError("PREDICTION_LAMBDA_MISSING")
    derived = probability_payload(lambda_home, lambda_away)
    if isinstance(raw_probabilities.get("1x2"), Mapping):
        probabilities = deepcopy(dict(raw_probabilities))
        one_x_two = probabilities["1x2"]
    else:
        one_x_two = {label: raw_probabilities.get(label) for label in ("home", "draw", "away")}
        probabilities = {"1x2": one_x_two}
    if any(_number(one_x_two.get(label)) is None for label in ("home", "draw", "away")):
        raise PairQualityAdapterError("PREDICTION_1X2_INVALID")
    for field in ("totals", "btts", "score_matrix"):
        if not isinstance(probabilities.get(field), Mapping):
            probabilities[field] = deepcopy(derived[field])
    if not isinstance(probabilities.get("totals"), Mapping) or not isinstance(probabilities.get("btts"), Mapping):
        raise PairQualityAdapterError("PREDICTION_DISTRIBUTION_MISSING")
    row = {
        "match_key": match_key,
        "actual": {
            "home_goals": int(shared_result["home_score_90m"]),
            "away_goals": int(shared_result["away_score_90m"]),
        },
        "probabilities": probabilities,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "pair_id": pair_id,
        "prediction_id": record.get("prediction_id"),
        "prediction_sha256": record.get("prediction_sha256"),
    }
    top_scores = _top_scores(record, output, probabilities)
    if top_scores:
        row["top_scores"] = top_scores
    return row


def _top_scores(record: Mapping[str, Any], output: Mapping[str, Any], probabilities: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Map stored score rows to the gate's optional top_scores shape."""

    source: Any = probabilities.get("score_matrix")
    if not isinstance(source, list):
        source = output.get("score_matrix")
    if not isinstance(source, list):
        source = record.get("score_top5") or record.get("score_top3") or []
    rows: list[dict[str, Any]] = []
    for item in source:
        if isinstance(item, Mapping):
            home = item.get("home_goals")
            away = item.get("away_goals")
            score = item.get("score")
            probability = item.get("probability")
        else:
            home = away = probability = None
            score = item
        if (home is None or away is None) and isinstance(score, str) and "-" in score:
            left, right = score.split("-", 1)
            home, away = left.strip(), right.strip()
        try:
            home_goals = int(home)
            away_goals = int(away)
        except (TypeError, ValueError):
            continue
        row = {"home_goals": home_goals, "away_goals": away_goals}
        if _number(probability) is not None:
            row["probability"] = float(probability)
        rows.append(row)
    return rows


def adapt_settled_pairs(
    pair_evidence: Any,
    *,
    champion_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    challenger_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return Phase 2C rows only for captured pairs with a shared settlement."""

    states = _event_states(pair_evidence)
    if not states:
        raise PairQualityAdapterError("TRUE_PAIRED_SETTLEMENT_REQUIRED")
    champion_rows: list[dict[str, Any]] = []
    challenger_rows: list[dict[str, Any]] = []
    pair_ids: list[str] = []
    match_keys: set[str] = set()
    for state in states:
        pair_id, capture, champion_ref, challenger_ref = _settled_pair_state(state)
        match = capture["match"]
        match_key = _text(match["match_key"])
        if match_key in match_keys:
            raise PairQualityAdapterError("DUPLICATE_PAIRED_MATCH_KEY")
        match_keys.add(match_key)
        shared = state["shared_result"]
        evidence_cutoff = _time(capture["evidence_cutoff_at"], "PAIR_EVIDENCE_CUTOFF_MISSING")
        champion = _referenced_record(champion_records, _text(champion_ref.get("prediction_id")), "champion")
        challenger = _referenced_record(challenger_records, _text(challenger_ref.get("prediction_id")), "challenger")
        _validate_member(champion, champion_ref, role="champion", match=match, evidence_cutoff=evidence_cutoff)
        _validate_member(challenger, challenger_ref, role="challenger", match=match, evidence_cutoff=evidence_cutoff)
        champion_rows.append(_prediction_row(champion, pair_id=pair_id, match_key=match_key, shared_result=shared))
        challenger_rows.append(_prediction_row(challenger, pair_id=pair_id, match_key=match_key, shared_result=shared))
        pair_ids.append(pair_id)
    return {
        "champion_predictions": champion_rows,
        "challenger_predictions": challenger_rows,
        "pair_ids": pair_ids,
        "match_keys": sorted(match_keys),
    }


def evaluate_settled_pairs(
    pair_evidence: Any,
    *,
    champion_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    challenger_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    max_brier_degradation: float = 0.0,
    max_log_loss_degradation: float = 0.0,
    min_paired_matches: int = 1,
    structural_min_deltas: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate only true settled pairs through the existing shadow-only gate."""

    try:
        adapted = adapt_settled_pairs(
            pair_evidence,
            champion_records=champion_records,
            challenger_records=challenger_records,
        )
    except PairQualityAdapterError as error:
        result = evaluate_shadow_promotion_gate(
            [],
            [],
            max_brier_degradation=max_brier_degradation,
            max_log_loss_degradation=max_log_loss_degradation,
            min_paired_matches=min_paired_matches,
            structural_min_deltas=structural_min_deltas,
        )
        result["blocking_reasons"] = [f"pair_adapter:{error.code}"]
        result["adapter"] = {"status": "INSUFFICIENT_EVIDENCE", "reason": error.code}
        return result
    result = evaluate_shadow_promotion_gate(
        adapted["champion_predictions"],
        adapted["challenger_predictions"],
        max_brier_degradation=max_brier_degradation,
        max_log_loss_degradation=max_log_loss_degradation,
        min_paired_matches=min_paired_matches,
        structural_min_deltas=structural_min_deltas,
    )
    result["adapter"] = {
        "status": "TRUE_PAIRED",
        "pair_ids": adapted["pair_ids"],
        "match_keys": adapted["match_keys"],
    }
    return result


__all__ = ["PairQualityAdapterError", "adapt_settled_pairs", "evaluate_settled_pairs"]
