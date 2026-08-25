from __future__ import annotations

from scripts.football_data.phase2c1_model import probability_payload
from scripts.football_data.prediction_quality_gate import evaluate_shadow_promotion_gate


def prediction(match_id: str, lambda_home: float, lambda_away: float, *, actual_home: int = 1, actual_away: int = 1) -> dict:
    distribution = probability_payload(lambda_home, lambda_away)
    return {
        "target_match_id": match_id,
        "actual": {"home_goals": actual_home, "away_goals": actual_away},
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": {
            "1x2": distribution["1x2"],
            "totals": distribution["totals"],
            "btts": distribution["btts"],
        },
        **distribution,
    }


def test_fewer_top1_one_to_one_with_worse_probability_losses_fails():
    champion = [prediction(f"match-{index}", 1.2, 1.2) for index in range(4)]
    challenger = [prediction(f"match-{index}", 2.4, 0.2) for index in range(4)]

    result = evaluate_shadow_promotion_gate(champion, challenger)

    assert result["status"] == "FAIL"
    assert result["promotion_eligible"] is False
    assert result["paired"]["same_match_keys"] is True
    assert result["deltas"]["top1_1_to_1_concentration"] < 0
    assert result["primary_probability_quality"]["brier"]["passed"] is False
    assert result["primary_probability_quality"]["log_loss"]["passed"] is False
    assert "brier_degradation_exceeds_bound" in result["blocking_reasons"]
    assert "log_loss_degradation_exceeds_bound" in result["blocking_reasons"]


def test_gate_requires_exact_same_match_keys():
    champion = [prediction("match-a", 1.2, 1.2), prediction("match-b", 1.2, 1.2)]
    challenger = [prediction("match-a", 1.2, 1.2), prediction("match-c", 1.2, 1.2)]

    result = evaluate_shadow_promotion_gate(champion, challenger)

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["promotion_eligible"] is False
    assert result["paired"]["same_match_keys"] is False
    assert "same_match_keys_required" in result["blocking_reasons"]


def test_unavailable_true_pairs_are_insufficient_not_a_pass():
    result = evaluate_shadow_promotion_gate([], [])

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["promotion_eligible"] is False
    assert result["automatic_promotion"] is False
    assert "true_paired_samples_unavailable" in result["blocking_reasons"]


def test_equal_quality_on_same_pairs_is_shadow_review_eligible_only():
    champion = [prediction("match-a", 1.2, 1.2), prediction("match-b", 1.2, 1.2)]
    challenger = [prediction("match-a", 1.2, 1.2), prediction("match-b", 1.2, 1.2)]

    result = evaluate_shadow_promotion_gate(champion, challenger)

    assert result["status"] == "PASS"
    assert result["promotion_eligible"] is True
    assert result["automatic_promotion"] is False
    assert result["mode"] == "shadow_only"
