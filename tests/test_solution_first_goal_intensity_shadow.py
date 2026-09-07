import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solution_first_goal_intensity_shadow import (  # noqa: E402
    FEATURE_NAMES,
    MODEL_FAMILY,
    PoissonStumpBooster,
    _score_output,
)


SUMMARY_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "summary.json"
MODEL_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "model.json"
SHADOW_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "latest.json"


def test_unified_score_matrix_derives_all_markets_and_normalizes():
    output = _score_output(1.35, 0.92)
    assert output["rho"] == 0.0
    assert len(output["score_matrix"]) == 169
    assert sum(row["probability"] for row in output["score_matrix"]) == pytest.approx(1.0, abs=2e-10)
    assert len(output["exact_top3"]) == 3
    assert len(output["exact_top5"]) == 5
    assert sum(output["derived_markets"]["1x2"].values()) == pytest.approx(1.0, abs=2e-10)
    assert sum(output["derived_markets"]["btts"].values()) == pytest.approx(1.0, abs=2e-10)
    assert output["derived_markets"]["totals"]["over_2_5"] + output["derived_markets"]["totals"]["under_2_5"] == pytest.approx(1.0, abs=2e-10)
    assert output["score_matrix_normalization"]["finite_grid_raw_mass"] > 0.99


def test_poisson_offset_boosters_are_deterministic_and_separate():
    features = [[float(index % 3), float((index * 2) % 5)] for index in range(60)]
    home = [1.0 + (index % 3) * 0.2 for index in range(60)]
    away = [0.8 + ((index + 1) % 4) * 0.15 for index in range(60)]
    offsets = [0.0] * 60
    weights = [1.0] * 60
    validation = (features[45:], home[45:], offsets[45:])
    first = PoissonStumpBooster(("f0", "f1")).fit(features[:45], home[:45], offsets[:45], weights[:45], validation)
    second = PoissonStumpBooster(("f0", "f1")).fit(features[:45], home[:45], offsets[:45], weights[:45], validation)
    assert first.to_dict() == second.to_dict()
    assert first.predict_lambda(features[50], 0.0) > 0.0
    assert first.to_dict()["feature_names"] == ["f0", "f1"]
    assert home != away


def test_committed_shadow_artifact_is_external_pretrain_only_and_not_serving():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    shadow = json.loads(SHADOW_PATH.read_text(encoding="utf-8"))
    assert summary["decision"] == "SHADOW_CHALLENGER_WIRED"
    assert summary["training_authority"] == "EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER"
    assert summary["fixed_107_outcomes_used_for_fit"] is False
    assert summary["current_serving_changed"] is False
    assert summary["shadow_output_count"] > 0
    assert summary["model_family"] == MODEL_FAMILY
    assert summary["feature_schema"] == "prematch_venue_overall_goal_rates_v1"
    assert summary["feature_names"] == list(FEATURE_NAMES)
    assert summary["integrity"]["production_enabled"] is False
    assert summary["integrity"]["automatic_promotion"] is False
    assert model["model_digest"] == summary["model_digest"]
    assert shadow["production_enabled"] is False
    assert shadow["user_visible"] is False
    assert shadow["row_count"] == summary["shadow_output_count"]
    assert shadow["controls"] == ["market", "champion", "challenger_c"]


def test_shadow_rows_keep_frozen_prematch_contract_and_same_matrix_outputs():
    shadow = json.loads(SHADOW_PATH.read_text(encoding="utf-8"))
    assert shadow["rows"]
    for row in shadow["rows"][:5]:
        assert row["source_cutoff"] < row["kickoff_at"]
        assert row["prediction_id"].startswith("SFGI-")
        assert len(row["prediction_sha256"]) == 64
        assert row["post_match_input_used_for_generation"] is False
        assert row["production_enabled"] is False
        assert row["user_visible"] is False
        assert row["prediction"]["rho"] == 0.0
        assert len(row["prediction"]["score_matrix"]) == 169
        assert row["prediction"]["exact_top1"] == row["prediction"]["exact_top3"][0]
        assert set(row["controls"]) == {"market", "champion", "challenger_c"}
        assert row["settlement_adapter"]["uses_frozen_score_matrix"] is True
