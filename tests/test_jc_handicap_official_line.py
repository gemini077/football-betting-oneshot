from __future__ import annotations

from copy import deepcopy
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from exact_distribution import (  # noqa: E402
    JC_HANDICAP_SELECTION_ORDER,
    build_exact_distribution_contract,
    build_prediction_time_exact_distribution_state,
    classify_frozen_jc_handicap,
)
from market_contracts import settle_contract  # noqa: E402
from model_governance import (  # noqa: E402
    build_prediction_record,
    freeze_prediction,
    load_frozen_prediction,
    prediction_content_hash,
)
from official_jc_handicap import build_official_jc_handicap_state  # noqa: E402
from prospective_settlement import (  # noqa: E402
    _jc_handicap_summary,
    evaluate_prediction,
)
from risk_engine import dixon_coles_score_matrix  # noqa: E402
from test_model_governance import prediction_payload  # noqa: E402


TARGET = {
    "match_id": "FBOS-test-001",
    "match_num": "T001",
    "business_date": "2026-08-05",
    "home": "Home FC",
    "away": "Away FC",
    "kickoff_local": "2026-08-05T02:00:00+08:00",
}


def official_source(*, source: str = "sporttery.cn", line: int = -1) -> dict:
    return {
        "source": source,
        "url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu",
        "business_date": TARGET["business_date"],
        "fetch_time": "2026-08-04T23:30:00+08:00",
        "success": True,
        "payload_success": True,
        "http_status": 200,
        "response_bytes": 1234,
        "raw_response_sha256": "a" * 64,
        "request_contract": {
            "method": "GET",
            "url": "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?channel=c&poolCode=had,hhad,crs,ttg,hafu",
            "params": {"channel": "c", "poolCode": "had,hhad,crs,ttg,hafu"},
            "required_headers": [
                "Accept",
                "Accept-Encoding",
                "Accept-Language",
                "Origin",
                "Referer",
                "User-Agent",
                "X-Requested-With",
            ],
            "source_surface": "https://m.sporttery.cn/mjc/jsq/zqspf/",
        },
        "matches": [{
            "matchId": TARGET["match_id"],
            "matchNum": TARGET["match_num"],
            "businessDate": TARGET["business_date"],
            "homeTeam": TARGET["home"],
            "awayTeam": TARGET["away"],
            "matchDate": "2026-08-05",
            "matchTime": "02:00:00",
            "rqspf": {"handicap": line, "home": 2.8, "draw": 3.4, "away": 2.2},
        }],
    }


def official_state(*, source: str = "sporttery.cn", line: int = -1) -> dict:
    return build_official_jc_handicap_state(
        official_source(source=source, line=line),
        TARGET,
        source_ref="data/fetch_runs/test/test_sporttery.json",
    )


def frozen_record(*, state: dict | None = None) -> dict:
    matrix = dixon_coles_score_matrix({"lambda_home": 1.2, "lambda_away": 0.9, "rho": 0.0})
    exact_state = build_prediction_time_exact_distribution_state(
        matrix,
        lambda_home=1.2,
        lambda_away=0.9,
        rho=0.0,
    )
    payload = prediction_payload()
    record = build_prediction_record(
        payload,
        commit_sha="jc-handicap-test-sha",
        exact_distribution_state=exact_state,
        official_jc_handicap_state=state if state is not None else official_state(),
        require_exact_distribution=True,
    )
    record["freeze_created_at"] = "2026-08-05T00:01:00+08:00"
    record["prediction_sha256"] = prediction_content_hash(record)
    return record


def verified_result(record: dict, *, home: int = 2, away: int = 0) -> dict:
    return {
        "status": "result_verified",
        "match_key": record["match_key"],
        "score_90m": f"{home}-{away}",
        "home_score": home,
        "away_score": away,
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-06T04:00:00+08:00",
        "source": "fixture_result",
    }


def test_source_authority_requires_exact_sporttery_rqspf_binding():
    state = official_state()
    assert state["status"] == "AVAILABLE"
    assert state["provider"] == "sporttery.cn"
    assert state["market"] == "rqspf"
    assert state["market_identity"] == "JC_HANDICAP_1X2"
    assert state["raw_response_sha256"] == "a" * 64
    assert state["match_binding"]["status"] == "EXACT"
    assert state["handicap_line"] == -1
    assert state["same_time_official_market_baseline"]["status"] == "AVAILABLE"
    assert state["same_time_official_market_baseline"]["derived_from_asian_handicap"] is False

    third_party = official_state(source="500.com")
    assert third_party["status"] == "NOT_AVAILABLE"
    assert third_party["reason"] == "OFFICIAL_SPORTTERY_SOURCE_REQUIRED"

    mismatched = deepcopy(TARGET)
    mismatched["away"] = "Other FC"
    rejected = build_official_jc_handicap_state(official_source(), mismatched)
    assert rejected["status"] == "NOT_AVAILABLE"
    assert rejected["reason"] == "EXACT_OFFICIAL_MATCH_BINDING_REQUIRED"


def test_source_authority_rejects_old_calculator_route_and_missing_raw_hash():
    old_route = deepcopy(official_source())
    old_route["url"] = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=tycp"
    old_route["request_contract"]["url"] = old_route["url"]
    rejected_route = build_official_jc_handicap_state(old_route, TARGET)
    assert rejected_route["status"] == "NOT_AVAILABLE"
    assert rejected_route["reason"] == "OFFICIAL_SPORTTERY_CALCULATOR_URL_REQUIRED"

    lookalike_host = deepcopy(official_source())
    lookalike_host["url"] = lookalike_host["url"].replace(
        "webapi.sporttery.cn", "webapi.sporttery.cn.example.invalid"
    )
    lookalike_host["request_contract"]["url"] = lookalike_host["url"]
    rejected_host = build_official_jc_handicap_state(lookalike_host, TARGET)
    assert rejected_host["status"] == "NOT_AVAILABLE"
    assert rejected_host["reason"] == "OFFICIAL_SPORTTERY_CALCULATOR_URL_REQUIRED"

    missing_hash = deepcopy(official_source())
    missing_hash.pop("raw_response_sha256")
    rejected_hash = build_official_jc_handicap_state(missing_hash, TARGET)
    assert rejected_hash["status"] == "NOT_AVAILABLE"
    assert rejected_hash["reason"] == "OFFICIAL_SOURCE_RAW_HASH_REQUIRED"


def test_binding_uses_official_match_number_when_present_and_fails_closed_on_ambiguity():
    mismatched_number = deepcopy(TARGET)
    mismatched_number["match_num"] = "OTHER"
    rejected = build_official_jc_handicap_state(official_source(), mismatched_number)
    assert rejected["status"] == "NOT_AVAILABLE"
    assert rejected["reason"] == "EXACT_OFFICIAL_MATCH_BINDING_REQUIRED"

    ambiguous = deepcopy(official_source())
    ambiguous["matches"].append(deepcopy(ambiguous["matches"][0]))
    rejected_ambiguous = build_official_jc_handicap_state(ambiguous, TARGET)
    assert rejected_ambiguous["status"] == "NOT_AVAILABLE"
    assert rejected_ambiguous["reason"] == "AMBIGUOUS_OFFICIAL_MATCH_BINDING"


def test_parser_contract_keeps_valid_line_when_one_official_price_is_missing():
    source = deepcopy(official_source())
    source["matches"][0]["rqspf"].pop("away")
    state = build_official_jc_handicap_state(source, TARGET)
    assert state["status"] == "AVAILABLE"
    assert state["handicap_line"] == -1
    assert state["same_time_official_market_baseline"]["status"] == "NOT_AVAILABLE"


def test_projection_is_three_way_and_never_uses_asian_handicap():
    record = frozen_record()
    contract = record["exact_score_distribution"]["jc_handicap"]
    assert contract["status"] == "FORMAL_JC_HANDICAP_FROZEN"
    assert contract["selection_order"] == list(JC_HANDICAP_SELECTION_ORDER)
    assert contract["handicap_line"] == -1
    assert contract["market_identity"] == "JC_HANDICAP_1X2"
    assert contract["forecast_horizon"] == "prematch_to_regulation_90m_plus_stoppage"
    assert contract["line_semantics"]["not_asian_handicap"] is True
    assert sum(contract["probabilities"].values()) == pytest.approx(1.0)
    assert contract["same_time_official_market_baseline"]["status"] == "AVAILABLE"
    assert contract["same_time_official_market_baseline"]["devig_method"] == "PROPORTIONAL_INVERSE_ODDS"
    assert contract["same_time_official_market_baseline"]["line"] == -1
    expected_baseline = {
        key: (1.0 / odds) / sum(1.0 / value for value in (2.8, 3.4, 2.2))
        for key, odds in {"home": 2.8, "draw": 3.4, "away": 2.2}.items()
    }
    assert contract["same_time_official_market_baseline"]["probabilities"] == pytest.approx(
        expected_baseline
    )

    asian_only = deepcopy(official_source())
    asian_only["matches"][0].pop("rqspf")
    asian_only["matches"][0]["yazhi"] = {"handicap": -1}
    unavailable = build_official_jc_handicap_state(asian_only, TARGET)
    assert unavailable["status"] == "NOT_AVAILABLE"
    assert unavailable["reason"] == "OFFICIAL_RQSPF_NOT_AVAILABLE"


def test_line_truth_boundaries_and_90m_settlement_are_frozen():
    record = frozen_record()
    for score, expected in (((2, 0), "home"), ((1, 0), "draw"), ((0, 0), "away"), ((13, 0), "home")):
        classification = classify_frozen_jc_handicap(record, *score)
        assert classification["FORMAL_JC_HANDICAP_FROZEN"] is True
        assert classification["JC_HANDICAP_3WAY_EXACTLY_REPRESENTED"] is True
        assert classification["actual_jc_handicap_selection"] == expected
        assert classification["jc_handicap_line"] == -1
        assert classification["authority_status"] == "FROZEN_PREDICTION_TIME"

    assert settle_contract(
        {"family": "official_jc_handicap", "selection": "draw", "line": -1},
        (1, 0),
    )["units"] == 1.0
    assert settle_contract(
        {"family": "official_jc_handicap", "selection": "away", "line": -1},
        (1, 0),
    )["units"] == -1.0


def test_readback_hash_and_legacy_unavailable_state(tmp_path):
    record = frozen_record()
    expected = deepcopy(record["jc_handicap"])
    freeze_prediction(
        record,
        tmp_path / "predictions",
        input_snapshot_root=tmp_path / "input_snapshots",
    )
    loaded = load_frozen_prediction(record["prediction_id"], tmp_path / "predictions")
    assert loaded["jc_handicap"] == expected
    assert loaded["exact_score_distribution"]["jc_handicap"] == expected
    assert loaded["prediction_output"]["jc_handicap"] == expected

    no_source = frozen_record(state=official_state(source="trade.500.com"))
    assert no_source["jc_handicap"]["status"] == "NOT_AVAILABLE"
    assert classify_frozen_jc_handicap(no_source, 1, 0)["FORMAL_JC_HANDICAP_FROZEN"] is False
    assert classify_frozen_jc_handicap(no_source, 1, 0)["jc_handicap_status"] == "OFFICIAL_JC_HANDICAP_NOT_AVAILABLE"


def test_evaluation_is_independent_frozen_three_way_vector_and_fail_closed():
    record = frozen_record()
    actual = verified_result(record, home=2, away=0)
    metrics = evaluate_prediction(record, actual)
    vector = [record["jc_handicap"]["probabilities"][selection] for selection in JC_HANDICAP_SELECTION_ORDER]
    actual_index = 0
    expected_log_loss = -math.log(vector[actual_index])
    expected_brier = sum((probability - float(index == actual_index)) ** 2 for index, probability in enumerate(vector))
    expected_rps = sum((sum(vector[:index + 1]) - float(actual_index <= index)) ** 2 for index in range(2)) / 2
    assert metrics["jc_handicap_evaluation_eligible"] is True
    assert metrics["jc_handicap_evaluation_status"] == "ELIGIBLE_FROZEN_JC_HANDICAP"
    assert metrics["jc_handicap_log_loss"] == pytest.approx(expected_log_loss)
    assert metrics["jc_handicap_brier"] == pytest.approx(expected_brier)
    assert metrics["jc_handicap_multiclass_brier"] == pytest.approx(expected_brier)
    assert metrics["jc_handicap_rps"] == pytest.approx(expected_rps)
    assert metrics["jc_handicap_rps_denominator"] == 2
    assert metrics["jc_handicap_vector_order"] == list(JC_HANDICAP_SELECTION_ORDER)
    market_vector = [
        record["jc_handicap"]["same_time_official_market_baseline"]["probabilities"][selection]
        for selection in JC_HANDICAP_SELECTION_ORDER
    ]
    expected_market_log_loss = -math.log(market_vector[actual_index])
    expected_market_brier = sum(
        (probability - float(index == actual_index)) ** 2
        for index, probability in enumerate(market_vector)
    )
    expected_market_rps = sum(
        (sum(market_vector[:index + 1]) - float(actual_index <= index)) ** 2
        for index in range(2)
    ) / 2
    assert metrics["jc_handicap_market_evaluation_eligible"] is True
    assert metrics["jc_handicap_market_log_loss"] == pytest.approx(expected_market_log_loss)
    assert metrics["jc_handicap_market_brier"] == pytest.approx(expected_market_brier)
    assert metrics["jc_handicap_market_rps"] == pytest.approx(expected_market_rps)
    assert metrics["jc_handicap_model_minus_market_log_loss"] == pytest.approx(
        metrics["jc_handicap_log_loss"] - expected_market_log_loss
    )
    assert metrics["jc_handicap_paired_evaluation_eligible"] is True

    changed = deepcopy(record)
    changed["probabilities"] = {"home": 0.01, "draw": 0.01, "away": 0.98}
    changed["lambda_home"] = 99.0
    changed["lambda_away"] = 99.0
    replay = evaluate_prediction(changed, actual)
    for key in ("jc_handicap_log_loss", "jc_handicap_brier", "jc_handicap_rps", "actual_jc_handicap_selection"):
        assert replay[key] == metrics[key]

    unverified = evaluate_prediction(record, {"home_score": 2, "away_score": 0})
    assert unverified["jc_handicap_evaluation_eligible"] is False
    assert unverified["jc_handicap_evaluation_status"] == "UNVERIFIED_90M_RESULT"
    assert unverified["jc_handicap_log_loss"] is None
    assert unverified["jc_handicap_market_evaluation_eligible"] is False


def test_prospective_summary_reports_class_mix_recall_and_baseline_status():
    first = evaluate_prediction(frozen_record(), verified_result(frozen_record(), home=2, away=0))
    second_record = frozen_record(state=official_state(line=1))
    second = evaluate_prediction(second_record, verified_result(second_record, home=0, away=0))
    summary = _jc_handicap_summary([
        {"metrics": first},
        {"metrics": second},
        {"metrics": {"jc_handicap_evaluation_eligible": False}},
    ])
    assert summary["status"] == "INSUFFICIENT_SAMPLE"
    assert summary["formal_cohort_n"] == 3
    assert summary["eligible_n"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert summary["metric_conventions"]["order"] == list(JC_HANDICAP_SELECTION_ORDER)
    assert set(summary["actual_class_counts"]) == set(JC_HANDICAP_SELECTION_ORDER)
    assert summary["same_time_official_market_baseline_status_counts"]["AVAILABLE"] == 2
    assert summary["market_baseline_eligible_n"] == 2
    assert summary["paired_eligible_n"] == 2
    assert summary["forecast_horizon_counts"]["prematch_to_regulation_90m_plus_stoppage"] == 2
    assert sum(summary["line_counts"].values()) == 2
