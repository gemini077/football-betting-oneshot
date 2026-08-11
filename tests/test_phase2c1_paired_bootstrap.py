from __future__ import annotations

from scripts.football_data.phase2c1_model import paired_bootstrap_deltas


def test_paired_bootstrap_is_deterministic_for_same_fixture_pairs():
    challenger = [1.0, 2.0, 3.0, 4.0]
    baseline = [2.0, 2.0, 2.0, 2.0]
    first = paired_bootstrap_deltas(challenger, baseline, n_bootstrap=100, seed=7)
    second = paired_bootstrap_deltas(challenger, baseline, n_bootstrap=100, seed=7)
    assert first == second
    assert first["sample"] == 4
    assert first["mean_delta"] == 0.5
