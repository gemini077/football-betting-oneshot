from __future__ import annotations

import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pme_index_integrity import IndexIntegrityError, assert_index_monotonic


def entry(match: str, pid: str, settled: bool = False) -> dict:
    return {"match_key": match, "prediction_id": pid,
            "settlement_path": f"settlements/{pid}.json" if settled else None}


def index(*rows: dict, latest: dict | None = None, settled_count: int | None = None) -> dict:
    rows = list(rows)
    return {"schema_version": "pure_market_exact_prospective.index.v1",
            "prediction_count": len(rows),
            "settled_prediction_count": sum(bool(r.get("settlement_path")) for r in rows) if settled_count is None else settled_count,
            "latest_by_match": latest if latest is not None else {r["match_key"]: r["prediction_id"] for r in rows},
            "predictions": rows}


def test_identical_index():
    value = index(entry("m1", "p1", True))
    assert_index_monotonic(value, copy.deepcopy(value))


def test_appended_match():
    assert_index_monotonic(index(entry("m1", "p1")), index(entry("m1", "p1"), entry("m2", "p2")))


def test_later_version_can_become_latest_without_losing_prior_id():
    assert_index_monotonic(index(entry("m1", "p1")), index(entry("m1", "p1"), entry("m1", "p2"), latest={"m1": "p2"}))


def test_loss_of_previous_match_fails():
    with pytest.raises(IndexIntegrityError, match="matches 2->1"):
        assert_index_monotonic(index(entry("m1", "p1"), entry("m2", "p2")), index(entry("m1", "p1")))


def test_loss_of_historic_prediction_fails_even_when_match_remains():
    with pytest.raises(IndexIntegrityError, match="prediction:p1"):
        assert_index_monotonic(index(entry("m1", "p1"), entry("m1", "p2"), latest={"m1": "p2"}), index(entry("m1", "p2")))


def test_settlement_removal_fails():
    with pytest.raises(IndexIntegrityError, match="settlement:p1"):
        assert_index_monotonic(index(entry("m1", "p1", True)), index(entry("m1", "p1")))


def test_settlement_count_rollback_fails():
    with pytest.raises(IndexIntegrityError, match="settled 1->0"):
        assert_index_monotonic(index(entry("m1", "p1", True)), index(entry("m1", "p1"), settled_count=0))


def test_malformed_index_fails_closed():
    with pytest.raises(IndexIntegrityError, match="schema"):
        assert_index_monotonic({"schema_version": "wrong"}, index(entry("m1", "p1")))


def test_no_previous_index_allows_initial_build():
    assert_index_monotonic(None, index(entry("m1", "p1")))

