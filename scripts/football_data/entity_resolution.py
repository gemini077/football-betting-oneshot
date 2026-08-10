"""Conservative provider-to-canonical football entity resolution.

The resolver prefers an explicit provider ID and context. It never confirms a
team from a dangerous generic token or from string similarity alone.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_TEAM_REGISTRY = Path(__file__).resolve().parents[2] / "data" / "football_data" / "team_alias_registry.json"
DANGEROUS_GENERIC_NAMES = frozenset({"united", "city", "racing", "sporting", "national", "central"})


@dataclass(frozen=True)
class ResolutionResult:
    canonical_team_id: str | None
    canonical_name: str | None
    provider: str
    provider_team_id: str | None
    provider_team_name: str | None
    resolution_status: str
    resolution_method: str
    confidence: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_team_id": self.canonical_team_id,
            "canonical_name": self.canonical_name,
            "provider": self.provider,
            "provider_team_id": self.provider_team_id,
            "provider_team_name": self.provider_team_name,
            "resolution_status": self.resolution_status,
            "resolution_method": self.resolution_method,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class TeamEntityResolver:
    """Resolve provider team observations against a reviewed alias registry."""

    def __init__(self, registry_path: str | Path = DEFAULT_TEAM_REGISTRY) -> None:
        self.registry_path = Path(registry_path)
        with self.registry_path.open("r", encoding="utf-8") as handle:
            self.registry = json.load(handle)
        self.teams = list(self.registry.get("teams", []))
        self.crosswalk = list(self.registry.get("crosswalk", []))

    @staticmethod
    def normalize_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value or "").casefold().strip()
        normalized = normalized.replace("&", " and ")
        return re.sub(r"[^\w\u3400-\u9fff]+", "", normalized, flags=re.UNICODE)

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", (value or "").casefold()))

    @classmethod
    def _has_dangerous_generic_name(cls, value: str) -> bool:
        normalized = cls.normalize_name(value)
        # A full reviewed name such as "Manchester City" is safe to compare;
        # the gate is for an unqualified generic token such as "City".
        return normalized in DANGEROUS_GENERIC_NAMES

    @classmethod
    def _markers(cls, value: str) -> set[str]:
        lower = (value or "").casefold()
        markers: set[str] = set()
        if re.search(r"\b(u19|u21|u23|under\s*\d+)\b|youth|academy|青年", lower):
            markers.add("youth")
        if re.search(r"\b(reserve|reserves|ii|b)\b|二队|预备", lower):
            markers.add("reserve")
        if re.search(r"women|woman|femen|femeni|female|女足", lower):
            markers.add("female")
        return markers

    @classmethod
    def _compatible(cls, team: Mapping[str, Any], query: Mapping[str, Any]) -> bool:
        country = query.get("country")
        if country and team.get("country") and country.casefold() != str(team["country"]).casefold():
            return False
        competition = query.get("competition_context")
        team_competitions = set(team.get("competition_context", []))
        if competition and team_competitions and competition not in team_competitions:
            return False
        gender = query.get("gender")
        if gender and team.get("gender") not in {None, "unknown", gender}:
            return False
        team_level = query.get("team_level")
        if team_level and team.get("team_level") not in {None, "unknown", team_level}:
            return False

        markers = cls._markers(str(query.get("provider_team_name") or ""))
        candidate_markers = set()
        if team.get("gender") == "female":
            candidate_markers.add("female")
        if team.get("team_level") == "reserve":
            candidate_markers.add("reserve")
        if team.get("team_level") == "youth":
            candidate_markers.add("youth")
        if markers and not markers.issubset(candidate_markers):
            return False
        if candidate_markers and not candidate_markers.issubset(markers):
            return False
        return True

    @staticmethod
    def _mapping_matches(mapping: Mapping[str, Any], provider: str, provider_team_id: str | None) -> bool:
        return mapping.get("provider") == provider and provider_team_id is not None and mapping.get("provider_team_id") == provider_team_id

    def _candidate_rows(self, query: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], Mapping[str, Any] | None]]:
        provider = query["provider"]
        provider_team_id = query.get("provider_team_id")
        rows: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = []
        for team in self.teams:
            for mapping in team.get("provider_mappings", []):
                if self._mapping_matches(mapping, provider, provider_team_id) or mapping.get("provider") == provider:
                    if self._compatible(team, query):
                        rows.append((team, mapping))
                        break
            if not team.get("provider_mappings") and self._compatible(team, query):
                rows.append((team, None))
        return rows

    def _result(
        self,
        query: Mapping[str, Any],
        team: Mapping[str, Any] | None,
        method: str,
        confidence: float | None,
        reason: str,
    ) -> ResolutionResult:
        return ResolutionResult(
            canonical_team_id=team.get("canonical_team_id") if team else None,
            canonical_name=team.get("canonical_name") if team else None,
            provider=str(query["provider"]),
            provider_team_id=query.get("provider_team_id"),
            provider_team_name=query.get("provider_team_name"),
            resolution_status="resolved" if team else "unresolved",
            resolution_method=method,
            confidence=confidence if team else None,
            reason=reason,
        )

    def resolve_team(
        self,
        provider: str,
        provider_team_name: str | None,
        provider_team_id: str | None = None,
        *,
        country: str | None = None,
        competition_context: str | None = None,
        gender: str | None = None,
        team_level: str | None = None,
    ) -> ResolutionResult:
        query = {
            "provider": provider,
            "provider_team_id": provider_team_id,
            "provider_team_name": provider_team_name,
            "country": country,
            "competition_context": competition_context,
            "gender": gender,
            "team_level": team_level,
        }

        # An exact provider ID is authoritative only when it maps to one
        # reviewed canonical entity and context does not contradict it.
        id_rows = [
            (team, mapping)
            for team in self.teams
            for mapping in team.get("provider_mappings", [])
            if self._mapping_matches(mapping, provider, provider_team_id) and self._compatible(team, query)
        ]
        if provider_team_id is not None:
            if len(id_rows) == 1:
                return self._result(query, id_rows[0][0], "provider_id_exact", 1.0, "reviewed provider ID mapping")
            if len(id_rows) > 1:
                return self._result(query, None, "unresolved", None, "provider ID maps to multiple canonical teams")

        # A generic name is never confirmation material. An explicit provider
        # ID that was not reviewed also cannot bypass this unresolved result.
        if not provider_team_name or self._has_dangerous_generic_name(provider_team_name):
            return self._result(query, None, "unresolved", None, "generic or missing team name requires explicit reviewed ID/context")

        crosswalk_rows = [
            row for row in self.crosswalk
            if row.get("provider") == provider and row.get("provider_team_id") == provider_team_id
        ]
        if len(crosswalk_rows) == 1:
            canonical_id = crosswalk_rows[0].get("canonical_team_id")
            teams = [team for team in self.teams if team.get("canonical_team_id") == canonical_id and self._compatible(team, query)]
            if len(teams) == 1:
                return self._result(query, teams[0], "existing_crosswalk", 1.0, "reviewed existing crosswalk")

        candidates = []
        raw_name = provider_team_name.strip()
        normalized_name = self.normalize_name(raw_name)
        for team in self.teams:
            if not self._compatible(team, query):
                continue
            names = [team.get("canonical_name", ""), *team.get("aliases", [])]
            for mapping in team.get("provider_mappings", []):
                if mapping.get("provider") == provider:
                    names.extend([mapping.get("provider_team_name", ""), *mapping.get("aliases", [])])
            if raw_name.casefold() in {str(name).strip().casefold() for name in names if name}:
                candidates.append(team)
        if len(candidates) == 1:
            return self._result(query, candidates[0], "exact_alias", 0.99, "reviewed exact alias")
        if len(candidates) > 1:
            return self._result(query, None, "unresolved", None, "exact alias is ambiguous in available context")

        normalized_candidates = []
        for team in self.teams:
            if not self._compatible(team, query):
                continue
            names = [team.get("canonical_name", ""), *team.get("aliases", [])]
            for mapping in team.get("provider_mappings", []):
                if mapping.get("provider") == provider:
                    names.extend([mapping.get("provider_team_name", ""), *mapping.get("aliases", [])])
            if normalized_name and normalized_name in {self.normalize_name(str(name)) for name in names if name}:
                normalized_candidates.append(team)
        if len(normalized_candidates) == 1:
            return self._result(query, normalized_candidates[0], "normalized_alias", 0.9, "unique normalized alias with compatible context")
        if len(normalized_candidates) > 1:
            return self._result(query, None, "unresolved", None, "normalized alias is ambiguous")

        return self._result(query, None, "unresolved", None, "no reviewed alias or provider ID mapping")


def iter_registry_names(registry_path: str | Path = DEFAULT_TEAM_REGISTRY) -> Iterable[str]:
    """Yield canonical names for audit tooling without exposing mutable state."""

    resolver = TeamEntityResolver(registry_path)
    for team in resolver.teams:
        yield str(team["canonical_name"])
