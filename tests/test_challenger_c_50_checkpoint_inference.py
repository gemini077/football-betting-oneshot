from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import random
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from challenger_c_50_checkpoint_inference import (  # noqa: E402
    ACCEPTED_PR175_BASELINE,
    build_audit_cohort,
    build_competition_slices,
    decide_primary,
    leave_one_out_summary,
    moving_block_indices,
    paired_bootstrap_summary,
    preregistered_block_length,
    natural_main_delta,
)


TZ = timezone(timedelta(hours=8))
KICKOFF = datetime(2026, 9, 10, 12, 0, tzinfo=TZ)


def _output(*, actual_probability, one_x_two=None):
    return {
        "probabilities": one_x_two or {"home": 0.55, "draw": 0.25, "away": 0.20},
        "exact_score_distribution": [
            {"score": "1-0", "probability": actual_probability},
            {"score": "0-0", "probability": 1.0 - actual_probability},
        ],
        "score_top1": "1-0",
        "score_top3": ["1-0", "0-0"],
        "btts_probability": 0.40,
        "ou_2_5_probability": 0.30,
        "lambda_home": 1.2,
        "lambda_away": 0.8,
    }


def _pair(match_id="M-1", version=0, *, champion_probability=0.20, challenger_probability=0.40):
    source = KICKOFF - timedelta(days=2) + timedelta(hours=version)
    return {
        "pair_id": f"PAIR-{match_id}-{version}",
        "pair_status": "PAIRED",
        "match_id": match_id,
        "match_key": f"KEY-{match_id}",
        "kickoff_at": KICKOFF.isoformat(),
        "source_cutoff": source.isoformat(),
        "freeze_created_at": (source + timedelta(minutes=5)).isoformat(),
        "frozen_input_digest": f"digest-{match_id}-{version}",
        "challenger_prediction_id": f"shadow-c:PAIR-{match_id}-{version}",
        "champion_prediction_id": f"champion:PAIR-{match_id}-{version}",
        "promotion_eligible": True,
        "same_fixture": True,
        "champion_preserved": True,
        "post_match_input_used_for_generation": False,
        "integrity": {
            "same_match_id": True,
            "same_source_cutoff": True,
            "same_freeze_eligibility": True,
            "same_frozen_input_digest": True,
        },
        "champion": _output(actual_probability=champion_probability),
        "challenger": _output(actual_probability=challenger_probability),
    }


def _result():
    return {"home_score_90m": 1, "away_score_90m": 0}


def test_multiple_pair_versions_become_one_chronological_observation():
    pairs = [_pair(version=0), _pair(version=1)]
    before = deepcopy(pairs)

    cohort = build_audit_cohort(
        pairs,
        {"M-1": _result()},
        snapshot_at="2026-09-11T00:00:00+00:00",
    )

    assert cohort["selection"]["counts"]["promotion_eligible_unique_matches"] == 1
    assert cohort["selection"]["counts"]["verified_unique_matches"] == 1
    assert len(cohort["paired_rows"]) == 1
    assert cohort["paired_rows"][0]["pair_id"] == "PAIR-M-1-1"
    assert pairs == before


def test_read_only_cohort_audit_does_not_mutate_prediction_or_result_inputs():
    pairs = [_pair(version=0)]
    results = {"M-1": _result()}
    pairs_before = deepcopy(pairs)
    results_before = deepcopy(results)

    build_audit_cohort(
        pairs,
        results,
        snapshot_at="2026-09-11T00:00:00+00:00",
    )

    assert pairs == pairs_before
    assert results == results_before


def test_paired_exact_nll_delta_sign_is_challenger_minus_champion():
    cohort = build_audit_cohort(
        [_pair(champion_probability=0.20, challenger_probability=0.40)],
        {"M-1": _result()},
        snapshot_at="2026-09-11T00:00:00+00:00",
    )

    row = cohort["paired_rows"][0]
    assert row["delta_nll"] == pytest.approx(math.log(0.20 / 0.40))
    assert row["delta_nll"] < 0


def test_fixed_seed_iid_bootstrap_is_reproducible():
    values = [-0.20, -0.05, 0.10, 0.30]

    first = paired_bootstrap_summary(values, resamples=1000, seed=17601)
    second = paired_bootstrap_summary(values, resamples=1000, seed=17601)

    assert first == second
    assert first["resamples"] == 1000
    assert first["seed"] == 17601
    assert set(first["ci"]) == {"lower", "upper"}


def test_moving_block_bootstrap_is_chronological_and_preregistered():
    assert preregistered_block_length(56) == 7
    rng = random.Random(17602)
    indices = moving_block_indices(8, rng, block_length=3)

    assert len(indices) == 8
    assert all(0 <= index < 8 for index in indices)
    for start in (0, 3, 6):
        block = indices[start : min(start + 3, 8)]
        assert all((right - left) % 8 == 1 for left, right in zip(block, block[1:]))


def test_leave_one_out_reports_influence_and_sign_flip():
    rows = [
        {"match_key": "A", "delta_nll": -0.20},
        {"match_key": "B", "delta_nll": -0.10},
        {"match_key": "C", "delta_nll": 0.40},
    ]

    summary = leave_one_out_summary(rows)

    assert summary["full_mean_delta"] == pytest.approx(0.10 / 3)
    assert summary["sign_flip"] is True
    assert "C" in summary["sign_flip_match_keys"]
    assert summary["max_abs_shift"] == pytest.approx(abs(-0.15 - 0.10 / 3))


def test_small_competition_slice_is_insufficient_not_a_conclusion():
    rows = [
        {"match_id": f"M-{index}", "match_key": f"K-{index}", "delta_nll": -0.10}
        for index in range(3)
    ]

    slices = build_competition_slices(rows, {row["match_id"]: "League A" for row in rows})

    assert slices["League A"]["status"] == "INSUFFICIENT_SAMPLE"
    assert slices["League A"]["n"] == 3
    assert slices["League A"]["mean_delta_nll"] is None


def test_natural_main_delta_is_separate_from_accepted_pr175_baseline():
    assert ACCEPTED_PR175_BASELINE == {
        "eligible_unique_matches": 74,
        "verified_unique_matches": 56,
        "unmatched_unique_matches": 18,
    }
    assert natural_main_delta({
        "eligible_unique_matches": 80,
        "verified_unique_matches": 56,
        "unmatched_unique_matches": 24,
    }) == {
        "eligible_unique_matches": 6,
        "verified_unique_matches": 0,
        "unmatched_unique_matches": 6,
    }


def test_primary_decision_requires_both_cis_and_loo_stability():
    assert decide_primary(
        mean_delta=-0.02,
        iid_upper=0.01,
        block_upper=-0.01,
        loo_sign_flip=False,
        opposite_slice_names=[],
    ) == "C_SIGNAL_PROMISING_NOT_ESTABLISHED"
    assert decide_primary(
        mean_delta=-0.02,
        iid_upper=-0.001,
        block_upper=-0.002,
        loo_sign_flip=False,
        opposite_slice_names=[],
    ) == "C_SIGNAL_STABLE_KEEP_TO_100"
