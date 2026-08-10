import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from automatic_model_core import build_automatic_model
from model_governance import build_prediction_record, model_source_fingerprint
from test_model_governance import prediction_payload


EXPECTED_CORE_SHA256 = "064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15"
EXPECTED_FIXED_DIGEST = "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"


def core_sha256():
    return hashlib.sha256((ROOT / "scripts" / "automatic_model_core.py").read_bytes()).hexdigest()


def math_digest(result):
    snapshot = {
        "probabilities": result["model"]["probabilities"],
        "lambda_home": result["model"]["lambda_home"],
        "lambda_away": result["model"]["lambda_away"],
        "score_probabilities": result["model"]["score_probabilities"],
        "unique_score": result["decisions"]["unique_score"],
        "primary_contract": result["decisions"]["primary_contract"],
        "dimension_predictions": result["model"]["dimension_predictions"],
    }
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fixed_fixture_context():
    deep = {
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
            "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
            "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 4.5, "draw": 4.0, "away": 1.7}},
            {"spf_current": {"home": 4.2, "draw": 3.8, "away": 1.72}},
        ]},
        "daxiao": {"companies": [{"current_line": 2.75}, {"current_line": 2.5}]},
    }
    return {
        "request": {"match_id": "2040514"},
        "selected_workspace_match": {"id": "2040514", "home": "涓婚槦", "away": "瀹㈤槦"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    }


def test_new_data_foundation_files_cannot_change_champion_math_or_identity(tmp_path):
    paths = [
        ROOT / "config" / "football_feature_registry.json",
        ROOT / "data" / "football_data" / "team_alias_registry.json",
        ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data" / "matches.json",
        ROOT / "data" / "football_data" / "competition_registry.json",
        ROOT / "data" / "football_data" / "player_identity_registry.json",
        ROOT / "config" / "football_data_quality.json",
        ROOT / "data" / "football_data" / "xg_normalized_snapshot.json",
    ]
    original = {path: path.read_bytes() for path in paths}
    before = build_automatic_model(fixed_fixture_context())
    before_record = build_prediction_record(prediction_payload())
    before_fingerprint = model_source_fingerprint(ROOT)
    try:
        feature = json.loads(paths[0].read_text(encoding="utf-8"))
        feature["features"].append({"feature_name": "test_only", "contract_version": "xg_snapshot.v1", "source_requirements": [], "quality_requirement": "D", "freshness_requirement": "unknown", "validated_for_model": False})
        paths[0].write_text(json.dumps(feature, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        registry = json.loads(paths[1].read_text(encoding="utf-8"))
        registry["teams"].append({"canonical_team_id": "team:test-only", "canonical_name": "Test Only", "aliases": ["Test Only"], "country": "Nowhere", "competition_context": [], "gender": "unknown", "team_level": "unknown", "provider_mappings": []})
        paths[1].write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        matches = json.loads(paths[2].read_text(encoding="utf-8"))
        matches[0]["home_score"] = 99
        paths[2].write_text(json.dumps(matches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        competition = json.loads(paths[3].read_text(encoding="utf-8"))
        competition["competitions"].append({"canonical_competition_id": "competition:test-only", "seasons": []})
        paths[3].write_text(json.dumps(competition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        players = json.loads(paths[4].read_text(encoding="utf-8"))
        players["players"].append({"canonical_player_id": "player:test-only"})
        paths[4].write_text(json.dumps(players, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        quality = json.loads(paths[5].read_text(encoding="utf-8"))
        quality["clock_skew_tolerance_seconds"] = 1
        paths[5].write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        xg = json.loads(paths[6].read_text(encoding="utf-8"))
        xg["records"].append({"provider": "other-provider", "metric_definition": "other-definition", "value": 99})
        paths[6].write_text(json.dumps(xg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        after = build_automatic_model(fixed_fixture_context())
        after_record = build_prediction_record(prediction_payload())
        assert math_digest(before) == EXPECTED_FIXED_DIGEST
        assert math_digest(after) == EXPECTED_FIXED_DIGEST
        assert core_sha256() == EXPECTED_CORE_SHA256
        assert before_fingerprint == model_source_fingerprint(ROOT)
        assert before_record["prediction_id"] == after_record["prediction_id"]
    finally:
        for path, value in original.items():
            path.write_bytes(value)
