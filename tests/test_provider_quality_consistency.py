from datetime import datetime, timezone
from pathlib import Path

from scripts.football_data.quality import evaluate_record
from scripts.football_data.providers.nowscore_500 import Nowscore500SnapshotProvider
from scripts.football_data.providers.statsbomb_open import StatsBombOpenDataProvider
from scripts.football_data.competition_resolution import CompetitionEntityResolver
from scripts.football_data.entity_resolution import TeamEntityResolver
from scripts.football_data.player_identity import PlayerIdentityResolver


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data"


def test_provider_quality_is_the_central_evaluation_result():
    record = Nowscore500SnapshotProvider(
        {
            "source": "500.com",
            "captured_at": "2026-08-10T11:00:00Z",
            "home_team": {"name": "Manchester United"},
            "away_team": {"name": "Paris Saint-Germain"},
            "lineups": [{
                "team_name": "Manchester United",
                "players": [{"name": "Unidentified player", "provider_player_id": "unknown"}],
            }],
        }
    ).get_lineup()[0]
    assert record["provenance"]["source_reliable"] is True
    evaluated = evaluate_record(record, data_class="fast_changing", now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))
    assert record["quality"] == evaluated["data_quality_grade"]
    assert record["freshness"]["state"] == "unknown"


def test_lineup_quality_exposes_unresolved_player_coverage_and_synthetic_records_are_not_high_grade():
    provider = StatsBombOpenDataProvider(
        FIXTURE,
        match_id="fixture-match-001",
        resolver=TeamEntityResolver(FIXTURE / "team_alias_registry.json"),
        competition_resolver=CompetitionEntityResolver(FIXTURE / "competition_identity_registry.json"),
        player_resolver=PlayerIdentityResolver(FIXTURE / "player_identity_registry.json"),
    )
    lineup = provider.get_lineup()[0]
    assert lineup["player_identity_coverage"]["resolved_players"] < lineup["player_identity_coverage"]["total_players"]
    assert lineup["quality"] == "C"
    assert lineup["freshness"]["state"] in {"fresh", "stale"}

    xg = provider.get_xg()[0]
    assert xg["provenance"]["source_reliable"] is False
    assert xg["quality"] == "C"
    assert evaluate_record(xg, data_class="historical_immutable", now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))["data_quality_grade"] == "C"


def test_material_form_and_xg_gaps_cannot_be_graded_as_b():
    base = {
        "canonical_entity_id": "team:test",
        "captured_at": "2026-08-10T10:00:00Z",
        "source_as_of_at": "2026-08-10T10:00:00Z",
        "sample_size": {"matches": None, "minutes": None},
        "value": None,
        "provenance": {"captured_at": "2026-08-10T10:00:00Z", "source_as_of_at": "2026-08-10T10:00:00Z"},
    }
    form = evaluate_record({**base, "metrics": {}, "window_type": None}, data_class="slow_changing", record_type="team_form_snapshot", now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))
    xg = evaluate_record({**base, "value": 1.2, "metric_definition": None}, data_class="historical_immutable", record_type="xg_snapshot", now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))
    assert form["data_quality_grade"] == "C"
    assert xg["data_quality_grade"] == "C"
