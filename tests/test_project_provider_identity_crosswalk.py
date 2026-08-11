from __future__ import annotations

from scripts.football_data.project_identity import ProjectProviderIdentityResolver


def _mapping(**overrides):
    row = {
        "provider": "500",
        "provider_team_id": None,
        "provider_team_name": "布兰",
        "canonical_team_id": "team:norway:brann",
        "canonical_name": "SK Brann",
        "competition_id": "competition:norway-eliteserien",
        "country": "Norway",
        "verified": True,
        "resolution_method": "project_provider_context_verified",
    }
    row.update(overrides)
    return row


def test_verified_project_mapping_enters_one_resolver_by_name_and_id():
    resolver = ProjectProviderIdentityResolver(
        [
            _mapping(provider_team_name="布兰"),
            _mapping(
                provider="nowscore",
                provider_team_id="42",
                provider_team_name="Brann",
            ),
        ]
    )

    by_name = resolver.resolve_team(
        "500",
        "布兰",
        competition_id="competition:norway-eliteserien",
        country="Norway",
    )
    by_id = resolver.resolve_team(
        "nowscore",
        "Brann",
        "42",
        competition_id="competition:norway-eliteserien",
        country="Norway",
    )

    assert by_name.canonical_team_id == "team:norway:brann"
    assert by_name.resolution_method == "project_provider_context_verified"
    assert by_id.canonical_team_id == "team:norway:brann"
    assert by_id.resolution_method == "provider_id_exact"


def test_unverified_project_mapping_is_not_read_as_truth():
    resolver = ProjectProviderIdentityResolver(
        [_mapping(verified=False, resolution_method="exact_alias", provider_team_id="999")]
    )

    result = resolver.resolve_team(
        "500",
        "布兰",
        "999",
        competition_id="competition:norway-eliteserien",
        country="Norway",
    )

    assert result.canonical_team_id is None
    assert result.resolution_status == "unresolved"
    assert "reviewed" not in result.reason


def test_conflicting_reviewed_mappings_do_not_resolve():
    resolver = ProjectProviderIdentityResolver(
        [
            _mapping(canonical_team_id="team:norway:brann"),
            _mapping(canonical_team_id="team:norway:other"),
        ]
    )

    result = resolver.resolve_team(
        "500",
        "布兰",
        competition_id="competition:norway-eliteserien",
        country="Norway",
    )

    assert result.canonical_team_id is None
    assert result.resolution_status == "unresolved"

