from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recent_form_competition_scope_audit as audit  # noqa: E402


def _fixture(tmp_path: Path, *, mutate_recent_form: bool = False) -> dict:
    kickoff = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    match_key = "FIXTURE-20260820-001"
    prediction_id = "FIXTURE-PRED-001"
    match_id = "FIXTURE-MATCH-001"
    home_rows: list[dict] = []
    away_rows: list[dict] = []
    panlu_rows: list[dict] = []
    first_history_date = date(2026, 8, 1)
    for index in range(12):
        match_date = first_history_date + timedelta(days=index)
        home_goals = 1 + index % 2
        away_goals = index % 3
        home_opponent = f"H-OPP-{index}"
        away_opponent = f"A-OPP-{index}"
        home_row = {
            "match_date": match_date.isoformat(),
            "home_team_id": "H",
            "away_team_id": home_opponent,
            "home_goals": home_goals,
            "away_goals": away_goals,
        }
        away_row = {
            "match_date": match_date.isoformat(),
            "home_team_id": away_opponent,
            "away_team_id": "A",
            "home_goals": away_goals,
            "away_goals": home_goals,
        }
        home_rows.append(home_row)
        away_rows.append(away_row)
        for row, row_index in ((home_row, index), (away_row, index + 12)):
            panlu_rows.append(
                {
                    "match_id": f"FIXTURE-HISTORY-{row_index}",
                    "home_team_id": row["home_team_id"],
                    "away_team_id": row["away_team_id"],
                    "kickoff": f"{row['match_date']}T08:00:00+00:00",
                    "full_time": {
                        "home": row["home_goals"],
                        "away": row["away_goals"],
                    },
                    "competition": "英超",
                }
            )

    home_history = audit._subject_history(
        home_rows,
        subject_id="H",
        target_kickoff=kickoff,
        side_label="home",
    )
    away_history = audit._subject_history(
        away_rows,
        subject_id="A",
        target_kickoff=kickoff,
        side_label="away",
    )
    windows = audit._component_windows(home_history, away_history)
    recent_form = {
        component: audit._component_aggregate(rows)
        for component, rows in windows.items()
    }
    if mutate_recent_form:
        recent_form["home_overall"]["goals_for"] += 1

    evidence_root = tmp_path / "evidence"
    prediction_root = tmp_path / "predictions"
    snapshot_root = tmp_path / "data" / "model_governance" / "input_snapshots"
    result_root = tmp_path / "results"
    for path in (evidence_root, prediction_root, snapshot_root, result_root):
        path.mkdir(parents=True, exist_ok=True)

    snapshot_ref = f"data/model_governance/input_snapshots/{prediction_id}.json"
    snapshot = {
        "snapshot_ref": snapshot_ref,
        "snapshot_id": "FIXTURE-SNAPSHOT-001",
        "input": {
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [
                        {
                            "shuju": {"recent_form": recent_form},
                            "nowscore_context": {
                                "panlu": {"matches": panlu_rows}
                            },
                        }
                    ]
                }
            }
        },
    }
    prediction = {
        "prediction_id": prediction_id,
        "match_key": match_key,
        "match_id": match_id,
        "kickoff_at": kickoff.isoformat(),
        "model_role": "champion",
        "model_family": audit.CHAMPION_MODEL_FAMILY,
        "model_core_version": audit.CHAMPION_MODEL_FAMILY,
        "prediction_status": "formal",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "lambda_home": 1.4,
        "lambda_away": 0.9,
        "rho": -0.05,
        "input_snapshot_ref": snapshot_ref,
    }
    evidence = {
        "prediction_id": prediction_id,
        "match_key": match_key,
        "match_id": match_id,
        "kickoff_at": kickoff.isoformat(),
        "evidence_captured_at": "2026-08-19T08:00:00+00:00",
        "source_cutoff_at": "2026-08-19T07:00:00+00:00",
        "recent_matches": {"home_team": home_rows, "away_team": away_rows},
    }
    (evidence_root / f"{prediction_id}.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    (prediction_root / f"{prediction_id}.json").write_text(
        json.dumps(prediction), encoding="utf-8"
    )
    (snapshot_root / f"{prediction_id}.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    return {
        "expected": {match_key: prediction_id},
        "evidence_root": evidence_root,
        "prediction_root": prediction_root,
        "snapshot_root": snapshot_root,
        "result_root": result_root,
        "windows": windows,
        "recent_form": recent_form,
        "match_key": match_key,
        "prediction_id": prediction_id,
    }


def _joined_rows(count: int, *, friendly_indices: set[int] | None = None) -> list[dict]:
    friendly_indices = friendly_indices or set()
    return [
        {
            "goals_for": 1 + index % 2,
            "goals_against": index % 2,
            "_join": {
                "status": "JOINED",
                "is_club_friendly": index in friendly_indices,
            },
        }
        for index in range(count)
    ]


def test_frozen_recent_form_reconstruction_is_exact_and_fieldwise(tmp_path):
    fixture = _fixture(tmp_path)

    reconstruction = audit._reconstruct_recent_form(
        fixture["windows"], fixture["recent_form"]
    )

    assert reconstruction["exact"] is True
    assert reconstruction["mismatches"] == []
    assert reconstruction["reconstructed"] == fixture["recent_form"]


def test_mismatch_fails_closed_without_reading_authoritative_results(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, mutate_recent_form=True)
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)

    def should_not_read_results(_result_root):
        raise AssertionError("authoritative results were read before the gate")

    monkeypatch.setattr(audit, "_load_authoritative_results", should_not_read_results)
    summary = audit.run(
        evidence_root=fixture["evidence_root"],
        result_root=fixture["result_root"],
        prediction_root=fixture["prediction_root"],
        snapshot_root=fixture["snapshot_root"],
        expected_cohort=fixture["expected"],
        minimum_evaluable_unique_matches=1,
        bootstrap_replicates=5,
    )

    assert summary["decision"] == "FAIL_CLOSED"
    assert summary["frozen_recent_form_reconstruction"]["exact_all_selected"] is False
    assert summary["controls"]["counterfactual_count"] == 0
    assert summary["settlement_gate"]["actual_outcome_read"] is False


def test_competition_join_is_unique_or_ambiguous_without_guessing():
    row = {
        "home_team_id": "H",
        "away_team_id": "A",
        "match_date": "2026-08-01",
        "home_goals": 1,
        "away_goals": 0,
    }
    panlu = {
        "home_team_id": "H",
        "away_team_id": "A",
        "kickoff": "2026-08-01T08:00:00+00:00",
        "full_time": {"home": 1, "away": 0},
        "competition": "英超",
    }
    index, failures = audit._build_panlu_index([panlu, {**panlu, "match_id": "DUP"}])

    assert failures == {}
    assert audit._join_competition(row, index)["status"] == "AMBIGUOUS"

    unique_index, _ = audit._build_panlu_index([panlu])
    unique = audit._join_competition(row, unique_index)
    assert unique["status"] == "JOINED"
    assert unique["competition"] == "英超"


def test_friendly_filter_is_exact_and_never_backfills_older_rows():
    assert audit.is_club_friendly("球会友谊") is True
    assert audit.is_club_friendly("球會友誼") is True
    assert audit.is_club_friendly("英超") is False
    windows = {
        component: _joined_rows(10, friendly_indices=set(range(5)))
        for component in audit.COMPONENTS
    }
    eligibility = audit._compute_outcome_blind_eligibility(
        windows,
        {"exact": True, "reconstructed_anatomy": {"home_form": 1.0, "away_form": 1.0}},
    )

    for component in audit.COMPONENTS:
        filtered = eligibility["filtered_components"][component]
        assert filtered["original_matches"] == 10
        assert filtered["remaining_matches"] == 5
        assert filtered["excluded_friendly_matches"] == 5
        assert filtered["no_backfill"] is True
    assert eligibility["no_backfill"] is True


def test_fallback_uses_same_side_filtered_overall_when_venue_is_short():
    windows = {
        component: _joined_rows(10)
        for component in audit.COMPONENTS
    }
    windows["home_home"] = _joined_rows(10, friendly_indices=set(range(8)))
    eligibility = audit._compute_outcome_blind_eligibility(
        windows,
        {"exact": True, "reconstructed_anatomy": {"home_form": 1.0, "away_form": 1.0}},
    )

    assert eligibility["eligible"] is True
    assert eligibility["fallbacks"]["home_venue_to_filtered_overall"] is True
    assert eligibility["filtered_form"]["home_venue_source"] == "home_overall"
    assert eligibility["filtered_form"]["away_venue_source"] == "away_away"


def test_latest_legal_snapshot_is_selected_once_per_match():
    kickoff = datetime(2026, 8, 20, tzinfo=timezone.utc)
    records = {
        "old": {
            "match_key": "M-1",
            "prediction_id": "P-OLD",
            "usable": True,
            "captured": datetime(2026, 8, 19, 8, tzinfo=timezone.utc),
            "kickoff": kickoff,
        },
        "new": {
            "match_key": "M-1",
            "prediction_id": "P-NEW",
            "usable": True,
            "captured": datetime(2026, 8, 19, 9, tzinfo=timezone.utc),
            "kickoff": kickoff,
        },
    }

    selected, failures = audit._select_cohort(records, {"M-1": "P-NEW"})

    assert failures == []
    assert [row["prediction_id"] for row in selected] == ["P-NEW"]


def test_paired_bootstrap_is_deterministic_over_unique_matches():
    rows = []
    for actual_home, actual_away in ((1, 1), (2, 0), (0, 1)):
        rows.append(
            {
                "variants": {
                    "CHAMPION": audit._variant_observation(
                        actual_home=actual_home,
                        actual_away=actual_away,
                        lambda_home=1.4,
                        lambda_away=0.9,
                        rho=-0.05,
                    ),
                    "FRIENDLY_EXCLUDED": audit._variant_observation(
                        actual_home=actual_home,
                        actual_away=actual_away,
                        lambda_home=1.2,
                        lambda_away=0.8,
                        rho=-0.05,
                    ),
                }
            }
        )

    first = audit._paired_bootstrap(rows, "FRIENDLY_EXCLUDED", seed=123, replicates=40)
    second = audit._paired_bootstrap(rows, "FRIENDLY_EXCLUDED", seed=123, replicates=40)

    assert first == second
    assert first["exact_score_nll"]["sample_n"] == 3
    assert first["exact_score_nll"]["replicates"] == 40


def test_outcome_gate_is_isolated_and_does_not_read_results_before_threshold(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    before = {
        path: path.read_bytes()
        for path in fixture["evidence_root"].glob("*.json")
    }

    def should_not_read_results(_result_root):
        raise AssertionError("result store read before outcome-blind gate")

    monkeypatch.setattr(audit, "_load_authoritative_results", should_not_read_results)
    summary = audit.run(
        evidence_root=fixture["evidence_root"],
        result_root=fixture["result_root"],
        prediction_root=fixture["prediction_root"],
        snapshot_root=fixture["snapshot_root"],
        expected_cohort=fixture["expected"],
        minimum_evaluable_unique_matches=2,
        bootstrap_replicates=5,
    )

    assert summary["decision"] == "COMPETITION_SCOPE_SAMPLE_INSUFFICIENT"
    assert summary["outcome_blind_eligibility"]["eligible_unique_matches"] == 1
    assert summary["outcome_blind_eligibility"]["gate_passed"] is False
    assert summary["source"]["postmatch_reviews_used"] is False
    assert summary["source"]["provider_added"] is False
    assert summary["source"]["target_outcome_used_for_scope_or_eligibility"] is False
    assert all(value == "NO" for key, value in summary["controls"].items() if key.endswith("_changes"))
    assert summary["controls"]["counterfactual_count"] == 0
    assert {path: path.read_bytes() for path in fixture["evidence_root"].glob("*.json")} == before
