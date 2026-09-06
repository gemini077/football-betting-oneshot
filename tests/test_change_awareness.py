import copy
import json
import sys
from datetime import timedelta, timezone

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from change_awareness import (  # noqa: E402
    CHANGE_AWARENESS_STATUS_AVAILABLE,
    build_prematch_change_awareness,
)
from build_public_site import _change_awareness_for_fixture  # noqa: E402
from exact_distribution import (  # noqa: E402
    build_exact_distribution_contract,
    build_prediction_time_exact_distribution_state,
)
from official_jc_handicap import build_jc_handicap_contract  # noqa: E402
from test_official_jc_handicap import captured  # noqa: E402
from match_detail import render_match_detail  # noqa: E402


TZ = timezone(timedelta(hours=8))
KICKOFF = "2026-09-09T00:00:00+08:00"


def _exact_contract(prediction_id: str, *, lambda_home: float = 1.2, lambda_away: float = 0.9) -> dict:
    cells = {(home, away): 1 / 169 for home in range(13) for away in range(13)}
    weights = {
        score: 1.0 + (lambda_home * score[0]) + (lambda_away * score[1])
        for score in cells
    }
    total = sum(weights.values())
    cells = {score: weight / total for score, weight in weights.items()}
    state = build_prediction_time_exact_distribution_state(
        cells,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        rho=0.0,
    )
    return build_exact_distribution_contract(
        state,
        model_identity={
            "prediction_id": prediction_id,
            "model_role": "champion",
            "model_family": "recent_form_market_calibrated_poisson_v2",
            "release_version": "v0.19.0",
            "model_source_fingerprint": "model-fingerprint",
            "input_sha256": "input-hash",
        },
    )


def _record(
    prediction_id: str,
    freeze_created_at: str,
    *,
    match_id: str = "M1",
    match_key: str = "CANONICAL-M1",
    lambda_home: float = 1.2,
    lambda_away: float = 0.9,
    line: int = 1,
    probabilities: dict[str, float] | None = None,
) -> dict:
    exact = _exact_contract(prediction_id, lambda_home=lambda_home, lambda_away=lambda_away)
    handicap = build_jc_handicap_contract(
        exact,
        captured(line),
        model_identity={
            "prediction_id": prediction_id,
            "model_family": "recent_form_market_calibrated_poisson_v2",
        },
    )
    return {
        "prediction_id": prediction_id,
        "prediction_status": "formal",
        "model_role": "champion",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "model_source_fingerprint": "model-fingerprint",
        "input_sha256": "input-hash",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "prediction_variant": "model_only",
        "manual_override": None,
        "match_id": match_id,
        "match_key": match_key,
        "match_identity": {
            "match_id": match_id,
            "match_key": match_key,
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": KICKOFF,
        },
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_at": KICKOFF,
        "source_cutoff_at": "2026-09-08T08:00:00+08:00",
        "prediction_created_at": "2026-09-08T08:01:00+08:00",
        "freeze_created_at": freeze_created_at,
        "probabilities": probabilities or {"home": 0.50, "draw": 0.25, "away": 0.25},
        "exact_score_distribution": exact,
        "jc_total_goals": exact["jc_total_goals"],
        "jc_handicap": handicap,
    }


def _identity(record: dict) -> dict:
    return {
        "match_id": record["match_id"],
        "match_key": record["match_key"],
        "home": record["home"],
        "away": record["away"],
        "kickoff_at": record["kickoff_at"],
    }


def _pair(*, current: dict | None = None, previous: dict | None = None) -> tuple[dict, list[dict], dict]:
    selected = current or _record("CURRENT", "2026-09-08T12:00:00+08:00")
    earlier = previous or _record("PREVIOUS", "2026-09-08T10:00:00+08:00")
    records = [selected, earlier]
    return selected, records, _identity(selected)


def _set_chronology(record: dict, *, source: str, prediction: str, freeze: str) -> dict:
    record.update(
        {
            "source_cutoff_at": source,
            "prediction_created_at": prediction,
            "freeze_created_at": freeze,
        }
    )
    return record


def test_selects_nearest_earlier_legal_snapshot_deterministically_and_ignores_later_or_other_matches():
    current = _record("CURRENT", "2026-09-08T12:00:00+08:00")
    nearest = _record("NEAREST", "2026-09-08T11:00:00+08:00")
    older = _record("OLDER", "2026-09-08T09:00:00+08:00")
    later = _set_chronology(
        _record("LATER", "2026-09-08T13:00:00+08:00"),
        source="2026-09-08T07:00:00+08:00",
        prediction="2026-09-08T07:01:00+08:00",
        freeze="2026-09-08T13:00:00+08:00",
    )
    wrong_match = _record("WRONG", "2026-09-08T11:59:00+08:00", match_id="M2", match_key="CANONICAL-M2")
    wrong_match["home"] = "Other FC"
    wrong_match["match_identity"]["home"] = "Other FC"

    first = build_prematch_change_awareness(
        records=[older, later, wrong_match, nearest, current],
        current_record=current,
        identity=_identity(current),
    )
    second = build_prematch_change_awareness(
        records=[current, nearest, wrong_match, later, older],
        current_record=current,
        identity=_identity(current),
    )

    assert first == second
    assert first["status"] == CHANGE_AWARENESS_STATUS_AVAILABLE
    assert first["previous_snapshot"]["prediction_id"] == "NEAREST"
    assert first["current_snapshot"]["prediction_id"] == "CURRENT"


def test_selects_previous_by_authoritative_source_cutoff_not_freeze_order():
    older = _set_chronology(
        _record("OLDER", "2026-09-08T10:17:00+08:00"),
        source="2026-09-08T10:00:00+08:00",
        prediction="2026-09-08T10:01:00+08:00",
        freeze="2026-09-08T10:17:00+08:00",
    )
    previous = _set_chronology(
        _record("PREVIOUS", "2026-09-08T10:16:00+08:00"),
        source="2026-09-08T10:10:00+08:00",
        prediction="2026-09-08T10:11:00+08:00",
        freeze="2026-09-08T10:16:00+08:00",
    )
    current = _set_chronology(
        _record("CURRENT", "2026-09-08T10:18:00+08:00"),
        source="2026-09-08T10:15:00+08:00",
        prediction="2026-09-08T10:16:00+08:00",
        freeze="2026-09-08T10:18:00+08:00",
    )

    result = build_prematch_change_awareness(
        records=[older, current, previous],
        current_record=current,
        identity=_identity(current),
    )

    assert result["previous_snapshot"]["prediction_id"] == "PREVIOUS"


def test_delayed_freeze_does_not_suppress_authoritative_previous_snapshot():
    previous = _set_chronology(
        _record("PREVIOUS", "2026-09-08T10:20:00+08:00"),
        source="2026-09-08T10:10:00+08:00",
        prediction="2026-09-08T10:11:00+08:00",
        freeze="2026-09-08T10:20:00+08:00",
    )
    current = _set_chronology(
        _record("CURRENT", "2026-09-08T10:18:00+08:00"),
        source="2026-09-08T10:15:00+08:00",
        prediction="2026-09-08T10:16:00+08:00",
        freeze="2026-09-08T10:18:00+08:00",
    )

    result = build_prematch_change_awareness(
        records=[current, previous],
        current_record=current,
        identity=_identity(current),
    )

    assert result["previous_snapshot"]["prediction_id"] == "PREVIOUS"


def test_current_snapshot_must_be_the_authoritative_latest_version():
    current = _set_chronology(
        _record("CURRENT", "2026-09-08T10:18:00+08:00"),
        source="2026-09-08T10:15:00+08:00",
        prediction="2026-09-08T10:16:00+08:00",
        freeze="2026-09-08T10:18:00+08:00",
    )
    later = _set_chronology(
        _record("LATER", "2026-09-08T10:22:00+08:00"),
        source="2026-09-08T10:20:00+08:00",
        prediction="2026-09-08T10:21:00+08:00",
        freeze="2026-09-08T10:22:00+08:00",
    )

    result = build_prematch_change_awareness(
        records=[current, later],
        current_record=current,
        identity=_identity(current),
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "CURRENT_SNAPSHOT_NOT_LATEST_LEGAL_PREMATCH"
    assert result["current_snapshot"] is None


def test_equal_final_chronology_fails_closed_for_current_or_previous_selection():
    current = _set_chronology(
        _record("CURRENT", "2026-09-08T10:18:00+08:00"),
        source="2026-09-08T10:15:00+08:00",
        prediction="2026-09-08T10:16:00+08:00",
        freeze="2026-09-08T10:18:00+08:00",
    )
    tied_previous_a = _set_chronology(
        _record("PREVIOUS-A", "2026-09-08T10:16:00+08:00"),
        source="2026-09-08T10:10:00+08:00",
        prediction="2026-09-08T10:11:00+08:00",
        freeze="2026-09-08T10:16:00+08:00",
    )
    tied_previous_b = _set_chronology(
        _record("PREVIOUS-B", "2026-09-08T10:16:00+08:00"),
        source="2026-09-08T10:10:00+08:00",
        prediction="2026-09-08T10:11:00+08:00",
        freeze="2026-09-08T10:16:00+08:00",
    )

    previous_ambiguous = build_prematch_change_awareness(
        records=[current, tied_previous_a, tied_previous_b],
        current_record=current,
        identity=_identity(current),
    )

    tied_current_a = copy.deepcopy(current)
    tied_current_a["prediction_id"] = "CURRENT-A"
    tied_current_b = copy.deepcopy(current)
    tied_current_b["prediction_id"] = "CURRENT-B"
    current_ambiguous = build_prematch_change_awareness(
        records=[tied_current_a, tied_current_b, tied_previous_a],
        current_record=tied_current_a,
        identity=_identity(tied_current_a),
    )

    assert previous_ambiguous["status"] == "UNAVAILABLE"
    assert previous_ambiguous["reason"] == "AMBIGUOUS_PREVIOUS_PREMATCH_CHRONOLOGY"
    assert previous_ambiguous["previous_snapshot"] is None
    assert current_ambiguous["status"] == "UNAVAILABLE"
    assert current_ambiguous["reason"] == "AMBIGUOUS_CURRENT_PREMATCH_CHRONOLOGY"
    assert current_ambiguous["current_snapshot"] is None


def test_post_kickoff_and_identity_conflict_records_are_not_comparable():
    current = _record("CURRENT", "2026-09-08T12:00:00+08:00")
    post_kickoff = _record("POST", "2026-09-09T00:00:00+08:00")
    post_kickoff["source_cutoff_at"] = "2026-09-09T00:00:00+08:00"
    conflicting = _record("CONFLICT", "2026-09-08T11:00:00+08:00")
    conflicting["home"] = "Other FC"

    result = build_prematch_change_awareness(
        records=[post_kickoff, conflicting],
        current_record=current,
        identity=_identity(current),
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "CURRENT_IDENTITY_CONFLICT"
    assert result["previous_snapshot"] is None


def test_no_previous_snapshot_does_not_replay_current_model_or_backfill_lanes():
    current, _, identity = _pair()

    result = build_prematch_change_awareness(
        records=[current],
        current_record=current,
        identity=identity,
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "NO_COMPARABLE_PREVIOUS_SNAPSHOT"
    assert all(item["status"] == "UNAVAILABLE" for item in result["markets"].values())
    assert all(item.get("comparison_allowed") is False for item in result["markets"].values())


def test_public_site_builder_attaches_persisted_change_history_to_selected_fixture(tmp_path):
    current, records, _ = _pair()
    prediction_root = tmp_path / "model_governance" / "predictions"
    prediction_root.mkdir(parents=True)
    (prediction_root / f"{current['prediction_id']}.json").write_text(
        json.dumps(current), encoding="utf-8"
    )
    fixture = {
        "match_id": current["match_id"],
        "match_key": current["match_key"],
        "home": current["home"],
        "away": current["away"],
        "kickoff": current["kickoff_at"],
        "selected_prediction_id": current["prediction_id"],
    }

    result = _change_awareness_for_fixture(
        tmp_path,
        fixture,
        records={record["prediction_id"]: record for record in records},
    )

    assert result["status"] == CHANGE_AWARENESS_STATUS_AVAILABLE
    assert result["current_snapshot"]["prediction_id"] == current["prediction_id"]
    assert result["previous_snapshot"]["prediction_id"] == records[1]["prediction_id"]


def test_ft_1x2_deltas_are_before_to_now_percentage_points():
    previous = _record(
        "PREVIOUS",
        "2026-09-08T10:00:00+08:00",
        probabilities={"home": 0.42, "draw": 0.31, "away": 0.27},
    )
    current = _record(
        "CURRENT",
        "2026-09-08T12:00:00+08:00",
        probabilities={"home": 0.50, "draw": 0.25, "away": 0.25},
    )
    result = build_prematch_change_awareness(
        records=[current, previous],
        current_record=current,
        identity=_identity(current),
    )

    lane = result["markets"]["ft_1x2"]
    assert lane["status"] == "AVAILABLE"
    assert lane["items"][0]["before"] == pytest.approx(0.42)
    assert lane["items"][0]["now"] == pytest.approx(0.50)
    assert lane["items"][0]["delta_probability_points"] == pytest.approx(8.0)
    assert lane["items"][0]["meaningful"] is True


def test_exact_comparison_preserves_explicit_finite_support_without_tail_reconstruction():
    previous = _record("PREVIOUS", "2026-09-08T10:00:00+08:00", lambda_home=1.0, lambda_away=1.0)
    current = _record("CURRENT", "2026-09-08T12:00:00+08:00", lambda_home=2.0, lambda_away=0.5)

    result = build_prematch_change_awareness(
        records=[previous, current],
        current_record=current,
        identity=_identity(current),
    )

    lane = result["markets"]["exact_score"]
    assert lane["status"] == "AVAILABLE"
    assert lane["support"] == {
        "representation": "FINITE_NORMALIZED_GRID",
        "support_semantics": "EXPLICIT_CELLS_ONLY",
        "cell_count": 169,
        "max_home_goals": 12,
        "max_away_goals": 12,
        "tail_bucket": False,
    }
    assert lane["support"]["tail_bucket"] is False
    assert lane["items"]
    assert all("tail_probability" not in item for item in lane["items"])


def test_total_schema_mismatch_is_local_and_does_not_poison_ft_or_exact():
    current, records, identity = _pair()
    previous = records[1]
    previous["jc_total_goals"] = copy.deepcopy(previous["jc_total_goals"])
    previous["jc_total_goals"]["selection_order"] = ["0", "1", "2", "3", "4", "5", "6", "6+"]

    result = build_prematch_change_awareness(
        records=records,
        current_record=current,
        identity=identity,
    )

    assert result["markets"]["ft_1x2"]["status"] == "AVAILABLE"
    assert result["markets"]["exact_score"]["status"] == "AVAILABLE"
    assert result["markets"]["jc_total_goals"]["status"] == "UNAVAILABLE"
    assert result["markets"]["jc_total_goals"]["reason"] == "JC_TOTAL_GOALS_SCHEMA_NOT_COMPARABLE"


def test_handicap_line_change_is_explicit_and_has_no_probability_delta():
    previous = _record("PREVIOUS", "2026-09-08T10:00:00+08:00", line=1)
    current = _record("CURRENT", "2026-09-08T12:00:00+08:00", line=-1)

    result = build_prematch_change_awareness(
        records=[current, previous],
        current_record=current,
        identity=_identity(current),
    )

    lane = result["markets"]["jc_handicap"]
    assert lane["status"] == "LINE_CHANGED"
    assert lane["comparison_allowed"] is False
    assert lane["before_line"] == 1
    assert lane["now_line"] == -1
    assert lane["items"] == []


def test_invalid_prior_market_isolated_from_valid_current_lanes():
    current, records, identity = _pair()
    previous = records[1]
    previous["jc_handicap"] = {"status": "INVALID"}

    result = build_prematch_change_awareness(
        records=records,
        current_record=current,
        identity=identity,
    )

    assert result["markets"]["ft_1x2"]["status"] == "AVAILABLE"
    assert result["markets"]["exact_score"]["status"] == "AVAILABLE"
    assert result["markets"]["jc_total_goals"]["status"] == "AVAILABLE"
    assert result["markets"]["jc_handicap"]["status"] == "UNAVAILABLE"


def test_result_field_on_candidate_is_rejected_instead_of_used_for_selection():
    current, _, identity = _pair()
    postmatch = _record("POSTMATCH", "2026-09-08T11:00:00+08:00")
    postmatch["result"] = {"score_90m": "9-9"}

    result = build_prematch_change_awareness(
        records=[postmatch],
        current_record=current,
        identity=identity,
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["previous_snapshot"] is None


def test_match_detail_renders_fact_only_change_section_and_completed_is_result_blind():
    current, records, identity = _pair()
    change = build_prematch_change_awareness(
        records=records,
        current_record=current,
        identity=identity,
    )
    contract = {
        "identity": {
            "match_id": current["match_id"],
            "home": current["home"],
            "away": current["away"],
            "kickoff_at": current["kickoff_at"],
        },
        "status": {"code": "FROZEN"},
        "hero": {"probabilities": current["probabilities"]},
        "model": {"probabilities": current["probabilities"]},
        "change_awareness": change,
        "result": None,
    }
    before = render_match_detail(contract)
    contract["result"] = {"score_90m": "9-9", "verified_at": "2026-09-09T08:00:00+08:00"}
    completed = render_match_detail(contract)

    for document in (before, completed):
        assert 'data-change-awareness-status="AVAILABLE"' in document
        assert 'data-change-lane="ft_1x2"' in document
        assert 'data-change-lane="exact_score"' in document
        assert 'data-change-lane="jc_total_goals"' in document
        assert 'data-change-lane="jc_handicap"' in document
        assert "资金涌入" not in document
        assert "聪明钱" not in document
    section_start = before.index('<section class="detail-section change-awareness-section"')
    section_end = before.index("</section>", section_start) + len("</section>")
    completed_start = completed.index('<section class="detail-section change-awareness-section"')
    completed_end = completed.index("</section>", completed_start) + len("</section>")
    assert before[section_start:section_end] == completed[completed_start:completed_end]


def test_match_detail_marks_missing_change_history_without_replacing_current_prediction():
    current, _, identity = _pair()
    change = build_prematch_change_awareness(
        records=[current],
        current_record=current,
        identity=identity,
    )
    document = render_match_detail({
        "identity": {
            "match_id": current["match_id"],
            "home": current["home"],
            "away": current["away"],
            "kickoff_at": current["kickoff_at"],
        },
        "status": {"code": "FROZEN"},
        "hero": {"probabilities": current["probabilities"]},
        "model": {"probabilities": current["probabilities"]},
        "change_awareness": change,
    })

    assert 'data-change-awareness-status="UNAVAILABLE"' in document
    assert "暂无可比的此前记录" in document
    assert 'class="probability-section"' in document
