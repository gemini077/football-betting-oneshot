#!/usr/bin/env python3
"""Reprice a calibrated betting candidate against a live or user-supplied quote.

This module is deliberately read-only.  It never submits an order, mutates the
bankroll, or changes lock state.  It currently supports simple win/lose event
contracts only; Asian lines with push/half-win/half-loss settlement require a
full settlement distribution and are rejected here.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from risk_engine import binary_kelly_diagnostic


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "live_ev_reprices"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8765"
MODEL_NAME = "Football Betting OneShot"
MODEL_VERSION = "v0.14.0"
SUPPORTED_CONTRACT_TYPES = {"binary_no_push", "three_way_selection"}


class RepriceValidationError(ValueError):
    """Raised when a request is structurally unsafe or incomplete."""


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RepriceValidationError("request JSON must be an object")
    return data


def _text(value) -> str:
    return str(value or "").strip()


def _canonical_text(value) -> str:
    return " ".join(_text(value).split()).casefold()


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def canonical_line(value) -> str:
    """Canonicalize equivalent line notation without fuzzy line matching.

    For example, ``2.5/3`` and ``2.75`` identify the same quarter line.  Text
    that is not a numeric line is compared exactly after whitespace folding.
    """
    text = _text(value).replace("／", "/")
    if not text:
        return ""
    try:
        if "/" in text:
            parts = [Decimal(part.strip()) for part in text.split("/")]
            if len(parts) != 2:
                raise InvalidOperation
            return _decimal_text(sum(parts) / Decimal(2))
        return _decimal_text(Decimal(text))
    except (InvalidOperation, ValueError):
        return _canonical_text(text)


def _probability(value, field: str, *, required: bool) -> float | None:
    if value is None:
        if required:
            raise RepriceValidationError(f"{field} is required")
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise RepriceValidationError(f"{field} must be finite and between 0 and 1")
    return number


def _base_result(request: dict) -> dict:
    contract = request.get("contract") or {}
    probability = request.get("probability") or {}
    return {
        "schema_version": "1.0",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "contract": {
            "match_id": _text(contract.get("match_id")),
            "market_code": _text(contract.get("market_code")) or None,
            "market_name": _text(contract.get("market_name")) or None,
            "child_market_code": _text(contract.get("child_market_code")) or None,
            "market_id": _text(contract.get("market_id")) or None,
            "handicap_line": _text(contract.get("handicap_line")),
            "canonical_line": canonical_line(contract.get("handicap_line")),
            "selection_code": _text(contract.get("selection_code")) or None,
            "selection_name": _text(contract.get("selection_name")) or None,
            "contract_type": _text(contract.get("contract_type")),
        },
        "probability": {
            "point": probability.get("point"),
            "conservative": probability.get("conservative"),
            "source": probability.get("source"),
            "calibration_status": probability.get("calibration_status"),
        },
        "price": None,
        "ev": None,
        "match_state": None,
        "staking": {
            "method": "fixed_small_stake_with_exposure_caps",
            "suggested_stake": 0.0,
            "currency": "CNY",
            "kelly_is_diagnostic_only": True,
            "explicit_lock_required": True,
            "status": "not_evaluated"
        },
        "decision_status": None,
        "bet_status": "no_bet",
        "reason": None,
        "analysis_input_only": True,
        "execution_authorized": False,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
        "in_play_betting_enabled": False,
    }


def _finish(result: dict, status: str, reason: str, *, bet_status: str = "no_bet") -> dict:
    result["decision_status"] = status
    result["bet_status"] = bet_status
    result["reason"] = reason
    return result


def _contract_matches(quote: dict, contract: dict) -> bool:
    if _text(quote.get("match_id")) != _text(contract.get("match_id")):
        return False
    market_code = _text(contract.get("market_code"))
    market_name = _text(contract.get("market_name"))
    if market_code:
        if _text(quote.get("market_code")) != market_code:
            return False
    elif market_name:
        if _canonical_text(quote.get("market_name")) != _canonical_text(market_name):
            return False
    else:
        raise RepriceValidationError("contract.market_code or contract.market_name is required")
    if canonical_line(quote.get("handicap_line")) != canonical_line(contract.get("handicap_line")):
        return False
    selection_code = _text(contract.get("selection_code"))
    selection_name = _text(contract.get("selection_name"))
    if selection_code:
        if _canonical_text(quote.get("selection_code")) != _canonical_text(selection_code):
            return False
    elif selection_name:
        if _canonical_text(quote.get("selection_name")) != _canonical_text(selection_name):
            return False
    else:
        raise RepriceValidationError("contract.selection_code or contract.selection_name is required")
    for field in ("child_market_code", "market_id"):
        expected = _text(contract.get(field))
        if expected and _text(quote.get(field)) != expected:
            return False
    return True


def fetch_latest(bridge_url: str, match_id: str, timeout_seconds: float = 5.0) -> dict:
    query = urlencode({"match_id": match_id, "active_only": "true"})
    url = f"{bridge_url.rstrip('/')}/v1/latest?{query}"
    with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - loopback URL by policy
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get("ok"):
        raise RepriceValidationError("bridge latest endpoint returned an invalid response")
    return data


def _bridge_price(request: dict, latest_payload: dict | None) -> tuple[dict | None, str | None, str | None]:
    contract = request.get("contract") or {}
    price_request = request.get("price") or {}
    match_id = _text(contract.get("match_id"))
    if not match_id:
        raise RepriceValidationError("contract.match_id is required")
    payload = latest_payload or fetch_latest(
        _text(price_request.get("bridge_url")) or DEFAULT_BRIDGE_URL,
        match_id,
        float(price_request.get("timeout_seconds", 5.0)),
    )
    matches = [quote for quote in payload.get("quotes", []) if _contract_matches(quote, contract)]
    if not matches:
        return None, "contract_not_found", "最新报价中找不到完全相同的比赛、玩法、盘口线和选项"
    if len(matches) > 1:
        return None, "contract_ambiguous", "同一查询匹配到多个报价；请补充child_market_code或market_id"
    quote = matches[0]
    price = {
        "source": "bridge",
        "bridge_url": _text(price_request.get("bridge_url")) or DEFAULT_BRIDGE_URL,
        "decimal_odds": quote.get("inferred_decimal_odds"),
        "odds_format": "decimal",
        "odds_scale_verified": bool(quote.get("odds_scale_verified")),
        "source_timestamp_ms": quote.get("source_timestamp_ms"),
        "received_at": quote.get("received_at"),
        "quote_age_ms": quote.get("quote_age_ms"),
        "page_activity_age_ms": (latest_payload.get("match_activity") or {}).get("age_ms"),
        "max_quote_age_ms": int(price_request.get("max_quote_age_ms", 15000)),
        "market_status": quote.get("market_status"),
        "selection_status": quote.get("selection_status"),
        "matched_quote": {
            key: quote.get(key)
            for key in (
                "match_id", "market_code", "market_name", "child_market_code", "market_id",
                "handicap_line", "selection_code", "selection_name", "display_price",
            )
        },
    }
    if quote.get("market_status") != 0 or quote.get("selection_status") != 1:
        return price, "quote_inactive", "盘口或选项当前不是开放状态"
    if not price["odds_scale_verified"]:
        return price, "odds_unverified", "赔率尺度尚未通过原始价与展示价交叉核验"
    age = quote.get("quote_age_ms")
    activity_age = price.get("page_activity_age_ms")
    quote_is_fresh = age is not None and int(age) <= price["max_quote_age_ms"]
    page_is_live = activity_age is not None and int(activity_age) <= price["max_quote_age_ms"]
    if not quote_is_fresh and not page_is_live:
        return price, "quote_stale", "源报价已超过允许的新鲜度窗口"
    price["freshness_basis"] = "quote_timestamp" if quote_is_fresh else "active_match_page_heartbeat"
    return price, None, None


def _match_state(latest_payload: dict, match_id: str) -> dict:
    metadata = next(
        (row for row in latest_payload.get("match_metadata", []) if _text(row.get("match_id")) == match_id),
        {},
    )
    clock = next(
        (row for row in latest_payload.get("match_clocks", []) if _text(row.get("match_id")) == match_id),
        {},
    )
    status = _text(metadata.get("match_status"))
    phase = "pre_match" if status == "0" else ("unknown" if not status else "non_pre_match")
    return {
        "phase": phase,
        "match_status": status or None,
        "match_period": metadata.get("match_period"),
        "clock_seconds": clock.get("clock_seconds"),
        "home_score": metadata.get("home_score"),
        "away_score": metadata.get("away_score"),
    }


def _staking_recommendation(request: dict, result: dict) -> tuple[dict, bool]:
    staking_request = request.get("staking")
    if not staking_request:
        return result["staking"], True
    try:
        bankroll = float(staking_request.get("bankroll"))
        daily_exposure = float(staking_request.get("current_daily_exposure", 0.0))
        daily_cap_pct = float(staking_request.get("daily_exposure_cap_pct", 0.05))
        single_cap_pct = float(staking_request.get("single_match_cap_pct", 0.05))
        fixed_min = float(staking_request.get("fixed_stake_min", 2.0))
        fixed_max = float(staking_request.get("fixed_stake_max", 3.0))
        high_quality_ev = float(staking_request.get("high_quality_conservative_ev", 0.10))
    except (TypeError, ValueError) as exc:
        raise RepriceValidationError("staking fields must be numeric") from exc
    numbers = (bankroll, daily_exposure, daily_cap_pct, single_cap_pct, fixed_min, fixed_max, high_quality_ev)
    if any(not math.isfinite(value) for value in numbers):
        raise RepriceValidationError("staking fields must be finite")
    if bankroll <= 0 or daily_exposure < 0 or fixed_min <= 0 or fixed_max < fixed_min:
        raise RepriceValidationError("staking bankroll/exposure/fixed stake settings are invalid")
    if not 0 < daily_cap_pct <= 0.10 or not 0 < single_cap_pct <= 0.05:
        raise RepriceValidationError("staking caps exceed the current model limits")

    conservative = float(result["probability"]["conservative"])
    decimal_odds = float(result["price"]["decimal_odds"])
    diagnostic = binary_kelly_diagnostic(conservative, decimal_odds, fraction_multiplier=1.0)
    daily_cap_amount = bankroll * daily_cap_pct
    single_cap_amount = bankroll * single_cap_pct
    remaining_daily_cap = max(0.0, daily_cap_amount - daily_exposure)
    base_fixed_stake = fixed_max if float(result["ev"]["conservative_ev"]) >= high_quality_ev else fixed_min
    suggested = math.floor(min(base_fixed_stake, remaining_daily_cap, single_cap_amount) + 1e-9)
    if suggested < fixed_min:
        suggested = 0
    staking = {
        "method": "fixed_small_stake_with_exposure_caps",
        "bankroll": bankroll,
        "current_daily_exposure": daily_exposure,
        "daily_exposure_cap_pct": daily_cap_pct,
        "daily_exposure_cap_amount": daily_cap_amount,
        "remaining_daily_cap": remaining_daily_cap,
        "single_match_cap_pct": single_cap_pct,
        "single_match_cap_amount": single_cap_amount,
        "fixed_stake_range": [fixed_min, fixed_max],
        "base_fixed_stake": base_fixed_stake,
        "suggested_stake": float(suggested),
        "currency": _text(staking_request.get("currency")) or "CNY",
        "diagnostic_full_kelly_fraction": diagnostic["full_kelly_fraction"],
        "kelly_is_diagnostic_only": True,
        "explicit_lock_required": True,
        "status": "candidate_amount" if suggested > 0 else "exposure_limit",
    }
    return staking, suggested > 0


def _manual_price(request: dict) -> tuple[dict | None, str | None, str | None]:
    contract = request.get("contract") or {}
    price_request = request.get("price") or {}
    if _canonical_text(price_request.get("odds_format")) != "decimal":
        return None, "odds_format_unverified", "手工渠道价必须明确声明odds_format=decimal"
    observed_line = price_request.get("handicap_line", contract.get("handicap_line"))
    if canonical_line(observed_line) != canonical_line(contract.get("handicap_line")):
        return None, "requires_probability_recompute", "用户渠道盘口线已变化，必须先重算新盘口事件概率"
    observed_selection = price_request.get("selection_code")
    if observed_selection is not None and _canonical_text(observed_selection) != _canonical_text(contract.get("selection_code")):
        return None, "requires_probability_recompute", "用户渠道选项与原候选不同，必须先重算对应事件概率"
    try:
        decimal_odds = float(price_request.get("decimal_odds"))
    except (TypeError, ValueError):
        return None, "invalid_manual_price", "缺少有效的用户渠道十进制赔率"
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        return None, "invalid_manual_price", "用户渠道十进制赔率必须大于1.0"
    return {
        "source": "user_channel_manual",
        "decimal_odds": decimal_odds,
        "odds_format": "decimal",
        "odds_scale_verified": True,
        "observed_at": price_request.get("observed_at"),
        "handicap_line": _text(observed_line),
        "selection_code": _text(price_request.get("selection_code") or contract.get("selection_code")),
        "user_supplied": True,
    }, None, None


def evaluate_request(request: dict, *, latest_payload: dict | None = None) -> dict:
    """Evaluate a repricing request and return a non-executable decision record."""
    result = _base_result(request)
    contract = request.get("contract") or {}
    contract_type = _text(contract.get("contract_type"))
    if contract_type not in SUPPORTED_CONTRACT_TYPES:
        return _finish(
            result,
            "unsupported_settlement",
            "当前重算器只接受binary_no_push或three_way_selection；亚洲走盘/赢半/输半须使用完整结算分布",
        )

    point = _probability((request.get("probability") or {}).get("point"), "probability.point", required=True)
    conservative = _probability(
        (request.get("probability") or {}).get("conservative"),
        "probability.conservative",
        required=False,
    )
    if conservative is not None and conservative > point:
        raise RepriceValidationError("probability.conservative cannot exceed probability.point")
    result["probability"]["point"] = point
    result["probability"]["conservative"] = conservative

    price_request = request.get("price") or {}
    source = _canonical_text(price_request.get("source") or "bridge")
    if source == "bridge":
        if latest_payload is None:
            latest_payload = fetch_latest(
                _text(price_request.get("bridge_url")) or DEFAULT_BRIDGE_URL,
                _text(contract.get("match_id")),
                float(price_request.get("timeout_seconds", 5.0)),
            )
        result["match_state"] = _match_state(latest_payload, _text(contract.get("match_id")))
        if result["match_state"]["phase"] == "non_pre_match":
            return _finish(
                result,
                "in_play_probability_not_supported",
                "比赛已不是赛前状态；当前模型未验证赛中概率，禁止用赛前概率计算投注",
                bet_status="shadow_only",
            )
        price, gate_status, gate_reason = _bridge_price(request, latest_payload)
    elif source in {"manual", "user_channel_manual"}:
        price, gate_status, gate_reason = _manual_price(request)
    else:
        raise RepriceValidationError("price.source must be bridge or manual")
    result["price"] = price
    if gate_status:
        return _finish(result, gate_status, gate_reason or gate_status)

    decimal_odds = float(price["decimal_odds"])
    point_diag = binary_kelly_diagnostic(point, decimal_odds, fraction_multiplier=0.0)
    conservative_diag = (
        binary_kelly_diagnostic(conservative, decimal_odds, fraction_multiplier=0.0)
        if conservative is not None
        else None
    )
    result["ev"] = {
        "formula": "p * decimal_odds - 1",
        "fair_decimal_odds_point": 1.0 / point,
        "fair_decimal_odds_conservative": 1.0 / conservative if conservative is not None else None,
        "point_ev": point_diag["expected_value"],
        "conservative_ev": conservative_diag["expected_value"] if conservative_diag else None,
        "minimum_conservative_ev": float((request.get("execution") or {}).get("minimum_conservative_ev", 0.0)),
        "minimum_acceptable_decimal_odds": None,
        "kelly_scope": "diagnostic_only_no_stake_authority",
    }
    if conservative is not None:
        result["ev"]["minimum_acceptable_decimal_odds"] = (
            1.0 + result["ev"]["minimum_conservative_ev"]
        ) / conservative

    if bool(request.get("validation_only")):
        return _finish(result, "shadow_only_validation", "验证输入不生成候选", bet_status="shadow_only")
    if not bool((request.get("probability") or {}).get("confirmed_model_output")):
        return _finish(
            result,
            "probability_provenance_unconfirmed",
            "尚未确认概率来自当前模型报告；只展示影子计算，不生成金额建议",
            bet_status="shadow_only",
        )
    if conservative is None:
        return _finish(
            result,
            "probability_uncertainty_missing",
            "缺少保守概率边界；仅展示点估计EV，不进入候选",
            bet_status="shadow_only",
        )
    minimum_ev = result["ev"]["minimum_conservative_ev"]
    if result["ev"]["conservative_ev"] > minimum_ev:
        result = _finish(
            result,
            "candidate_price_pass",
            "同一合约的已校验新鲜价格通过保守EV执行线；仍需用户明确锁单",
            bet_status="candidate",
        )
        result["staking"], has_amount = _staking_recommendation(request, result)
        if not has_amount and request.get("staking"):
            return _finish(result, "exposure_limit", "价格通过但固定小额或暴露上限不允许新增金额")
        return result
    return _finish(result, "price_insufficient", "保守EV未超过执行线，保持空仓")


def write_result(result: dict, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / stamp
    suffix = 1
    while run_dir.exists():
        run_dir = output_root / f"{stamp}_{suffix:02d}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    match_id = _text((result.get("contract") or {}).get("match_id")) or "unknown_match"
    path = run_dir / f"{run_dir.name}_{match_id}_EV复算.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Football Betting OneShot v0.8.0 实时/用户渠道赔率EV复算")
    parser.add_argument("--request", required=True, type=Path, help="EV复算请求JSON")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--no-write", action="store_true", help="只输出到终端，不写入批次文件")
    args = parser.parse_args()
    try:
        result = evaluate_request(load_json(args.request))
    except (OSError, json.JSONDecodeError, RepriceValidationError, ValueError) as exc:
        result = {
            "ok": False,
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "error": str(exc),
            "analysis_input_only": True,
            "execution_authorized": False,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
            "in_play_betting_enabled": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    result["ok"] = True
    if not args.no_write:
        result["output_file"] = str(write_result(result, args.output_root))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

