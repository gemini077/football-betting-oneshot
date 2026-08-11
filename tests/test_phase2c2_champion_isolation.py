import hashlib
from pathlib import Path

from scripts.football_data.phase2c2_opponent_strength import OpponentSpec, build_opponent_adjusted_prediction
from tests.phase2c2_test_support import paired_history, target


ROOT = Path(__file__).resolve().parents[1]


def test_opponent_research_does_not_change_champion_core_or_validate_features():
    core_sha = hashlib.sha256((ROOT / "scripts" / "automatic_model_core.py").read_bytes()).hexdigest()
    assert core_sha == "064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15"
    prediction = build_opponent_adjusted_prediction(target(), paired_history(), OpponentSpec(regularization=10))
    assert prediction["validated_for_model"] is False
