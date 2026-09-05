#!/usr/bin/env python3
"""Read-only Decision Packet coverage, chronology, and horizon audit.

The audit deliberately treats one football match as one observation.  Frozen
record versions are retained only for the Change Awareness chronology check;
they are never allowed to inflate the product coverage denominator.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:  # Direct script execution puts ``scripts`` on sys.path.
    from match_identity import canonical_match_id
    from model_governance import load_frozen_prediction, load_input_snapshot
    from prediction_universe import load_prediction_universe
    from prospective_settlement import is_formally_eligible
except ImportError:  # Package imports used by pytest.
    from scripts.match_identity import canonical_match_id
    from scripts.model_governance import load_frozen_prediction, load_input_snapshot
    from scripts.prediction_universe import load_prediction_universe
    from scripts.prospective_settlement import is_formally_eligible


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "decision-packet-coverage-and-horizon-audit-1"
AUDIT_SCHEMA_VERSION = "decision_packet_coverage_horizon_audit.v1"
FORMAL_STATUSES = {"formal", "frozen", "FROZEN"}
RESULT_SCOPE = "regulation_90m_plus_stoppage"

# These labels and boundaries are part of the audit contract, not fitted to
# this repository's result.  The raw horizon distribution is emitted before
# these descriptive bands in report.md.
COVERAGE_LABELS = (
    (0.95, "UNIVERSAL"),
    (0.80, "BROAD"),
    (0.50, "PARTIAL"),
    (0.00, "SPARSE"),
)
HORIZON_BANDS = (
    {"id": "T_0_TO_60M", "label": "T-0 to <60m", "lower_minutes": 0.0, "upper_minutes": 60.0},
    {"id": "T_60_TO_180M", "label": "T-60m to <3h", "lower_minutes": 60.0, "upper_minutes": 180.0},
    {"id": "T_3_TO_6H", "label": "T-3h to <6h", "lower_minutes": 180.0, "upper_minutes": 360.0},
    {"id": "T_6_TO_12H", "label": "T-6h to <12h", "lower_minutes": 360.0, "upper_minutes": 720.0},
    {"id": "T_12_TO_24H", "label": "T-12h to <24h", "lower_minutes": 720.0, "upper_minutes": 1440.0},
    {"id": "T_24H_PLUS", "label": "T-24h+", "lower_minutes": 1440.0, "upper_minutes": None},
)
WEAK_HORIZON_BANDS = {"T_0_TO_60M", "T_60_TO_180M"}
MATERIAL_CONCENTRATION_SHARE = 0.50
MIN_COMPETITION_MATCHES_FOR_CONCENTRATION = 2

SOURCE_PATHS = [
    "data/model_governance/predictions/*.json",
    "data/model_governance/input_snapshots/*.json",
    "data/prediction_universe/*.json",
    "data/base_prediction_jobs/*.json",
    "data/prospective/ledger.jsonl",
    "data/postmatch_automation/results/*.json",
]
READER_PATHS = [
    "scripts/model_governance.py:load_frozen_prediction/load_input_snapshot",
    "scripts/prediction_universe.py:load_prediction_universe",
    "scripts/prospective_settlement.py:is_formally_eligible",
    "scripts/match_identity.py:canonical_match_id",
]

FIELD_DEFINITIONS = (
    {
        "id": "match_identity",
        "name": "Match identity",
        "group": "core",
        "source_basis": "frozen prediction record match_key/match_identity",
    },
    {
        "id": "competition",
        "name": "Competition",
        "group": "core",
        "source_basis": "canonical-joined prediction-universe fixture league/competition",
    },
    {
        "id": "kickoff",
        "name": "Kickoff",
        "group": "core",
        "source_basis": "frozen prediction record kickoff_at",
    },
    {
        "id": "serving_state",
        "name": "Serving/degraded/unavailable state",
        "group": "core",
        "source_basis": "frozen prediction status plus explicit data-quality state",
    },
    {
        "id": "frozen_1x2",
        "name": "Frozen 1X2 probability vector",
        "group": "core",
        "source_basis": "frozen prediction probabilities.home/draw/away",
    },
    {
        "id": "exact_score_top1",
        "name": "Exact Score Top1 with displayed probability",
        "group": "core",
        "source_basis": "frozen score_top1 joined to persisted score_distribution probability",
    },
    {
        "id": "exact_score_top3",
        "name": "Exact Score Top3 with displayed probabilities",
        "group": "core",
        "source_basis": "frozen score_top3 joined to persisted score_distribution probabilities",
    },
    {
        "id": "exact_score_top5",
        "name": "Exact Score Top5 with displayed probabilities",
        "group": "core",
        "source_basis": "frozen score_top5 joined to persisted score_distribution probabilities",
    },
    {
        "id": "full_score_distribution",
        "name": "Full score-distribution availability flag",
        "group": "core",
        "source_basis": "explicit frozen availability flag only; top-k rows do not imply full distribution",
    },
    {
        "id": "total_goals",
        "name": "Total-goals state/distribution",
        "group": "core",
        "source_basis": "frozen totals rows with goals and probabilities",
    },
    {
        "id": "btts",
        "name": "BTTS state/probability",
        "group": "core",
        "source_basis": "frozen btts yes/no probabilities",
    },
    {
        "id": "source_cutoff",
        "name": "Source cutoff",
        "group": "core",
        "source_basis": "frozen source_cutoff_at",
    },
    {
        "id": "freeze_timestamp",
        "name": "Frozen timestamp",
        "group": "core",
        "source_basis": "frozen freeze_created_at",
    },
    {
        "id": "recent_form_aggregate",
        "name": "Frozen recent-form aggregate",
        "group": "match",
        "source_basis": "stored input snapshot prematch_fundamentals/source shuju recent_form",
    },
    {
        "id": "home_away_recent_form",
        "name": "Home/away recent-form context",
        "group": "match",
        "source_basis": "stored input snapshot recent_form home_home/away_away contexts",
    },
    {
        "id": "lineup_publication",
        "name": "Lineup publication",
        "group": "optional_match",
        "source_basis": "explicit frozen lineup publication object/flag only",
    },
    {
        "id": "injuries_availability",
        "name": "Injuries/availability",
        "group": "optional_match",
        "source_basis": "explicit frozen injuries/availability object only",
    },
    {
        "id": "weather",
        "name": "Weather",
        "group": "optional_match",
        "source_basis": "explicit frozen weather object only",
    },
    {
        "id": "venue_h2h",
        "name": "Venue/H2H",
        "group": "optional_match",
        "source_basis": "explicit frozen venue or H2H object only",
    },
    {
        "id": "market_1x2_quotes",
        "name": "Timestamped frozen 1X2 quotes",
        "group": "market",
        "source_basis": "stored input snapshot ouzhi bookmaker spf_current",
    },
    {
        "id": "market_ah_line_water",
        "name": "AH line plus both-side water",
        "group": "market",
        "source_basis": "stored input snapshot yazhi current_handicap/current_water_home/current_water_away",
    },
    {
        "id": "market_ou_line_water",
        "name": "O/U line plus both-side water",
        "group": "market",
        "source_basis": "stored input snapshot daxiao current_line/current_over_water/current_under_water",
    },
    {
        "id": "market_snapshot_timestamp",
        "name": "Market snapshot timestamp",
        "group": "market",
        "source_basis": "frozen market_snapshot_at and stored snapshot timestamp",
    },
    {
        "id": "market_source_age_inputs",
        "name": "Market snapshot source-age inputs",
        "group": "market",
        "source_basis": "frozen source_time_range earliest/latest/source_timestamps",
    },
    {
        "id": "market_input_quality",
        "name": "Market/input quality/data-grade",
        "group": "market",
        "source_basis": "frozen data_grade, market_intelligence_quality, data_quality",
    },
    {
        "id": "verified_result_linkage",
        "name": "Verified-result linkage",
        "group": "trust",
        "source_basis": "formal ledger match identity joined to regulation-only result artifact",
    },
    {
        "id": "forecast_lead_time",
        "name": "Forecast lead time",
        "group": "trust",
        "source_basis": "kickoff_at minus legal frozen freeze_created_at",
    },
)

FIELD_IDS = tuple(field["id"] for field in FIELD_DEFINITIONS)
FIELD_BY_ID = {field["id"]: field for field in FIELD_DEFINITIONS}
CORE_REQUIRED_FIELDS = {
    "match_identity",
    "competition",
    "kickoff",
    "serving_state",
    "frozen_1x2",
    "exact_score_top1",
    "exact_score_top3",
    "exact_score_top5",
    "total_goals",
    "btts",
    "source_cutoff",
    "freeze_timestamp",
    "forecast_lead_time",
    "recent_form_aggregate",
    "home_away_recent_form",
}
MARKET_DEGRADED_FIELDS = {
    "full_score_distribution",
    "market_1x2_quotes",
    "market_ah_line_water",
    "market_ou_line_water",
    "market_snapshot_timestamp",
    "market_source_age_inputs",
    "market_input_quality",
    "verified_result_linkage",
}
OPTIONAL_ENRICHMENT_FIELDS = {
    "lineup_publication",
    "injuries_availability",
    "weather",
    "venue_h2h",
}


def parse_aware_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp only when timezone information is explicit."""

    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def coverage_label(ratio: float) -> str:
    for threshold, label in COVERAGE_LABELS:
        if ratio >= threshold:
            return label
    return "SPARSE"


def coverage_summary(eligible: int, present: int, reasons: Counter[str] | None = None) -> dict[str, Any]:
    ratio = present / eligible if eligible else 0.0
    return {
        "eligible_unique_matches": eligible,
        "present_unique_matches": present,
        "coverage_ratio": round(ratio, 8),
        "coverage_percent": round(ratio * 100.0, 4),
        "coverage_label": coverage_label(ratio),
        "missing_reasons": dict(sorted((reasons or Counter()).items())),
    }


def json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def record_match_key(record: dict[str, Any]) -> str:
    identity = record.get("match_identity")
    if not isinstance(identity, dict):
        identity = {}
    return str(record.get("match_key") or identity.get("match_key") or "").strip()


def fixture_kickoff(fixture: dict[str, Any]) -> str:
    direct = fixture.get("kickoff_local") or fixture.get("kickoff")
    if direct:
        return str(direct)
    match_date = str(fixture.get("matchDate") or fixture.get("match_date") or "").strip()
    match_time = str(fixture.get("matchTime") or fixture.get("match_time") or "").strip()
    if not match_date or not match_time:
        return ""
    if "T" in match_date:
        return match_date
    time_part = match_time
    if len(time_part) == 5:
        time_part += ":00"
    return f"{match_date}T{time_part}+08:00"


def fixture_match_key(fixture: dict[str, Any]) -> str:
    kickoff = fixture_kickoff(fixture)
    return canonical_match_id(
        {
            "home": fixture.get("homeTeam") or fixture.get("home_team") or fixture.get("home"),
            "away": fixture.get("awayTeam") or fixture.get("away_team") or fixture.get("away"),
            "kickoff_local": kickoff,
        }
    )


def load_universe_records(universe_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(universe_root.glob("*.json")):
        business_date = path.stem
        payload = load_prediction_universe(business_date, universe_root)
        if not isinstance(payload, dict):
            errors.append(f"{path.name}:reader_rejected")
            continue
        fixtures = payload.get("fixtures")
        if not isinstance(fixtures, list):
            errors.append(f"{path.name}:missing_fixtures")
            continue
        for index, fixture in enumerate(fixtures):
            if not isinstance(fixture, dict):
                errors.append(f"{path.name}:fixture_{index}:not_object")
                continue
            key = fixture_match_key(fixture)
            if key.endswith("-unknown-undefined") or "-unknown-" in key:
                errors.append(f"{path.name}:fixture_{index}:unsafe_identity")
                continue
            rows.append(
                {
                    "match_key": key,
                    "competition": str(fixture.get("league") or fixture.get("competition") or "").strip(),
                    "source": str(payload.get("source") or "").strip(),
                    "business_date": business_date,
                    "fixture": fixture,
                    "path": repo_relative(path),
                }
            )
    return rows, errors


def load_base_job_records(base_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(base_root.glob("*.json")):
        try:
            payload = json_load(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}:unreadable:{type(error).__name__}")
            continue
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            errors.append(f"{path.name}:missing_jobs")
            continue
        for index, job in enumerate(jobs):
            if not isinstance(job, dict):
                errors.append(f"{path.name}:job_{index}:not_object")
                continue
            key = canonical_match_id(
                {
                    "home": job.get("home"),
                    "away": job.get("away"),
                    "kickoff_local": job.get("kickoff"),
                }
            )
            rows.append(
                {
                    "match_key": key,
                    "status": str(job.get("status") or "UNKNOWN").strip(),
                    "competition": str(job.get("league") or "").strip(),
                    "job": job,
                    "path": repo_relative(path),
                }
            )
    return rows, errors


def load_ledger_records(ledger_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return [], [f"ledger_unreadable:{type(error).__name__}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line_{line_number}:invalid_json")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line_{line_number}:not_object")
            continue
        identity = payload.get("match_identity") if isinstance(payload.get("match_identity"), dict) else {}
        key = str(identity.get("match_key") or payload.get("match_key") or "").strip()
        if not key:
            errors.append(f"line_{line_number}:missing_match_key")
            continue
        rows.append(
            {
                "match_key": key,
                "prediction_id": str(payload.get("prediction_id") or "").strip(),
                "prediction_record_ref": str(payload.get("prediction_record_ref") or "").strip(),
                "prediction_sha256": str(payload.get("prediction_sha256") or "").strip(),
                "freeze_at": payload.get("freeze_at"),
                "kickoff_at": payload.get("kickoff_at"),
                "path": repo_relative(ledger_path),
            }
        )
    return rows, errors


def load_result_records(result_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    all_results: dict[str, dict[str, Any]] = {}
    valid_results: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in sorted(result_root.glob("*.json")):
        try:
            payload = json_load(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}:unreadable:{type(error).__name__}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name}:not_object")
            continue
        key = str(payload.get("match_key") or "").strip()
        if not key:
            errors.append(f"{path.name}:missing_match_key")
            continue
        if key in all_results:
            errors.append(f"{key}:duplicate_result_key")
            continue
        all_results[key] = payload
        if (
            payload.get("scope") == RESULT_SCOPE
            and str(payload.get("result_90m") or "").strip()
            and parse_aware_datetime(payload.get("verified_at")) is not None
        ):
            valid_results[key] = payload
    return all_results, valid_results, errors


def load_frozen_records(record_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in sorted(record_root.glob("*.json")):
        record = load_frozen_prediction(path.stem, record_root)
        if record is None:
            rejected.append({"path": repo_relative(path), "reason": "READER_REJECTED"})
            continue
        record = dict(record)
        record["_audit_path"] = repo_relative(path)
        accepted.append(record)
    return accepted, rejected


def legal_version_reason(record: dict[str, Any]) -> str | None:
    source = parse_aware_datetime(record.get("source_cutoff_at"))
    created = parse_aware_datetime(record.get("prediction_created_at"))
    freeze = parse_aware_datetime(record.get("freeze_created_at"))
    kickoff = parse_aware_datetime(record.get("kickoff_at"))
    if not source or not created or not freeze or not kickoff:
        return "MISSING_OR_UNSAFE_PREMATCH_TIMESTAMP"
    if not source < created <= freeze < kickoff:
        return "PREMATCH_CHRONOLOGY_VIOLATION"
    return None


def select_latest_legal_version(records: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    legal = [record for record in records if legal_version_reason(record) is None]
    if not legal:
        return None
    return max(
        legal,
        key=lambda record: (
            parse_aware_datetime(record.get("freeze_created_at")),
            parse_aware_datetime(record.get("prediction_created_at")),
            str(record.get("prediction_id") or ""),
        ),
    )


def snapshot_input(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    value = snapshot.get("input")
    return value if isinstance(value, dict) else {}


def source_snapshots(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    sources = snapshot_input(snapshot).get("source_snapshots")
    if not isinstance(sources, dict):
        return []
    result: list[dict[str, Any]] = []
    for provider in sorted(sources):
        source = sources[provider]
        if not isinstance(source, dict):
            continue
        snapshots = source.get("snapshots")
        if isinstance(snapshots, list):
            result.extend(item for item in snapshots if isinstance(item, dict))
    return result


def recent_form(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    input_data = snapshot_input(snapshot)
    fundamentals = input_data.get("prematch_fundamentals")
    if isinstance(fundamentals, dict) and isinstance(fundamentals.get("recent_form"), dict):
        return fundamentals["recent_form"]
    for source in source_snapshots(snapshot):
        shuju = source.get("shuju")
        if isinstance(shuju, dict) and isinstance(shuju.get("recent_form"), dict):
            return shuju["recent_form"]
    return None


def explicit_persisted_mapping(snapshot: dict[str, Any] | None, keys: set[str]) -> bool:
    """Look only at packet-level persisted objects, never collector code/history."""

    input_data = snapshot_input(snapshot)
    containers: list[dict[str, Any]] = [input_data]
    fundamentals = input_data.get("prematch_fundamentals")
    if isinstance(fundamentals, dict):
        containers.append(fundamentals)
    for container in containers:
        if any(key in container and container.get(key) not in (None, "", [], {}) for key in keys):
            return True
    return False


def valid_score_rows(record: dict[str, Any]) -> dict[str, float]:
    distribution = record.get("score_distribution")
    if not isinstance(distribution, list):
        return {}
    result: dict[str, float] = {}
    for row in distribution:
        if not isinstance(row, dict):
            continue
        score = str(row.get("score") or "").strip()
        probability = finite_number(row.get("probability"))
        if score and probability is not None:
            result[score] = probability
    return result


def valid_total_rows(record: dict[str, Any]) -> bool:
    values = record.get("totals")
    if not isinstance(values, list) or not values:
        return False
    return all(
        isinstance(row, dict)
        and str(row.get("goals") or "").strip()
        and finite_number(row.get("probability")) is not None
        for row in values
    )


def valid_btts(record: dict[str, Any]) -> bool:
    value = record.get("btts")
    if not isinstance(value, dict):
        return False
    return finite_number(value.get("yes")) is not None and finite_number(value.get("no")) is not None


def market_surface(snapshot: dict[str, Any] | None, family: str) -> bool:
    for source in source_snapshots(snapshot):
        market = source.get(family)
        if not isinstance(market, dict):
            continue
        if family == "ouzhi":
            bookmakers = market.get("bookmakers")
            if not isinstance(bookmakers, list):
                continue
            for bookmaker in bookmakers:
                odds = bookmaker.get("spf_current") if isinstance(bookmaker, dict) else None
                if isinstance(odds, dict) and all(finite_number(odds.get(key)) is not None for key in ("home", "draw", "away")):
                    return True
        elif family == "yazhi":
            companies = market.get("companies")
            if not isinstance(companies, list):
                continue
            for company in companies:
                if isinstance(company, dict) and all(
                    finite_number(company.get(key)) is not None
                    for key in ("current_handicap", "current_water_home", "current_water_away")
                ):
                    return True
        elif family == "daxiao":
            companies = market.get("companies")
            if not isinstance(companies, list):
                continue
            for company in companies:
                if isinstance(company, dict) and all(
                    finite_number(company.get(key)) is not None
                    for key in ("current_line", "current_over_water", "current_under_water")
                ):
                    return True
    return False


def market_fingerprint(snapshot: dict[str, Any] | None, family: str) -> list[dict[str, Any]] | None:
    """Return a deterministic pre-match market surface without exposing values."""

    rows: list[dict[str, Any]] = []
    for source in source_snapshots(snapshot):
        market = source.get(family)
        if not isinstance(market, dict):
            continue
        if family == "ouzhi" and isinstance(market.get("bookmakers"), list):
            for bookmaker in market["bookmakers"]:
                odds = bookmaker.get("spf_current") if isinstance(bookmaker, dict) else None
                if isinstance(odds, dict) and all(finite_number(odds.get(key)) is not None for key in ("home", "draw", "away")):
                    rows.append(
                        {
                            "name": bookmaker.get("name"),
                            "cid": bookmaker.get("cid"),
                            "source_company_id": bookmaker.get("source_company_id"),
                            "home": finite_number(odds.get("home")),
                            "draw": finite_number(odds.get("draw")),
                            "away": finite_number(odds.get("away")),
                        }
                    )
        elif family in {"yazhi", "daxiao"} and isinstance(market.get("companies"), list):
            keys = (
                ("current_handicap", "current_water_home", "current_water_away")
                if family == "yazhi"
                else ("current_line", "current_over_water", "current_under_water")
            )
            for company in market["companies"]:
                if isinstance(company, dict) and all(finite_number(company.get(key)) is not None for key in keys):
                    rows.append(
                        {
                            "name": company.get("name"),
                            **{key: finite_number(company.get(key)) for key in keys},
                        }
                    )
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True)) or None


def surface_fingerprint(
    surface: str,
    record: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> Any:
    if surface == "1x2":
        probabilities = record.get("probabilities")
        if not isinstance(probabilities, dict) or not all(
            finite_number(probabilities.get(key)) is not None for key in ("home", "draw", "away")
        ):
            return None
        return {key: finite_number(probabilities.get(key)) for key in ("home", "draw", "away")}
    if surface == "exact_top1_top3":
        if not field_presence("exact_score_top1", record)[0] or not field_presence("exact_score_top3", record)[0]:
            return None
        scores = valid_score_rows(record)
        top_scores = [str(record.get("score_top1"))] + [str(value) for value in record.get("score_top3", [])]
        return {
            "top1": str(record.get("score_top1")),
            "top3": [str(value) for value in record.get("score_top3", [])],
            "probabilities": {score: scores[score] for score in dict.fromkeys(top_scores) if score in scores},
        }
    if surface == "asian_handicap":
        return market_fingerprint(snapshot, "yazhi")
    if surface == "over_under":
        return market_fingerprint(snapshot, "daxiao")
    if surface == "frozen_evidence":
        if snapshot is None:
            return None
        return {
            key: snapshot.get(key)
            for key in (
                "snapshot_id",
                "canonical_input_sha256",
                "canonical_model_input_sha256",
                "source_cutoff_at",
                "market_snapshot_at",
            )
            if snapshot.get(key) not in (None, "")
        }
    raise KeyError(surface)


def surface_diff_status(
    surface: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    current_snapshot: dict[str, Any] | None,
) -> str:
    previous_fingerprint = surface_fingerprint(surface, previous, previous_snapshot)
    current_fingerprint = surface_fingerprint(surface, current, current_snapshot)
    if previous_fingerprint is None or current_fingerprint is None:
        return "NOT_DIFFABLE"
    return "CHANGED" if previous_fingerprint != current_fingerprint else "UNCHANGED"


def field_presence(
    field_id: str,
    record: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Return (present, one exhaustive missing reason)."""

    context = context or {}
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    if field_id == "match_identity":
        present = bool(
            record_match_key(record)
            and identity.get("match_key") == record_match_key(record)
            and str(identity.get("home") or "").strip()
            and str(identity.get("away") or "").strip()
            and parse_aware_datetime(record.get("kickoff_at"))
        )
        return present, None if present else "MISSING_FROZEN_MATCH_IDENTITY"
    if field_id == "competition":
        competition = str(context.get("competition") or "").strip()
        present = bool(competition and competition != "UNKNOWN")
        return present, None if present else "MISSING_AUTHORITATIVE_COMPETITION"
    if field_id == "kickoff":
        present = parse_aware_datetime(record.get("kickoff_at")) is not None
        return present, None if present else "MISSING_OR_UNSAFE_KICKOFF_TIMESTAMP"
    if field_id == "serving_state":
        quality = record.get("data_quality")
        prediction_output = record.get("prediction_output")
        present = (
            str(record.get("prediction_status") or "").strip() in FORMAL_STATUSES
            and isinstance(record.get("formal_eligible"), bool)
            and (
                isinstance(quality, dict) and str(quality.get("status") or "").strip()
                or isinstance(prediction_output, dict) and str(prediction_output.get("status") or "").strip()
            )
        )
        return bool(present), None if present else "MISSING_EXPLICIT_SERVING_STATE"
    if field_id == "frozen_1x2":
        probabilities = record.get("probabilities")
        present = isinstance(probabilities, dict) and all(
            finite_number(probabilities.get(key)) is not None for key in ("home", "draw", "away")
        )
        return present, None if present else "MISSING_FROZEN_1X2_VECTOR"
    if field_id.startswith("exact_score_top"):
        top_n = {"exact_score_top1": 1, "exact_score_top3": 3, "exact_score_top5": 5}[field_id]
        top = record.get(f"score_top{top_n}") if top_n != 1 else [record.get("score_top1")]
        scores = valid_score_rows(record)
        present = isinstance(top, list) and len(top) >= top_n and all(
            str(score or "").strip() in scores for score in top[:top_n]
        )
        return present, None if present else f"MISSING_DISPLAYED_EXACT_TOP{top_n}_PROBABILITIES"
    if field_id == "full_score_distribution":
        flag_keys = (
            "full_score_distribution",
            "full_score_distribution_available",
            "score_distribution_available",
            "score_matrix_available",
        )
        candidates: list[Any] = [record.get(key) for key in flag_keys]
        output = record.get("prediction_output")
        if isinstance(output, dict):
            candidates.extend(output.get(key) for key in flag_keys)
        present = any(value is True for value in candidates)
        return present, None if present else "TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG"
    if field_id == "total_goals":
        present = valid_total_rows(record)
        return present, None if present else "MISSING_TOTAL_GOALS_STATE_OR_DISTRIBUTION"
    if field_id == "btts":
        present = valid_btts(record)
        return present, None if present else "MISSING_BTTS_STATE_OR_PROBABILITIES"
    if field_id == "source_cutoff":
        present = parse_aware_datetime(record.get("source_cutoff_at")) is not None
        return present, None if present else "MISSING_OR_UNSAFE_SOURCE_CUTOFF_TIMESTAMP"
    if field_id == "freeze_timestamp":
        present = parse_aware_datetime(record.get("freeze_created_at")) is not None
        return present, None if present else "MISSING_OR_UNSAFE_FREEZE_TIMESTAMP"
    if field_id == "recent_form_aggregate":
        recent = recent_form(snapshot)
        present = isinstance(recent, dict) and all(isinstance(recent.get(key), dict) for key in ("home_overall", "away_overall"))
        return present, None if present else "MISSING_FROZEN_RECENT_FORM_AGGREGATE"
    if field_id == "home_away_recent_form":
        recent = recent_form(snapshot)
        present = isinstance(recent, dict) and all(
            isinstance(recent.get(key), dict) for key in ("home_home", "away_away")
        )
        return present, None if present else "MISSING_FROZEN_HOME_AWAY_FORM_CONTEXT"
    if field_id == "lineup_publication":
        present = explicit_persisted_mapping(snapshot, {"lineup_publication", "lineup"})
        return present, None if present else "NO_FROZEN_LINEUP_PUBLICATION_RECORD"
    if field_id == "injuries_availability":
        present = explicit_persisted_mapping(snapshot, {"injuries", "availability", "injuries_availability"})
        return present, None if present else "NO_FROZEN_INJURY_AVAILABILITY_RECORD"
    if field_id == "weather":
        present = explicit_persisted_mapping(snapshot, {"weather"})
        return present, None if present else "NO_FROZEN_WEATHER_RECORD"
    if field_id == "venue_h2h":
        present = explicit_persisted_mapping(snapshot, {"venue", "h2h", "head_to_head", "venue_h2h"})
        return present, None if present else "NO_FROZEN_VENUE_OR_H2H_RECORD"
    if field_id == "market_1x2_quotes":
        present = market_surface(snapshot, "ouzhi")
        return present, None if present else "NO_FROZEN_1X2_QUOTE_ROWS"
    if field_id == "market_ah_line_water":
        present = market_surface(snapshot, "yazhi")
        return present, None if present else "NO_FROZEN_AH_LINE_WITH_BOTH_WATERS"
    if field_id == "market_ou_line_water":
        present = market_surface(snapshot, "daxiao")
        return present, None if present else "NO_FROZEN_OU_LINE_WITH_BOTH_WATERS"
    if field_id == "market_snapshot_timestamp":
        input_data = snapshot_input(snapshot)
        snapshot_timestamp = snapshot.get("market_snapshot_at") if isinstance(snapshot, dict) else None
        snapshot_timestamp = snapshot_timestamp or input_data.get("market_snapshot_at")
        present = (
            parse_aware_datetime(record.get("market_snapshot_at")) is not None
            and parse_aware_datetime(snapshot_timestamp) is not None
        )
        return present, None if present else "MISSING_OR_UNSAFE_MARKET_SNAPSHOT_TIMESTAMP"
    if field_id == "market_source_age_inputs":
        value = record.get("source_time_range")
        present = (
            isinstance(value, dict)
            and parse_aware_datetime(value.get("earliest_source_at")) is not None
            and parse_aware_datetime(value.get("latest_source_at")) is not None
            and isinstance(value.get("source_timestamps"), dict)
            and bool(value.get("source_timestamps"))
            and all(parse_aware_datetime(timestamp) is not None for timestamp in value["source_timestamps"].values())
        )
        return present, None if present else "MISSING_SOURCE_AGE_INPUTS"
    if field_id == "market_input_quality":
        quality = record.get("data_quality")
        present = bool(
            str(record.get("data_grade") or "").strip()
            and str(record.get("market_intelligence_quality") or "").strip()
            and isinstance(quality, dict)
            and str(quality.get("status") or "").strip()
        )
        return present, None if present else "MISSING_MARKET_OR_INPUT_QUALITY_STATE"
    if field_id == "verified_result_linkage":
        present = context.get("settlement_status") == "SETTLED_VERIFIED"
        return present, None if present else str(context.get("result_missing_reason") or "NO_VERIFIED_RESULT_LINKAGE")
    if field_id == "forecast_lead_time":
        present = context.get("horizon_minutes") is not None
        return present, None if present else str(context.get("horizon_missing_reason") or "HORIZON_NOT_SAFE_TO_COMPUTE")
    raise KeyError(field_id)


def safe_horizon_minutes(record: dict[str, Any]) -> tuple[float | None, str | None]:
    kickoff = parse_aware_datetime(record.get("kickoff_at"))
    freeze = parse_aware_datetime(record.get("freeze_created_at"))
    if kickoff is None or freeze is None:
        return None, "MISSING_OR_UNSAFE_KICKOFF_OR_FREEZE_TIMESTAMP"
    minutes = (kickoff - freeze).total_seconds() / 60.0
    if not math.isfinite(minutes) or minutes < 0:
        return None, "FREEZE_NOT_STRICTLY_PREMATCH"
    return minutes, None


def find_horizon_band(minutes: float) -> dict[str, Any] | None:
    for band in HORIZON_BANDS:
        lower = float(band["lower_minutes"])
        upper = band["upper_minutes"]
        if minutes >= lower and (upper is None or minutes < float(upper)):
            return band
    return None


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def grouped_records(observations: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        groups[str(observation["context"].get(key) or "UNKNOWN")].append(observation)
    return dict(groups)


def coverage_for_observations(observations: list[dict[str, Any]], field_id: str) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    present = 0
    for observation in observations:
        is_present, reason = field_presence(
            field_id,
            observation["record"],
            snapshot=observation.get("snapshot"),
            context=observation["context"],
        )
        if is_present:
            present += 1
        else:
            reasons[str(reason or "MISSING_UNCLASSIFIED") ] += 1
    return coverage_summary(len(observations), present, reasons)


def build_field_coverage(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    dimensions = (
        ("competition", "competition"),
        ("provider", "provider"),
        ("source", "source"),
        ("data_grade", "data_grade"),
        ("settlement", "settlement_status"),
    )
    for field in FIELD_DEFINITIONS:
        field_id = field["id"]
        slices: dict[str, dict[str, dict[str, Any]]] = {}
        for dimension, context_key in dimensions:
            slices[dimension] = {}
            for value, rows in sorted(grouped_records(observations, context_key).items()):
                slices[dimension][value] = coverage_for_observations(rows, field_id)
        overall = coverage_for_observations(observations, field_id)
        result.append(
            {
                **field,
                "overall": overall,
                "slices": slices,
                "product_recommendation": product_recommendation(field_id, overall["coverage_label"]),
            }
        )
    return result


def product_recommendation(field_id: str, label: str) -> str:
    if field_id in CORE_REQUIRED_FIELDS:
        if label in {"UNIVERSAL", "BROAD"}:
            return "STANDARD_REQUIRED"
        if label == "PARTIAL":
            return "STANDARD_WITH_DEGRADED_FALLBACK"
        return "NOT_READY_FOR_PRODUCT_CONTRACT"
    if field_id in OPTIONAL_ENRICHMENT_FIELDS:
        if label in {"UNIVERSAL", "BROAD", "PARTIAL"}:
            return "OPTIONAL_ENRICHMENT"
        return "NOT_READY_FOR_PRODUCT_CONTRACT"
    if field_id in MARKET_DEGRADED_FIELDS:
        if label in {"UNIVERSAL", "BROAD"}:
            return "STANDARD_WITH_DEGRADED_FALLBACK"
        if label == "PARTIAL":
            return "STANDARD_WITH_DEGRADED_FALLBACK"
        return "NOT_READY_FOR_PRODUCT_CONTRACT"
    return "NOT_READY_FOR_PRODUCT_CONTRACT"


def load_snapshot_for_record(
    record: dict[str, Any], snapshot_root: Path, cache: dict[str, tuple[dict[str, Any] | None, str | None]]
) -> tuple[dict[str, Any] | None, str | None]:
    prediction_id = str(record.get("prediction_id") or record.get("_audit_path") or "")
    if prediction_id in cache:
        return cache[prediction_id]
    try:
        snapshot = load_input_snapshot(record, snapshot_root)
    except (OSError, ValueError, TypeError) as error:
        value = (None, f"INPUT_SNAPSHOT_UNAVAILABLE:{type(error).__name__}")
    else:
        value = (snapshot, None)
    cache[prediction_id] = value
    return value


def build_change_awareness(
    records_by_key: dict[str, list[dict[str, Any]]],
    snapshot_root: Path,
    snapshot_cache: dict[str, tuple[dict[str, Any] | None, str | None]],
    competition_by_key: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    integrity_failures: list[str] = []
    details: list[dict[str, Any]] = []
    multi_version_keys = 0
    safe_previous_count = 0
    pairable_count = 0
    reason_counts: Counter[str] = Counter()
    legal_version_rows = 0
    invalid_version_rows = 0

    for match_key in sorted(records_by_key):
        rows = records_by_key[match_key]
        legal_rows: list[dict[str, Any]] = []
        for record in rows:
            reason = legal_version_reason(record)
            if reason is None:
                legal_rows.append(record)
                legal_version_rows += 1
            else:
                invalid_version_rows += 1
                integrity_failures.append(f"{match_key}:{record.get('prediction_id')}:{reason}")
        legal_rows.sort(
            key=lambda record: (
                parse_aware_datetime(record.get("freeze_created_at")),
                parse_aware_datetime(record.get("prediction_created_at")),
                str(record.get("prediction_id") or ""),
            )
        )
        if len(legal_rows) < 2:
            continue
        multi_version_keys += 1
        previous = legal_rows[-2]
        current = legal_rows[-1]
        previous_snapshot, previous_error = load_snapshot_for_record(previous, snapshot_root, snapshot_cache)
        current_snapshot, current_error = load_snapshot_for_record(current, snapshot_root, snapshot_cache)
        reasons: list[str] = []
        previous_freeze = parse_aware_datetime(previous.get("freeze_created_at"))
        current_freeze = parse_aware_datetime(current.get("freeze_created_at"))
        kickoff = parse_aware_datetime(current.get("kickoff_at"))
        if previous_freeze is None:
            reasons.append("MISSING_PREVIOUS_FREEZE_TIMESTAMP")
        if current_freeze is None:
            reasons.append("MISSING_CURRENT_FREEZE_TIMESTAMP")
        if previous_freeze is not None and current_freeze is not None and previous_freeze >= current_freeze:
            reasons.append("NON_MONOTONIC_VERSION_FREEZE_ORDER")
        if previous_freeze is not None and kickoff is not None and previous_freeze >= kickoff:
            reasons.append("PREVIOUS_NOT_PREMATCH")
        if current_freeze is not None and kickoff is not None and current_freeze >= kickoff:
            reasons.append("CURRENT_NOT_PREMATCH")
        if previous_error:
            reasons.append(previous_error.split(":", 1)[0])
        if current_error:
            reasons.append(current_error.split(":", 1)[0])
        if record_match_key(previous) != match_key or record_match_key(current) != match_key:
            reasons.append("MATCH_IDENTITY_MISMATCH")

        safe_previous = not reasons
        if safe_previous:
            safe_previous_count += 1
        else:
            reason_counts.update(dict.fromkeys(reasons, 1))
        gap = None
        if previous_freeze is not None and current_freeze is not None:
            gap = (current_freeze - previous_freeze).total_seconds() / 60.0
        surfaces = {
            "1x2": False,
            "exact_top1_top3": False,
            "asian_handicap": False,
            "over_under": False,
            "frozen_evidence": False,
        }
        surface_diffs = {
            "1x2": "NOT_DIFFABLE",
            "exact_top1_top3": "NOT_DIFFABLE",
            "asian_handicap": "NOT_DIFFABLE",
            "over_under": "NOT_DIFFABLE",
            "frozen_evidence": "NOT_DIFFABLE",
        }
        if safe_previous:
            surfaces["1x2"] = field_presence("frozen_1x2", previous, context={})[0] and field_presence("frozen_1x2", current, context={})[0]
            surfaces["exact_top1_top3"] = (
                field_presence("exact_score_top1", previous, context={})[0]
                and field_presence("exact_score_top3", previous, context={})[0]
                and field_presence("exact_score_top1", current, context={})[0]
                and field_presence("exact_score_top3", current, context={})[0]
            )
            surfaces["asian_handicap"] = market_surface(previous_snapshot, "yazhi") and market_surface(current_snapshot, "yazhi")
            surfaces["over_under"] = market_surface(previous_snapshot, "daxiao") and market_surface(current_snapshot, "daxiao")
            surfaces["frozen_evidence"] = previous_snapshot is not None and current_snapshot is not None
            for surface, diffable in surfaces.items():
                if diffable:
                    surface_diffs[surface] = surface_diff_status(
                        surface,
                        previous,
                        current,
                        previous_snapshot,
                        current_snapshot,
                    )
        pairable = safe_previous
        if pairable:
            pairable_count += 1
        details.append(
            {
                "match_key": match_key,
                "competition": competition_by_key.get(match_key) or "UNKNOWN",
                "legal_version_count": len(legal_rows),
                "version_ids": [str(row.get("prediction_id") or "") for row in legal_rows],
                "previous_version_id": str(previous.get("prediction_id") or ""),
                "current_version_id": str(current.get("prediction_id") or ""),
                "safe_previous_comparable": safe_previous,
                "pairable": pairable,
                "prior_snapshot_gap_minutes": round(gap, 6) if gap is not None else None,
                "diffable_surfaces": surfaces,
                "surface_diff_status": surface_diffs,
                "not_pairable_reasons": sorted(set(reasons)),
            }
        )

    if invalid_version_rows:
        integrity_failures.append(f"INVALID_LEGAL_VERSION_ROWS:{invalid_version_rows}")
    denominator = multi_version_keys
    return (
        {
            "unique_matches_with_multiple_legal_prematch_versions": denominator,
            "legal_prematch_version_rows": legal_version_rows,
            "invalid_version_rows": invalid_version_rows,
            "safe_previous_comparable_matches": safe_previous_count,
            "safe_previous_comparable_percent": round(safe_previous_count / denominator * 100.0, 4) if denominator else 0.0,
            "pairable_matches": pairable_count,
            "pairable_percent": round(pairable_count / denominator * 100.0, 4) if denominator else 0.0,
            "not_pairable_reasons": dict(sorted(reason_counts.items())),
            "surface_pairability": {
                surface: sum(1 for detail in details if detail["diffable_surfaces"][surface])
                for surface in ("1x2", "exact_top1_top3", "asian_handicap", "over_under", "frozen_evidence")
            },
            "surface_diff_status_counts": {
                surface: dict(
                    sorted(
                        Counter(detail["surface_diff_status"][surface] for detail in details).items()
                    )
                )
                for surface in ("1x2", "exact_top1_top3", "asian_handicap", "over_under", "frozen_evidence")
            },
            "match_details": details,
        },
        integrity_failures,
    )


def build_horizon_map(observations: list[dict[str, Any]]) -> dict[str, Any]:
    values = [observation["context"]["horizon_minutes"] for observation in observations if observation["context"].get("horizon_minutes") is not None]
    missing_reasons = Counter(
        str(observation["context"].get("horizon_missing_reason") or "HORIZON_NOT_SAFE_TO_COMPUTE")
        for observation in observations
        if observation["context"].get("horizon_minutes") is None
    )
    raw = {
        "eligible_unique_matches": len(observations),
        "safe_unique_matches": len(values),
        "unsafe_unique_matches": len(observations) - len(values),
        "missing_reasons": dict(sorted(missing_reasons.items())),
        "minutes_sorted": [round(value, 6) for value in sorted(values)],
        "statistics_minutes": {
            "min": round(min(values), 6) if values else None,
            "p10": round(percentile(values, 0.10), 6) if percentile(values, 0.10) is not None else None,
            "p25": round(percentile(values, 0.25), 6) if percentile(values, 0.25) is not None else None,
            "median": round(percentile(values, 0.50), 6) if percentile(values, 0.50) is not None else None,
            "p75": round(percentile(values, 0.75), 6) if percentile(values, 0.75) is not None else None,
            "p90": round(percentile(values, 0.90), 6) if percentile(values, 0.90) is not None else None,
            "max": round(max(values), 6) if values else None,
        },
    }
    bands: list[dict[str, Any]] = []
    for band in HORIZON_BANDS:
        rows = [
            observation
            for observation in observations
            if observation["context"].get("horizon_band_id") == band["id"]
        ]
        band_row = {
            **band,
            "unique_matches": len(rows),
            "share_of_eligible_percent": round(len(rows) / len(observations) * 100.0, 4) if observations else 0.0,
            "field_coverage": {
                field_id: coverage_for_observations(rows, field_id)
                for field_id in FIELD_IDS
            },
        }
        bands.append(band_row)

    competition_rows: list[dict[str, Any]] = []
    for competition, rows in sorted(grouped_records(observations, "competition").items()):
        band_counts = Counter(row["context"].get("horizon_band_id") for row in rows)
        weak_count = sum(band_counts[band_id] for band_id in WEAK_HORIZON_BANDS)
        share = weak_count / len(rows) if rows else 0.0
        competition_rows.append(
            {
                "competition": competition,
                "unique_matches": len(rows),
                "band_counts": dict(sorted(band_counts.items())),
                "weak_horizon_unique_matches": weak_count,
                "weak_horizon_share_percent": round(share * 100.0, 4),
                "materially_concentrated_in_weak_horizon": bool(
                    len(rows) >= MIN_COMPETITION_MATCHES_FOR_CONCENTRATION
                    and share >= MATERIAL_CONCENTRATION_SHARE
                ),
            }
        )
    return {
        "raw_lead_time_distribution": raw,
        "band_policy": {
            "interval_convention": "lower inclusive, upper exclusive; T_24H_PLUS has no upper bound",
            "bands": list(HORIZON_BANDS),
            "weak_horizon_bands": sorted(WEAK_HORIZON_BANDS),
            "material_concentration_share": MATERIAL_CONCENTRATION_SHARE,
            "minimum_competition_unique_matches": MIN_COMPETITION_MATCHES_FOR_CONCENTRATION,
        },
        "bands": bands,
        "competition_horizon_map": competition_rows,
    }


def build_funnel(
    universe_rows: list[dict[str, Any]],
    universe_errors: list[str],
    base_jobs: list[dict[str, Any]],
    base_errors: list[str],
    formal_records: list[dict[str, Any]],
    accepted_unique_keys: set[str],
    raw_formal_flag_keys: set[str],
    reader_rejected_formal_flags: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    result_all: dict[str, dict[str, Any]],
    result_valid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    universe_keys = {row["match_key"] for row in universe_rows}
    base_keys = {row["match_key"] for row in base_jobs}
    base_frozen = [row for row in base_jobs if row.get("status") == "FROZEN"]
    base_frozen_keys = {row["match_key"] for row in base_frozen}
    ledger_keys = {row["match_key"] for row in ledger_rows}
    result_linked_keys = accepted_unique_keys & ledger_keys & set(result_all)
    verified_keys = result_linked_keys & set(result_valid)
    missing_formal = universe_keys - accepted_unique_keys
    missing_by_status = Counter()
    base_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_jobs:
        base_by_key[row["match_key"]].append(row)
    formal_base_status_counts: Counter[str] = Counter()
    for key in sorted(accepted_unique_keys):
        statuses = {str(row.get("status") or "UNKNOWN") for row in base_by_key.get(key, [])}
        formal_base_status_counts[sorted(statuses)[0] if len(statuses) == 1 else "MULTIPLE_STATUSES" if statuses else "NO_CURRENT_BASE_JOB"] += 1
    for key in sorted(missing_formal):
        statuses = {row.get("status") for row in base_by_key.get(key, [])}
        if "MISSED_PREMATCH_WINDOW" in statuses:
            missing_by_status["MISSED_PREMATCH_WINDOW"] += 1
        elif "INSUFFICIENT_DATA" in statuses:
            missing_by_status["INSUFFICIENT_DATA"] += 1
        elif not statuses:
            missing_by_status["NO_CURRENT_BASE_JOB"] += 1
        else:
            missing_by_status["NO_ACCEPTED_FORMAL_FREEZE"] += 1
    unresolved_result_keys = result_linked_keys - set(result_valid)
    no_result_keys = accepted_unique_keys - result_linked_keys
    return {
        "observation_unit": "one football match = one unique match_key; version rows are audit history only",
        "stages": [
            {"stage": "universe_candidates", "rows": len(universe_rows), "unique_matches": len(universe_keys)},
            {"stage": "current_base_job_rows", "rows": len(base_jobs), "unique_matches": len(base_keys)},
            {"stage": "current_base_frozen_rows", "rows": len(base_frozen), "unique_matches": len(base_frozen_keys)},
            {"stage": "formal_frozen_rows_accepted_by_existing_reader", "rows": len(formal_records), "unique_matches": len(accepted_unique_keys)},
            {"stage": "unique_frozen_matches", "rows": len(accepted_unique_keys), "unique_matches": len(accepted_unique_keys)},
            {"stage": "result_linked_unique_matches", "rows": len(result_linked_keys), "unique_matches": len(result_linked_keys)},
            {"stage": "verified_unique_matches", "rows": len(verified_keys), "unique_matches": len(verified_keys)},
        ],
        "drop_reasons": {
            "universe_to_accepted_formal_unique": {
                "missing_accepted_formal_freeze_unique_matches": len(missing_formal),
                "by_current_base_status": dict(sorted(missing_by_status.items())),
                "universe_reader_errors": len(universe_errors),
                "base_reader_errors": len(base_errors),
            },
            "accepted_formal_unique_not_in_current_universe": len(accepted_unique_keys - universe_keys),
            "raw_formal_flags_not_accepted_by_existing_reader": len(reader_rejected_formal_flags),
            "accepted_formal_to_result_linked": {
                "no_result_link": len(no_result_keys),
            },
            "result_linked_to_verified": {
                "result_artifact_unresolved_or_invalid_90m": len(unresolved_result_keys),
            },
        },
        "cross_checks": {
            "universe_unique_matches": len(universe_keys),
            "current_base_job_unique_matches": len(base_keys),
            "current_base_frozen_unique_matches": len(base_frozen_keys),
            "formal_unique_matches_not_in_universe": len(accepted_unique_keys - universe_keys),
            "formal_unique_matches_not_in_ledger": len(accepted_unique_keys - ledger_keys),
            "formal_unique_matches_by_current_base_status": dict(sorted(formal_base_status_counts.items())),
            "ledger_unique_matches": len(ledger_keys),
            "result_files": len(result_all),
            "valid_result_files": len(result_valid),
        },
        "version_rows_are_not_observations": True,
        "raw_formal_flag_unique_matches": len(raw_formal_flag_keys),
    }


def integrity_checks(
    all_frozen_records: list[dict[str, Any]],
    rejected_records: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    accepted_unique_keys: set[str],
    universe_rows: list[dict[str, Any]],
    base_jobs: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    result_errors: list[str],
    observations: list[dict[str, Any]],
    change_failures: list[str],
) -> dict[str, Any]:
    failures: list[str] = []
    identity_mismatches: list[str] = []
    for record in formal_rows:
        key = record_match_key(record)
        identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
        if not key or identity.get("match_key") != key:
            identity_mismatches.append(str(record.get("prediction_id") or record.get("_audit_path")))
    if identity_mismatches:
        failures.append(f"FORMAL_RECORD_IDENTITY_MISMATCH:{len(identity_mismatches)}")
    universe_keys = [row["match_key"] for row in universe_rows]
    if len(universe_keys) != len(set(universe_keys)):
        failures.append("UNIVERSE_DUPLICATE_UNIQUE_MATCH_KEY")
    base_keys = [row["match_key"] for row in base_jobs]
    if len(base_keys) != len(set(base_keys)):
        failures.append("CURRENT_BASE_JOB_DUPLICATE_UNIQUE_MATCH_KEY")
    ledger_keys = [row["match_key"] for row in ledger_rows]
    if len(ledger_keys) != len(set(ledger_keys)):
        # Ledger versions are allowed and expected; this is not an integrity
        # failure.  The unique key count is handled in the funnel.
        pass
    if result_errors:
        duplicate_or_identity_errors = [error for error in result_errors if "duplicate_result_key" in error]
        if duplicate_or_identity_errors:
            failures.extend(duplicate_or_identity_errors)
    for observation in observations:
        if record_match_key(observation["record"]) != observation["match_key"]:
            failures.append(f"OBSERVATION_KEY_MISMATCH:{observation['match_key']}")
    failures.extend(change_failures)
    # Reader-rejected records are surfaced as an explicit cohort drop, not
    # silently folded into the observation denominator.
    return {
        "integrity_failures": sorted(set(failures)),
        "reader_rejected_frozen_records": len(rejected_records),
        "formal_record_identity_mismatch_count": len(identity_mismatches),
        "accepted_formal_unique_match_count": len(accepted_unique_keys),
        "frozen_store_reader_rejections_are_excluded": True,
        "postmatch_fields_used_for_prematch_selection": False,
        "model_frozen_history_serving_mutated": False,
    }


def decide_top_level(
    field_coverage: list[dict[str, Any]],
    horizon: dict[str, Any],
    integrity: dict[str, Any],
) -> str:
    if integrity["integrity_failures"]:
        return "FAIL_CLOSED"
    field_map = {field["id"]: field for field in field_coverage}
    if any(field_map[field_id]["overall"]["coverage_label"] not in {"UNIVERSAL", "BROAD"} for field_id in CORE_REQUIRED_FIELDS):
        return "DECISION_PACKET_CORE_NOT_READY"
    raw = horizon["raw_lead_time_distribution"]
    horizon_ratio = raw["safe_unique_matches"] / raw["eligible_unique_matches"] if raw["eligible_unique_matches"] else 0.0
    if horizon_ratio < 0.95:
        return "DECISION_PACKET_CORE_NOT_READY"
    if any(
        field["overall"]["coverage_label"] not in {"UNIVERSAL", "BROAD"}
        or field["product_recommendation"] in {"STANDARD_WITH_DEGRADED_FALLBACK", "OPTIONAL_ENRICHMENT", "NOT_READY_FOR_PRODUCT_CONTRACT"}
        for field in field_coverage
        if field["id"] not in CORE_REQUIRED_FIELDS
    ):
        return "DECISION_PACKET_CORE_READY_WITH_DEGRADED_FIELDS"
    return "DECISION_PACKET_CORE_READY"


def build_observations(
    formal_rows: list[dict[str, Any]],
    snapshot_root: Path,
    snapshot_cache: dict[str, tuple[dict[str, Any] | None, str | None]],
    universe_by_key: dict[str, dict[str, Any]],
    valid_result_keys: set[str],
    ledger_keys: set[str],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in formal_rows:
        by_key[record_match_key(record)].append(record)
    observations: list[dict[str, Any]] = []
    chronology_failures: list[str] = []
    for key in sorted(by_key):
        selected = select_latest_legal_version(by_key[key])
        if selected is None:
            chronology_failures.append(f"{key}:NO_LEGAL_PREMATCH_VERSION")
            continue
        snapshot, snapshot_error = load_snapshot_for_record(selected, snapshot_root, snapshot_cache)
        horizon_minutes, horizon_error = safe_horizon_minutes(selected)
        if horizon_error:
            chronology_failures.append(f"{key}:{horizon_error}")
        if snapshot_error:
            chronology_failures.append(f"{key}:{snapshot_error}")
        universe = universe_by_key.get(key, {})
        competition = str(universe.get("competition") or "").strip() or "UNKNOWN"
        provider_values = selected.get("market_data_providers")
        source_values = selected.get("market_sources")
        provider = "+".join(sorted(str(value).strip() for value in provider_values if str(value).strip())) if isinstance(provider_values, list) else ""
        source = "+".join(sorted(str(value).strip() for value in source_values if str(value).strip())) if isinstance(source_values, list) else ""
        settlement_status = "SETTLED_VERIFIED" if key in valid_result_keys else (
            "RESULT_LINKED_UNRESOLVED" if key in ledger_keys else "CURRENT_UNSETTLED"
        )
        context = {
            "competition": competition,
            "provider": provider or "UNKNOWN",
            "source": source or "UNKNOWN",
            "data_grade": str(selected.get("data_grade") or "UNKNOWN"),
            "settlement_status": settlement_status,
            "result_missing_reason": "RESULT_ARTIFACT_UNRESOLVED" if key in ledger_keys else "NO_RESULT_ARTIFACT",
            "horizon_minutes": horizon_minutes,
            "horizon_missing_reason": horizon_error,
            "horizon_band_id": find_horizon_band(horizon_minutes)["id"] if horizon_minutes is not None and find_horizon_band(horizon_minutes) else None,
        }
        observations.append(
            {
                "match_key": key,
                "record": selected,
                "snapshot": snapshot,
                "context": context,
                "version_count": len(by_key[key]),
            }
        )
    return observations, dict(by_key), chronology_failures


def inventory_summary(
    all_records: list[dict[str, Any]],
    rejected_records: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    result_all: dict[str, dict[str, Any]],
    result_valid: dict[str, dict[str, Any]],
    universe_rows: list[dict[str, Any]],
    base_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    statuses = Counter(str(record.get("prediction_status") or "UNKNOWN") for record in all_records)
    raw_formal = [record for record in all_records if record.get("prediction_status") in FORMAL_STATUSES and record.get("formal_eligible") is True]
    formal_unique = {record_match_key(record) for record in formal_rows}
    raw_formal_unique = {record_match_key(record) for record in raw_formal}
    ledger_unique = {row["match_key"] for row in ledger_rows}
    universe_unique = {row["match_key"] for row in universe_rows}
    base_unique = {row["match_key"] for row in base_jobs}
    return {
        "frozen_prediction_store": {
            "reader_valid_rows": len(all_records),
            "reader_rejected_rows": len(rejected_records),
            "prediction_status_counts": dict(sorted(statuses.items())),
            "raw_formal_flag_rows": len(raw_formal),
            "raw_formal_flag_unique_matches": len(raw_formal_unique),
            "reader_accepted_formal_rows": len(formal_rows),
            "reader_accepted_formal_unique_matches": len(formal_unique),
            "research_only_rows": sum(1 for record in all_records if record.get("prediction_status") == "research_only"),
            "model_roles": dict(sorted(Counter(str(record.get("model_role") or "UNKNOWN") for record in formal_rows).items())),
            "data_grades": dict(sorted(Counter(str(record.get("data_grade") or "UNKNOWN") for record in formal_rows).items())),
        },
        "prospective_ledger": {
            "version_rows": len(ledger_rows),
            "unique_matches": len(ledger_unique),
            "duplicate_version_rows": len(ledger_rows) - len(ledger_unique),
        },
        "prediction_universe": {
            "rows": len(universe_rows),
            "unique_matches": len(universe_unique),
        },
        "base_prediction_jobs": {
            "current_job_rows": len(base_jobs),
            "unique_matches": len(base_unique),
            "status_counts": dict(sorted(Counter(row.get("status") or "UNKNOWN" for row in base_jobs).items())),
        },
        "result_artifacts": {
            "files_with_keys": len(result_all),
            "valid_regulation_only_files": len(result_valid),
            "unresolved_or_invalid_files": len(result_all) - len(result_valid),
        },
    }


def render_coverage_table(field_coverage: list[dict[str, Any]]) -> str:
    lines = [
        "| Field | Group | Eligible unique | Present unique | Coverage | Label | Product recommendation | Missing reasons |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for field in field_coverage:
        overall = field["overall"]
        reasons = ", ".join(f"{key}={value}" for key, value in overall["missing_reasons"].items()) or "—"
        lines.append(
            f"| {field['name']} (`{field['id']}`) | {field['group']} | {overall['eligible_unique_matches']} | {overall['present_unique_matches']} | {overall['coverage_percent']:.4f}% | {overall['coverage_label']} | {field['product_recommendation']} | {reasons} |"
        )
    return "\n".join(lines)


def render_slice_tables(field_coverage: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for dimension in ("competition", "provider", "source", "data_grade", "settlement"):
        lines.extend(
            [
                f"### {dimension}",
                "| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |",
                "|---|---|---:|---:|---:|---|---|",
            ]
        )
        for field in field_coverage:
            for value, summary in field["slices"][dimension].items():
                reasons = ", ".join(f"{key}={count}" for key, count in summary["missing_reasons"].items()) or "—"
                lines.append(
                    f"| `{field['id']}` | {value} | {summary['eligible_unique_matches']} | {summary['present_unique_matches']} | {summary['coverage_percent']:.4f}% | {summary['coverage_label']} | {reasons} |"
                )
        lines.append("")
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    funnel = summary["sample_funnel"]
    horizon = summary["horizon_map"]
    raw = horizon["raw_lead_time_distribution"]
    stats = raw["statistics_minutes"]
    lines = [
        "# Decision Packet coverage and horizon audit",
        "",
        f"- Issue: #{summary['issue']} — `{summary['milestone']}`",
        f"- Source `origin/main` SHA: `{summary['source_main_sha']}`",
        f"- Top-level decision: **`{summary['top_level_decision']}`**",
        "- Scope: read-only audit of repository-resident frozen/prospective truth; no UI, API, new data acquisition, The Odds API, Reep, model, calibration, serving, or frozen-history change.",
        "- Observation unit: **one football match = one unique `match_key`**. Version rows are counted only in the Change Awareness section.",
        "",
        "## Authority and anti-leakage contract",
        "",
        "The audit loads frozen prediction records through the existing governance reader and applies the existing formal eligibility reader. Input evidence is loaded from the stored input snapshot reader. Competition is a deterministic canonical join to the stored Prediction Universe fixture; it is not inferred from UI or collector code. Verified linkage uses only the formal ledger match key and a regulation-only result artifact. Postmatch result values are not read into any prematch field, are not used to choose a frozen version, and are not emitted in this report.",
        "",
        "### Source paths",
        "",
    ]
    lines.extend(f"- `{path}`" for path in summary["source_paths"])
    lines.extend(["", "### Readers", ""])
    lines.extend(f"- `{path}`" for path in summary["reader_paths"])
    lines.extend(
        [
            "",
            "The one-observation representative is the latest **legal prematch** version by `(freeze_created_at, prediction_created_at, prediction_id)`. This is chronology-only and never uses a postmatch result. Earlier versions remain available for Change Awareness only.",
            "",
            "## Inventory",
            "",
            "```json",
            json.dumps(summary["inventory"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## A. Unique-match sample funnel",
            "",
            "| Stage | Rows | Unique matches |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {stage['stage']} | {stage['rows']} | {stage['unique_matches']} |"
        for stage in funnel["stages"]
    )
    lines.extend(
        [
            "",
            "`formal_frozen_rows_accepted_by_existing_reader` is intentionally a version-row count; `unique_frozen_matches` is the only product observation denominator. The current BASE job status is shown separately because it is an operational cross-check, not a rewrite of immutable frozen truth. A current-universe snapshot can also omit an already-frozen historical match; those reconciliation counts remain explicit rather than being silently dropped.",
            "",
            "### Funnel drop reasons",
            "",
            "```json",
            json.dumps(funnel["drop_reasons"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## B. Decision Packet field coverage",
            "",
            "Coverage labels are fixed: `UNIVERSAL >=95%`, `BROAD 80–<95%`, `PARTIAL 50–<80%`, `SPARSE <50%`. Missing reasons are exhaustive for each field: eligible unique matches = present unique matches + reason counts.",
            "",
            render_coverage_table(summary["field_coverage"]),
            "",
            "The following complete slice matrices cover competition, provider, source, data grade, and settlement status. They are generated from the same unique-match representatives and contain no postmatch values.",
            "",
            render_slice_tables(summary["field_coverage"]),
            "",
            "## C. Actual prematch freeze horizon",
            "",
            "The raw distribution is reported before descriptive bands. Lead time is `kickoff_at - freeze_created_at`, using explicit timezone-aware frozen timestamps only; no source timestamp or guessed window is substituted.",
            "",
            "### Raw lead-time distribution",
            "",
            f"- Eligible unique matches: {raw['eligible_unique_matches']}",
            f"- Safe unique matches: {raw['safe_unique_matches']}",
            f"- Unsafe unique matches: {raw['unsafe_unique_matches']}",
            f"- min / p10 / p25 / median / p75 / p90 / max (minutes): {stats['min']} / {stats['p10']} / {stats['p25']} / {stats['median']} / {stats['p75']} / {stats['p90']} / {stats['max']}",
            "",
            "```json",
            json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "### Deterministic descriptive bands and coverage",
            "",
            "Bands use lower-inclusive / upper-exclusive intervals; `T-24h+` has no upper bound. Weak horizon is fixed to the first two bands (`<3h`) for descriptive concentration reporting only.",
            "",
            "| Band | Unique matches | Share |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {band['label']} (`{band['id']}`) | {band['unique_matches']} | {band['share_of_eligible_percent']:.4f}% |"
        for band in horizon["bands"]
    )
    lines.extend(
        [
            "",
            "Field coverage by every horizon band is persisted in `summary.json` under `horizon_map.bands[].field_coverage`. Weak-competition concentration is below.",
            "",
            "| Competition | Unique matches | Weak-horizon matches | Weak-horizon share | Material concentration | Band counts |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for row in horizon["competition_horizon_map"]:
        lines.append(
            f"| {row['competition']} | {row['unique_matches']} | {row['weak_horizon_unique_matches']} | {row['weak_horizon_share_percent']:.4f}% | {row['materially_concentrated_in_weak_horizon']} | {json.dumps(row['band_counts'], ensure_ascii=False, sort_keys=True)} |"
        )
    lines.extend(
        [
            "",
            "## D. Change Awareness previous-comparable snapshot",
            "",
            "Only formal-reader-accepted legal prematch versions are considered. For each unique match with at least two legal versions, the current snapshot is the latest legal version and the previous snapshot is the immediately preceding legal version by frozen timestamp. This section does not use result artifacts to select either version and provides no causal interpretation.",
            "",
            "```json",
            json.dumps({key: value for key, value in summary["change_awareness"].items() if key != "match_details"}, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "### Per-match chronology and diffability",
            "",
            "| Match key | Competition | Legal versions | Previous safe | Gap (min) | 1X2 diff | Exact Top1+Top3 diff | AH diff | O/U diff | Frozen evidence diff | Not-pairable reasons |",
            "|---|---|---:|---|---:|---|---|---|---|---|---|",
        ]
    )
    for detail in summary["change_awareness"]["match_details"]:
        diffs = detail["surface_diff_status"]
        reasons = ", ".join(detail["not_pairable_reasons"]) or "—"
        gap = detail["prior_snapshot_gap_minutes"]
        lines.append(
            f"| `{detail['match_key']}` | {detail['competition']} | {detail['legal_version_count']} | {detail['safe_previous_comparable']} | {gap if gap is not None else '—'} | {diffs['1x2']} | {diffs['exact_top1_top3']} | {diffs['asian_handicap']} | {diffs['over_under']} | {diffs['frozen_evidence']} | {reasons} |"
        )
    lines.extend(
        [
            "",
            "## E. Product-contract recommendation",
            "",
            "Recommendations are deterministic consequences of measured unique-match coverage and the fixed labels; they do not change thresholds or model behavior.",
            "",
            "| Field | Coverage label | Recommendation |",
            "|---|---|---|",
        ]
    )
    lines.extend(
        f"| {field['name']} (`{field['id']}`) | {field['overall']['coverage_label']} | {field['product_recommendation']} |"
        for field in summary["field_coverage"]
    )
    lines.extend(
        [
            "",
            "## Integrity and delivery boundary",
            "",
            "```json",
            json.dumps(summary["integrity"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "No model, Champion/Challenger, calibration, serving, frozen record, or frozen-history file is modified by this research-only audit. The output is ready for independent acceptance; **DO NOT MERGE** until that acceptance is complete.",
            "",
        ]
    )
    return "\n".join(lines)


def build_summary(root: Path, source_main_sha: str | None = None) -> dict[str, Any]:
    record_root = root / "data" / "model_governance" / "predictions"
    snapshot_root = root / "data" / "model_governance" / "input_snapshots"
    universe_root = root / "data" / "prediction_universe"
    base_root = root / "data" / "base_prediction_jobs"
    ledger_path = root / "data" / "prospective" / "ledger.jsonl"
    result_root = root / "data" / "postmatch_automation" / "results"
    all_records, reader_rejected = load_frozen_records(record_root)
    formal_rows = [record for record in all_records if is_formally_eligible(record)]
    raw_formal_rows = [record for record in all_records if record.get("prediction_status") in FORMAL_STATUSES and record.get("formal_eligible") is True]
    reader_rejected_formal_flags = [
        {"prediction_id": record.get("prediction_id"), "match_key": record_match_key(record), "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"}
        for record in raw_formal_rows
        if not is_formally_eligible(record)
    ]
    universe_rows, universe_errors = load_universe_records(universe_root)
    base_jobs, base_errors = load_base_job_records(base_root)
    ledger_rows, ledger_errors = load_ledger_records(ledger_path)
    result_all, result_valid, result_errors = load_result_records(result_root)
    universe_by_key: dict[str, dict[str, Any]] = {}
    for row in universe_rows:
        universe_by_key.setdefault(row["match_key"], row)
    ledger_keys = {row["match_key"] for row in ledger_rows}
    valid_result_keys = set(result_valid) & ledger_keys
    snapshot_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    observations, records_by_key, chronology_failures = build_observations(
        formal_rows,
        snapshot_root,
        snapshot_cache,
        universe_by_key,
        valid_result_keys,
        ledger_keys,
    )
    change_awareness, change_failures = build_change_awareness(
        records_by_key,
        snapshot_root,
        snapshot_cache,
        {key: str(row.get("competition") or "") for key, row in universe_by_key.items()},
    )
    field_coverage = build_field_coverage(observations)
    horizon_map = build_horizon_map(observations)
    accepted_unique_keys = {observation["match_key"] for observation in observations}
    integrity = integrity_checks(
        all_records,
        reader_rejected,
        formal_rows,
        accepted_unique_keys,
        universe_rows,
        base_jobs,
        ledger_rows,
        result_errors,
        observations,
        chronology_failures + change_failures,
    )
    top_level_decision = decide_top_level(field_coverage, horizon_map, integrity)
    if source_main_sha is None:
        try:
            source_main_sha = subprocess.check_output(
                ["git", "rev-parse", "origin/main"], cwd=root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            source_main_sha = "UNKNOWN"
    summary = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "issue": 183,
        "milestone": "DECISION-PACKET-COVERAGE-AND-HORIZON-AUDIT-1",
        "source_main_sha": source_main_sha,
        "audit_code_path": "scripts/decision_packet_coverage_audit.py",
        "source_paths": SOURCE_PATHS,
        "reader_paths": READER_PATHS,
        "scope": {
            "read_only": True,
            "external_api_used": False,
            "new_data_downloaded": False,
            "odds_api_used": False,
            "reep_used": False,
            "ui_changed": False,
            "model_champion_challenger_calibration_serving_changed": False,
            "frozen_history_changed": False,
            "postmatch_values_used_to_select_prematch_version": False,
            "observation_unit": "one football match = one unique match_key",
        },
        "policy": {
            "coverage_labels": {label: {"minimum_inclusive_ratio": threshold} for threshold, label in COVERAGE_LABELS},
            "horizon_timestamp_rule": "kickoff_at - freeze_created_at; both timezone-aware; freeze strictly before kickoff",
            "horizon_percentile_rule": "linear interpolation over sorted safe unique-match minutes",
            "horizon_bands": list(HORIZON_BANDS),
            "change_awareness_current_rule": "latest legal prematch version by freeze_created_at, prediction_created_at, prediction_id",
            "change_awareness_previous_rule": "immediately preceding legal prematch version by the same chronology",
            "result_scope": RESULT_SCOPE,
        },
        "inventory": inventory_summary(
            all_records,
            reader_rejected,
            formal_rows,
            ledger_rows,
            result_all,
            result_valid,
            universe_rows,
            base_jobs,
        ),
        "sample_funnel": build_funnel(
            universe_rows,
            universe_errors,
            base_jobs,
            base_errors,
            formal_rows,
            accepted_unique_keys,
            {record_match_key(record) for record in raw_formal_rows},
            reader_rejected_formal_flags,
            ledger_rows,
            result_all,
            result_valid,
        ),
        "field_coverage": field_coverage,
        "horizon_map": horizon_map,
        "change_awareness": change_awareness,
        "integrity": {
            **integrity,
            "universe_reader_errors": universe_errors,
            "base_reader_errors": base_errors,
            "ledger_reader_errors": ledger_errors,
            "result_reader_errors": result_errors,
            "chronology_failures": chronology_failures,
            "reader_rejected_formal_flags": reader_rejected_formal_flags,
        },
        "top_level_decision": top_level_decision,
        "stop": "READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE",
    }
    return summary


def safe_output_dir(root: Path, output_dir: Path) -> Path:
    resolved_root = root.resolve()
    resolved_output = output_dir.resolve()
    protected_roots = [
        resolved_root / "data" / "model_governance",
        resolved_root / "data" / "prospective",
        resolved_root / "data" / "product_runtime",
        resolved_root / "data" / "prediction_dashboard",
    ]
    if any(resolved_output == protected or protected in resolved_output.parents for protected in protected_roots):
        raise ValueError("audit output cannot be written inside protected truth/runtime directories")
    return resolved_output


def write_outputs(summary: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-main-sha", default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = safe_output_dir(root, args.output_dir if args.output_dir.is_absolute() else root / args.output_dir)
    summary = build_summary(root, args.source_main_sha)
    summary_path, report_path = write_outputs(summary, output_dir)
    print(json.dumps({"top_level_decision": summary["top_level_decision"], "summary": str(summary_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
