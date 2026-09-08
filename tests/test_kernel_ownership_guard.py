from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


MOVED_DEFINITIONS = {
    "scripts/automatic_model_core.py": {
        "_consensus_probabilities",
        "_market_total",
        "_market_handicap",
        "_total_line_pricing",
        "_outcomes",
        "_model_rows",
        "_settlement_probability",
    },
    "scripts/model_baselines.py": {
        "_as_rows",
        "_one_x_two_rows",
        "_quote_values",
        "_bookmaker_name",
        "_canonical_bookmaker_id",
        "_auxiliary_market_rows",
        "_line_from_rows",
        "_number_from_snapshot",
        "build_market_reference",
        "_poisson_matrix",
        "_total_distribution",
    },
    "scripts/risk_engine.py": {
        "dixon_coles_score_matrix",
        "_asian_line_parts",
        "asian_handicap_settlement",
        "asian_total_settlement",
        "exact_total_goals_set",
    },
    "scripts/baseline_production.py": {"_score_rows"},
}


MOVED_PRIVATE_IMPORTS = {
    "_consensus_probabilities",
    "_market_total",
    "_market_handicap",
    "_total_line_pricing",
    "_outcomes",
    "_model_rows",
    "_settlement_probability",
}


EVALUATION_DUPLICATE_DEFINITIONS = {
    "scripts/baseline_settlement.py": {
        "_actual_result",
        "_outcome",
        "_probabilities",
        "_score_rows",
        "_row_score",
        "_expected_goals",
        "_full_score_rows",
    },
    "scripts/prospective_settlement.py": {
        "_outcome",
        "_probabilities",
        "_score_rows",
        "_score_pair",
    },
}


EVALUATION_CALLERS = (
    ("scripts/baseline_settlement.py", "calculate_metrics"),
    ("scripts/automatic_postmatch_review.py", "_model_diagnostics"),
    ("scripts/prospective_settlement.py", "evaluate_prediction"),
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected one function named {name}"
    return matches[0]


def _called_names(node: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def test_moved_domain_functions_have_one_implementation_owner():
    for relative_path, forbidden in MOVED_DEFINITIONS.items():
        defined = {
            node.name
            for node in ast.walk(_tree(ROOT / relative_path))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert defined.isdisjoint(forbidden), f"duplicate implementation in {relative_path}"


def test_known_callers_do_not_import_private_model_core_market_score_helpers():
    for relative_path in (
        "scripts/base_prediction_runner.py",
        "scripts/baseline_production.py",
        "scripts/prediction_trust_2_replay.py",
    ):
        for node in ast.walk(_tree(ROOT / relative_path)):
            if not isinstance(node, ast.ImportFrom) or node.module != "automatic_model_core":
                continue
            imported = {alias.name for alias in node.names}
            assert imported.isdisjoint(MOVED_PRIVATE_IMPORTS), f"private kernel import in {relative_path}"


def test_legacy_score_exports_are_import_only_compatibility_aliases():
    tree = _tree(SCRIPTS / "risk_engine.py")
    score_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "score_engine"
        for alias in node.names
    }
    assert {
        "dixon_coles_score_matrix",
        "asian_handicap_settlement",
        "asian_total_settlement",
        "exact_total_goals_set",
    } <= score_imports


def test_asian_contract_semantics_have_one_owner_and_pricers_delegate():
    canonical_tree = _tree(SCRIPTS / "market_contracts.py")
    canonical_definitions = [
        node
        for node in ast.walk(canonical_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "settle_asian_contract"
    ]
    assert len(canonical_definitions) == 1

    delegated_functions = (
        ("scripts/market_contracts.py", "settle_contract"),
        ("scripts/market_engine.py", "price_total_line"),
        ("scripts/score_engine.py", "matrix_settlement_probability"),
        ("scripts/score_engine.py", "_settlement_categories"),
    )
    for relative_path, function_name in delegated_functions:
        calls = _called_names(_function(_tree(ROOT / relative_path), function_name))
        assert "settle_asian_contract" in calls, f"{relative_path}::{function_name} bypasses canonical semantics"

    for relative_path in ("scripts/market_engine.py", "scripts/score_engine.py"):
        assert "split_quarter_line" not in _called_names(_tree(ROOT / relative_path))


def test_common_evaluation_semantics_have_one_owner():
    canonical = _tree(SCRIPTS / "evaluation_kernel.py")
    canonical_names = {
        node.name
        for node in ast.walk(canonical)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert {
        "normalize_verified_result",
        "evaluate_prediction_common",
        "evaluate_exact_score",
        "evaluate_goal_residuals",
    } <= canonical_names

    for relative_path, forbidden in EVALUATION_DUPLICATE_DEFINITIONS.items():
        defined = {
            node.name
            for node in ast.walk(_tree(ROOT / relative_path))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert defined.isdisjoint(forbidden), f"duplicate evaluation implementation in {relative_path}"


def test_evaluation_callers_delegate_common_semantics_to_canonical_owner():
    for relative_path, function_name in EVALUATION_CALLERS:
        calls = _called_names(_function(_tree(ROOT / relative_path), function_name))
        assert "evaluate_prediction_common" in calls, f"{relative_path}::{function_name} bypasses evaluation owner"


def test_production_review_does_not_reconstruct_formal_exact_truth_locally():
    calls = _called_names(_function(_tree(ROOT / "scripts/automatic_postmatch_review.py"), "_model_diagnostics"))
    assert "dixon_coles_score_matrix" not in calls
    assert "classify_frozen_exact_score" not in calls
