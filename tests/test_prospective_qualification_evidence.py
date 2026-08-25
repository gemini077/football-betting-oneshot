from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_governance import prediction_content_hash  # noqa: E402
from prospective_pair_capture import PairLedger  # noqa: E402
from football_data.prospective_qualification_evidence import (  # noqa: E402
    evaluate_qualification_evidence,
)
from test_prospective_pair_capture import (  # noqa: E402
    NOW,
    challenger,
    prediction,
    verified_result,
)


def settled_pair(tmp_path, *, champion_updates=None, candidate_updates=None):
    champion = prediction()
    candidate = challenger()
    champion.update(champion_updates or {})
    candidate.update(candidate_updates or {})
    champion["prediction_sha256"] = prediction_content_hash(champion)
    candidate["prediction_sha256"] = prediction_content_hash(candidate)

    ledger = PairLedger(tmp_path / "pairs")
    captured = ledger.capture(champion, candidate, now=NOW)
    ledger.settle(captured["pair_id"], verified_result(), settled_at=NOW)
    return ledger.states(), champion, candidate


def market_snapshot(
    *,
    match_key="FBOS-PAIR-1",
    snapshot_id="market-snapshot-1",
    snapshot_at="2026-08-12T09:30:00+08:00",
    probabilities=None,
):
    return {
        "match_key": match_key,
        "snapshot_id": snapshot_id,
        "snapshot_at": snapshot_at,
        "probabilities": probabilities or {"home": 0.4, "draw": 0.35, "away": 0.25},
    }


def test_valid_settled_pair_reports_same_match_metrics_and_diagnostics(tmp_path):
    pair_evidence, champion, candidate = settled_pair(
        tmp_path,
        candidate_updates={
            "lambda_home": 1.6,
            "lambda_away": 0.4,
            "score_top3": ["1-1", "1-0", "0-0"],
        },
    )

    result = evaluate_qualification_evidence(
        pair_evidence,
        champion_records=[champion],
        candidate_records=[candidate],
        market_snapshots=[market_snapshot()],
    )

    assert result["status"] == "EVIDENCE_AVAILABLE"
    assert result["paired_sample_count"] == 1
    assert result["market_sample_count"] == 1
    assert result["metrics"]["champion"]["one_x_two"]["brier"] == pytest.approx(0.38)
    assert result["metrics"]["candidate"]["one_x_two"]["log_loss"] > 0
    assert result["metrics"]["market"]["one_x_two"]["brier"] == pytest.approx(0.545)
    assert result["metrics"]["champion"]["exact_score_top1"] == {"available": True, "count": 1, "share": 1.0}
    assert result["metrics"]["candidate"]["exact_score_top1"] == {"available": True, "count": 0, "share": 0.0}
    assert result["diagnostics"]["mean_abs_lambda_gap"] == pytest.approx(0.4)
    assert result["diagnostics"]["lambda_gap_below_0_5"] == {"count": 1, "share": 1.0}
    assert result["diagnostics"]["top1_one_to_one"] == {
        "champion": {"count": 0, "share": 0.0},
        "candidate": {"count": 1, "share": 1.0},
    }
    assert result["promotion_eligible"] is False
    assert result["automatic_promotion"] is False


def test_missing_market_keeps_pair_metrics_but_excludes_market(tmp_path):
    pair_evidence, champion, candidate = settled_pair(tmp_path)

    result = evaluate_qualification_evidence(
        pair_evidence,
        champion_records=[champion],
        candidate_records=[candidate],
        market_snapshots=[],
    )

    assert result["status"] == "PARTIAL_EVIDENCE"
    assert result["paired_sample_count"] == 1
    assert result["market_sample_count"] == 0
    assert result["metrics"]["candidate"]["sample_count"] == 1
    assert result["metrics"]["market"]["sample_count"] == 0
    assert result["market"]["status"] == "UNAVAILABLE"
    assert "market_snapshot_missing" in result["blocking_reasons"]


def test_market_requires_same_frozen_snapshot_identity_and_cutoff(tmp_path):
    pair_evidence, champion, candidate = settled_pair(
        tmp_path,
        champion_updates={"market_snapshot_id": "frozen-market-1"},
        candidate_updates={"market_snapshot_id": "frozen-market-1"},
    )

    mismatched_identity = evaluate_qualification_evidence(
        pair_evidence,
        champion_records=[champion],
        candidate_records=[candidate],
        market_snapshots=[market_snapshot(snapshot_id="frozen-market-2")],
    )
    assert mismatched_identity["paired_sample_count"] == 1
    assert mismatched_identity["market_sample_count"] == 0
    assert "market_snapshot_identity_mismatch" in mismatched_identity["blocking_reasons"]

    after_cutoff = evaluate_qualification_evidence(
        pair_evidence,
        champion_records=[champion],
        candidate_records=[candidate],
        market_snapshots=[
            market_snapshot(
                snapshot_id="frozen-market-1",
                snapshot_at="2026-08-12T10:30:00+08:00",
            )
        ],
    )
    assert after_cutoff["market_sample_count"] == 0
    assert "market_snapshot_after_pair_cutoff" in after_cutoff["blocking_reasons"]

    conflicting_pair_evidence, conflicting_champion, conflicting_candidate = settled_pair(
        tmp_path / "conflicting",
        champion_updates={"market_snapshot_id": "frozen-market-1"},
        candidate_updates={"market_snapshot_id": "frozen-market-2"},
    )
    conflicting = evaluate_qualification_evidence(
        conflicting_pair_evidence,
        champion_records=[conflicting_champion],
        candidate_records=[conflicting_candidate],
        market_snapshots=[market_snapshot(snapshot_id="frozen-market-1")],
    )
    assert conflicting["market_sample_count"] == 0
    assert "market_frozen_snapshot_identity_conflict" in conflicting["blocking_reasons"]


@pytest.mark.parametrize(
    ("role", "error_code"),
    (
        ("champion", "CHAMPION_PREDICTION_CONTENT_HASH_MISMATCH"),
        ("candidate", "CHALLENGER_PREDICTION_CONTENT_HASH_MISMATCH"),
    ),
)
def test_tampered_member_is_rejected_by_existing_pair_adapter(tmp_path, role, error_code):
    pair_evidence, champion, candidate = settled_pair(tmp_path)
    tampered = dict(champion if role == "champion" else candidate)
    tampered["probabilities"] = {"home": 0.2, "draw": 0.3, "away": 0.5}

    result = evaluate_qualification_evidence(
        pair_evidence,
        champion_records=[tampered if role == "champion" else champion],
        candidate_records=[tampered if role == "candidate" else candidate],
        market_snapshots=[market_snapshot()],
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["paired_sample_count"] == 0
    assert f"pair_adapter:{error_code}" in result["blocking_reasons"]


def test_zero_or_unpaired_evidence_is_explicitly_insufficient(tmp_path):
    result = evaluate_qualification_evidence(
        [],
        champion_records=[],
        candidate_records=[],
        market_snapshots=[market_snapshot()],
    )

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["paired_sample_count"] == 0
    assert result["market_sample_count"] == 0
    assert result["metrics"]["champion"]["sample_count"] == 0
    assert result["metrics"]["candidate"]["sample_count"] == 0
    assert result["metrics"]["market"]["sample_count"] == 0
    assert "pair_adapter:TRUE_PAIRED_SETTLEMENT_REQUIRED" in result["blocking_reasons"]
