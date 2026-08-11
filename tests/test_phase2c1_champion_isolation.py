from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.football_data.phase2c1_experiment import champion_evidence


EXPECTED_CORE_SHA = "064f9fa96e2995a66966c916dd9e9f600358b6c49b3ad9aa1efe9704cbdd1f15"
EXPECTED_FIXED_DIGEST = "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"


def test_phase2c1_does_not_change_champion_or_enable_features():
    evidence = champion_evidence(Path(__file__).resolve().parents[1])
    assert evidence["automatic_model_core_sha256"] == EXPECTED_CORE_SHA
    assert evidence["fixed_fixture_digest"] == EXPECTED_FIXED_DIGEST
    assert evidence["validated_for_model_true_count"] == 0
    assert evidence["champion_math_changed"] is False
