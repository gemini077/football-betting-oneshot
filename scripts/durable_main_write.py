#!/usr/bin/env python3
"""Push an already-created durable commit without overwriting newer main state.

The caller owns data generation and the commit.  This helper only synchronizes
that commit with the current remote branch and pushes it with a bounded retry.
Rebase conflicts are terminal so an immutable writer never force-pushes over a
different durable state.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence


def run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        encoding="utf-8",
    )


def abort_rebase() -> None:
    result = run_git(("rebase", "--abort"))
    if result.returncode:
        print("git rebase --abort did not report a clean abort", file=sys.stderr)


def sync_and_push(remote: str, branch: str, max_attempts: int, delay_seconds: float) -> int:
    refspec = f"HEAD:refs/heads/{branch}"

    for attempt in range(1, max_attempts + 1):
        print(f"durable main write attempt {attempt}/{max_attempts}", flush=True)

        fetch = run_git(("fetch", "--no-tags", remote, branch))
        if fetch.returncode:
            print("git fetch failed; the durable write was not pushed", file=sys.stderr)
        else:
            rebase = run_git(("rebase", f"{remote}/{branch}"))
            if rebase.returncode:
                print(
                    "git rebase conflict/failure; aborting without force push",
                    file=sys.stderr,
                )
                abort_rebase()
                return rebase.returncode

            push = run_git(("push", remote, refspec))
            if push.returncode == 0:
                print("durable main write pushed", flush=True)
                return 0
            print("git push did not advance remote main", file=sys.stderr)

        if attempt < max_attempts:
            time.sleep(delay_seconds)

    print(
        f"durable main write failed after {max_attempts} bounded attempts",
        file=sys.stderr,
    )
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize and push an existing durable commit to main."
    )
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    if args.retry_delay_seconds < 0:
        parser.error("--retry-delay-seconds must be non-negative")
    return args


def main() -> int:
    args = parse_args()
    return sync_and_push(
        remote=args.remote,
        branch=args.branch,
        max_attempts=args.max_attempts,
        delay_seconds=args.retry_delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
