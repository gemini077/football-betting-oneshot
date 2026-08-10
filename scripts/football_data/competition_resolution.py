"""Reviewed provider competition/season identity resolution.

Competition names are descriptive evidence only.  A canonical identity is
returned only for an exact, reviewed provider-and-season mapping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_COMPETITION_REGISTRY = Path(__file__).resolve().parents[2] / "data" / "football_data" / "competition_registry.json"


@dataclass(frozen=True)
class CompetitionResolutionResult:
    canonical_competition_id: str | None
    canonical_season_id: str | None
    provider: str
    provider_competition_id: str | None
    provider_competition_name: str | None
    provider_season_id: str | None
    provider_season_name: str | None
    resolution_status: str
    resolution_method: str
    confidence: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_competition_id": self.canonical_competition_id,
            "canonical_season_id": self.canonical_season_id,
            "provider": self.provider,
            "provider_competition_id": self.provider_competition_id,
            "provider_competition_name": self.provider_competition_name,
            "provider_season_id": self.provider_season_id,
            "provider_season_name": self.provider_season_name,
            "resolution_status": self.resolution_status,
            "resolution_method": self.resolution_method,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class CompetitionEntityResolver:
    """Resolve only exact reviewed provider competition/season mappings."""

    def __init__(self, registry_path: str | Path = DEFAULT_COMPETITION_REGISTRY) -> None:
        self.registry_path = Path(registry_path)
        with self.registry_path.open("r", encoding="utf-8") as handle:
            self.registry = json.load(handle)
        self.competitions = list(self.registry.get("competitions", []))

    @staticmethod
    def _same_name(left: Any, right: str | None) -> bool:
        return right is None or (left is not None and str(left).strip().casefold() == right.strip().casefold())

    @staticmethod
    def _reviewed(mapping: Mapping[str, Any]) -> bool:
        return bool(mapping.get("verified")) and mapping.get("resolution_method") in {
            "manual_verified",
            "provider_id_exact",
            "existing_crosswalk",
            "exact_alias",
        }

    def _result(
        self,
        *,
        provider: str,
        provider_competition_id: str | None,
        provider_competition_name: str | None,
        provider_season_id: str | None,
        provider_season_name: str | None,
        competition: Mapping[str, Any] | None = None,
        season: Mapping[str, Any] | None = None,
        method: str = "unresolved",
        confidence: float | None = None,
        reason: str,
    ) -> CompetitionResolutionResult:
        resolved = competition is not None and season is not None
        return CompetitionResolutionResult(
            canonical_competition_id=str(competition.get("canonical_competition_id")) if resolved else None,
            canonical_season_id=str(season.get("canonical_season_id")) if resolved else None,
            provider=provider,
            provider_competition_id=provider_competition_id,
            provider_competition_name=provider_competition_name,
            provider_season_id=provider_season_id,
            provider_season_name=provider_season_name,
            resolution_status="resolved" if resolved else "unresolved",
            resolution_method=method if resolved else "unresolved",
            confidence=confidence if resolved else None,
            reason=reason,
        )

    def resolve(
        self,
        *,
        provider: str,
        provider_competition_id: str | None,
        provider_competition_name: str | None,
        provider_season_id: str | None,
        provider_season_name: str | None,
    ) -> CompetitionResolutionResult:
        """Return a canonical pair only when both reviewed provider IDs match.

        No name-only, substring, edit-distance, or first-row fallback is used.
        """

        values = {
            "provider": str(provider),
            "provider_competition_id": str(provider_competition_id) if provider_competition_id is not None else None,
            "provider_competition_name": str(provider_competition_name) if provider_competition_name is not None else None,
            "provider_season_id": str(provider_season_id) if provider_season_id is not None else None,
            "provider_season_name": str(provider_season_name) if provider_season_name is not None else None,
        }
        if not values["provider_competition_id"] or not values["provider_season_id"]:
            return self._result(**values, reason="reviewed provider competition and season IDs are required")

        matches: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for competition in self.competitions:
            for season in competition.get("seasons", []):
                if not isinstance(season, Mapping):
                    continue
                if season.get("provider") != values["provider"]:
                    continue
                if str(season.get("provider_competition_id")) != values["provider_competition_id"]:
                    continue
                if str(season.get("provider_season_id")) != values["provider_season_id"]:
                    continue
                matches.append((competition, season))

        if len(matches) > 1:
            return self._result(**values, reason="ambiguous_competition_id")
        if not matches:
            return self._result(**values, reason="no reviewed provider competition/season mapping")

        competition, season = matches[0]
        if not self._reviewed(season):
            return self._result(**values, reason="provider mapping is not reviewed")
        if not self._same_name(season.get("provider_competition_name"), values["provider_competition_name"]):
            return self._result(**values, reason="provider competition name conflicts with reviewed mapping")
        if not self._same_name(season.get("provider_season_name"), values["provider_season_name"]):
            return self._result(**values, reason="provider season name conflicts with reviewed mapping")
        return self._result(
            **values,
            competition=competition,
            season=season,
            method=str(season.get("resolution_method")),
            confidence=float(season.get("confidence", 1.0)),
            reason="reviewed exact provider competition and season mapping",
        )

    resolve_competition = resolve

