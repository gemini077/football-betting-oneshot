"""Build a bounded normalized OpenFootball pilot from captured source files.

This command is intentionally offline: the caller supplies a capture directory
and a source manifest.  It writes only the selected normalized observations,
never the upstream database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .historical_results import HistoricalResultLedger
from .providers.openfootball import OpenFootballHistoricalAdapter


DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "football_data" / "openfootball" / "source_manifest.json"
DEFAULT_IDENTITIES = Path(__file__).resolve().parents[2] / "data" / "football_data" / "openfootball" / "identity_evidence.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "football_data" / "historical_result_samples" / "openfootball_pilot.json"
DEFAULT_LEDGER_ROOT = Path(__file__).resolve().parents[2] / "data" / "football_data" / "historical_result_ledger"


def load_openfootball_records(
    raw_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    identity_path: str | Path = DEFAULT_IDENTITIES,
    include_team_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    raw_root = Path(raw_root)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    identity_rows = json.loads(Path(identity_path).read_text(encoding="utf-8")).get("teams", [])
    identity_map = {str(row["provider_team_name"]): row for row in identity_rows}
    selected_ids = set(include_team_ids or ())
    records: list[dict[str, Any]] = []
    for source in manifest.get("sources", []):
        source_path = raw_root / str(source["source_file"])
        raw_bytes = source_path.read_bytes()
        raw_text = raw_bytes.decode("utf-8")
        adapter = OpenFootballHistoricalAdapter(
            competition_id=f"competition:{source['competition_key']}",
            season_id=f"season:{source['competition_key']}:{source['provider_season_id']}",
            provider_competition_id=str(source["provider_competition_id"]),
            provider_competition_name=str(source["provider_competition_name"]),
            provider_season_id=str(source["provider_season_id"]),
            provider_season_name=str(source["provider_season_name"]),
            repository=str(manifest["repository"]),
            commit_sha=str(manifest["commit_sha"]),
            source_file=str(source["source_file"]),
            captured_at=str(manifest["captured_at"]),
            country="Sweden" if str(source["competition_key"]).startswith("sweden") else "Portugal",
            team_identity_resolver=identity_map,
        )
        parsed = adapter.parse_text(raw_text, raw_sha256=hashlib.sha256(raw_bytes).hexdigest())
        if selected_ids:
            parsed = [
                record
                for record in parsed
                if record.get("home_team_id") in selected_ids or record.get("away_team_id") in selected_ids
            ]
        records.extend(parsed)
    return sorted(records, key=lambda record: (str(record.get("kickoff_at") or ""), str(record.get("canonical_match_id") or "")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--team-id", action="append", dest="team_ids")
    args = parser.parse_args()
    records = load_openfootball_records(args.raw_root, include_team_ids=args.team_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "contract_version": "historical_result_sample.v1",
        "provider": "openfootball",
        "record_count": len(records),
        "eligible_record_count": sum(record.get("eligible_for_team_strength") is True for record in records),
        "records": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = HistoricalResultLedger(args.ledger_root)
    for record in records:
        ledger.append(record)
    print(f"wrote {len(records)} normalized OpenFootball pilot records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
