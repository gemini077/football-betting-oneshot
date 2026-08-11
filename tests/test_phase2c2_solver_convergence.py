from scripts.football_data.phase2c2_opponent_strength import fit_opponent_strength
from tests.phase2c2_test_support import paired_history


def test_fixed_point_solver_converges_with_finite_strengths():
    fitted = fit_opponent_strength(paired_history(), regularization=10)
    assert fitted["converged"] is True
    assert fitted["iterations"] <= fitted["max_iterations"]
    assert all(value > 0 for value in fitted["attack_home"].values())
    assert all(value > 0 for value in fitted["defence_away"].values())
