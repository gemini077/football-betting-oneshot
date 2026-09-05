from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decision_packet_coverage_audit as audit


def version_record(
    prediction_id: str,
    freeze_at: str,
    *,
    kickoff_at: str = "2026-01-01T12:00:00+08:00",
) -> dict:
    return {
        "prediction_id": prediction_id,
        "match_key": "MATCH-1",
        "match_identity": {
            "match_key": "MATCH-1",
            "home": "HOME",
            "away": "AWAY",
        },
        "source_cutoff_at": "2026-01-01T08:00:00+08:00",
        "prediction_created_at": "2026-01-01T09:00:00+08:00",
        "freeze_created_at": freeze_at,
        "kickoff_at": kickoff_at,
        "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
        "score_top1": "1-0",
        "score_top3": ["1-0", "1-1", "0-0"],
        "score_distribution": [
            {"score": "1-0", "probability": 0.2},
            {"score": "1-1", "probability": 0.15},
            {"score": "0-0", "probability": 0.1},
        ],
    }


def test_version_rows_do_not_inflate_unique_match_count() -> None:
    rows = [
        version_record("v1", "2026-01-01T09:01:00+08:00"),
        version_record("v2", "2026-01-01T10:01:00+08:00"),
    ]

    assert len(rows) == 2
    assert len({audit.record_match_key(row) for row in rows}) == 1
    assert audit.select_latest_legal_version(rows)["prediction_id"] == "v2"


def test_postmatch_evidence_cannot_select_prematch_version() -> None:
    legal_early = version_record("early", "2026-01-01T09:01:00+08:00")
    legal_late = version_record("late", "2026-01-01T10:01:00+08:00")
    postmatch = version_record(
        "postmatch",
        "2026-01-01T13:00:00+08:00",
    )
    postmatch["actual_score"] = "9-9"

    selected = audit.select_latest_legal_version([legal_early, legal_late, postmatch])

    assert selected["prediction_id"] == "late"
    assert audit.legal_version_reason(postmatch) == "PREMATCH_CHRONOLOGY_VIOLATION"


def test_missing_or_naive_timestamps_fail_closed_for_horizon() -> None:
    missing = version_record("missing", "")
    naive = version_record("naive", "2026-01-01T09:00:00")

    assert audit.safe_horizon_minutes(missing) == (None, "MISSING_OR_UNSAFE_KICKOFF_OR_FREEZE_TIMESTAMP")
    assert audit.safe_horizon_minutes(naive) == (None, "MISSING_OR_UNSAFE_KICKOFF_OR_FREEZE_TIMESTAMP")


def test_collector_or_lineup_status_does_not_count_as_frozen_publication() -> None:
    record = {"lineup_status": "published"}
    snapshot = {
        "input": {
            "prematch_fundamentals": {
                "lineup_collector": {"status": "published"},
            }
        }
    }

    present, reason = audit.field_presence(
        "lineup_publication", record, snapshot=snapshot
    )

    assert not present
    assert reason == "NO_FROZEN_LINEUP_PUBLICATION_RECORD"


def test_previous_comparable_is_chronology_safe_and_prematch_only() -> None:
    early = version_record("early", "2026-01-01T09:01:00+08:00")
    late = version_record("late", "2026-01-01T10:01:00+08:00")
    after_kickoff = version_record("after", "2026-01-01T13:01:00+08:00")
    after_kickoff["actual_score"] = "4-0"

    with patch.object(
        audit,
        "load_snapshot_for_record",
        return_value=({"input": {}}, None),
    ):
        result, failures = audit.build_change_awareness(
            {"MATCH-1": [early, late, after_kickoff]},
            ROOT / "data" / "model_governance" / "input_snapshots",
            {},
            {"MATCH-1": "Competition"},
        )

    assert any("after:PREMATCH_CHRONOLOGY_VIOLATION" in failure for failure in failures)
    assert result["unique_matches_with_multiple_legal_prematch_versions"] == 1
    assert result["safe_previous_comparable_matches"] == 1
    assert result["match_details"][0]["previous_version_id"] == "early"
    assert result["match_details"][0]["current_version_id"] == "late"


def test_missing_reasons_are_exhaustive_for_every_audited_field() -> None:
    observation = {
        "match_key": "MATCH-1",
        "record": {},
        "snapshot": None,
        "context": {
            "competition": "UNKNOWN",
            "provider": "UNKNOWN",
            "source": "UNKNOWN",
            "data_grade": "UNKNOWN",
            "settlement_status": "CURRENT_UNSETTLED",
            "horizon_minutes": None,
            "horizon_missing_reason": "HORIZON_NOT_SAFE_TO_COMPUTE",
        },
    }

    coverage = audit.build_field_coverage([observation])

    for field in coverage:
        overall = field["overall"]
        assert overall["eligible_unique_matches"] == (
            overall["present_unique_matches"]
            + sum(overall["missing_reasons"].values())
        )


@pytest.mark.parametrize(
    ("ratio", "label"),
    [
        (0.95, "UNIVERSAL"),
        (0.949999, "BROAD"),
        (0.80, "BROAD"),
        (0.799999, "PARTIAL"),
        (0.50, "PARTIAL"),
        (0.499999, "SPARSE"),
    ],
)
def test_coverage_labels_use_fixed_boundaries(ratio: float, label: str) -> None:
    assert audit.coverage_label(ratio) == label


def test_protected_truth_directories_are_not_valid_audit_outputs() -> None:
    with pytest.raises(ValueError):
        audit.safe_output_dir(ROOT, ROOT / "data" / "model_governance")


def test_audit_helpers_do_not_mutate_frozen_record_input() -> None:
    record = version_record("v1", "2026-01-01T09:01:00+08:00")
    before = deepcopy(record)

    audit.safe_horizon_minutes(record)
    audit.field_presence("frozen_1x2", record)
    audit.select_latest_legal_version([record])

    assert record == before
