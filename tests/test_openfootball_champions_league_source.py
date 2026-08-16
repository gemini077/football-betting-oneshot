from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.football_data.build_openfootball_pilot import load_openfootball_records
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
