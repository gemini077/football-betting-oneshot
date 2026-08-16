from __future__ import annotations

from math import isclose, log
import sys

import pytest

import scripts.strength_challenger as strength_challenger
from scripts.strength_challenger import (
    ChallengerSpec,
    assert_evaluation_ids_not_in_history,
    blend_one_x_two,
    build_identity_bridge_index,
    build_opponent_adjusted_shadow,
    chronological_split,
    dataset_gate,
    paired_subset,
    market_only_from_record,
    prediction_record_target,
    reliability_bucket,
    resolve_fixture_identity,
    summarise_prediction_rows,
    strong_favourite_diagnostics,
    uniform_one_x_two,
    validation_row_counts,
)
from scripts.football_data.storage import DatasetNotAvailableError
from tests.phase2c2_test_support import paired_history, result, target


def test_dataset_gate_requires_result_identity_and_scores():
    report = dataset_gate(paired_history(count=2))
    assert report["eligible_count"] == 4
    assert report["excluded_count"] == 0

    bad = dict(paired_history(count=1)[0])
    bad["home_goals"] = None
    rejected = dataset_gate([bad])
    assert rejected["eligible_count"] == 0
    assert rejected["excluded_by_reason"]["missing_required_result"] == 1


def test_chronological_split_has_strict_non_overlapping_ranges():
    rows = [result(f"m-{i}", f"2025-01-{i + 1:02d}T12:00:00Z", "h", "a") for i in range(10)]
    split = chronological_split(rows, train_fraction=0.6, validation_fraction=0.2)
    assert [row["canonical_match_id"] for row in split["train"]] == [f"m-{i}" for i in range(6)]
    assert [row["canonical_match_id"] for row in split["validation"]] == ["m-6", "m-7"]
    assert [row["canonical_match_id"] for row in split["holdout"]] == ["m-8", "m-9"]
    assert split["train"][-1]["kickoff_at"] < split["validation"][0]["kickoff_at"]
    assert split["validation"][-1]["kickoff_at"] < split["holdout"][0]["kickoff_at"]


def test_opponent_adjusted_shadow_is_positive_coherent_and_excludes_future_rows():
    history = paired_history(count=8)
    future = result("future", "2026-04-01T12:00:00Z", "team:home", "team:late", 7, 0)
    prediction = build_opponent_adjusted_shadow(
        target(),
        history + [future],
        ChallengerSpec(regularization=10, minimum_history=3),
    )
    assert prediction["status"] == "AVAILABLE"
    assert prediction["lambda_home"] > 0
    assert prediction["lambda_away"] > 0
    assert isclose(sum(prediction["probabilities"]["1x2"].values()), 1.0, abs_tol=1e-12)
    assert "future" not in prediction["features"]["used_match_ids"]
    assert "target" not in prediction["features"]["used_match_ids"]


def test_competition_fallback_is_explicit_not_a_silent_second_schedule():
    history = paired_history(count=6)
    target_in_other_competition = dict(target())
    target_in_other_competition["competition_id"] = "competition:other"
    prediction = build_opponent_adjusted_shadow(
        target_in_other_competition,
        history,
        ChallengerSpec(regularization=10, minimum_history=3, competition_minimum_rows=100),
    )
    assert prediction["status"] == "AVAILABLE"
    assert prediction["features"]["history_scope"] == "global_fallback"


def test_market_only_and_fusion_are_separate_from_football_output():
    record = {"market_only_baseline": {"home": 0.6, "draw": 0.2, "away": 0.2}}
    market = market_only_from_record(record)
    assert market == {"home": 0.6, "draw": 0.2, "away": 0.2}
    football = {"home": 0.3, "draw": 0.3, "away": 0.4}
    fusion = blend_one_x_two(football, market, weight=0.5)
    assert fusion == {"home": 0.45, "draw": 0.25, "away": 0.3}
    assert fusion != football
    assert fusion != market


def test_uniform_baseline_is_exactly_one_third():
    assert uniform_one_x_two() == {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


def test_prediction_record_without_canonical_identity_is_not_fuzzy_resolved():
    target_info = prediction_record_target(
        {
            "match_id": "500-1",
            "match_identity": {"home": "Known-looking name", "away": "Other", "kickoff_at": "2026-08-15T12:00:00Z"},
        }
    )
    assert target_info["status"] == "IDENTITY_UNAVAILABLE"
    assert target_info["target"] is None


def test_formal_evaluation_ids_are_excluded_from_training_history():
    history = [result("h-1", "2025-01-01T12:00:00Z", "h", "a")]
    assert_evaluation_ids_not_in_history(history, {"formal-1"})
    with pytest.raises(ValueError, match="evaluation IDs must not be in training history"):
        assert_evaluation_ids_not_in_history(history + [result("formal-1", "2025-01-02T12:00:00Z", "h", "a")], {"formal-1"})


def test_metric_summary_reports_probability_goal_and_score_metrics():
    rows = [
        {
            "status": "AVAILABLE",
            "actual_score": "1-0",
            "actual_outcome": "home",
            "prediction": {
                "lambda_home": 1.2,
                "lambda_away": 0.8,
                "probabilities": {"1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}},
                "top_scores": [{"score": "1-0", "probability": 0.2}],
            },
        }
    ]
    metrics = summarise_prediction_rows(rows)
    assert metrics["sample"] == 1
    assert metrics["one_x_two_brier"] is not None
    assert metrics["one_x_two_log_loss"] is not None
    assert metrics["home_goals_mae"] == 0.2
    assert metrics["away_goals_mae"] == 0.8
    assert metrics["exact_top1_accuracy"] == 1.0


def test_score_nll_is_unavailable_without_explicit_actual_probability():
    metrics = summarise_prediction_rows([
        {
            "status": "AVAILABLE",
            "actual_score": "2-2",
            "prediction": {
                "probabilities": {"1x2": {"home": 0.4, "draw": 0.3, "away": 0.3}},
                "top_scores": [{"score": "1-0", "probability": 0.2}],
            },
        }
    ])
    assert metrics["score_nll_available_count"] == 0
    assert metrics["score_nll_unavailable_count"] == 1
    assert metrics["mean_score_nll_available_only"] is None


def test_score_nll_uses_explicit_frozen_probability_without_epsilon_fabrication():
    metrics = summarise_prediction_rows([
        {
            "status": "AVAILABLE",
            "actual_score": "2-2",
            "prediction": {
                "probabilities": {"1x2": {"home": 0.4, "draw": 0.3, "away": 0.3}},
                "actual_score_probability": 0.25,
                "top_scores": [],
            },
        }
    ])
    assert metrics["score_nll_available_count"] == 1
    assert isclose(metrics["mean_score_nll_available_only"], -log(0.25), rel_tol=0, abs_tol=1e-12)


def test_valid_stored_nll_is_used_but_unavailable_status_is_not():
    available = summarise_prediction_rows([{"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.6, "draw": 0.2, "away": 0.2}}, "actual_score_nll": 2.5}}])
    unavailable = summarise_prediction_rows([{"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.6, "draw": 0.2, "away": 0.2}}, "actual_score_nll": 2.5, "actual_score_nll_status": "UNAVAILABLE_IN_FROZEN_RECORD"}}])
    assert available["mean_score_nll_available_only"] == 2.5
    assert unavailable["mean_score_nll_available_only"] is None


def test_stored_nll_mismatch_with_frozen_probability_is_reported_not_silently_selected():
    metrics = summarise_prediction_rows([
        {
            "status": "AVAILABLE",
            "match_id": "mismatch-1",
            "actual_score": "1-0",
            "prediction": {
                "probabilities": {"1x2": {"home": 0.6, "draw": 0.2, "away": 0.2}},
                "actual_score_probability": 0.25,
                "actual_score_nll": 1.0,
            },
        }
    ])
    assert metrics["score_nll_available_count"] == 0
    assert metrics["score_nll_unavailable_reasons"] == {"NLL_RECONSTRUCTION_MISMATCH": 1}
    assert metrics["nll_reconstruction_mismatch_count"] == 1


def _identity_fixture(*, home="Alpha", away="Beta", competition="Test League"):
    return {
        "match_id": "production-match-1",
        "competition": competition,
        "home": home,
        "away": away,
        "kickoff": "2026-03-01T12:00:00Z",
    }


def _identity_sources():
    return {
        "team_alias_registry": {
            "teams": [
                {
                    "canonical_team_id": "team:alpha",
                    "canonical_name": "Alpha",
                    "aliases": ["Alpha"],
                    "competition_context": ["competition:test"],
                },
                {
                    "canonical_team_id": "team:beta",
                    "canonical_name": "Beta",
                    "aliases": ["Beta"],
                    "competition_context": ["competition:test"],
                },
            ]
        },
        "competition_registry": {
            "competitions": [
                {
                    "competition_key": "test",
                    "canonical_competition_id": "competition:test",
                    "name": "Test League",
                    "observed_raw_names": ["Test League"],
                    "result_coverage": "SUPPORTED",
                }
            ]
        },
    }


def _identity_history(count=5):
    rows = []
    for index in range(count):
        rows.append(result(f"alpha-{index}", f"2026-01-{index + 1:02d}T12:00:00Z", "team:alpha", f"team:opp-a-{index}", competition="competition:test"))
        rows.append(result(f"beta-{index}", f"2026-01-{index + 1:02d}T13:00:00Z", f"team:opp-b-{index}", "team:beta", competition="competition:test"))
    return rows


def test_identity_bridge_accepts_exact_registry_alias_only_when_history_is_eligible():
    index = build_identity_bridge_index(_identity_history(), **_identity_sources())
    mapped = resolve_fixture_identity(_identity_fixture(), index=index)
    assert mapped["final_status"] == "MAPPED"
    assert mapped["home_mapping"]["method"] == "registry_exact_alias"
    assert mapped["historical_coverage"]["eligible"] is True


def test_identity_bridge_accepts_provider_id_exact_and_rejects_fuzzy_names():
    sources = _identity_sources()
    sources["project_crosswalk"] = {
        "mappings": [
            {
                "canonical_team_id": "team:alpha",
                "canonical_name": "Alpha",
                "competition": "competition:test",
                "provider": "nowscore",
                "provider_team_id": "101",
                "provider_team_name": "Alpha provider",
                "verified": True,
            },
            {
                "canonical_team_id": "team:beta",
                "canonical_name": "Beta",
                "competition": "competition:test",
                "provider": "nowscore",
                "provider_team_id": "202",
                "provider_team_name": "Beta provider",
                "verified": True,
            },
        ]
    }
    index = build_identity_bridge_index(_identity_history(), **sources)
    provider_fixture = _identity_fixture(home="Unknown Alpha", away="Unknown Beta")
    provider_fixture["production_identity_signals"] = {
        "provider": "nowscore",
        "home_provider_team_id": "101",
        "away_provider_team_id": "202",
    }
    assert resolve_fixture_identity(provider_fixture, index=index)["final_status"] == "MAPPED"
    fuzzy = resolve_fixture_identity(_identity_fixture(home="Alph"), index=index)
    assert fuzzy["final_status"] == "IDENTITY_UNAVAILABLE"


def test_identity_bridge_rejects_ambiguous_alias_and_separates_history_or_competition_gaps():
    sources = _identity_sources()
    sources["team_alias_registry"]["teams"].append(
        {
            "canonical_team_id": "team:alpha-2",
            "canonical_name": "Alpha Two",
            "aliases": ["Alpha"],
            "competition_context": ["competition:test"],
        }
    )
    index = build_identity_bridge_index(_identity_history(), **sources)
    ambiguous = resolve_fixture_identity(_identity_fixture(), index=index)
    assert ambiguous["final_status"] == "AMBIGUOUS_IDENTITY"

    short_index = build_identity_bridge_index(_identity_history(1), **_identity_sources())
    short = resolve_fixture_identity(_identity_fixture(), index=short_index)
    assert short["final_status"] == "HISTORY_UNAVAILABLE"

    unsupported = resolve_fixture_identity(
        _identity_fixture(competition="Unsupported League"),
        index=index,
    )
    assert unsupported["final_status"] == "COMPETITION_UNSUPPORTED"


def test_paired_subset_uses_identical_match_ids_for_all_methods():
    formal = [
        {"prediction_id": "p-1", "actual_score": "1-0"},
        {"prediction_id": "p-2", "actual_score": "0-0"},
    ]
    challenger = [
        {"prediction_id": "p-1", "status": "AVAILABLE"},
        {"prediction_id": "p-2", "status": "INSUFFICIENT_HISTORY"},
    ]
    paired = paired_subset(formal, challenger)
    assert paired == ["p-1"]


def test_reliability_bins_are_non_overlapping_and_favourite_thresholds_are_cumulative():
    assert reliability_bucket(0.57) == "0.55-<0.60"
    assert reliability_bucket(0.62) == "0.60-<0.65"
    rows = [
        {"actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.56, "draw": 0.22, "away": 0.22}}}},
        {"actual_score": "0-1", "prediction": {"probabilities": {"1x2": {"home": 0.66, "draw": 0.20, "away": 0.14}}}},
    ]
    diag = strong_favourite_diagnostics(rows)
    assert diag[">=0.55"]["count"] == 2
    assert diag[">=0.60"]["count"] == 1
    assert diag[">=0.65"]["count"] == 1


def test_validation_counts_reconcile_total_available_metric_and_insufficient_rows():
    counts = validation_row_counts([
        {"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}}}},
        {"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {}}},
        {"status": "INSUFFICIENT_HISTORY", "actual_score": None, "prediction": {}},
    ])
    assert counts["validation_total"] == 3
    assert counts["available"] == 2
    assert counts["metric_eligible"] == 1
    assert counts["insufficient"] == 1


def test_cli_fails_fast_with_diagnostic_when_historical_dataset_is_missing(monkeypatch, tmp_path, capsys):
    missing_path = tmp_path / "historical_results.duckdb"

    def fail_fast(**_kwargs):
        raise DatasetNotAvailableError(missing_path)

    monkeypatch.setattr(strength_challenger, "run_research", fail_fast)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "strength_challenger",
            "--business-date",
            "2026-08-16",
            "--output-dir",
            str(tmp_path / "evidence"),
        ],
    )

    assert strength_challenger._cli() == 2
    captured = capsys.readouterr()
    assert "DATASET_NOT_AVAILABLE" in captured.err
    assert str(missing_path) in captured.err
