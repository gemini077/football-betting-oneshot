#!/usr/bin/env python3
"""Generate date-specific GitHub cron triggers for active one-shot reviews."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from postmatch_queue import BASE_DIR, SHANGHAI, parse_datetime
from postmatch_result import FINAL_STATUSES, SCHEDULE_ROOT


OUTPUT = BASE_DIR / ".github" / "workflows" / "postmatch-once.yml"


def active_due_times(now: datetime, schedule_root: Path) -> list[datetime]:
    due_times: set[datetime] = set()
    for path in schedule_root.glob("*.json"):
        try:
            schedule = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(schedule.get("status") or "scheduled") in FINAL_STATUSES:
            continue
        due = parse_datetime(schedule.get("review_due_at"))
        if due is not None and due >= now:
            due_times.add(due.astimezone(timezone.utc).replace(second=0, microsecond=0))
    return sorted(due_times)


def render(due_times: list[datetime]) -> str:
    schedule = ""
    if due_times:
        rows = "\n".join(f'    - cron: "{due.minute} {due.hour} {due.day} {due.month} *"' for due in due_times)
        schedule = f"\n  schedule:\n{rows}"
    return f'''name: One-shot post-match verification

on:
  workflow_dispatch:{schedule}

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: football-betting-oneshot-write
  cancel-in-progress: false

jobs:
  verify-once:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Verify only due results
        run: python scripts/postmatch_result.py
      - name: Replace completed trigger or schedule one bounded retry
        run: python scripts/sync_postmatch_workflow.py
      - name: Generate strict full post-match reviews
        run: python scripts/automatic_postmatch_review.py
      - name: Rebuild public pages
        run: |
          FBOS_DATE=$(TZ=Asia/Shanghai date +%F)
          python scripts/postmatch_dashboard.py
          python scripts/match_workspace.py --date "$FBOS_DATE"
          python scripts/build_public_site.py
      - name: Save verification state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add .github/workflows/postmatch-once.yml data/postmatch_automation data/postmatch_reviews data/match_workspace data/postmatch_dashboard data/paper_ledger
          if ! git diff --cached --quiet; then
            git commit -m "verify scheduled match result [skip ci]"
            git push
          fi
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deployment
        uses: actions/deploy-pages@v4
'''


def sync(now: datetime, schedule_root: Path, output: Path = OUTPUT) -> tuple[Path, list[datetime]]:
    due_times = active_due_times(now, schedule_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(due_times), encoding="utf-8")
    return output, due_times


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="ISO timestamp for deterministic generation")
    parser.add_argument("--schedule-root", type=Path, default=SCHEDULE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(timezone.utc).astimezone(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    schedule_root = args.schedule_root if args.schedule_root.is_absolute() else BASE_DIR / args.schedule_root
    output = args.output if args.output.is_absolute() else BASE_DIR / args.output
    path, due_times = sync(now, schedule_root, output)
    print(json.dumps({"output": str(path), "active_triggers": [due.isoformat() for due in due_times]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
