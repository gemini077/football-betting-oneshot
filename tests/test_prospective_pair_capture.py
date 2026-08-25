import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prospective_pair_capture import (  # noqa: E402
    PairLedger,
    PairValidationError,
    build_governance_counts,
    build_pair_capture,
    capture_forward_pairs,
    deterministic_pair_id,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=TZ)
KICKOFF = "2026-08-13T03:00:00+08:00"


def prediction(
    *,
    prediction_id="P-CHAMPION",
    role="champion",
    model_family="champion-family",
    model_source="champion-source",
    model_run="champion-run",
    challenger_id=None,
    kickoff=KICKOFF,
    status="formal",
):
    return {
        "prediction_id": prediction_id,
        "prediction_sha256": f"sha-{prediction_id}",
        "prediction_status": status,
        "model_role": role,
        "challenger_id": challenger_id,
        "model_family": model_family,
        "model_core_version": model_family,
        "model_source_fingerprint": model_source,
        "model_run_fingerprint": model_run,
        "release_version": "test-release",
        "match_key": "FBOS-PAIR-1",
        "match_id": "match-1",
        "match_identity": {
            "match_key": "FBOS-PAIR-1",
            "match_id": "match-1",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": kickoff,
        },
        "business_date": "2026-08-12",
        "kickoff_at": kickoff,
        "source_cutoff_at": "2026-08-12T10:00:00+08:00",
        "prediction_created_at": "2026-08-12T10:01:00+08:00",
        "freeze_created_at": "2026-08-12T10:02:00+08:00",
        "model_input_snapshot_ref": "data/model_governance/input_snapshots/test.json",
        "input_sha256": f"input-{prediction_id}",
        "canonical_model_input_sha256": f"canonical-{prediction_id}",
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "base_input_quality": "VERIFIED_MINIMUM",
        "generic_data_grade": "C",
        "data_grade": "C",
        "formal_eligible": role == "champion",
        "model_formal_eligible": role == "champion",
        "critical_missing_fields": [],
        "prediction_variant": "model_only",
        "manual_override": False,
        "analysis_output": {"report_type": "base_prediction_minimal"},
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "lambda_home": 1.2,
        "lambda_away": 0.8,
        "unique_score": "1-0",
        "score_top3": ["1-0", "1-1", "0-0"],
        "btts": {"yes": 0.5, "no": 0.5},
        "product_role": "FUSION_BASELINE_V0" if role == "champion" else "RESEARCH_CHALLENGER",
    }


def challenger(**overrides):
    values = {
        "prediction_id": "P-CHALLENGER",
        "role": "challenger",
        "model_family": "research-family-v1",
        "model_source": "research-source",
        "model_run": "research-run",
        "challenger_id": "research-v1",
    }
    values.update(overrides)
    value = prediction(**values)
    value["formal_eligible"] = False
    value["model_formal_eligible"] = False
    return value


def verified_result(*, match_key="FBOS-PAIR-1", home=1, away=0):
    return {
        "status": "result_verified",
        "scope": "regulation_90m_plus_stoppage",
        "match_key": match_key,
        "score_90m": f"{home}-{away}",
        "verified_at": "2026-08-13T05:00:00+08:00",
        "source": "fixture-provider",
    }


def test_legal_forward_pair_has_deterministic_id_and_idempotent_store(tmp_path):
    champion = prediction()
    shadow = challenger()
    first = build_pair_capture(champion, shadow, now=NOW)
    second = build_pair_capture(champion, shadow, now=NOW + timedelta(minutes=1))

    assert first["pair_id"] == second["pair_id"]
    assert first["pair_id"] == deterministic_pair_id(champion, shadow)
    ledger = PairLedger(tmp_path / "pairs")
    assert ledger.capture(champion, shadow, now=NOW)["status"] == "created"
    assert ledger.capture(champion, shadow, now=NOW + timedelta(minutes=1))["status"] == "existing"
    assert len((tmp_path / "pairs" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_pair_rejects_retroactive_or_postmatch_capture():
    champion = prediction()
    shadow = challenger()

    with pytest.raises(PairValidationError, match="RETROACTIVE_PAIR_FORBIDDEN"):
        build_pair_capture(champion, shadow, now=datetime(2026, 8, 13, 3, 1, tzinfo=TZ))

    after_match = prediction(kickoff="2026-08-12T11:00:00+08:00")
    after_shadow = challenger(kickoff="2026-08-12T11:00:00+08:00")
    with pytest.raises(PairValidationError, match="RETROACTIVE_PAIR_FORBIDDEN"):
        build_pair_capture(after_match, after_shadow, now=NOW)


def test_pair_rejects_same_model_and_fake_challenger():
    champion = prediction()
    same_model = challenger(
        challenger_id="fake",
        model_family=champion["model_family"],
        model_source=champion["model_source_fingerprint"],
        model_run=champion["model_run_fingerprint"],
    )
    with pytest.raises(PairValidationError, match="SAME_MODEL_IDENTITY"):
        build_pair_capture(champion, same_model, now=NOW)

    fake = challenger()
    fake.pop("challenger_id")
    with pytest.raises(PairValidationError, match="CHALLENGER_ID_MISSING"):
        build_pair_capture(champion, fake, now=NOW)


def test_shared_verified_90m_result_is_one_true_pair(tmp_path):
    ledger = PairLedger(tmp_path / "pairs")
    captured = ledger.capture(prediction(), challenger(), now=NOW)
    pair_id = captured["pair_id"]

    assert ledger.states()[pair_id]["TRUE_PAIRED"] is False
    settlement = ledger.settle(pair_id, verified_result())
    assert settlement["status"] == "created"
    state = ledger.states()[pair_id]
    assert state["TRUE_PAIRED"] is True
    assert state["shared_result"]["home_score_90m"] == 1
    assert state["shared_result"]["away_score_90m"] == 0

    assert ledger.settle(pair_id, verified_result())["status"] == "existing"
    assert len((tmp_path / "pairs" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_forward_capture_refuses_past_rows_and_reports_missing_challenger(tmp_path):
    existing = {"event_type": "audit_marker", "value": "unchanged"}
    ledger_path = tmp_path / "pairs" / "ledger.jsonl"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(existing) + "\n", encoding="utf-8")
    before = ledger_path.read_bytes()

    result = capture_forward_pairs(
        [prediction()],
        [],
        now=NOW,
        pair_root=tmp_path / "pairs",
        raw_frozen_path=tmp_path / "raw.json",
    )
    assert result["readiness"] == "READY_FOR_FORWARD_CAPTURE"
    assert result["pair_rejections"]["CHALLENGER_NOT_AVAILABLE"] == 1
    assert result["CHAMPION_EVALUABLE"] == 0
    assert result["TRUE_PAIRED"] == 0
    assert ledger_path.read_bytes() == before

    past = prediction(kickoff="2026-08-12T11:00:00+08:00")
    past_shadow = challenger(kickoff="2026-08-12T11:00:00+08:00")
    result = capture_forward_pairs(
        [past],
        [past_shadow],
        now=NOW,
        pair_root=tmp_path / "past-pairs",
    )
    assert result["pair_rejections"]["RETROACTIVE_PAIR_FORBIDDEN"] == 1
    assert not (tmp_path / "past-pairs" / "ledger.jsonl").exists()


def test_governance_counts_distinguish_settled_unresolved_and_future(tmp_path):
    past_settled = prediction(prediction_id="P-SETTLED", kickoff="2026-08-12T11:00:00+08:00")
    past_unresolved = prediction(prediction_id="P-UNRESOLVED", kickoff="2026-08-12T11:30:00+08:00")
    future = prediction(prediction_id="P-FUTURE", kickoff="2026-08-13T03:00:00+08:00")
    raw_path = tmp_path / "paper_ledger" / "frozen.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(json.dumps({"tickets": [1, 2, 3]}), encoding="utf-8")
    formal_rows = [{
        "prediction_id": "P-SETTLED",
        "formal_prospective_eligible": True,
        "actual": {"home_score": 1, "away_score": 0},
        "result_verified_at": "2026-08-11T05:00:00+08:00",
    }]

    counts = build_governance_counts(
        [past_settled, past_unresolved, future],
        formal_rows,
        now=NOW,
        raw_frozen_path=raw_path,
        pair_root=tmp_path / "pairs",
    )

    assert counts["RAW_FROZEN_TICKETS"] == 3
    assert counts["FORMAL_FROZEN"] == 3
    assert counts["FORMAL_PROSPECTIVE"] == 1
    assert counts["SETTLED"] == 1
    assert counts["RESULT_UNRESOLVED"] == 1
    assert counts["FUTURE_SCHEDULED_FORMAL"] == 1
    assert counts["CHAMPION_EVALUABLE"] == 0
    assert counts["CHALLENGER_EVALUABLE"] == 0
    assert counts["TRUE_PAIRED"] == 0
    assert counts["governance_count_scope"] == "TOTAL_SNAPSHOT_AS_OF"
    assert counts["semantics"]["RESULT_UNRESOLVED"]["scope"] == "total_snapshot_formal_frozen_not_in_ledger_past_kickoff"
    assert counts["semantics"]["FUTURE_SCHEDULED_FORMAL"]["scope"] == "total_snapshot_formal_frozen_not_in_ledger_future_kickoff"



def test_pair_requires_same_canonical_match_and_evidence_cutoff():
    champion = prediction()
    wrong_match = challenger()
    wrong_match["match_key"] = "FBOS-OTHER"
    wrong_match["match_identity"]["match_key"] = "FBOS-OTHER"
    with pytest.raises(PairValidationError, match="CANONICAL_MATCH_MISMATCH"):
        build_pair_capture(champion, wrong_match, now=NOW)

    wrong_cutoff = challenger()
    wrong_cutoff["source_cutoff_at"] = "2026-08-12T10:00:30+08:00"
    with pytest.raises(PairValidationError, match="EVIDENCE_CUTOFF_MISMATCH"):
        build_pair_capture(champion, wrong_cutoff, now=NOW)
