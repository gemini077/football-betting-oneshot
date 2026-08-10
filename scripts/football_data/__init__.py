"""Versioned football data foundation primitives.

This package is intentionally outside the Champion's deterministic input path.
"""

from .contracts import ContractError, validate_record
from .player_identity import PlayerIdentityResolver
from .storage import SnapshotStore, content_sha256

__all__ = ["ContractError", "PlayerIdentityResolver", "SnapshotStore", "content_sha256", "validate_record"]
