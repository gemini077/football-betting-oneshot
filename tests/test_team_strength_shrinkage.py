from __future__ import annotations

from scripts.football_data.phase2c1_model import shrink_rate


def test_shrinkage_moves_small_sample_rate_toward_competition_mean():
    assert shrink_rate(6, 2, 0, 1.0) == 3.0
    assert 1.0 < shrink_rate(6, 2, 10, 1.0) < 3.0

