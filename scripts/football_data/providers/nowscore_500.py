"""Adapter for already captured Nowscore/500 snapshots.

This adapter intentionally accepts evidence that is already in memory. It does
not scrape a website and it never turns missing provider fields into claims of
absence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import validate_record
from ..competition_resolution import CompetitionEntityResolver
from ..entity_resolution import TeamEntityResolver
from ..player_identity import PlayerIdentityResolver
from ..quality import finalize_record_quality
from .base import common_record, provenance


class Nowscore500SnapshotProvider:
    provider_name = "nowscore_500_snapshot"
    provider_version = "snapshot-adapter.v1"

    def __init__(
        self,
        snapshot: Mapping[str, Any],
        *,
        resolver: TeamEntityResolver | None = None,
        competition_resolver: CompetitionEntityResolver | None = None,
        player_resolver: PlayerIdentityResolver | None = None,
        captured_at: str | None = None,
    ) -> None:
        self.snapshot = dict(snapshot)
        self.resolver = resolver
        self.competition_resolver = competition_resolver
        self.player_resolver = player_resolver
        self.captured_at = captured_at or self.snapshot.get("captured_at") or self.snapshot.get("fetched_at")
        if not self.captured_at:
            raise ValueError("captured_at is required for a reproducible Nowscore/500 snapshot")
        self.source_as_of_at = self.snapshot.get("source_as_of_at") or self.snapshot.get("as_of_at")
        self.provider_competition_id = self.snapshot.get("competition_id")
        self.provider_competition_name = self.snapshot.get("competition") if self.provider_competition_id is None else self.snapshot.get("competition_name")
        self.provider_season_id = self.snapshot.get("season_id")
        self.provider_season_name = self.snapshot.get("season") if self.provider_season_id is None else self.snapshot.get("season_name")
        self.competition_resolution = (
            competition_resolver.resolve(
                provider=self._source_name(),
                provider_competition_id=str(self.provider_competition_id) if self.provider_competition_id is not None else None,
                provider_competition_name=str(self.provider_competition_name) if self.provider_competition_name is not None else None,
                provider_season_id=str(self.provider_season_id) if self.provider_season_id is not None else None,
                provider_season_name=str(self.provider_season_name) if self.provider_season_name is not None else None,
            )
            if competition_resolver is not None else None
        )
        self.canonical_competition_id = self.competition_resolution.canonical_competition_id if self.competition_resolution else None
        self.canonical_season_id = self.competition_resolution.canonical_season_id if self.competition_resolution else None
        self.competition = self.canonical_competition_id
        self.season = self.canonical_season_id

    def _source_name(self) -> str:
        value = str(self.snapshot.get("source") or self.snapshot.get("provider") or "nowscore").casefold()
        return "500" if "500" in value else "nowscore"

    def _team_rows(self) -> list[tuple[str, Mapping[str, Any]]]:
        rows = self.snapshot.get("teams")
        if isinstance(rows, list):
            result = []
            for row in rows:
                if isinstance(row, Mapping):
                    result.append((str(row.get("home_away_context") or row.get("context") or "unknown"), row))
            return result
        result = []
        for context, key in (("home", "home_team"), ("away", "away_team")):
            row = self.snapshot.get(key)
            if isinstance(row, Mapping):
                result.append((context, row))
            elif isinstance(row, str) and row.strip():
                result.append((context, {"name": row}))
        return result

    def _resolve(self, row: Mapping[str, Any]) -> Any:
        provider = self._source_name()
        name = row.get("name") or row.get("team_name") or row.get("title")
        provider_id = row.get("provider_team_id") or row.get("team_id") or row.get("id")
        if self.resolver is None:
            return None, name, provider_id
        result = self.resolver.resolve_team(
            provider=provider,
            provider_team_name=str(name) if name is not None else None,
            provider_team_id=str(provider_id) if provider_id is not None else None,
            country=row.get("country"),
            competition_context=self.canonical_competition_id if self.canonical_competition_id and self.canonical_competition_id.startswith("competition:") else None,
            gender=row.get("gender"),
            team_level=row.get("team_level"),
        )
        return result, name, provider_id

    def _freshness(self) -> dict[str, Any]:
        return {"state": "unknown", "age_seconds": None, "ttl_seconds": None}

    def _finish(self, record: dict[str, Any], *, data_class: str, record_type: str) -> dict[str, Any]:
        record.update({
            "provider_competition_id": str(self.provider_competition_id) if self.provider_competition_id is not None else None,
            "provider_competition_name": str(self.provider_competition_name) if self.provider_competition_name is not None else None,
            "provider_season_id": str(self.provider_season_id) if self.provider_season_id is not None else None,
            "provider_season_name": str(self.provider_season_name) if self.provider_season_name is not None else None,
            "canonical_competition_id": self.canonical_competition_id,
            "canonical_season_id": self.canonical_season_id,
        })
        finalize_record_quality(record, data_class=data_class, record_type=record_type)
        validate_record(record_type, record)
        return record

    def get_team_identity(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        source = self._source_name()
        output = []
        for context, row in self._team_rows():
            resolved, name, provider_id = self._resolve(row)
            canonical_id = resolved.canonical_team_id if resolved else None
            canonical_name = resolved.canonical_name if resolved else (str(name) if name else "Unresolved team")
            missing = [] if canonical_id else ["identity_unresolved"]
            record = common_record(
                contract_version="team_identity.v1",
                source=source,
                source_entity_id=str(provider_id) if provider_id is not None else (str(name) if name else None),
                canonical_entity_id=canonical_id,
                captured_at=self.captured_at,
                source_as_of_at=self.source_as_of_at,
                competition=self.competition,
                season=self.season,
                home_away_context=context if context in {"home", "away"} else "unknown",
                sample_matches=0,
                sample_minutes=None,
                value=None,
                unit=None,
                quality="C",
                freshness=self._freshness(),
                missing_reason=missing,
                provenance_record=provenance(
                    provider=source,
                    source=source,
                    source_record_ref=f"snapshot:team:{provider_id or name}",
                    captured_at=self.captured_at,
                    source_as_of_at=self.source_as_of_at,
                    parser_version=self.provider_version,
                ),
            )
            record.update(
                {
                    "canonical_name": canonical_name,
                    "country": row.get("country"),
                    "gender": row.get("gender") or "unknown",
                    "team_level": row.get("team_level") or "unknown",
                    "resolution_status": "resolved" if canonical_id else "unresolved",
                    "resolution_method": resolved.resolution_method if resolved else "unresolved",
                    "confidence": resolved.confidence if resolved else None,
                }
            )
            output.append(self._finish(record, data_class="slow_changing", record_type="team_identity"))
        return output

    def _recent_form_payload(self) -> list[tuple[str, Mapping[str, Any]]]:
        shuju = self.snapshot.get("shuju")
        form = self.snapshot.get("recent_form")
        if form is None and isinstance(shuju, Mapping):
            form = shuju.get("recent_form")
        if isinstance(form, Mapping):
            rows: list[tuple[str, Mapping[str, Any]]] = []
            team_by_role = {
                context: row
                for context, row in self._team_rows()
                if context in {"home", "away"}
            }
            for key, values in form.items():
                key_text = str(key)
                role = "home" if key_text.startswith("home") else "away" if key_text.startswith("away") else "overall"
                venue = "home" if key_text.endswith("_home") else "away" if key_text.endswith("_away") else "overall"
                if isinstance(values, Mapping):
                    row = dict(values)
                    team = team_by_role.get(role, {})
                    row.setdefault("team_name", team.get("name") or team.get("team_name"))
                    row.setdefault("team_id", team.get("team_id") or team.get("provider_team_id") or team.get("id"))
                    row["_window_context"] = key_text
                    rows.append((venue, row))
                elif isinstance(values, list):
                    for value in values:
                        if isinstance(value, Mapping):
                            row = dict(value)
                            row.setdefault("_window_context", key_text)
                            rows.append((venue if venue != "overall" else role, row))
            return rows
        if isinstance(form, list):
            return [("overall", {**row, "_window_context": "overall"}) for row in form if isinstance(row, Mapping)]
        return []

    @staticmethod
    def _number(row: Mapping[str, Any], *keys: str) -> float | int | None:
        for key in keys:
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
        return None

    def get_match_history(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        source = self._source_name()
        grouped: dict[str, dict[str, Any]] = {}
        for context, row in self._recent_form_payload():
            team_name = row.get("team_name") or row.get("team") or row.get("name")
            team_id = row.get("team_id") or row.get("provider_team_id")
            window_context = str(row.get("_window_context") or "overall")
            key = f"{team_id or team_name or context}:{context}:{window_context}"
            bucket = grouped.setdefault(key, {"context": context, "row": row, "rows": []})
            bucket["rows"].append(row)
        output = []
        for key, bucket in grouped.items():
            rows = bucket["rows"]
            first = bucket["row"]
            team_name = first.get("team_name") or first.get("team") or first.get("name")
            fake_team = {"name": team_name, "team_id": first.get("team_id") or first.get("provider_team_id")}
            resolved, _, provider_id = self._resolve(fake_team)
            canonical_id = resolved.canonical_team_id if resolved else None
            goals_for = sum((self._number(row, "goals_for", "gf", "scored") or 0) for row in rows)
            goals_against = sum((self._number(row, "goals_against", "ga", "conceded") or 0) for row in rows)
            sample_matches = sum(int(self._number(row, "matches") or 0) for row in rows) or len(rows)
            has_goal_fields = any(any(field in row for field in ("goals_for", "gf", "scored", "goals_against", "ga", "conceded")) for row in rows)
            missing = []
            if not canonical_id:
                missing.append("identity_unresolved")
            if not has_goal_fields:
                missing.append("provider_goal_fields_unverified")
            record = common_record(
                contract_version="team_form_snapshot.v1",
                source=source,
                source_entity_id=str(provider_id or key),
                canonical_entity_id=canonical_id,
                captured_at=self.captured_at,
                source_as_of_at=self.source_as_of_at,
                competition=self.competition,
                season=self.season,
                home_away_context=bucket["context"] if bucket["context"] in {"home", "away", "overall"} else "unknown",
                sample_matches=sample_matches,
                sample_minutes=None,
                value=None,
                unit="goals",
                quality="C",
                freshness=self._freshness(),
                missing_reason=missing,
                provenance_record=provenance(
                    provider=source,
                    source=source,
                    source_record_ref=f"snapshot:recent_form:{key}",
                    captured_at=self.captured_at,
                    source_as_of_at=self.source_as_of_at,
                    parser_version=self.provider_version,
                ),
            )
            record.update(
                {
                    "team_id": canonical_id or f"unresolved:{key}",
                    "competition_id": self.competition,
                    "season_id": self.season,
                    "as_of_at": self.source_as_of_at,
                    "matches": sample_matches,
                    "window_type": str(first.get("window_type") or ("last_5" if sample_matches <= 5 else "last_10")),
                    "window_start": str(rows[0].get("window_start") or rows[0].get("date") or self.source_as_of_at or "unknown"),
                    "window_end": str(rows[-1].get("window_end") or rows[-1].get("date") or self.source_as_of_at or "unknown"),
                    "minutes": None,
                    "metrics": {"goals_for": goals_for if has_goal_fields else None, "goals_against": goals_against if has_goal_fields else None},
                }
            )
            output.append(self._finish(record, data_class="slow_changing", record_type="team_form_snapshot"))
        return output

    def get_team_stats(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.get_match_history(payload)

    def get_xg(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return only an explicitly structured provider xG list; never infer xG."""

        rows = self.snapshot.get("xg")
        if not isinstance(rows, list):
            return []
        source = self._source_name()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            value = row.get("value")
            if not isinstance(value, (int, float)):
                continue
            resolved, name, provider_id = self._resolve(row)
            record = common_record(
                contract_version="xg_snapshot.v1",
                source=source,
                source_entity_id=str(provider_id or name),
                canonical_entity_id=resolved.canonical_team_id if resolved else None,
                captured_at=self.captured_at,
                source_as_of_at=self.source_as_of_at,
                competition=self.competition,
                season=self.season,
                home_away_context=str(row.get("home_away_context") or "overall"),
                sample_matches=int(row.get("matches") or 0),
                sample_minutes=row.get("minutes"),
                value=value,
                unit="goals",
                quality="C",
                freshness=self._freshness(),
                missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider=source, source=source, source_record_ref=f"snapshot:xg:{provider_id or name}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, parser_version=self.provider_version),
            )
            record.update({
                "team_id": resolved.canonical_team_id if resolved else f"unresolved:{provider_id or name}",
                "competition_id": self.competition,
                "season_id": self.season,
                "as_of_at": self.source_as_of_at,
                "provider": source,
                "metric_definition": row.get("metric_definition") or "provider_reported_xg",
                "includes_penalties": row.get("includes_penalties"),
                "post_shot_or_pre_shot": row.get("post_shot_or_pre_shot") or "unknown",
                "model_version_if_known": row.get("model_version_if_known"),
                "normalization_version": None,
            })
            output.append(self._finish(record, data_class="historical_immutable", record_type="xg_snapshot"))
        return output

    def get_lineup(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self.snapshot.get("lineups") or self.snapshot.get("lineup")
        return self._lineup_records(rows) if isinstance(rows, list) else []

    def _lineup_records(self, rows: list[Any]) -> list[dict[str, Any]]:
        source = self._source_name()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            team_id = row.get("team_id") or row.get("provider_team_id")
            team_name = row.get("team_name") or row.get("team")
            resolved, _, provider_id = self._resolve({"team_id": team_id, "name": team_name})
            players = []
            resolved_players = 0
            for player in row.get("players", []):
                if not isinstance(player, Mapping):
                    continue
                starter = player.get("starter") if isinstance(player.get("starter"), bool) else None
                bench = player.get("bench") if isinstance(player.get("bench"), bool) else (not starter if starter is not None else None)
                player_resolution = None
                if self.player_resolver is not None:
                    player_resolution = self.player_resolver.resolve_player(
                        source,
                        str(player.get("name") or "") or None,
                        str(player.get("provider_player_id") or player.get("player_id") or "") or None,
                        team_id=resolved.canonical_team_id if resolved else None,
                    )
                if player_resolution and player_resolution.canonical_player_id:
                    resolved_players += 1
                players.append({
                    "canonical_player_id": player_resolution.canonical_player_id if player_resolution else None,
                    "provider_player_id": str(player.get("provider_player_id") or player.get("player_id") or ""),
                    "name": str(player.get("name") or "Unknown player"),
                    "team_id": resolved.canonical_team_id if resolved else f"unresolved:{provider_id or team_id or team_name}",
                    "position": player.get("position"),
                    "starter": starter,
                    "bench": bench,
                    "captain": player.get("captain") if isinstance(player.get("captain"), bool) else None,
                    "goalkeeper": player.get("goalkeeper") if isinstance(player.get("goalkeeper"), bool) else None,
                    "source": source,
                    "captured_at": self.captured_at,
                    "status": row.get("status") or "confirmed",
                })
            record = common_record(
                contract_version="lineup_snapshot.v1", source=source, source_entity_id=str(provider_id or team_id or team_name), canonical_entity_id=resolved.canonical_team_id if resolved else None,
                captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, competition=self.competition, season=self.season,
                home_away_context=str(row.get("home_away_context") or "unknown"), sample_matches=1, sample_minutes=None, value=None, unit=None,
                quality="C", freshness=self._freshness(), missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider=source, source=source, source_record_ref=f"snapshot:lineup:{provider_id or team_id or team_name}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, parser_version=self.provider_version),
            )
            total_players = len(players)
            record.update({
                "match_id": str(self.snapshot.get("match_id") or "unresolved:match"),
                "team_id": resolved.canonical_team_id if resolved else f"unresolved:{provider_id or team_id or team_name}",
                "status": row.get("status") or "confirmed",
                "players": players,
                "player_identity_coverage": {
                    "resolved_players": resolved_players,
                    "total_players": total_players,
                    "coverage_ratio": round(resolved_players / total_players, 6) if total_players else 0.0,
                },
            })
            output.append(self._finish(record, data_class="fast_changing", record_type="lineup_snapshot"))
        return output

    def get_availability(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self.snapshot.get("availability")
        if not isinstance(rows, list):
            return []
        source = self._source_name()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            team_id = row.get("team_id") or row.get("provider_team_id")
            resolved, name, provider_id = self._resolve(row)
            record = common_record(
                contract_version="availability_snapshot.v1", source=source, source_entity_id=str(provider_id or name), canonical_entity_id=resolved.canonical_team_id if resolved else None,
                captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, competition=self.competition, season=self.season,
                home_away_context=str(row.get("home_away_context") or "unknown"), sample_matches=1, sample_minutes=None, value=None, unit=None,
                quality="C", freshness=self._freshness(), missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider=source, source=source, source_record_ref=f"snapshot:availability:{row.get('provider_player_id') or row.get('player_name')}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, parser_version=self.provider_version),
            )
            record.update({
                "team_id": resolved.canonical_team_id if resolved else f"unresolved:{team_id or provider_id or name}",
                "canonical_player_id": row.get("canonical_player_id"),
                "provider_player_id": row.get("provider_player_id"),
                "player_name": str(row.get("player_name") or row.get("name") or "Unknown player"),
                "status": row.get("status") or "unknown",
                "evidence": [str(v) for v in row.get("evidence", [])] if isinstance(row.get("evidence"), list) else [],
                "source_timestamp": row.get("source_timestamp"),
                "confidence": row.get("confidence"),
            })
            output.append(self._finish(record, data_class="fast_changing", record_type="availability_snapshot"))
        return output
