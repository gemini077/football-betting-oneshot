import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.match_workspace as match_workspace
from scripts.prediction_universe import update_prediction_universe


def fixture(match_id: int, business_date: str | None = "2026-08-12") -> dict:
    row = {
        "matchId": str(match_id),
        "matchNum": f"周三{match_id:03d}",
        "matchDate": "2026-08-13",
        "matchTime": "03:00:00",
        "league": "测试联赛",
        "homeTeam": f"主队{match_id}",
        "awayTeam": f"客队{match_id}",
        "spf": {"home": 2.0, "draw": 3.0, "away": 3.5},
        "rqspf": None,
    }
    if business_date is not None:
        row["businessDate"] = business_date
    return row


def full_schedule(
    business_date: str = "2026-08-12", count: int = 14, source: str = "sporttery.cn"
) -> dict:
    return {
        "source": source,
        "date": business_date,
        "fetch_time": "2026-08-12T12:00:00+08:00",
        "success": True,
        "status": "OK_API",
        "matches": [fixture(index, business_date) for index in range(1, count + 1)],
    }


class PredictionUniverseTests(unittest.TestCase):
    def test_verified_nowscore_jc_payload_creates_deterministic_universe(self):
        payload = {
            "source": "nowscore_public_jc",
            "primary_source": "nowscore_public_jc_sales",
            "schedule_scope": "jc",
            "date": "2026-09-01",
            "business_date": "2026-09-01",
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
            "url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
            "fetch_time": "2026-09-01T12:00:00+08:00",
            "success": True,
            "status": "OK",
            "source_surface": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
            "business_date_contract": {
                "valid": True,
                "surface": "nowscore_public_jc_sales",
                "date_anchor": "SelDate + niDate header date",
                "sales_window": "11:00--次日11:00",
                "selected_date": "2026-09-01",
                "requested_date": "2026-09-01",
            },
            "jc_contract": {
                "valid": True,
                "surface": "nowscore_public_jc_sales",
                "date_anchor": "SelDate + niDate header date",
                "sales_window": "11:00--次日11:00",
                "selected_date": "2026-09-01",
                "requested_date": "2026-09-01",
            },
            "matches": [{
                "matchId": "2913701",
                "nowscoreId": 2913701,
                "nowscore_id": 2913701,
                "homeTeam": "主队",
                "awayTeam": "客队",
                "businessDate": "2026-09-01",
                "matchDate": "2026-09-01",
                "matchTime": "00:30",
                "matchNum": "周二001",
                "jc_membership": "VERIFIED",
                "jc_membership_source": "nowscore_public_jc_sales",
                "jc_membership_evidence": {
                    "source": "nowscore_public_jc_sales",
                    "selected_date": "2026-09-01",
                    "business_date": "2026-09-01",
                    "nowscore_id": 2913701,
                    "sales_row_id": "5510001",
                    "sales_window": "11:00--次日11:00",
                },
                "source_surface": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
                "source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
                "business_date_source": "nowscore_public_jc_sales",
                "business_date_source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
                "sales_row_id": "5510001",
                "match_number_source": "nowscore_public_jc_sales",
                "cansale": "true",
                "fetched_at": "2026-09-01T12:00:00+08:00",
                "date_provenance": {
                    "business_date": "2026-09-01",
                    "business_date_source": "nowscore_public_jc_sales",
                    "business_date_source_url": "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2026-09-01",
                    "sales_window": "11:00--次日11:00",
                    "expected_business_date": "2026-09-01",
                    "source_date_value": "2026-09-01 00:30",
                },
            }],
        }

        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-09-01", payload, root=Path(temp)
            )

        assert snapshot["status"] == "READY"
        assert snapshot["source"] == "nowscore_public_jc"
        assert snapshot["fixture_count"] == 1
        saved = snapshot["fixtures"][0]
        assert saved["matchId"] == "2913701"
        assert saved["nowscoreId"] == 2913701
        assert saved["nowscore_id"] == 2913701
        assert saved["jc_membership"] == "VERIFIED"
        assert saved["jc_membership_source"] == "nowscore_public_jc_sales"
        assert saved["jc_membership_evidence"]["source"] == "nowscore_public_jc_sales"
        assert saved["sales_row_id"] == "5510001"
        assert saved["source_surface"].startswith("https://cp.nowscore.com/buy/")
        assert saved["date_provenance"]["expected_business_date"] == "2026-09-01"

    def test_full_schedule_creates_fourteen_fixture_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-12", full_schedule(), root=Path(temp)
            )

            self.assertEqual("READY", snapshot["status"])
            self.assertEqual(14, snapshot["fixture_count"])
            self.assertEqual(14, len(snapshot["fixtures"]))

    def test_single_deep_fetch_cannot_replace_existing_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe("2026-08-12", full_schedule(), root=root)
            before = json.loads((root / "2026-08-12.json").read_text(encoding="utf-8"))
            deep = {
                "source": "500_deep",
                "success": True,
                "analysis_input_only": True,
                "matches": [fixture(1)],
            }

            snapshot = update_prediction_universe("2026-08-12", deep, root=root)

            self.assertEqual("READY", snapshot["status"])
            self.assertEqual(14, snapshot["fixture_count"])
            self.assertEqual(before, snapshot)
            self.assertEqual(before, json.loads((root / "2026-08-12.json").read_text(encoding="utf-8")))

    def test_failed_refresh_preserves_existing_ready_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe("2026-08-12", full_schedule(), root=root)

            snapshot = update_prediction_universe(
                "2026-08-12",
                {"source": "sporttery.cn", "success": False, "status": "FETCH_FAILED"},
                root=root,
            )

            self.assertEqual("READY", snapshot["status"])
            self.assertEqual(14, snapshot["fixture_count"])
            self.assertEqual("FETCH_FAILED", snapshot["last_fetch"]["status"])

    def test_first_failed_fetch_is_not_recorded_as_confirmed_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-12",
                {"source": "sporttery.cn", "success": False, "status": "FETCH_FAILED"},
                root=Path(temp),
            )

            self.assertEqual("FETCH_FAILED", snapshot["status"])
            self.assertEqual(0, snapshot["fixture_count"])

    def test_failed_refresh_persists_fallback_provenance(self):
        fallback_provenance = {
            "source": "trade.500.com",
            "url": "https://trade.500.com/jczq/?playid=312&g=2",
            "fetch_time": "2026-08-31T07:41:13+00:00",
            "date": "2026-09-01",
            "success": False,
            "status": "NO_MATCHES_FOR_DATE",
            "parsed_match_count": 0,
            "error": None,
        }

        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-09-01",
                {
                    "source": "sporttery.cn",
                    "success": False,
                    "status": "API_FAILED",
                    "fallback_provenance": fallback_provenance,
                },
                root=Path(temp),
            )

        self.assertEqual(fallback_provenance, snapshot["last_fetch"]["fallback_provenance"])

    def test_failed_nowscore_jc_refresh_preserves_ready_universe_and_records_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe("2026-08-12", full_schedule(), root=root)

            failed = update_prediction_universe(
                "2026-08-12",
                {
                    "source": "nowscore_public_jc",
                    "schedule_scope": "jc",
                    "success": False,
                    "status": "FETCH_ERROR",
                    "matches": [],
                    "fetch_time": "2026-08-12T13:00:00+08:00",
                },
                root=root,
            )

        self.assertEqual("READY", failed["status"])
        self.assertEqual(14, failed["fixture_count"])
        self.assertEqual("FETCH_FAILED", failed["last_fetch"]["status"])
        self.assertEqual("nowscore_public_jc", failed["last_fetch"]["source"])

    def test_successful_nowscore_jc_without_verified_membership_is_rejected(self):
        payload = {
            "source": "nowscore_public_jc",
            "schedule_scope": "jc",
            "success": True,
            "status": "OK",
            "jc_contract": {
                "valid": True,
                "filter_function": "SetLevel(3)",
                "row_index": 32,
                "predicate": "A[j][32] == 1",
            },
            "matches": [{
                "matchId": "1",
                "nowscoreId": 1,
                "homeTeam": "主队",
                "awayTeam": "客队",
                "businessDate": "2026-08-12",
                "jc_membership_source": "nowscore_public_jc",
                "source_surface": "surface",
                "source_url": "data",
                "date_provenance": {"expected_business_date": "2026-08-12"},
                "jc_membership_evidence": {"row_index": 32, "raw_value": 1},
            }],
        }

        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-12", payload, root=Path(temp)
            )

        self.assertEqual("FETCH_FAILED", snapshot["status"])
        self.assertEqual(0, snapshot["fixture_count"])

    def test_successful_empty_full_schedule_is_confirmed_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-12", full_schedule(count=0), root=Path(temp)
            )

            self.assertEqual("EMPTY_CONFIRMED", snapshot["status"])
            self.assertEqual(0, snapshot["fixture_count"])
            self.assertEqual(0, snapshot["source_fixture_count"])

    def test_later_successful_full_refresh_can_expand_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe(
                "2026-08-12", full_schedule(count=12), root=root
            )

            snapshot = update_prediction_universe(
                "2026-08-12", full_schedule(count=14), root=root
            )

            self.assertEqual("READY", snapshot["status"])
            self.assertEqual(14, snapshot["fixture_count"])

    def test_workspace_prefers_ready_universe_over_newer_legacy_single_match(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data"
            universe_root = data_root / "prediction_universe"
            universe = update_prediction_universe(
                "2026-08-12", full_schedule(), root=universe_root
            )
            universe_path = universe_root / "2026-08-12.json"
            universe_path.write_text(
                json.dumps(universe, ensure_ascii=False), encoding="utf-8"
            )

            legacy_path = (
                data_root
                / "fetch_runs"
                / "20260812_130000"
                / "20260812_130000_sporttery_2026-08-12.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps(
                    {
                        "source": "sporttery.cn",
                        "success": True,
                        "matches": [fixture(1)],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(match_workspace, "DATA", data_root):
                path, payload = match_workspace.latest_schedule("2026-08-12")

            self.assertEqual(universe_path, path)
            self.assertEqual("PREDICTION_UNIVERSE", payload["universe_source"])
            self.assertEqual(14, len(payload["matches"]))

    def test_cross_date_fixtures_are_excluded_and_diagnosed(self):
        payload = full_schedule("2026-08-13", count=0)
        payload["matches"] = [
            *[fixture(index, "2026-08-12") for index in range(1, 4)],
            *[fixture(index, "2026-08-13") for index in range(4, 8)],
        ]

        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-13", payload, root=Path(temp)
            )

        self.assertEqual("READY", snapshot["status"])
        self.assertEqual(7, snapshot["source_fixture_count"])
        self.assertEqual(4, snapshot["fixture_count"])
        self.assertEqual(3, snapshot["excluded_cross_date_count"])
        self.assertEqual(
            {"2026-08-13"},
            {row["businessDate"] for row in snapshot["fixtures"]},
        )

    def test_missing_business_date_uses_target_date(self):
        payload = full_schedule("2026-08-13", count=0)
        payload["matches"] = [fixture(1, None)]

        with tempfile.TemporaryDirectory() as temp:
            snapshot = update_prediction_universe(
                "2026-08-13", payload, root=Path(temp)
            )

        self.assertEqual("READY", snapshot["status"])
        self.assertEqual("2026-08-13", snapshot["fixtures"][0]["businessDate"])

    def test_unapproved_source_cannot_create_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = update_prediction_universe(
                "2026-08-12",
                full_schedule(source="500_deep"),
                root=root,
            )

        self.assertEqual("FETCH_FAILED", snapshot["status"])
        self.assertEqual(0, snapshot["fixture_count"])
        self.assertFalse(snapshot["persisted"])
        self.assertFalse((root / "2026-08-12.json").exists())

    def test_filtered_or_deep_marked_payload_cannot_update_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe("2026-08-12", full_schedule(), root=root)

            filtered = {**full_schedule(count=1), "match_filter": "主队1"}
            deep = {**full_schedule(count=1), "deep": True}
            filtered_snapshot = update_prediction_universe(
                "2026-08-12", filtered, root=root
            )
            deep_snapshot = update_prediction_universe(
                "2026-08-12", deep, root=root
            )

        self.assertEqual("READY", filtered_snapshot["status"])
        self.assertEqual(14, filtered_snapshot["fixture_count"])
        self.assertEqual("READY", deep_snapshot["status"])
        self.assertEqual(14, deep_snapshot["fixture_count"])

    def test_malformed_refresh_preserves_existing_ready_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            update_prediction_universe("2026-08-12", full_schedule(), root=root)

            snapshot = update_prediction_universe(
                "2026-08-12",
                {"source": "sporttery.cn", "success": True, "matches": [{"homeTeam": "only-home"}]},
                root=root,
            )

        self.assertEqual("READY", snapshot["status"])
        self.assertEqual(14, snapshot["fixture_count"])
        self.assertEqual("FETCH_FAILED", snapshot["last_fetch"]["status"])


if __name__ == "__main__":
    unittest.main()
