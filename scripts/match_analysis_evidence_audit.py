"""Offline natural-cohort audit for the match-analysis evidence projection."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from match_analysis_evidence_projection import project_match_analysis_evidence
except ImportError:  # package imports used by tests
    from scripts.match_analysis_evidence_projection import project_match_analysis_evidence


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
PREDICTION_ROOT = ROOT / "data" / "model_governance" / "predictions"
INPUT_SNAPSHOT_ROOT = ROOT / "data" / "model_governance" / "input_snapshots"
EVIDENCE_ROOT = ROOT / "data" / "prospective" / "football_evidence"
LOCAL_TZ = timezone(timedelta(hours=8))
READY_SOURCES = {"nowscore_public_jc", "nowscore_public_jc_sales"}


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _id_key(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(text))
    except ValueError:
        return text


def _parse_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _resolve_path(value: Any, *, fallback_root: Path) -> Path | None:
    text = _text(value)
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return path
    candidate = fallback_root / path.name
    return candidate if candidate.is_file() else None


def _fixture_kickoff(fixture: Mapping[str, Any]) -> datetime | None:
    direct = _text(fixture.get("kickoff") or fixture.get("kickoff_at"))
    if direct:
        return _parse_datetime(direct)
    match_date = _text(fixture.get("matchDate") or fixture.get("match_date"))
    match_time = _text(fixture.get("matchTime") or fixture.get("match_time"))
    return _parse_datetime(f"{match_date}T{match_time}:00+08:00") if match_date and match_time else None


def _fixture_id(fixture: Mapping[str, Any]) -> str | None:
    return _id_key(
        fixture.get("nowscore_id")
        or fixture.get("nowscoreId")
        or fixture.get("match_id")
        or fixture.get("matchId")
    )


def _prediction_timestamp(record: Mapping[str, Any]) -> datetime:
    for key in ("freeze_created_at", "created_at", "prediction_created_at"):
        parsed = _parse_datetime(record.get(key))
        if parsed:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def discover_natural_cohort(
    *,
    cohort_path: str | Path | None = None,
    as_of: str | datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Select the latest READY cohort at or before the execution date."""

    if cohort_path is not None:
        path = Path(cohort_path)
        if not path.is_absolute():
            path = ROOT / path
        payload = _load_json(path)
        if payload.get("status") != "READY":
            raise ValueError(f"cohort is not READY: {path}")
        if payload.get("source") not in READY_SOURCES:
            raise ValueError(f"cohort source is not accepted: {path}")
        return payload, path

    cutoff = _parse_datetime(as_of) if as_of is not None else datetime.now(LOCAL_TZ)
    if cutoff is None:
        raise ValueError(f"invalid as-of timestamp: {as_of}")
    candidates: list[tuple[date, Path, dict[str, Any]]] = []
    for path in sorted(UNIVERSE_ROOT.glob("*.json")):
        business_date = _parse_date(path.stem)
        if business_date is None or business_date > cutoff.date():
            continue
        try:
            payload = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if payload.get("status") == "READY" and payload.get("source") in READY_SOURCES:
            candidates.append((business_date, path, payload))
    if not candidates:
        raise FileNotFoundError("no READY natural cohort at or before as-of")
    _, path, payload = max(candidates, key=lambda item: (item[0], str(item[1])))
    return payload, path


def _candidate_predictions(
    fixture_id: str, prediction_root: Path
) -> list[tuple[Path, dict[str, Any]]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(Path(prediction_root).glob("*.json")):
        try:
            record = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if _id_key(record.get("match_id")) != fixture_id:
            continue
        if record.get("prediction_status") != "formal" or record.get("formal_eligible") is not True:
            continue
        if not _text(record.get("prediction_id")):
            continue
        candidates.append((path, record))
    return candidates


def _select_prediction(
    fixture: Mapping[str, Any], prediction_root: Path = PREDICTION_ROOT
) -> tuple[Path, dict[str, Any]] | None:
    fixture_id = _fixture_id(fixture)
    if fixture_id is None:
        return None
    candidates = _candidate_predictions(fixture_id, Path(prediction_root))
    if not candidates:
        return None
    kickoff = _fixture_kickoff(fixture)
    if kickoff is not None:
        matching = [
            item
            for item in candidates
            if _parse_datetime(item[1].get("kickoff_at")) == kickoff
        ]
        if not matching:
            return None
        candidates = matching
    return max(
        candidates,
        key=lambda item: (_prediction_timestamp(item[1]), _text(item[1].get("prediction_id")) or ""),
    )


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _failure_match(fixture: Mapping[str, Any], reason: str) -> dict[str, Any]:
    fixture_id = _fixture_id(fixture)
    return {
        "cohort_fixture": {
            "provider_match_id": fixture_id,
            "match_number": _text(fixture.get("matchNum") or fixture.get("match_num")),
            "business_date": _text(fixture.get("businessDate") or fixture.get("business_date")),
            "kickoff_at": _fixture_kickoff(fixture).isoformat(timespec="seconds") if _fixture_kickoff(fixture) else None,
        },
        "projection_status": "REJECTED",
        "projection_success": False,
        "projection_reject_reasons": [reason],
        "coverage": {
            "atoms": {},
            "omitted_atoms": ["projection"],
        },
    }


def _relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _aggregate(matches: list[dict[str, Any]]) -> dict[str, Any]:
    projection_rejects = Counter()
    atom_status: dict[str, Counter[str]] = {}
    omitted = Counter()
    history = {
        side: Counter(
            {
                "raw_row_count": 0,
                "accepted_history_row_count": 0,
                "rejected_row_count": 0,
                "source_fixture_id_count": 0,
                "team_id_count": 0,
                "competition_resolved_count": 0,
                "opponent_name_candidate_count": 0,
                "opponent_name_resolved_count": 0,
            }
        )
        for side in ("home", "away")
    }
    history_rejects = {side: Counter() for side in ("home", "away")}
    opponent_rejects = Counter()
    market = Counter(
        {
            "bookmaker_count": 0,
            "valid_open_bookmaker_count": 0,
            "valid_current_bookmaker_count": 0,
            "valid_book_count": 0,
            "rejected_bookmaker_count": 0,
            "chronology_available_count": 0,
        }
    )
    market_rejects = Counter()
    alignment = Counter({"available_count": 0, "omitted_count": 0, "aligned_count": 0, "conflict_count": 0})
    context = Counter({"competition_available_count": 0, "coach_available_count": 0, "referee_available_count": 0})
    successful = 0
    for match in matches:
        if match.get("projection_success") is True:
            successful += 1
        projection_rejects.update(match.get("projection_reject_reasons") or [])
        coverage = match.get("coverage") or {}
        for atom, item in (coverage.get("atoms") or {}).items():
            if not isinstance(item, Mapping):
                continue
            atom_status.setdefault(atom, Counter())[str(item.get("status") or "UNKNOWN")] += 1
            if item.get("status") == "OMITTED":
                omitted[f"{atom}:{item.get('reason') or 'UNSPECIFIED'}"] += 1
        omitted.update(str(atom) for atom in coverage.get("omitted_atoms") or [])

        for side in ("home", "away"):
            item = (coverage.get("atoms") or {}).get("recent_state", {}).get("history", {}).get(side, {})
            if isinstance(item, Mapping):
                for key in history[side]:
                    history[side][key] += int(item.get(key) or 0)
                history_rejects[side].update(item.get("reject_counts") or {})
                opponent_rejects.update(item.get("opponent_name_reject_counts") or {})

        market_projection = match.get("market_1x2_chronology") or {}
        for key in market:
            market[key] += int(market_projection.get(key) or 0)
        if market_projection.get("status") == "AVAILABLE":
            market["chronology_available_count"] += 1
        for bookmaker in market_projection.get("rejected_bookmakers") or []:
            market_rejects.update(bookmaker.get("reasons") or [])

        alignment_projection = match.get("model_market_alignment") or {}
        if alignment_projection.get("status") == "AVAILABLE":
            alignment["available_count"] += 1
            alignment[f"{str(alignment_projection.get('direction') or '').lower()}_count"] += 1
        else:
            alignment["omitted_count"] += 1

        context_projection = match.get("coverage", {}).get("atoms", {})
        for name, key in (("current_competition", "competition_available_count"), ("coach", "coach_available_count"), ("referee", "referee_available_count")):
            if (context_projection.get(name) or {}).get("status") == "AVAILABLE":
                context[key] += 1

    return {
        "projection_success_count": successful,
        "projection_reject_count": len(matches) - successful,
        "projection_reject_reason_counts": dict(sorted(projection_rejects.items())),
        "atom_status_counts": {atom: dict(sorted(counts.items())) for atom, counts in sorted(atom_status.items())},
        "omitted_atom_reason_counts": dict(sorted(omitted.items())),
        "history": {
            side: {
                **dict(history[side]),
                "reject_counts": dict(sorted(history_rejects[side].items())),
            }
            for side in ("home", "away")
        },
        "opponent_names": {
            "candidate_count": sum(history[side]["opponent_name_candidate_count"] for side in ("home", "away")),
            "resolved_count": sum(history[side]["opponent_name_resolved_count"] for side in ("home", "away")),
            "rejected_count": sum(history[side]["opponent_name_candidate_count"] - history[side]["opponent_name_resolved_count"] for side in ("home", "away")),
            "reject_counts": dict(sorted(opponent_rejects.items())),
        },
        "market_1x2": {
            **dict(market),
            "rejected_bookmaker_reason_counts": dict(sorted(market_rejects.items())),
        },
        "model_market_alignment": dict(alignment),
        "context": dict(context),
    }


def run_natural_cohort_audit(
    *,
    cohort_path: str | Path | None = None,
    as_of: str | datetime | None = None,
    prediction_root: Path = PREDICTION_ROOT,
    input_snapshot_root: Path = INPUT_SNAPSHOT_ROOT,
    evidence_root: Path = EVIDENCE_ROOT,
) -> dict[str, Any]:
    """Project every fixture in the selected READY cohort using local files."""

    cohort, selected_path = discover_natural_cohort(cohort_path=cohort_path, as_of=as_of)
    fixtures = [item for item in cohort.get("fixtures") or [] if isinstance(item, Mapping)]
    matches: list[dict[str, Any]] = []
    for fixture in fixtures:
        selected = _select_prediction(fixture, prediction_root=Path(prediction_root))
        if selected is None:
            matches.append(_failure_match(fixture, "NO_FROZEN_FORMAL_PREDICTION"))
            continue
        prediction_path, prediction = selected
        prediction_id = _text(prediction.get("prediction_id")) or ""
        snapshot_ref = (prediction.get("input_snapshot") or {}).get("snapshot_ref") if isinstance(prediction.get("input_snapshot"), Mapping) else None
        snapshot_path = _resolve_path(snapshot_ref or prediction.get("input_snapshot_ref"), fallback_root=input_snapshot_root)
        if snapshot_path is None:
            item = _failure_match(fixture, "INPUT_SNAPSHOT_NOT_FOUND")
            item["prediction_id"] = prediction_id
            item["prediction_ref"] = _relative(prediction_path)
            matches.append(item)
            continue
        evidence_path = evidence_root / f"{prediction_id}.json"
        if not evidence_path.is_file():
            item = _failure_match(fixture, "FOOTBALL_EVIDENCE_SIDECAR_NOT_FOUND")
            item.update({"prediction_id": prediction_id, "prediction_ref": _relative(prediction_path)})
            matches.append(item)
            continue
        try:
            snapshot = _load_json(snapshot_path)
            evidence = _load_json(evidence_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            item = _failure_match(fixture, f"FROZEN_INPUT_UNREADABLE_{type(error).__name__.upper()}")
            item.update({"prediction_id": prediction_id, "prediction_ref": _relative(prediction_path)})
            matches.append(item)
            continue
        projection = project_match_analysis_evidence(
            prediction,
            snapshot,
            evidence,
            accepted_fixture=fixture,
        )
        projection["cohort_fixture"] = {
            "provider_match_id": _fixture_id(fixture),
            "match_number": _text(fixture.get("matchNum") or fixture.get("match_num")),
            "business_date": _text(fixture.get("businessDate") or fixture.get("business_date")),
            "kickoff_at": _fixture_kickoff(fixture).isoformat(timespec="seconds") if _fixture_kickoff(fixture) else None,
        }
        projection["prediction_ref"] = _relative(prediction_path)
        projection["input_snapshot_ref"] = _relative(snapshot_path)
        projection["football_evidence_ref"] = _relative(evidence_path)
        matches.append(projection)

    cutoff = _parse_datetime(as_of) if as_of is not None else datetime.now(LOCAL_TZ)
    return {
        "contract_version": "match_analysis_evidence_projection_audit.v1",
        "run": {
            "mode": "offline_frozen_truth",
            "exact_head": _git_head(),
            "as_of": cutoff.isoformat(timespec="seconds") if cutoff else None,
        },
        "cohort": {
            "source": cohort.get("source"),
            "source_path": _relative(selected_path),
            "business_date": cohort.get("business_date"),
            "declared_fixture_count": len(fixtures),
            "actual_fixture_count": len(fixtures),
        },
        "matches": matches,
        "coverage": _aggregate(matches),
        "rights": {
            "network_used": False,
            "new_provider_used": False,
            "raw_bodies_persisted": False,
            "frozen_inputs_mutated": False,
        },
        "change_boundary": {
            "model_math_changed": False,
            "champion_changed": False,
            "serving_changed": False,
            "ui_changed": False,
            "provider_selection_changed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path")
    parser.add_argument("--as-of")
    parser.add_argument("--output", default="match-analysis-evidence-audit.json")
    args = parser.parse_args(argv)
    try:
        report = run_natural_cohort_audit(cohort_path=args.cohort_path, as_of=args.as_of)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"match-analysis evidence audit failed: {type(error).__name__}: {error}")
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    coverage = report["coverage"]
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(output),
                "exact_head": report["run"]["exact_head"],
                "cohort_count": report["cohort"]["actual_fixture_count"],
                "projection_success_count": coverage["projection_success_count"],
                "projection_reject_count": coverage["projection_reject_count"],
                "opponent_name_resolved_count": coverage["opponent_names"]["resolved_count"],
                "opponent_name_reject_count": coverage["opponent_names"]["rejected_count"],
                "valid_market_book_count": coverage["market_1x2"]["valid_book_count"],
                "market_chronology_available_count": coverage["market_1x2"]["chronology_available_count"],
                "model_market_alignment_available_count": coverage["model_market_alignment"]["available_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
