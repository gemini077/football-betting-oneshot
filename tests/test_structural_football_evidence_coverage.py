from __future__ import annotations

import json
from pathlib import Path

from scripts.structural_football_evidence_coverage import build_report, run


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _evidence(
    prediction_id: str,
    *,
    rows: int = 10,
    captured: str = "2026-09-01T10:00:00+08:00",
    match_key: str | None = None,
):
    def history(subject_id: int, opponent_start: int):
        output = []
        for index in range(rows):
            output.append(
                {
                    "match_date": f"2026-08-{20-index:02d}",
                    "home_team_id": subject_id if index % 2 == 0 else opponent_start + index,
                    "away_team_id": opponent_start + index if index % 2 == 0 else subject_id,
                    "home_goals": index % 4,
                    "away_goals": (index + 1) % 3,
                }
            )
        return output

    return {
        "prediction_id": prediction_id,
        "match_id": f"match-{prediction_id}",
        "match_key": match_key or f"key-{prediction_id}",
        "kickoff_at": "2026-09-02T12:00:00+08:00",
        "evidence_captured_at": captured,
        "source_cutoff_at": "2026-09-01T10:00:00+08:00",
        "source_provider": "nowscore",
        "recent_matches": {
            "home_team": history(101, 1000),
            "away_team": history(202, 2000),
        },
    }


def _result(
    match_key: str,
    *,
    scope: str = "regulation_90m_plus_stoppage",
    result_90m: str | None = "2-1",
    verified_at: str | None = "2026-09-02T13:00:00+08:00",
    kickoff_at: str = "2026-09-02T12:00:00+08:00",
):
    return {
        "match_key": match_key,
        "kickoff_local": kickoff_at,
        "verified_at": verified_at,
        "result_90m": result_90m,
        "scope": scope,
    }


def _write_evidence(root: Path, record: dict):
    _write_json(root / f"{record['prediction_id']}.json", record)


def _write_result(root: Path, record: dict):
    _write_json(root / f"{record['match_key']}.json", record)


def test_authoritative_match_key_settlement_does_not_need_review(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    good_ids = [f"P-{index}" for index in range(50)]

    for prediction_id in good_ids:
        evidence = _evidence(prediction_id)
        _write_evidence(evidence_root, evidence)
        _write_result(result_root, _result(evidence["match_key"]))

    # Has a valid authoritative result, but evidence was captured after kickoff.
    late = _evidence("P-late", captured="2026-09-02T12:01:00+08:00")
    _write_evidence(evidence_root, late)
    _write_result(result_root, _result(late["match_key"]))

    # Has good evidence, but no authoritative result.
    _write_evidence(evidence_root, _evidence("P-pending"))

    # This settled, usable record is outside the old pinned manifest.  The
    # current prospective gate must still count it.
    outside = _evidence("P-outside-pinned")
    _write_evidence(evidence_root, outside)
    _write_result(result_root, _result(outside["match_key"]))

    manifest_path = tmp_path / "manifest.json"
    _write_json(
        manifest_path,
        {
            "selected_records": [{"prediction_id": prediction_id} for prediction_id in good_ids],
            "verified_prediction_ids": good_ids,
        },
    )

    result = run(
        evidence_root=evidence_root,
        result_root=result_root,
        pinned_manifest=manifest_path,
    )

    assert result["decision"] == "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
    assert result["coverage"]["settled_usable_prediction_snapshots"] == 51
    assert result["coverage"]["settled_usable_unique_matches"] == 51
    assert result["coverage"]["settled_with_any_evidence"] == 52
    assert result["coverage"]["all_prospective"]["settled_usable_unique_matches"] == 51
    assert result["coverage"]["pinned_verified_with_usable_evidence"] == 50
    assert result["integrity_contract"]["postmatch_review_used_for_readiness"] is False
    assert result["failure_reasons"]["EVIDENCE_NOT_PREMATCH"] == 1


def test_multiple_prediction_snapshots_count_one_unique_match(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    shared_match_key = "shared-match-key"

    for prediction_id in ("P-checkpoint-a", "P-checkpoint-b", "P-checkpoint-c"):
        _write_evidence(
            evidence_root,
            _evidence(prediction_id, match_key=shared_match_key),
        )
    _write_result(result_root, _result(shared_match_key))

    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {"selected_records": [], "verified_prediction_ids": []})
    result = run(
        evidence_root=evidence_root,
        result_root=result_root,
        pinned_manifest=manifest_path,
    )

    assert result["coverage"]["settled_usable_prediction_snapshots"] == 3
    assert result["coverage"]["settled_usable_unique_matches"] == 1
    assert result["decision"] == "STRUCTURAL_EVIDENCE_SAMPLE_INSUFFICIENT"


def test_authoritative_result_gate_rejects_scope_and_invalid_verification(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    records = {
        "P-valid": _result("key-P-valid"),
        "P-wrong-scope": _result("key-P-wrong-scope", scope="after_extra_time"),
        "P-invalid-verified": _result("key-P-invalid-verified", verified_at="not-a-time"),
        "P-invalid-score": _result("key-P-invalid-score", result_90m="FT"),
        "P-before-kickoff": _result(
            "key-P-before-kickoff",
            verified_at="2026-09-02T11:00:00+08:00",
        ),
    }
    for prediction_id, authoritative_result in records.items():
        _write_evidence(evidence_root, _evidence(prediction_id))
        _write_result(result_root, authoritative_result)

    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {"selected_records": [], "verified_prediction_ids": []})
    result = run(
        evidence_root=evidence_root,
        result_root=result_root,
        pinned_manifest=manifest_path,
    )

    assert result["coverage"]["settled_with_any_evidence"] == 1
    assert result["coverage"]["settled_usable_prediction_snapshots"] == 1
    assert result["coverage"]["settled_usable_unique_matches"] == 1
    assert result["authoritative_result_failure_reasons"]["RESULT_SCOPE_NOT_REGULATION_90M"] == 1
    assert result["authoritative_result_failure_reasons"]["INVALID_RESULT_VERIFIED_AT"] == 1
    assert result["authoritative_result_failure_reasons"]["RESULT_90M_UNPARSEABLE"] == 1
    assert result["authoritative_result_failure_reasons"]["VERIFIED_AT_NOT_AFTER_KICKOFF"] == 1


def test_short_history_stays_unusable_with_authoritative_result(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    evidence = _evidence("P-short", rows=5)
    _write_evidence(evidence_root, evidence)
    _write_result(result_root, _result(evidence["match_key"]))
    manifest_path = tmp_path / "manifest.json"
    _write_json(
        manifest_path,
        {
            "selected_records": [{"prediction_id": "P-short"}],
            "verified_prediction_ids": ["P-short"],
        },
    )

    result = run(
        evidence_root=evidence_root,
        result_root=result_root,
        pinned_manifest=manifest_path,
    )

    assert result["coverage"]["settled_with_any_evidence"] == 1
    assert result["coverage"]["settled_usable_prediction_snapshots"] == 0
    assert result["coverage"]["settled_usable_unique_matches"] == 0
    assert result["failure_reasons"]["HOME_HISTORY_TOO_SHORT"] == 1
    assert result["failure_reasons"]["AWAY_HISTORY_TOO_SHORT"] == 1


def test_report_contains_corrected_settlement_and_gate_fields(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    evidence = _evidence("P-report")
    _write_evidence(evidence_root, evidence)
    _write_result(result_root, _result(evidence["match_key"]))
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {"selected_records": [], "verified_prediction_ids": []})

    report = build_report(
        run(
            evidence_root=evidence_root,
            result_root=result_root,
            pinned_manifest=manifest_path,
        )
    )

    for field in (
        "total_evidence_files",
        "usable_structural_evidence",
        "settled_usable_prediction_snapshots",
        "settled_usable_unique_matches",
        "PINNED_COHORT_ONLY",
        "final Gate decision",
    ):
        assert field in report


def test_sanity_reference_mismatch_fails_closed_without_changing_settlement_truth(tmp_path):
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    ledger_path = tmp_path / "ledger.jsonl"
    evidence = _evidence("P-sanity")
    _write_evidence(evidence_root, evidence)
    # The filename is present for the independent reference, but the
    # authoritative record fails the required result_90m gate.
    _write_result(result_root, _result(evidence["match_key"], result_90m=None))
    ledger_path.write_text(
        json.dumps(
            {
                "prediction_id": "P-sanity",
                "actual": {"home_score": 2, "away_score": 1},
                "match_identity": {"match_key": evidence["match_key"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, {"selected_records": [], "verified_prediction_ids": []})

    result = run(
        evidence_root=evidence_root,
        result_root=result_root,
        pinned_manifest=manifest_path,
        ledger_path=ledger_path,
    )

    assert result["coverage"]["settled_usable_prediction_snapshots"] == 0
    assert result["coverage"]["settled_usable_unique_matches"] == 0
    assert result["gate"]["fail_closed"] is True
    assert result["status"] == "FAIL_CLOSED"
