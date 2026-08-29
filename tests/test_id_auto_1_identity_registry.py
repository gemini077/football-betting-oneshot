from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.football_data.identity_registry import IdentityRegistryResolver
from scripts.football_data.identity_registry import IdentityRegistryBuilder


def registry(*teams: dict) -> dict:
    return {
        "contract_version": "identity_registry.v1",
        "resolution_ladder": [
            "stable_provider_id_crosswalk",
            "reviewed_canonical_provider_crosswalk",
            "fixture_canonical_id",
            "competition_exact_normalized_name",
            "competition_reviewed_alias",
        ],
        "teams": list(teams),
    }


def team(team_id: str, name: str, *, aliases: list[str] | None = None, source_names: list[str] | None = None, mappings: list[dict] | None = None) -> dict:
    return {
        "canonical_team_id": team_id,
        "canonical_name": name,
        "competition_scope": ["competition:alpha"],
        "country": "Fixtureland",
        "canonical_source_names": source_names or [],
        "reviewed_aliases": aliases or [],
        "provider_mappings": mappings or [],
    }


def test_stable_provider_id_is_reused_before_a_conflicting_name():
    value = registry(
        team(
            "team:alpha:one",
            "Alpha One",
            mappings=[{
                "provider": "nowscore",
                "provider_team_id": "17",
                "provider_exact_name": "Alpha Old",
                "competition_id": "competition:alpha",
                "verified": True,
            }],
        ),
        team(
            "team:alpha:two",
            "Alpha Two",
            mappings=[{
                "provider": "nowscore",
                "provider_team_id": "99",
                "provider_exact_name": "Alpha Old",
                "competition_id": "competition:alpha",
                "verified": True,
            }],
        ),
    )

    result = IdentityRegistryResolver(value).resolve_side(
        competition_id="competition:alpha",
        provider="nowscore",
        provider_team_id="17",
        provider_team_name="Alpha Old",
    )

    assert result["resolution_status"] == "AUTO_RESOLVED"
    assert result["canonical_team_id"] == "team:alpha:one"
    assert result["resolution_method"] == "stable_provider_id_crosswalk"


def test_ambiguous_stable_provider_id_fails_closed():
    value = registry(
        team("team:alpha:one", "Alpha One", mappings=[{
            "provider": "nowscore",
            "provider_team_id": "17",
            "provider_exact_name": "Alpha",
            "competition_id": "competition:alpha",
            "verified": True,
        }]),
        team("team:alpha:two", "Alpha Two", mappings=[{
            "provider": "nowscore",
            "provider_team_id": "17",
            "provider_exact_name": "Alpha",
            "competition_id": "competition:alpha",
            "verified": True,
        }]),
    )

    result = IdentityRegistryResolver(value).resolve_side(
        competition_id="competition:alpha",
        provider="nowscore",
        provider_team_id="17",
        provider_team_name="Alpha",
    )

    assert result["resolution_status"] == "AMBIGUOUS"
    assert result["canonical_team_id"] is None
    assert result["candidate_team_ids"] == ["team:alpha:one", "team:alpha:two"]


def test_ladder_uses_reviewed_provider_name_fixture_id_exact_name_then_alias():
    value = registry(
        team(
            "team:alpha:one",
            "Alpha One",
            aliases=["The Alpha"],
            source_names=["Alpha Source"],
            mappings=[{
                "provider": "500",
                "provider_team_id": None,
                "provider_exact_name": "Alpha Provider",
                "competition_id": "competition:alpha",
                "verified": True,
            }],
        )
    )
    resolver = IdentityRegistryResolver(value)

    assert resolver.resolve_side(
        competition_id="competition:alpha", provider="500", provider_team_name="Alpha Provider"
    )["resolution_method"] == "reviewed_canonical_provider_crosswalk"
    assert resolver.resolve_side(
        competition_id="competition:alpha", provider="unknown", fixture_canonical_team_id="team:alpha:one"
    )["resolution_method"] == "fixture_canonical_id"
    assert resolver.resolve_side(
        competition_id="competition:alpha", provider="unknown", provider_team_name="Alpha Source"
    )["resolution_method"] == "competition_exact_normalized_name"
    assert resolver.resolve_side(
        competition_id="competition:alpha", provider="unknown", provider_team_name="The Alpha"
    )["resolution_method"] == "competition_reviewed_alias"


def test_exact_name_and_alias_are_competition_scoped_and_ambiguous_names_fail_closed():
    value = {
        **registry(
            team("team:alpha:one", "United", source_names=["United"], aliases=["Utd"]),
            team("team:alpha:two", "United Reserve", source_names=["United"], aliases=["Utd"]),
        ),
        "teams": [
            {**team("team:alpha:one", "United", source_names=["United"], aliases=["Utd"]), "competition_scope": ["competition:alpha"]},
            {**team("team:alpha:two", "United Reserve", source_names=["United"], aliases=["Utd"]), "competition_scope": ["competition:alpha"]},
        ],
    }

    result = IdentityRegistryResolver(value).resolve_side(
        competition_id="competition:alpha", provider="unknown", provider_team_name="United"
    )

    assert result["resolution_status"] == "AMBIGUOUS"
    assert result["resolution_method"] == "competition_exact_normalized_name"
    assert result["candidate_team_ids"] == ["team:alpha:one", "team:alpha:two"]


def test_unmatched_near_name_is_not_fuzzy_resolved():
    value = registry(team("team:alpha:one", "Alpha One", source_names=["Alpha One"]))

    result = IdentityRegistryResolver(value).resolve_side(
        competition_id="competition:alpha", provider="unknown", provider_team_name="Alpha Oen"
    )

    assert result["resolution_status"] == "UNRESOLVED"
    assert result["canonical_team_id"] is None


def test_fixture_source_labels_can_reuse_a_reviewed_provider_crosswalk():
    value = registry(
        team("team:alpha:one", "Alpha One", mappings=[{
            "provider": "nowscore",
            "provider_team_id": "17",
            "provider_exact_name": "Alpha One",
            "competition_id": "competition:alpha",
            "verified": True,
        }]),
        team("team:alpha:two", "Alpha Two", mappings=[{
            "provider": "nowscore",
            "provider_team_id": "18",
            "provider_exact_name": "Alpha Two",
            "competition_id": "competition:alpha",
            "verified": True,
        }]),
    )

    result = IdentityRegistryResolver(value).resolve_fixture(
        {
            "matchId": "500-fixture",
            "nowscoreProviderHome": "Alpha One",
            "nowscoreProviderAway": "Alpha Two",
            "home_provider_team_id": "17",
            "away_provider_team_id": "18",
        },
        competition_id="competition:alpha",
    )

    assert result["identity_status"] == "AUTO_RESOLVED"
    assert result["home_team_id"] == "team:alpha:one"
    assert result["away_team_id"] == "team:alpha:two"


def test_builder_excludes_unverified_crosswalk_and_links_existing_reviewed_alias():
    class ReadOnlyFixtureStore:
        def dataset_digest(self) -> str:
            return "fixture-history-digest"

    def write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    records = [
        {
            "competition_id": "competition:alpha",
            "home_team_id": "team:alpha:one",
            "away_team_id": "team:alpha:opponent",
            "raw_home_team": "Alpha Local",
            "raw_away_team": "Opponent",
        }
    ]
    with __import__("tempfile").TemporaryDirectory() as temp:
        root = Path(temp)
        project = root / "project.json"
        verified = root / "verified.json"
        aliases = root / "aliases.json"
        team_registry = root / "team_registry.json"
        current = root / "current.json"
        match_crosswalk = root / "match_crosswalk.json"
        write(project, {"mappings": [
            {
                "competition": "competition:alpha",
                "canonical_team_id": "team:alpha:one",
                "canonical_name": "Alpha One",
                "provider": "nowscore",
                "provider_team_id": "17",
                "provider_team_name": "Alpha Local",
                "verified": True,
            },
            {
                "competition": "competition:alpha",
                "canonical_team_id": "team:alpha:unverified",
                "canonical_name": "Unverified",
                "provider": "nowscore",
                "provider_team_id": "99",
                "provider_team_name": "Unverified",
                "verified": False,
            },
        ]})
        write(verified, {"mappings": []})
        write(aliases, {
            "teams": [{"canonical": "Alpha Local", "aliases": ["Alpha Alias"], "evidence": "reviewed-alpha"}],
        })
        write(team_registry, {"teams": []})
        write(current, {"matches": []})
        write(match_crosswalk, {"matches": {}})

        built = IdentityRegistryBuilder(
            historical_records=records,
            historical_store=ReadOnlyFixtureStore(),
            coverage_registry={"competitions": [{"competition_id": "competition:alpha", "country": "Fixtureland"}]},
            project_crosswalk_path=project,
            verified_crosswalk_path=verified,
            team_alias_registry_path=team_registry,
            reviewed_alias_path=aliases,
            current_identity_evidence_path=current,
            provider_match_crosswalk_path=match_crosswalk,
            now=datetime(2026, 8, 30, tzinfo=timezone.utc),
        ).build()

    mappings = [mapping for row in built["teams"] for mapping in row["provider_mappings"]]
    assert {mapping["provider_team_id"] for mapping in mappings} == {"17"}
    assert built["summary"]["linked_reviewed_alias_group_count"] == 1
    resolved = IdentityRegistryResolver(built).resolve_side(
        competition_id="competition:alpha",
        provider="unknown",
        provider_team_name="Alpha Alias",
    )
    assert resolved["canonical_team_id"] == "team:alpha:one"
    assert resolved["resolution_method"] == "competition_reviewed_alias"
