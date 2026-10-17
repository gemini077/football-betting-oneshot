"""Fail-closed monotonicity checks for compact PME indexes."""
from __future__ import annotations

from collections.abc import Mapping

SCHEMA = "pure_market_exact_prospective.index.v1"
MAX_EXAMPLES = 8


class IndexIntegrityError(ValueError):
    """A rebuilt index would silently discard immutable PME history."""


def _validated(index: Mapping[str, object], label: str):
    if not isinstance(index, Mapping) or index.get("schema_version") != SCHEMA:
        raise IndexIntegrityError(f"{label} index schema invalid; expected {SCHEMA}")
    rows = index.get("predictions")
    latest = index.get("latest_by_match")
    if not isinstance(rows, list) or not isinstance(latest, Mapping):
        raise IndexIntegrityError(f"{label} index predictions/latest_by_match malformed")
    if type(index.get("prediction_count")) is not int or index["prediction_count"] != len(rows):
        raise IndexIntegrityError(f"{label} index prediction_count mismatch")
    settled_count = index.get("settled_prediction_count")
    if type(settled_count) is not int or settled_count < 0:
        raise IndexIntegrityError(f"{label} index settled_prediction_count invalid")
    keys, ids, settled = set(), set(), set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise IndexIntegrityError(f"{label} index contains malformed prediction entry")
        key, pid = row.get("match_key"), row.get("prediction_id")
        if not isinstance(key, str) or not key or not isinstance(pid, str) or not pid:
            raise IndexIntegrityError(f"{label} index contains empty match_key/prediction_id")
        pair = (key, pid)
        if pair in keys or pid in ids:
            raise IndexIntegrityError(f"{label} index contains duplicate canonical key/prediction_id")
        keys.add(pair); ids.add(pid)
        if row.get("settlement_path"):
            settled.add(pid)
    if index["prediction_count"] != len(ids) or settled_count != len(settled):
        raise IndexIntegrityError(f"{label} index counts do not match canonical entries")
    expected = {}
    for key, pid in latest.items():
        if not isinstance(key, str) or not key or not isinstance(pid, str) or (key, pid) not in keys:
            raise IndexIntegrityError(f"{label} index latest_by_match references unknown prediction")
        expected[key] = pid
    if set(expected) != {key for key, _ in keys}:
        raise IndexIntegrityError(f"{label} index latest_by_match keys mismatch")
    return rows, ids, settled


def assert_index_monotonic(previous: Mapping[str, object] | None, new: Mapping[str, object]) -> None:
    """Raise bounded deterministic diagnostics if immutable history regresses."""
    _, new_ids, new_settled = _validated(new, "new")
    if previous is None:
        return
    old_rows, old_ids, old_settled = _validated(previous, "previous")
    old_matches = {str(row["match_key"]) for row in old_rows}
    new_matches = {str(row["match_key"]) for row in new["predictions"]}
    missing_matches = sorted(old_matches - new_matches)
    missing_ids = sorted(old_ids - new_ids)
    missing_settled = sorted(old_settled - new_settled)
    settlement_rollback = new["settled_prediction_count"] < previous["settled_prediction_count"]
    if missing_matches or missing_ids or missing_settled or settlement_rollback:
        details = [f"matches {len(old_matches)}->{len(new_matches)} (missing {len(missing_matches)})",
                   f"predictions {len(old_ids)}->{len(new_ids)} (missing {len(missing_ids)})",
                   f"settled {len(old_settled)}->{len(new_settled)} (missing {len(missing_settled)})"]
        examples = ([("match", x) for x in missing_matches] + [("prediction", x) for x in missing_ids] + [("settlement", x) for x in missing_settled])[:MAX_EXAMPLES]
        suffix = "; examples=" + ", ".join(f"{kind}:{value[:160]}" for kind, value in examples) if examples else ""
        raise IndexIntegrityError("PME index history regression: " + "; ".join(details) + suffix)

