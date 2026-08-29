"""Deterministic, competition-scoped football team identity registry.

This module is intentionally evidence-first.  It only promotes mappings that
already exist in reviewed crosswalks, reviewed alias groups, current reviewed
identity evidence, or canonical IDs present in the authoritative history
store.  It never uses fuzzy similarity, translation guesses, kickoff
proximity, or a highest-score tie breaker.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .storage import HistoricalResultStore, content_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDENTITY_REGISTRY_PATH = PROJECT_ROOT / "data" / "football_data" / "id_auto_1" / "identity_registry.json"
DEFAULT_PROJECT_CROSSWALK_PATH = PROJECT_ROOT / "data" / "football_data" / "verified_project_provider_crosswalk.json"
DEFAULT_VERIFIED_CROSSWALK_PATH = PROJECT_ROOT / "data" / "football_data" / "verified_identity_crosswalk.json"
DEFAULT_TEAM_ALIAS_REGISTRY_PATH = PROJECT_ROOT / "data" / "football_data" / "team_alias_registry.json"
DEFAULT_REVIEWED_ALIAS_PATH = PROJECT_ROOT / "data" / "team_aliases.json"
DEFAULT_CURRENT_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
DEFAULT_PROVIDER_MATCH_CROSSWALK_PATH = PROJECT_ROOT / "data" / "provider_match_crosswalk.json"
DEFAULT_FOOTBALL_DATA_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "football_data_uk" / "identity_evidence.json"
DEFAULT_OPENFOOTBALL_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "openfootball" / "identity_evidence.json"
DEFAULT_OPENFOOTBALL_ESPANA_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "openfootball" / "espana_identity_evidence.json"
DEFAULT_OPENFOOTBALL_BRAZIL_IDENTITY_EVIDENCE_PATH = PROJECT_ROOT / "data" / "football_data" / "openfootball" / "south_america_brazil_identity_evidence.json"

IDENTITY_REGISTRY_CONTRACT_VERSION = "identity_registry.v1"
RESOLUTION_LADDER = (
    "stable_provider_id_crosswalk",
    "reviewed_canonical_provider_crosswalk",
    "fixture_canonical_id",
    "competition_exact_normalized_name",
    "competition_reviewed_alias",
)
IDENTITY_STATUSES = frozenset({"AUTO_RESOLVED", "REVIEWABLE_CANDIDATE", "AMBIGUOUS", "UNRESOLVED"})


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _valid_team_id(value: Any) -> bool:
    return _text(value).startswith("team:")


def normalize_identity_name(value: Any) -> str:
    """Normalize only representation noise; do not transliterate or fuzz."""

    normalized = unicodedata.normalize("NFKC", _text(value)).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _json_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _path_text(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _scope_values(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {_text(item) for item in value if _text(item)}
    text = _text(value)
    return {text} if text else set()


def _mapping_competitions(mapping: Mapping[str, Any]) -> set[str]:
    return _scope_values(
        mapping.get("competition_id")
        or mapping.get("competition")
        or mapping.get("competition_scope")
    )


def _verified(raw: Mapping[str, Any]) -> bool:
    return raw.get("verified") is True


def _source_refs(raw: Mapping[str, Any]) -> list[str]:
    refs = list(raw.get("source_refs") or [])
    refs.extend(list(raw.get("verification_evidence") or []))
    for key in ("source_ref", "evidence", "verification_evidence_digest"):
        if raw.get(key):
            refs.append(raw[key])
    return _unique(refs)


class IdentityRegistryResolver:
    """Resolve one fixture side through the five-level exact ladder."""

    def __init__(self, registry: Mapping[str, Any] | str | Path) -> None:
        if isinstance(registry, (str, Path)):
            registry = _json_object(registry)
        self.registry = dict(registry)
        self.teams = [row for row in self.registry.get("teams", []) if isinstance(row, Mapping)]
        self.teams_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        self.by_provider_id: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_provider_name: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        self.by_exact_name: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_reviewed_alias: dict[tuple[str, str], set[str]] = defaultdict(set)
        for team in self.teams:
            team_id = _text(team.get("canonical_team_id"))
            if not _valid_team_id(team_id):
                continue
            self.teams_by_id[team_id].append(team)
            scopes = _scope_values(team.get("competition_scope"))
            for mapping in team.get("provider_mappings", []) or []:
                if not isinstance(mapping, Mapping) or not _verified(mapping):
                    continue
                provider = normalize_identity_name(mapping.get("provider"))
                provider_id = _text(mapping.get("provider_team_id"))
                if provider and provider_id and self._mapping_in_scope(team, mapping, None):
                    self.by_provider_id[(provider, provider_id)].add(team_id)
                exact = _text(mapping.get("provider_exact_name") or mapping.get("provider_team_name"))
                mapping_scopes = _mapping_competitions(mapping) or scopes
                for competition_id in mapping_scopes:
                    if provider and exact:
                        self.by_provider_name[(competition_id, provider, normalize_identity_name(exact))].add(team_id)
            for competition_id in scopes:
                for name in [team.get("canonical_name"), *(team.get("canonical_source_names") or [])]:
                    normalized = normalize_identity_name(name)
                    if normalized:
                        self.by_exact_name[(competition_id, normalized)].add(team_id)
                for alias in team.get("reviewed_aliases", []) or []:
                    normalized = normalize_identity_name(alias)
                    if normalized:
                        self.by_reviewed_alias[(competition_id, normalized)].add(team_id)

    @staticmethod
    def _mapping_in_scope(team: Mapping[str, Any], mapping: Mapping[str, Any], competition_id: str | None) -> bool:
        if not competition_id:
            return True
        team_scopes = _scope_values(team.get("competition_scope"))
        mapping_scopes = _mapping_competitions(mapping)
        # A canonical team may appear in more than one competition.  A
        # provider ID is reusable when the canonical team's own scope includes
        # the requested competition; otherwise an explicitly scoped mapping
        # must name the requested competition.
        if team_scopes and competition_id not in team_scopes:
            return False
        if not team_scopes and mapping_scopes and competition_id not in mapping_scopes:
            return False
        return not mapping_scopes or competition_id in mapping_scopes or bool(team_scopes)

    def _team(self, team_id: str) -> Mapping[str, Any] | None:
        rows = self.teams_by_id.get(team_id, [])
        return rows[0] if len(rows) == 1 else None

    def _scoped_ids(self, ids: Iterable[str], competition_id: str) -> list[str]:
        result: list[str] = []
        for team_id in sorted(set(ids)):
            team = self._team(team_id)
            if team is None:
                continue
            scopes = _scope_values(team.get("competition_scope"))
            if not scopes or competition_id in scopes:
                result.append(team_id)
        return result

    def _result(
        self,
        *,
        provider: Any,
        provider_team_id: Any,
        provider_team_name: Any,
        status: str,
        method: str,
        candidates: Iterable[str] = (),
        evidence: Iterable[str] = (),
        reason: str = "",
    ) -> dict[str, Any]:
        candidate_ids = sorted({_text(value) for value in candidates if _text(value)})
        canonical_team_id = candidate_ids[0] if status == "AUTO_RESOLVED" and len(candidate_ids) == 1 else None
        team = self._team(canonical_team_id) if canonical_team_id else None
        if status not in IDENTITY_STATUSES:
            raise ValueError(f"unknown identity status: {status}")
        return {
            "canonical_team_id": canonical_team_id,
            "canonical_name": _text(team.get("canonical_name")) if team else None,
            "provider": _text(provider),
            "provider_team_id": _text(provider_team_id) or None,
            "provider_team_name": _text(provider_team_name) or None,
            "resolution_status": status,
            "resolution_method": method,
            "confidence_class": "A" if status == "AUTO_RESOLVED" and method in RESOLUTION_LADDER[:3] else "B" if status == "AUTO_RESOLVED" else None,
            "candidate_team_ids": candidate_ids,
            "evidence": _unique(evidence),
            "reason": reason,
            "ambiguity_state": "AMBIGUOUS" if status == "AMBIGUOUS" else "NONE",
        }

    def resolve_side(
        self,
        *,
        competition_id: str,
        provider: str | None = None,
        provider_team_id: str | None = None,
        provider_team_name: str | None = None,
        fixture_canonical_team_id: str | None = None,
        evidence: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Resolve one side.  Each level either returns one ID or fails closed."""

        provider_key = normalize_identity_name(provider)
        team_id = _text(provider_team_id)
        name = _text(provider_team_name)
        base_evidence = list(evidence)

        # LEVEL 1: existing stable provider ID crosswalk.
        if provider_key and team_id:
            id_candidates = []
            for candidate_id in self.by_provider_id.get((provider_key, team_id), set()):
                team = self._team(candidate_id)
                if team and self._mapping_team_id_in_scope(team, provider_key, team_id, competition_id):
                    id_candidates.append(candidate_id)
            if len(id_candidates) == 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AUTO_RESOLVED",
                    method=RESOLUTION_LADDER[0],
                    candidates=id_candidates,
                    evidence=[*base_evidence, "identity_registry:stable_provider_id"],
                    reason="unique reviewed provider team ID",
                )
            if len(id_candidates) > 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AMBIGUOUS",
                    method=RESOLUTION_LADDER[0],
                    candidates=id_candidates,
                    evidence=base_evidence,
                    reason="provider team ID maps to multiple canonical teams",
                )

        # LEVEL 2: reviewed provider-name crosswalk, still exact and scoped.
        if name:
            if provider_key:
                provider_ids = self.by_provider_name.get((competition_id, provider_key, normalize_identity_name(name)), set())
            else:
                provider_ids = {
                    candidate_id
                    for (scoped_competition, _provider, normalized_name), candidate_ids in self.by_provider_name.items()
                    if scoped_competition == competition_id and normalized_name == normalize_identity_name(name)
                    for candidate_id in candidate_ids
                }
            provider_candidates = self._scoped_ids(provider_ids, competition_id)
            if len(provider_candidates) == 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AUTO_RESOLVED",
                    method=RESOLUTION_LADDER[1],
                    candidates=provider_candidates,
                    evidence=[*base_evidence, "identity_registry:reviewed_provider_name"],
                    reason="unique reviewed provider exact name",
                )
            if len(provider_candidates) > 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AMBIGUOUS",
                    method=RESOLUTION_LADDER[1],
                    candidates=provider_candidates,
                    evidence=base_evidence,
                    reason="provider exact name maps to multiple canonical teams",
                )

        # LEVEL 3: an explicit canonical ID carried on the fixture.
        explicit_id = _text(fixture_canonical_team_id)
        if explicit_id:
            team = self._team(explicit_id)
            if team and (not _scope_values(team.get("competition_scope")) or competition_id in _scope_values(team.get("competition_scope"))):
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AUTO_RESOLVED",
                    method=RESOLUTION_LADDER[2],
                    candidates=[explicit_id],
                    evidence=[*base_evidence, "identity_registry:fixture_canonical_id"],
                    reason="fixture carries a known canonical team ID",
                )
            return self._result(
                provider=provider,
                provider_team_id=team_id,
                provider_team_name=name,
                status="UNRESOLVED",
                method=RESOLUTION_LADDER[2],
                evidence=base_evidence,
                reason="fixture canonical team ID is unknown or outside competition scope",
            )

        normalized_name = normalize_identity_name(name)
        if normalized_name:
            # LEVEL 4: competition-constrained exact normalized canonical name.
            exact_candidates = self._scoped_ids(
                self.by_exact_name.get((competition_id, normalized_name), set()),
                competition_id,
            )
            if len(exact_candidates) == 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AUTO_RESOLVED",
                    method=RESOLUTION_LADDER[3],
                    candidates=exact_candidates,
                    evidence=[*base_evidence, "identity_registry:competition_exact_name"],
                    reason="unique competition-scoped exact normalized name",
                )
            if len(exact_candidates) > 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AMBIGUOUS",
                    method=RESOLUTION_LADDER[3],
                    candidates=exact_candidates,
                    evidence=base_evidence,
                    reason="exact normalized name has multiple competition-scoped candidates",
                )

            # LEVEL 5: competition-constrained reviewed alias.
            alias_candidates = self._scoped_ids(
                self.by_reviewed_alias.get((competition_id, normalized_name), set()),
                competition_id,
            )
            if len(alias_candidates) == 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AUTO_RESOLVED",
                    method=RESOLUTION_LADDER[4],
                    candidates=alias_candidates,
                    evidence=[*base_evidence, "identity_registry:competition_reviewed_alias"],
                    reason="unique competition-scoped reviewed alias",
                )
            if len(alias_candidates) > 1:
                return self._result(
                    provider=provider,
                    provider_team_id=team_id,
                    provider_team_name=name,
                    status="AMBIGUOUS",
                    method=RESOLUTION_LADDER[4],
                    candidates=alias_candidates,
                    evidence=base_evidence,
                    reason="reviewed alias has multiple competition-scoped candidates",
                )

        return self._result(
            provider=provider,
            provider_team_id=team_id,
            provider_team_name=name,
            status="UNRESOLVED",
            method="unresolved",
            evidence=base_evidence,
            reason="no unique deterministic evidence in identity registry",
        )

    def _mapping_team_id_in_scope(self, team: Mapping[str, Any], provider: str, provider_id: str, competition_id: str) -> bool:
        for mapping in team.get("provider_mappings", []) or []:
            if not isinstance(mapping, Mapping) or not _verified(mapping):
                continue
            if normalize_identity_name(mapping.get("provider")) != provider or _text(mapping.get("provider_team_id")) != provider_id:
                continue
            if self._mapping_in_scope(team, mapping, competition_id):
                return True
        return False

    @staticmethod
    def _field(fixture: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            value = fixture.get(key)
            if value not in (None, ""):
                return value
        return None

    def resolve_fixture(
        self,
        fixture: Mapping[str, Any],
        *,
        competition_id: str,
        source_observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve both sides without changing the fixture or its source data."""

        observation = source_observation if isinstance(source_observation, Mapping) else {}
        side_results: dict[str, dict[str, Any]] = {}
        for side in ("home", "away"):
            side_observation = observation.get(side) if isinstance(observation.get(side), Mapping) else {}
            explicit_provider = _text(
                side_observation.get("provider")
                or fixture.get(f"{side}_provider")
                or fixture.get("identity_provider")
                or fixture.get("provider")
            )
            provider_id = _text(
                side_observation.get("provider_team_id")
                or self._field(fixture, f"{side}_provider_team_id", f"provider_{side}_team_id")
            )
            provider_name = _text(
                side_observation.get("provider_team_name")
                or self._field(
                    fixture,
                    f"provider_{side}_team_name",
                    f"nowscoreProvider{side.title()}",
                    f"{side}Team",
                    f"{side}_team",
                    side,
                )
            )
            canonical_id = _text(
                side_observation.get("fixture_canonical_team_id")
                or self._field(fixture, f"{side}_team_id", f"{side}_canonical_team_id")
            )
            evidence = [
                _text(side_observation.get("evidence_source")),
                _text(fixture.get("matchId") or fixture.get("match_id") or fixture.get("id")),
            ]
            provider_candidates = [explicit_provider] if explicit_provider else []
            # These are source labels carried by the current schedule schema,
            # not inferred team identities: nowscoreProvider* is a Nowscore
            # observation and a 500-* match ID is a 500 schedule observation.
            if not explicit_provider and self._field(fixture, f"nowscoreProvider{side.title()}"):
                provider_candidates.append("nowscore")
            if not explicit_provider and _text(fixture.get("matchId") or fixture.get("match_id")).startswith("500-"):
                provider_candidates.append("500")
            if not explicit_provider:
                # An existing reviewed crosswalk may predate a provider label
                # on the schedule row.  The empty-provider attempt is still
                # exact: it unions reviewed provider names and fails closed on
                # more than one canonical target.
                provider_candidates.append("")
            provider_candidates = list(dict.fromkeys(provider_candidates))
            if not provider_candidates:
                provider_candidates = [""]

            attempts = [
                self.resolve_side(
                    competition_id=competition_id,
                    provider=provider or None,
                    provider_team_id=provider_id or None,
                    provider_team_name=provider_name or None,
                    fixture_canonical_team_id=canonical_id or None,
                    evidence=evidence,
                )
                for provider in provider_candidates
            ]
            side_results[side] = self._choose_provider_results(attempts)

        statuses = [side_results[side]["resolution_status"] for side in ("home", "away")]
        if "AMBIGUOUS" in statuses:
            fixture_status = "AMBIGUOUS"
        elif statuses == ["AUTO_RESOLVED", "AUTO_RESOLVED"]:
            fixture_status = "AUTO_RESOLVED"
        elif "AUTO_RESOLVED" in statuses:
            fixture_status = "PARTIAL"
        else:
            fixture_status = "UNRESOLVED"
        methods = [side_results[side]["resolution_method"] for side in ("home", "away")]
        return {
            "home_team_id": side_results["home"].get("canonical_team_id"),
            "away_team_id": side_results["away"].get("canonical_team_id"),
            "status": fixture_status.casefold(),
            "identity_status": fixture_status,
            "resolution_method": methods[0] if methods[0] == methods[1] else "mixed_deterministic" if fixture_status in {"AUTO_RESOLVED", "PARTIAL"} else methods[0],
            "side_resolutions": side_results,
            "evidence": _unique([
                evidence
                for side in side_results.values()
                for evidence in side.get("evidence", [])
            ]),
        }

    @staticmethod
    def _method_rank(method: str) -> int:
        try:
            return RESOLUTION_LADDER.index(method)
        except ValueError:
            return len(RESOLUTION_LADDER)

    def _choose_provider_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge source-labelled attempts without weakening the ladder."""

        if len(results) == 1:
            return results[0]
        actionable = [
            result
            for result in results
            if result.get("resolution_status") in {"AUTO_RESOLVED", "AMBIGUOUS"}
        ]
        if not actionable:
            return results[0]
        best_rank = min(self._method_rank(str(result.get("resolution_method"))) for result in actionable)
        best = [result for result in actionable if self._method_rank(str(result.get("resolution_method"))) == best_rank]
        candidate_ids = sorted({
            candidate_id
            for result in best
            for candidate_id in result.get("candidate_team_ids", [])
            if _text(candidate_id)
        })
        if any(result.get("resolution_status") == "AMBIGUOUS" for result in best) or len(candidate_ids) > 1:
            first = best[0]
            return {
                **first,
                "canonical_team_id": None,
                "canonical_name": None,
                "resolution_status": "AMBIGUOUS",
                "candidate_team_ids": candidate_ids,
                "ambiguity_state": "AMBIGUOUS",
                "evidence": _unique([
                    evidence
                    for result in best
                    for evidence in result.get("evidence", [])
                ]),
                "reason": "source-labelled exact evidence has multiple canonical candidates",
            }
        chosen = best[0]
        return {
            **chosen,
            "evidence": _unique([
                evidence
                for result in best
                for evidence in result.get("evidence", [])
            ]),
        }


class IdentityRegistryBuilder:
    """Build a durable registry from existing deterministic evidence only."""

    def __init__(
        self,
        *,
        historical_records: Iterable[Mapping[str, Any]] | None = None,
        historical_store: HistoricalResultStore | None = None,
        coverage_registry: Mapping[str, Any] | None = None,
        project_crosswalk_path: str | Path = DEFAULT_PROJECT_CROSSWALK_PATH,
        verified_crosswalk_path: str | Path = DEFAULT_VERIFIED_CROSSWALK_PATH,
        team_alias_registry_path: str | Path = DEFAULT_TEAM_ALIAS_REGISTRY_PATH,
        reviewed_alias_path: str | Path = DEFAULT_REVIEWED_ALIAS_PATH,
        current_identity_evidence_path: str | Path = DEFAULT_CURRENT_IDENTITY_EVIDENCE_PATH,
        provider_match_crosswalk_path: str | Path = DEFAULT_PROVIDER_MATCH_CROSSWALK_PATH,
        football_data_identity_evidence_path: str | Path = DEFAULT_FOOTBALL_DATA_IDENTITY_EVIDENCE_PATH,
        openfootball_identity_evidence_path: str | Path = DEFAULT_OPENFOOTBALL_IDENTITY_EVIDENCE_PATH,
        openfootball_espana_identity_evidence_path: str | Path = DEFAULT_OPENFOOTBALL_ESPANA_IDENTITY_EVIDENCE_PATH,
        openfootball_brazil_identity_evidence_path: str | Path = DEFAULT_OPENFOOTBALL_BRAZIL_IDENTITY_EVIDENCE_PATH,
        now: datetime | None = None,
    ) -> None:
        self.historical_store = historical_store or HistoricalResultStore()
        self.historical_records = list(historical_records) if historical_records is not None else list(self.historical_store.iter_records())
        self.coverage_registry = dict(coverage_registry or {})
        self.paths = {
            "project_crosswalk": Path(project_crosswalk_path),
            "verified_crosswalk": Path(verified_crosswalk_path),
            "team_alias_registry": Path(team_alias_registry_path),
            "reviewed_alias_registry": Path(reviewed_alias_path),
            "current_identity_evidence": Path(current_identity_evidence_path),
            "provider_match_crosswalk": Path(provider_match_crosswalk_path),
            "football_data_identity_evidence": Path(football_data_identity_evidence_path),
            "openfootball_identity_evidence": Path(openfootball_identity_evidence_path),
            "openfootball_espana_identity_evidence": Path(openfootball_espana_identity_evidence_path),
            "openfootball_brazil_identity_evidence": Path(openfootball_brazil_identity_evidence_path),
        }
        self.now = now or datetime.now(timezone.utc)

    def _coverage_context(self) -> dict[str, dict[str, Any]]:
        context: dict[str, dict[str, Any]] = {}
        for row in self.coverage_registry.get("competitions", []) or []:
            if not isinstance(row, Mapping):
                continue
            competition_id = _text(row.get("competition_id"))
            if competition_id:
                context[competition_id] = {
                    "country": _text(row.get("country")),
                    "canonical_name": _text(row.get("canonical_name")),
                }
        return context

    def _competition_id(self, value: Any) -> str | None:
        candidate = _text(value)
        if not candidate:
            return None
        if candidate.startswith("competition:"):
            return candidate
        normalized = normalize_identity_name(candidate)
        for row in self.coverage_registry.get("competitions", []) or []:
            if not isinstance(row, Mapping):
                continue
            aliases = [row.get("competition_id"), row.get("competition_key"), row.get("canonical_name"), *(row.get("aliases") or [])]
            if normalized and normalized in {normalize_identity_name(alias) for alias in aliases if alias}:
                return _text(row.get("competition_id")) or None
        return None

    @staticmethod
    def _team_row(team_id: str) -> dict[str, Any]:
        return {
            "canonical_team_id": team_id,
            "canonical_name": team_id,
            "competition_scope": set(),
            "country": set(),
            "canonical_source_names": set(),
            "reviewed_aliases": set(),
            "provider_mappings": {},
            "evidence_sources": set(),
        }

    @staticmethod
    def _add_name(row: dict[str, Any], field: str, value: Any) -> None:
        value_text = _text(value)
        if not value_text:
            return
        if field == "canonical_name" and row.get(field) in (None, "", row["canonical_team_id"]):
            row[field] = value_text
        elif field != "canonical_name":
            row[field].add(value_text)

    def _ensure(
        self,
        teams: dict[str, dict[str, Any]],
        team_id: Any,
        *,
        competition_id: Any = None,
        country: Any = None,
        canonical_name: Any = None,
        source_name: Any = None,
        source_ref: Any = None,
    ) -> dict[str, Any] | None:
        team_id_text = _text(team_id)
        if not _valid_team_id(team_id_text):
            return None
        row = teams.setdefault(team_id_text, self._team_row(team_id_text))
        row["competition_scope"].update(_scope_values(competition_id))
        row["country"].update(_scope_values(country))
        self._add_name(row, "canonical_name", canonical_name)
        self._add_name(row, "canonical_source_names", source_name)
        if source_ref:
            row["evidence_sources"].add(_text(source_ref))
        return row

    def _add_provider_mapping(self, row: dict[str, Any], raw: Mapping[str, Any], source_path: Path) -> None:
        if not _verified(raw):
            return
        provider = _text(raw.get("provider"))
        exact_name = _text(raw.get("provider_exact_name") or raw.get("provider_team_name"))
        provider_id = _text(raw.get("provider_team_id")) or None
        competition_ids = _mapping_competitions(raw)
        key = (provider, provider_id or "", exact_name, ",".join(sorted(competition_ids)))
        existing = row["provider_mappings"].get(key)
        if existing is None:
            existing = {
                "provider": provider,
                "provider_team_id": provider_id,
                "provider_exact_name": exact_name or None,
                "competition_scope": sorted(competition_ids),
                "reviewed_aliases": [],
                "evidence_source": _path_text(source_path),
                "evidence_timestamp": _text(raw.get("verified_at") or raw.get("updated_at")) or None,
                "resolution_method": _text(raw.get("resolution_method") or raw.get("verification_method")) or "reviewed_crosswalk",
                "confidence_class": "A" if provider_id else "B",
                "ambiguity_state": "NONE",
                "verified": True,
                "source_refs": [],
            }
            row["provider_mappings"][key] = existing
        existing["source_refs"] = _unique([*existing.get("source_refs", []), *_source_refs(raw)])
        existing["reviewed_aliases"] = _unique([
            *existing.get("reviewed_aliases", []),
            *list(raw.get("reviewed_aliases") or []),
            *list(raw.get("aliases") or []),
        ])
        for alias in existing["reviewed_aliases"]:
            row["reviewed_aliases"].add(alias)

    def _history_index(self) -> tuple[dict[tuple[str, str], set[str]], dict[str, Counter[str]], dict[str, set[str]]]:
        names: dict[tuple[str, str], set[str]] = defaultdict(set)
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        scopes: dict[str, set[str]] = defaultdict(set)
        for record in self.historical_records:
            if not isinstance(record, Mapping):
                continue
            competition_id = _text(record.get("competition_id"))
            if not competition_id:
                continue
            for side in ("home", "away"):
                team_id = _text(record.get(f"{side}_team_id"))
                raw_name = _text(record.get(f"raw_{side}_team"))
                if not _valid_team_id(team_id):
                    continue
                scopes[team_id].add(competition_id)
                if raw_name:
                    names[(competition_id, normalize_identity_name(raw_name))].add(team_id)
                    counts[team_id][raw_name] += 1
        return names, counts, scopes

    def _source_inputs(self, loaded: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        inputs: list[dict[str, Any]] = []
        for key, path in self.paths.items():
            row = {
                "kind": key,
                "path": _path_text(path),
                "exists": path.exists(),
                "sha256": content_sha256(loaded[key]) if loaded.get(key) else None,
            }
            if key in {"project_crosswalk", "verified_crosswalk"}:
                row["row_count"] = len(loaded.get(key, {}).get("mappings", []))
            elif key == "team_alias_registry":
                row["row_count"] = len(loaded.get(key, {}).get("teams", []))
            elif key == "reviewed_alias_registry":
                row["row_count"] = len(loaded.get(key, {}).get("teams", []))
            elif key in {
                "football_data_identity_evidence",
                "openfootball_identity_evidence",
                "openfootball_espana_identity_evidence",
                "openfootball_brazil_identity_evidence",
            }:
                payload = loaded.get(key, {})
                row["row_count"] = len(payload.get("mappings", payload.get("teams", [])))
            elif key == "current_identity_evidence":
                row["row_count"] = len(loaded.get(key, {}).get("matches", []))
            elif key == "provider_match_crosswalk":
                row["row_count"] = len(loaded.get(key, {}).get("matches", {}))
            inputs.append(row)
        history_path_value = getattr(self.historical_store, "path", None)
        history_path = Path(history_path_value) if history_path_value else Path("<provided-historical-records>")
        history_exists = bool(history_path_value and history_path.exists())
        dataset_digest = self.historical_store.dataset_digest() if history_exists else None
        inputs.append({
            "kind": "authoritative_historical_store",
            "path": str(history_path),
            "exists": history_exists,
            "row_count": len(self.historical_records),
            "dataset_digest": dataset_digest,
            "read_mode": "read_only",
        })
        return inputs

    def build(self) -> dict[str, Any]:
        loaded = {key: _json_object(path) for key, path in self.paths.items()}
        coverage = self._coverage_context()
        teams: dict[str, dict[str, Any]] = {}
        history_names, history_counts, history_scopes = self._history_index()

        # Canonical catalog from the immutable historical store.
        for team_id, counts in history_counts.items():
            for competition_id in history_scopes.get(team_id, set()):
                row = self._ensure(
                    teams,
                    team_id,
                    competition_id=competition_id,
                    country=coverage.get(competition_id, {}).get("country"),
                    canonical_name=counts.most_common(1)[0][0] if counts else team_id,
                    source_ref="authoritative_historical_store",
                )
                if row:
                    for source_name in counts:
                        row["canonical_source_names"].add(source_name)

        # Existing team registry, then verified crosswalks.
        team_alias_registry = loaded["team_alias_registry"]
        for raw in team_alias_registry.get("teams", []) or []:
            if not isinstance(raw, Mapping):
                continue
            scopes = list(raw.get("competition_context") or [])
            row = self._ensure(
                teams,
                raw.get("canonical_team_id"),
                competition_id=scopes,
                country=raw.get("country"),
                canonical_name=raw.get("canonical_name"),
                source_ref=_path_text(self.paths["team_alias_registry"]),
            )
            if not row:
                continue
            row["reviewed_aliases"].update(_unique([*list(raw.get("aliases") or [])]))
            for mapping in raw.get("provider_mappings", []) or []:
                if isinstance(mapping, Mapping) and _verified(mapping):
                    mapping_copy = dict(mapping)
                    mapping_copy.setdefault("competition_scope", scopes)
                    self._add_provider_mapping(row, mapping_copy, self.paths["team_alias_registry"])

        for source_key in ("project_crosswalk", "verified_crosswalk"):
            for raw in loaded[source_key].get("mappings", []) or []:
                if not isinstance(raw, Mapping) or not _verified(raw):
                    continue
                competition_id = raw.get("competition_id") or raw.get("competition")
                row = self._ensure(
                    teams,
                    raw.get("canonical_team_id"),
                    competition_id=competition_id,
                    country=raw.get("country") or coverage.get(_text(competition_id), {}).get("country"),
                    canonical_name=raw.get("canonical_name"),
                    source_ref=_path_text(self.paths[source_key]),
                )
                if row:
                    self._add_provider_mapping(row, raw, self.paths[source_key])

        # Existing Football-Data/OpenFootball identity evidence is already
        # reviewed and competition-scoped.  Importing it into one registry is
        # a deterministic consolidation, not a new provider adapter.
        for source_key in (
            "football_data_identity_evidence",
            "openfootball_identity_evidence",
            "openfootball_espana_identity_evidence",
            "openfootball_brazil_identity_evidence",
        ):
            document = loaded[source_key]
            provider = _text(document.get("provider"))
            raw_rows = document.get("mappings", document.get("teams", [])) or []
            for raw in raw_rows:
                if not isinstance(raw, Mapping) or not _verified(raw):
                    continue
                raw_competitions = raw.get("competition_keys") or raw.get("competition_scope") or raw.get("competition") or document.get("competition_key")
                if isinstance(raw_competitions, (str, bytes)):
                    raw_competitions = [raw_competitions]
                competition_ids = _unique(
                    self._competition_id(value)
                    for value in (raw_competitions or [])
                )
                if not competition_ids:
                    continue
                mapping = dict(raw)
                mapping["provider"] = provider or raw.get("provider")
                mapping["provider_team_name"] = raw.get("provider_team_name") or raw.get("provider_exact_name")
                mapping["competition_scope"] = competition_ids
                row = self._ensure(
                    teams,
                    raw.get("canonical_team_id"),
                    competition_id=competition_ids,
                    country=raw.get("country") or document.get("country") or coverage.get(competition_ids[0], {}).get("country"),
                    canonical_name=raw.get("canonical_name"),
                    source_ref=_path_text(self.paths[source_key]),
                )
                if row:
                    self._add_provider_mapping(row, mapping, self.paths[source_key])

        # Current reviewed fixture evidence contributes only reviewed aliases
        # and canonical IDs; no provider ID is invented from a match ID.
        for raw in loaded["current_identity_evidence"].get("matches", []) or []:
            if not isinstance(raw, Mapping) or not _verified(raw):
                continue
            competition_id = raw.get("competition_id")
            for side in ("home", "away"):
                row = self._ensure(
                    teams,
                    raw.get(f"{side}_team_id"),
                    competition_id=competition_id,
                    country=raw.get("country") or coverage.get(_text(competition_id), {}).get("country"),
                    canonical_name=raw.get(side),
                    source_name=raw.get(side),
                    source_ref=_path_text(self.paths["current_identity_evidence"]),
                )
                if row:
                    row["reviewed_aliases"].add(_text(raw.get(side)))

        # Promote a reviewed alias group only when one alias normalizes exactly
        # to one historical canonical target in one competition.  Every other
        # group remains a backlog item for review.
        alias_backlog: list[dict[str, Any]] = []
        linked_alias_groups = 0
        reviewed_aliases = loaded["reviewed_alias_registry"].get("teams", []) or []
        for group in reviewed_aliases:
            if not isinstance(group, Mapping):
                continue
            names = _unique([group.get("canonical"), *list(group.get("aliases") or [])])
            hits: set[tuple[str, str, str]] = set()
            for name in names:
                normalized = normalize_identity_name(name)
                for (competition_id, history_name), team_ids in history_names.items():
                    if normalized and normalized == history_name:
                        for team_id in team_ids:
                            hits.add((competition_id, team_id, name))
            targets = sorted({(competition_id, team_id) for competition_id, team_id, _ in hits})
            if len(targets) != 1 or not _text(group.get("evidence")):
                alias_backlog.append({
                    "canonical": _text(group.get("canonical")),
                    "aliases": names,
                    "evidence": _text(group.get("evidence")) or None,
                    "status": "AMBIGUOUS" if len(targets) > 1 else "UNRESOLVED",
                    "candidate_targets": [{"competition_id": c, "canonical_team_id": t} for c, t in targets],
                })
                continue
            competition_id, team_id = targets[0]
            row = self._ensure(
                teams,
                team_id,
                competition_id=competition_id,
                country=coverage.get(competition_id, {}).get("country"),
                source_ref=_path_text(self.paths["reviewed_alias_registry"]),
            )
            if row:
                row["reviewed_aliases"].update(names)
                row["evidence_sources"].add(_text(group.get("evidence")))
                linked_alias_groups += 1

        serialized_teams: list[dict[str, Any]] = []
        for team_id in sorted(teams):
            row = teams[team_id]
            mappings = []
            for mapping in row["provider_mappings"].values():
                mapping["reviewed_aliases"] = _unique(mapping.get("reviewed_aliases", []))
                mapping["source_refs"] = _unique(mapping.get("source_refs", []))
                mappings.append(mapping)
            serialized_teams.append({
                "canonical_team_id": team_id,
                "canonical_name": row["canonical_name"],
                "competition_scope": sorted(row["competition_scope"]),
                "country": sorted(row["country"])[0] if row["country"] else None,
                "canonical_source_names": sorted(row["canonical_source_names"]),
                "reviewed_aliases": sorted(row["reviewed_aliases"]),
                "provider_mappings": sorted(mappings, key=lambda item: (
                    _text(item.get("provider")),
                    _text(item.get("provider_team_id")),
                    _text(item.get("provider_exact_name")),
                )),
                "evidence_sources": sorted(row["evidence_sources"]),
            })

        registry: dict[str, Any] = {
            "contract_version": IDENTITY_REGISTRY_CONTRACT_VERSION,
            "generated_at": self.now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "builder": "IdentityRegistryBuilder.v1",
            "generation_method": "deterministic_existing_evidence_only",
            "normalization": {
                "form": "NFKC",
                "case": "casefold",
                "retained_characters": "Unicode alphanumeric only",
                "fuzzy_matching": False,
                "transliteration": False,
                "kickoff_proximity": False,
            },
            "resolution_ladder": list(RESOLUTION_LADDER),
            "source_inputs": self._source_inputs(loaded),
            "teams": serialized_teams,
            "ambiguities": alias_backlog,
            "summary": {
                "canonical_team_count": len(serialized_teams),
                "provider_mapping_count": sum(len(row["provider_mappings"]) for row in serialized_teams),
                "stable_provider_id_mapping_count": sum(
                    bool(mapping.get("provider_team_id"))
                    for row in serialized_teams
                    for mapping in row["provider_mappings"]
                ),
                "reviewed_alias_group_count": len(reviewed_aliases),
                "linked_reviewed_alias_group_count": linked_alias_groups,
                "alias_backlog_count": len(alias_backlog),
                "ambiguous_alias_backlog_count": sum(item["status"] == "AMBIGUOUS" for item in alias_backlog),
            },
        }
        registry["registry_digest"] = content_sha256(registry)
        return registry


def write_identity_registry(registry: Mapping[str, Any], path: str | Path = DEFAULT_IDENTITY_REGISTRY_PATH) -> Path:
    validate_identity_registry(registry)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def validate_identity_registry(registry: Mapping[str, Any]) -> None:
    """Validate the stable fields consumed by the daily resolver."""

    if registry.get("contract_version") != IDENTITY_REGISTRY_CONTRACT_VERSION:
        raise ValueError("unexpected identity registry contract version")
    if list(registry.get("resolution_ladder") or []) != list(RESOLUTION_LADDER):
        raise ValueError("identity registry resolution ladder changed")
    teams = registry.get("teams")
    if not isinstance(teams, list):
        raise ValueError("identity registry teams must be a list")
    seen: set[str] = set()
    required = {
        "canonical_team_id",
        "canonical_name",
        "competition_scope",
        "country",
        "reviewed_aliases",
        "provider_mappings",
    }
    for team in teams:
        if not isinstance(team, Mapping) or not required.issubset(team):
            raise ValueError("identity registry team row is missing required fields")
        team_id = _text(team.get("canonical_team_id"))
        if not _valid_team_id(team_id) or team_id in seen:
            raise ValueError("identity registry canonical team IDs must be unique team IDs")
        seen.add(team_id)
        if not isinstance(team.get("provider_mappings"), list):
            raise ValueError("identity registry provider mappings must be a list")
        for mapping in team.get("provider_mappings", []):
            if not isinstance(mapping, Mapping) or mapping.get("verified") is not True:
                raise ValueError("identity registry contains an unverified provider mapping")
            if not _text(mapping.get("provider")) or not (_text(mapping.get("provider_team_id")) or _text(mapping.get("provider_exact_name"))):
                raise ValueError("identity registry provider mapping requires provider and exact identity")


__all__ = [
    "DEFAULT_IDENTITY_REGISTRY_PATH",
    "IDENTITY_REGISTRY_CONTRACT_VERSION",
    "IDENTITY_STATUSES",
    "IdentityRegistryBuilder",
    "IdentityRegistryResolver",
    "RESOLUTION_LADDER",
    "normalize_identity_name",
    "validate_identity_registry",
    "write_identity_registry",
]
