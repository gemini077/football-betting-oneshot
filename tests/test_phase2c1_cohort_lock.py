from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_experiment import validate_cohort_lock


def test_cohort_lock_rejects_wrong_id_or_digest():
    with pytest.raises(ValueError, match="cohort"):
        validate_cohort_lock(
            {
                "research_cohort_id": "wrong",
                "cohort_match_id_digest": "wrong",
                "cohort_size": 688,
            }
        )
