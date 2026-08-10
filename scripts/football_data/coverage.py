"""Competition-observation and historical-result coverage diagnostics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


STATUSES = frozenset({"SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED"})


def _status(value: Any) -> str:
    text = str(value or "UNVERIFIED").upper()
    return text if text in STATUSES else "UNVERIFIED"


def build_coverage_registry(
    *,
    observed: Iterable[Mapping[str, Any]],
    entries: Iterable[Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Merge bounded observations with reviewed coverage declarations.

    Observations never promote a competition to a canonical identity or to
    SUPPORTED.  Those are reviewed registry decisions, not name inference.
    """

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "raw_names": set(),
            "observed_count": 0,
            "current_match_count": 0,
            "provider_competition_ids": set(),
        }
    )
    for row in observed:
        key = str(row.get("competition_key") or row.get("raw_name") or "unresolved")
        bucket = grouped[key]
        if row.get("raw_name"):
            bucket["raw_names"].add(str(row["raw_name"]))
        bucket["observed_count"] += int(row.get("observed_count") or 1)
        bucket["current_match_count"] += int(row.get("current_match_count") or 0)
        if row.get("provider_competition_id"):
            bucket["provider_competition_ids"].add(str(row["provider_competition_id"]))

    by_key: dict[str, dict[str, Any]] = {}
    for raw in entries:
        row = dict(raw)
        key = str(row.get("competition_key") or row.get("canonical_competition_id") or row.get("name") or "unresolved")
        row["competition_key"] = key
        row["result_coverage"] = _status(row.get("result_coverage"))
        row["current_season_coverage"] = _status(row.get("current_season_coverage"))
        by_key[key] = row

    for key, bucket in grouped.items():
        row = by_key.setdefault(
            key,
            {
                "competition_key": key,
                "canonical_competition_id": None,
                "name": next(iter(bucket["raw_names"]), key),
                "country": None,
                "entity_type": "club",
                "competition_type": "unknown",
                "historical_result_sources": [],
                "current_match_sources": [],
                "result_coverage": "UNVERIFIED",
                "current_season_coverage": "UNVERIFIED",
                "team_identity_coverage": None,
                "last_verified_at": None,
                "notes": [],
            },
        )
        row["observed_count"] = int(row.get("observed_count") or 0) + bucket["observed_count"]
        row["current_match_count"] = int(row.get("current_match_count") or 0) + bucket["current_match_count"]
        row["observed_raw_names"] = sorted(set(row.get("observed_raw_names") or []) | bucket["raw_names"])
        row["observed_provider_competition_ids"] = sorted(set(row.get("observed_provider_competition_ids") or []) | bucket["provider_competition_ids"])
        row["result_coverage"] = _status(row.get("result_coverage"))
        row["current_season_coverage"] = _status(row.get("current_season_coverage"))

    return {
        "contract_version": "competition_coverage_registry.v1",
        "generated_at": generated_at,
        "observed_competitions": [
            {
                "competition_key": key,
                "raw_names": sorted(bucket["raw_names"]),
                "observed_count": bucket["observed_count"],
                "current_match_count": bucket["current_match_count"],
                "provider_competition_ids": sorted(bucket["provider_competition_ids"]),
            }
            for key, bucket in sorted(grouped.items())
        ],
        "competitions": [by_key[key] for key in sorted(by_key)],
    }


def rank_coverage_gaps(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rank actual gaps by current use, then observed frequency."""

    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        current = int(row.get("current_match_count") or 0)
        observed = int(row.get("observed_count") or 0)
        current_strength_coverage = row.get("current_strength_coverage")
        current_strength_ok = current_strength_coverage is None or float(current_strength_coverage) >= 1.0
        supported = _status(row.get("result_coverage")) == "SUPPORTED" and float(row.get("team_identity_coverage") or 0) >= 1.0 and current_strength_ok
        if current and not supported:
            priority = "P0"
        elif observed >= 10:
            priority = "P1"
        elif observed:
            priority = "P2"
        else:
            priority = "P3"
        row["coverage_priority"] = priority
        row["priority_reason"] = "current analysis gap" if priority == "P0" else "observed frequency"
        output.append(row)
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(
        output,
        key=lambda row: (
            order.get(str(row.get("coverage_priority")), 9),
            -int(row.get("current_match_count") or 0),
            -int(row.get("observed_count") or 0),
            str(row.get("competition_key") or ""),
        ),
    )


__all__ = ["STATUSES", "build_coverage_registry", "rank_coverage_gaps"]
