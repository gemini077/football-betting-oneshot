import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from exact_distribution_family_shadow_benchmark import (  # noqa: E402
    FIXED_COHORT_COUNT,
    FAMILIES,
    MIN_TRAINING_UNIQUE_MATCHES,
    run_benchmark,
)


def test_fixed_manifest_is_exactly_the_accepted_107_match_authority():
    path = ROOT / "artifacts" / "exact-distribution-family-shadow-benchmark-1" / "fixed_107_manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document["rows"]
    assert document["cohort_match_count"] == FIXED_COHORT_COUNT == 107
    assert len(rows) == FIXED_COHORT_COUNT
    assert len({row["pair_id"] for row in rows}) == FIXED_COHORT_COUNT
    assert len({row["match_id"] for row in rows}) == FIXED_COHORT_COUNT


def test_training_authority_fails_closed_before_family_scoring():
    evidence = run_benchmark()

    assert evidence["milestone"] == "EXACT-DISTRIBUTION-FAMILY-SHADOW-BENCHMARK-1"
    assert evidence["fixed_cohort"]["status"] == "PASS"
    assert evidence["fixed_cohort"]["verified_match_count"] == 107
    assert evidence["training_chronology"]["strictly_earlier_than_evaluation"] is True
    assert evidence["training_chronology"]["evaluation_identity_overlap_unique_matches"] == 0
    assert evidence["training_unique_matches"] == 1
    assert evidence["training_unique_matches"] < MIN_TRAINING_UNIQUE_MATCHES
    assert evidence["decision"] == "FAIL_CLOSED_TRAINING_AUTHORITY"
    assert evidence["training_authority"]["fit_on_evaluation_cohort"] is False
    assert evidence["training_authority"]["scoring_attempted"] is False
    assert evidence["integrity_status"] == "PASS"


def test_all_family_outputs_are_unscored_when_training_authority_is_missing():
    evidence = run_benchmark()

    for family in FAMILIES:
        assert evidence["families"][family]["status"] == "NOT_EVALUATED"
        assert evidence["families"][family]["exact_nll"] is None
    assert evidence["POISSON_EXACT_NLL"] is None
    assert evidence["DC_EXACT_NLL"] is None
    assert evidence["NB_EXACT_NLL"] is None
    assert evidence["DC_DELTA_CI"] is None
    assert evidence["NB_DELTA_CI"] is None
    assert evidence["BEST_SUPPORTED_FAMILY"] is None
    assert evidence["1X2_SAFETY"] == "NOT_EVALUATED_TRAINING_AUTHORITY"
