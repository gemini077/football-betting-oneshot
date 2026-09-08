from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_side_shadow import load_persisted_pairs  # noqa: E402
from market_side_shadow_refresh import (  # noqa: E402
    CURRENT_EVALUATION_KEYS,
    CURRENT_VIEW_SCHEMA_VERSION,
    PAIR_INDEX_SCHEMA_VERSION,
    load_indexed_pairs,
    pair_set_digest,
    refresh_shadow,
)


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
    assert "entries" not in ast.unparse(function)


def test_current_evaluation_projection_drops_recomputable_history_arrays():
    tree = _tree(ROOT / "scripts" / "market_side_shadow_refresh.py")
    compact_source = ast.unparse(_function(tree, "build_compact_shadow_view"))
    projection_source = ast.unparse(_function(tree, "build_bounded_current_evaluation"))
    assert "build_bounded_current_evaluation" in compact_source
    assert "representative_selector" not in projection_source
    assert "selected_representative_pair_ids" not in projection_source
    assert "verified_representative_pair_ids" not in projection_source


def test_current_latest_artifact_is_a_bounded_compact_index(tmp_path):
    latest_path = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    pair_index = latest["pair_index"]

    assert latest["schema_version"] == CURRENT_VIEW_SCHEMA_VERSION
    assert "pairs" not in latest
    assert latest_path.stat().st_size <= 1_000_000
    assert pair_index["schema_version"] == PAIR_INDEX_SCHEMA_VERSION
    assert set(pair_index) == {"schema_version", "root", "pair_count", "pair_set_digest"}
    pair_root = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
    pairs = load_persisted_pairs(pair_root)
    assert 0 < pair_index["pair_count"] <= len(pairs)
    fresh_output = tmp_path / "latest.json"
    refresh_shadow(
        pair_root=pair_root,
        result_root=ROOT / "data" / "postmatch_automation" / "results",
        output=fresh_output,
        refreshed_at="2026-09-08T00:00:00+00:00",
    )
    fresh = json.loads(fresh_output.read_text(encoding="utf-8"))
    assert fresh["pair_index"]["pair_count"] == len(pairs)
    assert fresh["pair_index"]["pair_set_digest"] == pair_set_digest(pairs)
    assert len(load_indexed_pairs(fresh["pair_index"], pair_root)) == len(pairs)
    assert set(latest["evaluation"]) == set(CURRENT_EVALUATION_KEYS)
    assert "representative_selector" not in latest["evaluation"]


def test_pre_change_legacy_flat_pair_manifest_is_byte_for_byte_immutable():
    manifest_path = ROOT / "tests" / "fixtures" / "market_side_shadow_1_legacy_flat_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pair_root = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
    entries = manifest["files"]
    expected_paths = [ROOT / entry["path"] for entry in entries]
    actual_paths = sorted(
        pair_root.glob("MS-SHADOW-PAIR-*.json"),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    assert [path.relative_to(ROOT).as_posix() for path in actual_paths] == [
        entry["path"] for entry in entries
    ]
    for path, entry in zip(expected_paths, entries):
        payload = path.read_bytes()
        assert len(payload) == entry["bytes"]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_pair_layout_loader_is_the_only_physical_layout_owner():
    market_shadow_source = (ROOT / "scripts" / "market_side_shadow.py").read_text(encoding="utf-8")
    refresh_source = (ROOT / "scripts" / "market_side_shadow_refresh.py").read_text(encoding="utf-8")
    review_source = (ROOT / "scripts" / "challenger_c_promotion_review.py").read_text(encoding="utf-8")
    assert "def iter_persisted_pair_paths" in market_shadow_source
    assert "iter_persisted_pair_paths" not in refresh_source
    assert "glob(\"MS-SHADOW-PAIR-*.json\")" not in refresh_source
    assert "glob(\"MS-SHADOW-PAIR-*.json\")" not in review_source
    assert "rglob(\"MS-SHADOW-PAIR-*.json\")" not in market_shadow_source
