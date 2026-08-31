from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.football_data.identity_registry import IdentityRegistryResolver
from scripts.nowscore_markets import prebind_match, resolve_match


KICKOFF = "2026-09-01T00:00:00+08:00"


def _resolver() -> IdentityRegistryResolver:
    return IdentityRegistryResolver({
        "contract_version": "identity_registry.v1",
        "teams": [
            {
                "canonical_team_id": "team:test:one",
                "canonical_name": "Canonical One",
                "competition_scope": ["competition:test"],
                "provider_mappings": [
                    {
                        "provider": "500",
                        "provider_team_id": None,
                        "provider_exact_name": "Fixture Home",
                        "competition_scope": ["competition:test"],
                        "verified": True,
                    },
                    {
                        "provider": "nowscore",
                        "provider_team_id": "10",
                        "provider_exact_name": "Provider Home",
                        "competition_scope": ["competition:test"],
                        "verified": True,
                    },
                ],
            },
        ],
    })


def _fixture() -> dict:
    return {
        "matchId": "500-fixture",
        "league": "Test League",
        "homeTeam": "Fixture Home",
        "awayTeam": "Unknown Away",
    }


def _schedule(*rows: dict) -> list[dict]:
    return [
        {
            "nowscore_id": 123,
            "home_team_id": 10,
            "away_team_id": 20,
            "home_team": "Provider Home",
            "home_team_en": "Provider Home",
            "away_team": "Unrelated Away",
            "away_team_en": "Unrelated Away",
            "kickoff_local": KICKOFF,
        },
        *rows,
    ]


def test_identity_fallback_resolves_unique_provider_id_after_strict_miss():
    fixture = _fixture()
    schedule = _schedule({
        "nowscore_id": 999,
        "home_team_id": 30,
        "away_team_id": 31,
        "home_team": "Other Home",
        "home_team_en": "Other Home",
        "away_team": "Other Away",
        "away_team_en": "Other Away",
        "kickoff_local": KICKOFF,
    })

    strict = resolve_match(
        fixture["homeTeam"], fixture["awayTeam"], KICKOFF, schedule
    )
    result = resolve_match(
        fixture["homeTeam"], fixture["awayTeam"], KICKOFF, schedule,
        fixture=fixture,
        competition_id="competition:test",
        identity_resolver=_resolver(),
    )

    assert strict["status"] == "NO_EXACT_MATCH"
    assert result["status"] == "EXACT_MATCH"
    assert result["nowscore_id"] == 123
    assert result["resolution_method"] == "deterministic_identity_fallback"
    assert result["identity_fallback"]["identity_filtered_candidate_ids"] == [123]


def test_identity_fallback_fails_closed_on_multiple_provider_ids():
    second = {
        "nowscore_id": 124,
        "home_team_id": 10,
        "away_team_id": 22,
        "home_team": "Provider Home",
        "home_team_en": "Provider Home",
        "away_team": "Another Away",
        "away_team_en": "Another Away",
        "kickoff_local": KICKOFF,
    }
    result = resolve_match(
        "Fixture Home", "Unknown Away", KICKOFF, _schedule(second),
        fixture=_fixture(), competition_id="competition:test",
        identity_resolver=_resolver(),
    )

    assert result["status"] == "NO_EXACT_MATCH"
    assert "nowscore_id" not in result
    assert result["fallback_status"] == "AMBIGUOUS_MATCH"
    assert result["identity_fallback"]["identity_filtered_candidate_ids"] == [123, 124]


def test_identity_fallback_fails_closed_on_orientation_conflict():
    reversed_row = {
        "nowscore_id": 125,
        "home_team_id": 30,
        "away_team_id": 10,
        "home_team": "Other Home",
        "home_team_en": "Other Home",
        "away_team": "Provider Home",
        "away_team_en": "Provider Home",
        "kickoff_local": KICKOFF,
    }
    result = resolve_match(
        "Fixture Home", "Unknown Away", KICKOFF, [reversed_row],
        fixture=_fixture(), competition_id="competition:test",
        identity_resolver=_resolver(),
    )

    assert result["status"] == "NO_EXACT_MATCH"
    assert "nowscore_id" not in result
    assert result["fallback_status"] == "ORIENTATION_CONFLICT"


def test_identity_fallback_requires_confirmed_side_and_competition_context():
    no_context = resolve_match(
        "Unmapped Home", "Unknown Away", KICKOFF, _schedule(),
        fixture={"matchId": "500-fixture"},
        identity_resolver=_resolver(),
    )
    no_side = resolve_match(
        "Unmapped Home", "Unknown Away", KICKOFF, _schedule(),
        fixture={"matchId": "500-fixture"},
        competition_id="competition:test",
        identity_resolver=_resolver(),
    )

    assert no_context["status"] == "NO_EXACT_MATCH"
    assert no_context["fallback_status"] == "NO_COMPETITION_CONTEXT"
    assert no_side["status"] == "NO_EXACT_MATCH"
    assert no_side["fallback_status"] == "NO_CONFIRMED_SIDE"
    assert "nowscore_id" not in no_side


def test_stored_binding_blocks_identity_fallback():
    with patch(
        "scripts.nowscore_markets.lookup_provider_binding",
        return_value={"id": "999"},
    ):
        result = resolve_match(
            "Fixture Home", "Unknown Away", KICKOFF, _schedule(),
            fixture=_fixture(), competition_id="competition:test",
            identity_resolver=_resolver(),
        )

    assert result["status"] == "NO_EXACT_MATCH"
    assert "nowscore_id" not in result
    assert "fallback_status" not in result


def test_prebind_records_identity_fallback_as_verified_schedule_binding():
    with patch("scripts.nowscore_markets.record_binding") as record:
        result = prebind_match(
            "Fixture Home", "Unknown Away", KICKOFF, _schedule(),
            fixture=_fixture(), competition_id="competition:test",
            identity_resolver=_resolver(),
        )

    assert result["status"] == "EXACT_MATCH"
    assert result["nowscore_id"] == 123
    assert record.call_args.kwargs["verification"] == (
        "schedule_pair_time_identity_fallback"
    )
