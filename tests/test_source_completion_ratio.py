from __future__ import annotations

from scripts.football_data.coverage import classify_source_completeness


def test_completed_season_with_53_of_240_results_is_partial():
    result = classify_source_completeness(
        listed_match_count=240,
        parsed_result_count=53,
        season_status="completed",
    )

    assert result["result_completion_ratio"] == 53 / 240
    assert result["source_completeness_status"] == "PARTIAL"
    assert result["result_coverage"] == "PARTIAL"


def test_current_in_progress_season_is_not_claimed_complete():
    result = classify_source_completeness(
        listed_match_count=240,
        parsed_result_count=119,
        season_status="in_progress",
    )

    assert result["source_completeness_status"] == "IN_PROGRESS"
    assert result["result_coverage"] == "PARTIAL"


def test_complete_result_source_is_supported_only_when_all_results_are_parsed():
    result = classify_source_completeness(
        listed_match_count=306,
        parsed_result_count=306,
        season_status="completed",
    )

    assert result["source_completeness_status"] == "COMPLETE"
    assert result["result_coverage"] == "SUPPORTED"
