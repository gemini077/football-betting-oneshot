from __future__ import annotations

import pytest

from scripts.football_data.data_home import resolve_football_data_home
from scripts.football_data.phase2c1_experiment import (
    EXPECTED_COHORT_ID,
    EXPECTED_COHORT_SIZE,
    EXPECTED_COHORT_MATCH_DIGEST,
    EXPECTED_SELECTED_SPEC_ID,
    EXPECTED_HELDOUT_PREDICTION_DIGEST,
    load_locked_heldout_predictions,
    recompute_locked_heldout_metrics,
)
from scripts.football_data.verify_data_home import verify_data_home


def _require_shared_artifact():
    if verify_data_home().get("status") != "OK":
        pytest.skip("shared Football Data Home unavailable; locked held-out recompute not executed")


def test_metrics_only_recompute_validates_locked_prediction_digest():
    _require_shared_artifact()
    locked = load_locked_heldout_predictions()
    assert locked["cohort_id"] == EXPECTED_COHORT_ID
    assert locked["cohort_match_id_digest"] == EXPECTED_COHORT_MATCH_DIGEST
    assert locked["cohort_size"] == EXPECTED_COHORT_SIZE
    assert locked["selected_spec_id"] == EXPECTED_SELECTED_SPEC_ID
    assert locked["prediction_digest"] == EXPECTED_HELDOUT_PREDICTION_DIGEST
    assert len(locked["team_strength"]) == 144
    result = recompute_locked_heldout_metrics(write=False)
    assert result["artifact_digests"]["heldout_prediction"] == EXPECTED_HELDOUT_PREDICTION_DIGEST

