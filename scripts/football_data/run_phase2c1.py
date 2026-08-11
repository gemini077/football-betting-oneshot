"""Run the offline Phase 2C-1 Basic Team Strength experiment."""

from __future__ import annotations

import argparse
import json

from .phase2c1_experiment import recompute_locked_heldout_metrics, run_phase2c1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--generated-at")
    parser.add_argument("--recompute-locked-metrics", action="store_true")
    args = parser.parse_args(argv)
    if args.recompute_locked_metrics:
        result = recompute_locked_heldout_metrics(pr_number=args.pr_number, generated_at=args.generated_at)
    else:
        result = run_phase2c1(pr_number=args.pr_number, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
