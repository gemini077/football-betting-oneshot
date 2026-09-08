from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation_kernel import ranked_probability_score  # noqa: E402
from market_engine import (  # noqa: E402
    build_pure_market_exact_projection,
    extract_pure_market_1x2_quotes,
    extract_pure_market_ou_quotes,
    pure_market_fair_probability,
    solve_pure_market_total_lambda,
)
from pure_market_exact_prospective import (  # noqa: E402
    LaneConflictError,
    PREDICTION_SCHEMA_VERSION,
    RESULT_SCOPE,
    aggregate_settlements,
    build_compact_index,
    build_prospective_prediction,
    load_persisted_predictions,
    load_persisted_settlements,
    iter_persisted_prediction_paths,
    prediction_digest,
    prediction_shard_path,
    prediction_shard_prefix,
    persist_settlement,
    persist_prediction,
    run_lane,
    settle_prediction,
    select_legal_market_snapshot,
    settlement_digest,
    settlement_shard_path,
)
from score_engine import (  # noqa: E402
    independent_poisson_score_matrix,
    independent_poisson_score_matrix_with_tail,
)


UTC = timezone.utc


def _raw_market(*, fetched_at: str = "2026-09-08T08:00:00+00:00") -> dict:
    return {
        "fetched_at": fetched_at,
        "ouzhi": {
            "bookmakers": [
                {"cid": 1, "spf_current": {"home": 2.0, "draw": 4.0, "away": 4.0}},
                {"cid": 2, "spf_current": {"home": 2.1, "draw": 3.9, "away": 4.1}},
            ]
        },
        "daxiao": {
            "companies": [
                {
                    "name": "one",
                    "current_line": 2.5,
                    "current_over_water": 0.9,
                    "current_under_water": 0.9,
                }
            ]
        },
    }


def _snapshot(*, raw: dict | None = None) -> dict:
    raw = raw or _raw_market()
    return {
        "snapshot_id": "FBOS-SNAPSHOT-TEST",
        "canonical_input_sha256": "input-sha",
        "canonical_model_input_sha256": "model-input-sha",
        "source_cutoff_at": "2026-09-08T08:00:00+00:00",
        "input": {
            "source_snapshots": {
                "nowscore": {"snapshots": [raw]},
            }
        },
    }


def _record(*, kickoff: str = "2026-09-08T12:00:00+00:00") -> dict:
    return {
        "prediction_id": "FBOS-PRED-CHAMPION-1",
        "match_key": "FBOS-TEST-MATCH-1",
        "match_id": "TEST-1",
        "home": "HOME",
        "away": "AWAY",
        "match_identity": {
            "match_key": "FBOS-TEST-MATCH-1",
            "match_id": "TEST-1",
            "home": "HOME",
            "away": "AWAY",
            "kickoff_at": kickoff,
        },
        "kickoff_at": kickoff,
        "source_cutoff_at": "2026-09-08T08:00:00+00:00",
        "prediction_created_at": "2026-09-08T08:01:00+00:00",
        "freeze_created_at": "2026-09-08T08:02:00+00:00",
        "prediction_status": "formal",
        "model_role": "champion",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "prediction_variant": "model_only",
        "manual_override": None,
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "prediction_sha256": "champion-sha",
        "input_sha256": "input-sha",
        "canonical_model_input_sha256": "model-input-sha",
        "input_snapshot": {"snapshot_id": "FBOS-SNAPSHOT-TEST"},
    }


def _synthetic_prediction(index: int) -> dict:
    prediction = {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "prediction_id": f"PME-HIGH-WATER-{index:05d}",
        "match_key": f"HIGH-WATER-MATCH-{index:05d}",
        "kickoff_at": "2026-09-10T12:00:00+00:00",
        "implementation_activated_at": "2026-09-08T09:00:00+00:00",
        "generated_at": "2026-09-08T09:00:00+00:00",
        "source_cutoff_at": "2026-09-08T08:00:00+00:00",
        "model_role": "shadow",
        "result_scope": RESULT_SCOPE,
        "production_enabled": False,
        "serving_enabled": False,
        "user_visible": False,
        "auto_promote": False,
        "score_matrix": [{
            "score": "0-0",
            "home_goals": 0,
            "away_goals": 0,
            "probability": 1.0,
        }],
        "probabilities": {"home": 0.0, "draw": 1.0, "away": 0.0},
        "lambda_home": 0.1,
        "lambda_away": 0.1,
        "rho": 0.0,
    }
    prediction["prediction_digest"] = prediction_digest(prediction)
    prediction["prediction_sha256"] = prediction["prediction_digest"]
    return prediction


def test_pure_market_solver_matches_the_accepted_quarter_line_contract():
    matrix = independent_poisson_score_matrix(2.4, 0.0, max_goals_per_team=20)
    for line in (2.0, 2.5, 2.25):
        target = pure_market_fair_probability(matrix, line, "over")
        solved = solve_pure_market_total_lambda(line, target)
        assert solved["lambda_total"] == pytest.approx(2.4, abs=2e-4)
        assert abs(solved["residual"]) <= 1e-7


def test_quote_normalization_matches_the_accepted_market_189_contract():
    one_x2 = extract_pure_market_1x2_quotes(_raw_market())
    ou = extract_pure_market_ou_quotes(_raw_market())

    assert one_x2["valid_bookmaker_count"] == 2
    assert one_x2["valid"][0]["fair_probabilities"] == pytest.approx(
        {"home": 0.5, "draw": 0.25, "away": 0.25}
    )
    assert ou["valid_bookmaker_count"] == 1
    assert ou["valid"][0]["line"] == 2.5
    assert ou["valid"][0]["fair_over_probability"] == pytest.approx(0.5)


def test_pure_market_projection_uses_one_matrix_for_all_derived_markets():
    projection = build_pure_market_exact_projection(_raw_market())

    assert projection["status"] == "EVALUABLE"
    assert projection["rho"] == 0.0
    assert projection["score_matrix_complete"] is True
    assert sum(row["probability"] for row in projection["score_matrix"]) == pytest.approx(1.0)
    assert projection["probabilities"] == pytest.approx(
        projection["derived_markets"]["ft_1x2"]
    )
    assert projection["btts"] == projection["derived_markets"]["btts"]
    assert projection["score_top1"] == projection["score_matrix"][0]["score"]
    assert "2.5" in projection["derived_markets"]["totals"]
    assert "0.0" in projection["derived_markets"]["asian_handicap"]


def test_handicap_quotes_are_held_out_of_the_pure_market_solver():
    baseline = build_pure_market_exact_projection(_raw_market())
    altered = _raw_market()
    altered["yazhi"] = {
        "companies": [{
            "name": "held-out",
            "current_handicap": -2.0,
            "current_water_home": 0.1,
            "current_water_away": 9.0,
        }]
    }
    changed = build_pure_market_exact_projection(altered)

    assert changed["lambda_total"] == pytest.approx(baseline["lambda_total"])
    assert changed["lambda_home"] == pytest.approx(baseline["lambda_home"])
    assert changed["lambda_away"] == pytest.approx(baseline["lambda_away"])
    assert changed["score_matrix"] == baseline["score_matrix"]


def test_score_engine_tail_helper_preserves_existing_matrix_output():
    existing = independent_poisson_score_matrix(1.4, 0.9, max_goals_per_team=12)
    with_tail, tail = independent_poisson_score_matrix_with_tail(1.4, 0.9, max_goals_per_team=12)

    assert with_tail == existing
    assert tail >= 0.0
    assert sum(with_tail.values()) == pytest.approx(1.0)


def test_compact_index_contains_pointers_but_no_full_distribution():
    prediction = build_prospective_prediction(
        _record(),
        _snapshot(),
        activation_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        repository_commit_sha="head-sha",
    )

    index = build_compact_index([prediction], settlement_ids=set(), refreshed_at="now")

    assert index["prediction_count"] == 1
    assert index["predictions"][0]["prediction_path"].startswith("predictions/")
    assert index["predictions"][0]["settlement_path"] is None
    assert "score_matrix" not in index


def test_ranked_probability_score_is_owned_by_evaluation_kernel():
    assert ranked_probability_score(
        {"home": 0.5, "draw": 0.25, "away": 0.25}, "draw"
    ) == pytest.approx(((0.5 - 0.0) ** 2 + (0.75 - 1.0) ** 2) / 2.0)


def test_later_snapshot_cannot_backfill_an_earlier_cutoff():
    record = _record()
    snapshot = _snapshot(
        raw={
            **_raw_market(fetched_at="2026-09-08T09:00:00+00:00"),
        }
    )

    selected = select_legal_market_snapshot(record, snapshot)

    assert selected["snapshot"] is None
    assert selected["reason"] == "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"


def test_postkickoff_historical_recovery_snapshot_is_rejected():
    record = _record(kickoff="2026-09-08T12:00:00+00:00")
    recovered = {
        **_snapshot(),
        "captured_at": "2026-09-08T13:00:00+00:00",
        "input": {"source_snapshots": {"nowscore": {"snapshots": [_raw_market()]}}},
    }

    selected = select_legal_market_snapshot(record, recovered)

    assert selected["snapshot"] is None
    assert selected["reason"] == "POSTKICKOFF_HISTORICAL_RECOVERY_BLOCKED"


def test_unlisted_market_source_is_not_eligible_for_the_lane():
    record = _record()
    snapshot = {
        **_snapshot(),
        "input": {"source_snapshots": {"bsd": {"snapshots": [_raw_market()]}}},
    }

    selected = select_legal_market_snapshot(record, snapshot)

    assert selected["snapshot"] is None
    assert selected["reason"] == "NO_AUTHORIZED_FROZEN_SOURCE_SNAPSHOT"


def test_earlier_snapshot_wins_when_a_later_snapshot_is_present():
    record = _record()
    earlier = _raw_market(fetched_at="2026-09-08T07:59:00+00:00")
    later = _raw_market(fetched_at="2026-09-08T09:00:00+00:00")
    snapshot = {
        **_snapshot(raw=earlier),
        "input": {
            "source_snapshots": {
                "nowscore": {"snapshots": [earlier, later]},
            }
        },
    }

    selected = select_legal_market_snapshot(record, snapshot)

    assert selected["reason"] is None
    assert selected["captured_at"] == "2026-09-08T07:59:00+00:00"


def test_future_prediction_is_write_once_and_never_contains_settlement(tmp_path):
    record = _record()
    generated_at = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    prediction = build_prospective_prediction(
        record,
        _snapshot(),
        activation_at=generated_at,
        generated_at=generated_at,
        repository_commit_sha="head-sha",
    )

    first = persist_prediction(prediction, tmp_path)
    second = persist_prediction(deepcopy(prediction), tmp_path)

    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert prediction["generated_at"] < prediction["kickoff_at"]
    assert prediction["implementation_activated_at"] < prediction["kickoff_at"]
    assert prediction["production_enabled"] is False
    assert prediction["user_visible"] is False
    assert prediction["auto_promote"] is False
    assert prediction["solver_identity"]["version"] == "market_189.solver.v1"
    stored = json.loads(first["path"].read_text(encoding="utf-8"))
    assert "settlement" not in stored
    assert len(stored["score_matrix"]) == 441
    assert first["path"] == prediction_shard_path(prediction["prediction_id"], tmp_path / "predictions")
    assert first["path"].is_file()
    assert not (tmp_path / "predictions" / f"{prediction['prediction_id']}.json").exists()


def test_legacy_flat_and_future_sharded_predictions_share_one_loader_and_conflict_closed(tmp_path):
    prediction = build_prospective_prediction(
        _record(),
        _snapshot(),
        activation_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        repository_commit_sha="head-sha",
    )
    prediction_root = tmp_path / "predictions"
    prediction_root.mkdir()
    legacy_path = prediction_root / f"{prediction['prediction_id']}.json"
    legacy_bytes = (json.dumps(prediction, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    legacy_path.write_bytes(legacy_bytes)

    assert load_persisted_predictions(tmp_path) == [prediction]
    existing = persist_prediction(prediction, tmp_path)
    assert existing["status"] == "existing"
    assert existing["path"] == legacy_path
    sharded_path = prediction_shard_path(prediction["prediction_id"], prediction_root)
    sharded_path.parent.mkdir()
    sharded_path.write_bytes(legacy_bytes)
    assert load_persisted_predictions(tmp_path) == [prediction]
    assert legacy_path.read_bytes() == legacy_bytes

    conflicting = deepcopy(prediction)
    conflicting["match_key"] = "CONFLICTING-MATCH"
    conflicting["prediction_digest"] = prediction_digest(conflicting)
    conflicting["prediction_sha256"] = conflicting["prediction_digest"]
    sharded_path.write_text(json.dumps(conflicting, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(LaneConflictError):
        load_persisted_predictions(tmp_path)
    with pytest.raises(LaneConflictError):
        persist_prediction(prediction, tmp_path)


def test_future_prediction_shards_keep_directory_width_bounded_at_high_water(tmp_path):
    total = 5000
    for index in range(total):
        prediction = _synthetic_prediction(index)
        written = persist_prediction(prediction, tmp_path)
        assert written["path"] == prediction_shard_path(prediction["prediction_id"], tmp_path / "predictions")

    paths = iter_persisted_prediction_paths(tmp_path)
    widths: dict[str, int] = {}
    for path in paths:
        widths[path.parent.name] = widths.get(path.parent.name, 0) + 1
    assert len(paths) == total
    assert len(load_persisted_predictions(tmp_path)) == total
    assert not list((tmp_path / "predictions").glob("*.json"))
    assert len(widths) >= 32
    assert max(widths.values()) < 3000
    assert all(path.parent.name == prediction_shard_prefix(path.stem) for path in paths)


def test_repeated_lane_run_reuses_immutable_prediction_without_rewriting_it(tmp_path):
    record = _record()
    first = build_prospective_prediction(
        record,
        _snapshot(),
        activation_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        repository_commit_sha="first-sha",
    )
    second = build_prospective_prediction(
        record,
        _snapshot(),
        activation_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        repository_commit_sha="second-sha",
    )

    assert persist_prediction(first, tmp_path)["status"] == "created"
    result = persist_prediction(second, tmp_path)

    assert result["status"] == "existing"
    assert result["record"]["generated_at"] == first["generated_at"]
    assert json.loads(result["path"].read_text(encoding="utf-8"))["repository_commit_sha"] == "first-sha"


def test_matches_kicked_off_before_lane_activation_are_not_backfilled(tmp_path):
    old = _record(kickoff="2026-09-08T08:00:00+00:00")
    old["source_cutoff_at"] = "2026-09-08T07:00:00+00:00"
    old["prediction_created_at"] = "2026-09-08T07:01:00+00:00"
    old["freeze_created_at"] = "2026-09-08T07:02:00+00:00"
    outcome = run_lane(
        records=[old],
        snapshot_loader=lambda _: _snapshot(),
        output_root=tmp_path,
        now=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        activation_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        repository_commit_sha="head-sha",
    )

    assert outcome["completion_state"] == "PURE_MARKET_PROSPECTIVE_WIRED_NO_CURRENT_ROWS"
    assert outcome["skip_reasons"]["KICKOFF_BEFORE_LANE_ACTIVATION"] == 1
    assert load_persisted_predictions(tmp_path) == []


def test_settlement_is_separate_idempotent_and_uses_unique_match_observations(tmp_path):
    record = _record()
    prediction = build_prospective_prediction(
        record,
        _snapshot(),
        activation_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        generated_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        repository_commit_sha="head-sha",
    )
    result = {
        "status": "result_verified",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-09-08T13:00:00+00:00",
        "result_90m": {"home_goals": 1, "away_goals": 1},
    }

    assert persist_prediction(prediction, tmp_path)["status"] == "created"
    first = settle_prediction(
        prediction,
        result,
        settled_at=datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
    )
    second = settle_prediction(
        prediction,
        result,
        settled_at=datetime(2026, 9, 8, 15, 0, tzinfo=UTC),
    )
    assert persist_settlement(first, tmp_path)["status"] == "created"
    persisted = persist_settlement(second, tmp_path)
    assert persisted["status"] == "existing"
    assert persisted["settlement"]["evaluated_at"] == first["evaluated_at"]
    assert (tmp_path / "predictions" / prediction_shard_prefix(prediction["prediction_id"]) / f"{prediction['prediction_id']}.json").is_file()
    assert persist_settlement(first, tmp_path)["status"] == "existing"
    settlement_path = settlement_shard_path(prediction["prediction_id"], tmp_path / "settlements")
    assert settlement_path.is_file()
    assert not (tmp_path / "settlements" / f"{prediction['prediction_id']}.json").exists()
    expected = deepcopy(first)
    expected["settlement_digest"] = settlement_digest(first)
    assert load_persisted_settlements(tmp_path) == [expected]
    legacy_settlement_path = tmp_path / "settlements" / f"{prediction['prediction_id']}.json"
    legacy_settlement_path.write_bytes(settlement_path.read_bytes())
    assert load_persisted_settlements(tmp_path) == [expected]

    conflicting_settlement = deepcopy(expected)
    conflicting_settlement["metrics"] = deepcopy(conflicting_settlement["metrics"])
    conflicting_settlement["metrics"]["exact_top1"] = 0.0
    conflicting_settlement["settlement_digest"] = settlement_digest(conflicting_settlement)
    settlement_path.write_text(
        json.dumps(conflicting_settlement, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LaneConflictError):
        load_persisted_settlements(tmp_path)
    with pytest.raises(LaneConflictError):
        persist_settlement(first, tmp_path)

    duplicate_version = deepcopy(first)
    duplicate_version["prediction_id"] = "PME-DUPLICATE-VERSION"
    duplicate_version["prediction_digest"] = "another-frozen-version"
    summary = aggregate_settlements([first, duplicate_version])
    assert summary["records_seen"] == 2
    assert summary["unique_match_count"] == 1
    assert summary["duplicate_match_conflicts"] == []
    assert summary["metrics"]["score_1_1_top1_share"]["n"] == 1
