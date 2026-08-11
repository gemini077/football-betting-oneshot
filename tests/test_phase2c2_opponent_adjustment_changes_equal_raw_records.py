from scripts.football_data.phase2c2_opponent_strength import fit_opponent_strength
from tests.phase2c2_test_support import result


def test_opponent_adjustment_can_separate_equal_raw_attack_totals():
    rows = [
        result("a1", "2026-01-01T12:00:00Z", "team:a", "team:elite", 2, 0),
        result("a2", "2026-01-02T12:00:00Z", "team:weak", "team:a", 0, 2),
        result("b1", "2026-01-03T12:00:00Z", "team:b", "team:weak", 2, 0),
        result("b2", "2026-01-04T12:00:00Z", "team:elite", "team:b", 0, 2),
        result("e1", "2026-01-05T12:00:00Z", "team:elite", "team:weak", 3, 0),
        result("e2", "2026-01-06T12:00:00Z", "team:weak", "team:elite", 0, 2),
    ]
    fitted = fit_opponent_strength(rows, regularization=10)
    assert fitted["attack_home"]["team:a"] != fitted["attack_home"]["team:b"]
