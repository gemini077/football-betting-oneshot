from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import challenger_c_current_unique_checkpoint_audit as audit  # noqa: E402


def _review_with_passed_structure() -> dict:
    return {
        "integrity": {"status": "PASS"},
        "overall_reproduction": {"status": "PASS"},
        "matching": {"result_identity_mismatches": 0},
        "discovery": {"result_identity_conflicts": 0},
    }


def test_current_checkpoint_uses_all_tracked_pair_artifacts_and_unique_units():
    latest = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
    before = hashlib.sha256(latest.read_bytes()).hexdigest()

    summary = audit.run_audit(
        source_main_sha="TEST-MAIN-SHA",
        head_sha="TEST-HEAD-SHA",
    )

    after = hashlib.sha256(latest.read_bytes()).hexdigest()
    assert after == before
    assert summary["source"]["source_main_sha"] == "TEST-MAIN-SHA"
    assert summary["current_input_state"]["tracked_pair_artifact_files"] == 400
    assert summary["current_input_state"]["latest_json_pair_rows"] == 391
    assert summary["current_input_state"]["loaded_current_pair_rows"] == 400
    assert summary["current_input_state"]["tracked_rows_absent_from_latest_json"] == 9
    assert summary["counts"]["total_pair_version_rows"] == 400
    assert summary["counts"]["promotion_eligible_pair_version_rows"] == 399
    assert summary["counts"]["verified_unique_matches"] == 30
    assert summary["checkpoint"]["status"] == "NOT_REACHED"
    assert summary["checkpoint"]["auto_promote"] is False
    assert summary["final_decision"] == "NOT_REACHED_KEEP_SHADOW"
    assert summary["production_action"] == "STOPPED_BEFORE_PROMOTION"
    assert "pairs" not in summary


def test_checkpoint_boundaries_delegate_to_existing_non_promoting_semantics():
    review = _review_with_passed_structure()
    pair_integrity = {"status": "PASS"}

    not_reached, reasons = audit._final_decision(
        audit.shadow.checkpoint_status(49),
        review,
        pair_artifact_integrity=pair_integrity,
        ambiguous_final_chronology_match_groups=0,
    )
    checkpoint, checkpoint_reasons = audit._final_decision(
        audit.shadow.checkpoint_status(50),
        review,
        pair_artifact_integrity=pair_integrity,
        ambiguous_final_chronology_match_groups=0,
    )
    promotion_ready, promotion_reasons = audit._final_decision(
        audit.shadow.checkpoint_status(100),
        review,
        pair_artifact_integrity=pair_integrity,
        ambiguous_final_chronology_match_groups=0,
    )

    assert (not_reached, reasons) == ("NOT_REACHED_KEEP_SHADOW", [])
    assert (checkpoint, checkpoint_reasons) == ("CHECKPOINT_REACHED_KEEP_SHADOW", [])
    assert (promotion_ready, promotion_reasons) == (
        "PROMOTION_REVIEW_READY_PENDING_INDEPENDENT_ACCEPTANCE",
        [],
    )


def test_ambiguous_final_chronology_fails_closed_without_promotion():
    decision, reasons = audit._final_decision(
        audit.shadow.checkpoint_status(50),
        _review_with_passed_structure(),
        pair_artifact_integrity={"status": "PASS"},
        ambiguous_final_chronology_match_groups=1,
    )

    assert decision == "FAIL_CLOSED"
    assert reasons == ["AMBIGUOUS_FINAL_CHRONOLOGY"]


def test_compact_report_keeps_current_counts_and_stop_state():
    summary = audit.run_audit(source_main_sha="TEST-MAIN-SHA", head_sha="TEST-HEAD-SHA")
    report = audit._build_report(summary)

    assert "tracked pair artifact files: `400`" in report
    assert "verified unique matches: `30`" in report
    assert "NOT_REACHED_KEEP_SHADOW" in report
    assert "DO NOT MERGE" in report
    assert len(report) < 20_000
