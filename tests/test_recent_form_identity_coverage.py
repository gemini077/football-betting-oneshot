from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import scripts.recent_form_cache as cache_module
from scripts.recent_form_cache import build_recent_form


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "football_data" / "openfootball" / "espana_source_manifest.json"
EVIDENCE_PATH = ROOT / "data" / "football_data" / "openfootball" / "espana_identity_evidence.json"
ALIAS_PATH = ROOT / "data" / "football_data" / "team_alias_registry.json"

EXPECTED_IDS = {
    "Celta Vigo": "team:spain:celta-vigo",
    "Osasuna": "team:spain:osasuna",
    "Barcelona": "team:barcelona",
    "Athletic Club": "team:spain:athletic-club",
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _raw_fixture() -> bytes:
    return (
        "= Spain Primera Division 2026/27\n"
        "Thu Aug 20 2026\n"
        "  18:00 RC Celta de Vigo v CA Osasuna 1-0\n"
        "Fri Aug 21 2026\n"
        "  18:00 CA Osasuna v RC Celta de Vigo 0-2\n"
        "Sat Aug 22 2026\n"
        "  18:00 Celta v CA Osasuna 2-2\n"
    ).encode("utf-8")


def test_current_targets_use_reviewed_exact_identity_and_no_duplicate_barcelona_entity():
    manifest = _manifest()
    targets = {row["canonical_name"]: row for row in manifest["targets"]}
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))["teams"]
    evidence_by_name = {}
    for row in evidence:
        evidence_by_name.setdefault(row["provider_team_name"], []).append(row)

    aliases = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))["teams"]
    existing_provider_ids = {}
    existing_alias_ids = {}
    for team in aliases:
        for alias in team.get("aliases", []):
            existing_alias_ids[str(alias)] = team["canonical_team_id"]
        for mapping in team.get("provider_mappings", []):
            if mapping.get("verified") is True:
                existing_provider_ids[str(mapping.get("provider_team_name") or "")] = team["canonical_team_id"]

    assert existing_provider_ids["Barcelona"] == "team:barcelona"
    assert existing_alias_ids["Barcelona"] == "team:barcelona"
    assert existing_alias_ids["FC Barcelona"] == "team:barcelona"
    assert targets["Barcelona"]["canonical_team_id"] == "team:barcelona"
    assert targets["Barcelona"]["canonical_team_id"] != "team:spain:barcelona"

    for canonical_name, canonical_id in EXPECTED_IDS.items():
        target = targets[canonical_name]
        assert target["canonical_team_id"] == canonical_id
        for provider_name in target["provider_team_names"]:
            matches = [row for row in evidence_by_name.get(provider_name, []) if row["canonical_team_id"] == canonical_id]
            assert len(matches) == 1
            assert matches[0]["verified"] is True
            assert matches[0]["resolution_method"] == "manual_verified"
            assert "spain-la-liga" in matches[0]["competition_keys"]

    new_names = {"RC Celta de Vigo", "RC Celta", "CA Osasuna", "FC Barcelona", "Athletic Club"}
    assert not any(name in existing_provider_ids for name in new_names if name != "Barcelona")
    brazil_projects = {"\u5df4\u897f\u56fd\u9645", "\u683c\u96f7\u7c73\u5965"}
    assert not any(brazil_projects.intersection(set(target.get("project_names", []))) for target in manifest["targets"])


def test_exact_provider_names_build_usable_form_and_unknown_alias_is_ignored():
    manifest = _manifest()
    targets = [row for row in manifest["targets"] if row["canonical_name"] in {"Celta Vigo", "Osasuna"}]
    sources = [{
        "source_file": "2026-27/1-liga.txt",
        "provider_season_id": "2026-27",
        "raw_text": _raw_fixture().decode("utf-8"),
    }]
    records = cache_module._build_provider_records(sources, targets)
    assert {row["team_id"] for row in records} == {EXPECTED_IDS["Celta Vigo"], EXPECTED_IDS["Osasuna"]}
    assert not any(
        row["team_id"] == EXPECTED_IDS["Celta Vigo"] and (row["raw_home"] == "Celta" or row["raw_away"] == "Celta")
        for row in records
    )

    built = build_recent_form(
        records,
        home_team_id=EXPECTED_IDS["Celta Vigo"],
        away_team_id=EXPECTED_IDS["Osasuna"],
        cutoff_at="2026-08-28T00:00:00Z",
    )
    assert built is not None
    assert built["recent_form"]["home_home"]["matches"] == 1
    assert built["recent_form"]["away_away"]["matches"] >= 1
    assert all(row["kickoff_at"] < "2026-08-28T00:00:00Z" for row in built["records"])


def test_demand_driven_cache_accepts_reviewed_target_and_fail_closes_unknown_alias(tmp_path):
    raw = _raw_fixture()
    manifest = _manifest()
    targets = [row for row in manifest["targets"] if row["canonical_name"] in {"Celta Vigo", "Osasuna"}]
    temp_manifest = {
        "contract_version": "historical_source_manifest.v1",
        "repository": "openfootball/espana",
        "commit_sha": "fixture-commit",
        "sources": [{
            "source_file": "2026-27/1-liga.txt",
            "provider_season_id": "2026-27",
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }],
        "targets": targets,
    }
    manifest_path = tmp_path / "manifest.json"
    cache_path = tmp_path / "cache.json"
    manifest_path.write_text(json.dumps(temp_manifest, ensure_ascii=False), encoding="utf-8")
    home = targets[0]["project_names"][0]
    away = targets[1]["project_names"][0]
    job = {"match_id": "fixture-1", "home": home, "away": away, "kickoff": "2026-08-28T08:00:00+08:00"}

    with patch.object(cache_module, "_github_request", return_value=raw):
        assert cache_module.refresh_recent_form_cache(
            "2026-08-27",
            jobs=[job],
            now=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
            manifest_path=manifest_path,
            cache_path=cache_path,
        ) is True
    entry = json.loads(cache_path.read_text(encoding="utf-8"))["fixtures"][0]
    assert entry["home_team_id"] == EXPECTED_IDS["Celta Vigo"]
    assert entry["away_team_id"] == EXPECTED_IDS["Osasuna"]

    unknown_cache = tmp_path / "unknown-cache.json"
    unknown_job = {**job, "match_id": "fixture-unknown", "home": "Celta"}
    with patch.object(cache_module, "_github_request", side_effect=AssertionError("unknown identity must not fetch")):
        assert cache_module.refresh_recent_form_cache(
            "2026-08-27",
            jobs=[unknown_job],
            now=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
            manifest_path=manifest_path,
            cache_path=unknown_cache,
        ) is False
    assert not unknown_cache.exists()
