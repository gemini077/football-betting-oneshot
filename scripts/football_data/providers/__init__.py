"""Provider adapters behind the Phase 2A football data interface."""

from .base import FootballDataProvider
from .nowscore_500 import Nowscore500SnapshotProvider
from .statsbomb_open import StatsBombOpenDataProvider

__all__ = ["FootballDataProvider", "Nowscore500SnapshotProvider", "StatsBombOpenDataProvider"]
