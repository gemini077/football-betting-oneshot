from scripts.football_data.phase2c2_opponent_strength import fit_opponent_strength
from tests.phase2c2_test_support import result


def test_larger_regularization_shrinks_strength_toward_one():
    rows = [
        result("r1", "2026-01-01T12:00:00Z", "team:extreme", "team:opponent", 8, 0),
        result("r2", "2026-01-02T12:00:00Z", "team:opponent", "team:extreme", 0, 0),
    ]
    weak = fit_opponent_strength(rows, regularization=5)["attack_home"]["team:extreme"]
    strong = fit_opponent_strength(rows, regularization=20)["attack_home"]["team:extreme"]
    assert abs(strong - 1.0) < abs(weak - 1.0)
