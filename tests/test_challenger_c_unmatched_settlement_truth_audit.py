from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import challenger_c_unmatched_settlement_truth_audit as audit  # noqa: E402


SNAPSHOT = "2026-09-04T12:00:00+08:00"


def _pair(
    match_id: str = "M-1",
    *,
    match_key: str = "FBOS-202609010100-test000001",
    pair_id: str = "MS-SHADOW-PAIR-test-1",
    source_cutoff: str = "2026-09-01T00:00:00+08:00",
    kickoff: str = "2026-09-01T01:00:00+08:00",
) -> dict:
    return {
        "schema_version": "market_side_shadow_1.paired_capture.v1",
        "pair_id": pair_id,
        "pair_status": "PAIRED",
        "promotion_eligible": True,
        "match_id": match_id,
        "match_key": match_key,
        "kickoff_at": kickoff,
        "source_cutoff": source_cutoff,
        "freeze_created_at": (
            datetime.fromisoformat(source_cutoff)
            + timedelta(minutes=1)
        ).isoformat(),
        "frozen_input_digest": f"digest-{pair_id}",
        "challenger_prediction_id": f"shadow-c:{pair_id}",
        "champion_prediction_id": f"champion:{pair_id}",
        "same_fixture": True,
        "champion_preserved": True,
        "post_match_input_used_for_generation": False,
        "integrity": {
            "same_match_id": True,
            "same_source_cutoff": True,
            "same_freeze_eligibility": True,
            "same_frozen_input_digest": True,
        },
    }


def _write_pair(root: Path, pair: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{pair['pair_id']}.json").write_text(
        json.dumps(pair), encoding="utf-8"
    )


def _write_result(
    root: Path,
    pair: dict,
    *,
    score: str = "1-0",
    result_match_id: str | None = None,
    scope: str = "regulation_90m_plus_stoppage",
    verified_at: str = "2026-09-01T02:00:00+08:00",
    use_legacy_score_fields: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    home, away = (int(value) for value in score.split("-", 1))
    result = {
        "status": "result_verified",
        "match_key": pair["match_key"],
        "prediction_match_id": result_match_id or pair["match_id"],
        "kickoff_local": pair["kickoff_at"],
        "verified_at": verified_at,
        "scope": scope,
    }
    if use_legacy_score_fields:
        result.update({"home_score": home, "away_score": away})
    else:
        result["score_90m"] = score
    (root / f"{pair['match_key']}.json").write_text(
        json.dumps(result), encoding="utf-8"
    )


def _cohort(tmp_path: Path, pairs: list[dict], result_pairs: list[dict] | None = None, *, result_kwargs: dict | None = None) -> dict:
    pair_root = tmp_path / "pairs"
    result_root = tmp_path / "results"
    for pair in pairs:
        _write_pair(pair_root, pair)
    for pair in result_pairs or []:
        _write_result(result_root, pair, **(result_kwargs or {}))
    return audit._cohort(
        "TEST",
        pair_root=pair_root,
        result_root=result_root,
        snapshot_at=audit._utc(SNAPSHOT),
    )


def test_multiple_version_rows_count_once_and_select_latest_legal_representative(tmp_path):
    older = _pair(pair_id="MS-SHADOW-PAIR-old")
    newer = _pair(
        pair_id="MS-SHADOW-PAIR-new",
        source_cutoff="2026-09-01T00:30:00+08:00",
    )

    cohort = _cohort(tmp_path, [older, newer])

    assert cohort["counts"]["total_pair_version_rows"] == 2
    assert cohort["counts"]["promotion_eligible_unique_matches"] == 1
    assert cohort["counts"]["verified_unique_matches"] == 0
    assert cohort["unmatched_unique"][0]["selected_representative"]["pair_id"] == newer["pair_id"]


def test_future_match_is_future_not_due(tmp_path):
    pair = _pair(
        kickoff="2026-09-05T01:00:00+08:00",
        source_cutoff="2026-09-04T00:00:00+08:00",
    )

    cohort = _cohort(tmp_path, [pair])

    assert cohort["unmatched_unique"][0]["reason"] == "FUTURE_NOT_DUE"
    assert cohort["unmatched_unique"][0]["future_relative_to_snapshot"] is True


def test_past_match_without_authoritative_result_is_past_result_missing(tmp_path):
    pair = _pair()

    cohort = _cohort(tmp_path, [pair])

    assert cohort["unmatched_unique"][0]["reason"] == "PAST_RESULT_MISSING"
    assert cohort["unmatched_unique"][0]["result_evidence"]["file_exists"] is False


def test_valid_exact_result_with_score_90m_is_recoverable_without_rewriting(tmp_path):
    pair = _pair()

    cohort = _cohort(tmp_path, [pair], [pair])
    row = cohort["unmatched_unique"][0]

    assert row["reason"] == "RESULT_PRESENT_RECOVERABLE_LINKAGE"
    assert row["result_evidence"]["integrity_status"] == "VALID_90M_EXACT_IDENTITY"
    assert row["result_evidence"]["result_90m"] == "1-0"
    assert row["result_evidence"]["existing_matcher_actual"] is None
    assert row["result_evidence"]["counterfactual_actual"] == [1, 0]


def test_invalid_result_cannot_be_recoverable(tmp_path):
    pair = _pair()

    cohort = _cohort(
        tmp_path,
        [pair],
        [pair],
        result_kwargs={"scope": "after_extra_time"},
    )

    assert cohort["unmatched_unique"][0]["reason"] == "RESULT_PRESENT_INVALID"


def test_identity_conflict_fails_closed(tmp_path):
    pair = _pair()

    cohort = _cohort(
        tmp_path,
        [pair],
        [pair],
        result_kwargs={"result_match_id": "OTHER-MATCH"},
    )

    assert cohort["unmatched_unique"][0]["reason"] == "RESULT_PRESENT_IDENTITY_CONFLICT"


def test_legacy_result_shape_is_already_verified_not_recoverable(tmp_path):
    pair = _pair()
    pair_root = tmp_path / "pairs"
    result_root = tmp_path / "results"
    _write_pair(pair_root, pair)
    _write_result(result_root, pair, use_legacy_score_fields=True)

    cohort = audit._cohort(
        "TEST",
        pair_root=pair_root,
        result_root=result_root,
        snapshot_at=audit._utc(SNAPSHOT),
    )

    assert cohort["counts"]["verified_unique_matches"] == 1
    assert cohort["unmatched_unique"] == []


def test_final_decision_uses_only_issue_172_four_decisions():
    passed = {"status": "PASS"}

    current = {
        "counts": {"verified_unique_matches": 30},
        "reason_counts": {"RESULT_PRESENT_RECOVERABLE_LINKAGE": 26},
    }
    decision, recoverable, after = audit._decision(
        baseline_reproduction=passed,
        current=current,
    )
    assert (decision, recoverable, after) == ("SETTLEMENT_GAP_MATERIAL", 26, 56)

    current["reason_counts"] = {"RESULT_PRESENT_RECOVERABLE_LINKAGE": 10}
    decision, _, after = audit._decision(baseline_reproduction=passed, current=current)
    assert (decision, after) == ("PARTIAL_SETTLEMENT_GAP_NOT_CHECKPOINT", 40)

    current["reason_counts"] = {"FUTURE_NOT_DUE": 1, "PAST_RESULT_MISSING": 1}
    decision, recoverable, after = audit._decision(baseline_reproduction=passed, current=current)
    assert (decision, recoverable, after) == ("SAMPLE_GENUINELY_NOT_REACHED", 0, 30)

    current["reason_counts"] = {"UNKNOWN_FAIL_CLOSED": 1}
    decision, _, _ = audit._decision(baseline_reproduction=passed, current=current)
    assert decision == "FAIL_CLOSED"
    assert decision in audit.FINAL_DECISIONS


def test_audit_reads_only_sources_and_has_no_network_or_fuzzy_linkage_path(tmp_path):
    pair = _pair()
    pair_root = tmp_path / "pairs"
    result_root = tmp_path / "results"
    _write_pair(pair_root, pair)
    _write_result(result_root, pair)
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [pair_root / f"{pair['pair_id']}.json", result_root / f"{pair['match_key']}.json"]
    }

    cohort = _cohort(tmp_path, [pair], [pair])

    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
    source = (ROOT / "scripts" / "challenger_c_unmatched_settlement_truth_audit.py").read_text(encoding="utf-8").lower()
    assert cohort["unmatched_unique"]
    assert after == before
    assert "urllib" not in source
    assert "requests" not in source
    assert "urlopen" not in source
    assert "fuzzy_match(" not in source
    assert "rapidfuzz" not in source


def test_current_delta_maps_added_unique_and_natural_result_artifacts():
    baseline = {
        "counts": {
            "total_pair_version_rows": 400,
            "promotion_eligible_pair_version_rows": 399,
            "promotion_eligible_unique_matches": 70,
            "verified_pair_version_rows": 118,
            "verified_unique_matches": 30,
            "unmatched_eligible_unique_matches": 40,
        },
        "groups_by_match_key": {
            "K-1": {"selected_pair_id": "P-1", "verified": False},
        },
        "unmatched_unique": [
            {
                "match_key": "K-1",
                "reason": "PAST_RESULT_MISSING",
                "selected_representative": {"pair_id": "P-1"},
            }
        ],
        "result_files": ["K-1.json"],
    }
    current = {
        "counts": {
            "total_pair_version_rows": 443,
            "promotion_eligible_pair_version_rows": 442,
            "promotion_eligible_unique_matches": 74,
            "verified_pair_version_rows": 118,
            "verified_unique_matches": 30,
            "unmatched_eligible_unique_matches": 44,
        },
        "groups_by_match_key": {
            "K-1": {"selected_pair_id": "P-1-new", "verified": False},
            "K-2": {"selected_pair_id": "P-2", "verified": False},
        },
        "unmatched_unique": [
            {
                "match_key": "K-1",
                "reason": "RESULT_PRESENT_RECOVERABLE_LINKAGE",
                "selected_representative": {"pair_id": "P-1-new"},
                "result_evidence": {"file_exists": True},
            },
            {
                "match_key": "K-2",
                "reason": "FUTURE_NOT_DUE",
                "selected_representative": {"pair_id": "P-2"},
                "kickoff_at": "2026-09-05T01:00:00+08:00",
                "result_evidence": {"file_exists": False},
            },
        ],
        "result_files": ["K-1.json", "K-2.json"],
    }

    delta = audit._current_delta(baseline, current)

    assert delta["counts"]["promotion_eligible_unique_matches"]["delta"] == 4
    assert delta["counts"]["unmatched_eligible_unique_matches"]["delta"] == 4
    assert delta["added_unique_matches"] == [
        {
            "match_key": "K-2",
            "selected_pair_id": "P-2",
            "status": "UNMATCHED",
            "reason": "FUTURE_NOT_DUE",
            "kickoff_at": "2026-09-05T01:00:00+08:00",
        }
    ]
    assert delta["baseline_unmatched_current_mapping"][0]["current_reason"] == "RESULT_PRESENT_RECOVERABLE_LINKAGE"
