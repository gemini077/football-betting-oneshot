import json
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from exact_distribution import build_exact_distribution_contract, build_prediction_time_exact_distribution_state
from official_jc_handicap import (
    JC_HANDICAP_SELECTION_ORDER,
    build_jc_handicap_contract,
    capture_nowscore_jc_handicap,
    classify_frozen_jc_handicap,
    evaluate_frozen_jc_handicap,
    parse_nowscore_analysis_page,
    project_jc_handicap_probabilities,
    settle_frozen_jc_handicap,
    summarize_jc_handicap_evaluations,
    validate_jc_handicap_contract,
)
import official_jc_handicap_live_audit as live_audit
from model_governance import build_prediction_record
from test_model_governance import prediction_payload


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=TZ)


def fixture() -> dict:
    return {
        "businessDate": "2026-09-07",
        "matchNum": "周一001",
        "matchDate": "2026-09-07",
        "matchTime": "18:00",
        "homeTeam": "Home FC",
        "awayTeam": "Away FC",
        "nowscoreId": 3000001,
        "nowscore_id": 3000001,
        "nowscoreMatchStatus": "EXACT_MATCH",
        "nowscoreMatchConfidence": 1.0,
        "jc_membership": "VERIFIED",
        "jc_membership_source": "nowscore_public_jc_sales",
        "source_surface": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-07",
        "source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-07",
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-07",
        "match_number_source": "nowscore_public_jc_sales",
        "sales_row_id": "5516001",
        "fetched_at": "2026-09-06T02:39:58+08:00",
        "jc_membership_evidence": {
            "source": "nowscore_public_jc_sales",
            "selected_date": "2026-09-07",
            "business_date": "2026-09-07",
            "sales_window": "11:00--次日11:00",
            "match_number": "周一001",
            "sales_row_id": "5516001",
            "nowscore_id": 3000001,
            "source_surface": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-07",
        },
        "date_provenance": {
            "business_date": "2026-09-07",
            "expected_business_date": "2026-09-07",
            "business_date_source": "nowscore_public_jc_sales",
            "sales_window": "11:00--次日11:00",
            "sales_row_id": "5516001",
            "match_number": "周一001",
            "business_date_source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-07",
        },
    }


def page(line: str = "1", *, nowscore_id: int = 3000001, home: str = "Home FC", away: str = "Away FC") -> str:
    return f'''<html><script>
        var scheduleId = {nowscore_id};
        var homeTeam = "{home}";
        var guestTeam = "{away}";
        var MatchTimeStamp = 1788775200000;
    </script><div class="fenxiBar">竞彩指数</div>
    <div><table><tr onclick="GoJcUrl(1)"><td>0</td><td>1.5</td></tr>
    <tr onclick="GoJcUrl(0)"><td>{line}</td><td>1.8</td><td>3.5</td><td>4.5</td></tr></table></div></html>'''


def captured(line: int = 1) -> dict:
    response = {"http_status": 200, "body": page(str(line)).encode("utf-8")}
    return capture_nowscore_jc_handicap(
        fixture(),
        now=NOW,
        fetcher=lambda *_args, **_kwargs: response,
    )


def exact_contract() -> dict:
    cells = {(home, away): 1 / 169 for home in range(13) for away in range(13)}
    state = build_prediction_time_exact_distribution_state(
        cells,
        lambda_home=1.2,
        lambda_away=0.9,
        rho=0.0,
    )
    return build_exact_distribution_contract(
        state,
        model_identity={
            "prediction_id": "JC-211-001",
            "model_family": "recent_form_market_calibrated_poisson_v2",
        },
    )


def test_parser_accepts_only_explicit_jc_row_and_rejects_generic_asian_row():
    parsed = parse_nowscore_analysis_page(page("+1"), expected_nowscore_id=3000001)
    assert parsed["identity_status"] == "EXACT_ID"
    assert parsed["official_row_count"] == 1
    assert parsed["official_rows"][0]["line"] == 1

    asian_only = page("+1").replace('GoJcUrl(0)', 'onclick="showAsian(0)"')
    asian_only = asian_only.replace('onclick="onclick="showAsian(0)""', 'onclick="showAsian(0)"')
    parsed_asian = parse_nowscore_analysis_page(asian_only, expected_nowscore_id=3000001)
    assert parsed_asian["official_row_count"] == 0


@pytest.mark.parametrize("line", [1, -1, 0, 3])
def test_integer_line_capture_and_projection_boundaries(line):
    source = captured(line)
    assert source["status"] == "CAPTURED"
    assert source["line"] == line
    exact = exact_contract()
    projected = project_jc_handicap_probabilities(exact, line)
    assert list(projected) == list(JC_HANDICAP_SELECTION_ORDER)
    assert sum(projected.values()) == pytest.approx(1.0)


def test_non_integer_multiple_identity_and_non200_fail_closed():
    non_integer = capture_nowscore_jc_handicap(
        fixture(), now=NOW, fetcher=lambda *_args, **_kwargs: {"http_status": 200, "body": page("1.5").encode()}
    )
    assert non_integer["status"] == "ABSTAIN"
    assert non_integer["reason"] == "NON_INTEGER_LINE"

    duplicate = page("1").replace('</table>', '<tr onclick="GoJcUrl(0)"><td>2</td></tr></table>')
    duplicate_result = capture_nowscore_jc_handicap(
        fixture(), now=NOW, fetcher=lambda *_args, **_kwargs: {"http_status": 200, "body": duplicate.encode()}
    )
    assert duplicate_result["reason"] == "MULTIPLE_JC_HANDICAP_ROWS"

    conflict = capture_nowscore_jc_handicap(
        fixture(), now=NOW, fetcher=lambda *_args, **_kwargs: {"http_status": 200, "body": page("1", home="Other FC").encode()}
    )
    assert conflict["reason"] == "IDENTITY_CONFLICT"

    unavailable = capture_nowscore_jc_handicap(
        fixture(), now=NOW, fetcher=lambda *_args, **_kwargs: {"http_status": 567, "body": b"blocked"}
    )
    assert unavailable["reason"] == "SOURCE_HTTP_NOT_200"
    assert unavailable["page_http_status"] == 567


def test_retry_budget_is_small_and_bounded():
    calls = []

    def fetcher(*_args, **_kwargs):
        calls.append(1)
        return {"http_status": 503, "body": b"temporarily unavailable"}

    result = capture_nowscore_jc_handicap(
        fixture(),
        now=NOW,
        max_retries=99,
        backoff_seconds=0,
        fetcher=fetcher,
    )

    assert result["status"] == "ABSTAIN"
    assert result["reason"] == "SOURCE_HTTP_NOT_200"
    assert result["retry_count"] == 2
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("line", "score", "expected"),
    [
        (1, (0, 0), "home"),
        (-1, (1, 0), "draw"),
        (0, (0, 0), "draw"),
        (-1, (0, 0), "away"),
    ],
)
def test_verified_90m_settlement_covers_positive_negative_zero_and_draw_boundaries(line, score, expected):
    contract = build_jc_handicap_contract(exact_contract(), captured(line))
    settled = settle_frozen_jc_handicap(contract, score)
    assert settled["status"] == "SETTLED"
    assert settled["actual_selection"] == expected
    assert settled["scope"] == "regulation_90m_plus_stoppage"


def test_freeze_classify_settle_and_evaluate_use_frozen_exact_authority_only():
    source = captured(1)
    contract = build_jc_handicap_contract(
        exact_contract(),
        source,
        forecast_horizon={
            "prediction_created_at": "2026-09-06T12:00:00+08:00",
            "kickoff_at": "2026-09-07T18:00:00+08:00",
        },
    )
    validate_jc_handicap_contract(contract)
    record = {
        "prediction_id": "JC-211-001",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "exact_score_distribution": exact_contract(),
        "jc_handicap": contract,
        "prediction_status": "formal",
    }
    classified = classify_frozen_jc_handicap(record, 0, 1)
    assert classified["FORMAL_JC_HANDICAP_FROZEN"] is True
    assert classified["actual_jc_handicap_class"] == "draw"
    assert classified["official_jc_handicap_line"] == 1
    settlement = settle_frozen_jc_handicap(record, (0, 1))
    assert settlement["actual_selection"] == "draw"
    assert settlement["units"] == 1.0
    metrics = evaluate_frozen_jc_handicap(record, (0, 1), verified_result=True)
    assert metrics["jc_handicap_evaluation_eligible"] is True
    assert metrics["jc_handicap_vector_order"] == ["home", "draw", "away"]
    assert metrics["jc_handicap_log_loss"] is not None


def test_abstain_authority_is_explicit_and_summary_is_prospective():
    abstain_source = capture_nowscore_jc_handicap(
        fixture(), now=NOW, fetcher=lambda *_args, **_kwargs: {"http_status": 403, "body": b"blocked"}
    )
    contract = build_jc_handicap_contract(exact_contract(), abstain_source)
    validate_jc_handicap_contract(contract)
    assert contract["served_state"] == "ABSTAIN"
    assert contract["same_time_official_market_baseline"]["status"] == "NOT_AVAILABLE"
    row = {
        "prediction_created_at": "2026-09-06T12:00:00+08:00",
        "kickoff_at": "2026-09-07T18:00:00+08:00",
        "metrics": {
            **evaluate_frozen_jc_handicap(
                {"jc_handicap": contract, "exact_score_distribution": exact_contract()},
                (1, 0),
                verified_result=True,
            )
        },
    }
    summary = summarize_jc_handicap_evaluations([row])
    assert summary["formal_cohort_n"] == 1
    assert summary["eligible_n"] == 0
    assert summary["coverage_status"] == "NO_ELIGIBLE_FROZEN_JC_SAMPLES"


def test_old_record_without_frozen_jc_handicap_is_not_reconstructed_or_backfilled():
    classified = classify_frozen_jc_handicap(
        {
            "prediction_id": "JC-211-001",
            "exact_score_distribution": exact_contract(),
        },
        1,
        0,
    )
    assert classified["FORMAL_JC_HANDICAP_FROZEN"] is False
    assert classified["jc_handicap_status"] == "MISSING_FROZEN_JC_HANDICAP"
    assert evaluate_frozen_jc_handicap(
        {"exact_score_distribution": exact_contract()},
        (1, 0),
        verified_result=True,
    )["jc_handicap_evaluation_eligible"] is False


def test_governance_freezes_the_lane_without_changing_champion_probability_state():
    payload = prediction_payload()
    payload["match"].update({
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_local": "2026-09-07T18:00:00+08:00",
    })
    payload["business_date"] = "2026-09-07"
    payload["official_jc_handicap_capture"] = captured(1)
    state = {
        "effective_matrix": [
            {"home_goals": home, "away_goals": away, "probability": 1 / 169}
            for home in range(13)
            for away in range(13)
        ],
        "probability_state": {"lambda_home": 1.2, "lambda_away": 0.9, "rho": 0.0},
        "production_path": {"effective_stage": "test"},
    }
    before = dict(payload["model"]["probabilities"])
    record = build_prediction_record(
        payload,
        commit_sha="jc-211-test-sha",
        exact_distribution_state=state,
        require_exact_distribution=True,
    )
    assert record["jc_handicap"]["served_state"] == "FORMAL"
    assert record["jc_handicap"]["official_integer_line"] == 1
    assert record["prediction_output"]["jc_handicap"] == record["jc_handicap"]
    assert record["probabilities"] == before


def test_live_audit_resolves_newest_nowscore_universe_and_reports_line_coverage(tmp_path, monkeypatch):
    universe_root = tmp_path / "prediction_universe"
    universe_root.mkdir()
    current = {
        "business_date": "2026-09-07",
        "status": "READY",
        "source": "nowscore_public_jc",
        "fixtures": [fixture()],
    }
    later_not_published = {
        "business_date": "2026-09-08",
        "status": "NOT_YET_PUBLISHED",
        "source": "nowscore_public_jc",
        "fixtures": [],
    }
    (universe_root / "2026-09-07.json").write_text(json.dumps(current), encoding="utf-8")
    (universe_root / "2026-09-08.json").write_text(json.dumps(later_not_published), encoding="utf-8")
    monkeypatch.setattr(live_audit, "capture_nowscore_jc_handicap", lambda *_args, **_kwargs: captured(1))

    result = live_audit.run_audit(universe_root=universe_root, limit=20)

    assert live_audit.resolve_current_business_date(universe_root) == "2026-09-07"
    assert result["current_business_date"] == "2026-09-07"
    assert result["binding_funnel"] == {
        "jc_fixture_n": 1,
        "attempted_n": 1,
        "exact_n": 1,
        "ambiguous_n": 0,
        "unmatched_n": 0,
        "duplicate_n": 0,
        "conflict_n": 0,
    }
    assert result["page_http_status_counts"] == {"200": 1}
    assert result["line_coverage"]["available_n"] == 1
    assert result["odds_coverage"]["baseline_status"] == "NOT_AVAILABLE"
    assert result["delivery_decision"] == "JC_HANDICAP_NOWSCORE_FORMAL_TRUTH_READY"
