from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from automatic_model_core import build_automatic_model
from model_governance import build_prediction_record, model_source_fingerprint
from test_champion_data_foundation_isolation import fixed_fixture_context
from test_model_governance import prediction_payload


EXPECTED_CORE_SHA256 = "6bf7d59b9a6c85c9fdb86fefc29c85fcfad5c74e0f7540e19312e708078b30e6"
EXPECTED_FIXED_DIGEST = "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"
EXPECTED_SOURCE_FINGERPRINT = "5bbad6d0fe3f17cc8a6d9175c0754d1af5720f8d96b3f3fd27bdb9075f382faf"


def digest(result: dict) -> str:
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


def fixture_context() -> dict:
    context = fixed_fixture_context()
    context["team_strength_snapshot"] = {"team_id": "team:test", "matches": 99, "validated_for_model": False}
    return context


def test_real_team_strength_data_cannot_change_champion_math_or_identity():
    before = build_automatic_model(fixture_context())
    before_record = build_prediction_record(prediction_payload())
    before_fingerprint = model_source_fingerprint(ROOT)

    changed = fixture_context()
    changed["team_strength_snapshot"]["matches"] = 0
    changed["team_strength_snapshot"]["metrics"] = {"goals_for_per_match": 99}
    after = build_automatic_model(changed)
    after_record = build_prediction_record(prediction_payload())

    assert hashlib.sha256((ROOT / "scripts" / "automatic_model_core.py").read_bytes()).hexdigest() == EXPECTED_CORE_SHA256
    assert digest(before) == EXPECTED_FIXED_DIGEST
    assert digest(after) == EXPECTED_FIXED_DIGEST
    assert before_fingerprint["fingerprint"] == EXPECTED_SOURCE_FINGERPRINT == model_source_fingerprint(ROOT)["fingerprint"]
    assert before_record["prediction_id"] == after_record["prediction_id"]
