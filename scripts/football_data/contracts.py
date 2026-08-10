"""Executable validation for the Phase 2A football data contracts.

The contract layer validates provenance and semantics at the normalized-data
boundary. It does not calculate model parameters and is not imported by the
formal Champion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping


class ContractError(ValueError):
    """Raised when a football data record violates its versioned contract."""


QUALITY_GRADES = frozenset({"A", "B", "C", "D"})
FRESHNESS_STATES = frozenset({"fresh", "stale", "unknown"})
HOME_AWAY_CONTEXTS = frozenset({"home", "away", "overall", "neutral", "unknown"})
RESOLUTION_METHODS = frozenset(
    {
        "provider_id_exact",
        "existing_crosswalk",
        "exact_alias",
        "normalized_alias",
        "contextual_match",
        "manual_verified",
        "unresolved",
    }
)
RESOLUTION_STATUSES = frozenset({"resolved", "unresolved"})
LINEUP_STATUSES = frozenset({"projected", "confirmed", "unavailable"})
AVAILABILITY_STATUSES = frozenset(
    {"confirmed_out", "suspended", "doubtful", "questionable", "returned", "unknown"}
)
WINDOW_TYPES = frozenset({"last_5", "last_10", "last_20", "season_to_date", "rolling_365d", "single_match"})
DUPLICATE_STATUSES = frozenset({"unique", "duplicate_same", "possible_duplicate", "duplicate_conflict"})


def _is_number_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _require_iso_timestamp(value: Any, field: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{field} must be a non-empty ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO timestamp: {value!r}") from exc


def _optional_iso_timestamp(value: Any, field: str) -> None:
    if value is not None:
        _require_iso_timestamp(value, field)


@dataclass(frozen=True)
class DataProvenance:
    """Lineage required for every normalized value."""

    provider: str
    source: str
    source_record_ref: str
    captured_at: str
    source_reliable: bool | None = None
    source_as_of_at: str | None = None
    source_url: str | None = None
    data_license: str | None = None
    attribution_required: bool = False
    commercial_use_review: str = "not_required"
    parser_version: str | None = None
    raw_sha256: str | None = None
    synthetic: bool = False
    observation_origin: str = "provider_observation"
    provider_schema: str | None = None
    provider_schema_reference: str | None = None

    def __post_init__(self) -> None:
        _require(bool(self.provider.strip()), "provenance.provider is required")
        _require(bool(self.source.strip()), "provenance.source is required")
        _require(self.source_reliable is None or isinstance(self.source_reliable, bool), "provenance.source_reliable must be bool or null")
        _require(bool(self.source_record_ref.strip()), "provenance.source_record_ref is required")
        _require_iso_timestamp(self.captured_at, "provenance.captured_at")
        _optional_iso_timestamp(self.source_as_of_at, "provenance.source_as_of_at")
        _require(isinstance(self.attribution_required, bool), "provenance.attribution_required must be bool")
        _require(isinstance(self.synthetic, bool), "provenance.synthetic must be bool")
        _require(bool(self.observation_origin.strip()), "provenance.observation_origin is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DataProvenance":
        _require(isinstance(value, Mapping), "provenance must be an object")
        return cls(
            provider=str(value.get("provider", "")),
            source=str(value.get("source", "")),
            source_reliable=value.get("source_reliable"),
            source_record_ref=str(value.get("source_record_ref", "")),
            captured_at=str(value.get("captured_at", "")),
            source_as_of_at=value.get("source_as_of_at"),
            source_url=value.get("source_url"),
            data_license=value.get("data_license"),
            attribution_required=value.get("attribution_required", False),
            commercial_use_review=str(value.get("commercial_use_review", "not_required")),
            parser_version=value.get("parser_version"),
            raw_sha256=value.get("raw_sha256"),
            synthetic=value.get("synthetic", False),
            observation_origin=str(value.get("observation_origin", "provider_observation")),
            provider_schema=value.get("provider_schema"),
            provider_schema_reference=value.get("provider_schema_reference"),
        )


def validate_provenance(value: Mapping[str, Any]) -> None:
    DataProvenance.from_dict(value)


def validate_common_observation(record: Mapping[str, Any]) -> None:
    required = {
        "contract_version",
        "source",
        "source_entity_id",
        "canonical_entity_id",
        "captured_at",
        "source_as_of_at",
        "competition",
        "season",
        "home_away_context",
        "sample_size",
        "value",
        "unit",
        "quality",
        "freshness",
        "missing_reason",
        "provenance",
    }
    missing = sorted(required.difference(record))
    _require(not missing, f"missing common fields: {', '.join(missing)}")
    _require(isinstance(record["contract_version"], str), "contract_version must be string")
    _require(isinstance(record["source"], str) and bool(record["source"].strip()), "source is required")
    _require(record["source_entity_id"] is None or isinstance(record["source_entity_id"], str), "source_entity_id must be string or null")
    _require(record["canonical_entity_id"] is None or isinstance(record["canonical_entity_id"], str), "canonical_entity_id must be string or null")
    _require_iso_timestamp(record["captured_at"], "captured_at")
    _optional_iso_timestamp(record["source_as_of_at"], "source_as_of_at")
    _require(isinstance(record["competition"], str) or record["competition"] is None, "competition must be string or null")
    _require(isinstance(record["season"], str) or record["season"] is None, "season must be string or null")
    for field in ("provider_competition_id", "provider_competition_name", "provider_season_id", "provider_season_name", "canonical_competition_id", "canonical_season_id"):
        if field in record:
            _require(record[field] is None or isinstance(record[field], str), f"{field} must be string or null")
    _require(record["home_away_context"] in HOME_AWAY_CONTEXTS, "invalid home_away_context")
    sample_size = record["sample_size"]
    _require(isinstance(sample_size, Mapping), "sample_size must be an object")
    for field in ("matches", "minutes"):
        _require(field in sample_size, f"sample_size.{field} is required")
        _require(
            sample_size[field] is None
            or (isinstance(sample_size[field], int) and not isinstance(sample_size[field], bool) and sample_size[field] >= 0),
            f"sample_size.{field} must be a non-negative integer or null",
        )
    _require(isinstance(record["quality"], str) and record["quality"] in QUALITY_GRADES, "invalid quality grade")
    freshness = record["freshness"]
    _require(isinstance(freshness, Mapping), "freshness must be an object")
    _require(freshness.get("state") in FRESHNESS_STATES, "invalid freshness state")
    _require(isinstance(record["missing_reason"], list) and all(isinstance(v, str) for v in record["missing_reason"]), "missing_reason must be a string list")
    validate_provenance(record["provenance"])
    _require(record["provenance"].get("provider") == record.get("provider", record["provenance"].get("provider")), "provenance provider mismatch")


def _validate_resolution_fields(record: Mapping[str, Any]) -> None:
    _require(record.get("resolution_status") in RESOLUTION_STATUSES, "invalid resolution_status")
    _require(record.get("resolution_method") in RESOLUTION_METHODS, "invalid resolution_method")
    _require(_is_number_or_none(record.get("confidence")), "confidence must be numeric or null")
    if record["confidence"] is not None:
        _require(0 <= record["confidence"] <= 1, "confidence must be between 0 and 1")
    if record["resolution_status"] == "unresolved":
        _require(record.get("canonical_entity_id") is None, "unresolved record cannot have canonical_entity_id")
        _require("identity_unresolved" in record["missing_reason"], "unresolved record must explain identity_unresolved")
    else:
        _require(isinstance(record.get("canonical_entity_id"), str) and bool(record["canonical_entity_id"]), "resolved record needs canonical_entity_id")


def _validate_metric_map(value: Any, field: str = "metrics") -> None:
    _require(isinstance(value, Mapping), f"{field} must be an object")
    for key, metric in value.items():
        _require(isinstance(key, str) and bool(key), f"{field} keys must be strings")
        _require(_is_number_or_none(metric), f"{field}.{key} must be numeric or null")


def _validate_team_strength_metrics(value: Any) -> None:
    """Validate the v1 strength shape, including explicit home/away blocks."""

    _require(isinstance(value, Mapping), "metrics must be an object")
    for key, metric in value.items():
        _require(isinstance(key, str) and bool(key), "metrics keys must be strings")
        if key in {"home", "away"}:
            _require(isinstance(metric, Mapping), f"metrics.{key} must be an object")
            for venue_key in ("matches", "goals_for", "goals_against"):
                _require(venue_key in metric, f"metrics.{key}.{venue_key} is required")
                _require(
                    isinstance(metric[venue_key], int) and not isinstance(metric[venue_key], bool) and metric[venue_key] >= 0,
                    f"metrics.{key}.{venue_key} must be a non-negative integer",
                )
        else:
            _require(_is_number_or_none(metric), f"metrics.{key} must be numeric or null")


def _validate_version(record: Mapping[str, Any], expected: str) -> None:
    _require(record.get("contract_version") == expected, f"expected {expected}, got {record.get('contract_version')!r}")


def validate_record(kind: str, record: Mapping[str, Any]) -> bool:
    """Validate one versioned record and return ``True`` when valid."""

    _require(isinstance(record, Mapping), "record must be an object")
    validate_common_observation(record)

    if kind == "team_identity":
        _validate_version(record, "team_identity.v1")
        _require(isinstance(record.get("canonical_name"), str) and bool(record["canonical_name"]), "canonical_name is required")
        _validate_resolution_fields(record)
    elif kind == "player_identity":
        _validate_version(record, "player_identity.v1")
        _require(isinstance(record.get("canonical_name"), str) and bool(record["canonical_name"]), "canonical_name is required")
        _require(isinstance(record.get("team_id"), str) or record.get("team_id") is None, "team_id must be string or null")
        _require(isinstance(record.get("provider_player_id"), str) or record.get("provider_player_id") is None, "provider_player_id must be string or null")
        _require(record.get("dob") is None or isinstance(record.get("dob"), str), "dob must be string or null")
        _require(record.get("nationality") is None or isinstance(record.get("nationality"), str), "nationality must be string or null")
        _validate_resolution_fields(record)
    elif kind == "competition_identity":
        _validate_version(record, "competition_identity.v1")
        _require(isinstance(record.get("canonical_name"), str) and bool(record["canonical_name"]), "canonical_name is required")
        _validate_resolution_fields(record)
    elif kind == "match_identity":
        _validate_version(record, "match_identity.v1")
        for field in ("provider_match_id", "home_team_id", "away_team_id"):
            _require(isinstance(record.get(field), str) and bool(record[field]), f"{field} is required")
        if record.get("canonical_match_id") is None:
            _require("match_identity_unresolved" in record["missing_reason"], "unresolved match must explain match_identity_unresolved")
    elif kind == "team_strength_snapshot":
        _validate_version(record, "team_strength_snapshot.v1")
        _require(isinstance(record.get("team_id"), str) and bool(record["team_id"]), "team_id is required")
        _require(isinstance(record.get("matches"), int) and record["matches"] >= 0, "matches must be non-negative integer")
        _validate_team_strength_metrics(record.get("metrics"))
        _validate_window_fields(record)
        for field in ("red_card_events", "minutes_10v11", "minutes_11v10"):
            if field in record:
                _require(record[field] is None or (isinstance(record[field], int) and record[field] >= 0), f"{field} must be a non-negative integer or null")
        if "opponent_adjustment" in record and record["opponent_adjustment"] is not None:
            _validate_opponent_adjustment(record["opponent_adjustment"])
    elif kind == "team_form_snapshot":
        _validate_version(record, "team_form_snapshot.v1")
        _require(isinstance(record.get("team_id"), str) and bool(record["team_id"]), "team_id is required")
        _require(isinstance(record.get("matches"), int) and record["matches"] >= 0, "matches must be non-negative integer")
        _validate_window_fields(record)
        _validate_metric_map(record.get("metrics"))
    elif kind == "xg_snapshot":
        _validate_version(record, "xg_snapshot.v1")
        _require(isinstance(record.get("provider"), str) and bool(record["provider"]), "xG provider is required")
        _require(isinstance(record.get("metric_definition"), str) and bool(record["metric_definition"]), "metric_definition is required")
        _require(record.get("includes_penalties") is None or isinstance(record.get("includes_penalties"), bool), "includes_penalties must be bool or null")
        _require(record.get("post_shot_or_pre_shot") in {"pre_shot", "post_shot", "unknown"}, "invalid xG timing definition")
        _require(record.get("model_version_if_known") is None or isinstance(record.get("model_version_if_known"), str), "model_version_if_known must be string or null")
        _require(_is_number_or_none(record.get("value")), "xG value must be numeric or null")
        _require(record.get("normalization_version") is None, "normalized xG is not allowed without an explicit future contract")
    elif kind == "lineup_snapshot":
        _validate_version(record, "lineup_snapshot.v1")
        for field in ("match_id", "team_id"):
            _require(isinstance(record.get(field), str) and bool(record[field]), f"{field} is required")
        _require(record.get("status") in LINEUP_STATUSES, "invalid lineup status")
        _require(isinstance(record.get("players"), list), "players must be a list")
        for player in record["players"]:
            _require(isinstance(player, Mapping), "lineup player must be an object")
            for field in ("canonical_player_id", "provider_player_id", "name", "position", "starter", "bench", "captain", "goalkeeper"):
                _require(field in player, f"lineup player missing {field}")
            _require(player["canonical_player_id"] is None or isinstance(player["canonical_player_id"], str), "canonical_player_id must be string or null")
            _require(player["starter"] is None or isinstance(player["starter"], bool), "starter must be bool or null")
            _require(player["bench"] is None or isinstance(player["bench"], bool), "bench must be bool or null")
            _require(
                player["starter"] is None and player["bench"] is None
                or isinstance(player["starter"], bool) and isinstance(player["bench"], bool) and player["starter"] != player["bench"],
                "lineup player starter/bench state must be complementary or both unknown",
            )
            _require(player["captain"] is None or isinstance(player["captain"], bool), "captain must be bool or null")
            _require(player["goalkeeper"] is None or isinstance(player["goalkeeper"], bool), "goalkeeper must be bool or null")
        if "player_identity_coverage" in record:
            coverage = record["player_identity_coverage"]
            _require(isinstance(coverage, Mapping), "player_identity_coverage must be an object")
            for field in ("resolved_players", "total_players"):
                _require(isinstance(coverage.get(field), int) and coverage[field] >= 0, f"{field} must be a non-negative integer")
            _require(coverage["resolved_players"] <= coverage["total_players"], "resolved_players cannot exceed total_players")
            _require(_is_number_or_none(coverage.get("coverage_ratio")), "coverage_ratio must be numeric")
            _require(0 <= coverage["coverage_ratio"] <= 1, "coverage_ratio must be between 0 and 1")
    elif kind == "availability_snapshot":
        _validate_version(record, "availability_snapshot.v1")
        for field in ("team_id", "player_name", "status", "evidence", "source_timestamp", "confidence"):
            _require(field in record, f"availability missing {field}")
        _require(record["status"] in AVAILABILITY_STATUSES, "invalid availability status")
        _require(isinstance(record["evidence"], list) and all(isinstance(v, str) for v in record["evidence"]), "evidence must be a string list")
        _optional_iso_timestamp(record["source_timestamp"], "source_timestamp")
        _require(_is_number_or_none(record["confidence"]), "availability confidence must be numeric or null")
        if record["confidence"] is not None:
            _require(0 <= record["confidence"] <= 1, "availability confidence must be between 0 and 1")
        if "conflict_state" in record:
            _require(record["conflict_state"] in {"none", "conflicting", "acknowledged"}, "invalid availability conflict_state")
        if "conflict_group_id" in record:
            _require(record["conflict_group_id"] is None or isinstance(record["conflict_group_id"], str), "conflict_group_id must be string or null")
    elif kind == "historical_match_result":
        _validate_version(record, "historical_match_result.v1")
        for field in ("canonical_match_id", "competition_id", "season_id", "home_team_id", "away_team_id", "kickoff_at", "provider_match_id"):
            _require(record.get(field) is None or isinstance(record.get(field), str), f"{field} must be string or null")
        for field in ("raw_home_team", "raw_away_team", "raw_competition", "raw_season"):
            _require(record.get(field) is None or isinstance(record.get(field), str), f"{field} must be string or null")
        _optional_iso_timestamp(record.get("kickoff_at"), "kickoff_at")
        for field in ("home_goals", "away_goals"):
            value = record.get(field)
            _require(value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0), f"{field} must be a non-negative integer or null")
        _require(isinstance(record.get("provider"), str) and bool(record["provider"].strip()), "provider is required")
        _require(record.get("resolution_status") in RESOLUTION_STATUSES, "invalid historical result resolution_status")
        _require(record.get("resolution_method") in RESOLUTION_METHODS, "invalid historical result resolution_method")
        if record["resolution_status"] == "resolved":
            _require(record["resolution_method"] != "unresolved", "resolved historical result requires a resolution method")
            for field in ("canonical_match_id", "home_team_id", "away_team_id"):
                _require(record.get(field) not in (None, ""), f"resolved historical result requires {field}")
        else:
            _require(record["resolution_method"] == "unresolved", "unresolved historical result requires resolution_method=unresolved")
        _require(isinstance(record.get("eligible_for_team_strength"), bool), "eligible_for_team_strength must be bool")
        _require(record.get("duplicate_status") in DUPLICATE_STATUSES, "invalid duplicate_status")
        if record["eligible_for_team_strength"]:
            _require(record.get("resolution_status") == "resolved", "eligible historical result must be resolved")
            for field in ("canonical_match_id", "competition_id", "season_id", "home_team_id", "away_team_id", "kickoff_at", "home_goals", "away_goals", "source_as_of_at"):
                _require(record.get(field) not in (None, ""), f"eligible historical result requires {field}")
            _require(record.get("quality") in {"A", "B"}, "eligible historical result requires A/B quality")
            _require(record.get("provenance", {}).get("source_reliable") is True, "eligible historical result requires reliable provenance")
            _require(record.get("duplicate_status") in {"unique", "duplicate_same"}, "duplicate historical result cannot be eligible")
    else:
        raise ContractError(f"unknown football data contract kind: {kind}")
    return True


def _validate_window_fields(record: Mapping[str, Any]) -> None:
    _require(record.get("window_type") in WINDOW_TYPES, "invalid window_type")
    _require(isinstance(record.get("window_start"), str) and bool(record["window_start"]), "window_start is required")
    _require(isinstance(record.get("window_end"), str) and bool(record["window_end"]), "window_end is required")
    _require(record.get("minutes") is None or (isinstance(record.get("minutes"), int) and record["minutes"] >= 0), "minutes must be non-negative integer or null")


def _validate_opponent_adjustment(value: Mapping[str, Any]) -> None:
    _require(isinstance(value, Mapping), "opponent_adjustment must be an object")
    for field in ("opponent_team_id", "opponent_strength_snapshot_ref", "raw_metric", "opponent_adjusted_metric", "adjustment_method", "adjustment_version"):
        _require(field in value, f"opponent_adjustment missing {field}")
    _require(_is_number_or_none(value["raw_metric"]), "raw_metric must be numeric or null")
    _require(value["opponent_adjusted_metric"] is None, "Phase 2A opponent_adjusted_metric must remain null")
