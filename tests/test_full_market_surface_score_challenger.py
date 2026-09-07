import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_contracts import settle_contract  # noqa: E402
from market_implied_score_baseline_audit import fair_probability_from_matrix, independent_score_matrix  # noqa: E402
import full_market_surface_score_challenger as challenger  # noqa: E402


def _surface_fixture(lambda_home: float = 1.35, lambda_away: float = 0.95) -> tuple[dict, dict, dict]:
    matrix, _ = independent_score_matrix(lambda_home, lambda_away, max_goals=challenger.MAX_GOALS)
    distributions = challenger._distributions(matrix)

    def fair(distribution, line, selection):
        return challenger._fair_from_distribution(distribution, line, selection)

    one_x2 = {
        "reason": None,
        "valid": [{"bookmaker": "b1", "fair": distributions["1x2"]}],
        "consensus": dict(distributions["1x2"]),
        "raw_row_count": 1,
        "valid_bookmaker_count": 1,
    }
    ou_lines = (1.5, 2.0, 2.25, 2.5, 3.0)
    ah_lines = (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)
    ou_valid = [{"bookmaker": f"ou-{line}", "line": line, "fair_first_probability": fair(distributions["totals"], line, "over")} for line in ou_lines]
    ah_valid = [
        {
            "bookmaker": f"ah-{line}",
            "line": line,
            "fair_first_probability": challenger._fair_from_distribution(
                distributions["differences"], line, "home", family="asian_handicap"
            ),
        }
        for line in ah_lines
    ]
    ou = {"reason": None, "valid": ou_valid, "raw_row_count": len(ou_valid), "valid_bookmaker_count": len(ou_valid)}
    ah = {"reason": None, "valid": ah_valid, "raw_row_count": len(ah_valid), "valid_bookmaker_count": len(ah_valid)}
    return one_x2, ou, ah


def test_quarter_line_settlement_matches_accepted_contract():
    matrix = {(0, 0): 0.2, (1, 0): 0.2, (0, 1): 0.2, (2, 0): 0.2, (0, 2): 0.2}
    distribution = challenger._distributions(matrix)
    for line in (-0.25, 0.25, 0.75, 1.25):
        for selection in ("home", "away"):
            observed = challenger._fair_from_distribution(
                distribution["differences"], line, selection, family="asian_handicap"
            )
            expected = fair_probability_from_matrix(matrix, line, "asian_handicap", selection)
            contract = {"family": "asian_handicap", "selection": selection, "line": line}
            units = settle_contract(contract, (1, 0))["units"]
            assert units in {-1.0, 0.0, 1.0}
            assert observed == pytest.approx(expected, abs=1e-12)


def test_full_surface_solver_is_deterministic_and_rho_zero():
    one_x2, ou, ah = _surface_fixture()
    first = challenger.solve_full_market_surface(one_x2, ou, ah)
    second = challenger.solve_full_market_surface(one_x2, ou, ah)
    assert first == second
    assert first["solver_version"] == challenger.SOLVER_VERSION
    assert first["lambda_home"] > 0.0
    assert first["lambda_away"] > 0.0
    assert first["projection"]["rho"] == 0.0
    assert len(first["projection"]["score_matrix"]) == (challenger.MAX_GOALS + 1) ** 2
    assert sum(row["probability"] for row in first["projection"]["score_matrix"]) == pytest.approx(1.0, abs=2e-10)
    assert first["projection"]["exact_top1"] == first["projection"]["exact_top3"][0]
    assert set(first["family_losses"]) == {"1x2", "ou", "ah"}


def test_duplicate_rows_do_not_change_family_weight():
    one_x2, ou, ah = _surface_fixture()
    duplicated_ou = {**ou, "valid": [*ou["valid"], *ou["valid"]]}
    duplicated_ah = {**ah, "valid": [*ah["valid"], *ah["valid"]]}
    first = challenger.solve_full_market_surface(one_x2, ou, ah)
    ou_duplicate = challenger.solve_full_market_surface(one_x2, duplicated_ou, ah)
    ah_duplicate = challenger.solve_full_market_surface(one_x2, ou, duplicated_ah)
    for candidate in (ou_duplicate, ah_duplicate):
        assert candidate["lambda_home"] == pytest.approx(first["lambda_home"], abs=1e-12)
        assert candidate["lambda_away"] == pytest.approx(first["lambda_away"], abs=1e-12)
        assert candidate["loss"] == pytest.approx(first["loss"], abs=1e-12)


def test_missing_market_family_fails_closed():
    one_x2, ou, ah = _surface_fixture()
    with pytest.raises(challenger.FullMarketSurfaceBlocked):
        challenger.solve_full_market_surface(one_x2, ou, {"reason": "NO_VALID_AH", "valid": []})


def test_legal_snapshot_blocks_later_or_closing_backfill():
    record = {
        "source_cutoff_at": "2026-08-01T10:00:00+00:00",
        "kickoff_at": "2026-08-01T12:00:00+00:00",
    }
    snapshot = {
        "input": {
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [{"fetched_at": "2026-08-01T11:00:00+00:00", "ouzhi": {}, "daxiao": {}, "yazhi": {}}]
                }
            }
        }
    }
    result = challenger.load_legal_market_snapshot(record, snapshot)
    assert result["snapshot"] is None
    assert result["reason"] == "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"


def test_committed_evidence_and_shadow_are_research_only():
    root = ROOT / "data" / "prediction_quality" / "full_market_surface_score_challenger_1"
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    model = json.loads((root / "model.json").read_text(encoding="utf-8"))
    shadow = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    assert summary["decision"] in {"FULL_MARKET_SURFACE_SHADOW_WIRED", "FULL_MARKET_SURFACE_EVALUATED_ONLY", "FAIL_CLOSED"}
    assert summary["model_family"] == challenger.MODEL_FAMILY
    assert summary["model_contract"]["solver_version"] == challenger.SOLVER_VERSION
    assert summary["integrity"]["outcomes_loaded_after_market_freeze"] is True
    assert summary["integrity"]["solver_result_tuned"] is False
    assert summary["integrity"]["family_weights_tuned"] is False
    assert summary["integrity"]["champion_c_serving_ui_changed"] is False
    assert summary["prospective_shadow"]["row_count"] == shadow["row_count"] == len(shadow["rows"])
    assert model["model_digest"] == summary["model_digest"] == shadow["model_digest"]
    assert shadow["production_enabled"] is False
    assert shadow["user_visible"] is False
    for row in shadow["rows"][:3]:
        assert row["source_identity"]["source_cutoff_at"] < row["source_identity"]["kickoff_at"]
        assert row["solver"]["version"] == challenger.SOLVER_VERSION
        assert row["prediction"]["rho"] == 0.0
        assert len(row["prediction"]["score_matrix"]) == (challenger.MAX_GOALS + 1) ** 2
        assert row["prediction"]["exact_top1"] == row["prediction"]["exact_top3"][0]
        assert row["production_enabled"] is False
        assert row["user_visible"] is False


def test_historical_pair_is_unique_and_controls_are_explicit():
    summary = json.loads((ROOT / "data" / "prediction_quality" / "full_market_surface_score_challenger_1" / "summary.json").read_text(encoding="utf-8"))
    paired = summary["historical_evaluation"]["paired"]
    assert paired["paired_unique_match_n"] >= 50
    assert summary["historical_evaluation"]["controls"]["champion"]["status"] in {"EVALUABLE", "NOT_AVAILABLE"}
    assert summary["historical_evaluation"]["controls"]["challenger_c"]["status"] == "NOT_AVAILABLE_ON_ORIGIN_MAIN"
    rows = summary["historical_metric_rows"]["full_market_surface"]
    assert len({row["match_key"] for row in rows}) == len(rows)
