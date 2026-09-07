import json
import math
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from accepted_market_lambda import (  # noqa: E402
    market_lambdas_from_snapshot,
    poisson_pmf,
)
from market_side_shadow import load_persisted_pairs  # noqa: E402
from solution_first_goal_intensity_shadow import (  # noqa: E402
    DEFAULT_PAIR_ROOT,
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    FIXED_107_PAIR_IDS,
    MODEL_BACKEND,
    MODEL_FAMILY,
    XGB_PARAMS,
    XGBoostPoissonModel,
    _authoritative_controls,
    _build_features,
    _exclude_fixed_107_rows,
    _fixed_107_identity_keys,
    _load_authoritative_prediction,
    _load_legal_snapshot,
    _score_output,
)


SUMMARY_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "summary.json"
MODEL_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "model.json"
SHADOW_PATH = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1" / "latest.json"


def _form() -> dict[str, dict[str, float]]:
    return {
        "home_overall": {"matches": 10, "goals_for": 16, "goals_against": 9},
        "home_home": {"matches": 6, "goals_for": 11, "goals_against": 4},
        "away_overall": {"matches": 10, "goals_for": 13, "goals_against": 12},
        "away_away": {"matches": 5, "goals_for": 7, "goals_against": 8},
    }


def test_unified_score_matrix_derives_all_markets_and_normalizes():
    output = _score_output(1.35, 0.92)
    assert output["rho"] == 0.0
    assert len(output["score_matrix"]) == 169
    assert sum(row["probability"] for row in output["score_matrix"]) == pytest.approx(1.0, abs=2e-10)
    assert len(output["exact_top3"]) == 3
    assert len(output["exact_top5"]) == 5
    assert sum(output["derived_markets"]["1x2"].values()) == pytest.approx(1.0, abs=2e-10)
    assert sum(output["derived_markets"]["btts"].values()) == pytest.approx(1.0, abs=2e-10)
    totals = output["derived_markets"]["totals"]
    assert totals["over_2_5"] + totals["under_2_5"] == pytest.approx(1.0, abs=2e-10)
    assert totals["out_of_support_tail"] == output["score_matrix_tail_probability"]
    assert output["score_matrix_normalization"]["finite_grid_raw_mass"] > 0.99


def test_known_poisson_tail_is_omitted_raw_mass_not_represented_mass():
    lambda_home, lambda_away = 4.0, 3.5
    output = _score_output(lambda_home, lambda_away)
    represented_home = sum(poisson_pmf(lambda_home, 12))
    represented_away = sum(poisson_pmf(lambda_away, 12))
    expected_tail = 1.0 - represented_home * represented_away
    assert output["score_matrix_tail_probability"] == pytest.approx(expected_tail, abs=1e-12)
    assert output["score_matrix_normalization"]["finite_grid_raw_mass"] == pytest.approx(1.0 - expected_tail, abs=1e-12)
    assert output["score_matrix_normalization"]["represented_probability_sum"] == pytest.approx(1.0, abs=2e-10)
    assert expected_tail > 0.0


def test_train_and_live_feature_contract_is_symmetric():
    train = _build_features(_form(), source_scope="football_data_all_available_events_v1")
    live = _build_features(_form(), source_scope="nowscore_all_events_v1")
    assert train is not None and live is not None
    assert train["schema"] == live["schema"] == FEATURE_SCHEMA
    assert train["event_scope"] == live["event_scope"] == "ALL_PREMATCH_EVENTS"
    assert train["names"] == live["names"]
    assert train["values"] == pytest.approx(live["values"])
    assert train["fallback_home_venue"] == live["fallback_home_venue"]
    assert train["fallback_away_venue"] == live["fallback_away_venue"]
    assert train["source_scope"] != live["source_scope"]


def test_poisson_offset_xgboost_models_are_deterministic_and_use_base_margin():
    features = [[float(index % 3), float((index * 2) % 5)] for index in range(60)]
    targets = [1.0 + (index % 3) * 0.2 for index in range(60)]
    offsets = [math.log(0.8 + (index % 4) * 0.15) for index in range(60)]
    weights = [1.0] * 60
    validation = (features[45:], targets[45:], offsets[45:])
    first = XGBoostPoissonModel(("f0", "f1")).fit(features[:45], targets[:45], offsets[:45], weights[:45], validation)
    second = XGBoostPoissonModel(("f0", "f1")).fit(features[:45], targets[:45], offsets[:45], weights[:45], validation)
    assert first.to_dict() == second.to_dict()
    assert first.predict_lambda(features[50], offsets[50]) > 0.0
    assert first.to_dict()["feature_names"] == ["f0", "f1"]
    assert first.to_dict()["base_margin_contract"].startswith("log(lambda_market_home/away)")
    assert XGB_PARAMS["objective"] == "count:poisson"


def test_accepted_189_market_lambda_parity_against_frozen_market_baseline():
    pairs = load_persisted_pairs(DEFAULT_PAIR_ROOT)
    pair = next(pair for pair in pairs if pair.get("pair_id") in FIXED_107_PAIR_IDS)
    snapshot, reason = _load_legal_snapshot(pair)
    assert snapshot is not None, reason
    market = market_lambdas_from_snapshot(snapshot)
    document = _load_authoritative_prediction(pair)
    assert document is not None
    persisted = document["market_only_baseline"]
    assert market["contract"] == "accepted_same_time_market_lambda_v1"
    assert market["contract_source"] == "Issue #189 / PR #190"
    for outcome in ("home", "draw", "away"):
        assert market["one_x2_consensus"][outcome] == pytest.approx(persisted[outcome], abs=1e-5)


def test_fixed_107_exclusion_uses_identity_contract():
    fixed_pair_id = next(iter(FIXED_107_PAIR_IDS))
    kept, excluded = _exclude_fixed_107_rows(
        [{"pair_id": fixed_pair_id, "home_goals": 9}, {"pair_id": "not-in-fixed-cohort", "home_goals": 0}],
        set(FIXED_107_PAIR_IDS),
    )
    assert excluded == 1
    assert len(kept) == 1
    assert kept[0]["pair_id"] == "not-in-fixed-cohort"


def test_fixed_107_authority_is_exactly_the_accepted_pair_identity_set():
    identity_keys, authority = _fixed_107_identity_keys(DEFAULT_PAIR_ROOT)
    assert authority["pair_count"] == 107
    assert authority["outcomes_loaded"] is False
    assert authority["pair_id_sha256"] == "2139354111e89fcfb7e7e4e51c85e97b357595a8c42e9fbb05e82e75039acfd6"
    assert len(identity_keys) >= 107


def test_frozen_champion_and_c_controls_keep_pair_identity():
    pairs = load_persisted_pairs(DEFAULT_PAIR_ROOT)
    pair = next(pair for pair in pairs if pair.get("pair_id") in FIXED_107_PAIR_IDS)
    snapshot, reason = _load_legal_snapshot(pair)
    assert snapshot is not None, reason
    market = market_lambdas_from_snapshot(snapshot)
    market_output = _score_output(market["lambda_home"], market["lambda_away"])
    market_output["market_contract"] = market
    controls = _authoritative_controls(pair, _load_authoritative_prediction(pair) or {}, market_output)
    assert controls is not None
    assert controls["market"]["authority"]["kind"] == "FROZEN_INPUT_MARKET_RECONSTRUCTION"
    assert controls["champion"]["authority"]["kind"] == "IMMUTABLE_PAIR_TRUTH"
    assert controls["challenger_c"]["authority"]["kind"] == "IMMUTABLE_PAIR_TRUTH"
    assert controls["champion"]["authority"]["pair_id"] == pair["pair_id"]
    assert controls["challenger_c"]["authority"]["pair_id"] == pair["pair_id"]
    assert controls["champion"]["authority"]["prediction_id"] == pair["champion_prediction_id"]
    assert controls["challenger_c"]["authority"]["prediction_id"] == pair["challenger_prediction_id"]


def test_committed_shadow_artifact_is_external_pretrain_only_and_not_serving():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    shadow = json.loads(SHADOW_PATH.read_text(encoding="utf-8"))
    assert summary["decision"] == "SHADOW_CHALLENGER_WIRED"
    assert summary["training_authority"] == "EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER"
    assert summary["fixed_107_outcomes_used_for_fit"] is False
    assert summary["fixed_107_identity_exclusion"]["status"] == "ENFORCED_BEFORE_TRAINING"
    assert summary["fixed_107_identity_authority"]["pair_count"] == 107
    assert summary["current_serving_changed"] is False
    assert summary["shadow_output_count"] > 0
    assert summary["model_family"] == MODEL_FAMILY
    assert summary["backend"] == MODEL_BACKEND
    assert summary["feature_schema"] == FEATURE_SCHEMA
    assert summary["feature_authority"]["status"] == "SHARED_CONTRACT_VERIFIED"
    assert summary["market_contract_parity"]["status"] == "PASS"
    assert summary["market_contract_parity"]["passed_live_rows"] == summary["market_contract_parity"]["checked_live_rows"] == summary["shadow_output_count"]
    assert summary["feature_names"] == list(FEATURE_NAMES)
    assert summary["integrity"]["production_enabled"] is False
    assert summary["integrity"]["automatic_promotion"] is False
    assert summary["control_authority"]["external"] == "OMITTED_FORMULA_PROXIES"
    assert model["model_digest"] == summary["model_digest"]
    assert model["backend"] == MODEL_BACKEND
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
        assert row["feature_contract"]["training_live_vector_builder"] == "_build_features"
        assert row["feature_contract"]["event_scope"] == "ALL_PREMATCH_EVENTS"
        assert row["prediction"]["rho"] == 0.0
        assert len(row["prediction"]["score_matrix"]) == 169
        assert row["prediction"]["exact_top1"] == row["prediction"]["exact_top3"][0]
        assert set(row["controls"]) == {"market", "champion", "challenger_c"}
        assert row["controls"]["champion"]["authority"]["kind"] == "IMMUTABLE_PAIR_TRUTH"
        assert row["controls"]["challenger_c"]["authority"]["kind"] == "IMMUTABLE_PAIR_TRUTH"
        assert row["controls"]["market"]["authority"]["kind"] == "FROZEN_INPUT_MARKET_RECONSTRUCTION"
        assert row["settlement_adapter"]["uses_frozen_score_matrix"] is True
