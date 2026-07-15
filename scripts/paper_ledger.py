#!/usr/bin/env python3
"""Build an auditable paper-betting ledger from frozen pre-match reports."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

MIN_STAKE = 2.0
STAKE_STEP = 0.01
PAPER_BANKROLL = 100.0
KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 0.05


def norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value or "").casefold())


def pair_key(home: Any, away: Any) -> str:
    return f"{norm(home)}|{norm(away)}"


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def round_stake(value: float) -> float:
    """Round down to the platform's executable stake increment."""
    steps = math.floor((value + 1e-12) / STAKE_STEP)
    return round(steps * STAKE_STEP, 2)


def apply_ev_staking(contract: dict) -> dict:
    """Size a paper bet from EV; never turn the minimum into a forced bet.

    Conservative probability is preferred when the report provides one.
    Correct-score reports currently expose only a point probability, which is
    kept explicit in ``sizing_probability_basis`` instead of inventing a
    confidence haircut.
    """
    item = dict(contract)
    odds = number(item.get("odds"))
    point = number(item.get("probability"))
    conservative = number(item.get("conservative_probability"))
    sizing_probability = conservative if conservative is not None else point
    item["point_ev"] = point * odds - 1 if point is not None and odds is not None else None
    item["sizing_probability"] = sizing_probability
    item["sizing_probability_basis"] = (
        "conservative_probability" if conservative is not None else "model_point_probability"
    )
    item["sizing_ev"] = (
        sizing_probability * odds - 1
        if sizing_probability is not None and odds is not None
        else None
    )
    item["stake_units"] = 0.0
    item["kelly_fraction"] = None
    if odds is None or sizing_probability is None:
        item["sizing_status"] = "missing_price_or_probability"
        return item
    if item["sizing_ev"] <= 0:
        item["sizing_status"] = "rejected_non_positive_ev"
        return item
    full_kelly = item["sizing_ev"] / (odds - 1)
    fractional_kelly = max(0.0, full_kelly * KELLY_FRACTION)
    item["kelly_fraction"] = fractional_kelly
    raw_stake = min(PAPER_BANKROLL * fractional_kelly, PAPER_BANKROLL * MAX_STAKE_PCT)
    stake = round_stake(raw_stake)
    if stake < MIN_STAKE:
        item["sizing_status"] = "rejected_below_platform_minimum"
        return item
    item["stake_units"] = stake
    item["sizing_status"] = "paper_candidate"
    return item


def parse_score(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*[-:：]\s*(\d+)", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def primary_contract(payload: dict) -> dict:
    match = payload.get("match") or {}
    decisions = payload.get("decisions") or {}
    primary = str(decisions.get("unique_primary_dimension") or "").strip()
    audits = (payload.get("betting") or {}).get("price_audit") or []
    contract = {
        "ticket_type": "primary",
        "market_group": "其他",
        "market": primary or "未形成首推",
        "selection": None,
        "line": None,
        "odds": None,
        "probability": None,
        "ev": None,
        "stake_units": 0.0,
        "price_source": None,
    }

    total_match = re.search(r"([大小])\s*(\d+(?:\.\d+)?)", primary)
    outcome_key = None
    audit_tokens: list[str] = []
    if total_match:
        side, line = total_match.group(1), float(total_match.group(2))
        contract.update(
            market_group="大小球",
            market=f"全场{side}{line:g}",
            selection="under" if side == "小" else "over",
            line=line,
        )
        audit_tokens = [f"{side}{line:g}"]
    elif "主胜" in primary:
        contract.update(market_group="胜平负", market="90分钟主胜", selection="home")
        outcome_key, audit_tokens = "home", ["SPF主胜", "主胜"]
    elif "客胜" in primary:
        contract.update(market_group="胜平负", market="90分钟客胜", selection="away")
        outcome_key, audit_tokens = "away", ["SPF客胜", "客胜"]
    elif "平局" in primary:
        contract.update(market_group="胜平负", market="90分钟平局", selection="draw")
        outcome_key, audit_tokens = "draw", ["SPF平局", "平局"]
    elif "净胜" in primary or "让" in primary:
        contract.update(market_group="亚盘", selection="unresolved_handicap")

    chosen = None
    for row in audits:
        label = str(row.get("market") or "")
        if audit_tokens and any(token in label for token in audit_tokens) and number(row.get("odds")):
            chosen = row
            break
    if chosen:
        contract["odds"] = number(chosen.get("odds"))
        contract["probability"] = number(chosen.get("model_probability"))
        contract["ev"] = number(chosen.get("ev"))
        contract["conservative_probability"] = number(chosen.get("conservative_probability"))
        contract["conservative_ev"] = number(chosen.get("conservative_ev"))
        contract["price_source"] = str(chosen.get("market") or "赛前公开价格")
    elif outcome_key:
        odds = ((payload.get("market") or {}).get("official_spf") or {}).get(outcome_key)
        probability = ((payload.get("model") or {}).get("probabilities") or {}).get(outcome_key)
        contract["odds"] = number(odds)
        contract["probability"] = number(probability)
        if contract["odds"] and contract["probability"] is not None:
            contract["ev"] = contract["probability"] * contract["odds"] - 1
            contract["price_source"] = "竞彩赛前SPF"
    return contract


def score_contract(payload: dict) -> dict | None:
    decisions = payload.get("decisions") or {}
    score = parse_score(decisions.get("unique_score"))
    if score is None:
        return None
    contracts = (
        (((payload.get("market") or {}).get("polymarket") or {}).get("correct_score") or {}).get("contracts")
        or []
    )
    chosen = None
    for row in contracts:
        if parse_score(row.get("selection_label")) == score and number(row.get("best_ask")):
            chosen = row
            break
    probability = None
    for row in (payload.get("model") or {}).get("score_probabilities") or []:
        if parse_score(row.get("score")) == score:
            probability = number(row.get("probability"))
            break
    result = {
        "ticket_type": "correct_score",
        "market_group": "波胆",
        "market": f"正确比分 {score[0]}-{score[1]}",
        "selection": f"{score[0]}-{score[1]}",
        "line": None,
        "odds": None,
        "probability": probability,
        "ev": None,
        "stake_units": 0.0,
        "price_source": None,
    }
    if chosen:
        ask = number(chosen.get("best_ask"))
        fee_rate = number((chosen.get("fee_schedule") or {}).get("rate")) or 0.0
        gross_profit = (1 / ask) - 1
        result["odds"] = 1 + gross_profit * (1 - fee_rate)
        result["raw_ask_probability"] = ask
        result["fee_rate"] = fee_rate
        result["ev"] = probability * result["odds"] - 1 if probability is not None else None
        result["price_source"] = "Polymarket赛前最佳卖价（扣页面费率后诊断）"
    return result


def settle_ticket(ticket: dict, score: tuple[int, int] | None) -> dict:
    item = dict(ticket)
    odds = number(item.get("odds"))
    stake = number(item.get("stake_units")) or 0.0
    if odds is None:
        item.update(status="observed_no_price", settlement="无有效赛前价格", profit_units=None)
        return item
    if item.get("sizing_status") in {
        "rejected_non_positive_ev",
        "rejected_below_platform_minimum",
    }:
        label = "EV不通过" if item.get("sizing_status") == "rejected_non_positive_ev" else "低于最低投注额"
        item.update(status="rejected_by_ev", settlement=label, profit_units=0.0)
        return item
    if score is None:
        item.update(status="pending", settlement="待赛果", profit_units=None)
        return item
    home, away = score
    selection = item.get("selection")
    result_factor = None
    if selection == "home":
        result_factor = 1 if home > away else -1
    elif selection == "draw":
        result_factor = 1 if home == away else -1
    elif selection == "away":
        result_factor = 1 if home < away else -1
    elif selection in {"over", "under"}:
        total = home + away
        line = float(item["line"])
        quarter = round((line % 1) * 100)
        split = [line]
        if quarter == 25:
            split = [math.floor(line), math.floor(line) + 0.5]
        elif quarter == 75:
            split = [math.floor(line) + 0.5, math.ceil(line)]
        parts = []
        for threshold in split:
            delta = total - threshold
            if selection == "under":
                delta = -delta
            parts.append(1 if delta > 0 else 0 if delta == 0 else -1)
        result_factor = sum(parts) / len(parts)
    elif selection == "home_handicap":
        margin = home - away
        adjusted = margin + float(item["line"])
        result_factor = 1 if adjusted > 0 else 0 if adjusted == 0 else -1
    elif selection == "away_handicap":
        margin = away - home
        adjusted = margin + float(item["line"])
        result_factor = 1 if adjusted > 0 else 0 if adjusted == 0 else -1
    elif isinstance(selection, str) and parse_score(selection):
        result_factor = 1 if parse_score(selection) == score else -1

    if result_factor is None:
        item.update(status="observed_no_settlement_rule", settlement="玩法口径待补", profit_units=None)
        return item
    if result_factor > 0:
        profit = stake * (odds - 1) * result_factor
        label = "赢" if result_factor == 1 else "赢半"
    elif result_factor < 0:
        profit = stake * result_factor
        label = "输" if result_factor == -1 else "输半"
    else:
        profit, label = 0.0, "走"
    item.update(status="settled", settlement=label, profit_units=round(profit, 4), result_score=f"{home}-{away}")
    return item


def summarize(tickets: list[dict]) -> dict:
    settled = [row for row in tickets if row.get("status") == "settled"]
    pending = [row for row in tickets if row.get("status") == "pending"]
    observations = [row for row in tickets if str(row.get("status", "")).startswith("observed_")]
    rejected = [row for row in tickets if row.get("status") == "rejected_by_ev"]
    stake = sum(number(row.get("stake_units")) or 0 for row in settled)
    profit = sum(number(row.get("profit_units")) or 0 for row in settled)
    wins = sum(1 for row in settled if (number(row.get("profit_units")) or 0) > 0)
    losses = sum(1 for row in settled if (number(row.get("profit_units")) or 0) < 0)
    curve = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for row in sorted(settled, key=lambda item: str(item.get("kickoff_local") or "")):
        curve += number(row.get("profit_units")) or 0
        peak = max(peak, curve)
        max_drawdown = max(max_drawdown, peak - curve)
    return {
        "pending": len(pending),
        "settled": len(settled),
        "observations": len(observations),
        "rejected": len(rejected),
        "stake_units": round(stake, 4),
        "profit_units": round(profit, 4),
        "roi": profit / stake if stake else None,
        "wins": wins,
        "losses": losses,
        "hit_rate": wins / (wins + losses) if wins + losses else None,
        "max_drawdown_units": round(max_drawdown, 4),
    }


def freeze_key(ticket: dict) -> str:
    """One immutable paper contract per match and report dimension."""
    return f"{ticket.get('match_key')}|{ticket.get('ticket_type')}"


def report_is_prematch(payload: dict) -> bool:
    analysis = str((payload.get("report") or {}).get("analysis_timestamp") or "").strip()
    kickoff = str((payload.get("match") or {}).get("kickoff_local") or "").strip()
    if not analysis or not kickoff:
        return True
    try:
        analysis_dt = datetime.fromisoformat(analysis.replace("Z", "+00:00"))
        kickoff_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        return analysis_dt <= kickoff_dt
    except (TypeError, ValueError):
        return True


def build_paper_ledger(
    reports: list[dict],
    results: dict[str, tuple[int, int]],
    frozen_tickets: list[dict] | None = None,
    initial_price_overrides: dict[str, dict] | None = None,
) -> dict:
    frozen_tickets = frozen_tickets or []
    initial_price_overrides = initial_price_overrides or {}
    frozen_by_key = {}
    for row in frozen_tickets:
        migrated = dict(row)
        # A frozen direction remains immutable. If the first captured market
        # quote was indexed only after freezing, recover that historical quote
        # without substituting a later price or changing the selection.
        override = initial_price_overrides.get(str(migrated.get("ticket_id") or "")) or {}
        if number(migrated.get("odds")) is None and number(override.get("odds")) is not None:
            for field in (
                "odds", "probability", "ev", "price_source", "price_captured_at",
                "selection", "line", "market", "market_group",
            ):
                if field in override:
                    migrated[field] = override[field]
        # Settled paper history remains immutable. Pending/observed contracts
        # are re-sized because the old implementation incorrectly forced every
        # contract to the 2-yuan minimum without checking EV.
        if migrated.get("status") != "settled":
            migrated = apply_ev_staking(migrated)
        frozen_by_key[freeze_key(migrated)] = migrated
    tickets_by_key = dict(frozen_by_key)
    used_ids = [
        int(match.group(1))
        for row in frozen_tickets
        if (match := re.search(r"(\d+)$", str(row.get("ticket_id") or "")))
    ]
    next_id = max(used_ids, default=0) + 1
    for report in reports:
        payload = report.get("payload") or report
        if not report_is_prematch(payload):
            continue
        match = payload.get("match") or {}
        probabilities = (payload.get("model") or {}).get("probabilities") or {}
        if not all(number(probabilities.get(key)) is not None for key in ("home", "draw", "away")):
            continue
        key = pair_key(match.get("home"), match.get("away"))
        base = {
            "match_key": key,
            "match": f"{match.get('home')} vs {match.get('away')}",
            "home": match.get("home"),
            "away": match.get("away"),
            "kickoff_local": match.get("kickoff_local"),
            "model_version": (payload.get("report") or {}).get("model_version"),
            "frozen_at": (payload.get("report") or {}).get("analysis_timestamp"),
            "real_execution": False,
            "ledger": "模型模拟账",
        }
        for contract in (primary_contract(payload), score_contract(payload)):
            if contract is None:
                continue
            candidate = {"ticket_id": f"SIM-{next_id:04d}", **base, **contract}
            candidate = apply_ev_staking(candidate)
            candidate_key = freeze_key(candidate)
            if candidate_key in tickets_by_key:
                continue
            tickets_by_key[candidate_key] = candidate
            next_id += 1

    frozen_records = []
    for ticket in sorted(tickets_by_key.values(), key=lambda row: str(row.get("ticket_id") or "")):
        frozen_records.append(settle_ticket(ticket, results.get(str(ticket.get("match_key") or ""))))

    # “模拟注单”只记录真正通过价格审核并获得有效模拟金额的合约。
    # 负 EV、低于平台最低金额和无有效赛前价格的候选仍保留在冻结审计中，
    # 但不能进入注单数量、命中率、ROI 或盈亏统计。
    tickets = [
        row for row in frozen_records
        if row.get("status") in {"pending", "settled"}
        and (number(row.get("stake_units")) or 0) >= MIN_STAKE
    ]
    rejected_candidates = [row for row in frozen_records if row.get("status") == "rejected_by_ev"]
    price_pending_candidates = [
        row for row in frozen_records
        if str(row.get("status") or "").startswith("observed_")
    ]
    summary = summarize(tickets)
    groups = []
    for group in ("胜平负", "亚盘", "大小球", "波胆", "其他"):
        rows = [row for row in tickets if row.get("market_group") == group]
        if rows:
            groups.append({"market_group": group, **summarize(rows)})
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "policy": {
            "minimum_stake": MIN_STAKE,
            "stake_step": STAKE_STEP,
            "paper_bankroll": PAPER_BANKROLL,
            "staking_method": "quarter_kelly_positive_ev_only",
            "kelly_fraction": KELLY_FRACTION,
            "maximum_stake_pct": MAX_STAKE_PCT,
            "currency": "CNY",
            "real_balance_affected": False,
            "frozen_snapshot_only": True,
            "missing_price_policy": "observation_only_no_profit",
        },
        "summary": summary,
        "groups": groups,
        "tickets": tickets,
        "screening_summary": {
            "passed": len(tickets),
            "rejected": len(rejected_candidates),
            "waiting_for_price": len(price_pending_candidates),
        },
        "rejected_candidates": rejected_candidates,
        "price_pending_candidates": price_pending_candidates,
        # Only the workspace builder persists this internal collection. It is
        # removed before publishing so rejected candidates never masquerade as
        # simulated bets while immutable directions/first prices remain auditable.
        "_frozen_records": frozen_records,
    }
