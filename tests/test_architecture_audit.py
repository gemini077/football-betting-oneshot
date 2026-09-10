from __future__ import annotations

import json
from pathlib import Path

from scripts.architecture_audit import audit_repository, write_audit_outputs


def _fixture_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "schemas").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "scripts" / "a.py").write_text(
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from b import value
except ImportError:
    from scripts.b import value

def run():
    Path('data/product_runtime/latest_cycle.json').write_text('{}')
    json.load(open('05_RUNTIME_STATE.json'))
    return value
""",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "b.py").write_text(
        """
from scripts.a import run
value = run
""",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_a.py").write_text(
        "from scripts.a import run\n",
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows" / "deploy.yml").write_text(
        """
name: Deploy data
on:
  schedule:
    - cron: '0 * * * *'
permissions:
  contents: write
jobs:
  deploy:
    steps:
      - run: |
          git add data/product_runtime
          git commit -m refresh
          git push origin HEAD:main
""",
        encoding="utf-8",
    )
    (tmp_path / "schemas" / "example.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "config" / "example.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


def test_audit_scans_imports_cycles_and_data_ownership(tmp_path: Path):
    result = audit_repository(_fixture_repo(tmp_path))

    inventory = result["architecture_inventory"]
    modules = {item["module"]: item for item in inventory["modules"]}
    assert modules["scripts.a"]["function_count"] == 1
    assert "scripts.b" in modules["scripts.a"]["local_dependencies"]
    assert modules["scripts.a"]["direct_data_write_namespaces"] == ["data/product_runtime"]
    assert modules["scripts.a"]["direct_data_read_namespaces"] == ["05_RUNTIME_STATE.json"]

    dependencies = result["dependency_summary"]
    assert dependencies["cycles"] == [["scripts.a", "scripts.b"]]
    assert dependencies["sys_path_mutations"] == ["scripts.a"]
    assert dependencies["dual_import_fallbacks"][0]["module"] == "scripts.a"
    assert any(item["module"] == "scripts.a" for item in dependencies["high_fan_in"])

    data_map = {item["namespace"]: item for item in result["data_write_read_map"]["namespaces"]}
    assert "scripts.a" in data_map["data/product_runtime"]["writers"]
    assert "scripts.a" in data_map["05_RUNTIME_STATE.json"]["readers"]
    assert ".github/workflows/deploy.yml" in data_map["data/product_runtime"]["workflow_writers"]

    workflow = result["workflow_map"]["workflows"][0]
    assert workflow["classification"] == "durable production workflow"
    assert workflow["can_write_main"] is True
    assert "data/product_runtime" in workflow["write_namespaces"]


def test_write_outputs_creates_only_compact_required_artifacts(tmp_path: Path):
    repo = _fixture_repo(tmp_path / "repo")
    output_dir = tmp_path / "out"
    result = write_audit_outputs(repo, output_dir)

    expected = {
        "architecture_inventory.json",
        "domain_owner_map.md",
        "data_write_read_map.json",
        "workflow_map.json",
        "dependency_summary.json",
        "report.md",
    }
    assert {path.name for path in output_dir.iterdir()} == expected
    assert result["decision"] in {"ARCHITECTURE_CONSOLIDATION_REQUIRED", "BOUNDED_DEBT_ONLY", "FAIL_CLOSED"}
    assert result["architecture_inventory"]["data_scan_policy"] == "paths_only_no_data_contents"
    assert "ARCHITECTURE_CONSOLIDATION_REQUIRED" in (output_dir / "report.md").read_text(encoding="utf-8")
    for name in ("architecture_inventory.json", "data_write_read_map.json", "workflow_map.json", "dependency_summary.json"):
        json.loads((output_dir / name).read_text(encoding="utf-8"))


def test_real_repository_has_no_audit_parse_errors_and_records_collection_blocker():
    root = Path(__file__).resolve().parents[1]
    result = audit_repository(root)

    assert result["architecture_inventory"]["python_parse_errors"] == []
    assert result["architecture_inventory"]["module_count"] >= 100
    assert any(item["module"] == "scripts.match_identity" for item in result["architecture_inventory"]["modules"])
    assert "data/product_runtime" in {item["namespace"] for item in result["data_write_read_map"]["namespaces"]}
