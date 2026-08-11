from __future__ import annotations

import json
from pathlib import Path

from scripts.football_data.project_identity import (
    ProjectFixtureObservation,
    ProjectProviderIdentityCandidateBuilder,
    ProjectProviderIdentityResolver,
)


CANONICAL = [
    {
        "provider": "football-data.co.uk",
        "provider_team_name": "VPS",
        "canonical_name": "Vaasan PS",
        "canonical_team_id": "team:finland:vaasan-ps",
        "competition": "competition:finland-veikkausliiga",
        "country": "Finland",
        "verified": True,
        "resolution_method": "cross_source_context_verified",
    }
]

ALIASES = [
    {
        "canonical": "瓦萨",
        "aliases": ["VPS瓦萨", "VPS", "Vaasa VPS"],
        "evidence": "confirmed_nowscore_schedule_20260718",
    }
]


def _observations(names: tuple[str, ...]) -> list[ProjectFixtureObservation]:
    observations = []
    for name_index, name in enumerate(names):
        for fixture_index in (1, 2):
            observations.append(
                ProjectFixtureObservation(
                    target_match_id=f"target:vaasa-{name_index}-{fixture_index}",
                    provider="500",
                    provider_match_id=f"500-vaasa-{name_index}-{fixture_index}",
                    competition_id="competition:finland-veikkausliiga",
                    country="Finland",
                    kickoff_at=f"2026-07-{10 + name_index:02d}T12:00:00Z",
                    side="home",
                    provider_team_name=name,
                )
            )
    return observations


def test_reviewed_alias_group_propagates_every_name_to_one_canonical_team():
    results = [
        ProjectProviderIdentityCandidateBuilder(
            canonical_mappings=CANONICAL,
            project_alias_rows=ALIASES,
        ).build(_observations((name,)))
        for name in ("瓦萨", "VPS瓦萨", "VPS", "Vaasa VPS")
    ]

    assert all(result["summary"]["AUTO_VERIFIED"] == 1 for result in results)
    assert all(
        row["canonical_team_id"] == "team:finland:vaasan-ps"
        for result in results
        for row in result["provider_mappings"]
    )

    chinese_mapping = next(
        row
        for row in results[0]["provider_mappings"]
        if row["provider_team_name"] == "瓦萨"
    )
    evidence = chinese_mapping["evidence"]
    assert chinese_mapping["resolution_method"] == "project_alias_context_verified"
    assert chinese_mapping["verification_method"] == "project_alias_context_verified"
    assert evidence["reviewed_alias_group_used"] is True
    assert evidence["matched_alias_names"] == ["VPS", "VPS瓦萨"]
    assert evidence["candidate_canonical_team_ids_before_context"] == [
        "team:finland:vaasan-ps"
    ]
    assert evidence["candidate_canonical_team_ids_after_context"] == [
        "team:finland:vaasan-ps"
    ]
    assert "reviewed_project_alias" in evidence["evidence_kinds"]

    resolved = ProjectProviderIdentityResolver(
        [chinese_mapping]
    ).resolve_team(
        "500",
        "瓦萨",
        competition_id="competition:finland-veikkausliiga",
        country="Finland",
    )
    assert resolved.canonical_team_id == "team:finland:vaasan-ps"
    assert resolved.resolution_method == "project_alias_context_verified"


def test_real_reviewed_finland_alias_groups_propagate_to_canonical_source_catalog():
    root = Path(__file__).resolve().parents[1]
    alias_registry = json.loads(
        (root / "data" / "team_aliases.json").read_text(encoding="utf-8")
    )
    source_crosswalk = json.loads(
        (root / "data" / "football_data" / "verified_identity_crosswalk.json").read_text(
            encoding="utf-8"
        )
    )
    aliases = [
        row
        for row in alias_registry["teams"]
        if row.get("canonical") in {"瓦萨", "赫尔辛基火花", "库奥皮奥"}
    ]
    expected = {
        "瓦萨": "team:finland:vaasan-ps",
        "赫尔辛基火花": "team:finland:gnistan",
        "库奥皮奥": "team:finland:kuopion-ps",
    }

    for project_name, canonical_team_id in expected.items():
        result = ProjectProviderIdentityCandidateBuilder(
            canonical_mappings=source_crosswalk["mappings"],
            project_alias_rows=aliases,
        ).build(_observations((project_name,)))

        assert result["summary"]["AUTO_VERIFIED"] == 1
        assert result["provider_mappings"][0]["canonical_team_id"] == canonical_team_id
