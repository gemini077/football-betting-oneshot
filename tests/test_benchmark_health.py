import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_health import build_health_summary, write_health_summary  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def comparison(
    comparison_id: str,
    *,
    scope: str = "prospective",
    origin: str = "production_new_freeze",
    status: str = "complete",
    same_snapshot: bool | None = True,
    synthetic: bool = False,
    excluded: bool = False,
    cohort: str = "primary",
    primary: bool = True,
    market: bool = True,
    simple: bool = True,
    champion: bool = True,
    created_at: str | None = None,
) -> dict:
    row = {
        "comparison_id": comparison_id,
        "match_key": f"MATCH-{comparison_id}",
        "benchmark_scope": scope,
        "prospective_origin": origin,
        "comparison_status": status,
        "same_snapshot": same_snapshot,
        "snapshot_consistent": same_snapshot is True,
        "synthetic": synthetic,
        "excluded_from_formal_metrics": excluded,
        "cohort": cohort,
        "primary_benchmark_eligible": primary,
        "checkpoint_stage": "T-30M" if cohort == "primary" else "T-2H",
        "market_evaluable": market,
        "simple_evaluable": simple,
        "champion_evaluable": champion,
        "metrics": {
            "market_reference": {
                "brier_score_1x2": 0.10,
                "log_loss_1x2": 0.20,
                "top1_accuracy_1x2": 1.0,
            },
            "simple_poisson": {
                "brier_score_1x2": 0.11,
                "log_loss_1x2": 0.21,
                "top1_accuracy_1x2": 1.0,
                "btts_hit": 1.0,
                "total_goal_absolute_error": 0.5,
                "expected_goal_error": 0.25,
                "score_top1": 1.0,
                "score_top3": 1.0,
                "score_top5": 1.0,
                "score_top10": 1.0,
            },
            "champion": {
                "brier_score_1x2": 0.12,
                "log_loss_1x2": 0.22,
                "top1_accuracy_1x2": 0.0,
                "btts_hit": 0.0,
                "total_goal_absolute_error": 1.5,
                "expected_goal_error": 0.75,
                "score_top1": 0.0,
                "score_top3": 1.0,
                "score_top5": 1.0,
                "score_top10": 1.0,
            },
        },
    }
    if created_at is not None:
        row["created_at"] = created_at
    return row


def test_empty_health_is_valid_and_does_not_create_files(tmp_path):
    benchmark_root = tmp_path / "benchmarks"
    summary = build_health_summary(
        benchmark_root=benchmark_root,
        production_state_path=benchmark_root / "production_state.json",
    )

    assert summary["production_start_sha"] == ""
    assert summary["production_start_at"] == ""
    assert summary["prospective_comparisons"] == 0
    assert summary["settled_comparisons"] == 0
    assert summary["primary_t30m"] == 0
    assert summary["secondary"] == 0
    assert summary["paired_3way_1x2"] == 0
    assert summary["paired_simple_vs_champion"] == 0
    assert summary["benchmark_errors"] == 0
    assert summary["last_benchmark_created_at"] is None
    assert summary["last_benchmark_settled_at"] is None
    assert not benchmark_root.exists()


def test_health_counts_only_new_formal_prospective_records(tmp_path):
    benchmark_root = tmp_path / "benchmarks"
    predictions = benchmark_root / "predictions"
    settlements = benchmark_root / "settlements"
    state_path = benchmark_root / "production_state.json"
    write_json(state_path, {
        "phase1_production_start": {
            "merge_sha": "merge-sha",
            "merged_at": "2026-08-10T07:00:56Z",
            "prospective_only": True,
        }
    })

    rows = [
        comparison("A", created_at="2026-08-10T08:00:00Z"),
        comparison("B", market=False, created_at="2026-08-10T08:01:00Z"),
        comparison("C", cohort="secondary", primary=False, created_at="2026-08-10T08:02:00Z"),
        comparison("D", status="incomplete", created_at="2026-08-10T08:03:00Z"),
        comparison("E", status="invalid_snapshot_mismatch", same_snapshot=False, created_at="2026-08-10T08:04:00Z"),
        comparison("H", scope="historical_exploratory", origin="historical_exploratory", excluded=True),
        comparison("S", synthetic=True, excluded=True),
    ]
    for row in rows:
        write_json(predictions / f"{row['comparison_id']}.json", row)
    for row in (rows[0], rows[2]):
        settlement = dict(row)
        settlement["settled_at"] = "2026-08-10T09:00:00Z"
        write_json(settlements / f"{row['comparison_id']}.json", settlement)

    summary = build_health_summary(
        benchmark_root=benchmark_root,
        production_state_path=state_path,
    )

    assert summary["production_start_sha"] == "merge-sha"
    assert summary["production_start_at"] == "2026-08-10T07:00:56Z"
    assert summary["prospective_comparisons"] == 3
    assert summary["settled_comparisons"] == 2
    assert summary["primary_t30m"] == 2
    assert summary["secondary"] == 1
    assert summary["paired_3way_1x2"] == 1
    assert summary["paired_simple_vs_champion"] == 1
    assert summary["market_unavailable"] == 1
    assert summary["simple_unavailable"] == 0
    assert summary["incomplete_comparisons"] == 1
    assert summary["snapshot_mismatches"] == 1
    assert summary["benchmark_errors"] == 0
    assert summary["last_benchmark_created_at"] == "2026-08-10T08:02:00Z"
    assert summary["last_benchmark_settled_at"] == "2026-08-10T09:00:00Z"


def test_health_output_is_derived_and_state_does_not_change_ledger_counts(tmp_path):
    benchmark_root = tmp_path / "benchmarks"
    predictions = benchmark_root / "predictions"
    row = comparison("A")
    write_json(predictions / "A.json", row)
    state_path = benchmark_root / "production_state.json"
    write_json(state_path, {"phase1_production_start": {"merge_sha": "one", "merged_at": "t1"}})

    first = build_health_summary(benchmark_root=benchmark_root, production_state_path=state_path)
    state_path.write_text(
        json.dumps({"phase1_production_start": {"merge_sha": "two", "merged_at": "t2"}}),
        encoding="utf-8",
    )
    second = build_health_summary(benchmark_root=benchmark_root, production_state_path=state_path)
    output_path = tmp_path / "health.json"
    written = write_health_summary(second, output_path)

    assert first["prospective_comparisons"] == second["prospective_comparisons"] == 1
    assert first["production_start_sha"] == "one"
    assert second["production_start_sha"] == "two"
    assert written == output_path
    assert json.loads(output_path.read_text(encoding="utf-8"))["prospective_comparisons"] == 1
