import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_baseline_synthetic_smoke import run_synthetic_smoke  # noqa: E402


def test_complete_synthetic_flow_is_marked_and_excluded(tmp_path):
    result = run_synthetic_smoke(output_root=tmp_path)

    assert result["comparison"]["comparison_status"] == "complete"
    assert result["settlement"]["synthetic"] is True
    assert result["settlement"]["excluded_from_formal_metrics"] is True
    assert result["formal_summary"]["formal_records"] == 0
    assert len(result["metrics"]["metrics"]) == 3
    assert list((tmp_path / "predictions").glob("*.json"))
    assert list((tmp_path / "settlements").glob("*.json"))
    metrics_paths = list((tmp_path / "summaries").glob("*-synthetic-metrics.json"))
    assert metrics_paths
    saved = json.loads(metrics_paths[0].read_text(encoding="utf-8"))
    assert saved["synthetic"] is True
    assert saved["excluded_from_formal_metrics"] is True
