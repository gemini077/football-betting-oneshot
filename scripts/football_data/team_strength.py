"""Transparent pre-match team-strength snapshots from immutable results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import validate_record
from .historical_results import deduplicate_historical_results
from .providers.base import common_record, provenance, utc_now
from .quality import finalize_record_quality
from .storage import canonical_json_bytes


WINDOW_LIMITS = {"last_5": 5, "last_10": 10, "last_20": 20}
SUPPORTED_WINDOWS = frozenset((*WINDOW_LIMITS, "season_to_date"))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mean(value: int, matches: int) -> float | None:
    return round(value / matches, 6) if matches else None


class TeamStrengthBuilder:
    """Build one team snapshot using only results strictly before a target."""

    def __init__(self, records: Iterable[Mapping[str, Any]], *, captured_at: str | None = None) -> None:
        report = deduplicate_historical_results(records)
        self.records = report.records
        self.deduplication = report
        self.captured_at = captured_at or utc_now()

    def _eligible_before(
        self,
        team_id: str,
        target_kickoff: datetime,
        *,
        competition_id: str | None,
        season_id: str | None,
        window_type: str,
        entity_type: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in self.records:
            if record.get("eligible_for_team_strength") is not True:
                continue
            if record.get("duplicate_status") not in {"unique", "duplicate_same"}:
                continue
            if record.get("entity_type", "club") != entity_type:
                continue
            if window_type == "season_to_date" and (
                record.get("competition_id") != competition_id or record.get("season_id") != season_id
            ):
                continue
            kickoff = _parse_time(record.get("kickoff_at"))
            if kickoff is None or kickoff >= target_kickoff:
                continue
            if record.get("home_team_id") != team_id and record.get("away_team_id") != team_id:
                continue
            rows.append(record)
        return sorted(rows, key=lambda row: (_parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("canonical_match_id") or "")))

    @staticmethod
    def _team_line(record: Mapping[str, Any], team_id: str) -> tuple[int, int, str, str]:
        if record.get("home_team_id") == team_id:
            return int(record["home_goals"]), int(record["away_goals"]), "home", str(record["away_team_id"])
        return int(record["away_goals"]), int(record["home_goals"]), "away", str(record["home_team_id"])

    def build(
        self,
        team_id: str,
        *,
        target_kickoff: str,
        window_type: str,
        competition_id: str | None = None,
        season_id: str | None = None,
        target_match_id: str | None = None,
        entity_type: str = "club",
    ) -> dict[str, Any]:
        if window_type not in SUPPORTED_WINDOWS:
            raise ValueError(f"unsupported team-strength window: {window_type}")
        target_time = _parse_time(target_kickoff)
        if target_time is None:
            raise ValueError("target_kickoff must be an ISO timestamp")
        if window_type == "season_to_date" and (not competition_id or not season_id):
            raise ValueError("season_to_date requires canonical competition_id and season_id")
        available = self._eligible_before(
            team_id,
            target_time,
            competition_id=competition_id,
            season_id=season_id,
            window_type=window_type,
            entity_type=entity_type,
        )
        if window_type in WINDOW_LIMITS:
            selected = available[-WINDOW_LIMITS[window_type]:]
        else:
            selected = available

        goals_for = 0
        goals_against = 0
        venue = {
            "home": {"matches": 0, "goals_for": 0, "goals_against": 0},
            "away": {"matches": 0, "goals_for": 0, "goals_against": 0},
        }
        opponents: list[str] = []
        source_match_ids: list[str] = []
        for record in selected:
            scored, conceded, context, opponent = self._team_line(record, team_id)
            goals_for += scored
            goals_against += conceded
            venue[context]["matches"] += 1
            venue[context]["goals_for"] += scored
            venue[context]["goals_against"] += conceded
            opponents.append(opponent)
            source_match_ids.append(str(record.get("canonical_match_id")))

        matches = len(selected)
        latest_source_time = max((_parse_time(row.get("source_as_of_at")) for row in selected if _parse_time(row.get("source_as_of_at"))), default=None)
        providers = sorted({str(row.get("provider")) for row in selected if row.get("provider")})
        reliable = bool(selected) and all(row.get("provenance", {}).get("source_reliable") is True for row in selected)
        synthetic = any(bool(row.get("provenance", {}).get("synthetic")) for row in selected)
        provider_name = providers[0] if len(providers) == 1 else "mixed_historical_sources" if providers else "historical_result_ledger"
        effective_window = window_type if window_type == "season_to_date" else f"last_{matches}" if matches else "none"
        window_start = selected[0].get("kickoff_at") if selected else target_kickoff
        snapshot_id = f"{target_match_id or f'target:{target_kickoff}'}:team:{team_id}:window:{window_type}"
        missing = [] if matches else ["insufficient_history"]
        record = common_record(
            contract_version="team_strength_snapshot.v1",
            source="historical_result_ledger",
            source_entity_id=team_id,
            canonical_entity_id=team_id,
            captured_at=self.captured_at,
            source_as_of_at=_iso(latest_source_time) if latest_source_time else None,
            competition=competition_id,
            season=season_id,
            home_away_context="overall",
            sample_matches=matches,
            sample_minutes=None,
            value=None,
            unit="goals_per_match",
            quality="C",
            freshness={"state": "unknown", "age_seconds": None, "ttl_seconds": None},
            missing_reason=missing,
            provenance_record=provenance(
                provider=provider_name,
                source="historical_result_ledger",
                source_record_ref=f"ledger:team-strength:{team_id}:{target_kickoff}:{window_type}",
                captured_at=self.captured_at,
                source_as_of_at=_iso(latest_source_time) if latest_source_time else None,
                source_reliable=reliable and not synthetic,
                parser_version="team-strength-builder.v1",
                synthetic=synthetic,
                observation_origin="normalized_historical_result_aggregation",
            ),
        )
        record.update({
            "team_id": team_id,
            "entity_type": entity_type,
            "competition_id": competition_id,
            "season_id": season_id,
            "as_of_at": target_kickoff,
            "matches": matches,
            "available_matches": len(available),
            "requested_window": window_type,
            "effective_window": effective_window,
            "window_type": window_type,
            "window_start": window_start,
            "window_end": target_kickoff,
            "minutes": None,
            "metrics": {
                "goals_for_per_match": _mean(goals_for, matches),
                "goals_against_per_match": _mean(goals_against, matches),
                "home": venue["home"],
                "away": venue["away"],
                "opponent_adjusted": None,
            },
            "opponents": opponents,
            "source_match_ids": source_match_ids,
            "sources": providers,
            "latest_historical_match_at": selected[-1].get("kickoff_at") if selected else None,
            "oldest_used_match_at": selected[0].get("kickoff_at") if selected else None,
            "opponent_adjusted": None,
            "snapshot_id": snapshot_id,
            "validated_for_model": False,
        })
        finalize_record_quality(
            record,
            data_class="slow_changing",
            record_type="team_strength_snapshot",
            now=_parse_time(self.captured_at),
        )
        validate_record("team_strength_snapshot", record)
        return record

    def build_pre_match_snapshots(
        self,
        target_match: Mapping[str, Any],
        *,
        windows: Iterable[str] = ("last_5", "last_10", "last_20", "season_to_date"),
    ) -> dict[str, Any]:
        kickoff = target_match.get("kickoff_at") or target_match.get("kickoff")
        target_id = target_match.get("canonical_match_id") or target_match.get("id")
        output: dict[str, Any] = {
            "target_match_id": target_id,
            "target_kickoff": kickoff,
            "home": {},
            "away": {},
        }
        for side in ("home", "away"):
            team_id = target_match.get(f"{side}_team_id")
            if not team_id:
                continue
            for window in windows:
                output[side][window] = self.build(
                    str(team_id),
                    target_kickoff=str(kickoff),
                    window_type=window,
                    competition_id=target_match.get("competition_id"),
                    season_id=target_match.get("season_id"),
                    target_match_id=str(target_id) if target_id else None,
                    entity_type=str(target_match.get("entity_type") or "club"),
                )
        return output


class PreMatchSnapshotStore:
    """Persist a pre-match snapshot by stable identity without overwrite."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, snapshot_id: str) -> Path:
        digest = hashlib.sha256(snapshot_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def put(self, snapshot: Mapping[str, Any], *, snapshot_id: str | None = None) -> str:
        identity = snapshot_id or str(snapshot.get("snapshot_id") or "")
        if not identity:
            raise ValueError("immutable snapshot requires snapshot_id")
        path = self._path(identity)
        encoded = canonical_json_bytes(snapshot) + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError(f"immutable pre-match snapshot conflict: {identity}")
        if not path.exists():
            path.write_bytes(encoded)
        return identity

    def get(self, snapshot_id: str) -> dict[str, Any]:
        path = self._path(snapshot_id)
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if value.get("snapshot_id") != snapshot_id:
            raise ValueError(f"snapshot identity mismatch: {path}")
        return value
