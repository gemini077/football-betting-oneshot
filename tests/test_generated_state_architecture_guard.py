from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_refresh_and_review_use_compact_current_view_contract():
    refresh_source = (ROOT / "scripts" / "market_side_shadow_refresh.py").read_text(encoding="utf-8")
    assert "build_compact_shadow_view" in refresh_source
    assert "CURRENT_VIEW_SCHEMA_VERSION" in refresh_source

    review_tree = _tree(ROOT / "scripts" / "challenger_c_promotion_review.py")
    review_function = _function(review_tree, "run_review")
    indexed_loader_calls = {
        node.func.id
        for node in ast.walk(review_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "load_indexed_pairs" in indexed_loader_calls
    embedded_history_reads = [
        node
        for node in ast.walk(review_tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "pairs"
        )
    ]
    assert not embedded_history_reads


def test_compact_view_owner_does_not_serialize_full_pair_history():
    tree = _tree(ROOT / "scripts" / "market_side_shadow_refresh.py")
    function = _function(tree, "build_compact_shadow_view")
    serialized_keys = {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "pairs" in serialized_keys
    assert "pair_index" in serialized_keys


def test_current_latest_artifact_is_a_bounded_compact_index():
    latest_path = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    pair_index = latest["pair_index"]

    assert latest["schema_version"] == "market_side_shadow_1.current.v1"
    assert "pairs" not in latest
    assert latest_path.stat().st_size <= 1_000_000
    assert pair_index["schema_version"] == "market_side_shadow_1.pair_index.v1"
    assert pair_index["pair_count"] == len(pair_index["entries"])
    assert pair_index["entries"]
    assert all(
        (ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / entry["path"]).is_file()
        for entry in pair_index["entries"]
    )
