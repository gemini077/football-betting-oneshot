"""Read-only projection of immutable formal market contracts.

The product surfaces consume this module instead of deriving a market from
lambda values, legacy top-k rows, or post-match data.  Missing contracts stay
missing; invalid contracts fail closed per market.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

try:
    from .exact_distribution import (
        EXACT_DISTRIBUTION_MAX_GOALS,
        validate_exact_distribution_contract,
        validate_jc_total_goals_contract,
    )
    from .official_jc_handicap import (
        handicap_class,
        validate_jc_handicap_contract,
    )
except ImportError:  # pragma: no cover - direct script/test execution path.
    from exact_distribution import (  # type: ignore
        EXACT_DISTRIBUTION_MAX_GOALS,
        validate_exact_distribution_contract,
        validate_jc_total_goals_contract,
    )
    from official_jc_handicap import (  # type: ignore
        handicap_class,
        validate_jc_handicap_contract,
    )


FORMAL_MARKET_PROJECTION_VERSION = "formal_market_projection.v1"
FORMAL_MARKET_NAMES = ("exact_score", "jc_total_goals", "jc_handicap")
FORMAL_MARKET_STATUS_LABELS = {
    "AVAILABLE": "\u5df2\u8bb0\u5f55",
    "NOT_RECORDED": "\u672a\u8bb0\u5f55",
    "UNAVAILABLE": "\u4e0d\u53ef\u7528",
}

_EXACT_IDENTITY_KEYS = (
    "prediction_id",
    "model_role",
    "model_family",
    "model_core_version",
    "release_version",
    "model_source_fingerprint",
    "model_run_fingerprint",
    "calibration_artifact_sha256",
    "effective_calibration_fingerprint",
    "input_sha256",
)


def _status_entry(status: str, reason: str | None = None, contract: Any = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "contract": deepcopy(contract) if isinstance(contract, Mapping) else None,
    }


def _empty_projection() -> dict[str, Any]:
    return {
        "projection_version": FORMAL_MARKET_PROJECTION_VERSION,
        "authority": "immutable_frozen_prediction_truth",
        "markets": {
            name: _status_entry("NOT_RECORDED", f"MISSING_FROZEN_{name.upper()}")
            for name in FORMAL_MARKET_NAMES
        },
    }


def _expected_exact_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in _EXACT_IDENTITY_KEYS
        if record.get(key) is not None
    }


def _record_contract(record: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = record.get(key)
    return value if isinstance(value, Mapping) else None


def _exact_entry(record: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    contract = _record_contract(record, "exact_score_distribution")
    if contract is None:
        return _status_entry("NOT_RECORDED", "MISSING_FROZEN_EXACT_DISTRIBUTION"), None
    try:
        validate_exact_distribution_contract(
            contract,
            expected_model_identity=_expected_exact_identity(record),
        )
    except ValueError:
        return _status_entry("UNAVAILABLE", "INVALID_FROZEN_EXACT_DISTRIBUTION"), None
    return _status_entry("AVAILABLE", contract=contract), contract


def _total_entry(
    record: Mapping[str, Any],
    exact_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    top_level = _record_contract(record, "jc_total_goals")
    nested = (
        exact_contract.get("jc_total_goals")
        if isinstance(exact_contract, Mapping)
        and isinstance(exact_contract.get("jc_total_goals"), Mapping)
        else None
    )
    if top_level is not None and nested is not None and top_level != nested:
        return _status_entry("UNAVAILABLE", "JC_TOTAL_GOALS_PROJECTION_MISMATCH")
    contract = top_level or nested
    if contract is None:
        return _status_entry("NOT_RECORDED", "MISSING_FROZEN_JC_TOTAL_GOALS")
    try:
        validate_jc_total_goals_contract(contract)
    except ValueError:
        return _status_entry("UNAVAILABLE", "INVALID_FROZEN_JC_TOTAL_GOALS")
    return _status_entry("AVAILABLE", contract=contract)


def _handicap_entry(
    record: Mapping[str, Any],
    exact_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    contract = _record_contract(record, "jc_handicap")
    if contract is None:
        return _status_entry("NOT_RECORDED", "MISSING_FROZEN_JC_HANDICAP")
    if exact_contract is None:
        return _status_entry("UNAVAILABLE", "FROZEN_EXACT_AUTHORITY_UNAVAILABLE")
    try:
        validate_jc_handicap_contract(
            contract,
            expected_exact_content_sha256=exact_contract.get("content_sha256"),
        )
    except ValueError:
        return _status_entry("UNAVAILABLE", "INVALID_FROZEN_JC_HANDICAP")
    if contract.get("served_state") != "FORMAL":
        return _status_entry(
            "UNAVAILABLE",
            str(contract.get("abstain_reason") or "JC_HANDICAP_ABSTAIN"),
            contract,
        )
    return _status_entry("AVAILABLE", contract=contract)


def project_frozen_formal_markets(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project only formal contracts present in one frozen prediction record."""

    if not isinstance(record, Mapping):
        return _empty_projection()
    exact_entry, exact_contract = _exact_entry(record)
    return {
        "projection_version": FORMAL_MARKET_PROJECTION_VERSION,
        "authority": "immutable_frozen_prediction_truth",
        "markets": {
            "exact_score": exact_entry,
            "jc_total_goals": _total_entry(record, exact_contract),
            "jc_handicap": _handicap_entry(record, exact_contract),
        },
    }


def summarize_formal_markets(projection: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a compact dashboard-safe status/probability summary."""

    source = projection if isinstance(projection, Mapping) else _empty_projection()
    markets = source.get("markets") if isinstance(source.get("markets"), Mapping) else {}
    summary: dict[str, Any] = {
        "projection_version": source.get("projection_version", FORMAL_MARKET_PROJECTION_VERSION),
        "authority": source.get("authority", "immutable_frozen_prediction_truth"),
        "markets": {},
    }
    for name in FORMAL_MARKET_NAMES:
        item = markets.get(name) if isinstance(markets.get(name), Mapping) else {}
        result: dict[str, Any] = {
            "status": item.get("status", "NOT_RECORDED"),
            "reason": item.get("reason"),
        }
        contract = item.get("contract") if isinstance(item.get("contract"), Mapping) else None
        if result["status"] == "AVAILABLE" and contract is not None:
            if name == "exact_score":
                result.update({
                    "cell_count": contract.get("score_space", {}).get("cell_count"),
                    "support": {
                        "max_home_goals": contract.get("score_space", {}).get("max_home_goals"),
                        "max_away_goals": contract.get("score_space", {}).get("max_away_goals"),
                        "tail_bucket": contract.get("score_space", {}).get("tail_bucket"),
                    },
                })
            elif name == "jc_total_goals":
                result.update({
                    "selection_order": deepcopy(contract.get("selection_order")),
                    "top_selection": contract.get("top_selection"),
                    "top_probability": contract.get("top_probability"),
                })
            else:
                result.update({
                    "line": contract.get("official_integer_line"),
                    "selection_order": deepcopy(contract.get("selection_order")),
                    "probabilities": deepcopy(contract.get("probabilities")),
                    "top_selection": contract.get("top_selection"),
                    "top_probability": contract.get("top_probability"),
                })
        summary["markets"][name] = result
    return summary


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, Mapping):
        home, away = value.get("home_score_90m", value.get("home_score")), value.get(
            "away_score_90m", value.get("away_score")
        )
        if home is not None and away is not None:
            try:
                return int(home), int(away)
            except (TypeError, ValueError):
                return None
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    text = str(value or "").strip()
    if "-" not in text:
        return None
    home, away = text.split("-", 1)
    try:
        return int(home.strip()), int(away.strip())
    except ValueError:
        return None


def _verification_base(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "verification_status": item.get("status", "NOT_RECORDED"),
        "reason": item.get("reason"),
        "actual_selection": None,
        "actual_probability": None,
        "actual_rank": None,
        "represented_support_status": None,
        "top_selection": None,
        "top_selection_hit": None,
        "line": None,
    }


def verify_formal_markets(
    projection: Mapping[str, Any] | None,
    score_90m: Any,
) -> dict[str, dict[str, Any]]:
    """Compare a verified 90-minute result with frozen formal contracts."""

    source = projection if isinstance(projection, Mapping) else _empty_projection()
    markets = source.get("markets") if isinstance(source.get("markets"), Mapping) else {}
    score = _score_pair(score_90m)
    result: dict[str, dict[str, Any]] = {}
    for name in FORMAL_MARKET_NAMES:
        item = markets.get(name) if isinstance(markets.get(name), Mapping) else {}
        verification = _verification_base(item)
        contract = item.get("contract") if isinstance(item.get("contract"), Mapping) else None
        if item.get("status") != "AVAILABLE" or contract is None:
            result[name] = verification
            continue
        if score is None or score[0] < 0 or score[1] < 0:
            verification.update({"verification_status": "INVALID_90M_SCORE"})
            result[name] = verification
            continue
        home, away = score
        if name == "exact_score":
            if home > EXACT_DISTRIBUTION_MAX_GOALS or away > EXACT_DISTRIBUTION_MAX_GOALS:
                verification.update({
                    "verification_status": "OUT_OF_EXPLICIT_SUPPORT",
                    "reason": "OUT_OF_EXPLICIT_SUPPORT",
                    "actual_selection": f"{home}-{away}",
                    "represented_support_status": "OUT_OF_EXPLICIT_SUPPORT",
                })
                result[name] = verification
                continue
            cells = contract.get("cells") if isinstance(contract.get("cells"), list) else []
            by_score = {
                (cell.get("home_goals"), cell.get("away_goals")): cell
                for cell in cells
                if isinstance(cell, Mapping)
            }
            actual = by_score.get((home, away))
            if actual is None:
                verification.update({"verification_status": "UNAVAILABLE", "reason": "INVALID_FROZEN_EXACT_DISTRIBUTION"})
                result[name] = verification
                continue
            ranked = sorted(
                (cell for cell in cells if isinstance(cell, Mapping)),
                key=lambda cell: (-float(cell.get("probability") or 0.0), cell.get("home_goals"), cell.get("away_goals")),
            )
            top = ranked[0] if ranked else None
            actual_rank = next(
                (
                    index
                    for index, cell in enumerate(ranked, start=1)
                    if cell.get("home_goals") == home and cell.get("away_goals") == away
                ),
                None,
            )
            verification.update({
                "verification_status": "VERIFIED",
                "actual_selection": f"{home}-{away}",
                "actual_probability": _number(actual.get("probability")),
                "actual_rank": actual_rank,
                "represented_support_status": "REPRESENTED",
                "top_selection": f"{top.get('home_goals')}-{top.get('away_goals')}" if top else None,
                "top_selection_hit": bool(top and top.get("home_goals") == home and top.get("away_goals") == away),
            })
        elif name == "jc_total_goals":
            bucket = str(home + away) if home + away <= 6 else "7+"
            probabilities = contract.get("probabilities") if isinstance(contract.get("probabilities"), Mapping) else {}
            verification.update({
                "verification_status": "VERIFIED",
                "actual_selection": bucket,
                "actual_probability": _number(probabilities.get(bucket)),
                "top_selection": contract.get("top_selection"),
                "top_selection_hit": contract.get("top_selection") == bucket,
            })
        else:
            line = contract.get("official_integer_line", contract.get("line"))
            try:
                actual_class = handicap_class(home, away, line)
            except (TypeError, ValueError):
                verification.update({"verification_status": "UNAVAILABLE", "reason": "INVALID_FROZEN_JC_HANDICAP"})
                result[name] = verification
                continue
            probabilities = contract.get("probabilities") if isinstance(contract.get("probabilities"), Mapping) else {}
            verification.update({
                "verification_status": "VERIFIED",
                "actual_selection": actual_class,
                "actual_probability": _number(probabilities.get(actual_class)),
                "top_selection": contract.get("top_selection"),
                "top_selection_hit": contract.get("top_selection") == actual_class,
                "line": line,
            })
        result[name] = verification
    return result
