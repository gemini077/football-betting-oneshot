from scripts.football_data.phase2c2_opponent_strength import (
    PHASE2C2_CONTRACT_VERSION,
    experiment_id_for,
)


def test_phase2c2_experiment_id_is_deterministic():
    kwargs = {
        "pool_digest": "pool",
        "spent_heldout_digest": "spent",
        "selected_spec": {"spec_id": "opponent:test"},
        "candidate_registry_digest": "registry",
        "historical_dataset_digest": "dataset",
    }
    assert experiment_id_for(**kwargs) == experiment_id_for(**kwargs)
    assert experiment_id_for(**kwargs).startswith("phase2c2:")
    assert PHASE2C2_CONTRACT_VERSION
