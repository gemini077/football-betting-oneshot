"""Research-only qualification evidence for future settled prediction pairs.

The Champion and research candidate must pass the existing prospective pair
adapter.  Market input is deliberately a separate, small frozen snapshot
contract; it is never read from a governance record or reconstructed from
post-match/current odds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, log
from typing import Any, Iterable, Mapping

from .phase2c1_model import evaluate_predictions
from .prospective_pair_quality import PairQualityAdapterError, adapt_settled_pairs


MARKET_SNAPSHOT_CONTRACT_VERSION = "prospective_market_snapshot.v1"
_EPSILON = 1e-15
_SNAPSHOT_TIME_FIELDS = ("snapshot_at", "source_snapshot_at", "market_snapshot_at")
_SNAPSHOT_ID_FIELDS = ("snapshot_id", "snapshot_sha256", "snapshot_hash")
_MARKET_ID_FIELDS = (
    "market_snapshot_id",
    "market_snapshot_sha256",
    "market_snapshot_hash",
    "snapshot_id",
    "snapshot_sha256",
    "snapshot_hash",
)
_MARKET_TIME_FIELDS = ("market_snapshot_at", "odds_snapshot_at")


class MarketSnapshotError(ValueError):
    """A supplied market snapshot is not a legal frozen evaluation input."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _time(value: Any, code: str) -> datetime:
    if value in (None, ""):
        raise MarketSnapshotError(code)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise MarketSnapshotError(code) from error
    if parsed.tzinfo is None:
        raise MarketSnapshotError(code)
    return parsed.astimezone(timezone.utc)


def _records(values: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if values is None:
        return []
    if isinstance(values, Mapping):
        if "match_key" in values:
            values = [values]
        else:
            values = values.values()
    return [value for value in values if isinstance(value, Mapping)]


def _snapshot_time(snapshot: Mapping[str, Any]) -> datetime:
    present = [(field, snapshot.get(field)) for field in _SNAPSHOT_TIME_FIELDS if snapshot.get(field) not in (None, "")]
    if not present:
        raise MarketSnapshotError("market_snapshot_timestamp_missing")
    parsed = _time(present[0][1], "market_snapshot_timestamp_invalid")
    for _, value in present[1:]:
        if _time(value, "market_snapshot_timestamp_invalid") != parsed:
            raise MarketSnapshotError("market_snapshot_timestamp_conflict")
    return parsed


def _snapshot_identity(snapshot: Mapping[str, Any]) -> set[str]:
    identities = {_text(snapshot.get(field)) for field in _SNAPSHOT_ID_FIELDS}
    identities.discard("")
    if not identities:
        raise MarketSnapshotError("market_snapshot_identity_missing")
    return identities


def _snapshot_probabilities(snapshot: Mapping[str, Any]) -> dict[str, float]:
    value = snapshot.get("probabilities")
    if not isinstance(value, Mapping):
        raise MarketSnapshotError("market_snapshot_probabilities_missing")
    probabilities: dict[str, float] = {}
    for label in ("home", "draw", "away"):
        raw = value.get(label)
        if isinstance(raw, bool):
            raise MarketSnapshotError("market_snapshot_probabilities_invalid")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise MarketSnapshotError("market_snapshot_probabilities_invalid")
        if not isfinite(number) or number < 0 or number > 1:
            raise MarketSnapshotError("market_snapshot_probabilities_invalid")
        probabilities[label] = number
    if abs(sum(probabilities.values()) - 1.0) > 1e-9:
        raise MarketSnapshotError("market_snapshot_probabilities_not_normalized")
    return probabilities


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    match_key = _text(snapshot.get("match_key"))
    if not match_key:
        raise MarketSnapshotError("market_snapshot_match_key_missing")
    return {
        "contract": MARKET_SNAPSHOT_CONTRACT_VERSION,
        "match_key": match_key,
        "snapshot_at": _snapshot_time(snapshot),
        "identities": _snapshot_identity(snapshot),
        "probabilities": _snapshot_probabilities(snapshot),
    }


def _market_index(
    values: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    invalid: dict[str, list[str]] = {}
    for raw in _records(values):
        key = _text(raw.get("match_key"))
        if not key:
            continue
        try:
            snapshot = _validate_snapshot(raw)
        except MarketSnapshotError as error:
            invalid.setdefault(key, []).append(error.code)
            continue
        indexed.setdefault(key, []).append(snapshot)
    return indexed, invalid


def _record_market_identities(record: Mapping[str, Any]) -> set[str]:
    identities: set[str] = set()
    containers: list[Mapping[str, Any]] = [record]
    for name in ("snapshot_identity", "input_snapshot"):
        value = record.get(name)
        if isinstance(value, Mapping):
            containers.append(value)
    for container in containers:
        for field in _MARKET_ID_FIELDS:
            value = _text(container.get(field))
            if value:
                identities.add(value)
    return identities


def _record_market_times(record: Mapping[str, Any]) -> set[datetime]:
    times: set[datetime] = set()
    containers: list[Mapping[str, Any]] = [record]
    for name in ("snapshot_identity", "input_snapshot"):
        value = record.get(name)
        if isinstance(value, Mapping):
            containers.append(value)
    for container in containers:
        for field in _MARKET_TIME_FIELDS:
            if container.get(field) not in (None, ""):
                try:
                    times.add(_time(container[field], "frozen_market_snapshot_timestamp_invalid"))
                except MarketSnapshotError:
                    return set()
    return times


def _expected_market_identity(
    champion: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[set[str], set[datetime], bool, bool]:
    identity_sets = [values for values in (_record_market_identities(champion), _record_market_identities(candidate)) if values]
    time_sets = [values for values in (_record_market_times(champion), _record_market_times(candidate)) if values]
    identity_conflict = len(identity_sets) > 1 and not set.intersection(*identity_sets)
    timestamp_conflict = len(time_sets) > 1 and not set.intersection(*time_sets)
    identities = set.intersection(*identity_sets) if identity_sets and not identity_conflict else set()
    times = set.intersection(*time_sets) if time_sets and not timestamp_conflict else set()
    return identities, times, identity_conflict, timestamp_conflict


def _score_pair(row: Mapping[str, Any]) -> tuple[int, int] | None:
    value = row.get("score")
    if isinstance(value, Mapping):
        value = (value.get("home_goals"), value.get("away_goals"))
    if isinstance(value, str) and "-" in value:
        value = tuple(value.split("-", 1))
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        value = (row.get("home_goals"), row.get("away_goals"))
    try:
        home, away = int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (home, away) if home >= 0 and away >= 0 else None


def _top1_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values: list[bool] = []
    for row in rows:
        scores = row.get("top_scores")
        actual = row.get("actual")
        if not isinstance(scores, list) or not scores or not isinstance(actual, Mapping):
            continue
        top = scores[0]
        if not isinstance(top, Mapping):
            continue
        top_score = _score_pair(top)
        actual_score = (actual.get("home_goals"), actual.get("away_goals"))
        if top_score is None or any(value is None for value in actual_score):
            continue
        values.append(top_score == (int(actual_score[0]), int(actual_score[1])))
    return {
        "available": bool(values),
        "count": sum(values),
        "share": sum(values) / len(values) if values else None,
    }


def _one_to_one_stats(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values: list[bool] = []
    for row in rows:
        scores = row.get("top_scores")
        if not isinstance(scores, list) or not scores or not isinstance(scores[0], Mapping):
            continue
        top = _score_pair(scores[0])
        if top is not None:
            values.append(top == (1, 1))
    return {
        "count": sum(values),
        "share": sum(values) / len(values) if values else None,
    }


def _empty_model_metrics() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "match_keys": [],
        "one_x_two": {"brier": None, "log_loss": None},
        "one_x_two_brier": None,
        "one_x_two_log_loss": None,
        "exact_score_top1": {"available": False, "count": 0, "share": None},
    }


def _model_metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_model_metrics()
    evaluated = evaluate_predictions(rows)
    brier = float(evaluated["one_x_two_brier"])
    log_loss = float(evaluated["one_x_two_log_loss"])
    result = {
        "sample_count": len(rows),
        "match_keys": sorted(_text(row.get("match_key")) for row in rows),
        "one_x_two": {"brier": brier, "log_loss": log_loss},
        "one_x_two_brier": brier,
        "one_x_two_log_loss": log_loss,
        "exact_score_top1": _top1_stats(rows),
    }
    return result


def _market_metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _empty_model_metrics()
    briers: list[float] = []
    log_losses: list[float] = []
    for row in rows:
        actual = row["actual"]
        home, away = int(actual["home_goals"]), int(actual["away_goals"])
        outcome = "home" if home > away else "draw" if home == away else "away"
        probabilities = row["probabilities"]
        briers.append(sum((float(probabilities[label]) - float(label == outcome)) ** 2 for label in ("home", "draw", "away")))
        log_losses.append(-log(max(float(probabilities[outcome]), _EPSILON)))
    brier = sum(briers) / len(briers)
    log_loss = sum(log_losses) / len(log_losses)
    result = {
        "sample_count": len(rows),
        "match_keys": sorted(_text(row.get("match_key")) for row in rows),
        "one_x_two": {"brier": brier, "log_loss": log_loss},
        "one_x_two_brier": brier,
        "one_x_two_log_loss": log_loss,
        "exact_score_top1": {"available": False, "count": 0, "share": None},
    }
    return result


def _diagnostics(champion_rows: list[Mapping[str, Any]], candidate_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    home_gaps: list[float] = []
    away_gaps: list[float] = []
    mean_gaps: list[float] = []
    for champion, candidate in zip(champion_rows, candidate_rows):
        home_gap = abs(float(champion["lambda_home"]) - float(candidate["lambda_home"]))
        away_gap = abs(float(champion["lambda_away"]) - float(candidate["lambda_away"]))
        home_gaps.append(home_gap)
        away_gaps.append(away_gap)
        mean_gaps.append((home_gap + away_gap) / 2.0)
    count = len(mean_gaps)
    below = sum(value < 0.5 for value in mean_gaps)
    return {
        "mean_abs_lambda_gap": sum(mean_gaps) / count if count else None,
        "mean_abs_lambda_gap_home": sum(home_gaps) / count if count else None,
        "mean_abs_lambda_gap_away": sum(away_gaps) / count if count else None,
        "lambda_gap_below_0_5": {
            "count": below,
            "share": below / count if count else None,
        },
        "top1_one_to_one": {
            "champion": _one_to_one_stats(champion_rows),
            "candidate": _one_to_one_stats(candidate_rows),
        },
    }


def _result(
    *,
    status: str,
    blocking_reasons: list[str],
    champion_rows: list[Mapping[str, Any]],
    candidate_rows: list[Mapping[str, Any]],
    market_rows: list[Mapping[str, Any]],
    market_status: str,
    market_exclusions: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    metrics = {
        "champion": _model_metrics(champion_rows),
        "candidate": _model_metrics(candidate_rows),
        "market": _market_metrics(market_rows),
    }
    diagnostics = _diagnostics(champion_rows, candidate_rows)
    reasons = list(dict.fromkeys(blocking_reasons))
    return {
        "mode": "research_only_qualification_evidence",
        "status": status,
        "promotion_eligible": False,
        "automatic_promotion": False,
        "blocking_reasons": reasons,
        "paired_sample_count": len(champion_rows),
        "market_sample_count": len(market_rows),
        "paired": {
            "same_match_keys": bool(champion_rows) and [row.get("match_key") for row in champion_rows] == [row.get("match_key") for row in candidate_rows],
            "sample_count": len(champion_rows),
            "match_keys": sorted(_text(row.get("match_key")) for row in champion_rows),
        },
        "metrics": metrics,
        "champion_metrics": metrics["champion"],
        "candidate_metrics": metrics["candidate"],
        "market_metrics": metrics["market"],
        "diagnostics": diagnostics,
        "market": {
            "contract": MARKET_SNAPSHOT_CONTRACT_VERSION,
            "status": market_status,
            "sample_count": len(market_rows),
            "match_keys": sorted(_text(row.get("match_key")) for row in market_rows),
            "excluded_match_keys": {key: list(values) for key, values in sorted((market_exclusions or {}).items())},
        },
    }


def evaluate_qualification_evidence(
    pair_evidence: Any,
    *,
    champion_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    candidate_records: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
    market_snapshots: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare one explicitly supplied research candidate on settled pairs.

    ``market_snapshots`` is not a prediction record.  Each snapshot must carry
    ``match_key``, ``snapshot_at``, ``snapshot_id`` or ``snapshot_sha256``, and
    already-normalized ``probabilities`` for home/draw/away.
    """

    try:
        adapted = adapt_settled_pairs(
            pair_evidence,
            champion_records=champion_records,
            challenger_records=candidate_records,
        )
    except PairQualityAdapterError as error:
        return _result(
            status="INSUFFICIENT_EVIDENCE",
            blocking_reasons=[f"pair_adapter:{error.code}"],
            champion_rows=[],
            candidate_rows=[],
            market_rows=[],
            market_status="UNAVAILABLE",
        )

    champion_rows = list(adapted["champion_predictions"])
    candidate_rows = list(adapted["challenger_predictions"])
    market_index, invalid_market = _market_index(market_snapshots)
    champion_by_id = { _text(row.get("prediction_id")): row for row in _records(champion_records) }
    candidate_by_id = { _text(row.get("prediction_id")): row for row in _records(candidate_records) }
    market_rows: list[dict[str, Any]] = []
    exclusions: dict[str, list[str]] = {}

    for champion_row in champion_rows:
        match_key = _text(champion_row.get("match_key"))
        candidates = market_index.get(match_key, [])
        reasons: list[str] = []
        if len(candidates) == 0:
            reasons.extend(invalid_market.get(match_key, []) or ["market_snapshot_missing"])
        elif len(candidates) != 1:
            reasons.append("market_snapshot_duplicate")
        else:
            snapshot = candidates[0]
            champion = champion_by_id.get(_text(champion_row.get("prediction_id")), {})
            candidate = candidate_by_id.get(_text(next(
                row.get("prediction_id") for row in candidate_rows if row.get("pair_id") == champion_row.get("pair_id")
            )), {})
            cutoff = _time(champion.get("source_cutoff_at"), "pair_evidence_cutoff_missing")
            kickoff = _time(champion.get("kickoff_at"), "pair_kickoff_missing")
            if snapshot["snapshot_at"] > cutoff:
                reasons.append("market_snapshot_after_pair_cutoff")
            if snapshot["snapshot_at"] >= kickoff:
                reasons.append("market_snapshot_not_prematch")
            expected_ids, expected_times, identity_conflict, timestamp_conflict = _expected_market_identity(champion, candidate)
            if identity_conflict:
                reasons.append("market_frozen_snapshot_identity_conflict")
            if timestamp_conflict:
                reasons.append("market_frozen_snapshot_timestamp_conflict")
            if expected_ids and not expected_ids.intersection(snapshot["identities"]):
                reasons.append("market_snapshot_identity_mismatch")
            if expected_times and snapshot["snapshot_at"] not in expected_times:
                reasons.append("market_snapshot_timestamp_mismatch")
            if not reasons:
                market_rows.append({
                    "match_key": match_key,
                    "actual": champion_row["actual"],
                    "probabilities": snapshot["probabilities"],
                })
        if reasons:
            exclusions[match_key] = list(dict.fromkeys(reasons))

    blocking_reasons = [reason for reasons in exclusions.values() for reason in reasons]
    if not champion_rows:
        return _result(
            status="INSUFFICIENT_EVIDENCE",
            blocking_reasons=blocking_reasons or ["true_paired_samples_unavailable"],
            champion_rows=champion_rows,
            candidate_rows=candidate_rows,
            market_rows=market_rows,
            market_status="UNAVAILABLE",
            market_exclusions=exclusions,
        )
    if len(market_rows) != len(champion_rows):
        status = "PARTIAL_EVIDENCE"
        market_status = "PARTIAL" if market_rows else "UNAVAILABLE"
    else:
        status = "EVIDENCE_AVAILABLE"
        market_status = "AVAILABLE"
    return _result(
        status=status,
        blocking_reasons=blocking_reasons,
        champion_rows=champion_rows,
        candidate_rows=candidate_rows,
        market_rows=market_rows,
        market_status=market_status,
        market_exclusions=exclusions,
    )


__all__ = [
    "MARKET_SNAPSHOT_CONTRACT_VERSION",
    "MarketSnapshotError",
    "evaluate_qualification_evidence",
]
