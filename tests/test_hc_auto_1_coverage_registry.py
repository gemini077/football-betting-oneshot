import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.football_data.coverage_registry import CoverageRegistryBuilder


UTC = timezone.utc
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def result(match_id: int, *, competition: str = "competition:alpha", days_ago: int = 3) -> dict:
    kickoff = (NOW - timedelta(days=days_ago, hours=match_id)).isoformat().replace("+00:00", "Z")
    return {
        "canonical_match_id": f"match:alpha:{match_id}",
        "competition_id": competition,
        "season_id": "season:alpha:2026",
        "home_team_id": "team:alpha:home" if match_id % 2 else "team:alpha:third",
        "away_team_id": "team:alpha:away" if match_id % 2 else "team:alpha:home",
        "kickoff_at": kickoff,
        "eligible_for_team_strength": True,
        "quality": "A",
        "provider": "fixture-provider",
        "provenance": {"source_reliable": True, "synthetic": False},
    }


class CoverageRegistryBuilderTests(unittest.TestCase):
    def test_manifest_and_history_are_aggregated_into_versioned_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = root / "coverage_catalog.json"
            manifest = root / "source_manifest.json"
            write_json(catalog, {
                "contract_version": "football_data_coverage_catalog.v1",
                "policy": {
                    "minimum_history_matches_per_team": 5,
                    "current_max_history_age_days": 60,
                },
                "adapter_capabilities": {
                    "fixture-provider": {
                        "automatic_import": True,
                        "source_quality": "A",
                        "commercial_use_review": "internal_analysis_only",
                    }
                },
                "competitions": [
                    {
                        "competition_key": "alpha",
                        "canonical_competition_id": "competition:alpha",
                        "canonical_name": "Alpha League",
                        "country": "Fixtureland",
                        "competition_type": "league",
                        "aliases": ["Alpha League"],
                    },
                    {
                        "competition_key": "beta",
                        "canonical_competition_id": "competition:beta",
                        "canonical_name": "Beta League",
                        "country": "Fixtureland",
                        "competition_type": "league",
                        "aliases": ["Beta League"],
                    },
                ],
            })
            write_json(manifest, {
                "contract_version": "source_manifest.v1",
                "provider": "fixture-provider",
                "captured_at": "2026-08-28T08:00:00Z",
                "license": "fixture-license",
                "commercial_use_review": "internal_analysis_only",
                "sources": [
                    {
                        "competition_key": "alpha",
                        "provider_competition_id": "fixture:alpha",
                        "provider_season_id": "2025",
                        "provider_season_name": "2025",
                        "season_status": "completed",
                        "listed_match_count": 10,
                        "parsed_result_count": 10,
                        "source_completeness_status": "COMPLETE",
                        "result_coverage": "SUPPORTED",
                        "raw_sha256": "a" * 64,
                    },
                    {
                        "competition_key": "alpha",
                        "provider_competition_id": "fixture:alpha",
                        "provider_season_id": "2026",
                        "provider_season_name": "2026",
                        "season_status": "in_progress",
                        "listed_match_count": 20,
                        "parsed_result_count": 12,
                        "source_completeness_status": "IN_PROGRESS",
                        "result_coverage": "PARTIAL",
                        "current_season_coverage": "PARTIAL",
                        "raw_sha256": "b" * 64,
                    },
                ],
            })

            registry = CoverageRegistryBuilder(
                catalog_path=catalog,
                competition_registry_path=root / "no_competition_registry.json",
                manifest_paths=[manifest, manifest],
                historical_records=[result(index) for index in range(1, 7)],
                now=NOW,
            ).build()

        self.assertEqual("historical_coverage_registry.v1", registry["contract_version"])
        self.assertEqual(2, registry["competition_count"])
        alpha = next(row for row in registry["competitions"] if row["competition_id"] == "competition:alpha")
        self.assertEqual(6, alpha["historical_match_count"])
        self.assertEqual(3, alpha["team_count"])
        self.assertEqual(1.0, alpha["identity_coverage"]["ratio"])
        self.assertEqual(["2025", "2026"], alpha["seasons_available"])
        self.assertEqual("2025", alpha["latest_completed_season"])
        self.assertEqual("in_progress", alpha["current_season_status"])
        self.assertTrue(alpha["automatic_import_capability"])
        self.assertEqual("internal_analysis_only", alpha["commercial_use_restrictions"]["commercial_use_review"])
        self.assertEqual(2, len(alpha["provider_source_availability"]))
        self.assertEqual("2026-08-28T08:00:00Z", alpha["last_successful_refresh"])

        beta = next(row for row in registry["competitions"] if row["competition_id"] == "competition:beta")
        self.assertEqual(0, beta["historical_match_count"])
        self.assertIn("SOURCE_UNAVAILABLE", beta["failure_reason"])


if __name__ == "__main__":
    unittest.main()
