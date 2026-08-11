from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_model import probability_payload


def test_probability_outputs_are_coherent():
    probabilities = probability_payload(1.7, 0.9)
    assert sum(probabilities["1x2"].values()) == pytest.approx(1.0)
    assert probabilities["totals"]["over_2_5"] + probabilities["totals"]["under_2_5"] == pytest.approx(1.0)
    assert probabilities["btts"]["yes"] + probabilities["btts"]["no"] == pytest.approx(1.0)
