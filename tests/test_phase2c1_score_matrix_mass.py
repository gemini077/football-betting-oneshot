from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_model import probability_payload


def test_score_matrix_and_tail_probability_cover_one():
    probabilities = probability_payload(2.1, 1.4)
    matrix_mass = sum(cell for row in probabilities["score_matrix"].values() for cell in row.values())
    assert matrix_mass + probabilities["score_matrix_tail_probability"] == pytest.approx(1.0)
