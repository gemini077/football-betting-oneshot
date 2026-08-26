"""Offline adapter for the native OpenFootball Football.TXT result format.

The adapter consumes already captured text.  It does not fetch the network and
it never promotes a team name to a canonical identity without reviewed mapping
evidence supplied by the caller.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..entity_resolution import REVIEWED_MAPPING_METHODS
from ..historical_results import make_historical_match_result


_DATE_RE = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?(?P<metadata>\s+.*)?\s*$"
)
_SEASON_HEADER_RE = re.compile(r"(?<!\d)(?P<start>\d{4})\s*/\s*(?P<end>\d{2,4})(?!\d)")
_MATCH_RE = re.compile(
    r"^\s*(?:(?P<time>\d{1,2}:\d{2})\s+)?(?P<home>.+?)\s+v\s+(?P<away>.+?)\s+(?P<home_goals>\d+)-(?P<away_goals>\d+)(?:\s|$)"
)
_MONTHS = {name: number for number, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def _timezone_from_metadata(metadata: str | None) -> timezone:
    match = re.search(r"\bUTC(?P<sign>[+-])(?P<hours>\d{1,2})(?::?(?P<minutes>\d{2}))?\b", metadata or "", re.IGNORECASE)
    if not match:
        return timezone.utc
    delta = timedelta(hours=int(match.group("hours")), minutes=int(match.group("minutes") or 0))
    if match.group("sign") == "-":
        delta = -delta
    return timezone(delta)


def _slug(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", "-", value, flags=re.ASCII)
    return value.strip("-") or "unresolved"


class OpenFootballHistoricalAdapter:
    """Normalize one captured OpenFootball competition file.

    OpenFootball has both generated JSON datasets and native Football.TXT
    source repositories.  This adapter deliberately names the accepted native
    format and can be extended with another parser without changing the ledger
    or Team Strength builder.
    """

    provider_name = "openfootball"
    provider_version = "openfootball-foottxt-adapter.v1"

    def __init__(
        self,
        *,
        competition_id: str | None,
        season_id: str | None,
        provider_competition_id: str,
        provider_competition_name: str,
        provider_season_id: str,
        provider_season_name: str,
        repository: str,
        commit_sha: str,
        source_file: str,
        captured_at: str,
        source_as_of_at: str | None = None,
        country: str | None = None,
        entity_type: str = "club",
        match_type: str = "league",
        team_identity_resolver: Mapping[str, Mapping[str, Any]] | Callable[[str], Mapping[str, Any] | None] | Any | None = None,
        synthetic: bool = False,
    ) -> None:
        self.competition_id = competition_id
        self.season_id = season_id
        self.provider_competition_id = provider_competition_id
        self.provider_competition_name = provider_competition_name
        self.provider_season_id = provider_season_id
        self.provider_season_name = provider_season_name
        self.repository = repository
        self.commit_sha = commit_sha
        self.source_file = source_file
        self.captured_at = captured_at
        self.source_as_of_at = source_as_of_at or captured_at
        self.country = country
        self.entity_type = entity_type
        self.match_type = match_type
        self.team_identity_resolver = team_identity_resolver
        self.synthetic = synthetic

    @property
    def source_name(self) -> str:
        return "synthetic_openfootball_fixture" if self.synthetic else "openfootball"

    @property
    def observation_origin(self) -> str:
        return "synthetic_schema_fixture" if self.synthetic else "provider_open_data"

    def _resolve_team(self, raw_name: str) -> Mapping[str, Any] | None:
        resolver = self.team_identity_resolver
        if resolver is None:
            return None
        if isinstance(resolver, Mapping):
            value = resolver.get(raw_name)
        elif callable(resolver):
            value = resolver(raw_name)
        elif hasattr(resolver, "resolve_team"):
            result = resolver.resolve_team(
                self.provider_name,
                raw_name,
                None,
                country=self.country,
                competition_context=self.competition_id,
            )
            value = result.to_dict() if hasattr(result, "to_dict") else result
            if isinstance(value, Mapping):
                value = {
                    **value,
                    "verified": value.get("resolution_status") == "resolved"
                    and value.get("resolution_method") in REVIEWED_MAPPING_METHODS,
                }
        else:
            value = None
        if not isinstance(value, Mapping):
            return None
        method = value.get("resolution_method")
        if value.get("verified") is not True or method not in REVIEWED_MAPPING_METHODS:
            return None
        canonical_id = value.get("canonical_team_id")
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            return None
        return value

    def _canonical_match_id(self, kickoff_at: str, home_id: str | None, away_id: str | None) -> str | None:
        if not self.competition_id or not self.season_id or not home_id or not away_id:
            return None
        return f"match:{self.competition_id}:{kickoff_at[:10]}:{home_id}:{away_id}"

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
        canonical_match_id = self._canonical_match_id(kickoff_at, home_id, away_id)
        resolved = canonical_match_id is not None
        evidence: list[Any] = []
        for raw_name, resolution in ((raw_home, home_resolution), (raw_away, away_resolution)):
            if resolution:
                evidence.extend(resolution.get("verification_evidence") or [])
            else:
                evidence.append({"raw_team_name": raw_name, "reason": "no reviewed canonical mapping"})
        methods = {resolution.get("resolution_method") for resolution in (home_resolution, away_resolution) if resolution}
        resolution_method = "manual_verified" if resolved and "manual_verified" in methods else (next(iter(methods)) if resolved and methods else "unresolved")
        provider_match_id = f"{self.source_file}:{kickoff_at[:10]}:{_slug(raw_home)}:{_slug(raw_away)}"
        source_record_ref = f"{self.repository}@{self.commit_sha}:{self.source_file}:line:{line_number}"
        source_url = f"https://github.com/{self.repository}/blob/{self.commit_sha}/{self.source_file}" if self.commit_sha else None
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
            source_as_of_at=self.source_as_of_at,
            captured_at=self.captured_at,
            source_record_ref=source_record_ref,
            source=self.source_name,
            source_url=source_url,
            source_reliable=not self.synthetic,
            raw_home_team=raw_home,
            raw_away_team=raw_away,
            raw_competition=self.provider_competition_name,
            raw_season=self.provider_season_name,
            resolution_status="resolved" if resolved else "unresolved",
            resolution_method=resolution_method,
            synthetic=self.synthetic,
            observation_origin=self.observation_origin,
            data_license="CC0-1.0",
            attribution_required=False,
            commercial_use_review="reviewed_cc0",
            parser_version=self.provider_version,
            raw_sha256=raw_sha256,
            repository=self.repository,
            commit_sha=self.commit_sha,
            source_file=self.source_file,
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

    @staticmethod
    def _date_from_match(match: re.Match[str], current_year: int | None) -> date | None:
        year = int(match.group("year")) if match.group("year") else current_year
        month = _MONTHS.get(match.group("month"))
        day = int(match.group("day"))
        if year is None or month is None:
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def parse_text(self, raw_text: str, *, raw_sha256: str | None = None) -> list[dict[str, Any]]:
        """Parse official Football.TXT match lines from one captured file."""

        if not isinstance(raw_text, str):
            raise TypeError("raw_text must be a string")
        raw_sha256 = raw_sha256 or hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        records: list[dict[str, Any]] = []
        for row in parse_football_txt_rows(raw_text):
            records.append(
                self._record(
                    line_number=int(row["line_number"]),
                    raw_home=str(row["home"]),
                    raw_away=str(row["away"]),
                    kickoff_at=str(row["kickoff_at"]),
                    kickoff_precision=str(row["kickoff_precision"]),
                    home_goals=int(row["home_goals"]),
                    away_goals=int(row["away_goals"]),
                    raw_sha256=raw_sha256,
                )
            )
        return records


def parse_football_txt_rows(raw_text: str) -> list[dict[str, Any]]:
    """Parse Football.TXT result rows without applying entity resolution.

    This is the raw-evidence boundary used by the P0/P1 candidate builder.
    It intentionally returns names as observed; it never creates canonical IDs.
    """

    if not isinstance(raw_text, str):
        raise TypeError("OpenFootball Football.TXT input must be text")
    current_date: date | None = None
    current_year: int | None = None
    current_timezone: timezone = timezone.utc
    current_date_time: time | None = None
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_text.replace("\r\n", "\n").splitlines(), start=1):
        # Native season headers seed the first year for files whose date rows
        # intentionally omit the year.  This is generic for every competition.
        if line.lstrip().startswith("="):
            season_header = _SEASON_HEADER_RE.search(line)
            if season_header:
                current_year = int(season_header.group("start"))
            continue
        date_match = _DATE_RE.match(line)
        if date_match:
            explicit_year = date_match.group("year")
            month = _MONTHS.get(date_match.group("month"))
            day = int(date_match.group("day"))
            inferred_year = int(explicit_year) if explicit_year else current_year
            # A season file normally lists matches chronologically.  When a
            # date without a year rolls from December to January, advance the
            # seeded season year rather than assigning January to the header
            # year.
            if (
                not explicit_year
                and current_date is not None
                and inferred_year is not None
                and month is not None
                and (month, day) < (current_date.month, current_date.day)
            ):
                inferred_year += 1
            if inferred_year is not None and month is not None:
                try:
                    current_date = date(inferred_year, month, day)
                    current_year = inferred_year
                    metadata = date_match.group("metadata") or ""
                    current_timezone = _timezone_from_metadata(metadata)
                    time_match = re.search(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\b", metadata)
                    current_date_time = time(int(time_match.group("hour")), int(time_match.group("minute"))) if time_match else None
                except ValueError:
                    current_date = None
            continue
        match = _MATCH_RE.match(line)
        if not match or current_date is None:
            continue
        time_text = match.group("time")
        effective_time = time.fromisoformat(time_text) if time_text else current_date_time
        kickoff_at = f"{current_date.isoformat()}T00:00:00Z"
        if effective_time:
            # The full Football.TXT files may put a local offset/time on the
            # date row (for example ``19:00 UTC+2 @ stadium``).  Preserve the
            # fact time in UTC; files without it retain the date boundary.
            local_time = datetime.combine(current_date, effective_time, tzinfo=current_timezone)
            kickoff_at = local_time.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rows.append(
            {
                "line_number": line_number,
                "home": match.group("home").strip(),
                "away": match.group("away").strip(),
                "kickoff_at": kickoff_at,
                "kickoff_precision": "minute" if effective_time else "date",
                "home_goals": int(match.group("home_goals")),
                "away_goals": int(match.group("away_goals")),
            }
        )
    return rows


__all__ = ["OpenFootballHistoricalAdapter", "parse_football_txt_rows"]
