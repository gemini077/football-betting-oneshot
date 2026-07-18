import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prematch_task_registry import due_events, load_registry, register_match, sync_registry, update_checkpoint
from historical_market_recovery import recover_payload


def test_registry_survives_workspace_replacement_and_keeps_eight_nodes(tmp_path):
    registry_path = tmp_path / "tasks.json"
    workspace = tmp_path / "latest.json"
    reports = tmp_path / "reports"
    reports.mkdir()
    workspace.write_text(json.dumps({"matches": [{
        "id": "77", "home": "A", "away": "B", "kickoff": "2026-07-20 03:00",
        "report_state": "已分析", "report_url": "report.html",
    }]}), encoding="utf-8")
    first = sync_registry(registry_path, workspace, reports)
    assert first["task_count"] == 1
    task = next(iter(first["registry"]["tasks"].values()))
    assert len(task["checkpoints"]) == 8
    workspace.write_text('{"matches":[]}', encoding="utf-8")
    second = sync_registry(registry_path, workspace, reports)
    assert second["task_count"] == 1


def test_due_events_returns_every_elapsed_pending_checkpoint_once():
    registry = {"tasks": {}}
    match = {
        "id": "77", "home": "A", "away": "B", "kickoff": "2026-07-20 03:00",
        "report_state": "已分析", "report_url": "report.html",
    }
    canonical = register_match(registry, match)
    due = due_events(registry, datetime.fromisoformat("2026-07-20T01:30:00+08:00"))
    assert [row["_monitor_stage"] for row in due] == ["T-8H", "T-6H", "T-4H", "T-2H", "T-90M"]
    update_checkpoint(registry, canonical, "T-8H", "historical_recovery")
    assert "T-8H" not in [row["_monitor_stage"] for row in due_events(registry, datetime.fromisoformat("2026-07-20T01:30:00+08:00"))]


def test_historical_recovery_uses_last_quote_before_cutoff_and_drops_late_exchange():
    payload = {
        "ouzhi": {"bookmakers": [{"source_company_id": 8, "spf_current": {"home": 9, "draw": 9, "away": 9}}]},
        "yazhi": {"companies": [{"source_company_id": 8}]},
        "daxiao": {"companies": [{"source_company_id": 8}]},
        "touzhu": {"betfair": {"home": {"price": 2}}, "pl_flow": {"transactions": [{"x": 1}]}},
        "nowscore_context": {"company_trends": [{
            "source_company_id": 8,
            "markets": {
                "one_x_two": [
                    {"captured_at": "2026-07-19T18:00:00+08:00", "home": 2.1, "draw": 3.2, "away": 3.4},
                    {"captured_at": "2026-07-19T19:00:00+08:00", "home": 1.9, "draw": 3.3, "away": 3.8},
                ],
                "asian": [{"captured_at": "2026-07-19T18:20:00+08:00", "line_number": -0.5, "home_water": .9, "away_water": 1.0}],
                "total": [{"captured_at": "2026-07-19T18:30:00+08:00", "line_number": 2.5, "over": .88, "under": 1.02}],
            },
        }]},
    }
    result = recover_payload(payload, "2026-07-19T18:45:00+08:00")
    assert result["status"] == "recovered"
    assert payload["ouzhi"]["bookmakers"][0]["spf_current"]["home"] == 2.1
    assert payload["touzhu"]["betfair"] == {}
    assert payload["historical_checkpoint_recovery"]["current_price_used_as_history"] is False


def test_historical_recovery_reads_the_real_nowscore_context_location():
    payload = {
        "ouzhi": {"bookmakers": [{"source_company_id": 1}]},
        "yazhi": {"companies": [{"source_company_id": 1}]},
        "daxiao": {"companies": [{"source_company_id": 1}]},
        "context": {"company_trends": [{
            "source_company_id": 1,
            "markets": {
                "one_x_two": [{"captured_at": "2026-07-17T22:51:00+08:00", "home": 1.83, "draw": 3.5, "away": 3.4}],
                "asian": [{"captured_at": "2026-07-17T22:50:00+08:00", "line_number": -0.5, "home_water": .83, "away_water": .95}],
                "total": [{"captured_at": "2026-07-17T22:26:00+08:00", "line_number": 3.0, "over": .9, "under": .82}],
            },
        }]},
    }
    result = recover_payload(payload, "2026-07-17T23:00:00+08:00")
    assert result["status"] == "recovered"
    assert payload["ouzhi"]["bookmakers"][0]["spf_current"]["home"] == 1.83


def test_historical_recovery_drops_companies_and_quotes_after_cutoff():
    payload = {
        "ouzhi": {"bookmakers": [{"source_company_id": 1}, {"source_company_id": 2, "spf_current": {"home": 9}}]},
        "yazhi": {"companies": [{"source_company_id": 1}, {"source_company_id": 2}]},
        "daxiao": {"companies": [{"source_company_id": 1}, {"source_company_id": 2}]},
        "context": {"company_trends": [
            {"source_company_id": 1, "markets": {
                "one_x_two": [
                    {"captured_at": "2026-07-17T22:00:00+08:00", "home": 2.0, "draw": 3.0, "away": 4.0},
                    {"captured_at": "2026-07-18T00:00:00+08:00", "home": 9.0, "draw": 9.0, "away": 9.0},
                ],
                "asian": [{"captured_at": "2026-07-17T22:00:00+08:00", "line_number": -0.5, "home_water": .9, "away_water": 1.0}],
                "total": [{"captured_at": "2026-07-17T22:00:00+08:00", "line_number": 2.5, "over": .9, "under": 1.0}],
            }},
            {"source_company_id": 2, "markets": {
                "one_x_two": [{"captured_at": "2026-07-18T00:00:00+08:00", "home": 9.0, "draw": 9.0, "away": 9.0}],
                "asian": [], "total": [],
            }},
        ]},
    }
    result = recover_payload(payload, "2026-07-17T23:00:00+08:00")
    assert result["status"] == "recovered"
    assert [row["source_company_id"] for row in payload["ouzhi"]["bookmakers"]] == [1]
    assert len(payload["context"]["company_trends"]) == 1
    assert len(payload["context"]["company_trends"][0]["markets"]["one_x_two"]) == 1
