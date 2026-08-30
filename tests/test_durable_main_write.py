from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER = REPO_ROOT / "scripts" / "durable_main_write.py"


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stdout}")
    return result


def commit_file(repo: Path, name: str, content: str, message: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


@pytest.fixture()
def remote_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    full = tmp_path / "full"
    prematch = tmp_path / "prematch"

    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", str(remote), str(seed))
    git(seed, "config", "user.name", "fixture")
    git(seed, "config", "user.email", "fixture@example.invalid")
    commit_file(seed, "shared.txt", "base\n", "seed base")
    git(seed, "push", "-u", "origin", "main")

    for clone in (full, prematch):
        git(tmp_path, "clone", str(remote), str(clone))
        git(clone, "config", "user.name", "fixture")
        git(clone, "config", "user.email", "fixture@example.invalid")

    return remote, full, prematch


def run_writer(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--remote",
            "origin",
            "--branch",
            "main",
            "--retry-delay-seconds",
            "0",
            *extra,
        ],
        cwd=repo,
        check=False,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def verify_remote(remote: Path, tmp_path: Path) -> Path:
    verification = tmp_path / "verification"
    git(tmp_path, "clone", str(remote), str(verification))
    return verification


def test_full_writer_rebases_after_prematch_advances_main(
    remote_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    remote, full, prematch = remote_fixture
    commit_file(full, "full.json", "full\n", "full production output")
    commit_file(prematch, "prematch.json", "prematch\n", "prematch checkpoint")
    git(prematch, "push", "origin", "main")

    result = run_writer(full)

    assert result.returncode == 0, result.stdout
    verification = verify_remote(remote, tmp_path)
    assert (verification / "full.json").read_text(encoding="utf-8") == "full\n"
    assert (verification / "prematch.json").read_text(encoding="utf-8") == "prematch\n"


def test_prematch_writer_rebases_after_full_production_advances_main(
    remote_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    remote, full, prematch = remote_fixture
    commit_file(prematch, "prematch.json", "prematch\n", "prematch checkpoint")
    commit_file(full, "full.json", "full\n", "full production output")
    git(full, "push", "origin", "main")

    result = run_writer(prematch)

    assert result.returncode == 0, result.stdout
    verification = verify_remote(remote, tmp_path)
    assert (verification / "full.json").read_text(encoding="utf-8") == "full\n"
    assert (verification / "prematch.json").read_text(encoding="utf-8") == "prematch\n"


def test_non_conflicting_writers_keep_both_durable_states(
    remote_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    remote, full, prematch = remote_fixture
    commit_file(full, "full.json", "full\n", "full production output")
    commit_file(prematch, "prematch.json", "prematch\n", "prematch checkpoint")
    git(full, "push", "origin", "main")

    result = run_writer(prematch)

    assert result.returncode == 0, result.stdout
    verification = verify_remote(remote, tmp_path)
    assert sorted(path.name for path in verification.glob("*.json")) == [
        "full.json",
        "prematch.json",
    ]


def test_conflicting_immutable_file_fails_closed_without_overwriting_remote(
    remote_fixture: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    remote, full, prematch = remote_fixture
    commit_file(full, "shared.txt", "full-final\n", "full immutable final")
    commit_file(prematch, "shared.txt", "prematch-final\n", "prematch immutable final")
    full_commit = git(full, "rev-parse", "HEAD").stdout.strip()
    git(full, "push", "origin", "main")

    result = run_writer(prematch, "--max-attempts", "1")

    assert result.returncode != 0
    assert "rebase" in result.stdout.lower()
    assert git(prematch, "rebase", "--show-current-patch", check=False).returncode != 0
    assert git(tmp_path, "ls-remote", str(remote), "refs/heads/main").stdout.startswith(
        f"{full_commit}\t"
    )
    verification = verify_remote(remote, tmp_path)
    assert (verification / "shared.txt").read_text(encoding="utf-8") == "full-final\n"


def test_target_workflows_use_bounded_writer_and_rebuild_after_prematch_write() -> None:
    deploy = (REPO_ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(
        encoding="utf-8"
    )
    prematch = (
        REPO_ROOT / ".github" / "workflows" / "prematch-market-monitor.yml"
    ).read_text(encoding="utf-8")

    assert "python scripts/durable_main_write.py" in deploy
    assert "python scripts/durable_main_write.py" in prematch
    assert "git push" not in deploy[deploy.index("- name: Save generated public data") :]
    assert "git stash push --include-untracked" in deploy
    assert "git stash pop" in deploy
    save_start = prematch.index("- name: Save market snapshots and refreshed reports")
    save_end = prematch.index("- uses: actions/configure-pages@v5", save_start)
    save_block = prematch[save_start:save_end]
    assert "git push" not in save_block
    assert "Rebuild Pages artifact after durable write" in prematch
    assert prematch.index("python scripts/durable_main_write.py") < prematch.index(
        "Rebuild Pages artifact after durable write"
    )
