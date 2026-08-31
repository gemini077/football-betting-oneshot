from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import daily_schedule_workspace


def test_fallback_trade_schedule_preserves_fetch_failure_provenance():
    trade_result = {
        "source": "trade.500.com",
        "url": "https://trade.500.com/jczq/?playid=312&g=2",
        "fetch_time": "2026-08-31T07:41:13+00:00",
        "date": "2026-09-01",
        "success": False,
        "matches": [],
        "status": "FETCH_FAILED",
        "error": "HTTP 567",
    }

    with patch.object(daily_schedule_workspace, "fetch_trade_matches", return_value=trade_result):
        payload = daily_schedule_workspace.fallback_trade_schedule("2026-09-01", no_cache=True)

    assert payload["success"] is False
    assert payload["status"] == "FETCH_FAILED"
    assert payload["fallback_provenance"] == {
        "source": "trade.500.com",
        "url": "https://trade.500.com/jczq/?playid=312&g=2",
        "fetch_time": "2026-08-31T07:41:13+00:00",
        "date": "2026-09-01",
        "success": False,
        "status": "FETCH_FAILED",
        "parsed_match_count": 0,
        "error": "HTTP 567",
    }


def test_main_persists_fallback_provenance_when_primary_and_fallback_fail(tmp_path):
    primary_result = {
        "source": "sporttery.cn",
        "url": "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=tycp",
        "fetch_time": "2026-08-31T07:41:13+00:00",
        "success": False,
        "matches": [],
        "status": "API_FAILED",
    }
    trade_result = {
        "source": "trade.500.com",
        "url": "https://trade.500.com/jczq/?playid=312&g=2",
        "fetch_time": "2026-08-31T07:41:13+00:00",
        "success": False,
        "matches": [],
        "status": "NO_MATCHES_FOR_DATE",
    }

    with patch.object(daily_schedule_workspace, "ROOT", tmp_path), \
        patch.object(daily_schedule_workspace, "fetch_jingcai_odds", return_value=primary_result), \
        patch.object(daily_schedule_workspace, "fetch_trade_matches", return_value=trade_result), \
        patch.object(daily_schedule_workspace, "attach_nowscore_bindings", return_value={"status": "OK"}), \
        patch.object(daily_schedule_workspace, "update_prediction_universe", return_value={"status": "FETCH_FAILED"}), \
        patch.object(daily_schedule_workspace, "sync_base_prediction_jobs", return_value={"status": "BLOCKED_UNIVERSE"}), \
        patch.object(sys, "argv", [
            "daily_schedule_workspace.py",
            "--date",
            "2026-09-01",
            "--fetch-only",
        ]):
        assert daily_schedule_workspace.main() == 1

    snapshots = sorted((tmp_path / "data" / "schedule_updates").glob("*/*.json"))
    assert len(snapshots) == 2
    for snapshot_path in snapshots:
        saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert saved["source"] == "sporttery.cn"
        assert saved["status"] == "API_FAILED"
        assert saved["fallback_provenance"]["status"] == "NO_MATCHES_FOR_DATE"
        assert saved["fallback_provenance"]["parsed_match_count"] == 0
