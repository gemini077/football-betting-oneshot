import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prospective_pair_capture import PairLedger  # noqa: E402
from model_governance import prediction_content_hash  # noqa: E402
from football_data.prospective_pair_quality import (  # noqa: E402
    PairQualityAdapterError,
    adapt_settled_pairs,
    evaluate_settled_pairs,
)
from test_prospective_pair_capture import (  # noqa: E402
    NOW,
    challenger,
    prediction,
    verified_result,
)


def settled_fixture(tmp_path):
    champion = prediction()
    shadow = challenger()
    champion["prediction_sha256"] = prediction_content_hash(champion)
    shadow["prediction_sha256"] = prediction_content_hash(shadow)
    ledger = PairLedger(tmp_path / "pairs")
    captured = ledger.capture(champion, shadow, now=NOW)
    ledger.settle(captured["pair_id"], verified_result(), settled_at=NOW)
    return ledger, champion, shadow


def test_settled_pair_maps_frozen_records_and_stays_shadow_only(tmp_path):
    ledger, champion, shadow = settled_fixture(tmp_path)

    result = evaluate_settled_pairs(
        ledger.states(),
        champion_records=[champion],
        challenger_records=[shadow],
    )

    assert result["adapter"]["status"] == "TRUE_PAIRED"
    assert result["paired"] == {
        "same_match_keys": True,
        "sample_count": 1,
        "match_keys": ["FBOS-PAIR-1"],
    }
    assert result["mode"] == "shadow_only"
    assert result["automatic_promotion"] is False
    assert result["status"] in {"PASS", "FAIL"}

    adapted = adapt_settled_pairs(
        ledger.states(),
        champion_records=[champion],
        challenger_records=[shadow],
    )
    assert adapted["champion_predictions"][0]["actual"] == {"home_goals": 1, "away_goals": 0}
    assert adapted["challenger_predictions"][0]["probabilities"]["1x2"] == {
        "home": 0.5,
        "draw": 0.3,
        "away": 0.2,
    }


def test_settled_pair_adapter_accepts_events_but_not_unsettled_or_historical_rows(tmp_path):
    ledger, champion, shadow = settled_fixture(tmp_path)
    events = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]

    from_events = evaluate_settled_pairs(
        events,
        champion_records=[champion],
        challenger_records=[shadow],
    )
    assert from_events["adapter"]["status"] == "TRUE_PAIRED"

    unsettled = PairLedger(tmp_path / "unsettled")
    captured = unsettled.capture(prediction(), challenger(), now=NOW)
    result = evaluate_settled_pairs(
        unsettled.states(),
        champion_records=[champion],
        challenger_records=[shadow],
    )
    assert captured["event"]["event_type"] == "PAIR_CAPTURED"
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["automatic_promotion"] is False

    historical = dict(champion)
    historical["actual"] = {"home_score": 1, "away_score": 0}
    result = evaluate_settled_pairs(
        ledger.states(),
        champion_records=[historical],
        challenger_records=[shadow],
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["adapter"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_missing_or_hash_mismatched_referenced_records_fail_closed(tmp_path):
    ledger, champion, shadow = settled_fixture(tmp_path)

    missing = evaluate_settled_pairs(
        ledger.states(),
        champion_records=[champion],
        challenger_records=[],
    )
    assert missing["status"] == "INSUFFICIENT_EVIDENCE"
    assert "CHALLENGER_REFERENCED_RECORD_MISSING" in missing["blocking_reasons"][0]

    tampered = dict(shadow)
    tampered["prediction_sha256"] = "tampered-hash"
    mismatched = evaluate_settled_pairs(
        ledger.states(),
        champion_records=[champion],
        challenger_records=[tampered],
    )
    assert mismatched["status"] == "INSUFFICIENT_EVIDENCE"
    assert "CHALLENGER_PREDICTION_SHA256_MISMATCH" in mismatched["blocking_reasons"][0]

    tampered_content = dict(shadow)
    tampered_content["probabilities"] = {"home": 0.2, "draw": 0.3, "away": 0.5}
    tampered = evaluate_settled_pairs(
        ledger.states(),
        champion_records=[champion],
        challenger_records=[tampered_content],
    )
    assert tampered["status"] == "INSUFFICIENT_EVIDENCE"
    assert "CHALLENGER_PREDICTION_CONTENT_HASH_MISMATCH" in tampered["blocking_reasons"][0]


def test_adapter_rejects_unpaired_evidence_directly():
    with pytest.raises(PairQualityAdapterError, match="TRUE_PAIRED_SETTLEMENT_REQUIRED"):
        adapt_settled_pairs(
            [],
            champion_records=[prediction()],
            challenger_records=[challenger()],
        )
