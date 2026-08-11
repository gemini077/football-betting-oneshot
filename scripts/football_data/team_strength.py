"""Transparent pre-match team-strength snapshots from immutable results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import validate_record
from .historical_results import deduplicate_historical_results
from .providers.base import common_record, provenance, utc_now
from .quality import finalize_record_quality, load_quality_rules
from .storage import DuckDBSnapshotStore, HistoricalResultStore, content_sha256


WINDOW_LIMITS = {"last_5": 5, "last_10": 10, "last_20": 20}
SUPPORTED_WINDOWS = frozenset((*WINDOW_LIMITS, "season_to_date"))
DEFAULT_RECENCY_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "team_strength_recency.json"


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


def load_recency_rules(path: str | Path = DEFAULT_RECENCY_RULES_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _team_strength_quality_rules() -> dict[str, Any]:
    """Use historical fact time for strength freshness; never capture fallback."""

    rules = load_quality_rules()
    policy = dict(rules.get("freshness_policies", {}).get("slow_changing", {}))
    policy["requires_source_fact_time"] = True
    policy["allow_capture_time_fallback"] = False
    rules["freshness_policies"] = {**rules.get("freshness_policies", {}), "slow_changing": policy}
    return rules


def classify_history_recency(
    latest_historical_match_at: str | None,
    target_kickoff: str,
    *,
    bridge_context: Mapping[str, Any] | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify history age without confusing source capture with match time."""

    config = rules or load_recency_rules()
    target = _parse_time(target_kickoff)
    latest = _parse_time(latest_historical_match_at)
    context = dict(bridge_context or {})
    bridge_status = str(context.get("bridge_status") or "not_applicable")
    result: dict[str, Any] = {
        "latest_historical_match_at": latest_historical_match_at,
        "history_age_days": None,
        "latest_match_gap_days": None,
        "history_recency_status": "unknown",
        "current_strength_ready": False,
        "bridge_status": bridge_status,
        "bridge_from_season": context.get("bridge_from_season"),
        "bridge_reason": context.get("bridge_reason"),
        "bridge_verification_evidence": list(context.get("bridge_verification_evidence") or []),
    }
    if target is None or latest is None:
        return result
    age_seconds = (target - latest).total_seconds()
    if age_seconds < 0:
        result["history_recency_status"] = "unknown"
        result["bridge_status"] = "timestamp_conflict"
        result["bridge_reason"] = "latest historical match is after target kickoff"
        return result

    age_days = round(age_seconds / 86400, 6)
    result["history_age_days"] = age_days
    result["latest_match_gap_days"] = age_days
    if age_days <= int(config.get("current_max_history_age_days", 60)):
        result["history_recency_status"] = "current"
        result["current_strength_ready"] = True
        return result

    bridge_verified = bridge_status == "verified"
    opening = str(context.get("season_stage") or "") in {"opening", "very_early"}
    evidence = result["bridge_verification_evidence"]
    requires_evidence = bool(config.get("bridge_requires_verified_evidence", True))
    if (
        bridge_verified
        and opening
        and (not requires_evidence or bool(evidence))
        and age_days <= int(config.get("offseason_bridge_max_history_age_days", 180))
    ):
        result["history_recency_status"] = "offseason_bridge"
        return result

    result["history_recency_status"] = "stale"
    return result


class TeamStrengthBuilder:
    """Build one team snapshot using only results strictly before a target."""

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]] | HistoricalResultStore,
        *,
        captured_at: str | None = None,
        snapshot_revision: str | None = None,
    ) -> None:
        if hasattr(records, "iter_records"):
            source_records = list(records.iter_records())
            input_dataset_digest = records.dataset_digest()  # type: ignore[union-attr]
        else:
            source_records = [dict(record) for record in records]
            input_dataset_digest = content_sha256(
                sorted(content_sha256(record) for record in source_records)
            )
        report = deduplicate_historical_results(source_records)
        self.records = report.records
        self.deduplication = report
        self.captured_at = captured_at or utc_now()
        self.snapshot_revision = snapshot_revision
        self.input_dataset_digest = input_dataset_digest
        self.builder_version = "team-strength-builder.v2-duckdb"

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
        bridge_context: Mapping[str, Any] | None = None,
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
        latest_historical_match_at = selected[-1].get("kickoff_at") if selected else None
        latest_match_time = _parse_time(latest_historical_match_at)
        effective_bridge_context = dict(bridge_context or {})
        if selected and season_id and str(selected[-1].get("season_id")) != str(season_id) and not effective_bridge_context.get("bridge_status"):
            effective_bridge_context.update({
                "bridge_status": "unverified",
                "bridge_reason": "target season differs from latest historical season and no verified opening evidence",
            })
        recency = classify_history_recency(
            latest_historical_match_at,
            target_kickoff,
            bridge_context=effective_bridge_context,
        )
        providers = sorted({str(row.get("provider")) for row in selected if row.get("provider")})
        reliable = bool(selected) and all(row.get("provenance", {}).get("source_reliable") is True for row in selected)
        synthetic = any(bool(row.get("provenance", {}).get("synthetic")) for row in selected)
        provider_name = providers[0] if len(providers) == 1 else "mixed_historical_sources" if providers else "historical_result_ledger"
        effective_window = window_type if window_type == "season_to_date" else f"last_{matches}" if matches else "none"
        window_start = selected[0].get("kickoff_at") if selected else target_kickoff
        snapshot_id = f"{target_match_id or f'target:{target_kickoff}'}:team:{team_id}:window:{window_type}"
        if self.snapshot_revision:
            snapshot_id = f"{snapshot_id}:revision:{self.snapshot_revision}"
        missing = [] if matches else ["insufficient_history"]
        record = common_record(
            contract_version="team_strength_snapshot.v1",
            source="historical_result_ledger",
            source_entity_id=team_id,
            canonical_entity_id=team_id,
            captured_at=self.captured_at,
            source_as_of_at=_iso(latest_match_time) if latest_match_time else None,
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
                source_as_of_at=_iso(latest_match_time) if latest_match_time else None,
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
            "latest_historical_match_at": recency["latest_historical_match_at"],
            "history_age_days": recency["history_age_days"],
            "latest_match_gap_days": recency["latest_match_gap_days"],
            "history_recency_status": recency["history_recency_status"],
            "current_strength_ready": bool(matches and recency["current_strength_ready"]),
            "history_available": bool(matches),
            "bridge_status": recency["bridge_status"],
            "bridge_from_season": recency["bridge_from_season"],
            "bridge_reason": recency["bridge_reason"],
            "bridge_verification_evidence": recency["bridge_verification_evidence"],
            "oldest_used_match_at": selected[0].get("kickoff_at") if selected else None,
            "opponent_adjusted": None,
            "snapshot_id": snapshot_id,
            "input_dataset_digest": self.input_dataset_digest,
            "builder_version": self.builder_version,
            "validated_for_model": False,
        })
        finalize_record_quality(
            record,
            data_class="slow_changing",
            record_type="team_strength_snapshot",
            now=target_time,
            rules=_team_strength_quality_rules(),
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
                    bridge_context=target_match.get("bridge_context"),
                )
        return output


class PreMatchSnapshotStore:
    """Persist pre-match snapshots in one immutable DuckDB table."""

    def __init__(self, root: str | Path) -> None:
        self.store = DuckDBSnapshotStore(root)

    def put(self, snapshot: Mapping[str, Any], *, snapshot_id: str | None = None) -> str:
        identity = snapshot_id or str(snapshot.get("snapshot_id") or "")
        if not identity:
            raise ValueError("immutable snapshot requires snapshot_id")
        if snapshot.get("snapshot_id") not in (None, identity):
            raise ValueError(f"snapshot identity mismatch: {identity}")
        value = dict(snapshot)
        value["snapshot_id"] = identity
        return self.store.put(value)

    def get(self, snapshot_id: str) -> dict[str, Any]:
        return self.store.get(snapshot_id)
