from datetime import datetime, timezone

from scripts.football_data.quality import freshness_status


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_fast_changing_uses_source_fact_time_not_capture_time():
    result = freshness_status(
        captured_at="2026-08-10T11:00:00Z",
        source_as_of_at="2026-08-08T11:00:00Z",
        data_class="fast_changing",
        now=NOW,
    )
    assert result["state"] == "stale"
    assert result["age_seconds"] == 176400


def test_fast_changing_without_source_fact_time_is_unknown():
    result = freshness_status(
        captured_at="2026-08-10T11:00:00Z",
        source_as_of_at=None,
        data_class="fast_changing",
        now=NOW,
    )
    assert result["state"] == "unknown"
    assert result["reason"] == "source_fact_time_missing"


def test_availability_source_timestamp_has_priority_over_capture_and_source_as_of():
    result = freshness_status(
        captured_at="2026-08-10T11:00:00Z",
        source_as_of_at="2026-08-10T11:30:00Z",
        source_timestamp="2026-08-08T11:00:00Z",
        data_class="fast_changing",
        now=NOW,
    )
    assert result["state"] == "stale"
    assert result["age_seconds"] == 176400


def test_future_source_fact_time_is_unknown_and_flagged():
    result = freshness_status(
        captured_at="2026-08-10T10:00:00Z",
        source_as_of_at="2026-08-10T13:00:00Z",
        data_class="fast_changing",
        now=NOW,
    )
    assert result["state"] == "unknown"
    assert result["timestamp_conflict"] is True


def test_capture_time_fallback_is_explicit_and_class_specific():
    slow = freshness_status(
        captured_at="2026-08-10T10:00:00Z",
        source_as_of_at=None,
        data_class="slow_changing",
        now=NOW,
    )
    immutable = freshness_status(
        captured_at="2026-08-10T10:00:00Z",
        source_as_of_at=None,
        data_class="historical_immutable",
        now=NOW,
    )
    assert slow["state"] == "fresh"
    assert slow["reference"] == "captured_at"
    assert immutable["state"] == "unknown"
    assert immutable["reference"] is None
