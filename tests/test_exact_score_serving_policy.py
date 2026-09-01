import pytest

from scripts.exact_score_serving_policy import (
    DEGRADED,
    NORMAL,
    UNVERIFIED,
    exact_score_serving_presentation,
    exact_score_serving_state,
)


NORMAL_HEALTH = {
    "scope": "current_serving",
    "available": True,
    "provenance_status": "MATCHED",
    "status": "HEALTHY",
}


def test_healthy_matched_current_serving_is_normal():
    assert exact_score_serving_state(NORMAL_HEALTH) == NORMAL
    presentation = exact_score_serving_presentation(NORMAL_HEALTH)
    assert presentation["label"] == "系统首推比分"
    assert presentation["note"] == ""


def test_alert_matched_current_serving_is_degraded_without_hiding_score():
    health = {**NORMAL_HEALTH, "status": "ALERT"}

    presentation = exact_score_serving_presentation(health)

    assert exact_score_serving_state(health) == DEGRADED
    assert presentation["label"] == "模型原始比分 · 当前不作为推荐"
    assert presentation["note"] == "当前比分推荐能力处于质量降级状态"


@pytest.mark.parametrize(
    "health",
    [
        {**NORMAL_HEALTH, "provenance_status": "MISMATCHED"},
        {**NORMAL_HEALTH, "available": False},
        {**NORMAL_HEALTH, "scope": "historical_audit"},
        {},
    ],
)
def test_unverified_quality_never_becomes_normal_or_degraded(health):
    presentation = exact_score_serving_presentation(health)

    assert exact_score_serving_state(health) == UNVERIFIED
    assert presentation["label"] == "预测质量状态待确认 · 模型原始输出"
    assert presentation["note"] == ""


def test_stale_previous_cycle_alert_is_unverified_not_current_degradation():
    stale_alert = {
        **NORMAL_HEALTH,
        "status": "ALERT",
        "provenance_status": "MISMATCHED",
    }

    assert exact_score_serving_state(stale_alert) == UNVERIFIED
