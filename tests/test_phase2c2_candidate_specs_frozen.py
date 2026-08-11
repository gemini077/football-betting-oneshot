from scripts.football_data.phase2c2_opponent_strength import (
    candidate_specs_manifest,
    select_opponent_spec,
)


def test_candidate_registry_is_small_and_pre_registered():
    registry = candidate_specs_manifest()
    assert [row["regularization"] for row in registry] == [5, 10, 20]
    assert all(row["solver"] == "multiplicative_fixed_point" for row in registry)
    assert len({row["spec_id"] for row in registry}) == 3


def test_selection_rejects_unregistered_spec_results():
    rows = [{"spec_id": "not-registered", "one_x_two_log_loss": 1.0, "one_x_two_brier": 0.5, "goal_distribution_nll": 2.0}]
    try:
        select_opponent_spec(rows)
    except ValueError as exc:
        assert "unregistered" in str(exc)
    else:
        raise AssertionError("unregistered candidate must be rejected")
