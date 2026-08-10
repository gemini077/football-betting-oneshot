from pathlib import Path

from scripts.football_data.player_identity import PlayerIdentityResolver


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data"


def test_production_player_registry_does_not_resolve_synthetic_fixture_people():
    resolver = PlayerIdentityResolver(ROOT / "data" / "football_data" / "player_identity_registry.json")
    result = resolver.resolve_player("statsbomb", "Fixture Captain", "102", team_id="team:manchester-united")
    assert result.canonical_player_id is None
    assert result.resolution_status == "unresolved"


def test_test_only_registry_resolves_only_test_namespace():
    resolver = PlayerIdentityResolver(FIXTURE / "player_identity_registry.json")
    result = resolver.resolve_player("statsbomb_fixture", "Fixture Captain", "102", team_id="team:manchester-united")
    assert result.canonical_player_id == "player:fixture-captain"
    assert resolver.resolve_player("statsbomb", "Fixture Captain", "102", team_id="team:manchester-united").canonical_player_id is None
