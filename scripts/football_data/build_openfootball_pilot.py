"""Build a bounded normalized OpenFootball pilot from captured source files.

This command is intentionally offline: the caller supplies a capture directory
and a source manifest.  It writes only the selected normalized observations,
never the upstream database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .historical_results import HistoricalResultLedger
from .data_home import historical_results_path
from .providers.openfootball import OpenFootballHistoricalAdapter


DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "football_data" / "openfootball" / "source_manifest.json"
DEFAULT_IDENTITIES = Path(__file__).resolve().parents[2] / "data" / "football_data" / "openfootball" / "identity_evidence.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "football_data" / "historical_result_samples" / "openfootball_pilot.json"
DEFAULT_LEDGER_ROOT = historical_results_path()


def load_openfootball_records(
    raw_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    identity_path: str | Path = DEFAULT_IDENTITIES,
    include_team_ids: Iterable[str] | None = None,
    cutoff_at: str | None = None,
    include_ambiguous_scores: bool = False,
) -> list[dict[str, Any]]:
    raw_root = Path(raw_root)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    identity_rows = json.loads(Path(identity_path).read_text(encoding="utf-8")).get("teams", [])
    identity_map = {str(row["provider_team_name"]): row for row in identity_rows}
    selected_ids = set(include_team_ids or ())
    cutoff = None
    if cutoff_at is not None:
        cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            raise ValueError("cutoff_at must include a timezone")
        cutoff = cutoff.astimezone(timezone.utc)
    records: list[dict[str, Any]] = []
    for source in manifest.get("sources", []):
        source_path = raw_root / str(source["source_file"])
        raw_bytes = source_path.read_bytes()
        actual_raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        expected_raw_sha256 = source.get("raw_sha256")
        if expected_raw_sha256 and str(expected_raw_sha256).lower() != actual_raw_sha256:
            raise ValueError(f"raw SHA256 mismatch for {source['source_file']}")
        raw_text = raw_bytes.decode("utf-8-sig")
        adapter = OpenFootballHistoricalAdapter(
            competition_id=str(source.get("canonical_competition_id") or f"competition:{source['competition_key']}"),
            season_id=str(source.get("canonical_season_id") or f"season:{source['competition_key']}:{source['provider_season_id']}"),
            provider_competition_id=str(source["provider_competition_id"]),
            provider_competition_name=str(source["provider_competition_name"]),
            provider_season_id=str(source["provider_season_id"]),
            provider_season_name=str(source["provider_season_name"]),
            repository=str(manifest["repository"]),
            commit_sha=str(manifest["commit_sha"]),
            source_file=str(source["source_file"]),
            captured_at=str(manifest["captured_at"]),
            source_as_of_at=str(source.get("source_as_of_at") or manifest["captured_at"]),
            country=source.get("country") or ("Sweden" if str(source["competition_key"]).startswith("sweden") else "Portugal"),
            entity_type=str(source.get("entity_type", "club")),
            match_type=str(source.get("match_type", "league")),
            team_identity_resolver=identity_map,
        )
        parsed = adapter.parse_text(raw_text, raw_sha256=actual_raw_sha256)
        if cutoff is not None:
            parsed = [
                record for record in parsed
                if datetime.fromisoformat(str(record["kickoff_at"]).replace("Z", "+00:00")).astimezone(timezone.utc) < cutoff
            ]
        if not include_ambiguous_scores:
            parsed = [record for record in parsed if record.get("score_semantics") == "90_minute_unambiguous"]
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
    parser.add_argument("--cutoff-at")
    parser.add_argument("--include-ambiguous-scores", action="store_true")
    args = parser.parse_args()
    records = load_openfootball_records(
        args.raw_root,
        include_team_ids=args.team_ids,
        cutoff_at=args.cutoff_at,
        include_ambiguous_scores=args.include_ambiguous_scores,
    )
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
