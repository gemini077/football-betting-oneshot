"""Offline adapter for official-shape StatsBomb Open Data JSON.

The adapter accepts the raw public JSON resource shapes directly.  It does not
use statsbombpy, credentials, network access, or a first-row fallback.  The
fixture mode is explicitly marked as synthetic and is never represented as a
real provider observation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..competition_resolution import CompetitionEntityResolver
from ..contracts import validate_record
from ..entity_resolution import TeamEntityResolver
from ..player_identity import PlayerIdentityResolver
from ..quality import finalize_record_quality
from .base import common_record, provenance


class StatsBombOpenDataProvider:
    provider_name = "statsbomb_open_data"
    provider_version = "offline-json-adapter.v2"
    SOURCE_URL = "https://github.com/hudl/open-data"
    DATA_LICENSE = "StatsBomb Open Data LICENSE.pdf / User Agreement review required"

    def __init__(
        self,
        fixture_root: str | Path | None = None,
        *,
        match_source: Any = None,
        events_source: Any = None,
        lineups_source: Any = None,
        metadata: Mapping[str, Any] | None = None,
        match_id: str | None = None,
        resolver: TeamEntityResolver | None = None,
        competition_resolver: CompetitionEntityResolver | None = None,
        player_resolver: PlayerIdentityResolver | None = None,
    ) -> None:
        self.fixture_root = Path(fixture_root) if fixture_root is not None and not isinstance(fixture_root, Mapping) else None
        self.resolver = resolver
        self.competition_resolver = competition_resolver
        self.player_resolver = player_resolver
        self.metadata = dict(metadata or self._read_optional("metadata.json") or {})

        if match_source is None:
            if self.fixture_root is None:
                raise ValueError("match_source is required")
            match_source = self._read_optional("matches.json")
            if match_source is None:
                # Legacy one-object compatibility is retained only as a source
                # loader; official list parsing remains the primary path.
                match_source = self._read_optional("match.json")
        self.match = self._select_match(self._load_source(match_source), match_id)

        if events_source is None:
            events_source = self._read_optional("events.json") if self.fixture_root else []
        if lineups_source is None:
            lineups_source = self._read_optional("lineups.json") if self.fixture_root else []
        self.events = self._as_list(self._load_source(events_source), "events")
        self.lineups = self._as_list(self._load_source(lineups_source), "lineups")

        self.synthetic = bool(self.metadata.get("synthetic", False))
        self.observation_provider = "statsbomb_fixture" if self.synthetic else "statsbomb"
        self.observation_source = "synthetic_statsbomb_schema_fixture" if self.synthetic else "statsbomb_open_data"
        self.captured_at = str(self.metadata.get("captured_at") or "")
        if not self.captured_at:
            raise ValueError("StatsBomb fixture requires captured_at metadata")
        self.source_as_of_at = self.metadata.get("source_as_of_at") or self.match.get("last_updated")
        self.match_id = str(self.match.get("match_id") or self.match.get("id") or "")
        if not self.match_id:
            raise ValueError("StatsBomb fixture requires match_id")

        competition = self.match.get("competition") if isinstance(self.match.get("competition"), Mapping) else {}
        season = self.match.get("season") if isinstance(self.match.get("season"), Mapping) else {}
        self.provider_competition_id = self._text(competition.get("competition_id"))
        self.provider_competition_name = self._text(competition.get("competition_name"))
        self.provider_season_id = self._text(season.get("season_id"))
        self.provider_season_name = self._text(season.get("season_name"))
        self.competition_resolution = (
            competition_resolver.resolve(
                provider=self.observation_provider,
                provider_competition_id=self.provider_competition_id,
                provider_competition_name=self.provider_competition_name,
                provider_season_id=self.provider_season_id,
                provider_season_name=self.provider_season_name,
            )
            if competition_resolver is not None
            else None
        )
        self.canonical_competition_id = self.competition_resolution.canonical_competition_id if self.competition_resolution else None
        self.canonical_season_id = self.competition_resolution.canonical_season_id if self.competition_resolution else None
        self.competition = self.canonical_competition_id
        self.season = self.canonical_season_id
        self.kickoff_at = self._kickoff_at()

    @staticmethod
    def _text(value: Any) -> str | None:
        return str(value) if value is not None else None

    def _read_optional(self, name: str) -> Any:
        if self.fixture_root is None:
            return None
        path = self.fixture_root / name
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _load_source(source: Any) -> Any:
        if isinstance(source, (Mapping, list)) or source is None:
            return source
        path = Path(source)
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        if isinstance(source, str):
            return json.loads(source)
        raise ValueError("unsupported StatsBomb source")

    @staticmethod
    def _as_list(value: Any, name: str) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, Mapping) and isinstance(value.get(name), list):
            value = value[name]
        if not isinstance(value, list):
            raise ValueError(f"StatsBomb {name} source must be a list")
        return value

    @staticmethod
    def _select_match(source: Any, match_id: str | None) -> Mapping[str, Any]:
        if isinstance(source, Mapping) and isinstance(source.get("matches"), list):
            rows = source["matches"]
        elif isinstance(source, Mapping):
            rows = [source]
        elif isinstance(source, list):
            rows = source
        else:
            raise ValueError("StatsBomb matches source must be a match object or list[match]")
        rows = [row for row in rows if isinstance(row, Mapping)]
        if match_id is None:
            if len(rows) != 1:
                raise ValueError("match_id_required")
            return rows[0]
        selected = [row for row in rows if str(row.get("match_id") or row.get("id") or "") == str(match_id)]
        if not selected:
            raise ValueError("match_not_found")
        if len(selected) > 1:
            raise ValueError("ambiguous_match_id")
        return selected[0]

    def _kickoff_at(self) -> str | None:
        if self.match.get("kickoff_at"):
            return str(self.match["kickoff_at"])
        date = self.match.get("match_date")
        kick_off = self.match.get("kick_off")
        if date and kick_off:
            return f"{date}T{kick_off}Z"
        return None

    def _team(self, side: str) -> Mapping[str, Any]:
        value = self.match.get(f"{side}_team")
        if not isinstance(value, Mapping):
            raise ValueError(f"StatsBomb fixture missing {side}_team")
        # Official Open Data fields take precedence over legacy synthetic keys.
        id_key = f"{side}_team_id"
        name_key = f"{side}_team_name"
        country = value.get("country")
        return {
            "provider_team_id": self._text(value.get(id_key) if value.get(id_key) is not None else value.get("id") or value.get("team_id")),
            "provider_team_name": self._text(value.get(name_key) if value.get(name_key) is not None else value.get("name") or value.get("team_name")),
            "country": country.get("name") if isinstance(country, Mapping) else country,
            "gender": value.get(f"{side}_team_gender") if value.get(f"{side}_team_gender") is not None else value.get("gender"),
            "team_level": value.get("team_level"),
        }

    def _team_ids(self) -> list[tuple[str, Mapping[str, Any]]]:
        return [(str(self._team(side).get("provider_team_id")), self._team(side)) for side in ("home", "away")]

    def _resolve(self, team: Mapping[str, Any]) -> Any:
        if self.resolver is None:
            return None
        context = self.canonical_competition_id if self.canonical_competition_id and self.canonical_competition_id.startswith("competition:") else None
        return self.resolver.resolve_team(
            provider=self.observation_provider,
            provider_team_name=team.get("provider_team_name"),
            provider_team_id=team.get("provider_team_id"),
            country=team.get("country"),
            competition_context=context,
            gender=team.get("gender"),
            team_level=team.get("team_level"),
        )

    def _provenance(self, reference: str) -> dict[str, Any]:
        source_url = None if self.synthetic else self.metadata.get("source_url") or self.SOURCE_URL
        return provenance(
            provider=self.observation_provider,
            source=self.observation_source,
            source_reliable=not self.synthetic,
            source_record_ref=reference,
            captured_at=self.captured_at,
            source_as_of_at=self.source_as_of_at,
            source_url=source_url,
            data_license=self.metadata.get("data_license") or self.DATA_LICENSE,
            attribution_required=bool(self.metadata.get("attribution_required", not self.synthetic)),
            commercial_use_review=str(self.metadata.get("commercial_use_review") or "required"),
            parser_version=self.provider_version,
            synthetic=self.synthetic,
            observation_origin=str(self.metadata.get("observation_origin") or ("synthetic_schema_fixture" if self.synthetic else "provider_open_data")),
            provider_schema=str(self.metadata.get("provider_schema") or "statsbomb"),
            provider_schema_reference=str(self.metadata.get("provider_schema_reference") or self.SOURCE_URL),
        )

    def _record(self, *, kind: str, data_class: str, source_entity_id: str | None, canonical_entity_id: str | None, context: str, value: Any, unit: str | None, missing_reason: list[str], reference: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        record = common_record(
            contract_version=f"{kind}.v1",
            source=self.observation_source,
            source_entity_id=source_entity_id,
            canonical_entity_id=canonical_entity_id,
            captured_at=self.captured_at,
            source_as_of_at=self.source_as_of_at,
            competition=self.canonical_competition_id,
            season=self.canonical_season_id,
            home_away_context=context,
            sample_matches=1,
            sample_minutes=None,
            value=value,
            unit=unit,
            quality="C",
            freshness={"state": "unknown", "age_seconds": None, "ttl_seconds": None},
            missing_reason=missing_reason,
            provenance_record=self._provenance(reference),
            provider_competition_id=self.provider_competition_id,
            provider_competition_name=self.provider_competition_name,
            provider_season_id=self.provider_season_id,
            provider_season_name=self.provider_season_name,
            canonical_competition_id=self.canonical_competition_id,
            canonical_season_id=self.canonical_season_id,
        )
        if extra:
            record.update(extra)
        finalize_record_quality(record, data_class=data_class, record_type=kind)
        validate_record(kind, record)
        return record

    def _team_record(self, team: Mapping[str, Any], context: str) -> dict[str, Any]:
        team_id = str(team.get("provider_team_id"))
        team_name = str(team.get("provider_team_name") or "Unknown team")
        resolved = self._resolve(team)
        canonical_id = resolved.canonical_team_id if resolved else None
        return self._record(
            kind="team_identity",
            data_class="slow_changing",
            source_entity_id=team_id,
            canonical_entity_id=canonical_id,
            context=context,
            value=None,
            unit=None,
            missing_reason=[] if canonical_id else ["identity_unresolved"],
            reference=f"match:{self.match_id}:team:{team_id}",
            extra={
                "canonical_name": resolved.canonical_name if resolved else team_name,
                "country": team.get("country"),
                "gender": team.get("gender") or "unknown",
                "team_level": team.get("team_level") or "unknown",
                "resolution_status": "resolved" if canonical_id else "unresolved",
                "resolution_method": resolved.resolution_method if resolved else "unresolved",
                "confidence": resolved.confidence if resolved else None,
            },
        )

    def get_team_identity(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self._team_record(self._team("home"), "home"), self._team_record(self._team("away"), "away")]

    def _team_canonical(self, provider_team_id: str) -> str | None:
        for side_id, team in self._team_ids():
            if side_id == provider_team_id:
                resolved = self._resolve(team)
                return resolved.canonical_team_id if resolved else None
        return None

    def get_match_history(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        home_id = str(self._team("home").get("provider_team_id"))
        away_id = str(self._team("away").get("provider_team_id"))
        return [self._record(
            kind="match_identity",
            data_class="historical_immutable",
            source_entity_id=self.match_id,
            canonical_entity_id=None,
            context="neutral",
            value=None,
            unit=None,
            missing_reason=["match_identity_unresolved"],
            reference=f"match:{self.match_id}",
            extra={
                "provider_match_id": self.match_id,
                "canonical_match_id": None,
                "home_team_id": self._team_canonical(home_id) or f"{self.observation_provider}:{home_id}",
                "away_team_id": self._team_canonical(away_id) or f"{self.observation_provider}:{away_id}",
                "kickoff_at": self.kickoff_at,
            },
        )]

    def _event_stats(self) -> dict[str, dict[str, float | int | None]]:
        stats: dict[str, dict[str, float | int | None]] = defaultdict(lambda: {"goals_for": 0, "shots_for": 0, "shots_on_target_for": 0, "xg_for": 0.0})
        for event in self.events:
            if not isinstance(event, Mapping):
                continue
            team = event.get("team")
            if not isinstance(team, Mapping):
                continue
            team_id = str(team.get("id") or team.get("team_id") or "")
            event_type = event.get("type")
            type_name = event_type.get("name") if isinstance(event_type, Mapping) else event_type
            if type_name != "Shot":
                continue
            bucket = stats[team_id]
            bucket["shots_for"] = int(bucket.get("shots_for") or 0) + 1
            shot = event.get("shot") if isinstance(event.get("shot"), Mapping) else {}
            outcome = shot.get("outcome") if isinstance(shot.get("outcome"), Mapping) else {}
            if outcome.get("name") == "Goal":
                bucket["goals_for"] = int(bucket.get("goals_for") or 0) + 1
            xg = shot.get("statsbomb_xg")
            if isinstance(xg, (int, float)) and not isinstance(xg, bool):
                bucket["xg_for"] = float(bucket.get("xg_for") or 0.0) + float(xg)
            if outcome.get("name") in {"Goal", "Saved", "Saved Off Target"}:
                bucket["shots_on_target_for"] = int(bucket.get("shots_on_target_for") or 0) + 1
        return dict(stats)

    def get_team_stats(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        event_stats = self._event_stats()
        home_id = str(self._team("home").get("provider_team_id"))
        home_score = self.match.get("home_score")
        away_score = self.match.get("away_score")
        output = []
        for provider_id, team in self._team_ids():
            resolved = self._resolve(team)
            metrics = dict(event_stats.get(provider_id, {"goals_for": None, "shots_for": None, "shots_on_target_for": None, "xg_for": None}))
            if isinstance(home_score, (int, float)) and isinstance(away_score, (int, float)):
                metrics.update({
                    "goals_for": home_score if provider_id == home_id else away_score,
                    "goals_against": away_score if provider_id == home_id else home_score,
                })
            output.append(self._record(
                kind="team_strength_snapshot",
                data_class="historical_immutable",
                source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None,
                context="home" if provider_id == home_id else "away",
                value=None,
                unit="match",
                missing_reason=[] if resolved else ["identity_unresolved"],
                reference=f"match:{self.match_id}:team_stats:{provider_id}",
                extra={
                    "team_id": resolved.canonical_team_id if resolved else f"{self.observation_provider}:{provider_id}",
                    "competition_id": self.canonical_competition_id,
                    "season_id": self.canonical_season_id,
                    "as_of_at": self.source_as_of_at,
                    "matches": 1,
                    "window_type": "single_match",
                    "window_start": self.kickoff_at or self.source_as_of_at or "unknown",
                    "window_end": self.kickoff_at or self.source_as_of_at or "unknown",
                    "minutes": None,
                    "metrics": metrics,
                    "opponent_adjustment": {"opponent_team_id": None, "opponent_strength_snapshot_ref": None, "raw_metric": None, "opponent_adjusted_metric": None, "adjustment_method": "not_calculated", "adjustment_version": "future"},
                },
            ))
        return output

    def get_xg(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        event_stats = self._event_stats()
        output = []
        for provider_id, team in self._team_ids():
            if provider_id not in event_stats:
                continue
            resolved = self._resolve(team)
            output.append(self._record(
                kind="xg_snapshot",
                data_class="historical_immutable",
                source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None,
                context="home" if provider_id == str(self._team("home").get("provider_team_id")) else "away",
                value=float(event_stats[provider_id].get("xg_for") or 0.0),
                unit="goals",
                missing_reason=[] if resolved else ["identity_unresolved"],
                reference=f"match:{self.match_id}:xg:{provider_id}",
                extra={
                    "team_id": resolved.canonical_team_id if resolved else f"{self.observation_provider}:{provider_id}",
                    "competition_id": self.canonical_competition_id,
                    "season_id": self.canonical_season_id,
                    "as_of_at": self.source_as_of_at,
                    "provider": self.observation_provider,
                    "metric_definition": "shot.statsbomb_xg",
                    "includes_penalties": None,
                    "post_shot_or_pre_shot": "pre_shot",
                    "model_version_if_known": None,
                    "normalization_version": None,
                },
            ))
        return output

    @staticmethod
    def _position_name(position: Mapping[str, Any]) -> str | None:
        value = position.get("position")
        if isinstance(value, Mapping):
            return str(value.get("name")) if value.get("name") is not None else None
        return str(value) if value is not None else None

    @staticmethod
    def _is_substitution_on(reason: str) -> bool:
        normalized = " ".join(str(reason).strip().casefold().split())
        return (
            normalized == "substitution on"
            or normalized.startswith("substitution - on")
            or normalized.startswith("substitute - on")
        )

    @classmethod
    def _lineup_state(cls, positions: list[Any]) -> tuple[bool | None, bool | None, str | None]:
        names: list[str] = []
        reasons: list[str] = []
        for value in positions:
            if not isinstance(value, Mapping):
                continue
            position_name = cls._position_name(value)
            if position_name:
                names.append(position_name)
            if value.get("start_reason") is not None:
                reasons.append(str(value["start_reason"]).strip().casefold())
        if "starting xi" in reasons:
            return True, False, names[0] if names else None
        if any(cls._is_substitution_on(reason) for reason in reasons):
            return False, True, names[0] if names else None
        return None, None, names[0] if names else None

    @staticmethod
    def _goalkeeper(positions: list[Any]) -> bool | None:
        names = []
        for value in positions:
            if isinstance(value, Mapping):
                name = StatsBombOpenDataProvider._position_name(value)
                if name:
                    names.append(name.casefold())
        if any("goalkeeper" in name or "goal keeper" in name for name in names):
            return True
        return None

    def get_lineup(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        output = []
        for row in self.lineups:
            if not isinstance(row, Mapping):
                continue
            provider_id = str(row.get("team_id") or row.get("id") or "")
            team = next((team for team_id, team in self._team_ids() if team_id == provider_id), {"provider_team_id": provider_id, "provider_team_name": row.get("team_name")})
            resolved = self._resolve(team)
            players = []
            resolved_players = 0
            raw_players = row.get("lineup") if isinstance(row.get("lineup"), list) else []
            for item in raw_players:
                if not isinstance(item, Mapping):
                    continue
                player_id = str(item.get("player_id") or item.get("id") or "")
                player_name = str(item.get("player_name") or item.get("name") or "Unknown player")
                positions = item.get("positions") if isinstance(item.get("positions"), list) else []
                starter, bench, position = self._lineup_state(positions)
                player_resolution = self.player_resolver.resolve_player(
                    self.observation_provider,
                    player_name,
                    player_id or None,
                    team_id=resolved.canonical_team_id if resolved else None,
                ) if self.player_resolver is not None else None
                if player_resolution and player_resolution.canonical_player_id:
                    resolved_players += 1
                captain = item.get("captain") if isinstance(item.get("captain"), bool) else None
                goalkeeper = item.get("goalkeeper") if isinstance(item.get("goalkeeper"), bool) else self._goalkeeper(positions)
                players.append({
                    "canonical_player_id": player_resolution.canonical_player_id if player_resolution else None,
                    "provider_player_id": player_id,
                    "name": player_name,
                    "team_id": resolved.canonical_team_id if resolved else f"{self.observation_provider}:{provider_id}",
                    "position": position,
                    "starter": starter,
                    "bench": bench,
                    "captain": captain,
                    "goalkeeper": goalkeeper,
                    "source": self.observation_source,
                    "captured_at": self.captured_at,
                    "status": self.metadata.get("lineup_status") or "confirmed",
                })
            total_players = len(players)
            coverage_ratio = round(resolved_players / total_players, 6) if total_players else 0.0
            missing = [] if resolved else ["identity_unresolved"]
            if coverage_ratio < 1:
                missing.append("player_identity_incomplete")
            output.append(self._record(
                kind="lineup_snapshot",
                data_class="fast_changing",
                source_entity_id=provider_id,
                canonical_entity_id=resolved.canonical_team_id if resolved else None,
                context="home" if provider_id == str(self._team("home").get("provider_team_id")) else "away",
                value=None,
                unit=None,
                missing_reason=missing,
                reference=f"match:{self.match_id}:lineup:{provider_id}",
                extra={
                    "match_id": self.match_id,
                    "team_id": resolved.canonical_team_id if resolved else f"{self.observation_provider}:{provider_id}",
                    "status": self.metadata.get("lineup_status") or "confirmed",
                    "players": players,
                    "player_identity_coverage": {"resolved_players": resolved_players, "total_players": total_players, "coverage_ratio": coverage_ratio},
                },
            ))
        return output

    def get_availability(self, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        # StatsBomb Open Data does not provide an official availability feed in
        # this adapter boundary; absence is not converted into player_out.
        return []
