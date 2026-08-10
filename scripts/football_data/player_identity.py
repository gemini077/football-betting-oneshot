"""Small, explicit player identity resolver for lineup consistency."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_PLAYER_REGISTRY = Path(__file__).resolve().parents[2] / "data" / "football_data" / "player_identity_registry.json"


@dataclass(frozen=True)
class PlayerResolutionResult:
    canonical_player_id: str | None
    canonical_name: str | None
    resolution_status: str
    resolution_method: str
    confidence: float | None
    reason: str


class PlayerIdentityResolver:
    """Resolve only reviewed provider IDs or unique exact names within a team."""

    def __init__(self, registry_path: str | Path = DEFAULT_PLAYER_REGISTRY) -> None:
        with Path(registry_path).open("r", encoding="utf-8") as handle:
            self.registry = json.load(handle)
        self.players = list(self.registry.get("players", []))

    @staticmethod
    def normalize_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value or "").casefold().strip()
        return re.sub(r"[^\w\u3400-\u9fff]+", "", normalized, flags=re.UNICODE)

    def _result(self, player: Mapping[str, Any] | None, method: str, confidence: float | None, reason: str) -> PlayerResolutionResult:
        return PlayerResolutionResult(
            canonical_player_id=player.get("canonical_player_id") if player else None,
            canonical_name=player.get("canonical_name") if player else None,
            resolution_status="resolved" if player else "unresolved",
            resolution_method=method,
            confidence=confidence if player else None,
            reason=reason,
        )

    @staticmethod
    def _team_compatible(player: Mapping[str, Any], team_id: str | None) -> bool:
        return not team_id or not player.get("team_id") or player.get("team_id") == team_id

    def resolve_player(
        self,
        provider: str,
        provider_player_name: str | None,
        provider_player_id: str | None = None,
        *,
        team_id: str | None = None,
    ) -> PlayerResolutionResult:
        id_matches = [
            player
            for player in self.players
            for mapping in player.get("provider_mappings", [])
            if mapping.get("provider") == provider
            and provider_player_id is not None
            and str(mapping.get("provider_player_id")) == str(provider_player_id)
            and self._team_compatible(player, team_id)
        ]
        if len(id_matches) == 1:
            return self._result(id_matches[0], "provider_id_exact", 1.0, "reviewed provider player ID")
        if len(id_matches) > 1:
            return self._result(None, "unresolved", None, "provider player ID is ambiguous")
        if not provider_player_name:
            return self._result(None, "unresolved", None, "missing player name and unreviewed ID")

        exact_matches = []
        raw = provider_player_name.strip().casefold()
        normalized = self.normalize_name(provider_player_name)
        for player in self.players:
            if not self._team_compatible(player, team_id):
                continue
            names = []
            for mapping in player.get("provider_mappings", []):
                if mapping.get("provider") == provider:
                    names.extend([mapping.get("provider_player_name", ""), *mapping.get("aliases", [])])
            if raw in {str(name).strip().casefold() for name in names if name}:
                exact_matches.append(player)
        if len(exact_matches) == 1:
            return self._result(exact_matches[0], "exact_alias", 0.99, "unique exact player name within team context")
        if len(exact_matches) > 1:
            return self._result(None, "unresolved", None, "player name is ambiguous")

        normalized_matches = []
        for player in self.players:
            if not self._team_compatible(player, team_id):
                continue
            provider_names = [
                mapping.get("provider_player_name", "")
                for mapping in player.get("provider_mappings", [])
                if mapping.get("provider") == provider
            ]
            if normalized and normalized in {self.normalize_name(str(name)) for name in provider_names if name}:
                normalized_matches.append(player)
        if len(normalized_matches) == 1:
            return self._result(normalized_matches[0], "normalized_alias", 0.9, "unique normalized name within team context")
        return self._result(None, "unresolved", None, "no reviewed player identity")
