from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.football_data.build_openfootball_pilot import load_openfootball_records
from scripts.football_data.build_id2_v3_staging import _source_rows_with_raw_team
from scripts.football_data.competition_resolution import CompetitionEntityResolver


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "football_data" / "openfootball" / "champions_league_source_manifest.json"


def test_champions_league_manifest_is_pinned_and_europa_mapping_is_reviewed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["repository"] == "openfootball/champions-league"
    assert len(manifest["commit_sha"]) == 40
    source = next(item for item in manifest["sources"] if item["source_file"] == "2025-26/elq.txt")
    assert source["canonical_competition_id"] == "competition:uefa-europa-league"
    assert source["raw_sha256"]

    resolution = CompetitionEntityResolver().resolve(
        provider="openfootball",
        provider_competition_id=source["provider_competition_id"],
        provider_competition_name=source["provider_competition_name"],
        provider_season_id=source["provider_season_id"],
        provider_season_name=source["provider_season_name"],
    )
    assert resolution.resolution_status == "resolved"
    assert resolution.canonical_competition_id == "competition:uefa-europa-league"


def test_openfootball_loader_validates_raw_sha_and_excludes_post_cutoff_rows(tmp_path):
    raw = """= UEFA Europa League - Quali 2025/26

Thu Jul 10 2025
  17:00  Team Alpha (AAA) v Team Beta (BBB) 1-0

Thu Aug 15 2025
  17:00  Team Alpha (AAA) v Team Beta (BBB) 2-0
"""
    raw_bytes = raw.encode("utf-8")
    source_file = "2025-26/elq.txt"
    (tmp_path / source_file).parent.mkdir(parents=True)
    (tmp_path / source_file).write_bytes(raw_bytes)
    manifest = {
        "contract_version": "historical_source_manifest.v1",
        "provider": "openfootball",
        "repository": "openfootball/champions-league",
        "commit_sha": "a" * 40,
        "captured_at": "2026-08-16T00:00:00Z",
        "sources": [{
            "source_file": source_file,
            "canonical_competition_id": "competition:uefa-europa-league",
            "competition_key": "uefa-europa-league",
            "provider_competition_id": "champions-league:el",
            "provider_competition_name": "UEFA Europa League",
            "provider_season_id": "2025-26",
            "provider_season_name": "2025/26",
            "canonical_season_id": "season:uefa-europa-league:2025-26",
            "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    identities = {
        "teams": [
            {"provider_team_name": "Team Alpha", "canonical_team_id": "team:alpha", "verified": True, "resolution_method": "manual_verified"},
            {"provider_team_name": "Team Beta", "canonical_team_id": "team:beta", "verified": True, "resolution_method": "manual_verified"},
        ]
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identities), encoding="utf-8")

    records = load_openfootball_records(
        tmp_path,
        manifest_path=manifest_path,
        identity_path=identity_path,
        cutoff_at="2025-08-14T17:00:00Z",
    )
    assert len(records) == 1
    assert records[0]["competition_id"] == "competition:uefa-europa-league"
    assert records[0]["season_id"] == "season:uefa-europa-league:2025-26"
    assert records[0]["provenance"]["commit_sha"] == "a" * 40
    assert records[0]["provenance"]["raw_sha256"] == hashlib.sha256(raw_bytes).hexdigest()


def test_benfica_has_one_authoritative_canonical_id_across_governed_providers():
    openfootball = json.loads((ROOT / "data" / "football_data" / "openfootball" / "identity_evidence.json").read_text(encoding="utf-8"))
    crosswalk = json.loads((ROOT / "data" / "football_data" / "verified_identity_crosswalk.json").read_text(encoding="utf-8"))
    expected = "team:portugal:sport-lisboa-e-benfica"
    openfootball_ids = {
        row["canonical_team_id"]
        for row in openfootball["teams"]
        if row["provider_team_name"] == "Sport Lisboa e Benfica"
    }
    crosswalk_ids = {
        row["canonical_team_id"]
        for row in crosswalk["mappings"]
        if row["provider_team_name"] in {"Benfica", "Sport Lisboa e Benfica"}
    }
    assert openfootball_ids == {expected}
    assert crosswalk_ids == {expected}


def test_champions_league_identity_evidence_keeps_unproven_source_aliases_unresolved():
    evidence = json.loads((ROOT / "data" / "football_data" / "openfootball" / "champions_league_identity_evidence.json").read_text(encoding="utf-8"))
    mappings = {row["provider_team_name"]: row["canonical_team_id"] for row in evidence["teams"]}
    assert mappings["SL Benfica (POR)"] == "team:portugal:sport-lisboa-e-benfica"
    assert mappings["Paphos FC (CYP)"] == "team:cyprus:pafos-fc"
    assert "RB Salzburg (AUT)" not in mappings
    assert "PAOK Saloniki (GRE)" not in mappings


def test_id2_builder_uses_actual_raw_team_fields_for_hearts_rows():
    rows = [
        {
            "raw_home_team": "Viktoria Plzeň (CZE)",
            "raw_away_team": "Heart of Midlothian (SCO)",
            "home_team_id": None,
            "away_team_id": "team:scotland:heart-of-midlothian-fc",
            "competition_id": "competition:uefa-europa-league",
            "eligible_for_team_strength": False,
        }
    ]
    selected = _source_rows_with_raw_team(rows, "Heart of Midlothian (SCO)")
    assert len(selected) == 1
    assert selected[0]["raw_away_team"] == "Heart of Midlothian (SCO)"


def test_viktoria_plzen_uses_exact_official_uefa_identity_evidence():
    evidence = json.loads((ROOT / "data" / "football_data" / "openfootball" / "champions_league_identity_evidence.json").read_text(encoding="utf-8"))
    mappings = {row["provider_team_name"]: row["canonical_team_id"] for row in evidence["teams"]}
    assert mappings["Viktoria Plzeň (CZE)"] == "team:czechia:fc-viktoria-plzen"
    viktoria = next(row for row in evidence["teams"] if row["provider_team_name"] == "Viktoria Plzeň (CZE)")
    assert viktoria["official_uefa_team_id"] == "64388"
    assert viktoria["canonical_id_status"] == "newly_minted_from_official_uefa_team_id"
    assert any("2024-25/elq.txt:lines:88,105" in ref for ref in viktoria["verification_evidence"])


def test_uefa_fixture_manifest_is_valid_utf8_json_and_has_one_verified_target():
    manifest_path = ROOT / "data" / "football_data" / "uefa_europa_2026_27_fixture_identity_evidence.json"
    manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    fixtures = manifest["fixtures"]
    assert len(fixtures) == 4
    assert all(row["production_competition_label"] == "欧罗巴联赛" for row in fixtures)
    verified = [row for row in fixtures if row["bridge_status"] == "VERIFIED_CROSS_SOURCE_FIXTURE"]
    assert [row["production_match_id"] for row in verified] == ["500-1460786"]
    viktoria = manifest["captures"]["teams"]["64388"]
    assert viktoria["raw_sha256"] == "1a80e0c55d6f137e105589dbb1222756dd34eaa3a4e50f6c0508b1048d55da86"
    assert viktoria["europa_club_raw_sha256"] == "16e9212f633d279166077e08beb0b34211679dc44d654137a07bb671fa42a4f5"


def test_hearts_europa_rows_resolve_both_teams_and_are_eligible(tmp_path):
    raw = """= UEFA Europa League - Quali 2024/25\n\nThu Aug 22 2024\n           Viktoria Plzeň (CZE) v Heart of Midlothian (SCO) 1-0\n\nThu Aug 29 2024\n           Heart of Midlothian (SCO) v Viktoria Plzeň (CZE) 0-1\n"""
    raw_bytes = raw.encode("utf-8")
    source_file = "2024-25/elq.txt"
    (tmp_path / source_file).parent.mkdir(parents=True)
    (tmp_path / source_file).write_bytes(raw_bytes)
    manifest = {
        "contract_version": "historical_source_manifest.v1", "provider": "openfootball",
        "repository": "openfootball/champions-league", "commit_sha": "a" * 40,
        "captured_at": "2026-08-16T00:00:00Z", "sources": [{
            "source_file": source_file, "canonical_competition_id": "competition:uefa-europa-league",
            "competition_key": "uefa-europa-league", "provider_competition_id": "champions-league:el",
            "provider_competition_name": "UEFA Europa League", "provider_season_id": "2024-25",
            "provider_season_name": "2024/25", "canonical_season_id": "season:uefa-europa-league:2024-25",
            "raw_sha256": hashlib.sha256(raw_bytes).hexdigest()
        }]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    identities = json.loads((ROOT / "data" / "football_data" / "openfootball" / "champions_league_identity_evidence.json").read_text(encoding="utf-8"))
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identities, ensure_ascii=False), encoding="utf-8")
    records = load_openfootball_records(tmp_path, manifest_path=manifest_path, identity_path=identity_path)
    hearts = [row for row in records if "Heart of Midlothian (SCO)" in {row["raw_home_team"], row["raw_away_team"]}]
    assert len(hearts) == 2
    assert all(row["home_team_id"] and row["away_team_id"] for row in hearts)
    assert all(row["eligible_for_team_strength"] is True for row in hearts)
