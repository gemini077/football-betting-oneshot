"""Run the Champion once for every eligible BASE job and freeze it.

This runner is deliberately smaller than the deep-analysis pipeline.  Its
only output authority is the existing model-governance store; it does not
create a second prediction or report format.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from automatic_model_core import (  # noqa: E402
    MODEL_FAMILY,
    _consensus_probabilities,
    build_automatic_model,
)
from fetch_and_parse import DEFAULT_CACHE_DIR, fetch_and_parse  # noqa: E402
from fetch_trade_matches import fetch_trade_matches  # noqa: E402
from match_identity import canonical_match_id  # noqa: E402
from model_governance import (  # noqa: E402
    DEFAULT_INPUT_SNAPSHOT_ROOT,
    DEFAULT_RECORD_ROOT,
    PredictionConflictError,
    build_deterministic_model_input_snapshot,
    build_prediction_record,
    freeze_prediction,
    load_config,
    prediction_content_hash,
)
from nowscore_markets import fetch_match_markets  # noqa: E402
from prediction_universe import load_prediction_universe  # noqa: E402
from prediction_quality import recent_form_is_usable  # noqa: E402
from target_team_identity_bridge import resolve_target_team_identity  # noqa: E402


JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
ANALYSIS_INPUT_ROOT = PROJECT_ROOT / "data" / "analysis_inputs" / "automated"
UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
LOCAL_TZ = timezone(timedelta(hours=8))
RETRYABLE_STATUSES = {"PENDING", "INSUFFICIENT_DATA", "PREDICTION_FAILED"}
TERMINAL_STATUSES = {"FROZEN", "MISSED_PREMATCH_WINDOW", "PREDICTED"}
UNIVERSE_STATUSES = {"READY", "EMPTY_CONFIRMED"}


class GovernanceContractBlocker(RuntimeError):
    """The existing governance contract rejected the minimum BASE payload."""


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed


def _iso(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed else None


def _present(value: Any) -> bool:
    return value not in (None, "")


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if _present(row.get(key)):
            return row[key]
    return None


def _relative_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _source_ref(path: Path, captured_at: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": _relative_ref(path)}
    normalized = _iso(captured_at)
    if normalized:
        value["captured_at"] = normalized
    return value


def _kickoff(job: dict[str, Any]) -> str:
    return str(job.get("kickoff") or "")


def _job_fixture(universe: dict[str, Any], job: dict[str, Any]) -> dict[str, Any] | None:
    fixtures = universe.get("fixtures") or []
    target_id = str(job.get("match_id") or "")
    if target_id:
        for fixture in fixtures:
            if isinstance(fixture, dict) and str(_first(fixture, "matchId", "match_id", "id") or "") == target_id:
                return fixture
    target_num = str(job.get("match_num") or "")
    for fixture in fixtures:
        if isinstance(fixture, dict) and str(_first(fixture, "matchNum", "match_num") or "") == target_num:
            return fixture
    return None


def _form_is_usable(form: Any) -> bool:
    return recent_form_is_usable(form)


def _valid_spf(odds: Any) -> dict[str, float] | None:
    if not isinstance(odds, dict):
        return None
    try:
        values = {key: float(odds[key]) for key in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 1.0 for value in values.values()):
        return None
    return values


def _fair_probabilities(odds: dict[str, float]) -> dict[str, float]:
    inverse = {key: 1.0 / value for key, value in odds.items()}
    total = sum(inverse.values())
    return {key: round(value / total, 9) for key, value in inverse.items()}


def _official_market_baseline(
    universe: dict[str, Any], fixture: dict[str, Any], kickoff: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    odds = _valid_spf(fixture.get("spf"))
    if odds is None:
        return None, "MISSING_MARKET_INTELLIGENCE"
    captured_at = _parse_timestamp(
        fixture.get("captured_at") or fixture.get("fetched_at") or universe.get("fetched_at")
    )
    if captured_at is None or captured_at >= kickoff:
        return None, "INPUT_TIMESTAMP_UNVERIFIED"
    fair = _fair_probabilities(odds)
    return {
        "source": "sporttery_spf",
        "captured_at": captured_at.isoformat(),
        "source_odds": odds,
        "fair_probabilities": fair,
        "role": "official_market_baseline_only_not_model_probability",
    }, None


def _snapshot_capture(snapshot: dict[str, Any]) -> datetime | None:
    for key in ("fetched_at", "captured_at", "source_timestamp", "source_time"):
        captured = _parse_timestamp(snapshot.get(key))
        if captured:
            return captured
    return None


def _valid_bookmakers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("ouzhi") or {}).get("bookmakers") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or _valid_spf(row.get("spf_current")) is None:
            continue
        valid.append(row)
    return valid


def _company_name(row: dict[str, Any]) -> str | None:
    for key in ("name", "company", "company_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    value = str(row.get("cid") or "").strip()
    return f"cid:{value}" if value else None


def _valid_handicap_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("yazhi") or {}).get("companies") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not _company_name(row):
            continue
        line_present = row.get("current_handicap") not in (None, "") or row.get("current_handicap_str") not in (None, "")
        if not line_present:
            continue
        try:
            waters = [float(row[key]) for key in ("current_water_home", "current_water_away")]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in waters):
            valid.append(row)
    return valid


def _valid_total_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ((snapshot.get("daxiao") or {}).get("companies") or [])
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not _company_name(row):
            continue
        line_present = row.get("current_line") not in (None, "") or row.get("current_line_str") not in (None, "")
        if not line_present:
            continue
        try:
            waters = [float(row[key]) for key in ("current_over_water", "current_under_water")]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in waters):
            valid.append(row)
    return valid


def _market_families(snapshot: dict[str, Any]) -> list[str]:
    families: list[str] = []
    if _valid_bookmakers(snapshot):
        families.append("1x2")
    if _valid_handicap_rows(snapshot):
        families.append("asian_handicap")
    if _valid_total_rows(snapshot):
        families.append("totals")
    return families


def _market_bookmakers(snapshot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    rows = [
        *_valid_bookmakers(snapshot),
        *_valid_handicap_rows(snapshot),
        *_valid_total_rows(snapshot),
    ]
    for row in rows:
        name = _company_name(row)
        if name and name not in names:
            names.append(name)
    return names


def _market_provider(name: str) -> str:
    return {"500_deep": "500.com", "nowscore": "nowscore"}.get(name, name)


def _has_full_market(snapshot: dict[str, Any]) -> bool:
    return len(_valid_bookmakers(snapshot)) >= 2 and set(("1x2", "asian_handicap", "totals")) <= set(
        _market_families(snapshot)
    )


def _market_only_baseline(
    snapshot: dict[str, Any], source: str, source_refs: list[str]
) -> dict[str, Any] | None:
    probabilities = _consensus_probabilities(snapshot)
    if not probabilities:
        return None
    return {
        "home": round(float(probabilities["home"]), 9),
        "draw": round(float(probabilities["draw"]), 9),
        "away": round(float(probabilities["away"]), 9),
        "method": "existing_multibook_consensus_devig",
        "sources": [source, *source_refs],
    }


def _find_existing_form(
    job: dict[str, Any], kickoff: datetime, now: datetime
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    """Reuse only an existing named prematch snapshot with a verifiable time."""
    if not ANALYSIS_INPUT_ROOT.is_dir():
        return None, False, []
    match_id = str(job.get("match_id") or "")
    unverified = False
    refs: list[str] = []
    for path in sorted(ANALYSIS_INPUT_ROOT.glob("*.json")):
        payload = _load_json(path)
        if not payload:
            continue
        match = payload.get("match") or {}
        candidate_ids = {
            str(match.get("match_id") or ""),
            str(match.get("canonical_match_id") or ""),
        }
        if match_id and match_id not in candidate_ids:
            continue
        form = (payload.get("fundamentals") or {}).get("recent_form")
        if not _form_is_usable(form):
            continue
        captured_raw = (
            (payload.get("report") or {}).get("analysis_timestamp")
            or payload.get("prediction_created_at")
            or payload.get("fetched_at")
        )
        captured_at = _parse_timestamp(captured_raw)
        refs.append(_relative_ref(path))
        if captured_at is None or captured_at >= now or captured_at >= kickoff:
            unverified = True
            continue
        return {
            "recent_form": form,
            "source": "existing_prematch_snapshot",
            "captured_at": captured_at.isoformat(),
            "references": [_source_ref(path, captured_at)],
        }, unverified, refs
    return None, unverified, refs


def _trade_row(
    job: dict[str, Any], fixture: dict[str, Any], payload: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not payload:
        return None
    target_num = str(job.get("match_num") or "")
    target_id = str(_first(fixture, "shujuId", "shuju_id") or "")
    for row in payload.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if target_num and str(row.get("match_num") or "") == target_num:
            return row
        if target_id and str(row.get("shuju_id") or "") == target_id:
            return row
    return None


def _nowscore_source(
    job: dict[str, Any], fixture: dict[str, Any], kickoff: datetime, now: datetime
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    nowscore_id = _first(fixture, "nowscoreId", "nowscore_id")
    status = str(_first(fixture, "nowscoreMatchStatus", "nowscore_match_status") or "")
    if not nowscore_id or status in {"NO_EXACT_MATCH", "AMBIGUOUS_MATCH", "LOW_CONFIDENCE_MATCH"}:
        return None, False, []
    try:
        result = fetch_match_markets(
            str(job.get("home") or ""),
            str(job.get("away") or ""),
            job.get("kickoff"),
            explicit_id=int(nowscore_id),
            no_cache=False,
        )
    except Exception:
        return None, True, []
    if not isinstance(result, dict) or result.get("status") != "OK":
        return None, bool(result), []
    captured_at = _snapshot_capture(result)
    refs = [
        _relative_ref(PROJECT_ROOT / "data" / "source_cache" / "nowscore" / "raw" / f"{int(nowscore_id)}_3in1.html"),
        _relative_ref(PROJECT_ROOT / "data" / "source_cache" / "nowscore" / "raw" / f"{int(nowscore_id)}_analysis.js"),
    ]
    for key in ("source_url", "analysis_source_url"):
        if result.get(key):
            refs.append(str(result[key]))
    if captured_at is None or captured_at >= kickoff:
        return None, True, refs
    return {
        "name": "nowscore",
        "snapshot": result,
        "captured_at": captured_at,
        "references": refs,
    }, False, refs


def _five_hundred_source(
    business_date: str,
    job: dict[str, Any],
    fixture: dict[str, Any],
    trade_payload: dict[str, Any] | None,
    kickoff: datetime,
    now: datetime,
) -> tuple[dict[str, Any] | None, bool, list[str]]:
    trade = _trade_row(job, fixture, trade_payload)
    shuju_id = _first(fixture, "shujuId", "shuju_id") or (trade or {}).get("shuju_id")
    if not shuju_id:
        return None, False, []
    try:
        result = fetch_and_parse(int(shuju_id), business_date, DEFAULT_CACHE_DIR, False)
    except Exception:
        return None, True, []
    if not isinstance(result, dict):
        return None, True, []
    captured_at = _snapshot_capture(result)
    path = PROJECT_ROOT / "data" / "source_cache" / "shared-football" / "parsed" / f"{business_date}_{int(shuju_id)}.json"
    refs = [_relative_ref(path)]
    if captured_at is None or captured_at >= kickoff:
        return None, True, refs
    return {
        # This is the governance/model contract key.  The user-facing source
        # label remains 500.com in the metadata below.
        "name": "500_deep",
        "snapshot": result,
        "captured_at": captured_at,
        "references": refs,
    }, False, refs


def _source_form(source: dict[str, Any]) -> dict[str, Any] | None:
    return ((source.get("snapshot") or {}).get("shuju") or {}).get("recent_form")


def _strip_source_form(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(snapshot)
    shuju = value.get("shuju")
    if isinstance(shuju, dict):
        shuju.pop("recent_form", None)
    return value


def _assemble_context(
    business_date: str,
    job: dict[str, Any],
    fixture: dict[str, Any],
    universe: dict[str, Any],
    now: datetime,
    trade_payload: dict[str, Any] | None,
    *,
    real_time: bool = False,
    competition_registry_path: Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    kickoff = _parse_timestamp(_kickoff(job))
    if kickoff is None:
        return None, None, "INPUT_TIMESTAMP_UNVERIFIED"

    official, official_error = _official_market_baseline(universe, fixture, kickoff)
    source_clock = _as_now(None) if real_time else now
    existing_form, existing_unverified, existing_refs = _find_existing_form(job, kickoff, source_clock)
    source_infos: list[dict[str, Any]] = []
    source_refs: list[str] = [
        _relative_ref(UNIVERSE_ROOT / f"{business_date}.json"),
        *existing_refs,
    ]
    unverified_source = existing_unverified

    nowscore, nowscore_unverified, nowscore_refs = _nowscore_source(job, fixture, kickoff, source_clock)
    unverified_source = unverified_source or nowscore_unverified
    source_refs.extend(nowscore_refs)
    if nowscore:
        source_infos.append(nowscore)

    def has_full_market() -> bool:
        return any(_has_full_market(info["snapshot"]) for info in source_infos)

    def has_form() -> bool:
        return bool(existing_form) or any(_form_is_usable(_source_form(info)) for info in source_infos)

    if not has_full_market() or not has_form():
        five_hundred, five_hundred_unverified, five_hundred_refs = _five_hundred_source(
            business_date, job, fixture, trade_payload, kickoff, now
        )
        unverified_source = unverified_source or five_hundred_unverified
        source_refs.extend(five_hundred_refs)
        if five_hundred:
            source_infos.append(five_hundred)

    source_refs = list(dict.fromkeys(source_refs))
    source_snapshots: dict[str, dict[str, Any]] = {}
    for info in source_infos:
        source_snapshots[info["name"]] = {
            "snapshots": [info["snapshot"]],
            "source_reference": info["references"][0] if info["references"] else info["name"],
        }

    form = existing_form
    form_source = None
    form_captured_at = None
    form_refs: list[dict[str, Any]] = []
    if form:
        form_source = form["source"]
        form_captured_at = form["captured_at"]
        form_refs = list(form.get("references") or [])
        # The existing snapshot is the declared form source.  Do not allow a
        # later source snapshot to silently replace it in the deterministic
        # projection.
        for value in source_snapshots.values():
            value["snapshots"][0] = _strip_source_form(value["snapshots"][0])
    else:
        for name in ("nowscore", "500_deep"):
            info = next((item for item in source_infos if item["name"] == name), None)
            candidate = _source_form(info) if info else None
            if info and _form_is_usable(candidate):
                form = {
                    "recent_form": candidate,
                    "source": name,
                    "captured_at": info["captured_at"].isoformat(),
                    "references": [_source_ref(Path(ref)) if not ref.startswith(("http://", "https://")) else {"url": ref} for ref in info["references"]],
                }
                form_source = name
                form_captured_at = form["captured_at"]
                form_refs = list(form["references"])
                break

    if not form or not _form_is_usable(form.get("recent_form")):
        return None, None, "INPUT_TIMESTAMP_UNVERIFIED" if unverified_source else "MISSING_RECENT_FORM"

    full_source = next((info for info in source_infos if _has_full_market(info["snapshot"])), None)
    market_source = next(
        (info for info in source_infos if "1x2" in _market_families(info["snapshot"])),
        None,
    )
    market_quality = "FULL" if full_source else "LIMITED"
    market_sources: list[str]
    market_data_providers: list[str]
    market_bookmakers: list[str]
    market_families: list[str]
    market_only: dict[str, Any] | None
    if full_source:
        market_label = _market_provider(full_source["name"])
        market_sources = [market_label]
        market_data_providers = [market_label]
        market_bookmakers = _market_bookmakers(full_source["snapshot"])
        market_families = _market_families(full_source["snapshot"])
        market_only = _market_only_baseline(full_source["snapshot"], market_label, full_source["references"])
        if market_only is None:
            full_source = None
            market_quality = "LIMITED"
    if not full_source:
        market_data_providers = []
        market_bookmakers = []
        market_families = []
        market_only = None
        if market_source:
            market_label = _market_provider(market_source["name"])
            market_only = _market_only_baseline(
                market_source["snapshot"], market_label, market_source["references"]
            )
            if market_only is not None:
                market_sources = [market_label]
                market_data_providers = [market_label]
                market_bookmakers = _market_bookmakers(market_source["snapshot"])
                market_families = _market_families(market_source["snapshot"])
        if market_only is None:
            if official is None:
                return None, None, official_error or "MISSING_MARKET_INTELLIGENCE"
            market_sources = ["sporttery_spf"]
            market_data_providers = ["sporttery"]
            market_bookmakers = []
            market_families = ["1x2"]
            market_only = {
                "home": official["fair_probabilities"]["home"],
                "draw": official["fair_probabilities"]["draw"],
                "away": official["fair_probabilities"]["away"],
                "method": "sporttery_spf_devig",
                "sources": ["sporttery_spf", _relative_ref(UNIVERSE_ROOT / f"{business_date}.json")],
            }

    prediction_time = _as_now(None) if real_time else now
    context: dict[str, Any] = {
        "request": {"match_id": str(job.get("match_id") or "")},
        "selected_workspace_match": {
            "id": str(job.get("match_id") or ""),
            "home": job.get("home"),
            "away": job.get("away"),
        },
        "source_snapshots": source_snapshots,
        "official_market_baseline": official or {},
        "prematch_fundamentals": {
            "recent_form": form["recent_form"],
            "form_source": form_source,
            "captured_at": form_captured_at,
        },
        "source_timestamps": {
            **{
                name: info["captured_at"].isoformat()
                for name, info in ((item["name"], item) for item in source_infos)
                if info.get("captured_at")
            },
            "prematch_fundamentals": form_captured_at,
            "official_market_baseline": official.get("captured_at") if official else None,
        },
        "model_input_source_refs": source_refs,
        "prediction_created_at": prediction_time.isoformat(),
    }
    if not source_snapshots:
        context["source_snapshots"] = {}

    try:
        input_snapshot = build_deterministic_model_input_snapshot(
            context,
            prediction_created_at=prediction_time.isoformat(),
            repository_root=PROJECT_ROOT,
        )
    except (TypeError, ValueError):
        return None, None, "INPUT_TIMESTAMP_UNVERIFIED"

    source_cutoff = _parse_timestamp(input_snapshot.get("source_cutoff_at"))
    market_snapshot = _parse_timestamp(input_snapshot.get("market_snapshot_at"))
    if (
        source_cutoff is None
        or market_snapshot is None
        or source_cutoff >= prediction_time
        or market_snapshot >= prediction_time
        or source_cutoff >= kickoff
        or market_snapshot >= kickoff
    ):
        return None, None, "INPUT_TIMESTAMP_UNVERIFIED"

    metadata = {
        "input_snapshot": input_snapshot,
        "market_intelligence_quality": market_quality,
        "market_sources": market_sources,
        "market_data_providers": market_data_providers,
        "market_bookmakers": market_bookmakers,
        "market_families": market_families,
        "market_source_references": source_refs,
        "market_only_baseline": market_only,
        "form_source": form_source,
        "form_captured_at": form_captured_at,
        "prediction_created_at": prediction_time.isoformat(),
        "source_references": [
            _source_ref(UNIVERSE_ROOT / f"{business_date}.json", universe.get("fetched_at")),
            *form_refs,
        ],
        "data_quality": {
            "status": "PREMATCH_INPUTS_VERIFIED",
            "market_intelligence_quality": market_quality,
            "recent_form": "READY",
            "missing": [],
        },
    }
    target_identity = resolve_target_team_identity(
        job=job,
        fixture=fixture,
        context=context,
        input_snapshot=input_snapshot,
        repository_root=PROJECT_ROOT,
        competition_registry_path=competition_registry_path,
    )
    metadata["canonical_team_identity"] = target_identity.get("canonical_team_identity")
    metadata["target_team_identity_evidence"] = target_identity.get("evidence")
    return context, metadata, None


def _build_payload(
    business_date: str,
    job: dict[str, Any],
    result: dict[str, Any],
    input_snapshot: dict[str, Any],
    now: datetime,
    freeze_created_at: datetime,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    config = load_config()
    model = result.get("model") if isinstance(result, dict) else None
    if not isinstance(model, dict):
        raise ValueError("MODEL_RETURNED_NO_PREDICTION")
    decisions = result.get("decisions") or {}
    payload = {
        "report": {
            "report_type": "base_prediction_minimal",
            "model_version": config["champion"]["release_version"],
            "analysis_timestamp": now.isoformat(),
            "snapshot_timestamp": input_snapshot.get("source_cutoff_at"),
            "freeze_created_at": freeze_created_at.isoformat(),
        },
        "match": {
            "canonical_match_id": canonical_match_id({
                "home": job.get("home"),
                "away": job.get("away"),
                "kickoff_local": job.get("kickoff"),
            }),
            "match_id": str(job.get("match_id") or ""),
            "home": job.get("home"),
            "away": job.get("away"),
            "kickoff_local": job.get("kickoff"),
        },
        "data_quality": {
            "missing": [],
            "market_intelligence_quality": metadata["market_intelligence_quality"],
        },
        "model": model,
        "decisions": decisions,
        "fundamentals": {
            "lineup_status": "unavailable_by_time",
        },
        "betting": {"candidates": []},
        "automation": {
            "provider": "fixed-python-core",
            "prompt_version": config["versions"]["prompt_version"],
            "model_input_snapshot": input_snapshot,
        },
        "business_date": business_date,
    }
    if metadata.get("canonical_team_identity") is not None:
        payload["canonical_team_identity"] = copy.deepcopy(metadata["canonical_team_identity"])
    if metadata.get("target_team_identity_evidence") is not None:
        payload["target_team_identity_evidence"] = copy.deepcopy(metadata["target_team_identity_evidence"])
    return payload


def _decorate_record(
    record: dict[str, Any],
    business_date: str,
    job: dict[str, Any],
    result: dict[str, Any],
    metadata: dict[str, Any],
    now: datetime,
    kickoff: datetime,
) -> dict[str, Any]:
    model = result["model"]
    decisions = result.get("decisions") or {}
    trace = decisions.get("score_selection_trace") or {}
    record.update({
        "product_role": "FUSION_BASELINE_V0",
        "business_date": business_date,
        "job_id": job.get("job_id"),
        "match_id": job.get("match_id"),
        "freeze_created_at": now.isoformat(),
        "minutes_to_kickoff_at_freeze": round((kickoff - now).total_seconds() / 60.0, 3),
        "input_snapshot_ref": record.get("model_input_snapshot_ref"),
        "market_intelligence_quality": metadata["market_intelligence_quality"],
        "market_sources": metadata["market_sources"],
        "market_data_providers": metadata["market_data_providers"],
        "market_bookmakers": metadata["market_bookmakers"],
        "market_families": metadata["market_families"],
        "market_source_references": metadata["market_source_references"],
        "market_only_baseline": metadata["market_only_baseline"],
        "data_quality": {
            **metadata["data_quality"],
            "data_grade": record.get("data_grade"),
            "generic_data_grade": record.get("generic_data_grade"),
            "base_input_quality": record.get("base_input_quality"),
        },
        "source_references": metadata["source_references"],
        "fusion_1X2": model.get("probabilities"),
        "totals": model.get("total_goals_buckets"),
        "btts": model.get("btts"),
        "score_distribution": model.get("score_probabilities"),
        "unique_score": decisions.get("unique_score"),
        "top_scores": list(model.get("score_probabilities") or [])[:10],
        "uncertainty": {
            "confidence_label": trace.get("confidence"),
            "main_risk": trace.get("main_risk"),
            "status": "QUALITATIVE_ONLY",
            "reason": "No calibrated numeric predictive uncertainty is available in the current Champion contract.",
        },
    })
    record["prediction_sha256"] = prediction_content_hash(record)
    return record


def _refresh_counts(ledger: dict[str, Any]) -> None:
    jobs = [job for job in ledger.get("jobs", []) if isinstance(job, dict)]
    counts = Counter(str(job.get("status") or "") for job in jobs)
    ledger["job_count"] = len(jobs)
    ledger["pending_count"] = counts["PENDING"]
    ledger["frozen_count"] = counts["FROZEN"]
    ledger["predicted_count"] = counts["PREDICTED"]
    ledger["insufficient_data_count"] = counts["INSUFFICIENT_DATA"]
    ledger["prediction_failed_count"] = counts["PREDICTION_FAILED"]
    ledger["missed_prematch_count"] = counts["MISSED_PREMATCH_WINDOW"]
    reasons = Counter(
        str(job.get("last_error"))
        for job in jobs
        if job.get("status") in {"INSUFFICIENT_DATA", "PREDICTION_FAILED"} and job.get("last_error")
    )
    ledger["failure_reasons"] = dict(reasons)


def _blocked_summary(business_date: str, ledger: dict[str, Any] | None) -> dict[str, Any]:
    blocked = {
        "schema_version": "1.0",
        "business_date": business_date,
        "status": "BLOCKED_UNIVERSE",
        "fixture_count": 0,
        "job_count": 0,
        "jobs": [],
    }
    return {
        "business_date": business_date,
        "universe": 0,
        "jobs": int((ledger or {}).get("job_count") or 0),
        "attempted": 0,
        "frozen": 0,
        "predicted": 0,
        "insufficient_data": 0,
        "prediction_failed": 0,
        "missed_prematch": 0,
        "failure_reasons": {"BLOCKED_UNIVERSE": 1},
        "ledger": blocked,
    }


def run_base_prediction_jobs(
    business_date: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    now: datetime | None = None,
    record_root: Path = DEFAULT_RECORD_ROOT,
    input_snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    job_id: str | None = None,
    competition_registry_path: Path | None = None,
) -> dict[str, Any]:
    """Attempt all retryable pre-kickoff BASE jobs for one business date."""
    current_time = _as_now(now)
    real_time = now is None
    ledger_path = Path(jobs_root) / f"{business_date}.json"
    ledger = _load_json(ledger_path)
    universe = load_prediction_universe(business_date, Path(universe_root))
    if not universe or universe.get("business_date") != business_date or universe.get("status") not in UNIVERSE_STATUSES:
        return _blocked_summary(business_date, ledger)
    if not ledger or ledger.get("status") not in UNIVERSE_STATUSES:
        return _blocked_summary(business_date, ledger)

    jobs = [job for job in ledger.get("jobs", []) if isinstance(job, dict)]
    attempted = 0
    trade_payload: dict[str, Any] | None = None
    trade_loaded = False
    for job in jobs:
        if job_id and job.get("job_id") != job_id:
            continue
        status = str(job.get("status") or "PENDING")
        if status in TERMINAL_STATUSES:
            continue
        kickoff = _parse_timestamp(_kickoff(job))
        if kickoff is None:
            if status in RETRYABLE_STATUSES:
                attempted += 1
                job["status"] = "INSUFFICIENT_DATA"
                job["last_error"] = "INPUT_TIMESTAMP_UNVERIFIED"
                job["updated_at"] = current_time.isoformat()
            continue
        if current_time >= kickoff:
            if status in RETRYABLE_STATUSES:
                job["status"] = "MISSED_PREMATCH_WINDOW"
                job["last_error"] = "MISSED_PREMATCH_WINDOW"
                job["updated_at"] = current_time.isoformat()
            continue
        if status not in RETRYABLE_STATUSES:
            continue
        attempted += 1
        fixture = _job_fixture(universe, job)
        if fixture is None:
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = "MISSING_UNIVERSE_FIXTURE"
            job["updated_at"] = current_time.isoformat()
            continue
        if not trade_loaded:
            trade_loaded = True
            try:
                trade_payload = fetch_trade_matches(business_date, no_cache=False)
            except Exception:
                trade_payload = None
        context, metadata, assembly_error = _assemble_context(
            business_date,
            job,
            fixture,
            universe,
            current_time,
            trade_payload,
            real_time=real_time,
            competition_registry_path=competition_registry_path,
        )
        if assembly_error:
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = assembly_error
            job["updated_at"] = current_time.isoformat()
            continue
        assert context is not None and metadata is not None
        input_snapshot = metadata["input_snapshot"]
        prediction_time = _parse_timestamp(metadata.get("prediction_created_at")) or current_time
        if prediction_time >= kickoff:
            job["status"] = "MISSED_PREMATCH_WINDOW"
            job["last_error"] = "MISSED_PREMATCH_WINDOW"
            job["updated_at"] = current_time.isoformat()
            continue
        try:
            # The projection is the exact deterministic input that is frozen;
            # no report or deep-language layer participates in the model call.
            result = build_automatic_model(input_snapshot["projection"])
        except Exception as error:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = f"MODEL_EXCEPTION_{type(error).__name__}"
            job["updated_at"] = current_time.isoformat()
            continue
        if not isinstance(result, dict) or not isinstance(result.get("model"), dict):
            job["status"] = "INSUFFICIENT_DATA"
            job["last_error"] = "MODEL_RETURNED_NO_PREDICTION"
            job["updated_at"] = current_time.isoformat()
            continue
        model = result["model"]
        if model.get("method") != MODEL_FAMILY:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "MODEL_IDENTITY_MISMATCH"
            job["updated_at"] = current_time.isoformat()
            continue
        try:
            freeze_time = _as_now(None) if real_time else current_time
            kickoff_at = _parse_timestamp(_kickoff(job))
            assert kickoff_at is not None
            if freeze_time >= kickoff_at:
                job["status"] = "MISSED_PREMATCH_WINDOW"
                job["last_error"] = "MISSED_PREMATCH_WINDOW"
                job["updated_at"] = freeze_time.isoformat()
                continue
            payload = _build_payload(
                business_date,
                job,
                result,
                input_snapshot,
                prediction_time,
                freeze_time,
                metadata,
            )
            record = build_prediction_record(
                payload,
                input_payload=input_snapshot,
                repository_root=PROJECT_ROOT,
            )
            if record.get("model_role") != "champion" or not record.get("formal_eligible"):
                raise GovernanceContractBlocker(
                    "governance rejected BASE payload as non-formal: "
                    + ",".join(record.get("missing_critical_fields") or [])
                )
            record = _decorate_record(record, business_date, job, result, metadata, freeze_time, kickoff_at)
            frozen = freeze_prediction(
                record,
                Path(record_root),
                input_snapshot_root=Path(input_snapshot_root),
            )
        except PredictionConflictError:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "PREDICTION_CONFLICT"
            job["updated_at"] = current_time.isoformat()
            continue
        except GovernanceContractBlocker:
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "GOVERNANCE_CONTRACT_BLOCKER"
            job["updated_at"] = current_time.isoformat()
            continue
        except (TypeError, ValueError, OSError):
            job["status"] = "PREDICTION_FAILED"
            job["last_error"] = "GOVERNANCE_CONTRACT_BLOCKER"
            job["updated_at"] = current_time.isoformat()
            continue
        stored = frozen.get("record") or record
        job["status"] = "FROZEN"
        job["prediction_id"] = stored.get("prediction_id")
        job["prediction_created_at"] = stored.get("prediction_created_at")
        job["freeze_created_at"] = stored.get("freeze_created_at")
        job["last_error"] = None
        job["updated_at"] = current_time.isoformat()

    ledger["last_run_at"] = current_time.isoformat()
    _refresh_counts(ledger)
    _write_json(ledger_path, ledger)
    return {
        "business_date": business_date,
        "universe": int(universe.get("fixture_count") or len(universe.get("fixtures") or [])),
        "jobs": len(jobs),
        "attempted": attempted,
        "frozen": ledger.get("frozen_count", 0),
        "predicted": ledger.get("predicted_count", 0),
        "insufficient_data": ledger.get("insufficient_data_count", 0),
        "prediction_failed": ledger.get("prediction_failed_count", 0),
        "missed_prematch": ledger.get("missed_prematch_count", 0),
        "pending": ledger.get("pending_count", 0),
        "failure_reasons": ledger.get("failure_reasons", {}),
        "ledger": ledger,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze minimum formal BASE predictions for one Prediction Day")
    parser.add_argument("--date", required=True, help="Business date YYYY-MM-DD")
    parser.add_argument("--job-id", help="Optional single-job debug selector")
    args = parser.parse_args()
    summary = run_base_prediction_jobs(args.date, job_id=args.job_id)
    print(json.dumps({key: value for key, value in summary.items() if key != "ledger"}, ensure_ascii=False, indent=2))
    return 1 if summary.get("failure_reasons", {}).get("BLOCKED_UNIVERSE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
