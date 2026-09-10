from __future__ import annotations

import importlib
import json
from datetime import timedelta, timezone
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


def test_real_repository_has_concrete_ownership_and_primitive_evidence():
    root = Path(__file__).resolve().parents[1]
    result = audit_repository(root)

    inventory = result["architecture_inventory"]
    assert inventory["python_parse_errors"] == []
    assert inventory["module_count"] >= 100
    assert any(item["module"] == "scripts.match_identity" for item in inventory["modules"])

    modules = {
        item["module"]: {symbol["name"] for symbol in item["defined_symbols"]}
        for item in inventory["modules"]
    }
    ownership = {
        item["namespace"]: item
        for item in result["data_write_read_map"]["namespaces"]
    }
    critical = {
        "05_RUNTIME_STATE.json",
        "data/product_runtime",
        "data/prediction_universe",
        "data/model_governance/predictions",
        "data/match_workspace",
    }
    assert result["data_write_read_map"]["critical_namespace_gaps"] == []
    for namespace in critical:
        row = ownership[namespace]
        assert row["code_reader_status"] == "OBSERVED"
        assert row["code_readers"]
        assert row["code_reader_evidence"]
        assert row["unclassified_code_references"] == []
        if namespace == "05_RUNTIME_STATE.json":
            assert row["code_writer_status"] == "NO_CODE_WRITER_OBSERVED"
            assert row["code_writer_evidence"] == []
        else:
            assert row["code_writer_status"] == "OBSERVED"
            assert row["code_writers"]
            assert row["code_writer_evidence"]
        for evidence in [*row["code_reader_evidence"], *row["code_writer_evidence"]]:
            assert evidence["module"] in modules
            assert evidence["symbol"] in modules[evidence["module"]]
            assert isinstance(evidence["line"], int) and evidence["line"] > 0
            assert evidence["operation"] in {"read", "write"}

    primitives = inventory["shared_semantic_primitives"]
    assert len(primitives) == 8
    for primitive_name, primitive in primitives.items():
        assert primitive["required"] is True
        assert primitive["status"] == "PASS"
        assert primitive["tag_only"] is False
        assert primitive["implementation_count"] == primitive["required_implementation_count"]
        assert primitive["implementations"]
        assert primitive["characterization_examples"]
        for implementation in primitive["implementations"]:
            assert implementation["module"] in modules
            assert implementation["symbol"] in modules[implementation["module"]]
            assert isinstance(implementation["line"], int) and implementation["line"] > 0
            assert implementation["semantics"]
            assert implementation["classification"] in {
                "intentional domain policy",
                "compatibility",
                "accidental duplication",
            }
            if primitive_name in {"datetime_timestamp_parsing", "identity_extraction_matching_canonical_key"}:
                assert implementation["characterization_test"].startswith(
                    "tests/test_architecture_audit.py::test_"
                )


def test_timestamp_semantics_are_characterized(monkeypatch):
    """Keep the currently different P0 timestamp contracts executable."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    match_identity = importlib.import_module("match_identity")
    current_serving_state = importlib.import_module("current_serving_state")
    postmatch_queue = importlib.import_module("postmatch_queue")
    match_workspace = importlib.import_module("match_workspace")
    prematch_versioning = importlib.import_module("prematch_versioning")

    naive = "2026-09-10T12:00:00"
    assert match_identity.parse_kickoff(naive).tzinfo is None
    assert current_serving_state._parse_timestamp(naive).tzinfo == timezone.utc
    assert postmatch_queue.parse_datetime(naive).utcoffset() == timedelta(hours=8)
    assert match_workspace.parse_kickoff_local(naive).utcoffset() == timedelta(hours=8)
    assert prematch_versioning._parse_timestamp(naive) is None


def test_identity_semantics_are_characterized(monkeypatch):
    """Keep canonical identity and current-serving fallback precedence executable."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    match_identity = importlib.import_module("match_identity")
    current_serving_state = importlib.import_module("current_serving_state")
    postmatch_queue = importlib.import_module("postmatch_queue")

    fixture = {
        "home": "Alpha",
        "away": "Beta",
        "kickoff_local": "2026-09-10T12:00:00+08:00",
        "match_id": "provider-1",
    }
    equivalent = dict(fixture)
    equivalent["kickoff"] = equivalent.pop("kickoff_local")
    assert match_identity.canonical_match_id(fixture) == match_identity.canonical_match_id(equivalent)
    assert match_identity.canonical_match_id(fixture) in match_identity.identity_aliases(fixture)
    assert current_serving_state.current_match_key({"job_id": "job", "match_id": "123"}) == "match_id:123"
    assert current_serving_state.current_match_key({"job_id": "job", "match_key": "key"}) == "match_key:key"
    assert current_serving_state.current_match_key(
        {
            "job_id": "job",
            "home": "Alpha",
            "away": "Beta",
            "kickoff_at": "2026-09-10T12:00:00",
        }
    ) == "fallback:2026-09-10T12:00:00+00:00|alpha|beta"
    assert postmatch_queue.report_key({"match": {"shuju_id": 42}}) == "shuju:42"
