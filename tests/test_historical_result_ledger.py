from __future__ import annotations

import json

from scripts.football_data.contracts import ContractError, validate_record
from scripts.football_data.historical_results import (
    HistoricalResultLedger,
    deduplicate_historical_results,
    make_historical_match_result,
)


def result_record(
    match_id: str = "match:past-a",
    *,
    provider: str = "nowscore",
    provider_match_id: str = "nowscore:past-a",
    home_team_id: str | None = "team:home",
    away_team_id: str | None = "team:away",
    kickoff_at: str = "2026-08-01T12:00:00Z",
    home_goals: int | None = 2,
    away_goals: int | None = 1,
    source_as_of_at: str | None = "2026-08-01T14:00:00Z",
    source_reliable: bool | None = True,
    resolution_status: str | None = "resolved",
) -> dict:
    return make_historical_match_result(
        canonical_match_id=match_id,
        competition_id="competition:test",
        season_id="season:2026",
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        kickoff_at=kickoff_at,
        home_goals=home_goals,
        away_goals=away_goals,
        provider=provider,
        provider_match_id=provider_match_id,
        source_as_of_at=source_as_of_at,
        captured_at="2026-08-10T00:00:00Z",
        source_record_ref=f"fixture:{match_id}",
        source_reliable=source_reliable,
        resolution_status=resolution_status,
        resolution_method="manual_verified" if resolution_status == "resolved" else "unresolved",
        raw_home_team="Home FC",
        raw_away_team="Away FC",
    )


def test_historical_result_contract_preserves_result_lineage_and_eligibility():
    record = result_record()

    assert validate_record("historical_match_result", record)
    assert record["eligible_for_team_strength"] is True
    assert record["provenance"]["source_record_ref"] == "fixture:match:past-a"
    assert record["provenance"]["source_reliable"] is True


def test_unresolved_result_is_raw_only_and_not_strength_eligible():
    record = result_record(
        match_id="match:unresolved",
        home_team_id=None,
        away_team_id=None,
        resolution_status="unresolved",
        source_reliable=False,
    )

    assert validate_record("historical_match_result", record)
    assert record["eligible_for_team_strength"] is False
    assert "identity_unresolved" in record["missing_reason"]


def test_missing_source_fact_time_does_not_become_eligible():
    record = result_record(match_id="match:no-source-time", source_as_of_at=None)

    assert validate_record("historical_match_result", record)
    assert record["quality"] == "C"
    assert record["eligible_for_team_strength"] is False
    assert record["freshness"]["state"] == "unknown"


def test_ledger_is_content_addressed_and_idempotent(tmp_path):
    ledger = HistoricalResultLedger(tmp_path / "results")
    record = result_record()

    first_digest = ledger.append(record)
    second_digest = ledger.append(json.loads(json.dumps(record)))

    assert first_digest == second_digest
    assert len(ledger.records()) == 1
    assert ledger.records()[0]["canonical_match_id"] == "match:past-a"


def test_invalid_eligible_record_is_rejected():
    record = result_record(home_goals=None)
    record["eligible_for_team_strength"] = True

    with __import__("pytest").raises(ContractError, match="eligible"):
        validate_record("historical_match_result", record)


def test_same_canonical_match_from_two_providers_collapses_once():
    left = result_record(provider="nowscore", provider_match_id="nowscore:1")
    right = result_record(provider="500", provider_match_id="500:1")

    report = deduplicate_historical_results([left, right])

    assert len(report.records) == 1
    assert report.duplicates_collapsed == 1
    assert report.possible_duplicates == 0
    assert report.conflicts == 0
