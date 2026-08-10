from __future__ import annotations

from scripts.football_data.historical_results import deduplicate_historical_results, make_historical_match_result


def result(score: tuple[int, int], provider: str):
    return make_historical_match_result(
        canonical_match_id="match:same",
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id="team:home",
        away_team_id="team:away",
        kickoff_at="2026-08-01T12:00:00Z",
        home_goals=score[0],
        away_goals=score[1],
        provider=provider,
        provider_match_id=f"{provider}:same",
        source_as_of_at="2026-08-01T14:00:00Z",
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"{provider}:same",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def test_conflicting_source_scores_are_not_counted():
    report = deduplicate_historical_results([result((1, 0), "source-a"), result((2, 0), "source-b")])

    assert report.conflicts == 1
    assert all(row["source_conflict"] is True for row in report.records)
    assert all(row["eligible_for_team_strength"] is False for row in report.records)
    assert all(row["quality"] == "D" for row in report.records)


def test_matching_sources_collapse_and_preserve_confirmations():
    report = deduplicate_historical_results([result((1, 0), "source-a"), result((1, 0), "source-b")])

    assert len(report.records) == 1
    assert report.records[0]["source_conflict"] is False
    assert len(report.records[0]["source_confirmations"]) == 2
    assert report.records[0]["eligible_for_team_strength"] is True
