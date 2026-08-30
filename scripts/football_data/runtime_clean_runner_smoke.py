#!/usr/bin/env python3
"""Run the clean-runner proof against the installed runtime snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .data_home import historical_results_path, resolve_football_data_home
    from .runtime_snapshot import EXPECTED_DATASET_SHA256, EXPECTED_RECORD_COUNT
    from .storage import HistoricalResultStore
except ImportError:  # pragma: no cover - module invocation is the workflow path
    from football_data.data_home import historical_results_path, resolve_football_data_home
    from football_data.runtime_snapshot import EXPECTED_DATASET_SHA256, EXPECTED_RECORD_COUNT
    from football_data.storage import HistoricalResultStore

try:
    from scripts.recent_form_cache import load_authoritative_recent_form
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from recent_form_cache import load_authoritative_recent_form


TARGET_MATCH_ID = "500-1364199"
TARGET_HOME = "博德闪耀"
TARGET_AWAY = "罗森博格"
TARGET_KICKOFF = "2026-08-30T12:30:00Z"
SMOKE_CLOCK = "2026-08-30T12:00:00Z"
COMPETITION_ID = "competition:norway-eliteserien"
HOME_TEAM_ID = "team:norway:bod-glimt"
AWAY_TEAM_ID = "team:norway:rosenborg"
CHAMPION_MINIMUM_RECORDS = 4


def run_smoke(data_home: str | Path | None = None) -> dict:
    home = Path(data_home) if data_home is not None else resolve_football_data_home()
    store = HistoricalResultStore(historical_results_path(home))
    record_count = store.count()
    dataset_sha256 = store.dataset_digest()
    if record_count != EXPECTED_RECORD_COUNT or dataset_sha256 != EXPECTED_DATASET_SHA256:
        raise RuntimeError("CLOUD_DATASET_PARITY_FAILED")

    job = {
        "match_id": TARGET_MATCH_ID,
        "home": TARGET_HOME,
        "away": TARGET_AWAY,
        "league": "挪威超级联赛",
        "kickoff": "2026-08-30T20:30:00+08:00",
    }
    fixture = {
        "matchId": TARGET_MATCH_ID,
        "homeTeam": TARGET_HOME,
        "awayTeam": TARGET_AWAY,
        "league": job["league"],
    }
    identity = {
        "home_team_id": HOME_TEAM_ID,
        "away_team_id": AWAY_TEAM_ID,
        "status": "AUTO_RESOLVED",
        "resolution_method": "reviewed_canonical_provider_crosswalk",
    }
    loaded = load_authoritative_recent_form(
        job,
        fixture,
        TARGET_KICKOFF,
        SMOKE_CLOCK,
        historical_store=store,
        identity=identity,
        competition_id=COMPETITION_ID,
    )
    if loaded is None:
        raise RuntimeError("RECENT_FORM_SMOKE_FAILED")
    records = loaded.get("records") or []
    if len(records) < CHAMPION_MINIMUM_RECORDS:
        raise RuntimeError("RECENT_FORM_BELOW_CHAMPION_MINIMUM")
    if any(str(row.get("kickoff_at") or "") >= TARGET_KICKOFF for row in records):
        raise RuntimeError("RECENT_FORM_FUTURE_LEAKAGE")
    form = loaded.get("recent_form") or {}
    if any(int((form.get(key) or {}).get("matches") or 0) <= 0 for key in ("home_overall", "home_home", "away_overall", "away_away")):
        raise RuntimeError("RECENT_FORM_CONTRACT_FAILED")

    return {
        "status": "CLOUD_CLEAN_RUNNER_SMOKE_VERIFIED",
        "record_count": record_count,
        "dataset_sha256": dataset_sha256,
        "match_id": TARGET_MATCH_ID,
        "form_source": loaded.get("source"),
        "recent_form_status": "AVAILABLE",
        "recent_form_record_count": len(records),
        "champion_minimum_record_count": CHAMPION_MINIMUM_RECORDS,
        "all_kickoff_before_target": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-home", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_smoke(args.data_home), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        reason = getattr(error, "code", None) or "CLOUD_CLEAN_RUNNER_SMOKE_FAILED"
        print(json.dumps({"status": "CLOUD_CLEAN_RUNNER_SMOKE_FAILED", "reason": str(reason)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
