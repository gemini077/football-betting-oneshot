import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.daily_schedule_workspace as daily_schedule_workspace
from scripts.base_prediction_jobs import sync_base_prediction_jobs


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 14, 0, tzinfo=TZ)


def fixture(
    match_id: str | None,
    index: int,
    *,
    kickoff: str = "2026-08-13T03:00:00+08:00",
    league: str = "Regional Test League",
) -> dict:
    row = {
        "matchNum": f"T{index:03d}",
        "businessDate": "2026-08-12",
        "matchDate": kickoff[:10],
        "matchTime": kickoff[11:19],
        "league": league,
        "homeTeam": f"Home {index}",
        "awayTeam": f"Away {index}",
    }
    if match_id is not None:
        row["matchId"] = match_id
    return row


def universe_payload(
    business_date: str = "2026-08-12",
    fixtures: list[dict] | None = None,
    status: str = "READY",
) -> dict:
    rows = list(fixtures or [])
    return {
        "schema_version": "1.0",
        "business_date": business_date,
        "status": status,
        "source": "sporttery.cn",
        "fetched_at": "2026-08-12T12:00:00+08:00",
        "fixture_count": len(rows),
        "fixtures": rows,
    }


def write_universe(root: Path, payload: dict) -> None:
    path = root / f"{payload['business_date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class BasePredictionJobsTests(unittest.TestCase):
    def sync(self, root: Path, *, now: datetime = NOW) -> dict:
        return sync_base_prediction_jobs(
            "2026-08-12",
            universe_root=root / "prediction_universe",
            jobs_root=root / "base_prediction_jobs",
            now=now,
        )

    def test_ready_universe_creates_one_job_per_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(
                fixtures=[fixture(str(index), index) for index in range(1, 15)]
            ))

            ledger = self.sync(root)

        self.assertEqual("READY", ledger["status"])
        self.assertEqual(14, ledger["fixture_count"])
        self.assertEqual(14, ledger["job_count"])
        self.assertEqual(14, len(ledger["jobs"]))
        self.assertEqual(14, len({job["job_id"] for job in ledger["jobs"]}))

    def test_repeated_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(
                fixtures=[fixture(str(index), index) for index in range(1, 15)]
            ))
            first = self.sync(root)
            second = self.sync(root)

        self.assertEqual(14, second["job_count"])
        self.assertEqual(
            [job["job_id"] for job in first["jobs"]],
            [job["job_id"] for job in second["jobs"]],
        )
        self.assertEqual(
            [job["created_at"] for job in first["jobs"]],
            [job["created_at"] for job in second["jobs"]],
        )

    def test_non_popular_leagues_are_not_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(
                fixtures=[fixture(str(index), index, league="Amateur County Cup") for index in range(1, 15)]
            ))

            ledger = self.sync(root)

        self.assertEqual(14, ledger["job_count"])
        self.assertEqual({"Amateur County Cup"}, {job["league"] for job in ledger["jobs"]})

    def test_empty_confirmed_universe_creates_empty_daily_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(status="EMPTY_CONFIRMED"))

            ledger = self.sync(root)

        self.assertEqual("EMPTY_CONFIRMED", ledger["status"])
        self.assertEqual(0, ledger["fixture_count"])
        self.assertEqual(0, ledger["job_count"])
        self.assertEqual([], ledger["jobs"])

    def test_failed_universe_blocks_without_fabricating_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(status="FETCH_FAILED"))

            ledger = self.sync(root)

        self.assertEqual("BLOCKED_UNIVERSE", ledger["status"])
        self.assertEqual(0, ledger["fixture_count"])
        self.assertEqual(0, ledger["job_count"])
        self.assertEqual([], ledger["jobs"])

    def test_missing_universe_blocks_without_fabricating_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = self.sync(Path(temp))

        self.assertEqual("BLOCKED_UNIVERSE", ledger["status"])
        self.assertEqual(0, ledger["job_count"])
        self.assertEqual([], ledger["jobs"])

    def test_new_job_after_kickoff_is_marked_missed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_universe(root / "prediction_universe", universe_payload(
                fixtures=[fixture("past-1", 1, kickoff="2026-08-12T13:59:00+08:00")]
            ))

            ledger = self.sync(root)

        self.assertEqual("MISSED_PREMATCH_WINDOW", ledger["jobs"][0]["status"])
        self.assertEqual(0, ledger["pending_count"])
        self.assertEqual(1, ledger["missed_prematch_count"])

    def test_universe_expansion_preserves_existing_identity_and_creation_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial = [fixture(str(index), index) for index in range(1, 13)]
            write_universe(root / "prediction_universe", universe_payload(fixtures=initial))
            first = self.sync(root)
            created = {job["job_id"]: job["created_at"] for job in first["jobs"]}

            expanded = initial + [fixture("13", 13), fixture("14", 14)]
            write_universe(root / "prediction_universe", universe_payload(fixtures=expanded))
            second = self.sync(root)

        self.assertEqual(14, second["job_count"])
        self.assertEqual(12, len(set(created) & {job["job_id"] for job in second["jobs"]}))
        for job in second["jobs"]:
            if job["job_id"] in created:
                self.assertEqual(created[job["job_id"]], job["created_at"])

    def test_existing_non_pending_states_are_not_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [fixture("pred-1", 1), fixture("frozen-1", 2)]
            write_universe(root / "prediction_universe", universe_payload(fixtures=rows))
            first = self.sync(root)
            first["jobs"][0]["status"] = "PREDICTED"
            first["jobs"][0]["prediction_id"] = "prediction-1"
            first["jobs"][1]["status"] = "FROZEN"
            ledger_path = root / "base_prediction_jobs" / "2026-08-12.json"
            ledger_path.write_text(json.dumps(first, indent=2), encoding="utf-8")

            second = self.sync(root, now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ))

        statuses = {job["match_id"]: job["status"] for job in second["jobs"]}
        self.assertEqual("PREDICTED", statuses["pred-1"])
        self.assertEqual("FROZEN", statuses["frozen-1"])
        self.assertEqual("prediction-1", second["jobs"][0]["prediction_id"])

    def test_missing_match_id_uses_existing_canonical_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = fixture(None, 1)
            write_universe(root / "prediction_universe", universe_payload(fixtures=[row]))
            first = self.sync(root)
            second = self.sync(root)

        self.assertTrue(first["jobs"][0]["job_id"].startswith("BASE-2026-08-12-FBOS-"))
        self.assertEqual(first["jobs"][0]["job_id"], second["jobs"][0]["job_id"])

    def test_daily_schedule_success_triggers_base_job_sync(self):
        def fetched(business_date: str, nowscore_id: int) -> dict:
            sales_url = (
                "https://cp.nowscore.com/buy/jingcai.aspx"
                f"?typeID=101&oddstype=2&date={business_date}"
            )
            kickoff_date = (
                datetime.fromisoformat(business_date) + timedelta(days=1)
            ).date().isoformat()
            return {
                "source": "nowscore_public_jc",
                "primary_source": "nowscore_public_jc_sales",
                "url": sales_url,
                "source_surface": sales_url,
                "business_date_source": "nowscore_public_jc_sales",
                "business_date_source_url": sales_url,
                "surface": "nowscore_public_jc_sales",
                "fetch_time": "2026-08-12T12:00:00+08:00",
                "fetched_at": "2026-08-12T12:00:00+08:00",
                "date": business_date,
                "business_date": business_date,
                "success": True,
                "status": "OK",
                "business_date_contract": {
                    "valid": True,
                    "surface": "nowscore_public_jc_sales",
                    "date_anchor": "SelDate + niDate header date",
                    "sales_window": "11:00--次日11:00",
                    "selected_date": business_date,
                    "requested_date": business_date,
                },
                "jc_contract": {
                    "valid": True,
                    "surface": "nowscore_public_jc_sales",
                    "date_anchor": "SelDate + niDate header date",
                    "sales_window": "11:00--次日11:00",
                    "selected_date": business_date,
                    "requested_date": business_date,
                },
                "matches": [{
                    "nowscore_id": nowscore_id,
                    "home_team": "Home FC",
                    "away_team": "Away FC",
                    "home_team_en": "Home FC",
                    "away_team_en": "Away FC",
                    "kickoff_local": f"{kickoff_date}T03:00+08:00",
                    "business_date": business_date,
                    "business_date_source": "nowscore_public_jc_sales",
                    "business_date_source_url": sales_url,
                    "match_number": f"周三{nowscore_id:03d}",
                    "match_number_source": "nowscore_public_jc_sales",
                    "sales_row_id": str(nowscore_id),
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
                    "fetched_at": "2026-08-12T12:00:00+08:00",
                    "date_provenance": {
                        "expected_business_date": business_date,
                        "business_date": business_date,
                        "business_date_source": "nowscore_public_jc_sales",
                        "business_date_source_url": sales_url,
                        "sales_window": "11:00--次日11:00",
                    },
                    "schedule_source_date": business_date,
                    "schedule_source_date_format": "month_day",
                }],
            }

        universe_result = {
            "status": "READY",
            "source": "nowscore_public_jc",
            "fetched_at": "2026-08-12T12:00:00+08:00",
            "source_fixture_count": 1,
            "fixture_count": 1,
            "excluded_cross_date_count": 0,
        }
        job_result = {
            "status": "READY",
            "fixture_count": 1,
            "job_count": 1,
            "pending_count": 1,
            "missed_prematch_count": 0,
        }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(daily_schedule_workspace, "ROOT", root), \
                patch.object(daily_schedule_workspace, "fetch_nowscore_jc_schedule", side_effect=[
                    fetched("2026-08-12", 2913701), fetched("2026-08-13", 2913702),
                ]), \
                patch.object(daily_schedule_workspace, "attach_nowscore_bindings", return_value={"status": "OK"}), \
                patch.object(daily_schedule_workspace, "update_prediction_universe", side_effect=[universe_result, universe_result]), \
                patch.object(daily_schedule_workspace, "sync_base_prediction_jobs", side_effect=[job_result, job_result]) as sync, \
                patch("sys.argv", ["daily_schedule_workspace.py", "--date", "2026-08-12", "--fetch-only"]):
                result = daily_schedule_workspace.main()

        self.assertEqual(0, result)
        self.assertEqual(["2026-08-12", "2026-08-13"], [call.args[0] for call in sync.call_args_list])


if __name__ == "__main__":
    unittest.main()
