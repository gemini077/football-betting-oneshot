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
    assert presentation["label"] == "\u7cfb\u7edf\u9996\u63a8\u6bd4\u5206"
    assert presentation["note"] == ""


def test_alert_matched_current_serving_is_degraded_without_hiding_score():
    health = {**NORMAL_HEALTH, "status": "ALERT"}

    presentation = exact_score_serving_presentation(health)

    assert exact_score_serving_state(health) == DEGRADED
    assert presentation["label"] == "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38\uff0c\u4ec5\u4f9b\u89c2\u5bdf"
    assert presentation["note"] == "\u5f53\u524d\u8d28\u91cf\u5f02\u5e38\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350\uff1b\u539f\u59cb\u6bd4\u5206\u6982\u7387\u7ee7\u7eed\u4fdd\u7559\u3002\u0031X2\u3001\u53cc\u65b9\u8fdb\u7403\u3001\u5927\u5c0f\u0032.5\u6309\u5404\u81ea\u6982\u7387\u5c55\u793a\u3002"


def test_insufficient_sample_is_degraded_with_sample_specific_copy():
    health = {**NORMAL_HEALTH, "status": "INSUFFICIENT_SAMPLE", "sample_count": 5}

    presentation = exact_score_serving_presentation(health)

    assert exact_score_serving_state(health) == DEGRADED
    assert presentation["label"] == "\u6bd4\u5206\u9884\u6d4b\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf"
    assert presentation["note"] == "\u5f53\u524d\u6709\u6548\u6837\u672c\u4e0d\u8db3\uff0c\u6682\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u6bd4\u5206\u63a8\u8350\uff1b\u539f\u59cb\u6bd4\u5206\u6982\u7387\u7ee7\u7eed\u4fdd\u7559\u3002\u0031X2\u3001\u53cc\u65b9\u8fdb\u7403\u3001\u5927\u5c0f\u0032.5\u6309\u5404\u81ea\u6982\u7387\u5c55\u793a\u3002"
    assert presentation["local_label"] == "\u5f53\u524d\u6837\u672c\u4e0d\u8db3\uff0c\u4ec5\u4f9b\u89c2\u5bdf"


def test_alert_insufficient_and_unverified_copy_are_distinct():
    alert = exact_score_serving_presentation({**NORMAL_HEALTH, "status": "ALERT"})
    insufficient = exact_score_serving_presentation({**NORMAL_HEALTH, "status": "INSUFFICIENT_SAMPLE"})
    unverified = exact_score_serving_presentation({**NORMAL_HEALTH, "provenance_status": "MISMATCHED"})

    assert len({alert["label"], insufficient["label"], unverified["label"]}) == 3
    assert "\u8d28\u91cf\u5f02\u5e38" in alert["label"]
    assert "\u6837\u672c\u4e0d\u8db3" in insufficient["label"]
    assert "\u5f85\u786e\u8ba4" in unverified["label"]


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
    assert presentation["label"] == "\u6bd4\u5206\u9884\u6d4b\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350"
    assert presentation["note"] == "\u5f71\u54cd\u6bd4\u5206\u9884\u6d4b\u63a8\u8350\u8bed\u4e49\uff1b\u4fdd\u7559\u539f\u59cb\u6bd4\u5206\u6982\u7387\uff0c\u5f85\u5b8c\u6210\u8d28\u91cf\u786e\u8ba4\u3002"


def test_stale_previous_cycle_alert_is_unverified_not_current_degradation():
    stale_alert = {
        **NORMAL_HEALTH,
        "status": "ALERT",
        "provenance_status": "MISMATCHED",
    }

    assert exact_score_serving_state(stale_alert) == UNVERIFIED
