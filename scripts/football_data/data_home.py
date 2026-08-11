"""Resolve the shared, worktree-independent football data home.

Bulk football datasets are local analytical artifacts rather than repository
files.  The environment variable is intentionally the only machine-specific
override; the default is stable across sibling Git worktrees.
"""

from __future__ import annotations

import os
from pathlib import Path


FOOTBALL_DATA_HOME_ENV = "FOOTBALL_DATA_HOME"
DEFAULT_DATA_HOME_PARTS = (".football-betting-oneshot", "football_data")


def resolve_football_data_home() -> Path:
    """Return the shared Football Data Home without creating it."""

    configured = os.environ.get(FOOTBALL_DATA_HOME_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home().joinpath(*DEFAULT_DATA_HOME_PARTS)


def historical_results_path(data_home: str | Path | None = None) -> Path:
    root = Path(data_home) if data_home is not None else resolve_football_data_home()
    return root / "historical_results.duckdb"


def team_strength_snapshots_path(data_home: str | Path | None = None) -> Path:
    root = Path(data_home) if data_home is not None else resolve_football_data_home()
    return root / "team_strength_snapshots.duckdb"


def identity_detail_path(data_home: str | Path | None = None) -> Path:
    root = Path(data_home) if data_home is not None else resolve_football_data_home()
    return root / "identity" / "p0_p1_identity_candidates.json"
