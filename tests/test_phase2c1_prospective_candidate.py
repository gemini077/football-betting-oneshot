from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from football_data.phase2c1_prospective_candidate import (  # noqa: E402
    CHALLENGER_ID,
    build_prospective_candidate_record,
    validate_candidate_record,
)
from model_governance import prediction_content_hash  # noqa: E402
from prospective_pair_capture import PairLedger  # noqa: E402
from test_prospective_pair_capture import prediction  # noqa: E402


TZ = timezone(timedelta(hours=8))
KICKOFF = "2026-08-13T03:00:00+08:00"
NOW = "2026-08-12T12:00:00+08:00"
SOURCE_CUTOFF = "2026-08-12T10:00:00+08:00"
CREATED = "2026-08-12T10:01:00+08:00"
FROZEN = "2026-08-12T10:02:00+08:00"


def _target(**updates):
    value = {
        "canonical_match_id": "match-1",
        "kickoff_at": KICKOFF,
        "competition_id": "COMP-1",
        "season_id": "SEASON-1",
        "home_team_id": "home-team",
        "away_team_id": "away-team",
    }
    value.update(updates)
    return value


def _history():
    rows = []
    start = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    for index in range(10):
        kickoff = (start + timedelta(days=index)).isoformat()
        rows.append(
            {
                "canonical_match_id": f"home-history-{index}",
                "kickoff_at": kickoff,
                "competition_id": "COMP-1",
                "home_team_id": "home-team",
                "away_team_id": f"opponent-home-{index}",
                "home_goals": 2,
                "away_goals": 0,
                "eligible_for_team_strength": True,
                "duplicate_status": "unique",
            }
        )
        rows.append(
            {
                "canonical_match_id": f"away-history-{index}",
                "kickoff_at": (start + timedelta(days=20 + index)).isoformat(),
                "competition_id": "COMP-1",
                "home_team_id": f"opponent-away-{index}",
                "away_team_id": "away-team",
                "home_goals": 0,
                "away_goals": 1,
                "eligible_for_team_strength": True,
                "duplicate_status": "unique",
            }
        )
    return rows


def _identity():
    return {
        "match_key": "FBOS-PAIR-1",
        "match_id": "match-1",
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_at": KICKOFF,
    }


def _candidate(**updates):
    values = {
        "target": _target(),
        "prematch_history": _history(),
        "match_identity": _identity(),
        "source_cutoff_at": SOURCE_CUTOFF,
        "prediction_created_at": CREATED,
        "freeze_created_at": FROZEN,
        "now": NOW,
    }
    values.update(updates)
    return build_prospective_candidate_record(**values)


def test_future_candidate_is_repeatable_and_contains_structural_evidence():
    first = _candidate()
    second = _candidate()

    assert first == second
    assert first["prediction_status"] == "FROZEN"
    assert first["challenger_id"] == CHALLENGER_ID
    assert set(first["probabilities"]) == {"home", "draw", "away"}
    assert first["score_top1"] == first["score_top3"][0]
    assert len(first["score_top3"]) == 3
    assert isinstance(first["lambda_home"], float)
    assert isinstance(first["lambda_away"], float)
    assert first["structural_evidence"]["top1_is_one_to_one"] == (first["score_top1"] == "1-1")
    assert first["structural_evidence"]["lambda_gap"] == pytest.approx(
        abs(first["lambda_home"] - first["lambda_away"])
    )
    assert first["prediction_sha256"] == prediction_content_hash(first)


def test_pair_ledger_accepts_the_frozen_research_candidate(tmp_path):
    candidate = _candidate()
    champion = prediction(kickoff=KICKOFF)
    champion.update(
        {
            "source_cutoff_at": SOURCE_CUTOFF,
            "prediction_created_at": CREATED,
            "freeze_created_at": FROZEN,
        }
    )

    ledger = PairLedger(tmp_path)
    event = ledger.capture(
        champion,
        candidate,
        now=datetime(2026, 8, 12, 12, 0, tzinfo=TZ),
    )

    assert event["status"] == "created"
    captured = ledger.states()[event["pair_id"]]["capture"]
    assert captured["event_type"] == "PAIR_CAPTURED"
    assert captured["match"]["match_key"] == "FBOS-PAIR-1"
    assert captured["challenger"]["challenger_id"] == CHALLENGER_ID
    assert captured["research_only"] is True


def test_kickoff_after_generation_and_future_history_are_rejected():
    with pytest.raises(ValueError, match="KICKOFF_ALREADY_STARTED"):
        _candidate(now="2026-08-13T03:00:00+08:00")
    with pytest.raises(ValueError, match="NON_PREMATCH_HISTORY_FORBIDDEN"):
        _candidate(prematch_history=_history() + [{**_history()[0], "kickoff_at": KICKOFF}])


def test_history_after_source_cutoff_is_rejected_even_before_kickoff():
    late_history = [{**_history()[0], "kickoff_at": SOURCE_CUTOFF}]

    with pytest.raises(ValueError, match="HISTORY_AFTER_SOURCE_CUTOFF_FORBIDDEN"):
        _candidate(prematch_history=_history() + late_history)


def test_missing_identity_or_result_field_leakage_is_rejected():
    with pytest.raises(ValueError, match="MATCH_IDENTITY_MATCH_KEY_MISSING"):
        _candidate(match_identity={"kickoff_at": KICKOFF})
    with pytest.raises(ValueError, match="TARGET_RESULT_FIELDS_FORBIDDEN"):
        _candidate(target=_target(home_goals=0, away_goals=0))


def test_hash_tampering_is_detected_and_boundary_is_not_promotable():
    candidate = _candidate()
    tampered = deepcopy(candidate)
    tampered["lambda_home"] = float(tampered["lambda_home"]) + 0.1

    assert tampered["prediction_sha256"] != prediction_content_hash(tampered)
    with pytest.raises(ValueError, match="PREDICTION_CONTENT_HASH_MISMATCH"):
        validate_candidate_record(tampered)
    assert candidate["production_registration"] is False
    assert candidate["automatic_promotion"] is False
    assert candidate["formal_eligible"] is False
