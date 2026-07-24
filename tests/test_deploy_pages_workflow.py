from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_site_is_rebuilt_after_generated_data_commit_and_stash():
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

    save_index = workflow.index("- name: Save generated public data")
    rebuild_index = workflow.index("- name: Rebuild Pages artifact after data save")
    upload_index = workflow.index("- name: Upload Pages artifact")

    assert save_index < rebuild_index < upload_index
    assert "run: python scripts/build_public_site.py" in workflow[rebuild_index:upload_index]
