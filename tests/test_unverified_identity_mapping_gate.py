import json

from scripts.football_data.entity_resolution import TeamEntityResolver
from scripts.football_data.player_identity import PlayerIdentityResolver


def _write_registry(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _team_registry(mapping, *, crosswalk=None):
    return {
        "contract_version": "team_alias_registry.v1",
        "teams": [{
            "canonical_team_id": "team:test",
            "canonical_name": "Canonical FC",
            "aliases": ["Canonical FC"],
            "country": "England",
            "competition_context": [],
            "gender": "male",
            "team_level": "senior",
            "provider_mappings": [mapping] if mapping is not None else [],
        }],
        "crosswalk": crosswalk or [],
    }


def _player_registry(mapping):
    return {
        "contract_version": "player_identity.v1",
        "players": [{
            "canonical_player_id": "player:test",
            "canonical_name": "Canonical Player",
            "team_id": "team:test",
            "provider_mappings": [mapping] if mapping is not None else [],
        }],
    }


def test_unverified_team_provider_id_cannot_confirm_or_claim_reviewed_reason(tmp_path):
    path = _write_registry(tmp_path, "teams.json", _team_registry({
        "provider": "test-provider",
        "provider_team_id": "123",
        "provider_team_name": "Unverified Team",
        "aliases": [],
        "verified": False,
        "resolution_method": "provider_id_exact",
    }))
    result = TeamEntityResolver(path).resolve_team("test-provider", "Unknown Team", "123")
    assert result.resolution_status == "unresolved"
    assert result.resolution_method == "unresolved"
    assert result.confidence is None
    assert result.reason != "reviewed provider ID mapping"


def test_unverified_team_provider_exact_name_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "teams.json", _team_registry({
        "provider": "test-provider",
        "provider_team_id": "123",
        "provider_team_name": "Unverified Team",
        "aliases": [],
        "verified": False,
        "resolution_method": "exact_alias",
    }))
    result = TeamEntityResolver(path).resolve_team("test-provider", "Unverified Team")
    assert result.resolution_status == "unresolved"


def test_unverified_team_provider_normalized_alias_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "teams.json", _team_registry({
        "provider": "test-provider",
        "provider_team_id": "123",
        "provider_team_name": "Unverified Team",
        "aliases": ["Unverified Alias"],
        "verified": False,
        "resolution_method": "normalized_alias",
    }))
    result = TeamEntityResolver(path).resolve_team("test-provider", "Unverified-Alias")
    assert result.resolution_status == "unresolved"


def test_verified_team_provider_id_can_confirm(tmp_path):
    path = _write_registry(tmp_path, "teams.json", _team_registry({
        "provider": "test-provider",
        "provider_team_id": "123",
        "provider_team_name": "Verified Team",
        "aliases": [],
        "verified": True,
        "resolution_method": "provider_id_exact",
    }))
    result = TeamEntityResolver(path).resolve_team("test-provider", "Unrelated Team", "123")
    assert result.canonical_team_id == "team:test"
    assert result.resolution_method == "provider_id_exact"
    assert result.confidence == 1.0
    assert result.reason == "reviewed provider ID mapping"


def test_unverified_crosswalk_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "teams.json", _team_registry(
        None,
        crosswalk=[{
            "provider": "test-provider",
            "provider_team_id": "123",
            "canonical_team_id": "team:test",
            "verified": False,
            "resolution_method": "existing_crosswalk",
        }],
    ))
    result = TeamEntityResolver(path).resolve_team("test-provider", "Unrelated Team", "123")
    assert result.resolution_status == "unresolved"
    assert result.resolution_method == "unresolved"


def test_unverified_player_provider_id_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "players.json", _player_registry({
        "provider": "test-provider",
        "provider_player_id": "999",
        "provider_player_name": "Unverified Player",
        "aliases": [],
        "verified": False,
        "resolution_method": "provider_id_exact",
    }))
    result = PlayerIdentityResolver(path).resolve_player("test-provider", "Unknown Player", "999", team_id="team:test")
    assert result.resolution_status == "unresolved"
    assert result.resolution_method == "unresolved"
    assert result.confidence is None
    assert result.reason != "reviewed provider player ID"


def test_unverified_player_provider_exact_name_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "players.json", _player_registry({
        "provider": "test-provider",
        "provider_player_id": "999",
        "provider_player_name": "Unverified Player",
        "aliases": [],
        "verified": False,
        "resolution_method": "exact_alias",
    }))
    result = PlayerIdentityResolver(path).resolve_player("test-provider", "Unverified Player", team_id="team:test")
    assert result.resolution_status == "unresolved"


def test_unverified_player_provider_normalized_alias_cannot_confirm(tmp_path):
    path = _write_registry(tmp_path, "players.json", _player_registry({
        "provider": "test-provider",
        "provider_player_id": "999",
        "provider_player_name": "Unverified Player",
        "aliases": ["Unverified Alias"],
        "verified": False,
        "resolution_method": "normalized_alias",
    }))
    result = PlayerIdentityResolver(path).resolve_player("test-provider", "Unverified-Alias", team_id="team:test")
    assert result.resolution_status == "unresolved"


def test_verified_player_provider_id_can_confirm(tmp_path):
    path = _write_registry(tmp_path, "players.json", _player_registry({
        "provider": "test-provider",
        "provider_player_id": "999",
        "provider_player_name": "Verified Player",
        "aliases": [],
        "verified": True,
        "resolution_method": "provider_id_exact",
    }))
    result = PlayerIdentityResolver(path).resolve_player("test-provider", "Unrelated Player", "999", team_id="team:test")
    assert result.canonical_player_id == "player:test"
    assert result.resolution_method == "provider_id_exact"
    assert result.confidence == 1.0
    assert result.reason == "reviewed provider player ID"
