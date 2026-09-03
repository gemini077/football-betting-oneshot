from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from scripts import dynamic_recency_structural_signal_audit as audit


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _history_rows(subject_id: str, *, subject_is_home: bool, kickoff: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(12):
        match_date = kickoff - timedelta(days=10 + index)
        if subject_is_home:
            home_team_id, away_team_id = subject_id, f"opponent-home-{index}"
            home_goals, away_goals = 2 if index % 2 else 1, 1 if index % 3 == 0 else 0
        else:
            home_team_id, away_team_id = f"opponent-away-{index}", subject_id
            home_goals, away_goals = 1 if index % 3 == 0 else 0, 2 if index % 2 else 1
        rows.append(
            {
                "match_date": match_date.isoformat(),
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_goals": home_goals,
                "away_goals": away_goals,
            }
        )
    return rows


def _fixture(
    tmp_path: Path,
    *,
    prediction_ids: tuple[str, ...] = ("prediction-1",),
    result_scope: str = audit.RESULT_SCOPE,
    verified_at: str = "2026-09-11T12:00:00Z",
    capture_times: tuple[str, ...] | None = None,
    evidence_overrides: dict[str, object] | None = None,
) -> dict[str, Path | tuple[str, ...]]:
    evidence_root = tmp_path / "evidence"
    result_root = tmp_path / "results"
    prediction_root = tmp_path / "predictions"
    jobs_root = tmp_path / "jobs"
    kickoff = "2026-09-10T12:00:00Z"
    target_date = date(2026, 9, 10)
    match_key = "match-key-1"
    captures = capture_times or tuple("2026-09-09T{:02d}:00:00Z".format(8 + index) for index in range(len(prediction_ids)))

    for index, prediction_id in enumerate(prediction_ids):
        evidence = {
            "prediction_id": prediction_id,
            "match_id": "match-id-1",
            "match_key": match_key,
            "kickoff_at": kickoff,
            "evidence_captured_at": captures[index],
            "source_cutoff_at": "2026-09-08T12:00:00Z",
            "source_provider": "fixture",
            "recent_matches": {
                "home_team": _history_rows("home-team-1", subject_is_home=True, kickoff=target_date),
                "away_team": _history_rows("away-team-1", subject_is_home=False, kickoff=target_date),
            },
        }
        if evidence_overrides:
            evidence.update(evidence_overrides)
        _write_json(evidence_root / f"{prediction_id}.json", evidence)
        _write_json(
            prediction_root / f"{prediction_id}.json",
            {
                "prediction_id": prediction_id,
                "match_key": match_key,
                "kickoff_at": kickoff,
                "model_role": "champion",
                "model_family": audit.CHAMPION_MODEL_FAMILY,
                "model_core_version": audit.CHAMPION_MODEL_FAMILY,
                "prediction_status": "formal",
                "formal_eligible": True,
                "model_formal_eligible": True,
                "lambda_home": 1.65,
                "lambda_away": 1.25,
                "rho": 0.0,
            },
        )

    _write_json(
        result_root / "authoritative-result.json",
        {
            "match_key": match_key,
            "scope": result_scope,
            "kickoff_at": kickoff,
            "verified_at": verified_at,
            "result_90m": "2-1",
        },
    )
    _write_json(
        jobs_root / "jobs.json",
        {"jobs": [{"match_id": "match-id-1", "league": "英格兰超级联赛"}]},
    )
    return {
        "evidence_root": evidence_root,
        "result_root": result_root,
        "prediction_root": prediction_root,
        "jobs_root": jobs_root,
        "prediction_ids": prediction_ids,
    }


def _run(fixture: dict[str, Path | tuple[str, ...]], *, replicates: int = 25) -> dict[str, object]:
    return audit.run(
        evidence_root=fixture["evidence_root"],  # type: ignore[arg-type]
        result_root=fixture["result_root"],  # type: ignore[arg-type]
        prediction_root=fixture["prediction_root"],  # type: ignore[arg-type]
        jobs_root=fixture["jobs_root"],  # type: ignore[arg-type]
        bootstrap_replicates=replicates,
    )


def test_authoritative_result_matches_evidence_match_key_without_review(tmp_path: Path):
    fixture = _fixture(tmp_path)
    summary = _run(fixture)

    settlement = summary["settlement_gate"]
    assert settlement["strict_settled_usable_prediction_snapshots"] == 1
    assert settlement["strict_settled_usable_unique_matches"] == 1
    assert summary["source"]["settlement_truth"] == "authoritative result.match_key joined to evidence.match_key"
    assert summary["source"]["postmatch_reviews_used"] is False
    assert summary["cohort"]["evaluated_unique_matches"] == 1


def test_multiple_predictions_are_one_unique_match_observation(tmp_path: Path):
    fixture = _fixture(
        tmp_path,
        prediction_ids=("prediction-old", "prediction-middle", "prediction-latest"),
        capture_times=(
            "2026-09-09T08:00:00Z",
            "2026-09-09T09:00:00Z",
            "2026-09-09T10:00:00Z",
        ),
    )
    summary = _run(fixture)

    assert summary["settlement_gate"]["strict_settled_usable_prediction_snapshots"] == 3
    assert summary["settlement_gate"]["strict_settled_usable_unique_matches"] == 1
    assert summary["cohort"]["selected_latest_legal_unique_matches"] == 1
    assert summary["cohort"]["evaluated_unique_matches"] == 1
    assert summary["cohort"]["selected_prediction_ids"] == ["prediction-latest"]
    assert summary["cohort"]["one_match_one_observation"] is True


def test_non_regulation_scope_is_not_settled(tmp_path: Path):
    fixture = _fixture(tmp_path, result_scope="extra_time")
    summary = _run(fixture)

    assert summary["settlement_gate"]["strict_settled_usable_prediction_snapshots"] == 0
    assert summary["settlement_gate"]["strict_settled_usable_unique_matches"] == 0
    assert summary["settlement_gate"]["failure_reasons"]["RESULT_SCOPE_NOT_REGULATION_90M"] == 1
    assert summary["decision"] == "SAMPLE_INSUFFICIENT"


def test_invalid_verified_at_is_not_settled(tmp_path: Path):
    fixture = _fixture(tmp_path, verified_at="not-a-timestamp")
    summary = _run(fixture)

    assert summary["settlement_gate"]["strict_settled_usable_unique_matches"] == 0
    assert summary["settlement_gate"]["failure_reasons"]["INVALID_RESULT_VERIFIED_AT"] == 1


def test_prematch_evidence_integrity_gate_remains_required(tmp_path: Path):
    fixture = _fixture(
        tmp_path,
        evidence_overrides={"evidence_captured_at": "2026-09-10T12:00:00Z"},
    )
    summary = _run(fixture)

    assert summary["prematch_evidence_failure_reasons"]["EVIDENCE_NOT_PREMATCH"] == 1
    assert summary["settlement_gate"]["usable_prematch_evidence_snapshots"] == 0
    assert summary["settlement_gate"]["strict_settled_usable_unique_matches"] == 0


def test_form_proxy_scales_frozen_champion_and_retains_rho(tmp_path: Path):
    fixture = _fixture(tmp_path)
    summary = _run(fixture)
    observation = summary["per_match_observations"][0]

    assert observation["frozen_champion"]["lambda_total"] == 2.9
    assert observation["form_proxies"]["E0"]["form_total"] == observation["form_proxy_e0_total"]
    for variant in audit.VARIANTS:
        model = observation["variants"][variant]
        assert model["rho"] == observation["frozen_champion"]["rho"]
        assert model["lambda_home"] == 1.65 * observation["ratios"][variant]["home_ratio"]
        assert model["lambda_away"] == 1.25 * observation["ratios"][variant]["away_ratio"]


def test_paired_bootstrap_is_deterministic(tmp_path: Path):
    fixture = _fixture(tmp_path)
    first = _run(fixture, replicates=40)
    second = _run(fixture, replicates=40)

    assert first["primary_paired_bootstrap"] == second["primary_paired_bootstrap"]
    assert first["primary_paired_bootstrap"]["seed"] == audit._stable_seed(audit.BOOTSTRAP_SEED, "E120")


def test_non_positive_form_denominator_fails_closed(tmp_path: Path):
    fixture = _fixture(tmp_path)
    evidence_path = fixture["evidence_root"] / "prediction-1.json"  # type: ignore[operator]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    for rows in evidence["recent_matches"].values():
        for row in rows:
            row["home_goals"] = 0
            row["away_goals"] = 0
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    summary = _run(fixture)

    assert summary["decision"] == "FAIL_CLOSED"
    assert any("denominator is non-positive" in failure["reason"] for failure in summary["failures"])
