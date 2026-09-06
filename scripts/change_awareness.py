"""Build a result-blind, read-only comparison of immutable prematch snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

try:
    from .formal_market_projection import project_frozen_formal_markets
    from .prematch_versioning import select_latest_legal_prematch
except ImportError:  # pragma: no cover - direct script/test execution path.
    from formal_market_projection import project_frozen_formal_markets  # type: ignore
    from prematch_versioning import select_latest_legal_prematch  # type: ignore


CHANGE_AWARENESS_CONTRACT_VERSION = "prematch_change_awareness.v1"
CHANGE_AWARENESS_STATUS_AVAILABLE = "AVAILABLE"
CHANGE_AWARENESS_STATUS_UNAVAILABLE = "UNAVAILABLE"
PROBABILITY_DELTA_THRESHOLD = 0.0001
EXACT_TOP_LIMIT = 5
FT_1X2_ORDER = ("home", "draw", "away")
JC_TOTAL_GOALS_ORDER = ("0", "1", "2", "3", "4", "5", "6", "7+")
JC_HANDICAP_ORDER = ("home", "draw", "away")
MARKET_ORDER = ("ft_1x2", "exact_score", "jc_total_goals", "jc_handicap")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _probability(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and 0 <= result <= 1 else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _record_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    nested = record.get("match_identity")
    nested = nested if isinstance(nested, Mapping) else {}
    return {
        "match_id": _first(record, "match_id", "live_match_id") or _first(nested, "match_id", "live_match_id"),
        "match_key": _first(record, "match_key", "canonical_match_id")
        or _first(nested, "match_key", "canonical_match_id"),
        "home": _first(record, "home", "home_team") or _first(nested, "home", "home_team"),
        "away": _first(record, "away", "away_team") or _first(nested, "away", "away_team"),
        "kickoff_at": _first(record, "kickoff_at", "kickoff_local")
        or _first(nested, "kickoff_at", "kickoff_local"),
    }


def _expected_identity(current: Mapping[str, Any], identity: Mapping[str, Any] | None) -> dict[str, Any]:
    expected = dict(identity or {})
    current_identity = _record_identity(current)
    for key, value in current_identity.items():
        if expected.get(key) in (None, "") and value not in (None, ""):
            expected[key] = value
    return expected


def _same_canonical_match(record: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    candidate = _record_identity(record)
    expected_match_id = _text(expected.get("match_id"))
    expected_match_key = _text(expected.get("match_key"))
    candidate_match_id = _text(candidate.get("match_id"))
    candidate_match_key = _text(candidate.get("match_key"))

    if expected_match_id:
        if candidate_match_id:
            if candidate_match_id != expected_match_id:
                return False
        elif not expected_match_key or candidate_match_key != expected_match_key:
            return False
    elif expected_match_key:
        if candidate_match_key != expected_match_key:
            return False
    else:
        expected_kickoff = _parse_timestamp(expected.get("kickoff_at"))
        candidate_kickoff = _parse_timestamp(candidate.get("kickoff_at"))
        if expected_kickoff is None or candidate_kickoff is None or expected_kickoff != candidate_kickoff:
            return False
        if _text(candidate.get("home")).casefold() != _text(expected.get("home")).casefold():
            return False
        if _text(candidate.get("away")).casefold() != _text(expected.get("away")).casefold():
            return False

    for key in ("match_key", "home", "away"):
        wanted = _text(expected.get(key))
        actual = _text(candidate.get(key))
        if wanted and actual and wanted.casefold() != actual.casefold():
            return False
    expected_kickoff = _parse_timestamp(expected.get("kickoff_at"))
    candidate_kickoff = _parse_timestamp(candidate.get("kickoff_at"))
    return not (expected_kickoff and candidate_kickoff and expected_kickoff != candidate_kickoff)


def _snapshot_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    chronology = _parse_timestamp(record.get("source_cutoff_at"))
    return {
        "prediction_id": record.get("prediction_id"),
        "freeze_created_at": record.get("freeze_created_at"),
        "source_cutoff_at": record.get("source_cutoff_at"),
        "chronology_timestamp": record.get("source_cutoff_at"),
        "chronology_valid": chronology is not None,
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
        "reason": reason,
        "comparison_allowed": False,
        "items": [],
    }


def _market_item(projection: Mapping[str, Any], name: str) -> dict[str, Any]:
    markets = projection.get("markets")
    item = markets.get(name) if isinstance(markets, Mapping) else None
    return dict(item) if isinstance(item, Mapping) else {"status": "NOT_RECORDED", "reason": "MISSING_MARKET"}


def _contract(
    record: Mapping[str, Any],
    projection: Mapping[str, Any],
    name: str,
    *,
    kickoff: datetime,
) -> tuple[dict[str, Any] | None, str | None]:
    item = _market_item(projection, name)
    if item.get("status") != "AVAILABLE" or not isinstance(item.get("contract"), Mapping):
        return None, str(item.get("reason") or f"{name.upper()}_NOT_AVAILABLE")
    if name == "jc_handicap":
        authority = record.get("jc_handicap")
        authority = authority.get("source_authority") if isinstance(authority, Mapping) else None
        if not isinstance(authority, Mapping):
            return None, "JC_HANDICAP_SOURCE_UNAVAILABLE"
        observed_times = []
        for key in ("request_started_at", "response_at", "fetched_at", "captured_at", "observed_at"):
            if authority.get(key) not in (None, ""):
                parsed = _parse_timestamp(authority.get(key))
                if parsed is None or parsed >= kickoff:
                    return None, "JC_HANDICAP_SOURCE_NOT_STRICTLY_PREMATCH"
                observed_times.append(parsed)
        if not observed_times:
            return None, "JC_HANDICAP_SOURCE_TIME_UNAVAILABLE"
    return dict(item["contract"]), None


def _delta_item(
    key: str,
    before: float,
    now: float,
    *,
    label: str | None = None,
    before_rank: int | None = None,
    now_rank: int | None = None,
) -> dict[str, Any]:
    delta = now - before
    return {
        "key": key,
        "label": label or key,
        "before": before,
        "now": now,
        "delta": delta,
        "delta_probability_points": delta * 100,
        "meaningful": abs(delta) >= PROBABILITY_DELTA_THRESHOLD,
        "before_rank": before_rank,
        "now_rank": now_rank,
    }


def _ft_lane(current: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    current_probabilities = current.get("probabilities")
    previous_probabilities = previous.get("probabilities")
    if not isinstance(current_probabilities, Mapping) or not isinstance(previous_probabilities, Mapping):
        return _unavailable("FT_1X2_PROBABILITIES_NOT_RECORDED")
    labels = {"home": "主胜", "draw": "平", "away": "客胜"}
    values: list[dict[str, Any]] = []
    for key in FT_1X2_ORDER:
        before = _probability(previous_probabilities.get(key))
        now = _probability(current_probabilities.get(key))
        if before is None or now is None:
            return _unavailable("FT_1X2_PROBABILITIES_NOT_COMPARABLE")
        values.append(_delta_item(key, before, now, label=labels[key]))
    return {
        "status": CHANGE_AWARENESS_STATUS_AVAILABLE,
        "reason": None,
        "comparison_allowed": True,
        "items": values,
        "changed": any(item["meaningful"] for item in values),
    }


def _exact_support(contract: Mapping[str, Any]) -> dict[str, Any] | None:
    score_space = contract.get("score_space")
    if not isinstance(score_space, Mapping):
        return None
    return {
        "representation": score_space.get("representation"),
        "support_semantics": score_space.get("support_semantics"),
        "cell_count": score_space.get("cell_count"),
        "max_home_goals": score_space.get("max_home_goals"),
        "max_away_goals": score_space.get("max_away_goals"),
        "tail_bucket": score_space.get("tail_bucket"),
    }


def _exact_cells(contract: Mapping[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    rows = contract.get("cells")
    if not isinstance(rows, list):
        return {}
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            score = (int(row.get("home_goals")), int(row.get("away_goals")))
        except (TypeError, ValueError):
            continue
        probability = _probability(row.get("probability"))
        if probability is not None:
            result[score] = {"score": f"{score[0]}-{score[1]}", "probability": probability}
    return result


def _ranked_exact_cells(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    cells = _exact_cells(contract)
    return sorted(
        [
            {**value, "home_goals": score[0], "away_goals": score[1]}
            for score, value in cells.items()
        ],
        key=lambda item: (-item["probability"], item["home_goals"], item["away_goals"]),
    )


def _exact_lane(
    current_contract: Mapping[str, Any] | None,
    previous_contract: Mapping[str, Any] | None,
    current_reason: str | None,
    previous_reason: str | None,
) -> dict[str, Any]:
    if current_contract is None or previous_contract is None:
        return _unavailable(
            current_reason and f"CURRENT_{current_reason}" or previous_reason and f"PREVIOUS_{previous_reason}" or "EXACT_NOT_COMPARABLE"
        )
    current_support = _exact_support(current_contract)
    previous_support = _exact_support(previous_contract)
    if current_support is None or previous_support is None or current_support != previous_support:
        return _unavailable("EXACT_SUPPORT_NOT_COMPARABLE")
    current_cells = _exact_cells(current_contract)
    previous_cells = _exact_cells(previous_contract)
    if not current_cells or current_cells.keys() != previous_cells.keys():
        return _unavailable("EXACT_EXPLICIT_SUPPORT_NOT_COMPARABLE")
    current_ranked = _ranked_exact_cells(current_contract)
    previous_ranked = _ranked_exact_cells(previous_contract)
    current_ranks = {item["score"]: index for index, item in enumerate(current_ranked, start=1)}
    previous_ranks = {item["score"]: index for index, item in enumerate(previous_ranked, start=1)}
    candidate_scores = {item["score"] for item in current_ranked[:EXACT_TOP_LIMIT]}
    candidate_scores.update(item["score"] for item in previous_ranked[:EXACT_TOP_LIMIT])
    by_score = {item["score"]: item for item in current_ranked}
    before_by_score = {item["score"]: item for item in previous_ranked}
    rows = []
    for score in candidate_scores:
        now = by_score[score]["probability"]
        before = before_by_score[score]["probability"]
        item = _delta_item(
            score,
            before,
            now,
            label=score,
            before_rank=previous_ranks[score],
            now_rank=current_ranks[score],
        )
        item["meaningful"] = item["meaningful"] or item["before_rank"] != item["now_rank"]
        rows.append(item)
    rows.sort(key=lambda item: (item["now_rank"], item["before_rank"], item["key"]))
    meaningful = [item for item in rows if item["meaningful"]]
    return {
        "status": CHANGE_AWARENESS_STATUS_AVAILABLE,
        "reason": None,
        "comparison_allowed": True,
        "support": current_support,
        "top_before": [
            {"score": item["score"], "rank": index, "probability": item["probability"]}
            for index, item in enumerate(previous_ranked[:EXACT_TOP_LIMIT], start=1)
        ],
        "top_now": [
            {"score": item["score"], "rank": index, "probability": item["probability"]}
            for index, item in enumerate(current_ranked[:EXACT_TOP_LIMIT], start=1)
        ],
        "items": meaningful,
        "changed": bool(meaningful),
    }


def _total_signature(contract: Mapping[str, Any]) -> tuple[Any, Any] | None:
    if contract.get("selection_order") != list(JC_TOTAL_GOALS_ORDER):
        return None
    semantics = contract.get("bucket_semantics")
    if not isinstance(semantics, list):
        return None
    compact = tuple(
        (
            item.get("goals"),
            item.get("minimum_total_goals"),
            item.get("maximum_total_goals"),
        )
        for item in semantics
        if isinstance(item, Mapping)
    )
    if compact != (("0", 0, 0),) + tuple((str(value), value, value) for value in range(1, 7)) + (("7+", 7, None),):
        return None
    return tuple(JC_TOTAL_GOALS_ORDER), compact


def _total_lane(
    current_contract: Mapping[str, Any] | None,
    previous_contract: Mapping[str, Any] | None,
    current_reason: str | None,
    previous_reason: str | None,
) -> dict[str, Any]:
    if current_contract is None or previous_contract is None:
        if "JC_TOTAL" in str(current_reason or "") or "JC_TOTAL" in str(previous_reason or ""):
            return _unavailable("JC_TOTAL_GOALS_SCHEMA_NOT_COMPARABLE")
        return _unavailable(
            current_reason and f"CURRENT_{current_reason}" or previous_reason and f"PREVIOUS_{previous_reason}" or "JC_TOTAL_GOALS_NOT_COMPARABLE"
        )
    if _total_signature(current_contract) is None or _total_signature(previous_contract) is None:
        return _unavailable("JC_TOTAL_GOALS_SCHEMA_NOT_COMPARABLE")
    current_probabilities = current_contract.get("probabilities")
    previous_probabilities = previous_contract.get("probabilities")
    if not isinstance(current_probabilities, Mapping) or not isinstance(previous_probabilities, Mapping):
        return _unavailable("JC_TOTAL_GOALS_PROBABILITIES_NOT_COMPARABLE")
    rows = []
    for key in JC_TOTAL_GOALS_ORDER:
        before = _probability(previous_probabilities.get(key))
        now = _probability(current_probabilities.get(key))
        if before is None or now is None:
            return _unavailable("JC_TOTAL_GOALS_PROBABILITIES_NOT_COMPARABLE")
        rows.append(_delta_item(key, before, now))
    return {
        "status": CHANGE_AWARENESS_STATUS_AVAILABLE,
        "reason": None,
        "comparison_allowed": True,
        "selection_order": list(JC_TOTAL_GOALS_ORDER),
        "items": rows,
        "changed": any(item["meaningful"] for item in rows),
    }


def _line_value(contract: Mapping[str, Any]) -> Any:
    value = contract.get("official_integer_line", contract.get("line"))
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else value


def _handicap_lane(
    current_contract: Mapping[str, Any] | None,
    previous_contract: Mapping[str, Any] | None,
    current_reason: str | None,
    previous_reason: str | None,
) -> dict[str, Any]:
    if current_contract is None or previous_contract is None:
        return _unavailable(
            current_reason and f"CURRENT_{current_reason}" or previous_reason and f"PREVIOUS_{previous_reason}" or "JC_HANDICAP_NOT_COMPARABLE"
        )
    current_line = _line_value(current_contract)
    previous_line = _line_value(previous_contract)
    if current_line in (None, "") or previous_line in (None, ""):
        return _unavailable("JC_HANDICAP_LINE_NOT_RECORDED")
    if current_line != previous_line:
        return {
            "status": "LINE_CHANGED",
            "reason": "JC_HANDICAP_LINE_CHANGED",
            "comparison_allowed": False,
            "before_line": previous_line,
            "now_line": current_line,
            "items": [],
            "changed": True,
        }
    current_probabilities = current_contract.get("probabilities")
    previous_probabilities = previous_contract.get("probabilities")
    if not isinstance(current_probabilities, Mapping) or not isinstance(previous_probabilities, Mapping):
        return _unavailable("JC_HANDICAP_PROBABILITIES_NOT_COMPARABLE")
    rows = []
    for key in JC_HANDICAP_ORDER:
        before = _probability(previous_probabilities.get(key))
        now = _probability(current_probabilities.get(key))
        if before is None or now is None:
            return _unavailable("JC_HANDICAP_PROBABILITIES_NOT_COMPARABLE")
        rows.append(_delta_item(key, before, now, label={"home": "主胜", "draw": "平", "away": "客胜"}[key]))
    return {
        "status": CHANGE_AWARENESS_STATUS_AVAILABLE,
        "reason": None,
        "comparison_allowed": True,
        "line": current_line,
        "before_line": previous_line,
        "now_line": current_line,
        "items": rows,
        "changed": any(item["meaningful"] for item in rows),
    }


def _elapsed_seconds(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float | None:
    before = _parse_timestamp(previous.get("source_cutoff_at"))
    now = _parse_timestamp(current.get("source_cutoff_at"))
    if before is None or now is None or now < before:
        return None
    return (now - before).total_seconds()


def _selection_failure_reason(selection: Mapping[str, Any], scope: str) -> str:
    status = _text(selection.get("status"))
    if status == "IDENTITY_CONFLICT":
        return f"{scope}_IDENTITY_CONFLICT"
    if status == "AMBIGUOUS_FINAL_CHRONOLOGY":
        return f"AMBIGUOUS_{scope}_PREMATCH_CHRONOLOGY"
    return f"{scope}_NOT_STRICTLY_PREMATCH"


def build_prematch_change_awareness(
    *,
    records: Iterable[dict[str, Any]],
    current_record: dict[str, Any] | None,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the current immutable record with its nearest earlier legal record.

    Only persisted formal prematch records are accepted.  The function does not
    accept a result argument and never derives a missing market from model
    parameters or a current record.
    """

    record_list = [record for record in records if isinstance(record, dict)]
    expected = _expected_identity(current_record or {}, identity)
    if not isinstance(current_record, dict) or not _same_canonical_match(current_record, expected):
        markets = {name: _unavailable("CURRENT_SNAPSHOT_UNAVAILABLE") for name in MARKET_ORDER}
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": "CURRENT_SNAPSHOT_UNAVAILABLE",
            "current_snapshot": None,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }

    selection_records = list(record_list)
    current_prediction_id = _text(current_record.get("prediction_id"))
    if not any(_text(record.get("prediction_id")) == current_prediction_id for record in selection_records):
        selection_records.append(current_record)

    # Use the repository's canonical selector for the latest snapshot; this
    # deliberately does not order records by freeze time.
    current_selection = select_latest_legal_prematch(selection_records, identity=dict(expected))
    if current_selection.get("status") != "SELECTED":
        markets = {name: _unavailable("CURRENT_SNAPSHOT_NOT_STRICTLY_PREMATCH") for name in MARKET_ORDER}
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": _selection_failure_reason(current_selection, "CURRENT"),
            "current_snapshot": None,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }

    authoritative_current = current_selection.get("selected_record")
    if not isinstance(authoritative_current, dict):
        markets = {name: _unavailable("CURRENT_SNAPSHOT_NOT_STRICTLY_PREMATCH") for name in MARKET_ORDER}
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": "CURRENT_SNAPSHOT_NOT_STRICTLY_PREMATCH",
            "current_snapshot": None,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }
    if _text(authoritative_current.get("prediction_id")) != current_prediction_id:
        markets = {name: _unavailable("CURRENT_SNAPSHOT_NOT_LATEST_LEGAL_PREMATCH") for name in MARKET_ORDER}
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": "CURRENT_SNAPSHOT_NOT_LATEST_LEGAL_PREMATCH",
            "current_snapshot": None,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }

    current_record = authoritative_current
    current_snapshot = _snapshot_summary(current_record)
    previous_candidates = [
        record
        for record in selection_records
        if _text(record.get("prediction_id")) != current_prediction_id
    ]
    # Removing the selected latest record and applying the same selector again
    # yields the immediately previous authoritative version with the same
    # ambiguity and identity-conflict fail-closed behavior.
    previous_selection = select_latest_legal_prematch(previous_candidates, identity=dict(expected))
    if previous_selection.get("status") != "SELECTED":
        markets = {name: _unavailable("NO_COMPARABLE_PREVIOUS_SNAPSHOT") for name in MARKET_ORDER}
        reason = "NO_COMPARABLE_PREVIOUS_SNAPSHOT"
        if previous_selection.get("status") in {"IDENTITY_CONFLICT", "AMBIGUOUS_FINAL_CHRONOLOGY"}:
            reason = _selection_failure_reason(previous_selection, "PREVIOUS")
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": reason,
            "current_snapshot": current_snapshot,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }

    previous_record = previous_selection.get("selected_record")
    if not isinstance(previous_record, dict):
        markets = {name: _unavailable("NO_COMPARABLE_PREVIOUS_SNAPSHOT") for name in MARKET_ORDER}
        return {
            "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
            "status": CHANGE_AWARENESS_STATUS_UNAVAILABLE,
            "reason": "NO_COMPARABLE_PREVIOUS_SNAPSHOT",
            "current_snapshot": current_snapshot,
            "previous_snapshot": None,
            "elapsed_seconds": None,
            "markets": markets,
            "available_market_count": 0,
        }

    previous_snapshot = _snapshot_summary(previous_record)
    current_projection = project_frozen_formal_markets(current_record)
    previous_projection = project_frozen_formal_markets(previous_record)
    kickoff = _parse_timestamp(expected.get("kickoff_at"))
    if kickoff is None:
        markets = {name: _unavailable("CURRENT_SNAPSHOT_KICKOFF_UNAVAILABLE") for name in MARKET_ORDER}
    else:
        current_exact, current_exact_reason = _contract(
            current_record, current_projection, "exact_score", kickoff=kickoff
        )
        previous_exact, previous_exact_reason = _contract(
            previous_record, previous_projection, "exact_score", kickoff=kickoff
        )
        current_total, current_total_reason = _contract(
            current_record, current_projection, "jc_total_goals", kickoff=kickoff
        )
        previous_total, previous_total_reason = _contract(
            previous_record, previous_projection, "jc_total_goals", kickoff=kickoff
        )
        current_handicap, current_handicap_reason = _contract(
            current_record, current_projection, "jc_handicap", kickoff=kickoff
        )
        previous_handicap, previous_handicap_reason = _contract(
            previous_record, previous_projection, "jc_handicap", kickoff=kickoff
        )
        markets = {
            "ft_1x2": _ft_lane(current_record, previous_record),
            "exact_score": _exact_lane(
                current_exact, previous_exact, current_exact_reason, previous_exact_reason
            ),
            "jc_total_goals": _total_lane(
                current_total, previous_total, current_total_reason, previous_total_reason
            ),
            "jc_handicap": _handicap_lane(
                current_handicap, previous_handicap, current_handicap_reason, previous_handicap_reason
            ),
        }

    available_market_count = sum(
        1 for item in markets.values() if item.get("status") in {CHANGE_AWARENESS_STATUS_AVAILABLE, "LINE_CHANGED"}
    )
    return {
        "schema_version": CHANGE_AWARENESS_CONTRACT_VERSION,
        "status": CHANGE_AWARENESS_STATUS_AVAILABLE,
        "reason": None if available_market_count else "NO_COMPARABLE_MARKET_LANE",
        "current_snapshot": current_snapshot,
        "previous_snapshot": previous_snapshot,
        "elapsed_seconds": _elapsed_seconds(previous_record, current_record),
        "markets": markets,
        "available_market_count": available_market_count,
    }
