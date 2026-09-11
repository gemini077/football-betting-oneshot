from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pure_market_exact_paired_review import build_review  # noqa: E402
from pure_market_exact_prospective import RESULT_SCOPE  # noqa: E402


KICKOFF = "2026-09-10T12:00:00+00:00"


def _control_pair(
    *,
    champion_id: str,
    match_key: str,
    cutoff: str,
    freeze: str = "2026-09-10T08:05:00+00:00",
    champion_sha: str | None = None,
    snapshot_id: str | None = None,
) -> dict:
    return {
        "prediction_id": champion_id,
        "prediction_sha256": champion_sha or f"sha-{champion_id}",
        "match_key": match_key,
        "snapshot_id": snapshot_id or f"snapshot-{match_key}",
        "source_cutoff_at": cutoff,
        "freeze_created_at": freeze,
        "same_match": True,
        "same_source_cutoff": True,
        "same_horizon_authority": True,
    }


def _settlement(
    *,
    market_id: str,
    match_key: str,
    champion_id: str = "CHAMPION-1",
    source_cutoff: str = "2026-09-10T08:00:00+00:00",
    generated_at: str = "2026-09-10T08:01:00+00:00",
    freeze: str = "2026-09-10T08:05:00+00:00",
    score: str = "0-0",
    control_pair: dict | None = None,
    metrics: dict | None = None,
) -> dict:
    pair = control_pair
    if pair is None:
        pair = _control_pair(
            champion_id=champion_id,
            match_key=match_key,
            cutoff=source_cutoff,
            freeze=freeze,
        )
    return {
        "settlement_status": "SETTLED",
        "prediction_id": market_id,
        "match_key": match_key,
        "kickoff_at": KICKOFF,
        "prediction_generated_at": generated_at,
        "source_cutoff_at": source_cutoff,
        "prediction_digest": f"sha-{market_id}",
        "result": {
            "actual_score": score,
            "scope": RESULT_SCOPE,
            "verified_at": "2026-09-10T13:00:00+00:00",
        },
        "metrics": metrics or {
            "exact_nll": 1.0,
            "exact_top1": True,
            "exact_top3": True,
            "exact_top5": True,
            "actual_score_rank": 1,
            "ft_1x2_log_loss": 1.0,
            "ft_1x2_brier": 1.0,
            "ft_1x2_rps": 1.0,
            "ou_2_5_brier": 1.0,
            "btts_brier": 1.0,
            "lambda_home_residual": 0.0,
            "lambda_away_residual": 0.0,
            "lambda_total_residual": 0.0,
            "lambda_home_absolute_error": 0.0,
            "lambda_away_absolute_error": 0.0,
            "lambda_total_absolute_error": 0.0,
            "score_1_1_top1": False,
        },
        "control_pair": pair,
    }


def _prediction(
    *,
    prediction_id: str,
    match_key: str,
    champion: bool,
    source_cutoff: str = "2026-09-10T08:00:00+00:00",
    generated_at: str = "2026-09-10T08:01:00+00:00",
    freeze: str = "2026-09-10T08:05:00+00:00",
    probabilities: dict | None = None,
    matrix: list[dict] | None = None,
    lambda_home: float = 1.0,
    lambda_away: float = 1.0,
) -> dict:
    probabilities = probabilities or {"home": 0.0, "draw": 1.0, "away": 0.0}
    matrix = matrix or [{"score": "0-0", "probability": 1.0}]
    return {
        "prediction_id": prediction_id,
        "prediction_sha256": f"sha-{prediction_id}",
        "match_key": match_key,
        "match_id": match_key,
        "kickoff_at": KICKOFF,
        "source_cutoff_at": source_cutoff,
        "prediction_created_at": generated_at,
        "freeze_created_at": freeze,
        "model_input_as_of_at": source_cutoff,
        "model_role": "champion" if champion else "shadow",
        "model_family": "recent_form_market_calibrated_poisson_v2" if champion else "pure_market_exact_prospective_1",
        "formal_eligible": champion,
        "model_formal_eligible": champion,
        "prediction_variant": "model_only",
        "manual_override": False,
        "input_snapshot": {"snapshot_id": f"snapshot-{match_key}"},
        "match_identity": {"match_key": match_key, "kickoff_at": KICKOFF},
        "probabilities": probabilities,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rho": 0.0,
        "score_matrix": matrix,
        "btts": {"yes": 0.0, "no": 1.0},
        "score_matrix_complete": True,
    }


def test_exact_control_pair_uses_stored_id_not_match_nearest_champion():
    market_id = "PM-EXACT"
    match_key = "MATCH-EXACT"
    settlement = _settlement(market_id=market_id, match_key=match_key, champion_id="CHAMPION-EXACT")
    champion = _prediction(prediction_id="CHAMPION-EXACT", match_key=match_key, champion=True)
    decoy = _prediction(prediction_id="CHAMPION-DECOY", match_key=match_key, champion=True)

    report = build_review(
        [settlement],
        market_predictions={market_id: _prediction(prediction_id=market_id, match_key=match_key, champion=False)},
        champion_predictions={champion["prediction_id"]: champion, decoy["prediction_id"]: decoy},
    )

    assert report["counts"]["paired_unique_match_count"] == 1
    assert report["pairs"][0]["champion_prediction_id"] == "CHAMPION-EXACT"


def test_latest_legal_market_version_is_selected_without_result_or_metric_cherry_picking():
    match_key = "MATCH-LATEST"
    older = _settlement(
        market_id="PM-OLDER",
        match_key=match_key,
        metrics={**_settlement(market_id="PM-TEMP", match_key="TEMP")["metrics"], "exact_nll": 0.1},
    )
    newer = _settlement(
        market_id="PM-NEWER",
        match_key=match_key,
        source_cutoff="2026-09-10T08:30:00+00:00",
        generated_at="2026-09-10T08:31:00+00:00",
        metrics={**older["metrics"], "exact_nll": 9.0},
    )
    postkickoff = _settlement(
        market_id="PM-POST",
        match_key=match_key,
        source_cutoff="2026-09-10T12:01:00+00:00",
        generated_at="2026-09-10T12:01:00+00:00",
    )
    champion = _prediction(
        prediction_id="CHAMPION-1",
        match_key=match_key,
        champion=True,
        source_cutoff="2026-09-10T08:30:00+00:00",
        generated_at="2026-09-10T08:31:00+00:00",
    )

    report = build_review([older, newer, postkickoff], champion_predictions={"CHAMPION-1": champion})

    assert report["counts"]["raw_market_settlement_count"] == 3
    assert report["counts"]["unique_market_matches"] == 1
    assert report["counts"]["paired_unique_match_count"] == 1
    assert report["market_selection"][0]["selected_market_prediction_id"] == "PM-NEWER"
    assert report["pairs"][0]["market"]["exact_nll"] == 9.0
    assert report["counts"]["selection_excluded_reason_counts"] == {
        "MARKET_VERSION_POST_KICKOFF": 1
    }


def test_missing_mismatch_and_conflicting_control_pairs_fail_closed():
    missing = _settlement(market_id="PM-MISSING", match_key="MATCH-MISSING", control_pair=None)
    missing.pop("control_pair")
    unknown = _settlement(market_id="PM-UNKNOWN", match_key="MATCH-UNKNOWN", champion_id="CHAMPION-UNKNOWN")
    mismatch = _settlement(market_id="PM-MISMATCH", match_key="MATCH-MISMATCH", champion_id="CHAMPION-MISMATCH")
    mismatch_champion = _prediction(prediction_id="CHAMPION-MISMATCH", match_key="OTHER-MATCH", champion=True)

    conflict = _settlement(market_id="PM-CONFLICT", match_key="MATCH-CONFLICT", champion_id="CHAMPION-A")
    conflict_market = _prediction(prediction_id="PM-CONFLICT", match_key="MATCH-CONFLICT", champion=False)
    conflict_market["champion_reference"] = {"prediction_id": "CHAMPION-B"}

    report = build_review(
        [missing, unknown, mismatch, conflict],
        market_predictions={
            "PM-MISSING": _prediction(prediction_id="PM-MISSING", match_key="MATCH-MISSING", champion=False),
            "PM-UNKNOWN": _prediction(prediction_id="PM-UNKNOWN", match_key="MATCH-UNKNOWN", champion=False),
            "PM-MISMATCH": _prediction(prediction_id="PM-MISMATCH", match_key="MATCH-MISMATCH", champion=False),
            "PM-CONFLICT": conflict_market,
        },
        champion_predictions={"CHAMPION-MISMATCH": mismatch_champion},
    )

    assert report["counts"]["paired_unique_match_count"] == 0
    assert report["counts"]["reject_reason_counts"] == {
        "CHAMPION_PREDICTION_MISSING": 1,
        "CONTROL_PAIR_ID_CONFLICT": 1,
        "CONTROL_PAIR_MISSING": 1,
        "MATCH_IDENTITY_MISMATCH": 1,
    }


def test_duplicate_market_versions_count_one_unique_pair():
    match_key = "MATCH-DUPLICATE"
    rows = [
        _settlement(
            market_id=f"PM-DUP-{index}",
            match_key=match_key,
            source_cutoff=f"2026-09-10T08:{index:02d}:00+00:00",
            generated_at=f"2026-09-10T08:{index:02d}:30+00:00",
        )
        for index in range(3)
    ]
    champion = _prediction(
        prediction_id="CHAMPION-1",
        match_key=match_key,
        champion=True,
        source_cutoff="2026-09-10T08:02:00+00:00",
        generated_at="2026-09-10T08:02:30+00:00",
    )

    report = build_review(rows, champion_predictions={"CHAMPION-1": champion})

    assert report["counts"]["raw_market_settlement_count"] == 3
    assert report["counts"]["unique_market_matches"] == 1
    assert report["counts"]["paired_unique_match_count"] == 1
    assert report["counts"]["superseded_market_version_count"] == 2


def test_metrics_use_identical_result_and_expose_paired_deltas():
    match_key = "MATCH-METRICS"
    market_id = "PM-METRICS"
    champion_id = "CHAMPION-METRICS"
    market = _prediction(
        prediction_id=market_id,
        match_key=match_key,
        champion=False,
        probabilities={"home": 0.7, "draw": 0.2, "away": 0.1},
        matrix=[
            {"score": "0-0", "probability": 0.7},
            {"score": "1-0", "probability": 0.3},
        ],
        lambda_home=1.4,
        lambda_away=0.5,
    )
    champion = _prediction(
        prediction_id=champion_id,
        match_key=match_key,
        champion=True,
        probabilities={"home": 0.6, "draw": 0.25, "away": 0.15},
        matrix=[
            {"score": "0-0", "probability": 0.4},
            {"score": "1-0", "probability": 0.6},
        ],
        lambda_home=1.1,
        lambda_away=0.8,
    )
    market["totals"] = [
        {"goals": "0", "probability": 0.1},
        {"goals": "1", "probability": 0.2},
        {"goals": "2", "probability": 0.3},
        {"goals": "3", "probability": 0.4},
    ]
    champion["totals"] = [
        {"goals": "0", "probability": 0.2},
        {"goals": "1", "probability": 0.3},
        {"goals": "2", "probability": 0.3},
        {"goals": "3", "probability": 0.2},
    ]
    settlement = _settlement(
        market_id=market_id,
        match_key=match_key,
        champion_id=champion_id,
        score="1-0",
    )
    settlement["control_pair"]["prediction_sha256"] = champion["prediction_sha256"]

    report = build_review(
        [settlement],
        market_predictions={market_id: market},
        champion_predictions={champion_id: champion},
    )

    pair = report["pairs"][0]
    assert pair["actual_score"] == "1-0"
    assert pair["market"]["actual_score_rank"] == 2
    assert pair["champion"]["actual_score_rank"] == 1
    assert pair["market"]["exact_nll"] == pytest.approx(-math.log(0.3))
    assert pair["champion"]["exact_nll"] == pytest.approx(-math.log(0.6))
    assert pair["market"]["ou_2_5_brier"] == pytest.approx(0.4**2)
    assert pair["champion"]["ou_2_5_brier"] == pytest.approx(0.2**2)
    assert pair["deltas"]["actual_score_rank"] == 1
    assert report["metrics"]["paired_comparisons"]["actual_score_rank"]["market_losses"] == 1


@pytest.mark.parametrize(
    ("count", "verdict"),
    [
        (49, "INSUFFICIENT_SAMPLE_CONTINUE_ACCUMULATING"),
        (50, "DIRECTION_AND_UNCERTAINTY_ONLY_NO_AUTOMATIC_PROMOTION"),
        (99, "DIRECTION_AND_UNCERTAINTY_ONLY_NO_AUTOMATIC_PROMOTION"),
        (100, "MATURE_FOR_SEPARATE_INDEPENDENT_PROMOTION_REGATE"),
    ],
)
def test_maturity_rule_is_based_on_paired_unique_matches(count, verdict):
    settlements = []
    champions = {}
    markets = {}
    for index in range(count):
        match_key = f"MATCH-MATURITY-{index:03d}"
        market_id = f"PM-MATURITY-{index:03d}"
        champion_id = f"CHAMPION-MATURITY-{index:03d}"
        settlement = _settlement(market_id=market_id, match_key=match_key, champion_id=champion_id)
        market = _prediction(prediction_id=market_id, match_key=match_key, champion=False)
        champion = _prediction(prediction_id=champion_id, match_key=match_key, champion=True)
        settlement["control_pair"]["prediction_sha256"] = champion["prediction_sha256"]
        settlements.append(settlement)
        markets[market_id] = market
        champions[champion_id] = champion

    report = build_review(
        settlements,
        market_predictions=markets,
        champion_predictions=champions,
    )

    assert report["counts"]["paired_unique_match_count"] == count
    assert report["decision"]["verdict"] == verdict
    assert report["decision"]["winner"] is None
    assert report["decision"]["promotion_authorized"] is False
