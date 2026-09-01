from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    PROMOTION_REVIEW_MINIMUM,
    build_challenger_c_output,
    build_shadow_document,
    checkpoint_status,
    evaluate_paired_cohort,
    select_promotion_representatives,
)
from challenger_c_promotion_review import _gate_statuses  # noqa: E402


SHANGHAI = timezone(timedelta(hours=8))
KICKOFF = datetime(2026, 9, 10, 12, 0, tzinfo=SHANGHAI)


def _iso(value):
    return value.isoformat()


def _output(candidate_id):
    return {
        "candidate_id": candidate_id,
        "model_family": candidate_id,
        "namespace": candidate_id,
        "lambda_home": 1.2,
        "lambda_away": 0.8,
        "lambda_total": 2.0,
        "rho": 0.0,
        "probabilities": {"home": 0.35, "draw": 0.40, "away": 0.25},
        "exact_score_distribution": [
            {"rank": 1, "score": "1-1", "probability": 0.40},
            {"rank": 2, "score": "1-0", "probability": 0.30},
            {"rank": 3, "score": "0-1", "probability": 0.20},
            {"rank": 4, "score": "0-0", "probability": 0.10},
        ],
        "score_top1": "1-1",
        "score_top3": ["1-1", "1-0", "0-1"],
        "btts_probability": 0.55,
        "ou_2_5_probability": 0.45,
        "tail_probabilities": {"total_ge_4": 0.20, "total_ge_5": 0.10, "total_ge_6": 0.04},
    }


def _pair(
    match_id="M-1",
    version=0,
    *,
    source=None,
    freeze=None,
    kickoff=KICKOFF,
    integrity=None,
    promotion_eligible=True,
):
    source = source or (KICKOFF - timedelta(days=5) + timedelta(hours=version))
    freeze = freeze or (source + timedelta(minutes=5))
    pair_id = f"PAIR-{match_id}-{version}"
    return {
        "pair_id": pair_id,
        "pair_status": "PAIRED",
        "match_id": match_id,
        "match_key": f"KEY-{match_id}",
        "kickoff_at": _iso(kickoff),
        "source_cutoff": _iso(source),
        "freeze_created_at": _iso(freeze),
        "frozen_input_digest": f"digest-{match_id}-{version}",
        "challenger_prediction_id": f"shadow-c:{pair_id}",
        "champion_prediction_id": f"champion:{pair_id}",
        "promotion_eligible": promotion_eligible,
        "same_fixture": True,
        "champion_preserved": True,
        "post_match_input_used_for_generation": False,
        "integrity": integrity or {
            "same_match_id": True,
            "same_source_cutoff": True,
            "same_freeze_eligibility": True,
            "same_frozen_input_digest": True,
        },
        "champion": _output("champion"),
        "challenger": _output("challenger"),
    }


def _results(pairs):
    return {str(pair["match_id"]): {"actual_score": "1-1"} for pair in pairs}


def _formula_context():
    deep = {
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 15, "goals_against": 10},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 8},
            "away_overall": {"matches": 10, "goals_for": 11, "goals_against": 14},
            "away_away": {"matches": 10, "goals_for": 9, "goals_against": 16},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 1.8, "draw": 3.5, "away": 4.5}},
            {"spf_current": {"home": 1.9, "draw": 3.4, "away": 4.4}},
        ]},
        "daxiao": {"companies": [{"current_line": 2.5}]},
    }
    return {
        "request": {"match_id": "fixture-formula"},
        "selected_workspace_match": {"id": "fixture-formula", "home": "Home", "away": "Away"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    }


def test_seven_legal_versions_are_one_verified_promotion_observation():
    pairs = [_pair(version=index) for index in range(7)]
    evaluation = evaluate_paired_cohort(pairs, _results(pairs))

    assert evaluation["total_pair_version_rows"] == 7
    assert evaluation["promotion_eligible_pair_version_rows"] == 7
    assert evaluation["verified_pair_version_rows"] == 7
    assert evaluation["promotion_eligible_unique_matches"] == 1
    assert evaluation["verified_unique_matches"] == 1
    assert evaluation["version_history_match_groups"] == 1
    assert evaluation["extra_version_rows"] == 6
    assert evaluation["candidates"]["challenger"]["sample_count"] == 1


def test_latest_legal_prematch_version_is_representative():
    pairs = [_pair(version=index) for index in range(7)]
    selected = select_promotion_representatives(pairs, _results(pairs))

    assert [pair["pair_id"] for pair in selected["selected_representatives"]] == ["PAIR-M-1-6"]
    group = selected["groups"][0]
    assert group["status"] == "SELECTED"
    assert group["selected_pair_id"] == "PAIR-M-1-6"
    assert group["selected_frozen_input_digest"] == "digest-M-1-6"


def test_later_valid_version_changes_representative_but_not_sample_size():
    earlier = [_pair(version=index) for index in range(6)]
    before = evaluate_paired_cohort(earlier, _results(earlier))
    later = earlier + [_pair(version=6)]
    after = evaluate_paired_cohort(later, _results(later))

    assert before["representative_selector"]["groups"][0]["selected_pair_id"] == "PAIR-M-1-5"
    assert after["representative_selector"]["groups"][0]["selected_pair_id"] == "PAIR-M-1-6"
    assert before["verified_unique_matches"] == after["verified_unique_matches"] == 1
    assert before["candidates"]["challenger"]["sample_count"] == after["candidates"]["challenger"]["sample_count"] == 1


def test_post_kickoff_version_is_excluded_from_representative_selection():
    legal = _pair(version=0)
    post = _pair(
        version=1,
        source=KICKOFF + timedelta(minutes=1),
        freeze=KICKOFF + timedelta(minutes=2),
    )
    selected = select_promotion_representatives([legal, post], _results([legal, post]))

    assert [pair["pair_id"] for pair in selected["selected_representatives"]] == [legal["pair_id"]]
    assert selected["groups"][0]["excluded_version_counts"] == {"POST_KICKOFF_VERSION": 1}


def test_integrity_failed_version_is_excluded():
    legal = _pair(version=0)
    invalid = _pair(
        version=1,
        integrity={
            "same_match_id": True,
            "same_source_cutoff": False,
            "same_freeze_eligibility": True,
            "same_frozen_input_digest": True,
        },
    )
    selected = select_promotion_representatives([legal, invalid], _results([legal, invalid]))

    assert [pair["pair_id"] for pair in selected["selected_representatives"]] == [legal["pair_id"]]
    assert selected["groups"][0]["excluded_version_counts"] == {"INTEGRITY_INVALID": 1}


def test_equal_final_chronology_fails_closed():
    source = KICKOFF - timedelta(days=1)
    freeze = source + timedelta(minutes=5)
    first = _pair(version=1, source=source, freeze=freeze)
    second = _pair(version=2, source=source, freeze=freeze)
    selected = select_promotion_representatives([first, second], _results([first, second]))
    evaluation = evaluate_paired_cohort([first, second], _results([first, second]))

    assert selected["groups"][0]["status"] == "AMBIGUOUS_FINAL_CHRONOLOGY"
    assert selected["selected_representatives"] == []
    assert evaluation["verified_pair_version_rows"] == 2
    assert evaluation["verified_unique_matches"] == 0
    assert evaluation["candidates"]["champion"]["sample_count"] == 0


def test_fifty_unique_matches_pass_checkpoint_with_many_version_rows():
    pairs = [
        _pair(
            match_id=f"M-{match_index}",
            version=version,
            source=KICKOFF - timedelta(days=2) + timedelta(hours=version),
            freeze=KICKOFF - timedelta(days=2) + timedelta(hours=version, minutes=5),
        )
        for match_index in range(50)
        for version in range(4)
    ]
    document = build_shadow_document(pairs, _results(pairs))

    assert document["counts"]["total_pair_version_rows"] == 200
    assert document["counts"]["verified_pair_version_rows"] == 200
    assert document["counts"]["promotion_eligible_unique_matches"] == 50
    assert document["counts"]["verified_unique_matches"] == 50
    assert document["checkpoint"]["status"] == "CHECKPOINT"
    assert document["checkpoint"]["verified_unique_matches"] == 50
    assert document["checkpoint"]["verified_pair_version_rows"] == 200
    assert document["checkpoint"]["auto_promote"] is False

    slice_metrics = {
        candidate: {
            "exact_nll": 2.0 if candidate == "champion" else 1.9,
            "one_one_top1_share": 0.70 if candidate == "champion" else 0.40,
            "one_x_two_brier": 0.20,
            "one_x_two_log_loss": 0.50,
            "btts_brier": 0.20,
            "ou_2_5_brier": 0.20,
        }
        for candidate in ("champion", "challenger")
    }
    gate = _gate_statuses(
        integrity={"status": "PASS"},
        reproduction={"status": "PASS"},
        unique_count=document["counts"]["verified_unique_matches"],
        minimum_unique_matches=50,
        subgroup_gate={"status": "PASS"},
        overall_metrics=slice_metrics,
        slices={"earlier": {"metrics": slice_metrics}, "later": {"metrics": slice_metrics}},
    )
    assert gate["checks"]["unique_match_promotion_gate"] is True


def test_repeated_versions_cannot_accelerate_checkpoint():
    pairs = [_pair(version=index) for index in range(PROMOTION_REVIEW_MINIMUM + 1)]
    document = build_shadow_document(pairs, _results(pairs))

    assert document["counts"]["total_pair_version_rows"] == PROMOTION_REVIEW_MINIMUM + 1
    assert document["counts"]["verified_unique_matches"] == 1
    assert document["checkpoint"]["status"] == "NOT_REACHED"
    assert document["checkpoint"]["next_threshold"] == 50


def test_pair_version_history_is_not_mutated_by_representative_evaluation():
    pairs = [_pair(version=index) for index in range(7)]
    original = deepcopy(pairs)
    build_shadow_document(pairs, _results(pairs))

    assert pairs == original
    serialized_before = [json.dumps(pair, ensure_ascii=False, sort_keys=True) for pair in original]
    serialized_after = [json.dumps(pair, ensure_ascii=False, sort_keys=True) for pair in pairs]
    assert hashlib.sha256("\n".join(serialized_before).encode()).hexdigest() == hashlib.sha256(
        "\n".join(serialized_after).encode()
    ).hexdigest()


def test_champion_and_c_generation_formula_boundary_is_unchanged():
    output = build_challenger_c_output(_formula_context())

    assert output["candidate_id"] == "market_side_only_hybrid"
    assert output["formula"]["total"] == "champion_total_0.60_form_0.40_market"
    assert output["formula"]["share"] == "market_share_only"
    assert output["formula"]["score_matrix"] == "independent_poisson_rho_0"
    assert output["rho"] == 0.0
    assert len(output["exact_score_distribution"]) == 169
    assert set(output["probabilities"]) == {"home", "draw", "away"}
    assert set(output["tail_probabilities"]) == {"total_ge_4", "total_ge_5", "total_ge_6"}


def test_checkpoint_status_reports_unique_observation_and_raw_audit_separately():
    checkpoint = checkpoint_status(29, verified_pair_version_rows=112)

    assert checkpoint["status"] == "NOT_REACHED"
    assert checkpoint["verified_unique_matches"] == 29
    assert checkpoint["verified_pair_version_rows"] == 112
    assert checkpoint["next_threshold"] == 50
    assert checkpoint["auto_promote"] is False
