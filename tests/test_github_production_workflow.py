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
        "import automation_cycle, base_prediction_jobs, prediction_dashboard, production_health_watch"
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


def test_durable_state_sync_happens_before_cycle_and_not_after_generated_commit():
    text = _workflow_text()
    sync_step = text.index("Sync latest durable state")
    cycle_step = text.index("Run production cycle")
    save_step = text.index("Save generated public data")

    assert sync_step < cycle_step
    assert text.index("git pull --rebase origin main", sync_step) < cycle_step
    assert "git pull --rebase origin main" not in text[save_step:]


def test_workflow_has_exception_only_health_alerting_and_minimum_issue_permission():
    text = _workflow_text()

    assert "issues: write" in text
    assert "actions: write" not in text
    assert "pull-requests: write" not in text
    assert "administration: write" not in text
    assert "python scripts/production_health_watch.py" in text
    assert "if: ${{ failure() }}" in text
    assert "[PRODUCTION] Football MVP health alert" in text
    assert "gh issue" in text
    assert "gh issue close" in text
    assert "Production health recovered automatically." in text


def test_health_alert_does_not_block_durable_save_or_pages_deploy():
    text = _workflow_text()
    health_step = text.index("Evaluate production health")
    save_step = text.index("Save generated public data")
    deploy_step = text.index("Deploy Pages")

    assert health_step < save_step < deploy_step
    assert "if: ${{ steps.health.outputs.status != 'ALERT' }}" not in text
    assert "if: ${{ steps.health.outputs.notify == 'true' }}" not in text


def test_generated_data_save_uses_narrow_durability_gate():
    text = _workflow_text()
    cycle_index = text.index("- name: Run production cycle")
    gate_index = text.index("- name: Classify generated data durability")
    fail_closed_index = text.index("- name: Fail closed when refresh is not durable")
    save_index = text.index("- name: Save generated public data")
    rebuild_index = text.index("- name: Rebuild Pages artifact after data save")
    cycle_block = text[cycle_index:gate_index]
    gate_block = text[gate_index:save_index]
    save_block = text[save_index:rebuild_index]

    assert "id: production_cycle" in cycle_block
    assert "python scripts/automation_cycle.py" in cycle_block
    assert "id: generated_data_gate" in gate_block
    assert "if: ${{ always() }}" in gate_block
    assert "--cycle-result data/product_runtime/latest_cycle.json" in gate_block
    fail_closed_block = text[fail_closed_index:save_index]
    assert fail_closed_index > gate_index
    assert "steps.generated_data_gate.outputs.ready != 'true'" in fail_closed_block
    assert "exit 1" in fail_closed_block
    assert "if: ${{ !cancelled() && steps.generated_data_gate.outputs.ready == 'true' }}" in save_block
    assert "always()" not in save_block
