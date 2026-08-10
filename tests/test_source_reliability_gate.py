from datetime import datetime, timezone

from scripts.football_data.quality import evaluate_record


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _team_record(provenance):
    return {
        "canonical_entity_id": "team:test",
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
        "sample_size": {"matches": 5, "minutes": 450},
        "value": 1.2,
        "provenance": provenance,
    }


def test_missing_source_reliability_evidence_is_not_reliable():
    result = evaluate_record(_team_record({
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
    }), data_class="slow_changing", record_type="team_identity", now=NOW)
    assert result["flags"]["reliable_source"] is False
    assert result["data_quality_grade"] == "C"


def test_unknown_nonempty_source_strings_cannot_masquerade_as_reliable():
    result = evaluate_record(_team_record({
        "provider": "random-webpage",
        "source": "unknown-blog",
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
    }), data_class="slow_changing", record_type="team_identity", now=NOW)
    assert result["flags"]["reliable_source"] is False
    assert result["data_quality_grade"] == "C"


def test_reviewed_provider_sets_explicit_source_reliability():
    result = evaluate_record(_team_record({
        "provider": "nowscore",
        "source": "nowscore",
        "source_reliable": True,
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
    }), data_class="slow_changing", record_type="team_identity", now=NOW)
    assert result["flags"]["reliable_source"] is True
    assert result["data_quality_grade"] == "A"


def test_synthetic_schema_fixture_is_never_high_grade():
    result = evaluate_record(_team_record({
        "provider": "statsbomb_fixture",
        "source": "synthetic_statsbomb_schema_fixture",
        "source_reliable": False,
        "synthetic": True,
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
    }), data_class="slow_changing", record_type="team_identity", now=NOW)
    assert result["flags"]["reliable_source"] is False
    assert result["data_quality_grade"] == "C"
