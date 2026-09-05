from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_implied_score_baseline_audit as audit


def _record(prediction_id: str, freeze_at: str, *, actual_score: str | None = None) -> dict:
    record = {
        "prediction_id": prediction_id,
        "match_key": "MATCH-1",
        "match_id": "500-1",
        "match_identity": {
            "match_key": "MATCH-1",
            "match_id": "500-1",
            "home": "HOME",
            "away": "AWAY",
            "kickoff_at": "2026-01-01T12:00:00+08:00",
        },
        "home": "HOME",
        "away": "AWAY",
        "kickoff_at": "2026-01-01T12:00:00+08:00",
        "source_cutoff_at": "2026-01-01T08:00:00+08:00",
        "prediction_created_at": "2026-01-01T09:00:00+08:00",
        "freeze_created_at": freeze_at,
        "prediction_status": "formal",
        "model_role": "champion",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "model_core_version": "recent_form_market_calibrated_poisson_v2",
        "prediction_variant": "model_only",
        "manual_override": None,
        "formal_eligible": True,
        "model_formal_eligible": True,
        "model_input_snapshot_ref": "data/model_governance/input_snapshots/fixture.json",
        "input_sha256": "a" * 64,
        "model_source_fingerprint": "b" * 64,
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "data_grade": "B",
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "lambda_home": 1.4,
        "lambda_away": 1.0,
        "score_top1": "1-0",
        "score_top3": ["1-0", "1-1", "0-0"],
        "score_top5": ["1-0", "1-1", "0-0", "2-0", "0-1"],
    }
    if actual_score:
        record["actual_score"] = actual_score
    return record


def _quote_snapshot(*, fetched_at: str = "2026-01-01T08:00:00+08:00") -> dict:
    return {
        "fetched_at": fetched_at,
        "ouzhi": {
            "bookmakers": [
                {"cid": 1, "spf_current": {"home": 2.0, "draw": 4.0, "away": 4.0}},
                {"cid": 2, "spf_current": {"home": 2.1, "draw": 3.9, "away": 4.1}},
            ]
        },
        "daxiao": {
            "companies": [
                {"name": "one", "current_line": 2.25, "current_over_water": 0.9, "current_under_water": 0.9}
            ]
        },
        "yazhi": {
            "companies": [
                {"name": "one", "current_handicap": -0.75, "current_water_home": 0.9, "current_water_away": 0.9}
            ]
        },
    }


def test_hk_water_conversion_and_fail_closed_guards() -> None:
    assert audit.water_to_decimal(0.9) == pytest.approx(1.9)
    with pytest.raises(audit.AuditError, match="INVALID_HK_WATER_DOMAIN"):
        audit.water_to_decimal(0)
    with pytest.raises(audit.AuditError, match="INVALID_HK_WATER_DOMAIN"):
        audit.water_to_decimal(-0.1)
    with pytest.raises(audit.AuditError, match="INVALID_HK_WATER_DOMAIN"):
        audit.water_to_decimal(float("nan"))


def test_artifact_float_serialization_is_stable() -> None:
    value = audit._stable_artifact_value({"a": 0.123456789012345, "nested": [1.0 / 3.0]})
    assert value == {"a": 0.123457, "nested": [0.333333]}


def test_proportional_devig_is_fixed_and_normalized() -> None:
    fair = audit.proportional_devig({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert fair["home"] == pytest.approx(0.5)
    assert sum(fair.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("line", [2.0, 2.5, 2.25])
def test_integer_half_and_quarter_ou_settlement_solves_recover_lambda(line: float) -> None:
    expected = 2.4
    matrix, _ = audit.independent_score_matrix(expected, 0.0)
    target = audit.fair_probability_from_matrix(matrix, line, "total", "over")
    solved = audit.solve_total_lambda(line, target)
    assert solved["lambda_total"] == pytest.approx(expected, abs=2e-4)
    assert abs(solved["residual"]) <= 1e-7


def test_ou_line_is_not_used_directly_as_expected_goals() -> None:
    expected = 3.1
    line = 2.5
    matrix, _ = audit.independent_score_matrix(expected, 0.0)
    target = audit.fair_probability_from_matrix(matrix, line, "total", "over")
    solved = audit.solve_total_lambda(line, target)
    assert solved["lambda_total"] == pytest.approx(expected, abs=2e-4)
    assert solved["lambda_total"] != pytest.approx(line, abs=1e-3)


def test_home_away_share_solver_reproduces_synthetic_known_state() -> None:
    target = audit._outcome_probabilities(1.8, 0.9)
    solved = audit.solve_home_share(2.7, target)
    assert solved["lambda_home"] == pytest.approx(1.8, abs=2e-4)
    assert solved["lambda_away"] == pytest.approx(0.9, abs=2e-4)
    assert solved["loss"] <= 1e-10


def test_ah_is_held_out_and_quarter_line_settlement_is_complementary() -> None:
    matrix, _ = audit.independent_score_matrix(1.8, 0.9)
    home = audit.fair_probability_from_matrix(matrix, -0.75, "asian_handicap", "home")
    away = audit.fair_probability_from_matrix(matrix, -0.75, "asian_handicap", "away")
    assert home + away == pytest.approx(1.0, abs=1e-10)
    one_x2 = audit.extract_1x2_quotes(_quote_snapshot())
    ou = audit.extract_ou_quotes(_quote_snapshot())
    ah = audit.extract_ah_quotes(_quote_snapshot())
    assert ah["valid_bookmaker_count"] == 1
    first = audit.build_market_baseline(one_x2, ou)
    altered = deepcopy(_quote_snapshot())
    altered["yazhi"]["companies"][0]["current_water_home"] = 9.0
    altered["yazhi"]["companies"][0]["current_water_away"] = 0.1
    second = audit.build_market_baseline(audit.extract_1x2_quotes(altered), audit.extract_ou_quotes(altered))
    assert first["projection"]["lambda_home"] == pytest.approx(second["projection"]["lambda_home"])
    assert first["projection"]["lambda_away"] == pytest.approx(second["projection"]["lambda_away"])


def test_version_rows_do_not_inflate_unique_match_count() -> None:
    rows = [_record("early", "2026-01-01T09:01:00+08:00"), _record("late", "2026-01-01T10:01:00+08:00")]
    selected = audit.select_unique_legal_versions(rows)
    assert selected["raw_reader_rows"] == 2
    assert selected["eligible_unique_match_count"] == 1
    assert selected["selected_records"][0]["prediction_id"] == "late"


def test_result_or_postmatch_value_cannot_select_prematch_version() -> None:
    early = _record("early", "2026-01-01T09:01:00+08:00")
    late = _record("late", "2026-01-01T10:01:00+08:00")
    postmatch = _record("postmatch", "2026-01-01T11:00:00+08:00", actual_score="9-9")
    selected = audit.select_unique_legal_versions([early, late, postmatch])
    assert selected["selected_records"][0]["prediction_id"] == "late"
    assert selected["postmatch_values_used_for_selection"] is False


def test_later_or_closing_quote_backfill_is_blocked() -> None:
    record = _record("v1", "2026-01-01T09:00:00+08:00")
    snapshot = {"input": {"source_snapshots": {"nowscore": {"snapshots": [_quote_snapshot(fetched_at="2026-01-01T09:01:00+08:00")]}}}}
    result = audit.load_legal_market_snapshot(record, snapshot)
    assert result["reason"] == "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"


def test_missing_raw_quote_fields_have_exhaustive_reasons() -> None:
    one_x2 = audit.extract_1x2_quotes({"daxiao": {"companies": []}})
    ou = audit.extract_ou_quotes({"ouzhi": {"bookmakers": []}})
    ah = audit.extract_ah_quotes({"yazhi": {"companies": []}})
    assert one_x2["reason"] == "NO_FROZEN_1X2_QUOTE_ROWS"
    assert ou["reason"] == "NO_FROZEN_DAXIAO_QUOTE_ROWS"
    assert ah["reason"] == "NO_FROZEN_YAZHI_QUOTE_ROWS"


def _metric(match_key: str) -> dict:
    row = {
        "match_key": match_key,
        "actual_score": "1-0",
        "actual_outcome": "home",
        "champion": {"top1_accuracy": 1, "log_loss": 0.2, "brier": 0.1, "rps": 0.05, "predicted_outcome": "home", "exact_top1": 1, "exact_top3": 1, "exact_top5": 1, "btts_brier": 0.1, "over_2_5_brier": 0.1},
        "market": {"top1_accuracy": 0, "log_loss": 0.8, "brier": 0.5, "rps": 0.3, "predicted_outcome": "draw", "exact_top1": 0, "exact_top3": 1, "exact_top5": 1, "btts_brier": 0.2, "over_2_5_brier": 0.2, "actual_score_nll": 2.0},
        "actual_score_rank": {"champion_persisted_top5": 1, "market_score_matrix": 3, "comparable": True},
    }
    return row


def test_paired_metrics_reject_duplicate_match_rows() -> None:
    with pytest.raises(audit.AuditError, match="DUPLICATE_PAIRED_MATCH_KEY"):
        audit.paired_scorecard([_metric("MATCH-1"), _metric("MATCH-1")], include_bootstrap=False)


def test_actual_score_rank_reports_only_comparable_ranked_surface() -> None:
    row = _metric("MATCH-1")
    scorecard = audit.paired_scorecard([row], include_bootstrap=False)
    rank = scorecard["actual_score_rank"]
    assert rank["comparable_unique_match_n"] == 1
    assert rank["champion_actual_score_rank"]["point"] == pytest.approx(1.0)
    assert rank["market_actual_score_rank"]["point"] == pytest.approx(3.0)
    assert rank["paired_delta_champion_minus_market"]["point"] == pytest.approx(-2.0)


def test_champion_full_distribution_nll_is_blocked_without_replay_parity() -> None:
    record = _record("v1", "2026-01-01T09:00:00+08:00")
    parity = audit.replay_champion_parity([record])
    assert parity["status"] == "CHAMPION_FULL_DISTRIBUTION_NOT_FORMALLY_RECONSTRUCTIBLE"
    assert parity["formal_champion_exact_nll"] is None
    assert parity["formal_champion_topk_probability_calibration"] is None


def test_protected_truth_and_production_paths_cannot_be_audit_outputs() -> None:
    with pytest.raises(ValueError):
        audit._safe_output_dir(ROOT, ROOT / "data" / "model_governance")
    with pytest.raises(ValueError):
        audit._safe_output_dir(ROOT, ROOT / "scripts")
