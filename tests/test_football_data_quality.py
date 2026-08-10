from datetime import datetime, timezone

from scripts.football_data.quality import assess_quality, evaluate_record, freshness_status


def test_quality_grades_are_data_quality_not_prediction_quality():
    assert assess_quality({"identity_confirmed": True, "timestamp_known": True, "reliable_source": True, "sample_complete": True}) == "A"
    assert assess_quality({"identity_confirmed": True, "timestamp_known": True, "reliable_source": True, "sample_complete": False}) == "B"
    assert assess_quality({"identity_confirmed": False, "timestamp_known": True, "reliable_source": True}) == "C"
    assert assess_quality({"identity_conflict": True, "identity_confirmed": True, "timestamp_known": True, "reliable_source": True}) == "D"


def test_freshness_uses_class_specific_ttl_and_unknown_time():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    assert freshness_status(captured_at="2026-08-10T10:00:00Z", source_as_of_at=None, data_class="fast_changing", now=now)["state"] == "unknown"
    assert freshness_status(captured_at="2026-08-09T00:00:00Z", source_as_of_at=None, data_class="fast_changing", now=now)["state"] == "unknown"
    assert freshness_status(captured_at=None, source_as_of_at=None, data_class="fast_changing", now=now)["state"] == "unknown"


def test_historical_xg_is_immutable_until_explicitly_invalidated():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    fresh = freshness_status(captured_at="2020-01-01T00:00:00Z", source_as_of_at="2020-01-01T00:00:00Z", data_class="historical_immutable", now=now)
    stale = freshness_status(captured_at="2020-01-01T00:00:00Z", source_as_of_at="2020-01-01T00:00:00Z", data_class="historical_immutable", now=now, invalidated=True)
    assert fresh["state"] == "fresh"
    assert stale["state"] == "stale"


def test_evaluate_record_reports_both_grade_and_freshness():
    result = evaluate_record(
        {
            "canonical_entity_id": "team:test",
            "captured_at": "2026-08-10T10:00:00Z",
            "source_as_of_at": "2026-08-10T10:00:00Z",
            "sample_size": {"matches": 5, "minutes": 450},
            "value": 1.2,
            "provenance": {"captured_at": "2026-08-10T10:00:00Z", "source_as_of_at": "2026-08-10T10:00:00Z"},
        },
        data_class="slow_changing",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )
    assert result["data_quality_grade"] == "A"
    assert result["freshness"]["state"] == "fresh"
