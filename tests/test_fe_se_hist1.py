from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.football_data import fe_se_hist1 as module
from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import HistoricalResultStore


def _result(
    *,
    provider: str,
    provider_match_id: str,
    home: str = "team:sweden:aik-solna",
    away: str = "team:sweden:malmo-ff",
    home_goals: int = 1,
    away_goals: int = 0,
    kickoff: str = "2025-03-29T14:00:00Z",
) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:{module.COMPETITION_ID}:{kickoff[:10]}:{home}:{away}",
        competition_id=module.COMPETITION_ID,
        season_id=module.TARGET_SEASON_ID,
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        home_goals=home_goals,
        away_goals=away_goals,
        provider=provider,
        provider_match_id=provider_match_id,
        source_as_of_at=kickoff,
        captured_at="2026-08-29T11:17:16Z",
        source_record_ref=f"{provider}:{provider_match_id}",
        source=provider,
        source_url=f"https://example.test/{provider}",
        source_reliable=True,
        raw_home_team="AIK",
        raw_away_team="Malmo FF",
        raw_competition="Sweden Allsvenskan",
        raw_season="2025",
        resolution_status="resolved",
        resolution_method="manual_verified",
        observation_origin="provider_historical_result",
        data_license="internal test fixture",
        parser_version="test.v1",
        raw_sha256="a" * 64,
        source_file="SWE.csv",
        entity_type="club",
        match_type="league",
        verification_evidence=["test exact mapping"],
    )


def test_source_loader_uses_target_season_and_exact_supplement_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw = (
        "Country,League,Season,Date,Time,Home,Away,HG,AG\n"
        "Sweden,Allsvenskan,2025,29/03/2025,16:00,Norrkoping,Oster,2,1\n"
    ).encode("utf-8")
    raw_path = tmp_path / "SWE.csv"
    raw_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": module.SOURCE_URL,
                "source_file": module.SOURCE_FILE,
                "captured_at": "2026-08-29T11:17:16Z",
                "raw_sha256": digest,
                "sources": [
                    {
                        "competition_key": "sweden-allsvenskan",
                        "provider_competition_id": "football-data.co.uk:sweden:allsvenskan",
                        "provider_competition_name": "Sweden Allsvenskan",
                        "provider_season_id": "2025",
                        "provider_season_name": "2025",
                        "source_completeness_status": "COMPLETE",
                        "result_coverage": "SUPPORTED",
                        "listed_match_count": 1,
                        "parsed_result_count": 1,
                        "raw_sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    base_path = tmp_path / "base_identity.json"
    base_path.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "provider_team_name": "Norrkoping",
                        "canonical_team_id": "team:sweden:ifk-norrkoping",
                        "verified": True,
                        "resolution_method": "manual_verified",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    supplement_path = tmp_path / "supplement.json"
    supplement_path.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "provider_team_name": "Oster",
                        "canonical_team_id": "team:sweden:osters-if",
                        "verified": True,
                        "resolution_method": "cross_source_context_verified",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "EXPECTED_TARGET_MATCHES", 1)

    records, metadata = module.load_target_records(
        raw_path,
        manifest_path=manifest_path,
        base_identity_path=base_path,
        identity_supplement_path=supplement_path,
    )

    assert len(records) == 1
    assert records[0]["season_id"] == module.TARGET_SEASON_ID
    assert records[0]["home_team_id"] == "team:sweden:ifk-norrkoping"
    assert records[0]["away_team_id"] == "team:sweden:osters-if"
    assert records[0]["eligible_for_team_strength"] is True
    assert metadata["raw_sha256"] == digest


def test_existing_pilot_builder_preserves_requested_season_id(tmp_path: Path):
    from scripts.football_data.build_football_data_uk_pilot import load_records

    raw_path = tmp_path / "SWE.csv"
    raw_path.write_text(
        "Country,League,Season,Date,Time,Home,Away,HG,AG\n"
        "Sweden,Allsvenskan,2025,29/03/2025,16:00,AIK,Malmo FF,2,1\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": module.SOURCE_URL,
                "source_file": module.SOURCE_FILE,
                "captured_at": "2026-08-29T11:17:16Z",
                "raw_sha256": "b" * 64,
                "sources": [
                    {
                        "provider_competition_id": "football-data.co.uk:sweden:allsvenskan",
                        "provider_competition_name": "Sweden Allsvenskan",
                        "provider_season_id": "2025",
                        "provider_season_name": "2025",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "provider_team_name": "AIK",
                        "canonical_team_id": "team:sweden:aik-solna",
                        "verified": True,
                        "resolution_method": "manual_verified",
                    },
                    {
                        "provider_team_name": "Malmo FF",
                        "canonical_team_id": "team:sweden:malmo-ff",
                        "verified": True,
                        "resolution_method": "manual_verified",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    records = load_records(raw_path, manifest_path=manifest_path, identity_path=identity_path, season="2025")

    assert len(records) == 1
    assert records[0]["season_id"] == "season:sweden-allsvenskan:2025"


def test_conflicting_existing_match_fails_closed():
    existing = _result(provider="openfootball", provider_match_id="open:1")
    candidate = _result(provider="football-data.co.uk", provider_match_id="fd:1", home_goals=2)

    with pytest.raises(module.ClosureError, match="source conflict"):
        module.prepare_authoritative_records([existing], [candidate])


def test_cross_source_key_keeps_score_outside_fixture_identity():
    first = _result(provider="football-data.co.uk", provider_match_id="fd:1", home_goals=1, away_goals=0)
    second = _result(provider="openfootball", provider_match_id="open:1", home_goals=2, away_goals=0)

    assert module._cross_source_key(first) == module._cross_source_key(second)


def test_replacement_retains_cross_source_confirmation_without_duplicate():
    existing = _result(provider="openfootball", provider_match_id="open:1")
    candidate = _result(provider="football-data.co.uk", provider_match_id="fd:1")

    final, metadata = module.prepare_authoritative_records([existing], [candidate])

    assert len(final) == 1
    assert final[0]["provider"] == "football-data.co.uk"
    assert metadata["existing_overlap_count"] == 1
    assert metadata["replacement_record_count"] == 1
    assert {row["provider"] for row in final[0]["source_confirmations"]} == {"openfootball", "football-data.co.uk"}


def test_rebuild_is_idempotent_after_first_import(tmp_path: Path):
    candidate = _result(provider="football-data.co.uk", provider_match_id="fd:1")
    first, first_meta = module.prepare_authoritative_records([], [candidate])
    second, second_meta = module.prepare_authoritative_records(first, [candidate])

    assert first == second
    assert first_meta["new_record_count"] == 1
    assert second_meta["new_record_count"] == 0
    assert second_meta["same_source_existing_count"] == 1

    db_path = tmp_path / "historical_results.duckdb"
    store = HistoricalResultStore(db_path)
    store.append_many(first)
    assert store.count() == 1
    assert store.records()[0]["provider"] == "football-data.co.uk"
