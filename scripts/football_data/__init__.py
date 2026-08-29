"""Versioned football data foundation primitives.

This package is intentionally outside the Champion's deterministic input path.
"""

from .contracts import ContractError, validate_record
from .competition_resolution import CompetitionEntityResolver
from .coverage_gate import ExactCoverageIdentityResolver, audit_fixture, audit_fixture_set
from .coverage_registry import CoverageRegistryBuilder, load_coverage_registry, write_coverage_registry
from .identity_registry import IdentityRegistryBuilder, IdentityRegistryResolver, validate_identity_registry, write_identity_registry
from .historical_results import HistoricalResultLedger, deduplicate_historical_results, make_historical_match_result
from .player_identity import PlayerIdentityResolver
from .storage import SnapshotStore, content_sha256
from .team_strength import PreMatchSnapshotStore, TeamStrengthBuilder
from .providers.openfootball import OpenFootballHistoricalAdapter

__all__ = [
    "CompetitionEntityResolver",
    "CoverageRegistryBuilder",
    "ContractError",
    "HistoricalResultLedger",
    "OpenFootballHistoricalAdapter",
    "PlayerIdentityResolver",
    "ExactCoverageIdentityResolver",
    "IdentityRegistryBuilder",
    "IdentityRegistryResolver",
    "PreMatchSnapshotStore",
    "SnapshotStore",
    "TeamStrengthBuilder",
    "audit_fixture",
    "audit_fixture_set",
    "content_sha256",
    "deduplicate_historical_results",
    "make_historical_match_result",
    "load_coverage_registry",
    "validate_record",
    "write_coverage_registry",
    "write_identity_registry",
    "validate_identity_registry",
]
