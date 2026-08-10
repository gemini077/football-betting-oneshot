"""CLI entry point for the offline shadow team-strength health population."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .health import build_team_strength_health
from .historical_results import HistoricalResultLedger


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _current_matches(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("matches", []) if isinstance(payload, dict) else payload
    return [dict(row) for row in rows if isinstance(row, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--captured-at")
    args = parser.parse_args(argv)
    health = build_team_strength_health(
        _current_matches(args.current),
        HistoricalResultLedger(args.ledger).records(),
        captured_at=args.captured_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(health, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
