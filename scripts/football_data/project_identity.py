"""Conservative project-provider to canonical team identity resolution.

The historical result providers and the project schedule providers are two
different identity surfaces.  This module joins them only through reviewed,
competition-scoped evidence.  It deliberately does not use edit distance,
embeddings, or language-model suggestions as confirmation material.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Mapping

from .entity_resolution import ResolutionResult
from .p0_p1_identity import normalize_source_team_name


PROJECT_RESOLUTION_METHOD = "project_provider_context_verified"
REVIEWED_METHODS = frozenset(
    {
        "manual_verified",
        "provider_id_exact",
        "existing_crosswalk",
        "exact_alias",
        "cross_source_context_verified",
        PROJECT_RESOLUTION_METHOD,
        "project_alias_context_verified",
    }
)
GENERIC_TEAM_KEYS = frozenset({"united", "city", "racing", "sporting", "national", "central"})


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _name_key(value: Any) -> str:
    """Normalize Latin and CJK provider names without collapsing CJK names."""

    text = _clean(value)
    latin_key = normalize_source_team_name(text)
    if latin_key:
        return latin_key
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", normalized)


def _context_key(competition_id: Any, country: Any) -> tuple[str, str]:
    return (_clean(competition_id), _clean(country).casefold())


def _is_generic(value: Any) -> bool:
    return _name_key(value) in GENERIC_TEAM_KEYS


def _reviewed(row: Mapping[str, Any]) -> bool:
    return row.get("verified") is True and row.get("resolution_method") in REVIEWED_METHODS


@dataclass(frozen=True)
class ProjectFixtureObservation:
    """One project fixture-side observation used to build identity evidence."""

    target_match_id: str
    provider: str
    provider_match_id: str
    competition_id: str
    country: str
    kickoff_at: str
    side: str
    provider_team_name: str
    provider_team_id: str | None = None
    translated_team_name: str | None = None
    translation_status: str | None = None
    source_ref: str | None = None
    opponent_name: str | None = None


def _canonical_catalog(canonical_mappings: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], set[tuple[str, str]]]:
    """Index reviewed source identities by exact normalized name and context."""

    catalog: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for row in canonical_mappings:
        if not _reviewed(row):
            continue
        team_id = _clean(row.get("canonical_team_id"))
        canonical_name = _clean(row.get("canonical_name"))
        competition_id = _clean(row.get("competition") or row.get("competition_id"))
        country = _clean(row.get("country"))
        if not team_id or not competition_id:
            continue
        names = {_clean(row.get("provider_team_name")), canonical_name}
        names.update(_clean(alias) for alias in row.get("aliases") or [])
        for name in names:
            key = _name_key(name)
            if key:
                catalog[(*_context_key(competition_id, country), key)].add((team_id, canonical_name))
    return catalog


def _alias_catalog(
    project_alias_rows: Iterable[Mapping[str, Any]],
    canonical_catalog: Mapping[tuple[str, str, str], set[tuple[str, str]]],
) -> dict[str, list[dict[str, Any]]]:
    """Index reviewed alias groups against every exact source-name match.

    A project alias row is one reviewed group, not a collection of unrelated
    one-name mappings.  Every name in a group therefore receives the complete
    exact-match candidate set, while the source competition/country context is
    retained for the later observation-specific safety gate.
    """

    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_source_rows: list[dict[str, Any]] = []
    for (competition_id, country, name), candidates in canonical_catalog.items():
        for candidate in candidates:
            all_source_rows.append(
                {
                    "competition_id": competition_id,
                    "country": country,
                    "source_name_key": name,
                    "canonical_team_id": candidate[0],
                    "canonical_name": candidate[1],
                }
            )
    for row_index, row in enumerate(project_alias_rows):
        evidence = str(row.get("evidence") or "").strip()
        if not evidence:
            continue
        names = {_clean(row.get("canonical"))}
        names.update(_clean(alias) for alias in row.get("aliases") or [])
        names.discard("")
        name_keys = {_name_key(name) for name in names if _name_key(name)}
        if not name_keys:
            continue

        group_key = ":".join(
            (
                "reviewed_alias",
                _name_key(row.get("canonical")) or f"row-{row_index}",
                _name_key(evidence),
            )
        )
        matched_source_rows = [
            source_row
            for source_row in all_source_rows
            if source_row["source_name_key"] in name_keys
        ]
        matched_alias_names = sorted(
            {
                name
                for name in names
                if _name_key(name)
                and any(
                    source_row["source_name_key"] == _name_key(name)
                    for source_row in matched_source_rows
                )
            }
        )
        group_records = [
            {
                "group_key": group_key,
                "evidence": evidence,
                "group_names": sorted(names),
                "matched_alias_names": matched_alias_names,
                **source_row,
            }
            for source_row in matched_source_rows
        ]
        if not group_records:
            group_records = [
                {
                    "group_key": group_key,
                    "evidence": evidence,
                    "group_names": sorted(names),
                    "matched_alias_names": [],
                    "competition_id": "",
                    "country": "",
                    "source_name_key": "",
                    "canonical_team_id": None,
                    "canonical_name": None,
                }
            ]
        # The complete group candidate set is deliberately attached to every
        # group name.  This is what lets a reviewed Chinese/project spelling
        # inherit the source candidate found through an English alias.
        for alias_key in name_keys:
            output[alias_key].extend(group_records)
    return output


def _alias_context_matches(
    record: Mapping[str, Any],
    context: tuple[str, str],
) -> bool:
    """Keep alias evidence inside the observation's competition/country."""

    competition_id, country = context
    if not competition_id or record.get("competition_id") != competition_id:
        return False
    record_country = _clean(record.get("country")).casefold()
    return not country or not record_country or record_country == country


def _candidate_names(
    observation: ProjectFixtureObservation,
    aliases: Mapping[str, list[dict[str, Any]]],
    catalog: Mapping[tuple[str, str, str], set[tuple[str, str]]],
) -> tuple[set[tuple[str, str]], list[str], dict[str, Any]]:
    """Return exact candidates plus the evidence kinds that produced them."""

    candidates: set[tuple[str, str]] = set()
    evidence_kinds: list[str] = []
    alias_diagnostics: dict[str, Any] = {
        "reviewed_alias_group_used": False,
        "reviewed_alias_group_keys": set(),
        "matched_alias_names": set(),
        "candidate_canonical_team_ids_before_context": set(),
        "candidate_canonical_team_ids_after_context": set(),
    }
    context = _context_key(observation.competition_id, observation.country)

    translated = _clean(observation.translated_team_name)
    if translated and observation.translation_status == "EXACT_MATCH":
        candidates.update(catalog.get((*context, _name_key(translated)), set()))
        if candidates:
            evidence_kinds.append("exact_translation")

    project_name_key = _name_key(observation.provider_team_name)
    alias_records = aliases.get(project_name_key, [])
    if alias_records:
        alias_diagnostics["reviewed_alias_group_used"] = True
        for record in alias_records:
            alias_diagnostics["reviewed_alias_group_keys"].add(record["group_key"])
            alias_diagnostics["matched_alias_names"].update(record["matched_alias_names"])
            team_id = _clean(record.get("canonical_team_id"))
            canonical_name = _clean(record.get("canonical_name"))
            if not team_id:
                continue
            candidate = (team_id, canonical_name)
            alias_diagnostics["candidate_canonical_team_ids_before_context"].add(team_id)
            if _alias_context_matches(record, context):
                alias_diagnostics["candidate_canonical_team_ids_after_context"].add(team_id)
                candidates.add(candidate)
        if alias_diagnostics["candidate_canonical_team_ids_after_context"]:
            evidence_kinds.append("reviewed_project_alias")

    return candidates, evidence_kinds, alias_diagnostics


def _mapping_key(observation: ProjectFixtureObservation) -> tuple[str, str, str, str]:
    return (
        observation.provider,
        _clean(observation.provider_team_id),
        _name_key(observation.provider_team_name),
        observation.competition_id,
    )


class ProjectProviderIdentityCandidateBuilder:
    """Build compactly verifiable project-provider identity candidates."""

    def __init__(
        self,
        *,
        canonical_mappings: Iterable[Mapping[str, Any]],
        project_alias_rows: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self.canonical_catalog = _canonical_catalog(canonical_mappings)
        self.alias_catalog = _alias_catalog(project_alias_rows, self.canonical_catalog)

    def build(self, observations: Iterable[ProjectFixtureObservation]) -> dict[str, Any]:
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            candidates, evidence_kinds, alias_diagnostics = _candidate_names(
                observation,
                self.alias_catalog,
                self.canonical_catalog,
            )
            grouped[_mapping_key(observation)].append(
                {
                    "observation": observation,
                    "candidate_ids": candidates,
                    "evidence_kinds": evidence_kinds,
                    "alias_diagnostics": alias_diagnostics,
                }
            )

        candidates_output: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []
        for key, entries in sorted(grouped.items()):
            provider, provider_team_id, provider_name_key, competition_id = key
            first = entries[0]["observation"]
            candidate_ids = set().union(*(entry["candidate_ids"] for entry in entries))
            candidate_ids.discard(("", ""))
            evidence_kinds = sorted({kind for entry in entries for kind in entry["evidence_kinds"]})
            fixture_ids = sorted({entry["observation"].target_match_id for entry in entries})
            source_refs = sorted({
                _clean(entry["observation"].source_ref)
                for entry in entries
                if _clean(entry["observation"].source_ref)
            })
            opposing_names = sorted({
                _clean(entry["observation"].opponent_name)
                for entry in entries
                if _clean(entry["observation"].opponent_name)
            })
            alias_diagnostics = {
                "reviewed_alias_group_used": any(
                    entry["alias_diagnostics"]["reviewed_alias_group_used"]
                    for entry in entries
                ),
                "reviewed_alias_group_keys": set().union(
                    *(
                        entry["alias_diagnostics"]["reviewed_alias_group_keys"]
                        for entry in entries
                    )
                ),
                "matched_alias_names": set().union(
                    *(
                        entry["alias_diagnostics"]["matched_alias_names"]
                        for entry in entries
                    )
                ),
                "candidate_canonical_team_ids_before_context": set().union(
                    *(
                        entry["alias_diagnostics"]["candidate_canonical_team_ids_before_context"]
                        for entry in entries
                    )
                ),
                "candidate_canonical_team_ids_after_context": set().union(
                    *(
                        entry["alias_diagnostics"]["candidate_canonical_team_ids_after_context"]
                        for entry in entries
                    )
                ),
            }
            if _is_generic(first.provider_team_name):
                status = "UNRESOLVED"
                reason = ["generic_provider_team_name"]
            elif len(candidate_ids) > 1:
                status = "CONFLICT"
                reason = ["multiple_unique_canonical_candidates"]
            elif not candidate_ids:
                status = "UNRESOLVED"
                if alias_diagnostics["reviewed_alias_group_used"]:
                    if alias_diagnostics["candidate_canonical_team_ids_before_context"]:
                        reason = ["reviewed_alias_group_context_mismatch"]
                    else:
                        reason = ["reviewed_alias_group_source_candidate_missing"]
                else:
                    reason = ["no_exact_reviewed_canonical_candidate"]
            elif len(fixture_ids) < 2 and not any(
                entry["observation"].provider_team_id for entry in entries
            ):
                status = "REVIEW_REQUIRED"
                reason = ["single_fixture_without_reviewed_provider_id"]
            elif not evidence_kinds:
                status = "REVIEW_REQUIRED"
                reason = ["candidate_without_reviewed_project_evidence"]
            else:
                status = "AUTO_VERIFIED"
                reason = ["exact_translation_or_reviewed_alias_with_competition_context"]

            selected = next(iter(candidate_ids), (None, None))
            resolved_method = (
                "project_alias_context_verified"
                if "reviewed_project_alias" in evidence_kinds
                else PROJECT_RESOLUTION_METHOD
            )
            evidence = {
                "evidence_kinds": evidence_kinds,
                "fixture_ids": fixture_ids,
                "supporting_fixture_count": len(fixture_ids),
                "opponent_names": opposing_names,
                "source_refs": source_refs,
                "provider_match_ids": sorted({
                    entry["observation"].provider_match_id
                    for entry in entries
                    if entry["observation"].provider_match_id
                }),
                "translation_names": sorted({
                    _clean(entry["observation"].translated_team_name)
                    for entry in entries
                    if _clean(entry["observation"].translated_team_name)
                }),
                "unique_canonical_candidate": len(candidate_ids) == 1,
                "reviewed_alias_group_used": alias_diagnostics["reviewed_alias_group_used"],
                "reviewed_alias_group_keys": sorted(alias_diagnostics["reviewed_alias_group_keys"]),
                "matched_alias_names": sorted(alias_diagnostics["matched_alias_names"]),
                "candidate_canonical_team_ids_before_context": sorted(
                    alias_diagnostics["candidate_canonical_team_ids_before_context"]
                ),
                "candidate_canonical_team_ids_after_context": sorted(
                    alias_diagnostics["candidate_canonical_team_ids_after_context"]
                ),
            }
            row = {
                "status": status,
                "verified": status == "AUTO_VERIFIED",
                "provider": provider,
                "provider_team_id": provider_team_id or None,
                "provider_team_name": first.provider_team_name,
                "canonical_team_id": selected[0] if status == "AUTO_VERIFIED" else None,
                "canonical_name": selected[1] if status == "AUTO_VERIFIED" else None,
                "competition_id": competition_id,
                "country": first.country,
                "confidence": 1.0 if status == "AUTO_VERIFIED" else None,
                "resolution_method": resolved_method if status == "AUTO_VERIFIED" else "unresolved",
                "verification_method": resolved_method if status == "AUTO_VERIFIED" else status.casefold(),
                "evidence": evidence,
                "conflicts": reason if status == "CONFLICT" else [],
                "reason": reason,
            }
            candidates_output.append(row)
            if status == "AUTO_VERIFIED":
                mappings.append(row)

        summary = {
            status: sum(row["status"] == status for row in candidates_output)
            for status in ("AUTO_VERIFIED", "REVIEW_REQUIRED", "UNRESOLVED", "CONFLICT")
        }
        summary["reviewed_alias_groups_used"] = len({
            group_key
            for row in candidates_output
            for group_key in row["evidence"].get("reviewed_alias_group_keys", [])
        })
        summary["alias_derived_verified_mapping_count"] = sum(
            row["status"] == "AUTO_VERIFIED"
            and "reviewed_project_alias" in row["evidence"].get("evidence_kinds", [])
            for row in candidates_output
        )
        return {
            "contract_version": "project_provider_identity.v1",
            "candidates": candidates_output,
            "provider_mappings": mappings,
            "summary": summary,
        }


class ProjectProviderIdentityResolver:
    """Read only verified project mappings through one deterministic API."""

    def __init__(self, mappings: Iterable[Mapping[str, Any]]) -> None:
        self.mappings = [dict(row) for row in mappings if _reviewed(row)]

    @staticmethod
    def _context_matches(row: Mapping[str, Any], competition_id: str | None, country: str | None) -> bool:
        if competition_id and _clean(row.get("competition_id") or row.get("competition")) != _clean(competition_id):
            return False
        row_country = _clean(row.get("country"))
        return not country or not row_country or row_country.casefold() == _clean(country).casefold()

    @staticmethod
    def _result(
        *,
        provider: str,
        provider_team_id: str | None,
        provider_team_name: str | None,
        row: Mapping[str, Any] | None,
        method: str,
        reason: str,
    ) -> ResolutionResult:
        return ResolutionResult(
            canonical_team_id=row.get("canonical_team_id") if row else None,
            canonical_name=row.get("canonical_name") if row else None,
            provider=provider,
            provider_team_id=provider_team_id,
            provider_team_name=provider_team_name,
            resolution_status="resolved" if row else "unresolved",
            resolution_method=method,
            confidence=1.0 if row else None,
            reason=reason,
        )

    def resolve_team(
        self,
        provider: str,
        provider_team_name: str | None,
        provider_team_id: str | None = None,
        *,
        competition_id: str | None = None,
        country: str | None = None,
    ) -> ResolutionResult:
        name = _clean(provider_team_name)
        scoped = [
            row for row in self.mappings
            if row.get("provider") == provider and self._context_matches(row, competition_id, country)
        ]
        if provider_team_id is not None:
            by_id = [row for row in scoped if row.get("provider_team_id") is not None and str(row.get("provider_team_id")) == str(provider_team_id)]
            canonical_ids = {str(row.get("canonical_team_id")) for row in by_id}
            if len(canonical_ids) == 1:
                return self._result(
                    provider=provider,
                    provider_team_id=str(provider_team_id),
                    provider_team_name=name or None,
                    row=by_id[0],
                    method="provider_id_exact",
                    reason="reviewed project provider ID mapping",
                )
            if len(canonical_ids) > 1:
                return self._result(
                    provider=provider,
                    provider_team_id=str(provider_team_id),
                    provider_team_name=name or None,
                    row=None,
                    method="unresolved",
                    reason="reviewed provider ID maps to conflicting canonical teams",
                )

        if not name or _is_generic(name):
            return self._result(
                provider=provider,
                provider_team_id=provider_team_id,
                provider_team_name=name or None,
                row=None,
                method="unresolved",
                reason="generic or missing provider team name requires verified mapping",
            )

        normalized = _name_key(name)
        by_name = [
            row for row in scoped
            if _name_key(row.get("provider_team_name")) == normalized
        ]
        canonical_ids = {str(row.get("canonical_team_id")) for row in by_name}
        if len(canonical_ids) == 1:
            return self._result(
                provider=provider,
                provider_team_id=provider_team_id,
                provider_team_name=name,
                row=by_name[0],
                method=str(by_name[0].get("resolution_method") or PROJECT_RESOLUTION_METHOD),
                reason="reviewed project provider context mapping",
            )
        if len(canonical_ids) > 1:
            return self._result(
                provider=provider,
                provider_team_id=provider_team_id,
                provider_team_name=name,
                row=None,
                method="unresolved",
                reason="project provider name maps to conflicting canonical teams",
            )
        return self._result(
            provider=provider,
            provider_team_id=provider_team_id,
            provider_team_name=name,
            row=None,
            method="unresolved",
                reason="no verified project provider mapping",
        )


def build_project_identity_output(
    *,
    events: Iterable[Mapping[str, Any]],
    translations: Mapping[str, Mapping[str, Any]],
    canonical_mappings: Iterable[Mapping[str, Any]],
    project_alias_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build project mappings and per-target evidence from existing metadata."""

    observations: list[ProjectFixtureObservation] = []
    target_evidence: dict[str, dict[str, Any]] = {}
    for event in events:
        competition = event.get("competition") or {}
        competition_id = _clean(competition.get("canonical_competition_id"))
        country = _clean(competition.get("country"))
        provider_match_id = _clean((event.get("provider_match_ids") or [""])[0])
        provider = "500" if provider_match_id.startswith("500-") else "nowscore" if provider_match_id else "project"
        translation = translations.get(provider_match_id.split("-")[-1]) or translations.get(provider_match_id) or {}
        evidence_sides: dict[str, dict[str, Any]] = {}
        for side, opponent_side in (("home", "away"), ("away", "home")):
            translated = _clean(translation.get(f"{side}_team_en")) or None
            team_id = (
                translation.get(f"{side}_provider_team_id")
                if translation.get("team_id_provider") == provider
                else None
            )
            observation = ProjectFixtureObservation(
                target_match_id=_clean(event.get("canonical_match_id")),
                provider=provider,
                provider_match_id=provider_match_id,
                competition_id=competition_id,
                country=country,
                kickoff_at=_clean(event.get("kickoff_at")),
                side=side,
                provider_team_name=_clean(event.get(side)),
                provider_team_id=_clean(team_id) or None,
                translated_team_name=translated,
                translation_status=_clean(translation.get("resolution_status")) or None,
                source_ref=_clean(translation.get("source_file")) or None,
                opponent_name=_clean(event.get(opponent_side)) or None,
            )
            observations.append(observation)
            # A 500 schedule may be bound to a Nowscore analysis capture.  The
            # two IDs are different provider namespaces; retain the Nowscore
            # team-ID evidence as a separate mapping instead of pretending it
            # is a 500 team ID.
            if translation.get("team_id_provider") == "nowscore" and translation.get(f"{side}_provider_team_id") is not None and translated:
                observations.append(
                    ProjectFixtureObservation(
                        target_match_id=_clean(event.get("canonical_match_id")),
                        provider="nowscore",
                        provider_match_id=_clean(translation.get("source_match_id")) or provider_match_id,
                        competition_id=competition_id,
                        country=country,
                        kickoff_at=_clean(event.get("kickoff_at")),
                        side=side,
                        provider_team_name=translated,
                        provider_team_id=_clean(translation.get(f"{side}_provider_team_id")) or None,
                        translated_team_name=translated,
                        translation_status="EXACT_MATCH",
                        source_ref=_clean(translation.get("source_file")) or None,
                        opponent_name=_clean(event.get(opponent_side)) or None,
                    )
                )
            evidence_sides[side] = {
                "provider": provider,
                "provider_team_id": observation.provider_team_id,
                "provider_team_name": observation.provider_team_name,
                "translated_team_name": translated,
                "translation_status": observation.translation_status,
                "source_ref": observation.source_ref,
                "resolution_status": "unresolved",
                "resolution_method": "unresolved",
                "reason": ["no_reviewed_project_identity_evidence"],
                "canonical_team_id": None,
            }
        target_evidence[_clean(event.get("canonical_match_id"))] = {
            "target_match_id": _clean(event.get("canonical_match_id")),
            "competition": competition_id,
            "project_home": event.get("home"),
            "project_away": event.get("away"),
            "provider": provider,
            "provider_match_id": provider_match_id or None,
            "kickoff_at": event.get("kickoff_at"),
            "home": evidence_sides["home"],
            "away": evidence_sides["away"],
        }

    builder = ProjectProviderIdentityCandidateBuilder(
        canonical_mappings=canonical_mappings,
        project_alias_rows=project_alias_rows,
    )
    output = builder.build(observations)
    resolver = ProjectProviderIdentityResolver(output["provider_mappings"])
    for target in target_evidence.values():
        for side in ("home", "away"):
            row = target[side]
            result = resolver.resolve_team(
                row["provider"],
                row["provider_team_name"],
                row.get("provider_team_id"),
                competition_id=target["competition"],
            )
            cross_provider_result = None
            if (
                result.canonical_team_id is None
                and target["provider"] == "500"
                and row.get("translated_team_name")
                and row.get("provider_team_id") is None
            ):
                # A 500 fixture may be backed by an exact Nowscore capture.
                # The Nowscore team ID remains in the Nowscore namespace; it
                # is used only as independently reviewed context for the 500
                # fixture and is never copied into a 500 mapping.
                source_id = None
                for observation in observations:
                    if (
                        observation.target_match_id == target["target_match_id"]
                        and observation.side == side
                        and observation.provider == "nowscore"
                    ):
                        source_id = observation.provider_team_id
                        break
                if source_id:
                    cross_provider_result = resolver.resolve_team(
                        "nowscore",
                        row.get("translated_team_name"),
                        source_id,
                        competition_id=target["competition"],
                    )
            if cross_provider_result and cross_provider_result.canonical_team_id:
                row.update(
                    {
                        "canonical_team_id": cross_provider_result.canonical_team_id,
                        "canonical_name": cross_provider_result.canonical_name,
                        "resolution_status": "resolved",
                        "resolution_method": "cross_provider_context_verified",
                        "reason": [
                            "reviewed Nowscore team ID bound to exact project fixture translation"
                        ],
                        "cross_provider": {
                            "provider": "nowscore",
                            "provider_team_id": source_id,
                            "provider_team_name": row.get("translated_team_name"),
                            "resolution_method": cross_provider_result.resolution_method,
                        },
                    }
                )
                continue
            row.update(
                {
                    "canonical_team_id": result.canonical_team_id,
                    "canonical_name": result.canonical_name,
                    "resolution_status": result.resolution_status,
                    "resolution_method": result.resolution_method,
                    "reason": [result.reason] if result.reason else [],
                }
            )
    output["target_evidence"] = target_evidence
    output["summary"]["target_count"] = len(target_evidence)
    output["summary"]["resolved_target_count"] = sum(
        bool(row["home"].get("canonical_team_id") and row["away"].get("canonical_team_id"))
        for row in target_evidence.values()
    )
    output["summary"]["unresolved_target_count"] = len(target_evidence) - output["summary"]["resolved_target_count"]
    return output


__all__ = [
    "PROJECT_RESOLUTION_METHOD",
    "ProjectFixtureObservation",
    "ProjectProviderIdentityCandidateBuilder",
    "ProjectProviderIdentityResolver",
    "build_project_identity_output",
]
