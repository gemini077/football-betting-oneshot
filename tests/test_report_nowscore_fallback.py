from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_analysis_report import deep_file, display_beijing_time  # noqa: E402


def test_report_uses_nowscore_snapshot_when_500_deep_is_missing(tmp_path):
    manifest = {
        "sources": {
            "nowscore": {
                "status": "OK",
                "matches": [{"file": "data/fetch_runs/run/nowscore.json"}],
            }
        }
    }
    assert deep_file(manifest, tmp_path) == tmp_path / "data/fetch_runs/run/nowscore.json"


def test_report_keeps_500_deep_precedence_when_both_exist(tmp_path):
    manifest = {
        "sources": {
            "500_deep": {"matches": [{"file": "data/fetch_runs/run/500.json"}]},
            "nowscore": {"matches": [{"file": "data/fetch_runs/run/nowscore.json"}]},
        }
    }
    assert deep_file(manifest, tmp_path) == tmp_path / "data/fetch_runs/run/500.json"


def test_report_displays_utc_snapshot_as_beijing_time():
    assert display_beijing_time("2026-07-16T15:53:25+00:00") == "2026-07-16 23:53:25 北京时间"
