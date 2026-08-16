"""Research-only opponent-adjusted strength challenger.

This module is intentionally separate from the production prediction path.  It
reads historical results and persisted production records, creates shadow
predictions, and writes research artifacts only when invoked by its CLI.  It
does not import or call the production Champion, freeze, prospective, or
automation code.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite, log
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

# Support both ``python -m scripts.strength_challenger`` and the repository's
# established direct-script invocation form.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.football_data.data_home import resolve_football_data_home
from scripts.football_data.phase2c1_model import InsufficientHistoryError, probability_payload
from scripts.football_data.storage import DatasetNotAvailableError, HistoricalResultStore


CHALLENGER_NAME = "opponent_adjusted_strength_poisson_v1"
SCORE_TOP_K = (1, 3, 5)
_EPSILON = 1e-15


@dataclass(frozen=True)
class ChallengerSpec:
    """Small, pre-registered challenger configuration."""

    regularization: int = 10
    minimum_history: int = 5
    competition_minimum_rows: int = 20
    recency_policy: str = "none"
    rho: float = 0.0
    formula_version: str = CHALLENGER_NAME


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse_time(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _sort_key(row: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("canonical_match_id") or ""))


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _score_string(value: Any) -> str | None:
    if isinstance(value, str) and "-" in value:
        left, right = value.split("-", 1)
        if left.strip().isdigit() and right.strip().isdigit():
            return f"{int(left)}-{int(right)}"
    if isinstance(value, Mapping):
        home = value.get("home_goals", value.get("home"))
        away = value.get("away_goals", value.get("away"))
        if str(home).isdigit() and str(away).isdigit():
            return f"{int(home)}-{int(away)}"
    return None


def _score_parts(value: Any) -> tuple[int, int] | None:
    score = _score_string(value)
    if not score:
        return None
    home, away = score.split("-")
    return int(home), int(away)


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def _normalise_probabilities(values: Mapping[str, Any]) -> dict[str, float] | None:
    result = {key: _finite_number(values.get(key)) for key in ("home", "draw", "away")}
    if any(value is None or value < 0 for value in result.values()):
        return None
    total = sum(float(value) for value in result.values())
    if total <= 0:
        return None
    return {key: round(float(value) / total, 12) for key, value in result.items()}


def _required_result_reason(row: Mapping[str, Any]) -> str | None:
    required = ("canonical_match_id", "competition_id", "home_team_id", "away_team_id", "kickoff_at", "home_goals", "away_goals")
    if any(row.get(key) in (None, "") for key in required):
        return "missing_required_result"
    if _parse_time(row.get("kickoff_at")) is None:
        return "invalid_kickoff"
    if _finite_number(row.get("home_goals")) is None or _finite_number(row.get("away_goals")) is None:
        return "missing_required_result"
    if row.get("eligible_for_team_strength") is not True:
        return "not_eligible_for_team_strength"
    if row.get("duplicate_status") not in {"unique", "duplicate_same"}:
        return "duplicate_or_conflicting"
    if row.get("source_conflict") is True:
        return "source_conflict"
    if row.get("entity_type", "club") != "club":
        return "non_club_entity"
    return None


def dataset_gate(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate the historical result contract without changing any row."""

    eligible: list[dict[str, Any]] = []
    excluded = Counter()
    seen: set[str] = set()
    for input_row in records:
        row = dict(input_row)
        reason = _required_result_reason(row)
        match_id = str(row.get("canonical_match_id") or "")
        if reason is None and match_id in seen:
            reason = "duplicate_canonical_match_id"
        if reason is None:
            seen.add(match_id)
            row["home_goals"] = int(row["home_goals"])
            row["away_goals"] = int(row["away_goals"])
            eligible.append(row)
        else:
            excluded[reason] += 1
    eligible.sort(key=_sort_key)
    return {
        "required_fields": ["date/kickoff_at", "competition_id", "home_team_id", "away_team_id", "home_goals", "away_goals"],
        "input_count": len(eligible) + sum(excluded.values()),
        "eligible_count": len(eligible),
        "excluded_count": sum(excluded.values()),
        "excluded_by_reason": dict(sorted(excluded.items())),
        "eligible_records": eligible,
    }


def chronological_split(records: Sequence[Mapping[str, Any]], *, train_fraction: float = 0.6, validation_fraction: float = 0.2) -> dict[str, Any]:
    """Create a deterministic chronological train/validation/holdout split."""

    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise ValueError("fractions must be positive and leave a holdout")
    ordered = sorted((dict(row) for row in records), key=_sort_key)
    count = len(ordered)
    train_end = max(1, int(count * train_fraction))
    train_end = _time_boundary(ordered, train_end)
    validation_size = max(1, int(count * validation_fraction))
    validation_end = min(count - 1, train_end + validation_size)
    validation_end = _time_boundary(ordered, validation_end)
    if validation_end <= train_end:
        validation_end = min(count - 1, train_end + 1)
    train = ordered[:train_end]
    validation = ordered[train_end:validation_end]
    holdout = ordered[validation_end:]
    return {
        "train": train,
        "validation": validation,
        "holdout": holdout,
        "fractions": {"train": train_fraction, "validation": validation_fraction, "holdout": 1 - train_fraction - validation_fraction},
        "ranges": {name: _range_metadata(rows) for name, rows in (("train", train), ("validation", validation), ("holdout", holdout))},
    }


def _time_boundary(rows: Sequence[Mapping[str, Any]], index: int) -> int:
    """Move a split boundary left so one kickoff timestamp is never split."""

    index = max(1, min(len(rows) - 1, index)) if len(rows) > 1 else len(rows)
    while 0 < index < len(rows) and _parse_time(rows[index - 1].get("kickoff_at")) == _parse_time(rows[index].get("kickoff_at")):
        index -= 1
    return index


def _range_metadata(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "start": _iso(rows[0].get("kickoff_at")) if rows else None,
        "end": _iso(rows[-1].get("kickoff_at")) if rows else None,
        "min_date": _iso(rows[0].get("kickoff_at"))[:10] if rows and _iso(rows[0].get("kickoff_at")) else None,
        "max_date": _iso(rows[-1].get("kickoff_at"))[:10] if rows and _iso(rows[-1].get("kickoff_at")) else None,
    }


def assert_evaluation_ids_not_in_history(history: Iterable[Mapping[str, Any]], evaluation_ids: Iterable[str]) -> None:
    overlap = {str(row.get("canonical_match_id")) for row in history} & {str(value) for value in evaluation_ids}
    if overlap:
        raise ValueError(f"evaluation IDs must not be in training history: {sorted(overlap)[0]}")


def _canonical_value(record: Mapping[str, Any], key: str) -> Any:
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), Mapping) else {}
    return record.get(key) if record.get(key) not in (None, "") else identity.get(key)


def prediction_record_target(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only explicit canonical identity; never fuzzy-resolve names."""

    match_id = _canonical_value(record, "canonical_match_id") or _canonical_value(record, "match_id") or _canonical_value(record, "match_key")
    competition = _canonical_value(record, "competition_id")
    home_id = _canonical_value(record, "home_team_id")
    away_id = _canonical_value(record, "away_team_id")
    kickoff = _canonical_value(record, "kickoff_at") or record.get("kickoff")
    if not all((match_id, competition, home_id, away_id, _parse_time(kickoff))):
        return {
            "status": "IDENTITY_UNAVAILABLE",
            "target": None,
            "reason": "canonical home/away team IDs and competition are not explicitly persisted; names are not fuzzy-resolved",
        }
    return {
        "status": "AVAILABLE",
        "target": {
            "canonical_match_id": str(match_id),
            "competition_id": str(competition),
            "season_id": str(_canonical_value(record, "season_id") or "unknown"),
            "home_team_id": str(home_id),
            "away_team_id": str(away_id),
            "kickoff_at": _iso(kickoff),
        },
        "reason": None,
    }


def _identity_alias(value: Any) -> str:
    """Normalize an identity alias without doing similarity matching."""

    if value in (None, ""):
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return "".join(character for character in normalized if character.isalnum())


def _identity_source_items(payload: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    for key in ("teams", "mappings", "entries", "competitions"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _identity_competition_context(item: Mapping[str, Any]) -> list[str]:
    value = item.get("competition") or item.get("competition_id") or item.get("competition_context") or []
    if isinstance(value, str):
        return [value]
    return [str(entry) for entry in value if entry not in (None, "")] if isinstance(value, list) else []


def _add_identity_candidate(index: dict[str, Any], alias: Any, candidate: Mapping[str, Any]) -> None:
    key = _identity_alias(alias)
    if not key:
        return
    values = index["alias_index"][key]
    candidate_key = (candidate.get("canonical_team_id"), tuple(candidate.get("competition_ids") or ()))
    if not any((item.get("canonical_team_id"), tuple(item.get("competition_ids") or ())) == candidate_key for item in values):
        values.append(dict(candidate))


def _add_provider_candidate(index: dict[str, Any], provider: Any, provider_team_id: Any, candidate: Mapping[str, Any]) -> None:
    if provider in (None, "") or provider_team_id in (None, ""):
        return
    key = (str(provider).casefold(), str(provider_team_id))
    values = index["provider_index"][key]
    candidate_key = (candidate.get("canonical_team_id"), tuple(candidate.get("competition_ids") or ()))
    if not any((item.get("canonical_team_id"), tuple(item.get("competition_ids") or ())) == candidate_key for item in values):
        values.append(dict(candidate))


def _register_identity_item(index: dict[str, Any], item: Mapping[str, Any], *, source_key: str) -> None:
    canonical_team_id = item.get("canonical_team_id")
    if not canonical_team_id:
        return
    competition_ids = _identity_competition_context(item)
    candidate = {
        "canonical_team_id": str(canonical_team_id),
        "canonical_name": item.get("canonical_name") or item.get("canonical") or item.get("name"),
        "competition_ids": competition_ids,
        "provider": item.get("provider"),
        "provider_team_id": item.get("provider_team_id"),
        "source_key": source_key,
        "resolution_method": item.get("resolution_method") or item.get("verification_method"),
        "verified": item.get("verified") is not False,
        "evidence": {
            "source_refs": item.get("source_refs") or [],
            "source_ref": item.get("source_ref"),
            "verification_evidence_digest": item.get("verification_evidence_digest"),
        },
    }
    names: list[Any] = [item.get("canonical_name"), item.get("canonical"), item.get("name"), item.get("provider_team_name")]
    aliases = item.get("aliases")
    if isinstance(aliases, list):
        names.extend(aliases)
    provider_aliases = item.get("provider_team_aliases")
    if isinstance(provider_aliases, list):
        names.extend(provider_aliases)
    for name in names:
        _add_identity_candidate(index, name, candidate)
    _add_provider_candidate(index, item.get("provider"), item.get("provider_team_id"), candidate)


def _register_team_registry_item(index: dict[str, Any], item: Mapping[str, Any], *, source_key: str) -> None:
    _register_identity_item(index, item, source_key=source_key)
    parent_id = item.get("canonical_team_id")
    for mapping in item.get("provider_mappings") or []:
        if not isinstance(mapping, Mapping) or not parent_id:
            continue
        child = dict(mapping)
        child["canonical_team_id"] = parent_id
        child["canonical_name"] = item.get("canonical_name")
        child["competition_context"] = child.get("competition_context") or item.get("competition_context")
        _register_identity_item(index, child, source_key=f"{source_key}.provider_mappings")


def build_identity_bridge_index(
    historical_records: Sequence[Mapping[str, Any]],
    *,
    team_alias_registry: Mapping[str, Any] | None = None,
    verified_crosswalk: Mapping[str, Any] | None = None,
    project_crosswalk: Mapping[str, Any] | None = None,
    competition_registry: Mapping[str, Any] | None = None,
    minimum_history: int = 5,
) -> dict[str, Any]:
    """Build a deterministic, research-only identity index.

    The index accepts only existing verified registries/crosswalks.  It never
    creates IDs from names and intentionally has no similarity/fuzzy matcher.
    """

    index: dict[str, Any] = {
        "alias_index": defaultdict(list),
        "provider_index": defaultdict(list),
        "competition_aliases": defaultdict(set),
        "historical_team_ids": set(),
        "historical_competition_ids": set(),
        "historical_records": [dict(row) for row in historical_records],
        "minimum_history": int(minimum_history),
        "source_files": [],
    }
    for row in historical_records:
        if row.get("home_team_id"):
            index["historical_team_ids"].add(str(row["home_team_id"]))
        if row.get("away_team_id"):
            index["historical_team_ids"].add(str(row["away_team_id"]))
        if row.get("competition_id"):
            index["historical_competition_ids"].add(str(row["competition_id"]))
        for field in ("competition", "raw_competition", "provider_competition_name"):
            value = row.get(field)
            if value not in (None, "") and row.get("competition_id"):
                index["competition_aliases"][_identity_alias(value)].add(str(row["competition_id"]))

    team_sources = (
        ("team_alias_registry", team_alias_registry, True),
        ("verified_identity_crosswalk", verified_crosswalk, False),
        ("verified_project_provider_crosswalk", project_crosswalk, False),
    )
    for source_key, payload, nested_provider_mappings in team_sources:
        if payload is not None:
            index["source_files"].append(source_key)
        for item in _identity_source_items(payload):
            if nested_provider_mappings:
                _register_team_registry_item(index, item, source_key=source_key)
            else:
                _register_identity_item(index, item, source_key=source_key)

    for item in _identity_source_items(competition_registry):
        key = item.get("competition_key")
        canonical = item.get("canonical_competition_id")
        if not canonical and key and f"competition:{key}" in index["historical_competition_ids"]:
            canonical = f"competition:{key}"
        canonical = str(canonical) if canonical else None
        aliases = [item.get("name"), key, item.get("canonical_competition_id")]
        observed = item.get("observed_raw_names")
        if isinstance(observed, list):
            aliases.extend(observed)
        if canonical:
            for alias in aliases:
                if alias not in (None, ""):
                    index["competition_aliases"][_identity_alias(alias)].add(canonical)
        elif key:
            # Keep an explicit unsupported competition identity so that a
            # known but uncovered league is not mislabeled as team identity loss.
            for alias in aliases:
                if alias not in (None, ""):
                    index["competition_aliases"][_identity_alias(alias)].add(f"UNSUPPORTED:{key}")

    # Make every historical canonical ID directly resolvable when a fixture
    # carries an explicit canonical competition_id.
    for competition_id in index["historical_competition_ids"]:
        index["competition_aliases"][_identity_alias(competition_id)].add(competition_id)
    return index


def _fixture_identity_value(fixture: Mapping[str, Any], key: str) -> Any:
    value = fixture.get(key)
    if value not in (None, ""):
        return value
    identity = fixture.get("match_identity")
    return identity.get(key) if isinstance(identity, Mapping) else None


def _fixture_provider_signals(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    signals = fixture.get("production_identity_signals")
    return signals if isinstance(signals, Mapping) else {}


def _candidate_for_competition(candidate: Mapping[str, Any], competition_id: str | None) -> bool:
    contexts = [str(value) for value in candidate.get("competition_ids") or []]
    return not competition_id or not contexts or competition_id in contexts


def _resolve_team_identity(fixture: Mapping[str, Any], index: Mapping[str, Any], side: str, competition_id: str | None) -> dict[str, Any]:
    signals = _fixture_provider_signals(fixture)
    explicit = signals.get(f"{side}_canonical_team_id") or fixture.get(f"{side}_team_id")
    if explicit and str(explicit) in index["historical_team_ids"]:
        return {"status": "MAPPED", "canonical_team_id": str(explicit), "method": "explicit_canonical_id", "source_key": "production_identity_signals", "evidence": {"field": f"{side}_canonical_team_id"}}

    provider = signals.get("provider") or fixture.get("provider")
    provider_id = signals.get(f"{side}_provider_team_id")
    if provider_id in (None, ""):
        nested = signals.get(side)
        if isinstance(nested, Mapping):
            provider_id = nested.get("provider_team_id") or nested.get("team_id")
    if provider_id not in (None, ""):
        candidates = [candidate for candidate in index["provider_index"].get((str(provider).casefold(), str(provider_id)), []) if _candidate_for_competition(candidate, competition_id)]
        ids = {candidate.get("canonical_team_id") for candidate in candidates}
        if len(ids) == 1:
            candidate = next(candidate for candidate in candidates if candidate.get("canonical_team_id") in ids)
            return {"status": "MAPPED", "canonical_team_id": next(iter(ids)), "method": "provider_id_exact", "source_key": candidate.get("source_key"), "evidence": {"provider": provider, "provider_team_id": str(provider_id), **(candidate.get("evidence") or {})}}
        if len(ids) > 1:
            return {"status": "AMBIGUOUS_IDENTITY", "canonical_team_id": None, "method": "provider_id_exact", "source_key": "provider_index", "evidence": {"provider": provider, "provider_team_id": str(provider_id), "candidate_ids": sorted(ids)}}

    name = _fixture_identity_value(fixture, side)
    candidates = [candidate for candidate in index["alias_index"].get(_identity_alias(name), []) if _candidate_for_competition(candidate, competition_id)]
    ids = {candidate.get("canonical_team_id") for candidate in candidates}
    if len(ids) == 1:
        candidate = next(candidate for candidate in candidates if candidate.get("canonical_team_id") in ids)
        method = "registry_exact_alias" if candidate.get("source_key") == "team_alias_registry" else "verified_alias_exact"
        return {"status": "MAPPED", "canonical_team_id": next(iter(ids)), "method": method, "source_key": candidate.get("source_key"), "evidence": {"alias": name, **(candidate.get("evidence") or {})}}
    if len(ids) > 1:
        return {"status": "AMBIGUOUS_IDENTITY", "canonical_team_id": None, "method": "exact_alias", "source_key": "alias_index", "evidence": {"alias": name, "candidate_ids": sorted(ids)}}
    return {"status": "IDENTITY_UNAVAILABLE", "canonical_team_id": None, "method": None, "source_key": None, "evidence": {"alias": name, "reason": "no verified exact alias or provider ID"}}


def _prior_history_coverage(index: Mapping[str, Any], *, home_team_id: str, away_team_id: str, competition_id: str, kickoff_at: Any) -> dict[str, Any]:
    target_time = _parse_time(kickoff_at)
    prior = [row for row in index["historical_records"] if _parse_time(row.get("kickoff_at")) and target_time and _parse_time(row.get("kickoff_at")) < target_time and _required_result_reason(row) is None]
    competition_prior = [row for row in prior if str(row.get("competition_id")) == competition_id]
    minimum = int(index.get("minimum_history", 5))
    global_home = _team_count(prior, home_team_id)
    global_away = _team_count(prior, away_team_id)
    competition_home = _team_count(competition_prior, home_team_id)
    competition_away = _team_count(competition_prior, away_team_id)
    if len(competition_prior) >= 20 and competition_home >= minimum and competition_away >= minimum:
        scope = "competition_prior"
    else:
        scope = "global_fallback"
    eligible = global_home >= minimum and global_away >= minimum
    return {
        "eligible": eligible,
        "minimum_history": minimum,
        "home_prior_count": global_home,
        "away_prior_count": global_away,
        "competition_prior_count": len(competition_prior),
        "competition_home_prior_count": competition_home,
        "competition_away_prior_count": competition_away,
        "history_scope": scope,
        "reason": None if eligible else f"target requires {minimum} prior matches per team",
    }


def resolve_fixture_identity(fixture: Mapping[str, Any], *, index: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one production fixture with deterministic identity gates only."""

    competition_name = _fixture_identity_value(fixture, "competition") or _fixture_identity_value(fixture, "league")
    signals = _fixture_provider_signals(fixture)
    explicit_competition = signals.get("canonical_competition_id") or fixture.get("competition_id")
    competition_candidates = set()
    if explicit_competition:
        competition_candidates = {str(explicit_competition)}
    else:
        competition_candidates = set(index["competition_aliases"].get(_identity_alias(competition_name), set()))
    competition_ids = {value for value in competition_candidates if not str(value).startswith("UNSUPPORTED:")}
    unsupported = {value for value in competition_candidates if str(value).startswith("UNSUPPORTED:")}
    if len(competition_ids) > 1:
        competition_mapping = {"status": "AMBIGUOUS_IDENTITY", "canonical_competition_id": None, "method": "exact_competition_alias", "source_key": "competition_index", "evidence": {"alias": competition_name, "candidate_ids": sorted(competition_ids)}}
        competition_id = None
    elif len(competition_ids) == 1:
        competition_id = next(iter(competition_ids))
        competition_mapping = {"status": "MAPPED", "canonical_competition_id": competition_id, "method": "exact_competition_alias", "source_key": "competition_index", "evidence": {"alias": competition_name}}
    elif unsupported:
        competition_id = None
        competition_mapping = {"status": "UNSUPPORTED", "canonical_competition_id": None, "method": "known_competition_without_history", "source_key": "competition_registry", "evidence": {"alias": competition_name, "known_keys": sorted(unsupported)}}
    else:
        competition_id = None
        competition_mapping = {"status": "UNSUPPORTED", "canonical_competition_id": None, "method": None, "source_key": None, "evidence": {"alias": competition_name, "reason": "competition not in bounded historical registry"}}

    home = _resolve_team_identity(fixture, index, "home", competition_id)
    away = _resolve_team_identity(fixture, index, "away", competition_id)
    if competition_mapping["status"] != "MAPPED":
        final_status = "COMPETITION_UNSUPPORTED" if competition_mapping["status"] == "UNSUPPORTED" else "AMBIGUOUS_IDENTITY"
        historical = {"eligible": False, "reason": "competition identity is not uniquely supported"}
    elif home["status"] == "AMBIGUOUS_IDENTITY" or away["status"] == "AMBIGUOUS_IDENTITY":
        final_status = "AMBIGUOUS_IDENTITY"
        historical = {"eligible": False, "reason": "team identity is ambiguous"}
    elif home["status"] != "MAPPED" or away["status"] != "MAPPED":
        final_status = "IDENTITY_UNAVAILABLE"
        historical = {"eligible": False, "reason": "one or both team identities are unavailable"}
    else:
        historical = _prior_history_coverage(index, home_team_id=home["canonical_team_id"], away_team_id=away["canonical_team_id"], competition_id=competition_id, kickoff_at=_fixture_identity_value(fixture, "kickoff"))
        final_status = "MAPPED" if historical["eligible"] else "HISTORY_UNAVAILABLE"
    match_id = _fixture_identity_value(fixture, "match_id") or _fixture_identity_value(fixture, "match_key")
    target = None
    if final_status in {"MAPPED", "HISTORY_UNAVAILABLE"} and competition_id and home.get("canonical_team_id") and away.get("canonical_team_id"):
        target = {
            "canonical_match_id": str(match_id),
            "competition_id": competition_id,
            "season_id": str(signals.get("season_id") or fixture.get("season_id") or "unknown"),
            "home_team_id": home["canonical_team_id"],
            "away_team_id": away["canonical_team_id"],
            "kickoff_at": _iso(_fixture_identity_value(fixture, "kickoff")),
        }
    return {
        "match_id": match_id,
        "competition": competition_name,
        "home": _fixture_identity_value(fixture, "home"),
        "away": _fixture_identity_value(fixture, "away"),
        "production_identity_signals": dict(signals),
        "home_mapping": home,
        "away_mapping": away,
        "competition_mapping": competition_mapping,
        "identity_mapped": competition_mapping["status"] == "MAPPED" and home["status"] == "MAPPED" and away["status"] == "MAPPED",
        "historical_coverage": historical,
        "final_status": final_status,
        "target": target,
    }


def paired_subset(formal_rows: Sequence[Mapping[str, Any]], challenger_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the exact shared prediction-ID sample used by paired metrics."""

    formal_ids = {str(row.get("prediction_id")) for row in formal_rows if row.get("prediction_id")}
    challenger_ids = {str(row.get("prediction_id")) for row in challenger_rows if row.get("prediction_id") and row.get("status") == "AVAILABLE"}
    return sorted(formal_ids & challenger_ids)


def _eligible_prior(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]], *, competition: str | None = None) -> list[dict[str, Any]]:
    target_time = _parse_time(target.get("kickoff_at"))
    if target_time is None:
        raise ValueError("target kickoff_at is required")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for input_row in records:
        row = dict(input_row)
        match_id = str(row.get("canonical_match_id") or "")
        kickoff = _parse_time(row.get("kickoff_at"))
        if not match_id or match_id in seen or kickoff is None or kickoff >= target_time:
            continue
        if _required_result_reason(row) is not None:
            continue
        if competition is not None and str(row.get("competition_id")) != competition:
            continue
        seen.add(match_id)
        rows.append(row)
    return sorted(rows, key=_sort_key)


def _team_count(rows: Sequence[Mapping[str, Any]], team_id: str) -> int:
    return sum(1 for row in rows if str(row.get("home_team_id")) == team_id or str(row.get("away_team_id")) == team_id)


def _fit_opponent_strength_fast(records: Sequence[Mapping[str, Any]], *, regularization: int, tolerance: float = 1e-8, max_iterations: int = 200) -> dict[str, Any]:
    """Efficient equivalent of the existing research fixed-point equations.

    The older exploratory implementation repeatedly rebuilt four filtered row
    lists inside each team iteration.  This local research implementation
    keeps the same multiplicative equations but accumulates denominators in a
    single pass per iteration, which makes walk-forward evaluation practical.
    """

    if not records:
        raise InsufficientHistoryError("opponent solver has no history")
    teams = sorted({str(row["home_team_id"]) for row in records} | {str(row["away_team_id"]) for row in records})
    if len(teams) < 2:
        raise InsufficientHistoryError("opponent solver needs at least two teams")
    league_home = max(sum(int(row["home_goals"]) for row in records) / len(records), 1e-9)
    league_away = max(sum(int(row["away_goals"]) for row in records) / len(records), 1e-9)
    home_attack = {team: 1.0 for team in teams}
    away_attack = {team: 1.0 for team in teams}
    home_defence = {team: 1.0 for team in teams}
    away_defence = {team: 1.0 for team in teams}
    observed = {team: {"home_scored": 0, "away_scored": 0, "home_conceded": 0, "away_conceded": 0} for team in teams}
    for row in records:
        home, away = str(row["home_team_id"]), str(row["away_team_id"])
        home_goals, away_goals = int(row["home_goals"]), int(row["away_goals"])
        observed[home]["home_scored"] += home_goals
        observed[home]["home_conceded"] += away_goals
        observed[away]["away_scored"] += away_goals
        observed[away]["away_conceded"] += home_goals
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        home_attack_denominator = {team: 0.0 for team in teams}
        away_attack_denominator = {team: 0.0 for team in teams}
        home_defence_denominator = {team: 0.0 for team in teams}
        away_defence_denominator = {team: 0.0 for team in teams}
        for row in records:
            home, away = str(row["home_team_id"]), str(row["away_team_id"])
            home_attack_denominator[home] += league_home * away_defence[away]
            away_attack_denominator[away] += league_away * home_defence[home]
            home_defence_denominator[home] += league_away * away_attack[away]
            away_defence_denominator[away] += league_home * home_attack[home]
        next_home_attack = {team: (observed[team]["home_scored"] + regularization) / (home_attack_denominator[team] + regularization) for team in teams}
        next_away_attack = {team: (observed[team]["away_scored"] + regularization) / (away_attack_denominator[team] + regularization) for team in teams}
        next_home_defence = {team: (observed[team]["home_conceded"] + regularization) / (home_defence_denominator[team] + regularization) for team in teams}
        next_away_defence = {team: (observed[team]["away_conceded"] + regularization) / (away_defence_denominator[team] + regularization) for team in teams}
        damping = 0.5
        updated = {
            "attack_home": {team: damping * next_home_attack[team] + (1 - damping) * home_attack[team] for team in teams},
            "attack_away": {team: damping * next_away_attack[team] + (1 - damping) * away_attack[team] for team in teams},
            "defence_home": {team: damping * next_home_defence[team] + (1 - damping) * home_defence[team] for team in teams},
            "defence_away": {team: damping * next_away_defence[team] + (1 - damping) * away_defence[team] for team in teams},
        }
        difference = max(
            max(abs(updated["attack_home"][team] - home_attack[team]) for team in teams),
            max(abs(updated["attack_away"][team] - away_attack[team]) for team in teams),
            max(abs(updated["defence_home"][team] - home_defence[team]) for team in teams),
            max(abs(updated["defence_away"][team] - away_defence[team]) for team in teams),
        )
        home_attack, away_attack = updated["attack_home"], updated["attack_away"]
        home_defence, away_defence = updated["defence_home"], updated["defence_away"]
        iterations = iteration
        if difference <= tolerance:
            converged = True
            break
    all_values = [value for mapping in (home_attack, away_attack, home_defence, away_defence) for value in mapping.values()]
    if not all(isfinite(value) and value > 0 for value in all_values):
        raise ValueError("opponent solver produced a non-finite or non-positive strength")
    return {"league_home_goal_rate": league_home, "league_away_goal_rate": league_away, "attack_home": home_attack, "attack_away": away_attack, "defence_home": home_defence, "defence_away": away_defence, "solver": "multiplicative_fixed_point", "converged": converged, "iterations": iterations, "max_iterations": max_iterations, "convergence_tolerance": tolerance}


def build_opponent_adjusted_shadow(target: Mapping[str, Any], records: Iterable[Mapping[str, Any]], spec: ChallengerSpec) -> dict[str, Any]:
    """Fit the research formula on strict prior results and return a shadow prediction."""

    all_prior = _eligible_prior(target, records)
    competition = str(target.get("competition_id") or "")
    competition_prior = [row for row in all_prior if str(row.get("competition_id")) == competition]
    home_id, away_id = str(target.get("home_team_id") or ""), str(target.get("away_team_id") or "")
    if not home_id or not away_id:
        return {"status": "IDENTITY_UNAVAILABLE", "reason": "canonical target team IDs are required"}
    if len(competition_prior) >= spec.competition_minimum_rows and _team_count(competition_prior, home_id) >= spec.minimum_history and _team_count(competition_prior, away_id) >= spec.minimum_history:
        history = competition_prior
        history_scope = "competition_prior"
    else:
        history = all_prior
        history_scope = "global_fallback"
    if _team_count(history, home_id) < spec.minimum_history or _team_count(history, away_id) < spec.minimum_history:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": f"target requires {spec.minimum_history} prior matches per team",
            "features": {"history_scope": history_scope, "history_count": len(history), "target_result_excluded": True},
        }
    try:
        fitted = _fit_opponent_strength_fast(history, regularization=spec.regularization)
        lambda_home = fitted["league_home_goal_rate"] * fitted["attack_home"][home_id] * fitted["defence_away"][away_id]
        lambda_away = fitted["league_away_goal_rate"] * fitted["attack_away"][away_id] * fitted["defence_home"][home_id]
        payload = probability_payload(lambda_home, lambda_away)
    except (KeyError, InsufficientHistoryError, ValueError) as exc:
        return {"status": "INSUFFICIENT_HISTORY", "reason": str(exc), "features": {"history_scope": history_scope, "history_count": len(history), "target_result_excluded": True}}
    features = {
        "history_scope": history_scope,
        "history_count": len(history),
        "used_match_ids": [str(row["canonical_match_id"]) for row in history],
        "used_kickoffs": [str(row["kickoff_at"]) for row in history],
        "target_result_excluded": True,
        "opponent_strength_used": True,
        "market_used": False,
        "xg_used": False,
        "recency_policy": spec.recency_policy,
        "rho": spec.rho,
        "regularization": spec.regularization,
        "league_home_goal_rate": fitted["league_home_goal_rate"],
        "league_away_goal_rate": fitted["league_away_goal_rate"],
        "home_advantage_goal_rate": fitted["league_home_goal_rate"] - fitted["league_away_goal_rate"],
        "home_advantage_ratio": fitted["league_home_goal_rate"] / fitted["league_away_goal_rate"] if fitted["league_away_goal_rate"] else None,
        "solver": {key: fitted[key] for key in ("solver", "converged", "iterations", "max_iterations", "convergence_tolerance")},
        "as_of_at": str(target.get("kickoff_at")),
        "formula_version": spec.formula_version,
    }
    return {
        "status": "AVAILABLE",
        "model_name": CHALLENGER_NAME,
        "model_kind": "research_shadow_only",
        "lambda_home": float(lambda_home),
        "lambda_away": float(lambda_away),
        "probabilities": payload,
        "top_scores": payload["top_scores"],
        "score_matrix": payload["score_matrix"],
        "features": features,
        "spec": asdict(spec),
    }


def market_only_from_record(record: Mapping[str, Any]) -> dict[str, float] | None:
    candidates: list[Any] = [record.get("market_only_baseline")]
    for container_key in ("prediction_output", "prediction"):
        container = record.get(container_key)
        if isinstance(container, Mapping):
            candidates.append(container.get("market_only_baseline"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            result = _normalise_probabilities(candidate)
            if result is not None:
                return result
    return None


def blend_one_x_two(football: Mapping[str, Any], market: Mapping[str, Any], *, weight: float = 0.5) -> dict[str, float]:
    if not 0 <= weight <= 1:
        raise ValueError("weight must be between 0 and 1")
    left = _normalise_probabilities(football)
    right = _normalise_probabilities(market)
    if left is None or right is None:
        raise ValueError("both probability vectors must be valid")
    return _normalise_probabilities({key: round((1 - weight) * left[key] + weight * right[key], 12) for key in left}) or {}


def uniform_one_x_two() -> dict[str, float]:
    return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


def _prediction_probabilities(prediction: Mapping[str, Any]) -> dict[str, float] | None:
    value = prediction.get("probabilities")
    if isinstance(value, Mapping) and isinstance(value.get("1x2"), Mapping):
        return _normalise_probabilities(value["1x2"])
    if isinstance(value, Mapping):
        return _normalise_probabilities(value)
    return None


def _row_score_probability(prediction: Mapping[str, Any], actual_score: str) -> float | None:
    explicit = _finite_number(prediction.get("actual_score_probability"))
    if explicit is not None and explicit > 0:
        return explicit
    parts = _score_parts(actual_score)
    if parts is None:
        return None
    home, away = parts
    matrix = prediction.get("score_matrix")
    if isinstance(matrix, Mapping):
        row = matrix.get(str(home))
        if isinstance(row, Mapping):
            value = _finite_number(row.get(str(away)))
            if value is not None and value > 0:
                return value
    for candidate_key in ("top_scores", "score_distribution"):
        values = prediction.get(candidate_key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, Mapping) and _score_string(item) == actual_score:
                    value = _finite_number(item.get("probability"))
                    if value is not None and value > 0:
                        return value
    return None


def _prediction_top_scores(prediction: Mapping[str, Any]) -> list[str]:
    values = prediction.get("top_scores") or prediction.get("score_distribution") or []
    output: list[str] = []
    if isinstance(values, list):
        for item in values:
            score = _score_string(item.get("score")) if isinstance(item, Mapping) else _score_string(item)
            if score is None and isinstance(item, Mapping):
                score = _score_string(item)
            if score and score not in output:
                output.append(score)
    return output


def _actual_score_from_row(row: Mapping[str, Any]) -> str | None:
    return _score_string(row.get("actual_score"))


def _metric_eligible_row(row: Mapping[str, Any]) -> bool:
    if str(row.get("status", "AVAILABLE")) != "AVAILABLE" or not _actual_score_from_row(row):
        return False
    prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
    return _prediction_probabilities(prediction) is not None


def validation_row_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Reconcile validation totals instead of conflating availability and metrics."""

    available = sum(str(row.get("status", "AVAILABLE")) == "AVAILABLE" for row in rows)
    insufficient = sum(str(row.get("status", "")) == "INSUFFICIENT_HISTORY" for row in rows)
    metric_eligible = sum(_metric_eligible_row(row) for row in rows)
    return {
        "validation_total": len(rows),
        "available": available,
        "metric_eligible": metric_eligible,
        "insufficient": insufficient,
        "available_not_metric_eligible": max(0, available - metric_eligible),
        "other_unavailable": max(0, len(rows) - available - insufficient),
    }


def _score_nll_detail(prediction: Mapping[str, Any], actual_score: str) -> tuple[float | None, str | None, bool]:
    stored = _finite_number(prediction.get("actual_score_nll"))
    status = str(prediction.get("actual_score_nll_status") or "")
    probability = _row_score_probability(prediction, actual_score)
    reconstructed = -log(probability) if probability is not None and probability > 0 else None
    if status == "UNAVAILABLE_IN_FROZEN_RECORD":
        return None, "UNAVAILABLE_IN_FROZEN_RECORD", False
    if stored is not None and reconstructed is not None and abs(stored - reconstructed) > 1e-6:
        return None, "NLL_RECONSTRUCTION_MISMATCH", True
    if stored is not None:
        return stored, None, False
    if reconstructed is not None:
        return reconstructed, None, False
    return None, "MISSING_FROZEN_ACTUAL_SCORE_PROBABILITY", False


def summarise_prediction_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate paired metrics for rows with explicit actual outcomes."""

    available = [row for row in rows if _metric_eligible_row(row)]
    brier_values: list[float] = []
    logloss_values: list[float] = []
    home_errors: list[float] = []
    away_errors: list[float] = []
    total_errors: list[float] = []
    top_hits = {key: 0 for key in SCORE_TOP_K}
    outcome_hits = 0
    score_nll: list[float] = []
    entropy_values: list[float] = []
    one_one = 0
    draw_score = 0
    predicted_one_one = 0
    lambda_gaps: list[float] = []
    ranked_score_rows = 0
    reliability: dict[str, dict[str, Any]] = {}
    nll_unavailable_reasons: Counter[str] = Counter()
    nll_mismatch_ids: list[str] = []
    for row in available:
        actual_score = _actual_score_from_row(row)
        actual_parts = _score_parts(actual_score)
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        probabilities = _prediction_probabilities(prediction)
        if actual_parts is None or probabilities is None:
            continue
        actual_home, actual_away = actual_parts
        actual_outcome = _outcome(actual_home, actual_away)
        target = {key: 1.0 if key == actual_outcome else 0.0 for key in probabilities}
        brier_values.append(sum((probabilities[key] - target[key]) ** 2 for key in probabilities))
        logloss_values.append(-log(max(probabilities[actual_outcome], _EPSILON)))
        lambda_home = _finite_number(prediction.get("lambda_home"))
        lambda_away = _finite_number(prediction.get("lambda_away"))
        if lambda_home is not None and lambda_away is not None:
            home_errors.append(abs(lambda_home - actual_home))
            away_errors.append(abs(lambda_away - actual_away))
            total_errors.append(abs(lambda_home + lambda_away - actual_home - actual_away))
            lambda_gaps.append(abs(lambda_home - lambda_away))
        ranked = _prediction_top_scores(prediction)
        if ranked:
            ranked_score_rows += 1
            predicted_one_one += int(ranked[0] == "1-1")
        for key in SCORE_TOP_K:
            if actual_score in ranked[:key]:
                top_hits[key] += 1
        if max(probabilities, key=probabilities.get) == actual_outcome:
            outcome_hits += 1
        nll_value, nll_reason, nll_mismatch = _score_nll_detail(prediction, actual_score)
        if nll_value is not None:
            score_nll.append(nll_value)
        elif nll_reason:
            nll_unavailable_reasons[nll_reason] += 1
            if nll_mismatch:
                nll_mismatch_ids.append(str(row.get("match_id") or row.get("prediction_id") or ""))
        matrix = prediction.get("score_matrix")
        if isinstance(matrix, Mapping):
            score_values = [float(value) for nested in matrix.values() if isinstance(nested, Mapping) for value in nested.values() if _finite_number(value) is not None and float(value) > 0]
            score_total = sum(score_values)
            if score_total > 0:
                entropy_values.append(-sum((value / score_total) * log(max(value / score_total, _EPSILON)) for value in score_values))
        one_one += actual_score == "1-1"
        draw_score += actual_home == actual_away
        favourite = max(probabilities.values())
        bucket = _reliability_bucket(favourite)
        item = reliability.setdefault(bucket, {"count": 0, "predicted_sum": 0.0, "actual_win_count": 0})
        item["count"] += 1
        item["predicted_sum"] += favourite
        item["actual_win_count"] += int(actual_outcome == max(probabilities, key=probabilities.get))
    sample = len(available)
    result = {
        "sample": sample,
        "one_x_two_brier": _mean(brier_values),
        "one_x_two_log_loss": _mean(logloss_values),
        "top1_outcome_accuracy": outcome_hits / sample if sample else None,
        "home_goals_mae": _mean(home_errors),
        "away_goals_mae": _mean(away_errors),
        "expected_total_goals_mae": _mean(total_errors),
        "exact_top1_accuracy": top_hits[1] / sample if sample and ranked_score_rows else None,
        "exact_top3_accuracy": top_hits[3] / sample if sample and ranked_score_rows else None,
        "exact_top5_accuracy": top_hits[5] / sample if sample and ranked_score_rows else None,
        "score_nll_available_count": len(score_nll),
        "score_nll_unavailable_count": max(0, sample - len(score_nll)),
        "score_nll_unavailable_reasons": dict(sorted(nll_unavailable_reasons.items())),
        "nll_reconstruction_mismatch_count": len(nll_mismatch_ids),
        "nll_reconstruction_mismatch_ids": nll_mismatch_ids,
        "mean_score_nll_available_only": _mean(score_nll),
        "unique_score_entropy": _mean(entropy_values),
        "predicted_top1_one_one_share": predicted_one_one / ranked_score_rows if ranked_score_rows else None,
        "actual_one_one_share": one_one / sample if sample else None,
        "actual_draw_score_share": draw_score / sample if sample else None,
        "mean_abs_lambda_gap": _mean(lambda_gaps),
        "reliability_buckets": _finish_reliability(reliability),
    }
    return result


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 12) if values else None


def _reliability_bucket(value: float) -> str:
    if value >= 0.65:
        return ">=0.65"
    if value >= 0.60:
        return "0.60-<0.65"
    if value >= 0.55:
        return "0.55-<0.60"
    if value >= 0.50:
        return "0.50-<0.55"
    return "<0.50"


def reliability_bucket(value: float) -> str:
    return _reliability_bucket(value)


def _finish_reliability(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    order = ("<0.50", "0.50-<0.55", "0.55-<0.60", "0.60-<0.65", ">=0.65")
    for key in order:
        if key not in values:
            continue
        item = values[key]
        count = int(item["count"])
        result[key] = {
            "count": count,
            "predicted_favourite_probability": item["predicted_sum"] / count if count else None,
            "actual_favourite_win_rate": item["actual_win_count"] / count if count else None,
            "small_sample": count < 10,
        }
    return result


def strong_favourite_diagnostics(rows: Sequence[Mapping[str, Any]], *, thresholds: Sequence[float] = (0.55, 0.60, 0.65)) -> dict[str, Any]:
    """Report cumulative p(favourite) thresholds, not mutually-exclusive bins."""

    output: dict[str, Any] = {}
    for threshold in thresholds:
        selected: list[tuple[Mapping[str, Any], dict[str, float], str, str]] = []
        for row in rows:
            actual_score = _actual_score_from_row(row)
            prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
            probabilities = _prediction_probabilities(prediction)
            if not actual_score or probabilities is None:
                continue
            actual_parts = _score_parts(actual_score)
            if actual_parts is None:
                continue
            favourite = max(probabilities.values())
            if favourite >= threshold:
                actual_outcome = _outcome(*actual_parts)
                selected.append((row, probabilities, actual_outcome, max(probabilities, key=probabilities.get)))
        brier = []
        logloss = []
        for _, probabilities, actual_outcome, _ in selected:
            target = {key: float(key == actual_outcome) for key in probabilities}
            brier.append(sum((probabilities[key] - target[key]) ** 2 for key in probabilities))
            logloss.append(-log(max(probabilities[actual_outcome], _EPSILON)))
        output[f">={threshold:.2f}"] = {
            "count": len(selected),
            "mean_predicted_probability": _mean([max(probabilities.values()) for _, probabilities, _, _ in selected]),
            "actual_win_rate": sum(actual_outcome == leader for _, _, actual_outcome, leader in selected) / len(selected) if selected else None,
            "one_x_two_brier": _mean(brier),
            "one_x_two_log_loss": _mean(logloss),
            "small_sample": len(selected) < 10,
            "prediction_ids": [str(row.get("prediction_id") or row.get("match_id") or "") for row, _, _, _ in selected],
        }
    return output


def _actual_score(row: Mapping[str, Any]) -> str | None:
    if _score_string(row.get("actual_score")):
        return _score_string(row.get("actual_score"))
    home = _finite_number(row.get("home_goals"))
    away = _finite_number(row.get("away_goals"))
    return f"{int(home)}-{int(away)}" if home is not None and away is not None else None


def _make_historical_row(target: Mapping[str, Any], prediction: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": prediction.get("status"), "match_id": target.get("canonical_match_id"), "actual_score": _actual_score(target), "prediction": prediction}


def _walk_forward_predictions(targets: Sequence[Mapping[str, Any]], all_history: Sequence[Mapping[str, Any]], spec: ChallengerSpec) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    leakage: list[dict[str, Any]] = []
    for target in sorted(targets, key=_sort_key):
        prediction = build_opponent_adjusted_shadow(target, all_history, spec)
        target_time = _parse_time(target.get("kickoff_at"))
        used = prediction.get("features", {}).get("used_kickoffs", []) if isinstance(prediction.get("features"), Mapping) else []
        training_times = [_parse_time(value) for value in used]
        training_times = [value for value in training_times if value]
        training_max = max(training_times) if training_times else None
        if target_time and training_max and not training_max < target_time:
            leakage.append({"match_id": target.get("canonical_match_id"), "training_max": _iso(training_max), "target": _iso(target_time)})
        rows.append(_make_historical_row(target, prediction))
    return rows, leakage


def evaluate_historical_walk_forward(records: Sequence[Mapping[str, Any]], *, specs: Sequence[ChallengerSpec] | None = None) -> dict[str, Any]:
    split = chronological_split(records)
    candidates = list(specs or [ChallengerSpec(regularization=value) for value in (5, 10, 20)])
    validation_results: list[dict[str, Any]] = []
    validation_rows_by_id: dict[str, list[dict[str, Any]]] = {}
    leakage: list[dict[str, Any]] = []
    for spec in candidates:
        rows, errors = _walk_forward_predictions(split["validation"], records, spec)
        metrics = summarise_prediction_rows(rows)
        validation_results.append({"spec_id": f"regularization:{spec.regularization}", "regularization": spec.regularization, **metrics})
        validation_rows_by_id[str(spec.regularization)] = rows
        leakage.extend(errors)
    usable_candidates = [row for row in validation_results if row.get("one_x_two_log_loss") is not None]
    selected_result = min(usable_candidates, key=lambda row: (row["one_x_two_log_loss"], row.get("one_x_two_brier") or float("inf"), row.get("mean_score_nll_available_only") or float("inf"), row["regularization"])) if usable_candidates else None
    selected_spec = next((spec for spec in candidates if selected_result and spec.regularization == selected_result["regularization"]), candidates[0])
    holdout_rows, errors = _walk_forward_predictions(split["holdout"], records, selected_spec)
    leakage.extend(errors)
    selected_validation_rows = validation_rows_by_id.get(str(selected_spec.regularization), [])
    return {
        "split": {"ranges": split["ranges"], "counts": {key: len(split[key]) for key in ("train", "validation", "holdout")}},
        "candidate_validation_metrics": validation_results,
        "validation_reconciliation": validation_row_counts(selected_validation_rows),
        "selected_spec": asdict(selected_spec),
        "selection_reason": "minimum validation 1X2 log loss, then Brier, then score NLL; deterministic tie-break by regularization",
        "holdout_metrics": summarise_prediction_rows(holdout_rows),
        "holdout_rows": holdout_rows,
        "leakage_audit": {"status": "LEAKAGE_FAIL" if leakage else "PASS", "violations": leakage, "every_training_max_before_target": not leakage},
    }


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _load_prediction_records(root: Path) -> list[dict[str, Any]]:
    directory = root / "data" / "model_governance" / "predictions"
    output: list[dict[str, Any]] = []
    if not directory.exists():
        return output
    for path in sorted(directory.glob("*.json")):
        value = _json_load(path)
        if isinstance(value, Mapping):
            item = dict(value)
            item["_artifact_path"] = str(path.relative_to(root))
            output.append(item)
    return output


def _load_dashboard_fixtures(root: Path, business_date: str) -> dict[str, dict[str, Any]]:
    path = root / "data" / "prediction_dashboard" / "latest.json"
    value = _json_load(path)
    if not isinstance(value, Mapping) or str(value.get("business_date")) != str(business_date):
        return {}
    fixtures = value.get("fixtures")
    if not isinstance(fixtures, list):
        return {}
    return {
        str(item.get("match_id")): dict(item)
        for item in fixtures
        if isinstance(item, Mapping) and item.get("match_id")
    }


def _load_universe_fixtures(root: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    directory = root / "data" / "prediction_universe"
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        value = _json_load(path)
        if not isinstance(value, Mapping) or not isinstance(value.get("fixtures"), list):
            continue
        for fixture in value["fixtures"]:
            if isinstance(fixture, Mapping) and fixture.get("matchId"):
                output[str(fixture["matchId"])] = dict(fixture)
    return output


def _attach_fixture_projection(record: Mapping[str, Any], *, dashboard_fixtures: Mapping[str, Mapping[str, Any]] | None = None, universe_fixtures: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    output = dict(record)
    match_id = str(record.get("match_id") or "")
    fixture = None
    if dashboard_fixtures:
        fixture = dashboard_fixtures.get(match_id)
    if fixture is None and universe_fixtures:
        fixture = universe_fixtures.get(match_id)
    if fixture is not None:
        output["_fixture_projection"] = dict(fixture)
    return output


def _load_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "prospective" / "ledger.jsonl"
    output: list[dict[str, Any]] = []
    if not path.exists():
        return output
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            output.append(dict(value))
    return output


def _load_exclusion_ids(root: Path) -> set[str]:
    output: set[str] = set()
    directory = root / "data" / "model_governance" / "prediction_exclusions"
    for path in directory.glob("*.json") if directory.exists() else []:
        value = _json_load(path)
        if not isinstance(value, Mapping):
            continue
        for key in ("prediction_ids", "excluded_prediction_ids"):
            if isinstance(value.get(key), list):
                output.update(str(item) for item in value[key])
        if isinstance(value.get("exclusions"), list):
            for item in value["exclusions"]:
                output.add(str(item.get("prediction_id"))) if isinstance(item, Mapping) and item.get("prediction_id") else None
    return output


def _record_prediction_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("prediction_output", "prediction"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return value
    return record


def _record_probabilities(record: Mapping[str, Any]) -> dict[str, float] | None:
    for value in (record.get("probabilities"), record.get("fusion_1X2"), _record_prediction_payload(record).get("probabilities")):
        if isinstance(value, Mapping):
            result = _normalise_probabilities(value.get("1x2") if isinstance(value.get("1x2"), Mapping) else value)
            if result is not None:
                return result
    return None


def _record_top_scores(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("score_distribution", "top_scores"):
        value = record.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping) and _score_string(item.get("score"))]
    payload = _record_prediction_payload(record)
    for key in ("score_distribution", "top_scores"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping) and _score_string(item.get("score"))]
    return []


def _persisted_prediction(record: Mapping[str, Any], *, ledger_metrics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = _record_prediction_payload(record)
    probabilities = _record_probabilities(record)
    lambda_home = _finite_number(record.get("lambda_home", payload.get("lambda_home")))
    lambda_away = _finite_number(record.get("lambda_away", payload.get("lambda_away")))
    result = {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probabilities or {},
        "top_scores": _record_top_scores(record),
        "score_distribution": _record_top_scores(record),
    }
    metrics = ledger_metrics if isinstance(ledger_metrics, Mapping) else {}
    nll = _finite_number(metrics.get("actual_score_nll"))
    probability = _finite_number(metrics.get("actual_score_probability"))
    if nll is not None:
        result["actual_score_nll"] = nll
    if probability is not None and probability > 0:
        result["actual_score_probability"] = probability
    result["actual_score_nll_status"] = metrics.get("actual_score_nll_status")
    return result


def _record_actual(entry: Mapping[str, Any]) -> str | None:
    actual = entry.get("actual") if isinstance(entry.get("actual"), Mapping) else {}
    home = _finite_number(actual.get("home_score"))
    away = _finite_number(actual.get("away_score"))
    return f"{int(home)}-{int(away)}" if home is not None and away is not None else None


def _formal_rows(root: Path, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(record.get("prediction_id")): record for record in records if record.get("prediction_id")}
    exclusions = _load_exclusion_ids(root)
    universe_fixtures = _load_universe_fixtures(root)
    output: list[dict[str, Any]] = []
    for entry in _load_ledger(root):
        if not entry.get("formal_prospective_eligible"):
            continue
        prediction_id = str(entry.get("prediction_id") or "")
        if not prediction_id or prediction_id in exclusions or prediction_id not in by_id:
            continue
        actual_score = _record_actual(entry)
        if not actual_score:
            continue
        record = _attach_fixture_projection(by_id[prediction_id], universe_fixtures=universe_fixtures)
        output.append({"prediction_id": prediction_id, "record": record, "entry": entry, "actual_score": actual_score})
    return output


def _record_date(record: Mapping[str, Any]) -> str | None:
    value = record.get("business_date")
    return str(value) if value else None


def _current_records(records: Sequence[Mapping[str, Any]], business_date: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Load the current frozen fixture set from the dashboard projection.

    The dashboard projection is the canonical current-date fixture set.  This
    avoids dropping late-night fixtures whose UTC date differs from the
    Shanghai business date and keeps the research sidecar aligned with the
    23 frozen cards rather than the artifact file's local date field.
    """

    if root is None:
        return [dict(record) for record in records if _record_date(record) == business_date]
    dashboard = _load_dashboard_fixtures(root, business_date)
    by_id = {str(record.get("prediction_id")): record for record in records if record.get("prediction_id")}
    by_match = {str(record.get("match_id")): record for record in records if record.get("match_id")}
    output: list[dict[str, Any]] = []
    for fixture in dashboard.values():
        if str(fixture.get("status")) != "FROZEN":
            continue
        record = by_id.get(str(fixture.get("prediction_id"))) or by_match.get(str(fixture.get("match_id")))
        if record is None:
            record = {
                "prediction_id": fixture.get("prediction_id"),
                "match_id": fixture.get("match_id"),
                "prediction": fixture.get("prediction"),
                "business_date": business_date,
            }
        merged = _attach_fixture_projection(record, dashboard_fixtures=dashboard)
        merged["business_date"] = business_date
        merged["match_id"] = fixture.get("match_id")
        merged["prediction_id"] = fixture.get("prediction_id")
        if not isinstance(merged.get("prediction"), Mapping) and isinstance(fixture.get("prediction"), Mapping):
            merged["prediction"] = fixture["prediction"]
        output.append(merged)
    return output


def _method_rows(records: Sequence[Mapping[str, Any]], *, method: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if method == "CURRENT_BASELINE":
            prediction = _persisted_prediction(record)
        elif method == "MARKET_ONLY":
            market = market_only_from_record(record)
            if market is None:
                continue
            prediction = {"probabilities": market, "top_scores": []}
        elif method == "UNIFORM_1X2":
            prediction = {"probabilities": uniform_one_x_two(), "top_scores": []}
        else:
            continue
        rows.append({"status": "AVAILABLE", "prediction_id": record.get("prediction_id"), "actual_score": None, "prediction": prediction})
    return rows


def _paired_method_rows(formal: Sequence[Mapping[str, Any]], *, method: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in formal:
        record = item["record"]
        if method == "CURRENT_BASELINE":
            prediction = _persisted_prediction(record, ledger_metrics=item.get("entry", {}).get("metrics") if isinstance(item.get("entry"), Mapping) else None)
        elif method == "MARKET_ONLY":
            market = market_only_from_record(record)
            if market is None:
                continue
            prediction = {"probabilities": market, "top_scores": []}
        elif method == "UNIFORM_1X2":
            prediction = {"probabilities": uniform_one_x_two(), "top_scores": []}
        else:
            continue
        rows.append({"status": "AVAILABLE", "prediction_id": item["prediction_id"], "actual_score": item["actual_score"], "prediction": prediction})
    return rows


def _identity_gate_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = Counter(prediction_record_target(record)["status"] for record in records)
    return {"counts": dict(statuses), "available_count": statuses.get("AVAILABLE", 0), "identity_unavailable_count": statuses.get("IDENTITY_UNAVAILABLE", 0), "fuzzy_resolution_used": False}


def _record_identity_fixture(record: Mapping[str, Any]) -> dict[str, Any]:
    projection = record.get("_fixture_projection") if isinstance(record.get("_fixture_projection"), Mapping) else {}
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), Mapping) else {}
    snapshot_identity = record.get("snapshot_identity") if isinstance(record.get("snapshot_identity"), Mapping) else {}
    input_snapshot = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), Mapping) else {}

    def first(*values: Any) -> Any:
        return next((value for value in values if value not in (None, "")), None)

    signals: dict[str, Any] = {
        "provider": first(record.get("provider"), projection.get("provider")),
        "provider_match_id": first(record.get("provider_match_id"), projection.get("matchId")),
        "nowscore_match_id": projection.get("nowscoreId"),
        "shuju_match_id": projection.get("shujuId"),
        "canonical_competition_id": first(record.get("competition_id"), snapshot_identity.get("competition_id")),
        "home_canonical_team_id": first(record.get("home_team_id"), snapshot_identity.get("home_team_id")),
        "away_canonical_team_id": first(record.get("away_team_id"), snapshot_identity.get("away_team_id")),
        "home_provider_team_id": first(record.get("home_provider_team_id"), snapshot_identity.get("home_provider_team_id")),
        "away_provider_team_id": first(record.get("away_provider_team_id"), snapshot_identity.get("away_provider_team_id")),
        "source_refs": input_snapshot.get("source_refs") if isinstance(input_snapshot.get("source_refs"), list) else [],
    }
    provider_team_ids = first(record.get("provider_team_ids"), snapshot_identity.get("provider_team_ids"))
    if isinstance(provider_team_ids, Mapping):
        signals["home_provider_team_id"] = first(signals.get("home_provider_team_id"), provider_team_ids.get("home"))
        signals["away_provider_team_id"] = first(signals.get("away_provider_team_id"), provider_team_ids.get("away"))
    signals = {key: value for key, value in signals.items() if value not in (None, "", [])}
    return {
        "match_id": first(projection.get("match_id"), projection.get("matchId"), record.get("match_id"), record.get("match_key")),
        "competition": first(projection.get("competition"), projection.get("league"), record.get("competition"), record.get("league")),
        "home": first(projection.get("home"), projection.get("homeTeam"), identity.get("home")),
        "away": first(projection.get("away"), projection.get("awayTeam"), identity.get("away")),
        "kickoff": first(projection.get("kickoff"), projection.get("kickoff_at"), record.get("kickoff_at"), identity.get("kickoff_at")),
        "season_id": first(record.get("season_id"), snapshot_identity.get("season_id")),
        "production_identity_signals": signals,
    }


def _bridge_records(records: Sequence[Mapping[str, Any]], *, index: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        fixture = _record_identity_fixture(record)
        bridge = resolve_fixture_identity(fixture, index=index)
        bridge["prediction_id"] = record.get("prediction_id")
        bridge["record_match_id"] = record.get("match_id")
        bridge["fixture"] = {key: fixture.get(key) for key in ("match_id", "competition", "home", "away", "kickoff")}
        output.append(bridge)
    return output


def _coverage_summary(bridge_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row.get("final_status")) for row in bridge_rows)
    mapped = sum(bool(row.get("identity_mapped")) for row in bridge_rows)
    eligible = sum(row.get("final_status") == "MAPPED" for row in bridge_rows)
    by_competition: dict[str, Counter[str]] = defaultdict(Counter)
    for row in bridge_rows:
        by_competition[str(row.get("competition") or "UNKNOWN")][str(row.get("final_status"))] += 1
    return {
        "total": len(bridge_rows),
        "identity_mapped": mapped,
        "identity_unavailable": counts.get("IDENTITY_UNAVAILABLE", 0),
        "ambiguous": counts.get("AMBIGUOUS_IDENTITY", 0),
        "historical_eligible": eligible,
        "history_unavailable": counts.get("HISTORY_UNAVAILABLE", 0),
        "competition_unsupported": counts.get("COMPETITION_UNSUPPORTED", 0),
        "final_status_counts": dict(sorted(counts.items())),
        "by_competition": {key: dict(sorted(value.items())) for key, value in sorted(by_competition.items())},
    }


def _one_one_count(records: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for record in records:
        payload = _record_prediction_payload(record)
        if _score_string(record.get("unique_score")) == "1-1" or _score_string(record.get("score_top1")) == "1-1" or _score_string(payload.get("unique_score")) == "1-1" or _score_string(payload.get("primary_score")) == "1-1":
            count += 1
    return count


def _leader_counts(records: Sequence[Mapping[str, Any]], *, market: bool = False) -> dict[str, int]:
    counts = Counter()
    for record in records:
        probabilities = market_only_from_record(record) if market else _record_probabilities(record)
        if probabilities:
            counts[max(probabilities, key=probabilities.get)] += 1
    return {key: counts.get(key, 0) for key in ("home", "draw", "away")}


def _record_lambda_gap_stats(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    for record in records:
        home = _finite_number(record.get("lambda_home"))
        away = _finite_number(record.get("lambda_away"))
        if home is not None and away is not None:
            values.append(abs(home - away))
    return {"count": len(values), "mean": _mean(values), "min": min(values) if values else None, "max": max(values) if values else None, "lt_0_5_count": sum(value < 0.5 for value in values)}


def _strong_favourite_diagnostics(formal: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _paired_method_rows(formal, method="MARKET_ONLY")
    return strong_favourite_diagnostics(rows)


def _representative_rows(holdout_rows: Sequence[Mapping[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in [item for item in holdout_rows if item.get("status") == "AVAILABLE"][:limit]:
        target_id = row.get("match_id")
        actual = row.get("actual_score")
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        result.append({"match_id": target_id, "actual": actual, "challenger_top1": _prediction_top_scores(prediction)[:1], "challenger_lambda": [prediction.get("lambda_home"), prediction.get("lambda_away")], "current": "UNAVAILABLE_IN_HISTORICAL_STORE", "market": "UNAVAILABLE_IN_HISTORICAL_STORE"})
    return result


def _dataset_summary(records: Sequence[Mapping[str, Any]], gate: Mapping[str, Any], store: HistoricalResultStore) -> dict[str, Any]:
    competitions = Counter(str(row.get("competition_id")) for row in records)
    qualities = Counter(str(row.get("quality")) for row in records)
    duplicates = Counter(str(row.get("duplicate_status")) for row in records)
    kickoff_values = [_parse_time(row.get("kickoff_at")) for row in records]
    kickoff_values = [value for value in kickoff_values if value]
    return {"record_count": len(records), "eligible_count": gate["eligible_count"], "excluded_count": gate["excluded_count"], "excluded_by_reason": gate["excluded_by_reason"], "date_range": {"start": _iso(min(kickoff_values)) if kickoff_values else None, "end": _iso(max(kickoff_values)) if kickoff_values else None}, "competitions": dict(sorted(competitions.items())), "quality": dict(sorted(qualities.items())), "duplicates": dict(sorted(duplicates.items())), "dataset_digest": store.dataset_digest()}


def _cohort_metadata(*, scope: str, total: int, eligible_count: int, business_date: str | None = None, excluded_pilot_count: int = 0, legacy_label: str | None = None) -> dict[str, Any]:
    metadata = {
        "scope": scope,
        "business_date": business_date,
        "total": total,
        "eligible_count": eligible_count,
        "excluded_pilot_count": excluded_pilot_count,
    }
    if legacy_label:
        metadata["legacy_label_name"] = legacy_label
    return metadata


def run_research(*, root: Path, data_home: Path, business_date: str, output_dir: Path) -> dict[str, Any]:
    """Run the complete shadow study and write only to ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    store = HistoricalResultStore(data_home / "historical_results.duckdb")
    raw_records = list(store.iter_records())
    gate = dataset_gate(raw_records)
    records = gate["eligible_records"]
    historical = evaluate_historical_walk_forward(records)
    production_records = _load_prediction_records(root)
    current = _current_records(production_records, business_date, root=root)
    formal = _formal_rows(root, production_records)
    selected_spec = ChallengerSpec(**historical["selected_spec"])

    identity_sources = {
        "team_alias_registry": _json_load(root / "data" / "football_data" / "team_alias_registry.json"),
        "verified_crosswalk": _json_load(root / "data" / "football_data" / "verified_identity_crosswalk.json"),
        "project_crosswalk": _json_load(root / "data" / "football_data" / "verified_project_provider_crosswalk.json"),
        "competition_registry": _json_load(root / "data" / "football_data" / "competition_coverage_registry.json"),
    }
    identity_index = build_identity_bridge_index(records, **identity_sources, minimum_history=selected_spec.minimum_history)
    current_bridge = _bridge_records(current, index=identity_index)
    formal_bridge = _bridge_records([item["record"] for item in formal], index=identity_index)
    formal_bridge_by_id = {str(row.get("prediction_id")): row for row in formal_bridge}
    current_identity = _coverage_summary(current_bridge)
    formal_identity = _coverage_summary(formal_bridge)
    historical_metrics = historical["holdout_metrics"]

    formal_challenger_rows: list[dict[str, Any]] = []
    formal_replay_status = Counter()
    for item in formal:
        bridge = formal_bridge_by_id.get(str(item["prediction_id"]))
        if not bridge or bridge.get("final_status") != "MAPPED":
            formal_replay_status[str((bridge or {}).get("final_status") or "IDENTITY_UNAVAILABLE")] += 1
            continue
        prediction = build_opponent_adjusted_shadow(bridge["target"], records, selected_spec)
        formal_replay_status[prediction.get("status", "UNKNOWN")] += 1
        if prediction.get("status") == "AVAILABLE":
            formal_challenger_rows.append({
                "status": "AVAILABLE",
                "prediction_id": item["prediction_id"],
                "match_id": item["record"].get("match_id"),
                "actual_score": item["actual_score"],
                "prediction": prediction,
            })

    formal_paired_ids = paired_subset(formal, formal_challenger_rows)
    formal_paired_items = [item for item in formal if str(item.get("prediction_id")) in set(formal_paired_ids)]
    formal_current_metrics = summarise_prediction_rows(_paired_method_rows(formal_paired_items, method="CURRENT_BASELINE"))
    formal_market_metrics = summarise_prediction_rows(_paired_method_rows(formal_paired_items, method="MARKET_ONLY"))
    formal_uniform_metrics = summarise_prediction_rows(_paired_method_rows(formal_paired_items, method="UNIFORM_1X2"))
    formal_challenger_metrics = summarise_prediction_rows(formal_challenger_rows)

    current_shadow_rows: list[dict[str, Any]] = []
    current_challenger_status = Counter()
    current_bridge_by_id = {str(row.get("prediction_id")): row for row in current_bridge}
    current_eligible_rows: list[dict[str, Any]] = []
    for record in current:
        bridge = current_bridge_by_id.get(str(record.get("prediction_id")))
        if not bridge or bridge.get("final_status") != "MAPPED":
            current_challenger_status[str((bridge or {}).get("final_status") or "IDENTITY_UNAVAILABLE")] += 1
            continue
        prediction = build_opponent_adjusted_shadow(bridge["target"], records, selected_spec)
        current_challenger_status[prediction.get("status", "UNKNOWN")] += 1
        if prediction.get("status") == "AVAILABLE":
            current_row = {"status": "AVAILABLE", "prediction_id": record.get("prediction_id"), "match_id": record.get("match_id"), "prediction": prediction}
            current_shadow_rows.append(current_row)
            current_eligible_rows.append({"record": record, "shadow": current_row})

    excluded_pilot_count = len(_load_exclusion_ids(root))
    current_metadata = _cohort_metadata(
        scope="current_business_date",
        business_date=business_date,
        total=len(current),
        eligible_count=len(current_eligible_rows),
        legacy_label="current_23",
    )
    formal_metadata = _cohort_metadata(
        scope="formal_eligible",
        business_date=business_date,
        total=len(formal),
        eligible_count=len(formal),
        excluded_pilot_count=excluded_pilot_count,
        legacy_label="formal_14",
    )

    current_comparison_rows = []
    for item in current_eligible_rows:
        record = item["record"]
        shadow = item["shadow"]["prediction"]
        baseline = _persisted_prediction(record)
        current_comparison_rows.append({
            "prediction_id": record.get("prediction_id"),
            "match_id": record.get("match_id"),
            "current_lambda": [baseline.get("lambda_home"), baseline.get("lambda_away")],
            "challenger_lambda": [shadow.get("lambda_home"), shadow.get("lambda_away")],
            "current_lambda_gap": abs((baseline.get("lambda_home") or 0) - (baseline.get("lambda_away") or 0)) if baseline.get("lambda_home") is not None and baseline.get("lambda_away") is not None else None,
            "challenger_lambda_gap": abs((shadow.get("lambda_home") or 0) - (shadow.get("lambda_away") or 0)),
            "current_top1": (_prediction_top_scores(baseline) or [None])[0],
            "challenger_top1": (_prediction_top_scores(shadow) or [None])[0],
            "current_top3": _prediction_top_scores(baseline)[:3],
            "challenger_top3": _prediction_top_scores(shadow)[:3],
        })

    paired_methods = {
        "CURRENT_BASELINE_ON_PAIRED": formal_current_metrics,
        "MARKET_ONLY_ON_PAIRED": formal_market_metrics,
        "NEW_FOOTBALL_ONLY_ON_PAIRED": formal_challenger_metrics,
        "UNIFORM_1X2_ON_PAIRED": formal_uniform_metrics,
        "NEW_FUSION_CHALLENGER": {"sample": 0, "status": "NOT_YET_EVALUATED"},
    }
    current_challenger_one_one = sum((_prediction_top_scores(row.get("prediction") or {}) or [None])[0] == "1-1" for row in current_shadow_rows)
    production_comparison = {
        "business_date": business_date,
        "current_total": len(current),
        "current_one_one_count": _one_one_count(current),
        "current_probability_leader_counts": _leader_counts(current),
        "current_market_leader_counts": _leader_counts(current, market=True),
        "current_lambda_gap": _record_lambda_gap_stats(current),
        "current_identity_gate": current_identity,
        "formal_sample_count": len(formal),
        "formal_identity_gate": formal_identity,
        "formal_methods": paired_methods,
        "formal_challenger_metrics": formal_challenger_metrics if formal_challenger_rows else {"sample": 0, "unavailable_reason": "NO_HISTORICAL_ELIGIBLE_PAIRED_SAMPLE"},
        "formal_challenger_status": dict(formal_replay_status),
        "current_challenger_status": dict(current_challenger_status),
        "current_challenger_available": len(current_shadow_rows),
        "current_challenger_one_one_count": current_challenger_one_one if current_shadow_rows else None,
        "current_eligible_subset": {"sample": len(current_eligible_rows), "current_one_one_count": sum(_one_one_count([item["record"] for item in current_eligible_rows]) for _ in [0]), "challenger_one_one_count": current_challenger_one_one if current_shadow_rows else None, "rows": current_comparison_rows},
        "paired_comparison_sample": len(formal_paired_ids),
        "paired_match_ids": formal_paired_ids,
        "strong_favourite_diagnostics": {
            "current_baseline": strong_favourite_diagnostics(_paired_method_rows(formal_paired_items, method="CURRENT_BASELINE")),
            "market_only": strong_favourite_diagnostics(_paired_method_rows(formal_paired_items, method="MARKET_ONLY")),
            "historical_challenger_holdout": strong_favourite_diagnostics(historical["holdout_rows"]),
        },
    }
    uniform_holdout_rows = [{"status": "AVAILABLE", "actual_score": row.get("actual_score"), "prediction": {"probabilities": uniform_one_x_two(), "top_scores": []}} for row in historical["holdout_rows"] if row.get("actual_score")]
    uniform_holdout_metrics = summarise_prediction_rows(uniform_holdout_rows)
    uniform_holdout_paired_rows = [{"status": "AVAILABLE", "actual_score": row.get("actual_score"), "prediction": {"probabilities": uniform_one_x_two(), "top_scores": []}} for row in historical["holdout_rows"] if row.get("status") == "AVAILABLE" and row.get("actual_score")]
    uniform_holdout_paired_metrics = summarise_prediction_rows(uniform_holdout_paired_rows)
    if formal_paired_ids and len(formal_paired_ids) < 5:
        paired_verdict = "TOO_SMALL_FOR_DECISION"
    elif formal_paired_ids:
        paired_verdict = "NEUTRAL"
    else:
        paired_verdict = "NOT_AVAILABLE"
    if formal_paired_ids and current_identity.get("historical_eligible", 0) > 0:
        result_gate = "PAIRED_EVALUATION_AVAILABLE"
    elif formal_paired_ids:
        result_gate = "PARTIAL_PAIRED_EVALUATION"
    elif formal_identity.get("identity_mapped", 0) or current_identity.get("identity_mapped", 0):
        result_gate = "HISTORICAL_COVERAGE_INSUFFICIENT"
    else:
        result_gate = "IDENTITY_BRIDGE_INSUFFICIENT"
    identity_audit = {
        "schema_version": "pa2_identity_bridge_audit.v1",
        "business_date": business_date,
        "deterministic_only": True,
        "fuzzy_resolution_used": False,
        "minimum_history": selected_spec.minimum_history,
        "sources_checked": [
            "data/prediction_dashboard/latest.json",
            "data/prediction_universe/*.json",
            "data/model_governance/predictions/*.json",
            "data/model_governance/input_snapshots/*.json",
            "data/football_data/team_alias_registry.json",
            "data/football_data/verified_identity_crosswalk.json",
            "data/football_data/verified_project_provider_crosswalk.json",
            "data/football_data/competition_coverage_registry.json",
            "HistoricalResultStore",
        ],
        "current_business_date": dict(current_metadata, identity=current_identity),
        "formal_eligible": dict(formal_metadata, identity=formal_identity),
        "current_23": dict(current_metadata, legacy_label=True, identity=current_identity),
        "formal_14": dict(formal_metadata, legacy_label=True, identity=formal_identity),
        "rows": ([dict(row, scope="current_business_date") for row in current_bridge] + [dict(row, scope="formal_eligible") for row in formal_bridge]),
    }
    paired_evaluation = {
        "schema_version": "pa2_r1_paired_evaluation.v1",
        "result_gate": result_gate,
        "formal_sample_total": len(formal),
        "paired_sample": len(formal_paired_ids),
        "paired_match_ids": formal_paired_ids,
        "same_match_ids_for_all_methods": True,
        "verdict": paired_verdict,
        "current_business_date": {
            **current_metadata,
            "eligible": len(current_eligible_rows),
            "current_top1_one_one": f"{_one_one_count(current)}/{len(current)}" if current else None,
            "challenger_top1_one_one": f"{current_challenger_one_one}/{len(current_shadow_rows)}" if current_shadow_rows else None,
            "rows": current_comparison_rows,
        },
        "formal_eligible": formal_metadata,
        "current_23": {**current_metadata, "legacy_label": True},
        "formal_14": {**formal_metadata, "legacy_label": True},
        "formal_paired_methods": paired_methods,
        "fusion_status": "NOT_YET_EVALUATED",
        "formal_replay_status": dict(formal_replay_status),
        "current_replay_status": dict(current_challenger_status),
    }
    benchmarks = {
        "CURRENT_BASELINE": {"scope": "formal_paired_subset", "metrics": formal_current_metrics},
        "MARKET_ONLY": {"scope": "formal_paired_subset", "metrics": formal_market_metrics},
        "NEW_FOOTBALL_ONLY": {"scope": "historical_holdout", "metrics": historical_metrics},
        "NEW_FUSION_CHALLENGER": {"scope": "not_evaluated", "metrics": {"sample": 0, "status": "NOT_YET_EVALUATED"}},
        "UNIFORM_1X2": {"scope": "formal_paired_subset", "metrics": formal_uniform_metrics},
        "UNIFORM_1X2_HISTORICAL_HOLDOUT": {"scope": "historical_holdout", "metrics": uniform_holdout_metrics},
        "UNIFORM_1X2_HISTORICAL_HOLDOUT_ON_CHALLENGER_SAMPLE": {"scope": "same_available_sample_as_new_football_only", "metrics": uniform_holdout_paired_metrics},
    }
    summary = {
        "schema_version": "pa2_strength_challenger.v1",
        "result": result_gate,
        "challenger_name": CHALLENGER_NAME,
        "research_only": True,
        "production_mutation": False,
        "promotion_status": "SHADOW_ONLY",
        "ca1_status": "KEEP_PAUSED",
        "dataset": _dataset_summary(raw_records, gate, store),
        "historical_split": historical["split"],
        "parameters": {"selected": asdict(selected_spec), "candidate_regularizations": [5, 10, 20], "market_fusion": "not evaluated without current canonical target identity", "rho": 0.0, "randomness": "none"},
        "leakage_audit": historical["leakage_audit"],
        "identity_bridge": {"current_business_date": dict(current_metadata, identity=current_identity), "formal_eligible": dict(formal_metadata, identity=formal_identity), "current_23": {**current_metadata, "legacy_label": True, "identity": current_identity}, "formal_14": {**formal_metadata, "legacy_label": True, "identity": formal_identity}, "deterministic_only": True, "fuzzy_resolution_used": False},
        "identity_bridge_audit_file": "identity_bridge_audit.json",
        "paired_evaluation_file": "paired_challenger_evaluation.json",
        "validation_reconciliation": historical.get("validation_reconciliation"),
        "benchmarks": benchmarks,
        "production_comparison": production_comparison,
        "representative_matches": _representative_rows(historical["holdout_rows"], limit=10),
        "verdict": paired_verdict,
        "primary_blocker": "IDENTITY" if current_identity.get("historical_eligible", 0) == 0 else "SAMPLE_SIZE",
        "next_step": "PA-3_SHADOW" if len(formal_paired_ids) >= 5 else "TARGETED_IDENTITY_PERSISTENCE_AND_MORE_PAIRED_DATA",
        "historical_holdout_one_one_reminder": {"predicted_share": historical_metrics.get("predicted_top1_one_one_share"), "actual_share": historical_metrics.get("actual_one_one_share")},
        "strong_favourite_diagnostics": production_comparison["strong_favourite_diagnostics"],
        "fusion_status": "NOT_YET_EVALUATED",
        "limitations": [
            "Current/formal production records do not persist canonical team IDs and competition IDs; only existing verified registries/crosswalks were used.",
            "Historical store has no corresponding freeze-time market prior, so market-only is unavailable on historical holdout.",
            "The challenger is not written into Champion or production prediction records.",
        ],
    }
    (output_dir / "identity_bridge_audit.json").write_text(json.dumps(identity_audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "paired_challenger_evaluation.json").write_text(json.dumps(paired_evaluation, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "challenger_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "walk_forward_metrics.json").write_text(json.dumps(historical, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    prediction_rows: list[dict[str, Any]] = []
    for row in historical["holdout_rows"]:
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        prediction_rows.append({"scope": "historical_holdout", "match_id": row.get("match_id"), "actual_score": row.get("actual_score"), "status": row.get("status"), "lambda_home": prediction.get("lambda_home"), "lambda_away": prediction.get("lambda_away"), "top1": (_prediction_top_scores(prediction) or [None])[0], "top3": "|".join(_prediction_top_scores(prediction)[:3])})
    for row in current_comparison_rows:
        prediction_rows.append({"scope": "current_business_date_shadow", "business_date": business_date, "eligible_count": len(current_eligible_rows), "excluded_pilot_count": 0, "legacy_label": "current_23", "match_id": row.get("match_id"), "actual_score": None, "status": "AVAILABLE", "lambda_home": row.get("challenger_lambda", [None, None])[0], "lambda_away": row.get("challenger_lambda", [None, None])[1], "top1": row.get("challenger_top1"), "top3": "|".join(row.get("challenger_top3") or [])})
    for row in formal_challenger_rows:
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        prediction_rows.append({"scope": "formal_eligible_challenger", "business_date": business_date, "eligible_count": len(formal), "excluded_pilot_count": excluded_pilot_count, "legacy_label": "formal_14", "match_id": row.get("match_id"), "actual_score": row.get("actual_score"), "status": row.get("status"), "lambda_home": prediction.get("lambda_home"), "lambda_away": prediction.get("lambda_away"), "top1": (_prediction_top_scores(prediction) or [None])[0], "top3": "|".join(_prediction_top_scores(prediction)[:3])})
    with (output_dir / "challenger_predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scope", "business_date", "eligible_count", "excluded_pilot_count", "legacy_label", "match_id", "actual_score", "status", "lambda_home", "lambda_away", "top1", "top3"])
        writer.writeheader()
        writer.writerows(prediction_rows)
    return summary


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Run the PA-2 opponent-adjusted strength challenger as a read-only shadow study")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path, default=None)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data_home = args.data_home or resolve_football_data_home()
    try:
        summary = run_research(root=args.root, data_home=data_home, business_date=args.business_date, output_dir=args.output_dir)
    except DatasetNotAvailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"result": summary["result"], "challenger": summary["challenger_name"], "holdout": summary["benchmarks"]["NEW_FOOTBALL_ONLY"]["metrics"], "formal_challenger_sample": summary["production_comparison"]["paired_comparison_sample"], "production_mutation": summary["production_mutation"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
