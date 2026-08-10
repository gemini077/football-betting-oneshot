from __future__ import annotations

from scripts.football_data.historical_results import (
    deduplicate_historical_results,
    make_historical_match_result,
)


def make(
    *,
    match_id: str | None,
    provider: str,
    provider_match_id: str,
    home: str | None = "team:home",
    away: str | None = "team:away",
    hg: int = 1,
    ag: int = 0,
) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id=home,
        away_team_id=away,
        kickoff_at="2026-08-01T12:00:00Z",
        home_goals=hg,
        away_goals=ag,
        provider=provider,
        provider_match_id=provider_match_id,
        source_as_of_at="2026-08-01T12:00:00Z",
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"{provider}:{provider_match_id}",
        source_reliable=True,
        resolution_method="manual_verified" if home and away else "unresolved",
        raw_home_team="Home FC",
        raw_away_team="Away FC",
    )


def test_uncertain_cross_provider_duplicate_is_not_automatically_merged():
    report = deduplicate_historical_results([
        make(match_id=None, provider="nowscore", provider_match_id="1", home=None, away=None),
        make(match_id=None, provider="500", provider_match_id="2", home=None, away=None),
    ])

    assert len(report.records) == 2
    assert report.possible_duplicates == 1
    assert all(row["duplicate_status"] == "possible_duplicate" for row in report.records)


def test_same_identity_with_different_score_is_a_conflict_not_a_merge():
    report = deduplicate_historical_results([
        make(match_id="match:conflict", provider="nowscore", provider_match_id="1", hg=1, ag=0),
        make(match_id="match:conflict", provider="500", provider_match_id="2", hg=2, ag=0),
    ])

    assert len(report.records) == 2
    assert report.conflicts == 1
    assert all(row["duplicate_status"] == "duplicate_conflict" for row in report.records)


def test_same_conservative_identity_with_different_score_is_not_merged():
    report = deduplicate_historical_results([
        make(match_id=None, provider="nowscore", provider_match_id="1", hg=1, ag=0),
        make(match_id=None, provider="500", provider_match_id="2", hg=2, ag=0),
    ])

    assert len(report.records) == 2
    assert report.conflicts == 1
    assert all(row["duplicate_status"] == "duplicate_conflict" for row in report.records)
