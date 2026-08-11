from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_bulk_cache_paths_are_ignored_and_phase2b3_snapshots_are_not_tracked():
    for path in (
        ".cache/football_data/historical_results.duckdb",
        ".cache/football_data/team_strength_snapshots.duckdb",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, f"bulk cache path is not ignored: {path}"

    if subprocess.run(["git", "rev-parse", "--verify", "origin/main"], cwd=ROOT, check=False, capture_output=True).returncode != 0:
        pytest.skip("origin/main ref is unavailable in this checkout")

    changed_bulk_paths = subprocess.check_output(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert not any(
        path.startswith(("data/football_data/historical_result_ledger/", "data/football_data/team_strength_snapshots/"))
        for path in changed_bulk_paths
    )
