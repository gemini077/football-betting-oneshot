"""Build an offline normalized football-data.co.uk result sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .historical_results import HistoricalResultLedger
from .data_home import historical_results_path
from .providers.football_data_uk import FootballDataCoUkHistoricalAdapter


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data" / "football_data" / "football_data_uk" / "source_manifest.json"
DEFAULT_IDENTITIES = ROOT / "data" / "football_data" / "football_data_uk" / "identity_evidence.json"
DEFAULT_OUTPUT = ROOT / "data" / "football_data" / "historical_result_samples" / "football_data_uk_sweden_2026.json"
DEFAULT_LEDGER_ROOT = historical_results_path()


def load_records(
    raw_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    identity_path: str | Path = DEFAULT_IDENTITIES,
    season: str = "2026",
) -> list[dict[str, Any]]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    identity = json.loads(Path(identity_path).read_text(encoding="utf-8"))
    mappings = {str(row["provider_team_name"]): row for row in identity.get("mappings", [])}
    source = next(item for item in manifest.get("sources", []) if str(item.get("provider_season_id")) == str(season))
    adapter = FootballDataCoUkHistoricalAdapter(
        competition_id="competition:sweden-allsvenskan",
        season_id="season:sweden-allsvenskan:2026",
        provider_competition_id=str(source["provider_competition_id"]),
        provider_competition_name=str(source["provider_competition_name"]),
        provider_season_id=str(source["provider_season_id"]),
        provider_season_name=str(source["provider_season_name"]),
        source_url=str(manifest["source_url"]),
        source_file=str(manifest["source_file"]),
        captured_at=str(manifest["captured_at"]),
        raw_sha256=str(manifest["raw_sha256"]),
        team_identity_resolver=mappings,
    )
    raw_text = Path(raw_path).read_text(encoding="utf-8-sig")
    return adapter.parse_csv_text(raw_text, season_filter=season)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_path", type=Path)
    parser.add_argument("--season", default="2026")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    args = parser.parse_args()
    records = load_records(args.raw_path, season=args.season)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "contract_version": "historical_result_sample.v1",
        "provider": "football-data.co.uk",
        "source_file": "SWE.csv",
        "season": args.season,
        "record_count": len(records),
        "eligible_record_count": sum(record.get("eligible_for_team_strength") is True for record in records),
        "records": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = HistoricalResultLedger(args.ledger_root)
    for record in records:
        ledger.append(record)
    print(f"wrote {len(records)} normalized football-data.co.uk records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
