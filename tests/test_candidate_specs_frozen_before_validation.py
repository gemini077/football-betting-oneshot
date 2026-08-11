from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_model import candidate_specs_manifest, select_spec


def test_candidate_registry_is_stable_and_validation_cannot_add_spec():
    registry = candidate_specs_manifest()
    assert len(registry) >= 3
    assert candidate_specs_manifest() == registry

    with pytest.raises(ValueError, match="registered"):
        select_spec([{"spec_id": "not-registered", "one_x_two_log_loss": 0.1}], registry)
