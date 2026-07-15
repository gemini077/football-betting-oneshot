import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from live_ev_profile import publish_live_ev_profiles  # noqa: E402
from generate_analysis_report import main as generate_report_main  # noqa: E402
from build_public_site import PUBLIC_DATA_DIRS  # noqa: E402


def payload_with_candidate(*, conservative=0.53, confirmed=True):
    return {
        "report": {
            "model_name": "Football Betting OneShot",
            "model_version": "v0.8.0",
            "analysis_timestamp": "2026-07-14T17:00:00+08:00",
        },
        "match": {
            "live_match_id": "5503037",
            "home": "法国",
            "away": "西班牙",
            "competition": "测试赛事",
        },
        "betting": {
            "candidates": [{
                "name": "全场大2.5",
                "live_ev_profile": {
                    "active": True,
                    "overlay_primary": True,
                    "contract": {
                        "match_id": "5503037",
                        "market_code": "2",
                        "market_name": "全场大小",
                        "child_market_code": "2",
                        "market_id": "market-total",
                        "handicap_line": "2.5",
                        "selection_code": "Over",
                        "selection_name": "大",
                        "contract_type": "binary_no_push",
                    },
                    "probability": {
                        "point": 0.56,
                        "conservative": conservative,
                        "confirmed_model_output": confirmed,
                        "source": "dc_calibrated_prematch_v0.7",
                        "calibration_status": "temporal_holdout_calibrated",
                    },
                    "price": {"max_quote_age_ms": 15000},
                    "execution": {"minimum_conservative_ev": 0.02},
                },
            }],
        },
    }


class LiveEvProfileTests(unittest.TestCase):
    def test_public_site_includes_live_ev_profiles(self):
        self.assertIn("live_ev_profiles", PUBLIC_DATA_DIRS)

    def test_publishes_history_and_current_without_execution_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = publish_live_ev_profiles(
                payload_with_candidate(),
                output_root=root,
                now=datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            )
            self.assertEqual("published", result["status"])
            current = json.loads((root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertTrue(current["active"])
            self.assertEqual(0.56, current["probability"]["point"])
            self.assertEqual(0.53, current["probability"]["conservative"])
            self.assertEqual("2.5", current["contract"]["handicap_line"])
            self.assertFalse(current["execution_authorized"])
            self.assertFalse(current["lock_state_changed"])
            self.assertFalse(current["bankroll_state_changed"])
            self.assertTrue(list((root / "history" / "20260714_090000").glob("*.json")))
            index = json.loads((root / "current" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(index["profiles"]))
            self.assertEqual("5503037", index["profiles"][0]["match"]["match_id"])
            self.assertFalse(index["execution_authorized"])

    def test_invalid_probability_replaces_known_match_with_inactive_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = publish_live_ev_profiles(payload_with_candidate(confirmed=False), output_root=root)
            current = json.loads((root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertEqual("published", result["status"])
            self.assertFalse(current["active"])
            self.assertEqual("invalid_live_ev_candidate", current["inactive_reason"])
            self.assertIsNone(current["probability"])

    def test_no_candidate_clears_stale_profile_for_known_live_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = payload_with_candidate()
            publish_live_ev_profiles(payload, output_root=root)
            payload["betting"]["candidates"] = []
            publish_live_ev_profiles(payload, output_root=root)
            current = json.loads((root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertFalse(current["active"])
            self.assertEqual("no_complete_live_ev_profile", current["inactive_reason"])

    def test_analysis_profile_publishes_without_betting_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = payload_with_candidate()
            profile = payload["betting"]["candidates"][0]["live_ev_profile"]
            payload["live_ev_profiles"] = [profile]
            payload["betting"]["candidates"] = []
            result = publish_live_ev_profiles(payload, output_root=root)
            current = json.loads((root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertEqual("published", result["status"])
            self.assertTrue(current["active"])
            self.assertEqual(0.56, current["probability"]["point"])
            self.assertEqual([], payload["betting"]["candidates"])
            self.assertFalse(current["execution_authorized"])

    def test_multiple_candidates_require_exactly_one_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = payload_with_candidate()
            duplicate = json.loads(json.dumps(payload["betting"]["candidates"][0]))
            payload["betting"]["candidates"][0]["live_ev_profile"]["overlay_primary"] = False
            duplicate["live_ev_profile"]["overlay_primary"] = False
            duplicate["live_ev_profile"]["contract"]["selection_code"] = "Under"
            payload["betting"]["candidates"].append(duplicate)
            root = Path(tmp)
            publish_live_ev_profiles(payload, output_root=root)
            current = json.loads((root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertFalse(current["active"])
            self.assertEqual("ambiguous_multiple_live_ev_candidates", current["inactive_reason"])

    def test_report_generator_automatically_publishes_profile(self):
        manifest = ROOT / "data" / "fetch_runs" / "20260714_041424" / "20260714_041424_fetch_manifest.json"
        self.assertTrue(manifest.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(payload_with_candidate(), ensure_ascii=False), encoding="utf-8")
            report_root = root / "reports"
            profile_root = root / "profiles"
            argv = [
                "generate_analysis_report.py",
                "--fetch-manifest", str(manifest),
                "--analysis-json", str(analysis_path),
                "--output-root", str(report_root),
                "--profile-output-root", str(profile_root),
            ]
            with patch("sys.argv", argv), redirect_stdout(StringIO()):
                self.assertEqual(0, generate_report_main())
            current = json.loads((profile_root / "current" / "5503037.json").read_text(encoding="utf-8"))
            self.assertTrue(current["active"])
            report_payload = next(report_root.glob("*/*.json"))
            generated = json.loads(report_payload.read_text(encoding="utf-8"))
            self.assertEqual("published", generated["report"]["live_ev_profile_publication"]["status"])


if __name__ == "__main__":
    unittest.main()

