"""Freeze one explicit research Challenger beside future Champion records.

The producer adapts the already validated Phase 2C-2 opponent-strength model to
the frozen governance record.  It never chooses a new spec, resolves team names,
or changes Champion output.  A target is eligible only when the Champion record
already carries reviewed canonical competition/team IDs and the historical
rows were both played and recorded no later than the Champion source cutoff.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from football_data.data_home import resolve_football_data_home
from football_data.phase2c2_opponent_strength import OpponentSpec, build_opponent_adjusted_prediction
from football_data.storage import HistoricalResultStore, content_sha256
from model_governance import (
    DEFAULT_CONFIG,
    DEFAULT_INPUT_SNAPSHOT_ROOT,
    build_prediction_record,
    canonical_json,
    freeze_prediction,
    load_config,
    load_input_snapshot,
    model_source_fingerprint,
    prediction_content_hash,
    resolve_commit_sha,
)
from prospective_settlement import FROZEN_STATUSES, is_formally_eligible


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAMPION_ROOT = ROOT / "data" / "model_governance" / "predictions"
DEFAULT_CHALLENGER_ROOT = ROOT / "data" / "model_governance" / "challenger_predictions"
CHALLENGER_ID = "phase2c2_opponent_strength_prior20"
MODEL_CORE_VERSION = "opponent_adjusted_strength_poisson_v1"
PRODUCER_CONTRACT_VERSION = "prospective_challenger_freeze.v1"
SELECTED_SPEC_ID = "opponent:fixed-point:prior20"
SHANGHAI = timezone(timedelta(hours=8))


class ChallengerCaptureError(ValueError):
    """A future Champion cannot receive a legal Challenger freeze."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _time(value: Any, code: str | None = None) -> datetime | None:
    if value in (None, ""):
        parsed = None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        if code:
            raise ChallengerCaptureError(code)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(SHANGHAI).isoformat()


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChallengerCaptureError(f"ARTIFACT_UNREADABLE:{path.name}") from error
    if not isinstance(value, dict):
        raise ChallengerCaptureError(f"ARTIFACT_NOT_OBJECT:{path.name}")
    return value


def _registered(config: dict[str, Any]) -> dict[str, Any]:
    rows = [
        row for row in config.get("challengers") or []
        if isinstance(row, dict) and str(row.get("id") or row.get("challenger_id") or "") == CHALLENGER_ID
    ]
    if len(rows) != 1:
        raise ChallengerCaptureError("CHALLENGER_NOT_REGISTERED_EXACTLY_ONCE")
    row = rows[0]
    if (
        row.get("research_only") is not True
        or row.get("status") != "shadow_only"
        or row.get("formal_benchmark_eligible") is not False
        or row.get("entrypoint") != "scripts/prospective_challenger_runner.py"
        or row.get("candidate_spec_id") != SELECTED_SPEC_ID
    ):
        raise ChallengerCaptureError("CHALLENGER_GOVERNANCE_BOUNDARY_INVALID")
    if row.get("model_core_version") != MODEL_CORE_VERSION:
        raise ChallengerCaptureError("CHALLENGER_MODEL_IDENTITY_INVALID")
    return row


def load_frozen_challenger_spec(
    data_home: str | Path | None = None,
) -> tuple[OpponentSpec, dict[str, Any]]:
    """Load the existing Phase 2C-2 selection without re-running selection."""

    root = Path(data_home).expanduser() if data_home is not None else resolve_football_data_home()
    artifact_root = root / "research" / "phase2c2"
    registry = _json(artifact_root / "candidate_specs.json")
    manifest = _json(artifact_root / "experiment_manifest.json")
    validation = _json(artifact_root / "validation_evaluation.json")
    selected = manifest.get("selected_spec")
    selected_id = str((selected or {}).get("spec_id") or "")
    if selected_id != SELECTED_SPEC_ID or validation.get("selected_spec_id") != SELECTED_SPEC_ID:
        raise ChallengerCaptureError("PHASE2C2_SELECTED_SPEC_MISMATCH")
    if registry.get("registry_digest") != content_sha256(registry.get("candidate_specs") or []):
        raise ChallengerCaptureError("PHASE2C2_REGISTRY_DIGEST_MISMATCH")
    if manifest.get("candidate_registry_digest") != registry.get("registry_digest"):
        raise ChallengerCaptureError("PHASE2C2_MANIFEST_REGISTRY_MISMATCH")
    registered = next(
        (row for row in registry.get("candidate_specs") or [] if row.get("spec_id") == SELECTED_SPEC_ID),
        None,
    )
    if not isinstance(registered, dict) or registered != selected:
        raise ChallengerCaptureError("PHASE2C2_SELECTED_SPEC_NOT_REGISTERED")
    fields = {key: selected[key] for key in (
        "regularization", "formula", "history_policy", "home_away_formulation",
        "solver", "convergence_tolerance", "max_iterations", "minimum_history",
    )}
    spec = OpponentSpec(**fields)
    if spec.to_dict() != selected:
        raise ChallengerCaptureError("PHASE2C2_SELECTED_SPEC_FIELDS_MISMATCH")
    provenance = {
        "contract_version": PRODUCER_CONTRACT_VERSION,
        "selected_spec_id": spec.spec_id,
        "selected_spec": spec.to_dict(),
        "candidate_registry_digest": registry["registry_digest"],
        "fresh_heldout_available": validation.get("fresh_heldout_available"),
        "historical_validation_reused": validation.get("historical_validation_reused"),
        "selection_source": "phase2c2/experiment_manifest.json",
    }
    return spec, provenance


def _information_time(row: dict[str, Any]) -> datetime | None:
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    values = [
        row.get("source_as_of_at"),
        row.get("captured_at"),
        provenance.get("source_as_of_at"),
        provenance.get("captured_at"),
    ]
    parsed = [_time(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return max(parsed) if parsed else None


def filter_history_at_cutoff(
    records: Iterable[dict[str, Any]],
    *,
    source_cutoff_at: str,
    target_kickoff_at: str,
) -> list[dict[str, Any]]:
    """Keep only rows both played and knowable by the Champion cutoff."""

    cutoff = _time(source_cutoff_at, "SOURCE_CUTOFF_INVALID")
    kickoff = _time(target_kickoff_at, "TARGET_KICKOFF_INVALID")
    filtered: list[dict[str, Any]] = []
    for value in records:
        if not isinstance(value, dict):
            continue
        row_kickoff = _time(value.get("kickoff_at"))
        info_at = _information_time(value)
        if row_kickoff is None or info_at is None:
            continue
        if row_kickoff >= cutoff or row_kickoff >= kickoff or info_at > cutoff:
            continue
        filtered.append(dict(value))
    return sorted(
        filtered,
        key=lambda row: (_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("canonical_match_id") or "")),
    )


def _target(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("canonical_team_identity")
    identity = identity if isinstance(identity, dict) else {}
    values = {
        key: identity.get(key) or record.get(key)
        for key in ("competition_id", "season_id", "home_team_id", "away_team_id")
    }
    if any(not str(values.get(key) or "").strip() for key in ("competition_id", "home_team_id", "away_team_id")):
        raise ChallengerCaptureError("CANONICAL_RESEARCH_IDENTITY_MISSING")
    return {
        "canonical_match_id": str(record.get("match_key") or (record.get("match_identity") or {}).get("match_key") or ""),
        "kickoff_at": record.get("kickoff_at") or (record.get("match_identity") or {}).get("kickoff_at"),
        **{key: str(value) if value not in (None, "") else value for key, value in values.items()},
    }


def _score_rows(probabilities: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "score": f"{item.get('home_goals')}-{item.get('away_goals')}",
            "probability": float(item.get("probability") or 0.0),
            "rank": rank,
        }
        for rank, item in enumerate(probabilities.get("top_scores") or [], 1)
        if isinstance(item, dict)
    ]


def _total_rows(probabilities: dict[str, Any]) -> list[dict[str, Any]]:
    totals: Counter[int] = Counter()
    matrix = probabilities.get("score_matrix") or {}
    for home, row in matrix.items():
        for away, probability in (row or {}).items():
            totals[int(home) + int(away)] += float(probability)
    return [
        *({"goals": str(goal), "probability": totals[goal]} for goal in sorted(totals)),
        {"goals": "9+", "probability": max(0.0, 1.0 - sum(totals.values()))},
    ]


def _candidate_model(output: dict[str, Any]) -> dict[str, Any]:
    probabilities = output["probabilities"]
    top_scores = _score_rows(probabilities)
    if len(top_scores) < 5:
        raise ChallengerCaptureError("CHALLENGER_SCORE_OUTPUT_INCOMPLETE")
    return {
        "method": MODEL_CORE_VERSION,
        "probabilities": probabilities["1x2"],
        "lambda_home": output["lambda_home"],
        "lambda_away": output["lambda_away"],
        "rho": 0.0,
        "btts": probabilities["btts"],
        "total_goals_buckets": _total_rows(probabilities),
        "score_probabilities": top_scores,
        "expected_goals": float(output["lambda_home"]) + float(output["lambda_away"]),
    }


def _candidate_source_fingerprint(repository_root: Path) -> str:
    result = model_source_fingerprint(
        repository_root,
        components=(
            ("scripts/prospective_challenger_runner.py", None),
            ("scripts/football_data/phase2c2_opponent_strength.py", None),
            ("scripts/football_data/phase2c1_model.py", "probability_payload"),
        ),
    )
    return str(result["fingerprint"])


def build_challenger_record(
    champion: dict[str, Any],
    *,
    history_records: Iterable[dict[str, Any]],
    input_snapshot_document: dict[str, Any],
    now: datetime,
    config: dict[str, Any] | None = None,
    spec: OpponentSpec | None = None,
    spec_provenance: dict[str, Any] | None = None,
    historical_dataset_digest: str | None = None,
    historical_dataset_path: str | None = None,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    current = _as_shanghai(now)
    if champion.get("model_role") != "champion" or not is_formally_eligible(champion):
        raise ChallengerCaptureError("CHAMPION_NOT_FORMAL")
    if champion.get("prediction_status") not in FROZEN_STATUSES:
        raise ChallengerCaptureError("CHAMPION_NOT_FROZEN")
    kickoff = _time(champion.get("kickoff_at"), "CHAMPION_KICKOFF_INVALID")
    cutoff = _time(champion.get("source_cutoff_at"), "CHAMPION_SOURCE_CUTOFF_INVALID")
    freeze = _time(champion.get("freeze_created_at"), "CHAMPION_FREEZE_INVALID")
    if not cutoff < freeze <= current < kickoff:
        raise ChallengerCaptureError("CHALLENGER_CAPTURE_TEMPORAL_ORDER_INVALID")
    target = _target(champion)
    target_kickoff = _time(target["kickoff_at"], "TARGET_KICKOFF_INVALID")
    if target_kickoff != kickoff:
        raise ChallengerCaptureError("CHAMPION_KICKOFF_IDENTITY_MISMATCH")
    bounded_history = filter_history_at_cutoff(
        history_records,
        source_cutoff_at=champion["source_cutoff_at"],
        target_kickoff_at=champion["kickoff_at"],
    )
    spec = spec or load_frozen_challenger_spec()[0]
    output = build_opponent_adjusted_prediction(target, bounded_history, spec)
    snapshot = deepcopy(input_snapshot_document)
    projection = snapshot.pop("input", None)
    if not isinstance(projection, dict):
        raise ChallengerCaptureError("CHAMPION_INPUT_SNAPSHOT_PROJECTION_MISSING")
    snapshot["prediction_created_at"] = _iso(current)
    snapshot["projection"] = projection
    config = config or load_config()
    registration = _registered(config)
    provenance = {
        **(spec_provenance or {"selected_spec_id": spec.spec_id, "selected_spec": spec.to_dict()}),
        "producer": "scripts/prospective_challenger_runner.py",
        "challenger_id": CHALLENGER_ID,
        "champion_prediction_id": champion.get("prediction_id"),
        "research_only": True,
        "formal_benchmark_eligible": False,
        "history_as_of_at": champion["source_cutoff_at"],
        "history_record_count": len(bounded_history),
        "used_match_ids": output["features"]["used_match_ids"],
        "historical_dataset_digest": historical_dataset_digest,
        "historical_dataset_path": historical_dataset_path,
        "historical_dataset_store": "HistoricalResultStore.read_only",
        "information_time_rule": "max(source_as_of_at,captured_at,provenance timestamps) <= Champion source_cutoff_at",
        "market_used": False,
        "xg_used": False,
        "affects_champion": False,
        "affects_production_decisions": False,
    }
    identity = champion.get("match_identity") or {}
    candidate_model = _candidate_model(output)
    payload = {
        "report": {
            "report_type": "prospective_challenger_freeze",
            "model_version": registration.get("release_version") or "research-v1",
            "analysis_timestamp": _iso(current),
            "prediction_created_at": _iso(current),
            "snapshot_timestamp": champion["source_cutoff_at"],
            "freeze_created_at": _iso(current),
        },
        "match": {
            "canonical_match_id": champion.get("match_key") or identity.get("match_key"),
            "match_id": champion.get("match_id") or identity.get("match_id"),
            "home": identity.get("home"),
            "away": identity.get("away"),
            "kickoff_local": champion.get("kickoff_at") or identity.get("kickoff_at"),
        },
        "data_quality": {"missing": [], "market_intelligence_quality": "LIMITED"},
        "model": candidate_model,
        "decisions": {
            "unique_score": (candidate_model["score_probabilities"] or [{}])[0].get("score"),
            "unique_primary_dimension": "research_shadow_only",
        },
        "automation": {
            "provider": "phase2c2-research",
            "prompt_version": config["versions"]["prompt_version"],
            "model_input_snapshot": snapshot,
        },
        "business_date": champion.get("business_date"),
    }
    if isinstance(champion.get("canonical_team_identity"), dict):
        payload["canonical_team_identity"] = deepcopy(champion["canonical_team_identity"])
    if isinstance(champion.get("target_team_identity_evidence"), dict):
        payload["target_team_identity_evidence"] = deepcopy(champion["target_team_identity_evidence"])
    record = build_prediction_record(
        payload,
        config=config,
        input_payload=snapshot,
        commit_sha=resolve_commit_sha(repository_root),
        repository_root=repository_root,
    )
    record.update({
        "challenger_id": CHALLENGER_ID,
        "prediction_status": "frozen",
        "formal_eligible": False,
        "model_formal_eligible": False,
        "product_role": "RESEARCH_CHALLENGER_SHADOW",
        "business_date": champion.get("business_date"),
        "match_id": champion.get("match_id") or identity.get("match_id"),
        "freeze_created_at": _iso(current),
        "challenger_provenance": provenance,
    })
    source_fingerprint = _candidate_source_fingerprint(repository_root)
    record["model_source_fingerprint"] = source_fingerprint
    record["model_run_identity"]["model_source_fingerprint"] = source_fingerprint
    record["model_run_fingerprint"] = hashlib.sha256(
        canonical_json(record["model_run_identity"]).encode("utf-8")
    ).hexdigest()
    record["prediction_sha256"] = prediction_content_hash(record)
    return record


def _records(root: Path, business_date: str) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    output = []
    for path in sorted(root.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict) and str(row.get("business_date") or "") == business_date:
            output.append(row)
    return output


def _existing_for(rows: Iterable[dict[str, Any]], champion: dict[str, Any], source_fingerprint: str) -> str:
    matches = [
        row for row in rows
        if row.get("model_role") == "challenger"
        and row.get("challenger_id") == CHALLENGER_ID
        and row.get("match_key") == champion.get("match_key")
        and row.get("source_cutoff_at") == champion.get("source_cutoff_at")
    ]
    if not matches:
        return ""
    if len(matches) > 1:
        raise ChallengerCaptureError("MULTIPLE_EXISTING_CHALLENGER_FREEZES")
    existing = matches[0]
    if existing.get("model_source_fingerprint") != source_fingerprint:
        raise ChallengerCaptureError("EXISTING_CHALLENGER_FINGERPRINT_CONFLICT")
    if (
        existing.get("model_core_version") != MODEL_CORE_VERSION
        or existing.get("model_family") != MODEL_CORE_VERSION
        or existing.get("prediction_status") not in FROZEN_STATUSES
        or existing.get("formal_eligible") is not False
        or existing.get("model_formal_eligible") is not False
    ):
        raise ChallengerCaptureError("EXISTING_CHALLENGER_CONTRACT_CONFLICT")
    if existing.get("prediction_sha256") != prediction_content_hash(existing):
        raise ChallengerCaptureError("EXISTING_CHALLENGER_HASH_CONFLICT")
    if (existing.get("challenger_provenance") or {}).get("champion_prediction_id") != champion.get("prediction_id"):
        raise ChallengerCaptureError("EXISTING_CHALLENGER_CHAMPION_MISMATCH")
    return str(existing.get("prediction_id") or "existing")


def freeze_future_challengers(
    business_date: str,
    *,
    now: datetime | None = None,
    champion_root: Path = DEFAULT_CHAMPION_ROOT,
    challenger_root: Path = DEFAULT_CHALLENGER_ROOT,
    input_snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    data_home: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    current = _as_shanghai(now or datetime.now(SHANGHAI))
    config = load_config()
    registration = _registered(config)
    spec, spec_provenance = load_frozen_challenger_spec(data_home)
    champions = _records(Path(champion_root), business_date)
    future = []
    for row in champions:
        kickoff = _time(row.get("kickoff_at"))
        if kickoff is not None and kickoff > current and is_formally_eligible(row):
            future.append(row)
    reasons: Counter[str] = Counter()
    frozen_this_run = 0
    would_freeze = 0
    existing_count = 0
    source_fingerprint = _candidate_source_fingerprint(ROOT)
    existing_rows = _records(Path(challenger_root), business_date)
    store: HistoricalResultStore | None = None
    dataset_digest: str | None = None
    for champion in future:
        try:
            if _existing_for(existing_rows, champion, source_fingerprint):
                existing_count += 1
                continue
            target = _target(champion)
            if store is None:
                home = Path(data_home).expanduser() if data_home is not None else resolve_football_data_home()
                store = HistoricalResultStore(home / "historical_results.duckdb")
                dataset_digest = store.dataset_digest()
            history = list(store.iter_records(competition_id=target["competition_id"], eligible_only=True))
            document = load_input_snapshot(champion, input_snapshot_root)
            record = build_challenger_record(
                champion,
                history_records=history,
                input_snapshot_document=document,
                now=current,
                config=config,
                spec=spec,
                spec_provenance=spec_provenance,
                historical_dataset_digest=dataset_digest,
                historical_dataset_path=str(store.path),
            )
            if dry_run:
                would_freeze += 1
                existing_rows.append(record)
            else:
                result = freeze_prediction(
                    record,
                    Path(challenger_root),
                    input_snapshot_root=Path(input_snapshot_root),
                )
                if result["status"] == "created":
                    existing_rows.append(record)
                frozen_this_run += int(result["status"] == "created")
        except ChallengerCaptureError as error:
            reasons[error.code] += 1
        except (OSError, ValueError, KeyError) as error:
            reasons[f"{type(error).__name__.upper()}:{str(error)[:120]}"] += 1
    return {
        "status": "READY_FOR_FORWARD_CAPTURE" if not reasons or frozen_this_run or would_freeze else "NO_LEGAL_CANDIDATE",
        "challenger_producer": "AVAILABLE",
        "challenger_id": registration.get("id") or CHALLENGER_ID,
        "model_core_version": MODEL_CORE_VERSION,
        "selected_spec_id": spec.spec_id,
        "business_date": business_date,
        "dry_run": dry_run,
        "future_formal_champion_count": len(future),
        "challenger_frozen_this_run": frozen_this_run,
        "challenger_would_freeze": would_freeze,
        "challenger_existing_count": existing_count,
        "rejections": dict(sorted(reasons.items())),
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="business date YYYY-MM-DD")
    parser.add_argument("--now", help="deterministic current time")
    parser.add_argument("--champion-root", type=Path, default=DEFAULT_CHAMPION_ROOT)
    parser.add_argument("--challenger-root", type=Path, default=DEFAULT_CHALLENGER_ROOT)
    parser.add_argument("--input-snapshot-root", type=Path, default=DEFAULT_INPUT_SNAPSHOT_ROOT)
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    current = _time(args.now) if args.now else datetime.now(SHANGHAI)
    if current is None:
        raise SystemExit("--now must be an ISO timestamp")
    print(json.dumps(
        freeze_future_challengers(
            args.date,
            now=current,
            champion_root=args.champion_root,
            challenger_root=args.challenger_root,
            input_snapshot_root=args.input_snapshot_root,
            data_home=args.data_home,
            dry_run=args.dry_run,
        ),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
