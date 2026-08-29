from __future__ import annotations

import csv
import json

from scripts.football_data.fe_dc1_model import COMPETITION_ID, PreRegisteredConfig
from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.run_fe_dc1 import run_and_write_fe_dc1
from scripts.football_data.storage import HistoricalResultStore


def _fixture_records() -> list[dict]:
    teams = ["team:a", "team:b", "team:c", "team:d", "team:e", "team:f"]
    records: list[dict] = []
    index = 0
    for home_index, home in enumerate(teams):
        for away_index, away in enumerate(teams):
            if home_index >= away_index:
                continue
            index += 1
            kickoff = f"2026-01-{index:02d}T12:00:00Z"
            records.append(
                make_historical_match_result(
                    canonical_match_id=f"match:{index}",
                    competition_id=COMPETITION_ID,
                    season_id="season:sweden-allsvenskan:2026",
                    home_team_id=home,
                    away_team_id=away,
                    kickoff_at=kickoff,
                    home_goals=1 + (home_index % 2),
                    away_goals=away_index % 2,
                    provider="fixture",
                    provider_match_id=f"fixture:{index}",
                    source_as_of_at=kickoff,
                    captured_at="2026-01-30T00:00:00Z",
                    source_record_ref=f"fixture:{index}",
                    source_reliable=True,
                    resolution_status="resolved",
                    resolution_method="manual_verified",
                    source="fixture",
                    entity_type="club",
                    match_type="league",
                )
            )
    return records


def test_fe_dc1_runner_writes_reproducible_artifacts_without_db_mutation(tmp_path):
    database_path = tmp_path / "historical_results.duckdb"
    store = HistoricalResultStore(database_path)
    store.append_many(_fixture_records())
    before_count = store.count()
    before_digest = store.dataset_digest()

    output_root = tmp_path / "output"
    report_path = tmp_path / "FE_DC_1.md"
    summary = run_and_write_fe_dc1(
        db_path=database_path,
        output_root=output_root,
        report_path=report_path,
        config=PreRegisteredConfig(
            warmup_matches=4,
            max_goals=8,
            optimizer_max_iter=300,
            rho_bounds=(-0.05, 0.05),
        ),
    )

    assert summary["status"] == "READY_FOR_ACCEPTANCE"
    assert summary["research_only"] is True
    assert summary["production_mutation"] is False
    assert summary["integrity"]["prediction_count"] == 10
    assert summary["integrity"]["all_history_strictly_pre_match"] is True
    assert summary["integrity"]["all_score_matrices_sum_to_one"] is True
    assert summary["integrity"]["all_optimizer_fits_converged"] is True
    assert "predictions" not in json.loads((output_root / "fe_dc1_results_summary.json").read_text(encoding="utf-8"))
    assert len(json.loads((output_root / "fe_dc1_predictions.json").read_text(encoding="utf-8"))) == 10
    with (output_root / "fe_dc1_predictions.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert "dc_score_matrix_json" in header
    assert "rho0_score_matrix_json" in header
    assert "Held-out metrics" in report_path.read_text(encoding="utf-8")

    assert store.count() == before_count
    assert store.dataset_digest() == before_digest
