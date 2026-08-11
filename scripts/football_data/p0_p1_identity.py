"""Conservative P0/P1 team identity candidate population.

This module joins already captured result evidence from different providers. It
does not scrape, fetch, or mutate the production identity registry. A provider
name becomes ``AUTO_VERIFIED`` only when a unique cross-source fixture graph
repeats the relationship across several matches and opponents.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


GENERIC_TEAM_KEYS = frozenset({"united", "city", "racing", "sporting", "national", "central"})
REVIEWED_CROSS_SOURCE_METHOD = "cross_source_context_verified"

# These are structural club markers, not identity evidence. They are removed
# only for cross-source alignment and never written back as aliases by this
# builder. Country/competition context remains mandatory for the graph.
_STRUCTURAL_TOKENS = frozenset(
    {
        "ac",
        "af",
        "bk",
        "ca",
        "cd",
        "cf",
        "clube",
        "club",
        "cr",
        "ec",
        "fc",
        "ff",
        "fk",
        "fbc",
        "fbpa",
        "fotball",
        "football",
        "fr",
        "if",
        "ifk",
        "il",
        "sc",
        "se",
        "sk",
    }
)
_REGION_TOKENS = frozenset({"ba", "mg", "pr", "rj", "rs", "sc", "sp"})


@dataclass(frozen=True)
class SourceMatchObservation:
    """One raw result observation before canonical entity resolution."""

    provider: str
    competition_id: str
    season_id: str
    country: str
    kickoff_at: str
    home_name: str
    away_name: str
    home_goals: int
    away_goals: int
    source_ref: str = ""
    home_provider_team_id: str | None = None
    away_provider_team_id: str | None = None
    match_type: str = "league"

    def teams(self) -> tuple[tuple[str, str | None], tuple[str, str | None]]:
        return (
            (self.home_name, self.home_provider_team_id),
            (self.away_name, self.away_provider_team_id),
        )


def normalize_source_team_name(value: str) -> str:
    """Return a cautious comparison key for source-name alignment."""

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    while tokens and tokens[-1] in _REGION_TOKENS:
        tokens.pop()
    tokens = [token for token in tokens if token not in _STRUCTURAL_TOKENS]
    return " ".join(tokens)


def _unsafe_generic(value: str) -> bool:
    return normalize_source_team_name(value) in GENERIC_TEAM_KEYS or str(value or "").strip().casefold() in GENERIC_TEAM_KEYS


def _slug(value: str) -> str:
    key = normalize_source_team_name(value)
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "unresolved"


def _date_key(value: str) -> str:
    return str(value or "").strip()[:10]


def _node(provider: str, name: str) -> tuple[str, str]:
    return (str(provider), str(name).strip())


def _fingerprint(row: SourceMatchObservation) -> tuple[str, str, str, int, int]:
    return (
        row.competition_id,
        row.season_id,
        _date_key(row.kickoff_at),
        int(row.home_goals),
        int(row.away_goals),
    )


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def add(self, value: tuple[str, str]) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: tuple[str, str]) -> tuple[str, str]:
        parent = self.parent.setdefault(value, value)
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


class P0P1TeamIdentityCandidateBuilder:
    """Build auditable team candidates from repeated source-to-source matches."""

    def __init__(self, *, min_confirmations: int = 3, min_distinct_opponents: int = 2) -> None:
        if min_confirmations < 1 or min_distinct_opponents < 1:
            raise ValueError("identity confirmation thresholds must be positive")
        self.min_confirmations = min_confirmations
        self.min_distinct_opponents = min_distinct_opponents

    @staticmethod
    def _candidate_id(country: str, canonical_name: str) -> str:
        return f"team:{_slug(country)}:{_slug(canonical_name)}"

    @staticmethod
    def _seed_lookup(seeds: Iterable[Mapping[str, Any]] | None) -> dict[str, tuple[str, str]]:
        lookup: dict[str, tuple[str, str]] = {}
        for seed in seeds or []:
            canonical_id = str(seed.get("canonical_team_id") or "").strip()
            canonical_name = str(seed.get("canonical_name") or "").strip()
            if not canonical_id or not canonical_name:
                continue
            for value in [canonical_name, *(seed.get("aliases") or [])]:
                key = normalize_source_team_name(str(value))
                if key:
                    lookup[key] = (canonical_id, canonical_name)
        return lookup

    @staticmethod
    def _compatible_pair(left: str, right: str) -> bool:
        left_key = normalize_source_team_name(left)
        right_key = normalize_source_team_name(right)
        if not left_key or not right_key:
            return False
        if left_key == right_key:
            return True
        # A single non-generic identity token may be qualified by a provider
        # (for example "Sport Lisboa e Benfica" versus "Benfica"). This is
        # only a graph edge; it is never sufficient for verification by itself.
        if left_key in GENERIC_TEAM_KEYS or right_key in GENERIC_TEAM_KEYS:
            return False
        left_tokens = set(left_key.split())
        right_tokens = set(right_key.split())
        if len(left_tokens) == 1 and left_key in right_tokens:
            return True
        if len(right_tokens) == 1 and right_key in left_tokens:
            return True
        return False

    def _align_pairs(self, rows: list[SourceMatchObservation]) -> list[tuple[SourceMatchObservation, SourceMatchObservation]]:
        groups: dict[tuple[str, str, str, int, int], list[SourceMatchObservation]] = defaultdict(list)
        for row in rows:
            groups[_fingerprint(row)].append(row)

        pairs: list[tuple[SourceMatchObservation, SourceMatchObservation]] = []
        for group in groups.values():
            providers = sorted({row.provider for row in group})
            for index, left_provider in enumerate(providers):
                for right_provider in providers[index + 1 :]:
                    left_rows = [row for row in group if row.provider == left_provider]
                    right_rows = [row for row in group if row.provider == right_provider]
                    possible: list[tuple[SourceMatchObservation, SourceMatchObservation]] = []
                    for left in left_rows:
                        for right in right_rows:
                            if self._compatible_pair(left.home_name, right.home_name) and self._compatible_pair(left.away_name, right.away_name):
                                possible.append((left, right))
                    if not possible and len(left_rows) == len(right_rows) == 1:
                        # Unique date/score fixture identity is acceptable even
                        # when provider naming differs completely. The repeated
                        # graph threshold still has to pass later.
                        possible = [(left_rows[0], right_rows[0])]
                    if len(possible) == 1:
                        pairs.append(possible[0])
        return pairs

    def build(
        self,
        observations: Iterable[SourceMatchObservation],
        *,
        canonical_name_provider: str = "openfootball",
        canonical_seeds: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        rows = list(observations)
        union = _UnionFind()
        node_rows: dict[tuple[str, str], list[SourceMatchObservation]] = defaultdict(list)
        for row in rows:
            for name, _provider_id in row.teams():
                node = _node(row.provider, name)
                union.add(node)
                node_rows[node].append(row)

        aligned = self._align_pairs(rows)
        aligned_by_node: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for left, right in aligned:
            for left_name, left_id in left.teams():
                for right_name, right_id in right.teams():
                    if (left_name == left.home_name) == (right_name == right.home_name):
                        union.union(_node(left.provider, left_name), _node(right.provider, right_name))
                        aligned_by_node[_node(left.provider, left_name)].append(
                            {
                                "left_provider": left.provider,
                                "left_name": left_name,
                                "left_provider_team_id": left_id,
                                "right_provider": right.provider,
                                "right_name": right_name,
                                "right_provider_team_id": right_id,
                                "kickoff_at": left.kickoff_at,
                                "home_goals": left.home_goals,
                                "away_goals": left.away_goals,
                                "left_source_ref": left.source_ref,
                                "right_source_ref": right.source_ref,
                            }
                        )
                        aligned_by_node[_node(right.provider, right_name)].append(
                            {
                                "left_provider": left.provider,
                                "left_name": left_name,
                                "left_provider_team_id": left_id,
                                "right_provider": right.provider,
                                "right_name": right_name,
                                "right_provider_team_id": right_id,
                                "kickoff_at": right.kickoff_at,
                                "home_goals": right.home_goals,
                                "away_goals": right.away_goals,
                                "left_source_ref": left.source_ref,
                                "right_source_ref": right.source_ref,
                            }
                        )

        components: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for node in node_rows:
            components[union.find(node)].append(node)
        seed_lookup = self._seed_lookup(canonical_seeds)
        candidates: list[dict[str, Any]] = []
        for root, nodes in sorted(components.items(), key=lambda item: str(item[0])):
            provider_names = defaultdict(list)
            for provider, name in nodes:
                provider_names[provider].append(name)
            canonical_names = provider_names.get(canonical_name_provider, [])
            canonical_name = sorted(canonical_names)[0] if canonical_names else None
            if canonical_name is None and nodes:
                canonical_name = sorted(name for _provider, name in nodes)[0]
            country = next((row.country for node in nodes for row in node_rows[node]), "")
            seed = seed_lookup.get(normalize_source_team_name(canonical_name or ""))
            canonical_id = seed[0] if seed else self._candidate_id(country, canonical_name or "") if canonical_name else None
            selected_provider_count = len(provider_names)
            component_conflict = any(len(set(names)) > 1 for names in provider_names.values())
            component_evidence = [evidence for node in nodes for evidence in aligned_by_node.get(node, [])]
            distinct_fixture_keys = {
                (_date_key(str(item.get("kickoff_at"))), int(item.get("home_goals", -1)), int(item.get("away_goals", -1)))
                for item in component_evidence
            }
            for provider, name in sorted(nodes):
                node = (provider, name)
                evidence_rows = aligned_by_node.get(node, [])
                opponent_keys = set()
                for raw in node_rows[node]:
                    own_is_home = raw.home_name == name
                    opponent = raw.away_name if own_is_home else raw.home_name
                    opponent_keys.add(normalize_source_team_name(opponent))
                aligned_match_count = len({
                    (str(item.get("kickoff_at"))[:10], item.get("home_goals"), item.get("away_goals"), item.get("left_source_ref"), item.get("right_source_ref"))
                    for item in evidence_rows
                })
                generic = _unsafe_generic(name) or _unsafe_generic(canonical_name or "")
                if generic:
                    status = "UNRESOLVED"
                elif component_conflict:
                    status = "CONFLICT"
                elif selected_provider_count < 2 or not evidence_rows:
                    status = "UNRESOLVED"
                elif aligned_match_count >= self.min_confirmations and len(opponent_keys) >= self.min_distinct_opponents:
                    status = "AUTO_VERIFIED"
                else:
                    status = "REVIEW_REQUIRED"
                row = next((item for item in node_rows[node]), None)
                provider_team_id = None
                if row is not None:
                    for observed_name, observed_id in row.teams():
                        if observed_name == name:
                            provider_team_id = observed_id
                            break
                candidates.append(
                    {
                        "status": status,
                        "verified": status == "AUTO_VERIFIED",
                        "provider": provider,
                        "provider_team_id": provider_team_id,
                        "provider_team_name": name,
                        "canonical_team_id": canonical_id if status != "UNRESOLVED" else None,
                        "canonical_name": canonical_name if status != "UNRESOLVED" else None,
                        "country": country,
                        "competition_id": row.competition_id if row else None,
                        "season_id": row.season_id if row else None,
                        "confidence": 1.0 if status == "AUTO_VERIFIED" else None,
                        "resolution_method": REVIEWED_CROSS_SOURCE_METHOD if status == "AUTO_VERIFIED" else "unresolved",
                        "verification_method": REVIEWED_CROSS_SOURCE_METHOD if status == "AUTO_VERIFIED" else status.casefold(),
                        "evidence": {
                            "aligned_match_count": aligned_match_count,
                            "distinct_opponent_count": len(opponent_keys),
                            "distinct_fixture_count": len(distinct_fixture_keys),
                            "source_providers": sorted(provider_names),
                            "aligned_fixtures": evidence_rows[:20],
                        },
                        "conflicts": ["multiple provider names in one source component"] if component_conflict else [],
                    }
                )
        summary = {status: sum(row["status"] == status for row in candidates) for status in ("AUTO_VERIFIED", "REVIEW_REQUIRED", "UNRESOLVED", "CONFLICT")}
        return {"candidates": candidates, "summary": summary, "aligned_fixture_count": len(aligned)}


def reviewed_mappings(result: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Return only auto-verified candidates for provider adapters."""

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for row in result.get("candidates", []):
        if row.get("status") != "AUTO_VERIFIED" or row.get("verified") is not True:
            continue
        output[(str(row["provider"]), str(row["provider_team_name"]))] = dict(row)
    return output


__all__ = [
    "P0P1TeamIdentityCandidateBuilder",
    "SourceMatchObservation",
    "normalize_source_team_name",
    "reviewed_mappings",
]
