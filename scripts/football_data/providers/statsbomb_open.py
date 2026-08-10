"""Offline adapter for selected StatsBomb Open Data JSON fixtures.

No network access, credentials, or statsbombpy dependency is used. The
adapter preserves provider-specific definitions and attribution metadata.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..contracts import validate_record
from ..entity_resolution import TeamEntityResolver
from ..player_identity import PlayerIdentityResolver
from .base import common_record, provenance


class StatsBombOpenDataProvider:
    provider_name = "statsbomb_open_data"
    provider_version = "offline-json-adapter.v1"
    SOURCE_URL = "https://github.com/hudl/open-data"
    DATA_LICENSE = "StatsBomb Open Data LICENSE.pdf / User Agreement review required"

    def __init__(self, fixture_root: str | Path, *, resolver: TeamEntityResolver | None = None, player_resolver: PlayerIdentityResolver | None = None) -> None:
        self.fixture_root = Path(fixture_root)
        self.resolver = resolver
        self.player_resolver = player_resolver
        self.metadata = self._read("metadata.json") if (self.fixture_root / "metadata.json").exists() else {}
        self.match = self._read("match.json")
        self.events = self._read("events.json")
        self.lineups = self._read("lineups.json")
        if not isinstance(self.match, Mapping) or not isinstance(self.events, list) or not isinstance(self.lineups, list):
            raise ValueError("StatsBomb fixture must contain match object, events list and lineups list")
        self.captured_at = str(self.metadata.get("captured_at") or self.match.get("captured_at") or "")
        if not self.captured_at:
            raise ValueError("StatsBomb fixture requires captured_at metadata")
        self.source_as_of_at = self.metadata.get("source_as_of_at") or self.match.get("source_as_of_at") or self.captured_at
        self.competition = self.metadata.get("competition_id") or self.match.get("competition_id")
        self.season = self.metadata.get("season_id") or self.match.get("season_id")
        self.match_id = str(self.match.get("match_id") or self.match.get("id") or "")
        if not self.match_id:
            raise ValueError("StatsBomb fixture requires match_id")

    def _read(self, name: str) -> Any:
        with (self.fixture_root / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _freshness(self) -> dict[str, Any]:
        return {"state": "fresh", "age_seconds": 0, "ttl_seconds": None}

    def _team(self, side: str) -> Mapping[str, Any]:
        value = self.match.get(f"{side}_team")
        if not isinstance(value, Mapping):
            raise ValueError(f"StatsBomb fixture missing {side}_team")
        return value

    def _resolve(self, team: Mapping[str, Any]) -> Any:
        team_id = team.get("id") or team.get("team_id")
        team_name = team.get("name") or team.get("team_name")
        if self.resolver is None:
            return None
        return self.resolver.resolve_team(
            provider="statsbomb",
            provider_team_name=str(team_name) if team_name is not None else None,
            provider_team_id=str(team_id) if team_id is not None else None,
            country=team.get("country"),
            competition_context=self.competition,
            gender=team.get("gender"),
            team_level=team.get("team_level"),
        )

    def _team_record(self, team: Mapping[str, Any], context: str) -> dict[str, Any]:
        team_id = str(team.get("id") or team.get("team_id"))
        team_name = str(team.get("name") or team.get("team_name") or "Unknown team")
        resolved = self._resolve(team)
        canonical_id = resolved.canonical_team_id if resolved else None
        record = common_record(
            contract_version="team_identity.v1", source="statsbomb", source_entity_id=team_id,
            canonical_entity_id=canonical_id, captured_at=self.captured_at, source_as_of_at=self.source_as_of_at,
            competition=self.competition, season=self.season, home_away_context=context, sample_matches=1,
            sample_minutes=None, value=None, unit=None, quality="B" if canonical_id else "C",
            freshness=self._freshness(), missing_reason=[] if canonical_id else ["identity_unresolved"],
            provenance_record=provenance(provider="statsbomb", source="statsbomb_open_data", source_record_ref=f"match:{self.match_id}:team:{team_id}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, source_url=self.SOURCE_URL, data_license=self.DATA_LICENSE, attribution_required=True, commercial_use_review="required", parser_version=self.provider_version),
        )
        record.update({
            "canonical_name": resolved.canonical_name if resolved else team_name,
            "country": team.get("country"),
            "gender": team.get("gender") or "unknown",
            "team_level": team.get("team_level") or "unknown",
            "resolution_status": "resolved" if canonical_id else "unresolved",
            "resolution_method": resolved.resolution_method if resolved else "unresolved",
            "confidence": resolved.confidence if resolved else None,
        })
        validate_record("team_identity", record)
        return record

    def get_team_identity(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self._team_record(self._team("home"), "home"), self._team_record(self._team("away"), "away")]

    def _team_ids(self) -> list[tuple[str, Mapping[str, Any]]]:
        return [(str(self._team(side).get("id") or self._team(side).get("team_id")), self._team(side)) for side in ("home", "away")]

    def _team_canonical(self, provider_team_id: str) -> str | None:
        for side_id, team in self._team_ids():
            if side_id == provider_team_id:
                resolved = self._resolve(team)
                return resolved.canonical_team_id if resolved else None
        return None

    def get_match_history(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        home = self._team("home")
        away = self._team("away")
        home_id = str(home.get("id") or home.get("team_id"))
        away_id = str(away.get("id") or away.get("team_id"))
        record = common_record(
            contract_version="match_identity.v1", source="statsbomb", source_entity_id=self.match_id, canonical_entity_id=None,
            captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, competition=self.competition, season=self.season,
            home_away_context="neutral", sample_matches=1, sample_minutes=None, value=None, unit=None, quality="B",
            freshness=self._freshness(), missing_reason=["match_identity_unresolved"],
            provenance_record=provenance(provider="statsbomb", source="statsbomb_open_data", source_record_ref=f"match:{self.match_id}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, source_url=self.SOURCE_URL, data_license=self.DATA_LICENSE, attribution_required=True, commercial_use_review="required", parser_version=self.provider_version),
        )
        record.update({
            "provider_match_id": self.match_id,
            "canonical_match_id": None,
            "home_team_id": self._team_canonical(home_id) or f"statsbomb:{home_id}",
            "away_team_id": self._team_canonical(away_id) or f"statsbomb:{away_id}",
            "kickoff_at": self.match.get("kickoff_at"),
        })
        validate_record("match_identity", record)
        return [record]

    def _event_stats(self) -> dict[str, dict[str, float | int]]:
        stats: dict[str, dict[str, float | int]] = defaultdict(lambda: {"goals_for": 0, "shots_for": 0, "shots_on_target_for": 0, "xg_for": 0.0})
        for event in self.events:
            if not isinstance(event, Mapping):
                continue
            team = event.get("team")
            if not isinstance(team, Mapping):
                continue
            team_id = str(team.get("id") or team.get("team_id"))
            event_type = event.get("type")
            type_name = event_type.get("name") if isinstance(event_type, Mapping) else event_type
            if type_name != "Shot":
                continue
            bucket = stats[team_id]
            bucket["shots_for"] += 1
            shot = event.get("shot") if isinstance(event.get("shot"), Mapping) else {}
            outcome = shot.get("outcome") if isinstance(shot.get("outcome"), Mapping) else {}
            if outcome.get("name") == "Goal":
                bucket["goals_for"] += 1
            if shot.get("statsbomb_xg") is not None and isinstance(shot.get("statsbomb_xg"), (int, float)):
                bucket["xg_for"] += float(shot["statsbomb_xg"])
            if outcome.get("name") in {"Goal", "Saved", "Saved Off Target"}:
                bucket["shots_on_target_for"] += 1
        return dict(stats)

    def get_team_stats(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        event_stats = self._event_stats()
        output = []
        for provider_id, team in self._team_ids():
            resolved = self._resolve(team)
            metrics = event_stats.get(provider_id, {"goals_for": None, "shots_for": None, "shots_on_target_for": None})
            home_id = str(self._team("home").get("id") or self._team("home").get("team_id"))
            home_score = self.match.get("home_score")
            away_score = self.match.get("away_score")
            if isinstance(home_score, (int, float)) and isinstance(away_score, (int, float)):
                metrics = {
                    **metrics,
                    "goals_for": home_score if provider_id == home_id else away_score,
                    "goals_against": away_score if provider_id == home_id else home_score,
                }
            record = common_record(
                contract_version="team_strength_snapshot.v1", source="statsbomb", source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None, captured_at=self.captured_at, source_as_of_at=self.source_as_of_at,
                competition=self.competition, season=self.season, home_away_context="home" if provider_id == str(self._team("home").get("id") or self._team("home").get("team_id")) else "away",
                sample_matches=1, sample_minutes=None, value=None, unit="match", quality="B" if resolved else "C", freshness=self._freshness(),
                missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider="statsbomb", source="statsbomb_open_data", source_record_ref=f"match:{self.match_id}:team_stats:{provider_id}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, source_url=self.SOURCE_URL, data_license=self.DATA_LICENSE, attribution_required=True, commercial_use_review="required", parser_version=self.provider_version),
            )
            record.update({
                "team_id": resolved.canonical_team_id if resolved else f"statsbomb:{provider_id}", "competition_id": self.competition, "season_id": self.season,
                "as_of_at": self.source_as_of_at, "matches": 1, "window_type": "single_match", "window_start": str(self.match.get("kickoff_at") or self.source_as_of_at),
                "window_end": str(self.match.get("kickoff_at") or self.source_as_of_at), "minutes": None, "metrics": metrics,
                "opponent_adjustment": {"opponent_team_id": None, "opponent_strength_snapshot_ref": None, "raw_metric": None, "opponent_adjusted_metric": None, "adjustment_method": "not_calculated", "adjustment_version": "future"},
            })
            validate_record("team_strength_snapshot", record)
            output.append(record)
        return output

    def get_xg(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        event_stats = self._event_stats()
        output = []
        for provider_id, team in self._team_ids():
            if provider_id not in event_stats:
                continue
            resolved = self._resolve(team)
            xg_value = float(event_stats[provider_id]["xg_for"])
            record = common_record(
                contract_version="xg_snapshot.v1", source="statsbomb", source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None, captured_at=self.captured_at, source_as_of_at=self.source_as_of_at,
                competition=self.competition, season=self.season, home_away_context="home" if provider_id == str(self._team("home").get("id") or self._team("home").get("team_id")) else "away",
                sample_matches=1, sample_minutes=None, value=xg_value, unit="goals", quality="B" if resolved else "C", freshness=self._freshness(),
                missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider="statsbomb", source="statsbomb_open_data", source_record_ref=f"match:{self.match_id}:xg:{provider_id}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, source_url=self.SOURCE_URL, data_license=self.DATA_LICENSE, attribution_required=True, commercial_use_review="required", parser_version=self.provider_version),
            )
            record.update({
                "team_id": resolved.canonical_team_id if resolved else f"statsbomb:{provider_id}", "competition_id": self.competition, "season_id": self.season, "as_of_at": self.source_as_of_at,
                "provider": "statsbomb", "metric_definition": "shot.statsbomb_xg", "includes_penalties": None, "post_shot_or_pre_shot": "pre_shot", "model_version_if_known": None, "normalization_version": None,
            })
            validate_record("xg_snapshot", record)
            output.append(record)
        return output

    def get_lineup(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        output = []
        for row in self.lineups:
            if not isinstance(row, Mapping):
                continue
            provider_id = str(row.get("team_id") or row.get("id"))
            team = next((team for team_id, team in self._team_ids() if team_id == provider_id), {"id": provider_id, "name": row.get("team_name")})
            resolved = self._resolve(team)
            players = []
            for item in row.get("lineup", []):
                if not isinstance(item, Mapping):
                    continue
                player = item.get("player") if isinstance(item.get("player"), Mapping) else item
                positions = item.get("positions") if isinstance(item.get("positions"), list) else []
                position = None
                if positions and isinstance(positions[0], Mapping):
                    position_obj = positions[0].get("position")
                    position = position_obj.get("name") if isinstance(position_obj, Mapping) else position_obj
                starter = bool(item.get("starter", False))
                player_resolution = None
                if self.player_resolver is not None:
                    player_resolution = self.player_resolver.resolve_player(
                        "statsbomb",
                        str(player.get("name") or "") or None,
                        str(player.get("id") or player.get("player_id") or "") or None,
                        team_id=resolved.canonical_team_id if resolved else None,
                    )
                players.append({
                    "canonical_player_id": player_resolution.canonical_player_id if player_resolution else None,
                    "provider_player_id": str(player.get("id") or player.get("player_id") or ""),
                    "name": str(player.get("name") or "Unknown player"),
                    "team_id": resolved.canonical_team_id if resolved else f"statsbomb:{provider_id}",
                    "position": position,
                    "starter": starter,
                    "bench": not starter,
                    "captain": bool(item.get("captain", False)),
                    "goalkeeper": position in {"Goalkeeper", "GK"},
                    "source": "statsbomb",
                    "captured_at": self.captured_at,
                    "status": "confirmed",
                })
            record = common_record(
                contract_version="lineup_snapshot.v1", source="statsbomb", source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None, captured_at=self.captured_at, source_as_of_at=self.source_as_of_at,
                competition=self.competition, season=self.season, home_away_context="home" if provider_id == str(self._team("home").get("id") or self._team("home").get("team_id")) else "away",
                sample_matches=1, sample_minutes=None, value=None, unit=None, quality="B" if resolved else "C", freshness=self._freshness(),
                missing_reason=[] if resolved else ["identity_unresolved"],
                provenance_record=provenance(provider="statsbomb", source="statsbomb_open_data", source_record_ref=f"match:{self.match_id}:lineup:{provider_id}", captured_at=self.captured_at, source_as_of_at=self.source_as_of_at, source_url=self.SOURCE_URL, data_license=self.DATA_LICENSE, attribution_required=True, commercial_use_review="required", parser_version=self.provider_version),
            )
            record.update({"match_id": self.match_id, "team_id": resolved.canonical_team_id if resolved else f"statsbomb:{provider_id}", "status": "confirmed", "players": players})
            validate_record("lineup_snapshot", record)
            output.append(record)
        return output

    def get_availability(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        # StatsBomb Open Data has no general injury/availability feed in these
        # fixtures. Empty means unavailable, not that every player is fit.
        return []
