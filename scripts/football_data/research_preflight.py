"""Walk-forward eligibility audit for a future Team Strength experiment.

This module is deliberately research-only.  It reuses the existing
``audit_retrospective_availability`` and ``TeamStrengthBuilder`` paths, keeps
the target result out of its own history, and never writes model or benchmark
records.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .historical_results import deduplicate_historical_results
from .p0_p1_coverage import audit_retrospective_availability
from .storage import content_sha256


RESEARCH_CONTRACT_VERSION = "phase2c_research_eligibility.v1"
COHORT_CONTRACT_VERSION = "phase2c_research_cohort.v1"
SPLIT_METHOD = "global_date_order_60_20_20"
MIN_STANDARD_FIXTURES = 200
MIN_STANDARD_COMPETITIONS = 3
MIN_STANDARD_TEAMS = 30
MIN_COMPETITION_DEVELOPMENT_FIXTURES = 10
MIN_COMPETITION_VALIDATION_FIXTURES = 5
MIN_COMPETITION_TEST_FIXTURES = 5
MIN_COMPETITION_SPAN_DAYS = 90
MAX_LARGEST_COMPETITION_SHARE = 0.5
MAX_LARGEST_SEASON_SHARE = 0.5
MAX_LARGEST_TEAM_APPEARANCE_SHARE = 0.15


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_sort_key(record: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_parse_time(record.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(record.get("canonical_match_id") or ""))


def _date_range(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = sorted(value for value in (_parse_time(row.get("kickoff_at")) for row in records) if value is not None)
    if not values:
        return {"first_fixture": None, "last_fixture": None, "span_days": None}
    return {
        "first_fixture": _iso(values[0]),
        "last_fixture": _iso(values[-1]),
        "span_days": round((values[-1] - values[0]).total_seconds() / 86400, 6),
    }


def _percentile(values: Iterable[int], fraction: float) -> float | None:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 6)


def _distribution(values: Iterable[int]) -> dict[str, Any]:
    ordered = sorted(int(value) for value in values)
    return {
        "count": len(ordered),
        "min": ordered[0] if ordered else None,
        "p10": _percentile(ordered, 0.10),
        "p25": _percentile(ordered, 0.25),
        "median": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
        "max": ordered[-1] if ordered else None,
    }


def concentration_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe concentration without treating it as a model metric."""

    rows = list(rows)
    fixture_count = len(rows)
    competitions = Counter(str(row.get("competition_id") or "unknown") for row in rows)
    seasons = Counter(str(row.get("season_id") or "unknown") for row in rows)
    appearances = Counter(
        str(team_id)
        for row in rows
        for team_id in (row.get("home_team_id"), row.get("away_team_id"))
        if team_id
    )

    def top(counter: Counter[str], denominator: int, key_name: str) -> dict[str, Any]:
        if not counter or not denominator:
            return {key_name: None, "count": 0, "share": None}
        key, count = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0]
        return {key_name: key, "count": count, "share": round(count / denominator, 6)}

    return {
        "fixture_count": fixture_count,
        "largest_competition": top(competitions, fixture_count, "competition_id"),
        "largest_season": top(seasons, fixture_count, "season_id"),
        "team_appearance_count": sum(appearances.values()),
        "largest_team_appearance": top(appearances, sum(appearances.values()), "team_id"),
    }


def _bucket_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=_record_sort_key)
    return {
        "count": len(ordered),
        "min_kickoff_at": _iso(_parse_time(ordered[0].get("kickoff_at"))) if ordered else None,
        "max_kickoff_at": _iso(_parse_time(ordered[-1].get("kickoff_at"))) if ordered else None,
        "match_ids": [str(row.get("canonical_match_id")) for row in ordered if row.get("canonical_match_id")],
    }


def chronological_split(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Create a deterministic date-only development/validation/test proposal."""

    ordered = sorted(list(rows), key=_record_sort_key)
    if not ordered:
        return {
            "method": SPLIT_METHOD,
            "development": _bucket_summary([]),
            "validation": _bucket_summary([]),
            "held_out_test": _bucket_summary([]),
        }

    unique_times = sorted(
        {
            parsed
            for row in ordered
            if (parsed := _parse_time(row.get("kickoff_at"))) is not None
        }
    )
    # Cut on the observed time axis rather than fixture indexes.  Several
    # competitions have many matches sharing a kickoff date; using the raw
    # fixture count can otherwise select the final unique timestamp as the
    # validation cutoff and silently produce an empty test bucket.
    train_index = min(len(unique_times) - 2, max(0, int((len(unique_times) - 1) * 0.60))) if len(unique_times) > 1 else 0
    validation_index = min(len(unique_times) - 1, max(train_index + 1, int((len(unique_times) - 1) * 0.80))) if len(unique_times) > 1 else 0
    train_cutoff = unique_times[train_index]
    validation_cutoff = unique_times[validation_index]

    def before_or_at(row: Mapping[str, Any], cutoff: datetime) -> bool:
        parsed = _parse_time(row.get("kickoff_at"))
        return parsed is not None and parsed <= cutoff

    def after(row: Mapping[str, Any], cutoff: datetime) -> bool:
        parsed = _parse_time(row.get("kickoff_at"))
        return parsed is not None and parsed > cutoff

    development = [row for row in ordered if before_or_at(row, train_cutoff)]
    validation = [
        row
        for row in ordered
        if after(row, train_cutoff) and before_or_at(row, validation_cutoff)
    ]
    held_out_test = [row for row in ordered if after(row, validation_cutoff)]
    return {
        "method": SPLIT_METHOD,
        "development": _bucket_summary(development),
        "validation": _bucket_summary(validation),
        "held_out_test": _bucket_summary(held_out_test),
    }


def _scope_complete(audit: Mapping[str, Any]) -> bool:
    return bool(
        audit.get("home_details", {}).get("recent_form_scope") == "COMPLETE"
        and audit.get("away_details", {}).get("recent_form_scope") == "COMPLETE"
    )


def _recency_current(audit: Mapping[str, Any]) -> bool:
    return audit.get("home_recency") == "current" and audit.get("away_recency") == "current"


def _source_conflict_free(
    target: Mapping[str, Any],
    audit: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if target.get("source_conflict") is True or target.get("duplicate_status") not in {"unique", "duplicate_same"}:
        return False
    selected_ids = set(audit.get("home_source_match_ids") or []) | set(audit.get("away_source_match_ids") or [])
    return all(
        records_by_id.get(str(match_id), {}).get("source_conflict") is not True
        and records_by_id.get(str(match_id), {}).get("duplicate_status") in {"unique", "duplicate_same"}
        for match_id in selected_ids
    )


def _reason_list(
    *,
    identity_valid: bool,
    competition_known: bool,
    source_conflict_free: bool,
    history_depth: int,
    recency_current: bool,
    scope_complete: bool,
    bridge_only: bool,
) -> list[str]:
    reasons: list[str] = []
    if not identity_valid:
        reasons.append("identity_invalid")
    if not competition_known:
        reasons.append("competition_or_season_unknown")
    if not source_conflict_free:
        reasons.append("source_conflict")
    if history_depth < 5:
        reasons.append("minimum_history_not_met")
    if not recency_current:
        reasons.append("recency_not_current")
    if not scope_complete:
        reasons.append("recent_form_scope_partial_or_unknown")
    if bridge_only:
        reasons.append("verified_bridge_is_reported_separately")
    return reasons


def _cohort_manifest(
    tier: str,
    rows: list[Mapping[str, Any]],
    *,
    dataset_digest: str,
) -> dict[str, Any]:
    ordered = sorted(rows, key=_record_sort_key)
    match_ids = sorted(str(row.get("canonical_match_id")) for row in ordered if row.get("canonical_match_id"))
    digest = content_sha256(
        {
            "cohort_contract_version": COHORT_CONTRACT_VERSION,
            "eligibility_contract_version": RESEARCH_CONTRACT_VERSION,
            "historical_dataset_digest": dataset_digest,
            "tier": tier,
            "canonical_match_ids": match_ids,
        }
    )
    return {
        "tier": tier,
        "research_cohort_id": f"phase2c-1:{tier}:{digest}",
        "cohort_match_id_digest": content_sha256(match_ids),
        "eligibility_contract_version": RESEARCH_CONTRACT_VERSION,
        "historical_dataset_digest": dataset_digest,
        "cohort_size": len(ordered),
        "competitions": sorted({str(row.get("competition_id")) for row in ordered if row.get("competition_id")}),
        "unique_teams": len({team_id for row in ordered for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id}),
        "date_range": _date_range(ordered),
        "match_ids": match_ids,
    }


def _competition_breakdown(
    records: list[Mapping[str, Any]],
    audits_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for competition_id in sorted({str(row.get("competition_id") or "unknown") for row in records}):
        rows = [row for row in records if str(row.get("competition_id") or "unknown") == competition_id]
        audits = [audits_by_id[str(row.get("canonical_match_id"))] for row in rows if str(row.get("canonical_match_id")) in audits_by_id]
        output[competition_id] = {
            "total_historical_fixtures": len(rows),
            "eligible_ge_5": sum(bool(row.get("eligible_ge_5")) for row in audits),
            "eligible_ge_10": sum(bool(row.get("eligible_ge_10")) for row in audits),
            "eligible_ge_20": sum(bool(row.get("eligible_ge_20")) for row in audits),
            "verified_bridge_fixtures": sum(bool(row.get("bridge_only")) for row in audits),
            "unique_teams": len({team_id for row in rows for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id}),
            "source_conflict_count": sum(bool(row.get("source_conflict")) for row in rows),
            **_date_range(rows),
        }
    return output


def _season_breakdown(
    records: list[Mapping[str, Any]],
    audits_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in sorted({(str(row.get("competition_id") or "unknown"), str(row.get("season_id") or "unknown")) for row in records}):
        competition_id, season_id = key
        rows = [row for row in records if str(row.get("competition_id") or "unknown") == competition_id and str(row.get("season_id") or "unknown") == season_id]
        audits = [audits_by_id[str(row.get("canonical_match_id"))] for row in rows if str(row.get("canonical_match_id")) in audits_by_id]
        output[f"{competition_id}|{season_id}"] = {
            "competition_id": competition_id,
            "season_id": season_id,
            "total_historical_fixtures": len(rows),
            "eligible_ge_5": sum(bool(row.get("eligible_ge_5")) for row in audits),
            "eligible_ge_10": sum(bool(row.get("eligible_ge_10")) for row in audits),
            "eligible_ge_20": sum(bool(row.get("eligible_ge_20")) for row in audits),
            "unique_teams": len({team_id for row in rows for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id}),
            **_date_range(rows),
        }
    return output


def _source_breakdown(records: list[Mapping[str, Any]], deduplication: Any) -> dict[str, Any]:
    providers = Counter(str(row.get("provider") or "unknown") for row in records)
    confirmations = [row.get("source_confirmations") or [] for row in records]
    known = {"Football-Data.co.uk", "football-data.co.uk", "OpenFootball", "openfootball"}
    other = sum(count for provider, count in providers.items() if provider not in known)
    return {
        "primary_provider_fixture_counts": dict(sorted(providers.items())),
        "single_source_fixture_count": sum(len(items) <= 1 for items in confirmations),
        "multi_source_corroborated_fixture_count": sum(len(items) > 1 for items in confirmations),
        "source_conflict_count": sum(bool(row.get("source_conflict")) for row in records),
        "deduplication_conflicts": int(deduplication.conflicts),
        "other_existing_adopted_source_fixture_count": other,
    }


def _competition_split_readiness(
    standard_rows: list[Mapping[str, Any]],
    split: Mapping[str, Any],
) -> dict[str, Any]:
    standard_by_id = {str(row.get("canonical_match_id")): row for row in standard_rows}
    buckets = {
        name: set(value.get("match_ids") or [])
        for name, value in split.items()
        if name in {"development", "validation", "held_out_test"}
    }
    output: dict[str, Any] = {}
    for competition_id in sorted({str(row.get("competition_id")) for row in standard_rows}):
        rows = [row for row in standard_rows if str(row.get("competition_id")) == competition_id]
        counts = {name: sum(match_id in ids for match_id, row in standard_by_id.items() if row.get("competition_id") == competition_id) for name, ids in buckets.items()}
        span = _date_range(rows)
        sufficient = bool(
            counts.get("development", 0) >= MIN_COMPETITION_DEVELOPMENT_FIXTURES
            and counts.get("validation", 0) >= MIN_COMPETITION_VALIDATION_FIXTURES
            and counts.get("held_out_test", 0) >= MIN_COMPETITION_TEST_FIXTURES
            and (span.get("span_days") or 0) >= MIN_COMPETITION_SPAN_DAYS
        )
        output[competition_id] = {
            "eligible_fixtures": len(rows),
            **counts,
            **span,
            "sufficient_chronological_span": sufficient,
        }
    return output


def audit_historical_eligibility(
    historical_records: Iterable[Mapping[str, Any]],
    *,
    dataset_digest: str,
) -> dict[str, Any]:
    """Audit every normalized fixture as a historical pre-match target."""

    deduplication = deduplicate_historical_results(historical_records)
    records = sorted(deduplication.records, key=_record_sort_key)
    targets: list[dict[str, Any]] = []
    for record in records:
        target = dict(record)
        target["weight"] = 1
        target["competition_type"] = "league" if record.get("match_type") == "league" else "other"
        target["intended_match_types"] = {str(record.get("match_type"))} if record.get("match_type") else set()
        targets.append(target)

    retrospective = audit_retrospective_availability(targets, records)
    records_by_id = {str(row.get("canonical_match_id")): row for row in records if row.get("canonical_match_id")}
    target_by_id = records_by_id
    enriched: list[dict[str, Any]] = []
    for audit in retrospective:
        target_id = str(audit.get("target_match_id") or "")
        target = target_by_id.get(target_id, {})
        identity_valid = bool(target.get("home_team_id") and target.get("away_team_id") and target.get("home_team_id") != target.get("away_team_id"))
        competition_known = bool(target.get("competition_id") and target.get("season_id"))
        conflict_free = _source_conflict_free(target, audit, records_by_id)
        depth = min(int(audit.get("home_history_matches") or 0), int(audit.get("away_history_matches") or 0))
        current = _recency_current(audit)
        scope = _scope_complete(audit)
        bridge_only = bool(audit.get("bridge_only"))
        common = bool(identity_valid and competition_known and conflict_free and current and scope and not bridge_only)
        row = dict(audit)
        row.update(
            {
                "season_id": target.get("season_id"),
                "entity_type": target.get("entity_type") or "club",
                "match_type": target.get("match_type"),
                "identity_valid": identity_valid,
                "competition_known": competition_known,
                "no_source_conflict": conflict_free,
                "recency_current": current,
                "scope_complete": scope,
                "prior_history_depth": depth,
                "bridge_only": bridge_only,
                "eligible_ge_5": bool(common and depth >= 5),
                "eligible_ge_10": bool(common and depth >= 10),
                "eligible_ge_20": bool(common and depth >= 20),
                "reason": _reason_list(
                    identity_valid=identity_valid,
                    competition_known=competition_known,
                    source_conflict_free=conflict_free,
                    history_depth=depth,
                    recency_current=current,
                    scope_complete=scope,
                    bridge_only=bridge_only,
                ),
            }
        )
        enriched.append(row)

    audits_by_id = {str(row.get("target_match_id")): row for row in enriched}
    tier_rows = {
        "minimum": [target_by_id[str(row["target_match_id"])] for row in enriched if row.get("eligible_ge_5")],
        "standard": [target_by_id[str(row["target_match_id"])] for row in enriched if row.get("eligible_ge_10")],
        "strict": [target_by_id[str(row["target_match_id"])] for row in enriched if row.get("eligible_ge_20")],
    }
    cohorts = {tier: _cohort_manifest(tier, rows, dataset_digest=dataset_digest) for tier, rows in tier_rows.items()}
    full_standard_split = chronological_split(tier_rows["standard"])
    full_timeline = _competition_split_readiness(tier_rows["standard"], full_standard_split)
    recommended_competitions = sorted(
        competition_id for competition_id, row in full_timeline.items() if row.get("sufficient_chronological_span") is True
    )
    recommended_rows = [
        row for row in tier_rows["standard"] if str(row.get("competition_id")) in set(recommended_competitions)
    ]
    recommended_split = chronological_split(recommended_rows)
    timeline = _competition_split_readiness(recommended_rows, recommended_split)
    concentration = concentration_metrics(tier_rows["standard"])
    recommended_concentration = concentration_metrics(recommended_rows)
    standard_teams = len({team_id for row in recommended_rows for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id})
    recommended_cohort = _cohort_manifest("standard_recommended", recommended_rows, dataset_digest=dataset_digest)
    excluded_competitions = {
        competition_id: {"reason": "insufficient chronological development/validation/test span", **row}
        for competition_id, row in full_timeline.items()
        if competition_id not in recommended_competitions
    }
    gate_criteria = {
        "recommended_standard_fixtures_at_least_200": len(recommended_rows) >= MIN_STANDARD_FIXTURES,
        "eligible_competitions_at_least_3": len(cohorts["standard"]["competitions"]) >= MIN_STANDARD_COMPETITIONS,
        "unique_teams_at_least_30": standard_teams >= MIN_STANDARD_TEAMS,
        "each_recommended_competition_has_chronological_train_validation_test": bool(timeline) and all(row["sufficient_chronological_span"] for row in timeline.values()),
        "concentration_within_audit_caps": bool(
            (recommended_concentration["largest_competition"]["share"] or 0) <= MAX_LARGEST_COMPETITION_SHARE
            and (recommended_concentration["largest_season"]["share"] or 0) <= MAX_LARGEST_SEASON_SHARE
            and (recommended_concentration["largest_team_appearance"]["share"] or 0) <= MAX_LARGEST_TEAM_APPEARANCE_SHARE
        ),
    }
    blockers = [name for name, passed in gate_criteria.items() if not passed]
    return {
        "contract_version": RESEARCH_CONTRACT_VERSION,
        "research_only": True,
        "formal_benchmark_eligible": False,
        "validated_for_model": False,
        "historical_dataset_digest": dataset_digest,
        "historical_record_count": len(historical_records) if hasattr(historical_records, "__len__") else len(records),
        "deduplicated_fixture_count": len(records),
        "date_range": _date_range(records),
        "unique_competitions": sorted({str(row.get("competition_id")) for row in records if row.get("competition_id")}),
        "unique_teams": len({team_id for row in records for team_id in (row.get("home_team_id"), row.get("away_team_id")) if team_id}),
        "tier_counts": {
            "minimum_ge_5": len(tier_rows["minimum"]),
            "standard_ge_10": len(tier_rows["standard"]),
            "strict_ge_20": len(tier_rows["strict"]),
            "verified_bridge": sum(bool(row.get("bridge_only")) for row in enriched),
        },
        "prior_history_distribution": {
            "home": _distribution(row.get("home_history_matches", 0) for row in enriched),
            "away": _distribution(row.get("away_history_matches", 0) for row in enriched),
        },
        "competition_breakdown": _competition_breakdown(records, audits_by_id),
        "season_breakdown": _season_breakdown(records, audits_by_id),
        "source_breakdown": _source_breakdown(records, deduplication),
        "deduplication": {
            "duplicates_collapsed": int(deduplication.duplicates_collapsed),
            "possible_duplicates": int(deduplication.possible_duplicates),
            "conflicts": int(deduplication.conflicts),
        },
        "concentration": concentration,
        "recommended_concentration": recommended_concentration,
        "chronological_split": recommended_split,
        "full_standard_chronological_split": full_standard_split,
        "full_standard_competition_split_readiness": full_timeline,
        "competition_split_readiness": timeline,
        "cohorts": cohorts,
        "recommended_cohort": recommended_cohort,
        "recommended_cohort_excluded_competitions": excluded_competitions,
        "recommended_cohort_tier": "standard_recommended" if recommended_rows else ("standard" if tier_rows["standard"] else "minimum"),
        "readiness_gate": {
            "phase2c_1_research_ready": not blockers,
            "criteria": gate_criteria,
            "blockers": blockers,
            "policy": {
                "minimum_standard_fixtures": MIN_STANDARD_FIXTURES,
                "minimum_standard_competitions": MIN_STANDARD_COMPETITIONS,
                "minimum_standard_teams": MIN_STANDARD_TEAMS,
                "minimum_competition_development_fixtures": MIN_COMPETITION_DEVELOPMENT_FIXTURES,
                "minimum_competition_validation_fixtures": MIN_COMPETITION_VALIDATION_FIXTURES,
                "minimum_competition_test_fixtures": MIN_COMPETITION_TEST_FIXTURES,
                "minimum_competition_span_days": MIN_COMPETITION_SPAN_DAYS,
                "max_largest_competition_share": MAX_LARGEST_COMPETITION_SHARE,
                "max_largest_season_share": MAX_LARGEST_SEASON_SHARE,
                "max_largest_team_appearance_share": MAX_LARGEST_TEAM_APPEARANCE_SHARE,
            },
        },
        "research_readiness_blockers": blockers,
        "audits": enriched,
    }


def compact_research_manifest(report: Mapping[str, Any], *, benchmark_health: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Remove per-fixture IDs while retaining reproducible cohort evidence."""

    cohorts = {}
    for tier, cohort in (report.get("cohorts") or {}).items():
        cohorts[tier] = {key: value for key, value in cohort.items() if key != "match_ids"}
    split = report.get("chronological_split") or {}
    compact_split = {
        "method": split.get("method"),
        **{
            name: {key: value for key, value in bucket.items() if key != "match_ids"}
            for name, bucket in split.items()
            if name in {"development", "validation", "held_out_test"}
        },
    }
    compact = {
        key: report[key]
        for key in (
            "contract_version",
            "research_only",
            "formal_benchmark_eligible",
            "validated_for_model",
            "historical_dataset_digest",
            "historical_record_count",
            "deduplicated_fixture_count",
            "date_range",
            "unique_competitions",
            "unique_teams",
            "tier_counts",
            "prior_history_distribution",
            "competition_breakdown",
            "season_breakdown",
            "source_breakdown",
            "deduplication",
            "concentration",
            "recommended_concentration",
            "competition_split_readiness",
            "full_standard_competition_split_readiness",
            "recommended_cohort_tier",
            "recommended_cohort",
            "recommended_cohort_excluded_competitions",
            "readiness_gate",
            "research_readiness_blockers",
        )
    }
    compact = dict(compact)
    compact["cohorts"] = cohorts
    compact["recommended_cohort"] = {
        key: value for key, value in (report.get("recommended_cohort") or {}).items() if key != "match_ids"
    }
    compact["chronological_split"] = compact_split
    compact["benchmark_health"] = dict(benchmark_health or {})
    return compact


__all__ = [
    "RESEARCH_CONTRACT_VERSION",
    "audit_historical_eligibility",
    "chronological_split",
    "compact_research_manifest",
    "concentration_metrics",
]
