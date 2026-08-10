from pathlib import Path

from scripts.football_data.player_identity import PlayerIdentityResolver


ROOT = Path(__file__).resolve().parents[1]


def test_player_resolution_requires_reviewed_id_or_unique_team_context():
    value = PlayerIdentityResolver(ROOT / "data" / "football_data" / "player_identity_registry.json")
    result = value.resolve_player("statsbomb", "Fixture Captain", "102", team_id="team:manchester-united")
    assert result.canonical_player_id == "player:fixture-captain"
    assert result.resolution_method == "provider_id_exact"
    assert value.resolve_player("statsbomb", "Fixture Captain", "102", team_id="team:paris-saint-germain").canonical_player_id is None
    assert value.resolve_player("unknown", "Fixture Captain").canonical_player_id is None
