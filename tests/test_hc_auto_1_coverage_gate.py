import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.football_data.coverage_gate import ExactCoverageIdentityResolver, audit_fixture_set
from scripts.football_data.coverage_registry import CoverageRegistryBuilder


UTC = timezone.utc
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def result(
    match_id: int,
    *,
    competition: str = "competition:alpha",
    home: str = "team:alpha:home",
    away: str = "team:alpha:away",
    days_ago: int = 3,
) -> dict:
    kickoff = (NOW - timedelta(days=days_ago, hours=match_id % 4)).isoformat().replace("+00:00", "Z")
    return {
        "canonical_match_id": f"match:{competition}:{match_id}",
        "competition_id": competition,
        "season_id": "season:alpha:2026",
        "home_team_id": home,
        "away_team_id": away,
        "kickoff_at": kickoff,
        "eligible_for_team_strength": True,
        "quality": "A",
        "provider": "fixture-provider",
        "provenance": {"source_reliable": True, "synthetic": False},
    }


def fixture(match_id: str, league: str = "Alpha League", **extra: object) -> dict:
    row = {
        "matchId": match_id,
        "league": league,
        "homeTeam": "Alpha Home",
        "awayTeam": "Alpha Away",
        "kickoff": "2026-08-30T12:00:00+00:00",
        **extra,
    }
    return row


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        catalog = root / "coverage_catalog.json"
        manifest = root / "source_manifest.json"
        write_json(catalog, {
            "contract_version": "football_data_coverage_catalog.v1",
            "policy": {
                "minimum_history_matches_per_team": 5,
                "current_max_history_age_days": 60,
            },
            "adapter_capabilities": {
                "fixture-provider": {"automatic_import": True, "source_quality": "A"}
            },
            "competitions": [{
                "competition_key": "alpha",
                "canonical_competition_id": "competition:alpha",
                "canonical_name": "Alpha League",
                "country": "Fixtureland",
                "competition_type": "league",
                "aliases": ["Alpha League"],
            }],
        })
        write_json(manifest, {
            "provider": "fixture-provider",
            "captured_at": "2026-08-28T08:00:00Z",
            "commercial_use_review": "internal_analysis_only",
            "sources": [{
                "competition_key": "alpha",
                "provider_competition_id": "fixture:alpha",
                "provider_season_id": "2026",
                "season_status": "in_progress",
                "listed_match_count": 20,
                "parsed_result_count": 12,
                "source_completeness_status": "IN_PROGRESS",
                "result_coverage": "PARTIAL",
            }],
        })
        self.records = [result(index) for index in range(1, 7)]
        self.registry = CoverageRegistryBuilder(
            catalog_path=catalog,
            competition_registry_path=root / "no_competition_registry.json",
            manifest_paths=[manifest],
            historical_records=self.records,
            now=NOW,
        ).build()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def verified_ids(row: dict, *, home: str = "team:alpha:home", away: str = "team:alpha:away") -> dict:
        return {
            **row,
            "competition_id": "competition:alpha",
            "home_team_id": home,
            "away_team_id": away,
            "identity_verified": True,
            "resolution_method": "manual_verified",
        }

    def test_batch_returns_three_statuses_without_blocking_other_fixtures(self):
        rows = [
            self.verified_ids(fixture("supported")),
            self.verified_ids(fixture("degraded"), home="team:alpha:unknown"),
            fixture("unsupported", league="Not In Registry"),
        ]
        result_set = audit_fixture_set(rows, self.registry, historical_records=self.records, now=NOW)

        self.assertEqual(["SUPPORTED", "DEGRADED", "UNSUPPORTED"], [row["status"] for row in result_set["fixtures"]])
        self.assertIn("CURRENT_SEASON_PARTIAL", result_set["fixtures"][0]["warning_codes"])
        self.assertIn("CURRENT_SEASON_PARTIAL", result_set["fixtures"][0]["reason_codes"])
        self.assertEqual([], result_set["fixtures"][0]["blocking_reason_codes"])
        self.assertIn("HISTORY_INSUFFICIENT", result_set["fixtures"][1]["reason_codes"])
        self.assertIn("COMPETITION_UNSUPPORTED", result_set["fixtures"][2]["reason_codes"])
        self.assertEqual({"SUPPORTED": 1, "DEGRADED": 1, "UNSUPPORTED": 1}, result_set["summary"]["status_counts"])
        self.assertEqual(0, result_set["summary"]["blocked_count"])

    def test_known_competition_without_exact_identity_is_unsupported(self):
        result_set = audit_fixture_set([fixture("missing-identity")], self.registry, historical_records=self.records, now=NOW)
        row = result_set["fixtures"][0]
        self.assertEqual("UNSUPPORTED", row["status"])
        self.assertIn("IDENTITY_UNAVAILABLE", row["reason_codes"])
        self.assertFalse(row["historical_challenger_allowed"])

    def test_stale_team_history_degrades_without_removing_fixture(self):
        stale = [result(index, days_ago=120) for index in range(1, 7)]
        row = self.verified_ids(fixture("stale"))
        result_set = audit_fixture_set([row], self.registry, historical_records=stale, now=NOW)
        self.assertEqual("DEGRADED", result_set["fixtures"][0]["status"])
        self.assertIn("SOURCE_STALE", result_set["fixtures"][0]["reason_codes"])
        self.assertFalse(result_set["fixtures"][0]["historical_challenger_allowed"])

    def test_known_competition_with_unavailable_source_is_degraded(self):
        registry = dict(self.registry)
        registry["competitions"] = [dict(self.registry["competitions"][0])]
        registry["competitions"][0]["historical_match_count"] = 0
        registry["competitions"][0]["provider_source_availability"] = [{
            "automatic_import_capability": False,
            "failure_reason": ["SOURCE_UNAVAILABLE"],
        }]
        row = self.verified_ids(fixture("source-unavailable"))
        result_set = audit_fixture_set([row], registry, historical_records=[], now=NOW)
        self.assertEqual("DEGRADED", result_set["fixtures"][0]["status"])
        self.assertIn("SOURCE_UNAVAILABLE", result_set["fixtures"][0]["reason_codes"])
        self.assertEqual(0, result_set["summary"]["blocked_count"])

    def test_provider_team_ids_use_exact_reviewed_crosswalk(self):
        root = Path(self.temp.name)
        crosswalk = root / "crosswalk.json"
        write_json(crosswalk, {
            "mappings": [
                {
                    "competition": "competition:alpha",
                    "provider": "fixture-provider",
                    "provider_team_id": "home-provider-id",
                    "canonical_team_id": "team:alpha:home",
                    "verified": True,
                },
                {
                    "competition": "competition:alpha",
                    "provider": "fixture-provider",
                    "provider_team_id": "away-provider-id",
                    "canonical_team_id": "team:alpha:away",
                    "verified": True,
                },
            ]
        })
        resolver = ExactCoverageIdentityResolver(
            crosswalk_path=crosswalk,
            identity_evidence_path=root / "missing-evidence.json",
        )
        row = fixture(
            "provider-ids",
            provider="fixture-provider",
            home_provider_team_id="home-provider-id",
            away_provider_team_id="away-provider-id",
        )
        result_set = audit_fixture_set([row], self.registry, historical_records=self.records, identity_resolver=resolver, now=NOW)
        self.assertEqual("SUPPORTED", result_set["fixtures"][0]["status"])


if __name__ == "__main__":
    unittest.main()
