from __future__ import annotations

import json
from pathlib import Path

from scripts.structural_football_evidence_coverage import run


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _evidence(prediction_id: str, *, rows: int = 10, captured: str = "2026-09-01T10:00:00+08:00"):
    def history(subject_id: int, opponent_start: int):
        output = []
        for index in range(rows):
            output.append({
                "match_date": f"2026-08-{20-index:02d}",
                "home_team_id": subject_id if index % 2 == 0 else opponent_start + index,
                "away_team_id": opponent_start + index if index % 2 == 0 else subject_id,
                "home_goals": index % 4,
                "away_goals": (index + 1) % 3,
            })
        return output

    return {
        "prediction_id": prediction_id,
        "match_id": f"match-{prediction_id}",
        "match_key": f"key-{prediction_id}",
        "kickoff_at": "2026-09-02T12:00:00+08:00",
        "evidence_captured_at": captured,
        "source_cutoff_at": "2026-09-01T10:00:00+08:00",
        "source_provider": "nowscore",
        "recent_matches": {
            "home_team": history(101, 1000),
            "away_team": history(202, 2000),
        },
    }


def _review(prediction_id: str):
    return {
        "prediction_id": prediction_id,
        "result": {"score_90m": "2-1"},
    }


def test_coverage_requires_true_settled_intersection_and_prematch_evidence(tmp_path):
    evidence_root = tmp_path / "evidence"
    review_root = tmp_path / "reviews"
    good_ids = [f"P-{index}" for index in range(50)]

    for prediction_id in good_ids:
        _write_json(evidence_root / f"{prediction_id}.json", _evidence(prediction_id))
        _write_json(review_root / f"{prediction_id}.json", _review(prediction_id))

    # Has a result, but evidence was captured after kickoff -> must not qualify.
    _write_json(
        evidence_root / "P-late.json",
        _evidence("P-late", captured="2026-09-02T12:01:00+08:00"),
    )
    _write_json(review_root / "P-late.json", _review("P-late"))

    # Has good evidence, but no result -> must not enter settled usable.
    _write_json(evidence_root / "P-pending.json", _evidence("P-pending"))

    manifest = {
        "selected_records": [{"prediction_id": prediction_id} for prediction_id in good_ids],
        "verified_prediction_ids": good_ids,
    }
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    result = run(
        evidence_root=evidence_root,
        review_root=review_root,
        pinned_manifest=manifest_path,
    )

    assert result["decision"] == "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
    assert result["coverage"]["settled_with_usable_structural_evidence"] == 50
    assert result["coverage"]["settled_with_any_evidence"] == 51
    assert result["failure_reasons"]["EVIDENCE_NOT_PREMATCH"] == 1
    assert result["integrity_contract"]["postmatch_result_used_for_generation"] is False


def test_short_history_does_not_qualify(tmp_path):
    evidence_root = tmp_path / "evidence"
    review_root = tmp_path / "reviews"
    _write_json(evidence_root / "P-short.json", _evidence("P-short", rows=5))
    _write_json(review_root / "P-short.json", _review("P-short"))
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
        review_root=review_root,
        pinned_manifest=manifest_path,
    )

    assert result["decision"] == "STRUCTURAL_EVIDENCE_SAMPLE_INSUFFICIENT"
    assert result["coverage"]["settled_with_usable_structural_evidence"] == 0
    assert result["failure_reasons"]["HOME_HISTORY_TOO_SHORT"] == 1
    assert result["failure_reasons"]["AWAY_HISTORY_TOO_SHORT"] == 1
