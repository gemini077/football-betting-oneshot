import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.base_prediction_jobs import sync_base_prediction_jobs


UTC = timezone.utc
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def history_row(index: int, *, days_ago: int = 3) -> dict:
    kickoff = (NOW - timedelta(days=days_ago, hours=index % 3)).isoformat().replace("+00:00", "Z")
    return {
        "canonical_match_id": f"match:alpha:{index}",
        "competition_id": "competition:alpha",
        "season_id": "season:alpha:2026",
        "home_team_id": "team:alpha:home",
        "away_team_id": "team:alpha:away",
        "kickoff_at": kickoff,
        "eligible_for_team_strength": True,
        "quality": "A",
        "provider": "fixture-provider",
        "provenance": {"source_reliable": True, "synthetic": False},
    }


def fixture(match_id: str, *, home: str = "team:alpha:home", away: str = "team:alpha:away", league: str = "Alpha League") -> dict:
    return {
        "matchId": match_id,
        "league": league,
        "homeTeam": "Alpha Home",
        "awayTeam": "Alpha Away",
        "kickoff": "2026-08-30T12:00:00+00:00",
        "competition_id": "competition:alpha",
        "home_team_id": home,
        "away_team_id": away,
        "identity_verified": True,
        "resolution_method": "manual_verified",
    }


class DailyCoverageIntegrationTests(unittest.TestCase):
    def test_coverage_is_attached_to_jobs_without_filtering_the_fixture_set(self):
        registry = {
            "contract_version": "historical_coverage_registry.v1",
            "policy": {"minimum_history_matches_per_team": 5, "current_max_history_age_days": 60},
            "competitions": [{
                "competition_id": "competition:alpha",
                "competition_key": "alpha",
                "canonical_name": "Alpha League",
                "aliases": ["Alpha League"],
                "provider_source_availability": [{
                    "automatic_import_capability": True,
                    "failure_reason": [],
                }],
                "historical_match_count": 12,
                "current_season_status": "in_progress",
            }],
        }
        rows = [
            fixture("supported"),
            fixture("degraded", home="team:alpha:missing"),
            fixture("unsupported", league="Outside Registry", home="", away=""),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / "prediction_universe" / "2026-08-29.json", {
                "schema_version": "1.0",
                "business_date": "2026-08-29",
                "status": "READY",
                "fixtures": rows,
            })
            ledger = sync_base_prediction_jobs(
                "2026-08-29",
                universe_root=root / "prediction_universe",
                jobs_root=root / "base_prediction_jobs",
                now=NOW,
                coverage_registry=registry,
                historical_records=[history_row(index) for index in range(1, 7)],
            )

        self.assertEqual(3, ledger["fixture_count"])
        self.assertEqual(3, ledger["job_count"])
        self.assertEqual({"SUPPORTED": 1, "DEGRADED": 1, "UNSUPPORTED": 1}, ledger["coverage_summary"]["status_counts"])
        self.assertEqual(0, ledger["coverage_summary"]["blocked_count"])
        self.assertTrue(ledger["coverage_summary"]["non_blocking"])
        self.assertEqual(
            ["SUPPORTED", "DEGRADED", "UNSUPPORTED"],
            [job["coverage_status"] for job in ledger["jobs"]],
        )
        self.assertTrue(all(job["status"] == "PENDING" for job in ledger["jobs"]))
        self.assertTrue(all(job["historical_challenger_allowed"] is (job["coverage_status"] == "SUPPORTED") for job in ledger["jobs"]))


if __name__ == "__main__":
    unittest.main()
