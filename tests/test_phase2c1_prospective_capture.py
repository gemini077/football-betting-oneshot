from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from football_data.phase2c1_prospective_capture import run_phase2c1_future_batch  # noqa: E402
from model_governance import prediction_content_hash  # noqa: E402
from prospective_pair_capture import PairLedger  # noqa: E402
from test_phase2c1_prospective_candidate import (  # noqa: E402
    CREATED,
    FROZEN,
    KICKOFF,
    NOW,
    SOURCE_CUTOFF,
    _history,
    _identity,
    _target,
)
from test_prospective_pair_capture import prediction  # noqa: E402


TZ = timezone(timedelta(hours=8))


def _champion(**updates):
    value = prediction(kickoff=KICKOFF)
    value.update(
        {
            "source_cutoff_at": SOURCE_CUTOFF,
            "prediction_created_at": CREATED,
            "freeze_created_at": FROZEN,
        }
    )
    value.update(updates)
    return value


def _schedule(**updates):
    target = _target(
        match_key="FBOS-PAIR-1",
        business_date="2026-08-12",
        schedule_source="prediction_universe_contract",
    )
    target.update(updates)
    return {"business_date": "2026-08-12", "fixtures": [target]}


def _run(tmp_path, *, schedule=None, champions=None, now=NOW, **kwargs):
    return run_phase2c1_future_batch(
        _schedule() if schedule is None else schedule,
        _history(),
        [_champion()] if champions is None else champions,
        now=now,
        candidate_root=tmp_path / "challenger",
        pair_root=tmp_path / "pairs",
        raw_frozen_path=tmp_path / "raw-frozen.json",
        prospective_root=tmp_path / "prospective",
        **kwargs,
    )


def test_future_schedule_batch_persists_candidate_and_captures_pair(tmp_path):
    result = _run(tmp_path)

    assert result["schedule_rows"] == 1
    assert result["candidates_frozen"] == 1
    assert result["persistence"] == {"created": 1, "existing": 0}
    assert result["pair_capture"]["pairs_captured_this_run"] == 1
    assert result["pair_capture"]["readiness"] == "READY_FOR_FORWARD_CAPTURE"
    assert result["research_only"] is True
    assert result["production_registration"] is False
    assert result["automatic_promotion"] is False
    assert result["settlement_status"] == "UNSETTLED_ONLY"
    assert result["settled_evidence_count"] == 0

    saved_path = next((tmp_path / "challenger").glob("*.json"))
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["prediction_status"] == "FROZEN"
    assert saved["business_date"] == "2026-08-12"
    assert saved["prediction_created_at"] == "2026-08-12T04:00:00Z"
    assert saved["freeze_created_at"] == saved["prediction_created_at"]
    assert saved["prediction_created_at"] != CREATED
    assert saved["prediction_sha256"] == prediction_content_hash(saved)
    assert "settlement" not in saved
    assert saved["structural_evidence"]["lambda_gap"] >= 0.0
    cutoff = datetime.fromisoformat(saved["source_cutoff_at"].replace("Z", "+00:00"))
    created = datetime.fromisoformat(saved["prediction_created_at"].replace("Z", "+00:00"))
    freeze = datetime.fromisoformat(saved["freeze_created_at"].replace("Z", "+00:00"))
    kickoff = datetime.fromisoformat(saved["kickoff_at"].replace("Z", "+00:00"))
    assert cutoff < created <= freeze < kickoff

    states = PairLedger(tmp_path / "pairs").states()
    assert len(states) == 1
    assert next(iter(states.values()))["TRUE_PAIRED"] is False


def test_repeating_same_future_batch_is_idempotent(tmp_path):
    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first["persistence"] == {"created": 1, "existing": 0}
    assert second["persistence"] == {"created": 0, "existing": 1}
    assert second["pair_capture"]["pairs_captured_this_run"] == 0
    assert second["pair_capture"]["pair_rejections"] == {}


def test_batch_fails_closed_for_past_target_result_leakage_and_missing_champion(tmp_path):
    past_kickoff = "2026-08-11T03:00:00+08:00"
    past_identity = dict(_identity(), kickoff_at=past_kickoff)
    past_target = _target(
        match_key="FBOS-PAIR-1",
        kickoff_at=past_kickoff,
        business_date="2026-08-12",
    )
    past_champion = _champion(
        kickoff_at=past_kickoff,
        match_identity=past_identity,
        source_cutoff_at="2026-08-10T10:00:00+08:00",
        prediction_created_at="2026-08-10T10:01:00+08:00",
        freeze_created_at="2026-08-10T10:02:00+08:00",
    )
    past = _run(
        tmp_path / "past",
        schedule={"fixtures": [past_target]},
        champions=[past_champion],
    )
    leaked = _run(tmp_path / "leaked", schedule=_schedule(home_goals=0, away_goals=0))
    missing = _run(tmp_path / "missing", champions=[])

    assert past["candidates_frozen"] == 0
    assert "CURRENT_OUTSIDE_PROSPECTIVE_WINDOW" in past["rejections"]["FBOS-PAIR-1"]
    assert "TARGET_RESULT_FIELDS_FORBIDDEN" in leaked["rejections"]["FBOS-PAIR-1"]
    assert missing["rejections"]["FBOS-PAIR-1"] == "CHAMPION_RECORD_NOT_FOUND"


def test_dry_run_produces_records_without_writing_pair_ledger(tmp_path):
    result = _run(tmp_path, dry_run=True)

    assert result["candidates_frozen"] == 1
    assert result["pair_capture"]["pairs_would_capture"] == 1
    assert result["pair_capture"]["pairs_captured_this_run"] == 0
    assert not (tmp_path / "pairs" / "ledger.jsonl").exists()
