from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recent_form_competition_provenance_recovery_audit as audit  # noqa: E402


PREMIER_LEAGUE = "\u82f1\u8d85"
FRIENDLY = "\u7403\u4f1a\u53cb\u8c0a"


def _raw_js(*, competition: str = PREMIER_LEAGUE, class_id: int = 1) -> str:
    return "\n".join(
        (
            f"var sclassNames = [{json.dumps({'SclassId': class_id, 'cn': competition, 'big': competition}, ensure_ascii=False)}];",
            'var h_data = [["26-08-01", 1, 0, 0, "RAW-H", "Name contains ' + PREMIER_LEAGUE + '", "RAW-A", "Other", 1, 0]];',
            "var a_data = [];",
        )
    )


def _fixture(
    tmp_path: Path,
    *,
    index: int = 0,
    include_legacy: bool = True,
    canonical_mutation: bool = False,
    competition: str = PREMIER_LEAGUE,
    include_raw: bool = False,
) -> dict:
    kickoff = datetime(2026, 8, 20, 12, tzinfo=timezone.utc) + timedelta(days=index)
    match_key = f"FIXTURE-{index:03d}"
    prediction_id = f"FIXTURE-PRED-{index:03d}"
    match_id = f"FIXTURE-MATCH-{index:03d}"
    home_id = f"HOME-{index:03d}"
    away_id = f"AWAY-{index:03d}"
    home_rows: list[dict] = []
    away_rows: list[dict] = []
    panlu_rows: list[dict] = []
    for history_index in range(12):
        match_date = kickoff.date() - timedelta(days=20 - history_index)
        home_goals = 1 + history_index % 2
        away_goals = history_index % 3
        home_row = {
            "match_date": match_date.isoformat(),
            "home_team_id": home_id,
            "away_team_id": f"HOME-OPP-{index:03d}-{history_index}",
            "home_goals": home_goals,
            "away_goals": away_goals,
        }
        away_row = {
            "match_date": match_date.isoformat(),
            "home_team_id": f"AWAY-OPP-{index:03d}-{history_index}",
            "away_team_id": away_id,
            "home_goals": away_goals,
            "away_goals": home_goals,
        }
        home_rows.append(home_row)
        away_rows.append(away_row)
        for row, row_number in ((home_row, history_index), (away_row, history_index + 12)):
            panlu_rows.append(
                {
                    "match_id": f"FIXTURE-HISTORY-{index:03d}-{row_number:02d}",
                    "home_team_id": row["home_team_id"],
                    "away_team_id": row["away_team_id"],
                    "kickoff": f"{row['match_date']}T08:00:00+00:00",
                    "full_time": {
                        "home": row["home_goals"],
                        "away": row["away_goals"],
                    },
                    "competition": competition,
                }
            )

    home_history = audit._subject_history(
        home_rows,
        subject_id=home_id,
        target_kickoff=kickoff,
        side_label="home",
    )
    away_history = audit._subject_history(
        away_rows,
        subject_id=away_id,
        target_kickoff=kickoff,
        side_label="away",
    )
    windows = audit._component_windows(home_history, away_history)
    recent_form = {
        component: audit._component_aggregate(rows)
        for component, rows in windows.items()
    }
    if canonical_mutation:
        recent_form["home_overall"]["goals_for"] += 1

    evidence_root = tmp_path / "evidence"
    prediction_root = tmp_path / "predictions"
    snapshot_root = tmp_path / "data" / "model_governance" / "input_snapshots"
    result_root = tmp_path / "results"
    raw_root = tmp_path / "raw-cache"
    for path in (evidence_root, prediction_root, snapshot_root, result_root, raw_root):
        path.mkdir(parents=True, exist_ok=True)

    snapshot_ref = f"data/model_governance/input_snapshots/{prediction_id}.json"
    raw_ref = f"data/source_cache/nowscore/raw/{match_key}_analysis.js"
    snapshot = {
        "snapshot_ref": snapshot_ref,
        "snapshot_id": f"FIXTURE-SNAPSHOT-{index:03d}",
        "source_refs": [raw_ref] if include_raw else [],
        "source_hashes": {},
        "input": {
            "prematch_fundamentals": {
                "recent_form": recent_form,
                "form_source": "existing_prematch_snapshot",
            },
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [
                        {
                            **(
                                {"shuju": {"recent_form": recent_form}}
                                if include_legacy
                                else {}
                            ),
                            "nowscore_context": {"panlu": {"matches": panlu_rows}},
                        }
                    ]
                }
            },
        },
    }
    if include_raw:
        raw_bytes = _raw_js().encode("utf-8")
        (raw_root / f"{match_key}_analysis.js").write_bytes(raw_bytes)
        snapshot["source_hashes"][raw_ref] = hashlib.sha256(raw_bytes).hexdigest()

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
        "evidence_captured_at": (kickoff - timedelta(days=1)).isoformat(),
        "source_cutoff_at": (kickoff - timedelta(days=2)).isoformat(),
        "recent_matches": {"home_team": home_rows, "away_team": away_rows},
    }
    (evidence_root / f"{prediction_id}.json").write_text(
        json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
    )
    (prediction_root / f"{prediction_id}.json").write_text(
        json.dumps(prediction, ensure_ascii=False), encoding="utf-8"
    )
    (snapshot_root / f"{prediction_id}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "expected": {match_key: prediction_id},
        "evidence_root": evidence_root,
        "prediction_root": prediction_root,
        "snapshot_root": snapshot_root,
        "result_root": result_root,
        "raw_root": raw_root,
        "windows": windows,
        "recent_form": recent_form,
        "match_key": match_key,
        "prediction_id": prediction_id,
        "match_id": match_id,
        "kickoff": kickoff,
        "raw_ref": raw_ref,
    }


def _run_fixture(fixture: dict, *, minimum: int = 2) -> dict:
    return audit.run(
        evidence_root=fixture["evidence_root"],
        result_root=fixture["result_root"],
        prediction_root=fixture["prediction_root"],
        snapshot_root=fixture["snapshot_root"],
        raw_cache_root=fixture["raw_root"],
        expected_cohort=fixture["expected"],
        minimum_evaluable_unique_matches=minimum,
        bootstrap_replicates=5,
    )


def test_canonical_recent_form_is_authoritative_when_legacy_shuju_is_missing(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, include_legacy=False)
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    summary = _run_fixture(fixture)

    assert summary["frozen_recent_form_reconstruction"]["exact_all_selected"] is True
    assert summary["structural_failures"] == []
    observation = summary["per_match_observations"][0]
    assert observation["legacy_recent_form_corroboration"]["present"] is False
    assert summary["decision"] == "SCOPE_EVIDENCE_NOT_RECOVERABLE"


def test_canonical_recent_form_mismatch_fails_closed(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, canonical_mutation=True)
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    summary = _run_fixture(fixture, minimum=1)

    assert summary["decision"] == "FAIL_CLOSED"
    assert summary["frozen_recent_form_reconstruction"]["exact_all_selected"] is False
    assert summary["settlement_gate"]["actual_outcome_read"] is False
    assert summary["controls"]["counterfactual_count"] == 0


def test_panlu_exact_join_uses_ids_date_and_full_time_score():
    row = {
        "home_team_id": "H",
        "away_team_id": "A",
        "match_date": "2026-08-01",
        "home_goals": 1,
        "away_goals": 0,
    }
    index, failures = audit._build_panlu_index(
        [
            {
                "match_id": "PANLU-1",
                "home_team_id": "H",
                "away_team_id": "A",
                "kickoff": "2026-08-01T08:00:00+00:00",
                "full_time": {"home": 1, "away": 0},
                "competition": PREMIER_LEAGUE,
            }
        ]
    )
    joined = audit._join_competition(row, index)

    assert failures == {}
    assert joined["status"] == "JOINED"
    assert joined["provenance_source"] == "PANLU"
    assert joined["competition"] == PREMIER_LEAGUE


def test_raw_absent_is_unavailable_and_stays_offline(tmp_path):
    raw_ref = "data/source_cache/nowscore/raw/MISSING_analysis.js"
    index, evidence = audit._raw_cache_evidence(
        {"source_refs": [raw_ref], "source_hashes": {raw_ref: "0" * 64}},
        raw_cache_root=tmp_path / "raw",
    )

    assert index == {}
    assert evidence["referenced_count"] == 1
    assert evidence["present_count"] == 0
    assert evidence["hash_valid_count"] == 0
    assert evidence["references"][0]["status"] == "MISSING"


def test_raw_hash_mismatch_is_unavailable(tmp_path):
    raw_ref = "data/source_cache/nowscore/raw/MISMATCH_analysis.js"
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    (raw_root / "MISMATCH_analysis.js").write_text(_raw_js(), encoding="utf-8")
    index, evidence = audit._raw_cache_evidence(
        {"source_refs": [raw_ref], "source_hashes": {raw_ref: "f" * 64}},
        raw_cache_root=raw_root,
    )

    assert index == {}
    assert evidence["references"][0]["status"] == "HASH_MISMATCH"
    assert evidence["references"][0]["hash_valid"] is False


def test_hash_valid_raw_cache_recovers_unresolved_competition(tmp_path):
    raw_ref = "data/source_cache/nowscore/raw/RECOVER_analysis.js"
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw_bytes = _raw_js().encode("utf-8")
    (raw_root / "RECOVER_analysis.js").write_bytes(raw_bytes)
    raw_index, evidence = audit._raw_cache_evidence(
        {"source_refs": [raw_ref], "source_hashes": {raw_ref: hashlib.sha256(raw_bytes).hexdigest()}},
        raw_cache_root=raw_root,
    )
    row = {
        "home_team_id": "RAW-H",
        "away_team_id": "RAW-A",
        "match_date": "2026-08-01",
        "home_goals": 1,
        "away_goals": 0,
    }

    joined = audit._join_competition(row, {}, raw_index)

    assert evidence["references"][0]["status"] == "HASH_VALID"
    assert evidence["parsed_analysis_file_count"] == 1
    assert joined["status"] == "JOINED"
    assert joined["provenance_source"] == "RAW_CACHE"
    assert joined["competition"] == PREMIER_LEAGUE


def test_parsed_raw_and_panlu_conflict_fails_closed(tmp_path):
    raw_ref = "data/source_cache/nowscore/raw/CONFLICT_analysis.js"
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw_bytes = _raw_js(competition=FRIENDLY).encode("utf-8")
    (raw_root / "CONFLICT_analysis.js").write_bytes(raw_bytes)
    raw_index, _ = audit._raw_cache_evidence(
        {"source_refs": [raw_ref], "source_hashes": {raw_ref: hashlib.sha256(raw_bytes).hexdigest()}},
        raw_cache_root=raw_root,
    )
    panlu_index, _ = audit._build_panlu_index(
        [
            {
                "match_id": "PANLU-CONFLICT",
                "home_team_id": "RAW-H",
                "away_team_id": "RAW-A",
                "kickoff": "2026-08-01T08:00:00+00:00",
                "full_time": {"home": 1, "away": 0},
                "competition": PREMIER_LEAGUE,
            }
        ]
    )
    row = {
        "home_team_id": "RAW-H",
        "away_team_id": "RAW-A",
        "match_date": "2026-08-01",
        "home_goals": 1,
        "away_goals": 0,
    }

    joined = audit._join_competition(row, panlu_index, raw_index)

    assert joined["status"] == "CONFLICT"
    assert joined["reason"] == "COMPETITION_LABEL_CONFLICT"
    assert joined["provenance_source"] == "PANLU_AND_RAW_CACHE_CONFLICT"


def test_raw_parser_does_not_infer_from_team_names_or_league_tokens():
    text = "\n".join(
        (
            "var sclassNames = [];",
            'var h_data = [["26-08-01", 1, 0, 0, "RAW-H", "英超", "RAW-A", "英超", 1, 0]];',
            "var a_data = [];",
        )
    )

    index, evidence = audit._raw_analysis_competition_index(
        text, source_ref="data/source_cache/nowscore/raw/TOKEN_analysis.js"
    )

    assert index == {}
    assert evidence["status"] == "PARSE_INCOMPLETE"
    assert evidence["unlabeled_rows"] == 1


def test_outcome_blind_eligibility_is_evaluated_before_any_result_read(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path)
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)

    def should_not_read_results(_result_root):
        raise AssertionError("authoritative results were read before the gate")

    monkeypatch.setattr(audit, "_load_authoritative_results", should_not_read_results)
    summary = _run_fixture(fixture, minimum=2)

    assert summary["outcome_blind_eligibility"]["actual_outcome_read"] is False
    assert summary["settlement_gate"]["actual_outcome_read"] is False
    assert summary["decision"] == "SCOPE_EVIDENCE_NOT_RECOVERABLE"


def test_below_50_never_reads_results_even_when_results_exist(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    result = {
        "match_key": fixture["match_key"],
        "scope": audit.RESULT_SCOPE,
        "kickoff_at": fixture["kickoff"].isoformat(),
        "verified_at": (fixture["kickoff"] + timedelta(days=1)).isoformat(),
        "result_90m": "1-0",
    }
    (fixture["result_root"] / "result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)

    def should_not_read_results(_result_root):
        raise AssertionError("results must remain unread below the pre-registered threshold")

    monkeypatch.setattr(audit, "_load_authoritative_results", should_not_read_results)
    summary = _run_fixture(fixture, minimum=50)

    assert summary["outcome_blind_eligibility"]["eligible_unique_matches"] < 50
    assert summary["settlement_gate"]["authoritative_result_files_read"] == 0
    assert summary["decision"] == "SCOPE_EVIDENCE_NOT_RECOVERABLE"


def test_at_least_50_runs_exactly_one_friendly_excluded_counterfactual(tmp_path, monkeypatch):
    fixtures = [_fixture(tmp_path, index=index) for index in range(50)]
    expected = {}
    for fixture in fixtures:
        expected.update(fixture["expected"])
        result = {
            "match_key": fixture["match_key"],
            "scope": audit.RESULT_SCOPE,
            "kickoff_at": fixture["kickoff"].isoformat(),
            "verified_at": (fixture["kickoff"] + timedelta(days=1)).isoformat(),
            "result_90m": "1-0",
        }
        (fixture["result_root"] / f"{fixture['match_key']}.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    calls: list[int] = []
    original = audit._run_counterfactual

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(audit, "_run_counterfactual", counted)
    summary = audit.run(
        evidence_root=fixtures[0]["evidence_root"],
        result_root=fixtures[0]["result_root"],
        prediction_root=fixtures[0]["prediction_root"],
        snapshot_root=fixtures[0]["snapshot_root"],
        raw_cache_root=fixtures[0]["raw_root"],
        expected_cohort=expected,
        minimum_evaluable_unique_matches=50,
        bootstrap_replicates=5,
    )

    assert len(calls) == 1
    assert summary["cohort"]["observed_unique_matches"] == 50
    assert summary["settlement_gate"]["actual_outcome_read"] is True
    assert summary["controls"]["counterfactual_count"] == 1
    assert set(summary["variants"]) == {"CHAMPION", "FRIENDLY_EXCLUDED"}


def test_research_only_run_preserves_input_bytes_and_production_isolation(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, include_raw=True)
    evidence_path = fixture["evidence_root"] / f"{fixture['prediction_id']}.json"
    before = evidence_path.read_bytes()
    monkeypatch.setattr(audit, "PROJECT_ROOT", tmp_path)
    summary = _run_fixture(fixture, minimum=2)

    assert evidence_path.read_bytes() == before
    assert summary["source"]["network_access"] == "NO_NETWORK"
    assert summary["source"]["postmatch_reviews_used"] is False
    assert summary["source"]["provider_added"] is False
    assert summary["source"]["target_outcome_used_for_scope_or_eligibility"] is False
    for key in (
        "production_changes",
        "champion_changes",
        "market_changes",
        "provider_changes",
        "frozen_prediction_changes",
        "results_truth_changes",
        "serving_changes",
        "selector_changes",
        "calibration_changes",
        "rho_changes",
        "promotion",
    ):
        assert summary["controls"][key] == "NO"
    assert summary["controls"]["counterfactual_count"] == 0
    assert summary["variants"] == {}
