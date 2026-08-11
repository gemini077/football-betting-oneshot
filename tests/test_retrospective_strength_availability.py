from __future__ import annotations

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.p0_p1_coverage import audit_retrospective_availability


def _result(index: int, kickoff: str, home: str = "team:home", away: str = "team:away") -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:test:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{index}",
        source_as_of_at=kickoff,
        captured_at="2026-08-10T00:00:00Z",
        source_reliable=True,
        resolution_method="manual_verified",
        match_type="league",
    )


def test_retro_audit_uses_only_history_before_target_and_exposes_team_facts():
    records = [
        _result(index, f"2026-07-{index + 1:02d}T12:00:00Z")
        for index in range(5)
    ]
    records.append(_result(99, "2026-08-12T12:00:00Z", "team:home", "team:future"))
    target = {
        "canonical_match_id": "target:test",
        "competition_id": "competition:test",
        "season_id": "season:test:2026",
        "kickoff_at": "2026-08-11T12:00:00Z",
        "home": "Home",
        "away": "Away",
        "home_team_id": "team:home",
        "away_team_id": "team:away",
        "entity_type": "club",
    }

    audit = audit_retrospective_availability(
        [target],
        records,
        captured_at="2026-08-11T00:00:00Z",
    )[0]

    assert audit["strength_ready"] is True
    assert audit["home_history_matches"] == 5
    assert audit["away_history_matches"] == 5
    assert "match:test:99" not in audit["home_source_match_ids"]
    assert audit["target_kickoff"] == "2026-08-11T12:00:00Z"
