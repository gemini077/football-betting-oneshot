from __future__ import annotations

import pytest

from scripts.football_data.storage import DatasetNotAvailableError, HistoricalResultStore
from scripts.football_data.team_strength import PreMatchSnapshotStore


def test_missing_shared_data_home_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_HOME", str(tmp_path / "missing"))

    with pytest.raises(DatasetNotAvailableError, match="DATASET_NOT_AVAILABLE"):
        HistoricalResultStore().count()
    with pytest.raises(DatasetNotAvailableError, match="DATASET_NOT_AVAILABLE"):
        PreMatchSnapshotStore().store.count()
