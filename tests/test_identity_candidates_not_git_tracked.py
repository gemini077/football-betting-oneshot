from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_detailed_identity_candidates_are_not_git_tracked():
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "data/football_data/p0_p1_identity_candidates.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not (ROOT / "data" / "football_data" / "p0_p1_identity_candidates.json").exists()
