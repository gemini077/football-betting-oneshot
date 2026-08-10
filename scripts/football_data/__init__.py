"""Versioned football data foundation primitives.

This package is intentionally outside the Champion's deterministic input path.
"""

from .contracts import ContractError, validate_record
from .competition_resolution import CompetitionEntityResolver
from .historical_results import HistoricalResultLedger, deduplicate_historical_results, make_historical_match_result
from .player_identity import PlayerIdentityResolver
from .storage import SnapshotStore, content_sha256
from .team_strength import PreMatchSnapshotStore, TeamStrengthBuilder
from .providers.openfootball import OpenFootballHistoricalAdapter

__all__ = [
    "CompetitionEntityResolver",
    "ContractError",
    "HistoricalResultLedger",
    "OpenFootballHistoricalAdapter",
    "PlayerIdentityResolver",
    "PreMatchSnapshotStore",
    "SnapshotStore",
    "TeamStrengthBuilder",
    "content_sha256",
    "deduplicate_historical_results",
    "make_historical_match_result",
    "validate_record",
]
