"""Offline adapter for football-data.co.uk historical result CSV captures.

Only date, teams, competition/season and full-time goals are normalized. Odds
and other columns remain outside the result contract and are never interpreted.
The adapter does not fetch the network and requires explicit reviewed team
identity evidence supplied by the caller.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from typing import Any, Callable, Mapping

from ..entity_resolution import REVIEWED_MAPPING_METHODS
from ..historical_results import make_historical_match_result


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold(), flags=re.ASCII)
    return normalized.strip("-") or "unresolved"


class FootballDataCoUkHistoricalAdapter:
    """Normalize one captured football-data.co.uk results CSV."""

    provider_name = "football-data.co.uk"
    provider_version = "football-data-co-uk-csv-adapter.v1"

    def __init__(
        self,
        *,
        competition_id: str | None,
        season_id: str | None,
        provider_competition_id: str,
        provider_competition_name: str,
        provider_season_id: str,
        provider_season_name: str,
        source_url: str,
        source_file: str,
        captured_at: str,
        raw_sha256: str | None = None,
        country: str = "Sweden",
        entity_type: str = "club",
        match_type: str = "league",
        team_identity_resolver: Mapping[str, Mapping[str, Any]] | Callable[[str], Mapping[str, Any] | None] | Any | None = None,
    ) -> None:
        self.competition_id = competition_id
        self.season_id = season_id
        self.provider_competition_id = provider_competition_id
        self.provider_competition_name = provider_competition_name
        self.provider_season_id = provider_season_id
        self.provider_season_name = provider_season_name
        self.source_url = source_url
        self.source_file = source_file
        self.captured_at = captured_at
        self.raw_sha256 = raw_sha256
        self.country = country
        self.entity_type = entity_type
        self.match_type = match_type
        self.team_identity_resolver = team_identity_resolver

    def _resolve_team(self, raw_name: str) -> Mapping[str, Any] | None:
        resolver = self.team_identity_resolver
        value: Mapping[str, Any] | None
        if resolver is None:
            value = None
        elif isinstance(resolver, Mapping):
            candidate = resolver.get(raw_name)
            value = candidate if isinstance(candidate, Mapping) else None
        elif callable(resolver):
            candidate = resolver(raw_name)
            value = candidate if isinstance(candidate, Mapping) else None
        elif hasattr(resolver, "resolve_team"):
            candidate = resolver.resolve_team(
                self.provider_name,
                raw_name,
                None,
                country=self.country,
                competition_context=self.competition_id,
            )
            value = candidate.to_dict() if hasattr(candidate, "to_dict") else candidate
            if not isinstance(value, Mapping):
                value = None
        else:
            value = None
        if not isinstance(value, Mapping):
            return None
        if value.get("verified") is not True or value.get("resolution_method") not in REVIEWED_MAPPING_METHODS:
            return None
        canonical_id = value.get("canonical_team_id")
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            return None
        return value

    def _record(
        self,
        *,
        line_number: int,
        raw_home: str,
        raw_away: str,
        kickoff_at: str,
        kickoff_precision: str,
        home_goals: int,
        away_goals: int,
        raw_sha256: str,
    ) -> dict[str, Any]:
        home_resolution = self._resolve_team(raw_home)
        away_resolution = self._resolve_team(raw_away)
        home_id = str(home_resolution["canonical_team_id"]) if home_resolution else None
        away_id = str(away_resolution["canonical_team_id"]) if away_resolution else None
        resolved = bool(self.competition_id and self.season_id and home_id and away_id)
        canonical_match_id = (
            f"match:{self.competition_id}:{kickoff_at[:10]}:{home_id}:{away_id}" if resolved else None
        )
        evidence: list[Any] = []
        for raw_name, resolution in ((raw_home, home_resolution), (raw_away, away_resolution)):
            if resolution:
                evidence.extend(resolution.get("verification_evidence") or [])
            else:
                evidence.append({"raw_team_name": raw_name, "reason": "no reviewed canonical mapping"})
        methods = {item.get("resolution_method") for item in (home_resolution, away_resolution) if item}
        resolution_method = "manual_verified" if resolved and "manual_verified" in methods else next(iter(methods), "unresolved")
        provider_match_id = f"{self.source_file}:{self.provider_season_id}:{kickoff_at[:10]}:{_slug(raw_home)}:{_slug(raw_away)}"
        source_record_ref = f"{self.source_url}#line={line_number}"
        record = make_historical_match_result(
            canonical_match_id=canonical_match_id,
            competition_id=self.competition_id,
            season_id=self.season_id,
            home_team_id=home_id,
            away_team_id=away_id,
            kickoff_at=kickoff_at,
            home_goals=home_goals,
            away_goals=away_goals,
            provider=self.provider_name,
            provider_match_id=provider_match_id,
            source_as_of_at=kickoff_at,
            captured_at=self.captured_at,
            source_record_ref=source_record_ref,
            source=self.provider_name,
            source_url=self.source_url,
            source_reliable=True,
            raw_home_team=raw_home,
            raw_away_team=raw_away,
            raw_competition=self.provider_competition_name,
            raw_season=self.provider_season_name,
            resolution_status="resolved" if resolved else "unresolved",
            resolution_method=resolution_method if resolved else "unresolved",
            observation_origin="provider_historical_result",
            data_license="football-data.co.uk terms review required",
            attribution_required=True,
            commercial_use_review="required",
            parser_version=self.provider_version,
            raw_sha256=raw_sha256,
            source_file=self.source_file,
            raw_redistribution=False,
            internal_analysis_only=True,
            entity_type=self.entity_type,
            match_type=self.match_type,
            verification_evidence=evidence,
        )
        record.update(
            {
                "provider_competition_id": self.provider_competition_id,
                "provider_competition_name": self.provider_competition_name,
                "provider_season_id": self.provider_season_id,
                "provider_season_name": self.provider_season_name,
                "kickoff_precision": kickoff_precision,
            }
        )
        return record

    def parse_csv_text(self, raw_text: str, *, season_filter: str | None = None, raw_sha256: str | None = None) -> list[dict[str, Any]]:
        """Parse captured CSV text without making a network request."""

        if not isinstance(raw_text, str):
            raise TypeError("football-data.co.uk input must be text")
        digest = raw_sha256 or self.raw_sha256 or hashlib.sha256(raw_text.encode("utf-8-sig")).hexdigest()
        reader = csv.DictReader(io.StringIO(raw_text.lstrip("\ufeff")))
        records: list[dict[str, Any]] = []
        for line_number, row in enumerate(reader, start=2):
            season = str(row.get("Season") or "").strip()
            if season_filter is not None and season != str(season_filter):
                continue
            date_text = str(row.get("Date") or "").strip()
            home = str(row.get("Home") or "").strip()
            away = str(row.get("Away") or "").strip()
            if not date_text or not home or not away:
                continue
            try:
                match_date = datetime.strptime(date_text, "%d/%m/%Y").date()
                home_goals = int(str(row.get("HG") or "").strip())
                away_goals = int(str(row.get("AG") or "").strip())
            except (TypeError, ValueError):
                continue
            time_text = str(row.get("Time") or "").strip()
            if time_text:
                try:
                    kickoff_at = f"{match_date.isoformat()}T{datetime.strptime(time_text, '%H:%M').strftime('%H:%M')}:00Z"
                except ValueError:
                    kickoff_at = f"{match_date.isoformat()}T00:00:00Z"
                    kickoff_precision = "date"
                else:
                    kickoff_precision = "minute"
            else:
                kickoff_at = f"{match_date.isoformat()}T00:00:00Z"
                kickoff_precision = "date"
            records.append(
                self._record(
                    line_number=line_number,
                    raw_home=home,
                    raw_away=away,
                    kickoff_at=kickoff_at,
                    kickoff_precision=kickoff_precision,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    raw_sha256=digest,
                )
            )
        return records


__all__ = ["FootballDataCoUkHistoricalAdapter"]
