import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-pages.yml"


def _workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_deploy_pages_keeps_half_hour_schedule_and_uses_production_cycle():
    text = _workflow_text()

    assert 'cron: "*/30 * * * *"' in text
    assert "run: python scripts/automation_cycle.py\n" in text
    assert "automation_cycle.py --date" not in text
    assert "FBOS_DATE" not in text
    assert "Resolve China business date" not in text


def test_deploy_pages_persists_mvp_durable_state_without_site():
    text = _workflow_text()
    paths_match = re.search(r"paths=\(([^)]*)\)", text)
    assert paths_match, "durable path allowlist is missing"
    durable_paths = paths_match.group(1)

    for required in (
        "data/prediction_universe",
        "data/base_prediction_jobs",
        "data/model_governance/predictions",
        "data/model_governance/input_snapshots",
        "data/model_governance/prediction_exclusions",
        "data/prospective",
        "data/prediction_dashboard",
        "data/product_runtime",
    ):
        assert required in durable_paths
    assert "site" not in durable_paths
    assert "actions/upload-pages-artifact@v3" in text
    assert "actions/deploy-pages@v4" in text


def test_production_entry_imports_without_football_data_home():
    env = os.environ.copy()
    env.pop("FOOTBALL_DATA_HOME", None)
    code = (
        "import sys; "
        "sys.path.insert(0, 'scripts'); "
        "import automation_cycle, base_prediction_jobs, prediction_dashboard"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
