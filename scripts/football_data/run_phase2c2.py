"""Run the offline Phase 2C-2 Opponent Strength experiment once."""

from __future__ import annotations

import argparse
import json

from .phase2c2_experiment import (
    materialize_phase2c2_rolling_predictions,
    refresh_phase2c2_compact_outputs,
    run_phase2c2,
    write_phase2c2_handoff,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--generated-at")
    parser.add_argument("--refresh-handoff", action="store_true")
    parser.add_argument("--refresh-compact", action="store_true")
    parser.add_argument("--materialize-rolling", action="store_true")
    args = parser.parse_args(argv)
    if args.materialize_rolling:
        result = materialize_phase2c2_rolling_predictions(pr_number=args.pr_number)
    elif args.refresh_compact:
        result = refresh_phase2c2_compact_outputs(pr_number=args.pr_number)
    elif args.refresh_handoff:
        result = {"status": "OK", "handoff": str(write_phase2c2_handoff(pr_number=args.pr_number))}
    else:
        result = run_phase2c2(pr_number=args.pr_number, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
