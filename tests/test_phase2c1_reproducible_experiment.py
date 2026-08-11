from __future__ import annotations

from scripts.football_data.phase2c1_experiment import experiment_id_for


def test_same_experiment_inputs_produce_same_experiment_id():
    kwargs = {
        "cohort_id": "phase2c-1:standard_recommended:cohort",
        "dataset_digest": "dataset",
        "spec": {"spec_id": "basic:last10:shrink3"},
    }
    assert experiment_id_for(**kwargs) == experiment_id_for(**kwargs)
