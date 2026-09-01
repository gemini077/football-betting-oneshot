from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import daily_schedule_workspace


def _fetched_row(
    business_date: str = "2026-09-01",
    *,
    kickoff_date: str | None = None,
) -> dict:
    kickoff_date = kickoff_date or (
        date.fromisoformat(business_date) + timedelta(days=1)
    ).isoformat()
    sales_url = (
        "https://cp.nowscore.com/buy/jingcai.aspx"
        f"?typeID=101&oddstype=2&date={business_date}"
    )
    return {
        "nowscore_id": 2913701,
        "home_team": "主队",
        "away_team": "客队",
        "home_team_en": "Home FC",
        "away_team_en": "Away FC",
        "kickoff_local": f"{kickoff_date}T00:30+08:00",
        "business_date": business_date,
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": sales_url,
        "match_number": "周二001",
        "match_number_source": "nowscore_public_jc_sales",
        "sales_row_id": "5510001",
        "cansale": "true",
        "jc_membership": "VERIFIED",
        "jc_membership_source": "nowscore_public_jc_sales",
        "jc_membership_evidence": {
            "source": "nowscore_public_jc_sales",
            "selected_date": business_date,
            "business_date": business_date,
            "sales_window": "11:00--次日11:00",
        },
        "source_surface": sales_url,
        "source_url": sales_url,
        "fetched_at": "2026-09-01T12:00:00+08:00",
        "date_provenance": {
            "expected_business_date": business_date,
            "source_date_value": f"{kickoff_date} 00:30",
            "business_date": business_date,
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": sales_url,
            "sales_window": "11:00--次日11:00",
        },
        "schedule_source_date": business_date,
        "schedule_source_date_format": "month_day",
    }


def _fetched_success(business_date: str = "2026-09-01") -> dict:
    sales_url = (
        "https://cp.nowscore.com/buy/jingcai.aspx"
        f"?typeID=101&oddstype=2&date={business_date}"
    )
    return {
        "source": "nowscore_public_jc",
        "primary_source": "nowscore_public_jc_sales",
        "url": sales_url,
        "source_surface": sales_url,
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": sales_url,
        "surface": "nowscore_public_jc_sales",
        "fetch_time": "2026-09-01T12:00:00+08:00",
        "fetched_at": "2026-09-01T12:00:00+08:00",
        "date": business_date,
        "business_date": business_date,
        "success": True,
        "status": "OK",
        "jc_contract": {
            "valid": True,
            "surface": "nowscore_public_jc_sales",
            "date_anchor": "SelDate + niDate header date",
            "sales_window": "11:00--次日11:00",
            "selected_date": business_date,
            "requested_date": business_date,
        },
        "business_date_contract": {
            "valid": True,
            "surface": "nowscore_public_jc_sales",
            "date_anchor": "SelDate + niDate header date",
            "sales_window": "11:00--次日11:00",
            "selected_date": business_date,
            "requested_date": business_date,
        },
        "jc_flagged_row_count": 1,
        "duplicate_nowscore_id_count": 0,
        "ambiguous_nowscore_id_count": 0,
        "matches": [_fetched_row(business_date)],
    }


def test_nowscore_schedule_payload_preserves_verified_fixture_provenance():
    payload = daily_schedule_workspace._nowscore_schedule_payload(
        "2026-09-01", _fetched_success()
    )

    assert payload["source"] == "nowscore_public_jc"
    assert payload["schedule_scope"] == "jc"
    assert payload["success"] is True
    assert payload["matches"][0]["matchId"] == "2913701"
    assert payload["matches"][0]["nowscore_id"] == 2913701
    assert payload["matches"][0]["jc_membership"] == "VERIFIED"
    assert payload["matches"][0]["jc_membership_source"] == "nowscore_public_jc_sales"
    assert payload["matches"][0]["matchNum"] == "周二001"
    assert payload["matches"][0]["sales_row_id"] == "5510001"
    assert payload["matches"][0]["cansale"] == "true"
    assert payload["matches"][0]["matchDate"] == "2026-09-02"
    assert payload["matches"][0]["source_surface"].startswith("https://cp.nowscore.com/buy/")


def test_nowscore_schedule_payload_accepts_next_calendar_day_kickoff():
    payload = daily_schedule_workspace._nowscore_schedule_payload(
        "2026-08-31", _fetched_success("2026-08-31")
    )

    assert payload["success"] is True
    assert payload["business_date"] == "2026-08-31"
    assert payload["matches"][0]["businessDate"] == "2026-08-31"
    assert payload["matches"][0]["matchDate"] == "2026-09-01"


def test_attach_nowscore_bindings_uses_current_jc_rows_without_legacy_schedule_fetch():
    payloads = [daily_schedule_workspace._nowscore_schedule_payload(
        "2026-09-01", _fetched_success()
    )]

    def prebind(home, away, kickoff, schedule, *, fixture=None):
        assert home == "主队"
        assert away == "客队"
        assert schedule[0]["nowscore_id"] == 2913701
        assert fixture is payloads[0]["matches"][0]
        return {
            "status": "EXACT_MATCH",
            "nowscore_id": 2913701,
            "match_confidence": 1.0,
            "home_team": "主队",
            "away_team": "客队",
        }

    with patch.object(
        daily_schedule_workspace, "fetch_nowscore_schedule", side_effect=AssertionError
    ), patch.object(daily_schedule_workspace, "prebind_match", side_effect=prebind):
        result = daily_schedule_workspace.attach_nowscore_bindings(payloads)

    assert result["status"] == "OK_PUBLIC_JC"
    assert result["bound"] == 1
    assert result["ambiguous"] == 0
    assert payloads[0]["matches"][0]["nowscoreMatchStatus"] == "EXACT_MATCH"


def test_main_keeps_both_universe_snapshots_failed_without_secondary_schedule_provider(tmp_path):
    failed = {
        "source": "nowscore_public_jc",
        "url": "https://live.nowscore.com/schedule.aspx?f=ft1",
        "source_surface": "https://live.nowscore.com/schedule.aspx?f=ft1",
        "backing_data_url": "https://live.nowscore.com/data/ft1.js",
        "fetch_time": "2026-09-01T12:00:00+08:00",
        "fetched_at": "2026-09-01T12:00:00+08:00",
        "date": "2026-09-01",
        "success": False,
        "matches": [],
        "status": "FETCH_ERROR",
        "error": "HTTP 567",
    }

    with patch.object(daily_schedule_workspace, "ROOT", tmp_path), \
        patch.object(daily_schedule_workspace, "fetch_nowscore_jc_schedule", side_effect=[failed, failed]), \
        patch.object(daily_schedule_workspace, "attach_nowscore_bindings", return_value={"status": "FETCH_ERROR"}), \
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
        assert saved["source"] == "nowscore_public_jc"
        assert saved["status"] == "FETCH_ERROR"
        assert saved["matches"] == []
