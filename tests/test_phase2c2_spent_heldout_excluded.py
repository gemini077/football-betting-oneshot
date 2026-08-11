import pytest

from scripts.football_data.phase2c2_opponent_strength import (
    assert_no_spent_heldout,
    spent_heldout_digest,
)
from tests.phase2c2_test_support import result


def test_spent_heldout_match_is_rejected_before_model_use():
    spent = {"spent-match"}
    row = result("spent-match", "2026-01-01T12:00:00Z", "team:a", "team:b")
    with pytest.raises(ValueError, match="spent-heldout"):
        assert_no_spent_heldout([row], spent)


def test_spent_heldout_digest_is_deterministic_from_ids_only():
    assert spent_heldout_digest(["b", "a", "b"]) == spent_heldout_digest(["a", "b"])
