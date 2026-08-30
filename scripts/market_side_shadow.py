#!/usr/bin/env python3
"""Capture and evaluate the locked Market-Side-Only Challenger C.

This is a research-only sidecar.  It consumes an already frozen Champion
record and its immutable input snapshot, then writes a separate paired
namespace.  It never writes the Champion record, the formal prospective
ledger, or post-match fields into a prediction capture.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import sys
from statistics import fmean, median
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from automatic_model_core import build_automatic_model  # noqa: E402
from prediction_trust_2_replay import (  # noqa: E402
    ACCEPTED_PRODUCTION_RUN,
    ACCEPTED_WRITEBACK_COMMIT,
    _actual_outcome,
    _form_and_market_inputs,
    _score_pair,
    build_score_matrix,
)
from prediction_trust_3_replay import derive_market_side_only_lambdas  # noqa: E402


MILESTONE = "MARKET-SIDE-SHADOW-1"
SCHEMA_VERSION = "market_side_shadow_1.paired_capture.v1"
EVALUATION_SCHEMA_VERSION = "market_side_shadow_1.evaluation.v1"
NAMESPACE = "market_side_shadow_1"
CHAMPION_NAMESPACE = "production_champion"
CANDIDATE_NAMESPACE = "market_side_only_hybrid"
CANDIDATE_ID = "market_side_only_hybrid"
MIN_PAIRED_VERIFIED = 50
PROMOTION_REVIEW_MINIMUM = 100
EARLY_KILL_WINDOW = 30
PINNED_UNIQUE_MATCHES = 217
PINNED_VERIFIED_MATCHES = 181
DEFAULT_MANIFEST = ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "smoke_2026-08-30.json"
EPSILON = 1e-15
OUTCOMES = ("home", "draw", "away")
TAIL_KEYS = ("total_ge_4", "total_ge_5", "total_ge_6")
FORBIDDEN_CAPTURE_KEYS = {"actual_result", "settlement", "metrics", "settled_at"}


class ShadowCaptureConflictError(RuntimeError):
    """Raised when a deterministic pair id is reused with different content."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 9) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _mean(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values if _number(value) is not None]
    return fmean(clean) if clean else None


def _rate(value: float | None, count: int) -> float | None:
    return float(value) / count if value is not None and count else None


def _score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def _sorted_score_rows(matrix: Mapping[tuple[int, int], float]) -> list[dict[str, Any]]:
    ordered = sorted(
        ((tuple(score), float(probability)) for score, probability in matrix.items()),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    return [
        {
            "rank": rank,
            "score": _score_text(score),
            "home_goals": score[0],
            "away_goals": score[1],
            "probability": round(probability, 12),
        }
        for rank, (score, probability) in enumerate(ordered, 1)
    ]


def _outcome_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    output = {key: 0.0 for key in OUTCOMES}
    for (home, away), probability in matrix.items():
        output[_actual_outcome((home, away))] += float(probability)
    return {key: round(value, 12) for key, value in output.items()}


def _btts_probability(matrix: Mapping[tuple[int, int], float]) -> float:
    return sum(float(value) for (home, away), value in matrix.items() if home > 0 and away > 0)


def _tail_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    return {
        "total_ge_4": round(sum(value for (home, away), value in matrix.items() if home + away >= 4), 12),
        "total_ge_5": round(sum(value for (home, away), value in matrix.items() if home + away >= 5), 12),
        "total_ge_6": round(sum(value for (home, away), value in matrix.items() if home + away >= 6), 12),
    }


def _output_from_matrix(
    matrix: Mapping[tuple[int, int], float],
    *,
    lambda_home: float,
    lambda_away: float,
    candidate_id: str,
    model_family: str,
    namespace: str,
    frozen_input_digest: str | None = None,
    freeze_eligibility: Mapping[str, Any] | None = None,
    prediction_id: str | None = None,
    prediction_sha256: str | None = None,
    rho: float = 0.0,
) -> dict[str, Any]:
    rows = _sorted_score_rows(matrix)
    if not rows:
        raise ValueError("score matrix is empty")
    btts_yes = _btts_probability(matrix)
    probabilities = _outcome_probabilities(matrix)
    return {
        "candidate_id": candidate_id,
        "model_family": model_family,
        "namespace": namespace,
        "prediction_id": prediction_id,
        "prediction_sha256": prediction_sha256,
        "frozen_input_digest": frozen_input_digest,
        "freeze_eligibility": deepcopy(dict(freeze_eligibility or {})),
        "lambda_home": round(float(lambda_home), 12),
        "lambda_away": round(float(lambda_away), 12),
        "lambda_total": round(float(lambda_home) + float(lambda_away), 12),
        "rho": float(rho),
        "probabilities": probabilities,
        "exact_score_distribution": rows,
        "score_top1": rows[0]["score"],
        "score_top3": [row["score"] for row in rows[:3]],
        "btts": {"yes": round(btts_yes, 12), "no": round(1.0 - btts_yes, 12)},
        "btts_probability": round(btts_yes, 12),
        "ou_2_5_probability": round(
            sum(value for (home, away), value in matrix.items() if home + away >= 3),
            12,
        ),
        "tail_probabilities": _tail_probabilities(matrix),
    }


def build_challenger_c_output(context: Mapping[str, Any]) -> dict[str, Any]:
    """Build C with exactly the PRED-TRUST-3 locked boundary."""

    inputs = _form_and_market_inputs(context)
    candidate = derive_market_side_only_lambdas(
        form_home=inputs["form_home"],
        form_away=inputs["form_away"],
        market_total=inputs["market_total"],
        market_share=inputs["market_share"],
        form_total=inputs["form_total"],
    )
    matrix = build_score_matrix(float(candidate["lambda_home"]), float(candidate["lambda_away"]))
    output = _output_from_matrix(
        matrix,
        lambda_home=float(candidate["lambda_home"]),
        lambda_away=float(candidate["lambda_away"]),
        candidate_id=CANDIDATE_ID,
        model_family=CANDIDATE_ID,
        namespace=CANDIDATE_NAMESPACE,
    )
    output.update(
        {
            "formula": {
                "total": "champion_total_0.60_form_0.40_market",
                "share": "market_share_only",
                "lambda_home": "total * market_share",
                "lambda_away": "total * (1-market_share)",
                "clamp": "existing_clamp",
                "score_matrix": "independent_poisson_rho_0",
            },
            "inputs": {
                "form_total": round(float(inputs["form_total"]), 12),
                "market_total": _round(inputs["market_total"], 12),
                "champion_total": round(float(candidate["total"]), 12),
                "form_share": round(float(candidate["form_share"]), 12),
                "market_share": round(float(candidate["market_share"]), 12),
            },
            "post_match_parameter_input": False,
        }
    )
    return output


def _freeze_eligibility(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policy": record.get("formal_eligibility_policy"),
        "formal_eligible": record.get("formal_eligible") is True,
        "model_formal_eligible": record.get("model_formal_eligible") is True,
        "prediction_status": record.get("prediction_status"),
        "prediction_variant": record.get("prediction_variant"),
        "model_role": record.get("model_role"),
        "freeze_created_at": record.get("freeze_created_at"),
    }


def _record_snapshot_ref(record: Mapping[str, Any]) -> str:
    reference = str(record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or "").strip()
    if not reference:
        raise ValueError("frozen record is missing input_snapshot_ref")
    return reference


def _snapshot_path(record: Mapping[str, Any], snapshot_root: Path) -> Path:
    reference = Path(_record_snapshot_ref(record))
    if reference.is_absolute():
        return reference
    root = Path(snapshot_root)
    direct = root / reference
    if direct.is_file():
        return direct
    # The production freeze API receives the input-snapshots directory while
    # the pinned cohort stores a repository-relative reference.  Support both
    # contracts without changing either frozen record or snapshot.
    canonical = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), Mapping) else {}
    digest = str(
        canonical.get("canonical_input_sha256")
        or record.get("input_sha256")
        or record.get("canonical_model_input_sha256")
        or ""
    )
    candidates = [root / reference.name]
    if digest:
        candidates.append(root / f"{digest}.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return direct


def _load_frozen_input(
    record: Mapping[str, Any],
    snapshot_root: Path,
    expected_snapshot_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = _snapshot_path(record, snapshot_root)
    raw = path.read_bytes()
    digest = _sha256_bytes(raw)
    if expected_snapshot_sha256 and digest != str(expected_snapshot_sha256):
        raise ValueError("frozen input snapshot digest does not match pinned manifest")
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("input"), dict):
        raise ValueError("frozen input snapshot has no input object")
    snapshot_meta = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), dict) else {}
    expected_canonical = str(
        record.get("canonical_model_input_sha256")
        or snapshot_meta.get("canonical_model_input_sha256")
        or ""
    )
    actual_canonical = str(document.get("canonical_model_input_sha256") or "")
    if expected_canonical and actual_canonical and expected_canonical != actual_canonical:
        raise ValueError("frozen input canonical digest mismatch")
    record_cutoff = str(record.get("source_cutoff_at") or "")
    snapshot_cutoff = str(document.get("source_cutoff_at") or "")
    if record_cutoff and snapshot_cutoff and record_cutoff != snapshot_cutoff:
        raise ValueError("frozen input source cutoff mismatch")
    return document, document["input"], digest


def _stored_champion_output(
    record: Mapping[str, Any],
    *,
    frozen_input_digest: str | None,
    eligibility: Mapping[str, Any],
) -> dict[str, Any]:
    source = record.get("prediction_output") if isinstance(record.get("prediction_output"), dict) else {}
    lambda_home = _number(record.get("lambda_home"))
    lambda_home = lambda_home if lambda_home is not None else _number(source.get("lambda_home"))
    lambda_away = _number(record.get("lambda_away"))
    lambda_away = lambda_away if lambda_away is not None else _number(source.get("lambda_away"))
    probabilities = record.get("probabilities") or source.get("probabilities")
    if not isinstance(probabilities, dict):
        probabilities = {}
    rows = record.get("score_distribution") or record.get("score_top10") or source.get("score_matrix")
    rows = deepcopy(rows) if isinstance(rows, list) else []
    matrix = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = _score_pair(row.get("score"))
        probability = _number(row.get("probability"))
        if score is not None and probability is not None:
            matrix[score] = probability
    if lambda_home is not None and lambda_away is not None:
        matrix = build_score_matrix(lambda_home, lambda_away)
    if matrix:
        return _output_from_matrix(
            matrix,
            lambda_home=lambda_home or 0.0,
            lambda_away=lambda_away or 0.0,
            candidate_id="champion",
            model_family=str(record.get("model_family") or "recent_form_market_calibrated_poisson_v2"),
            namespace=CHAMPION_NAMESPACE,
            frozen_input_digest=frozen_input_digest,
            freeze_eligibility=eligibility,
            prediction_id=str(record.get("prediction_id") or ""),
            prediction_sha256=str(record.get("prediction_sha256") or "") or None,
            rho=_number(record.get("rho")) or 0.0,
        )
    return {
        "candidate_id": "champion",
        "model_family": str(record.get("model_family") or "recent_form_market_calibrated_poisson_v2"),
        "namespace": CHAMPION_NAMESPACE,
        "prediction_id": str(record.get("prediction_id") or ""),
        "prediction_sha256": str(record.get("prediction_sha256") or "") or None,
        "frozen_input_digest": frozen_input_digest,
        "freeze_eligibility": deepcopy(dict(eligibility)),
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": (lambda_home + lambda_away) if lambda_home is not None and lambda_away is not None else None,
        "rho": _number(record.get("rho")) or 0.0,
        "probabilities": deepcopy(probabilities),
        "exact_score_distribution": rows,
        "score_top1": record.get("unique_score"),
        "score_top3": [row.get("score") for row in rows[:3] if isinstance(row, dict)],
        "btts": deepcopy(record.get("btts") or source.get("btts") or {}),
        "btts_probability": _number((record.get("btts") or source.get("btts") or {}).get("yes")),
        "ou_2_5_probability": None,
        "tail_probabilities": {key: None for key in TAIL_KEYS},
    }


def _champion_parity(record: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    stored_source = record.get("prediction_output") if isinstance(record.get("prediction_output"), dict) else {}
    checks: dict[str, bool] = {}
    for field in ("lambda_home", "lambda_away"):
        stored = _number(record.get(field))
        generated = _number(model.get(field))
        checks[field] = stored is None or generated is None or abs(stored - generated) <= 1e-5
    stored_probs = record.get("probabilities") or stored_source.get("probabilities")
    generated_probs = model.get("probabilities")
    for outcome in OUTCOMES:
        stored = _number(stored_probs.get(outcome)) if isinstance(stored_probs, dict) else None
        generated = _number(generated_probs.get(outcome)) if isinstance(generated_probs, dict) else None
        checks[f"probability_{outcome}"] = stored is None or generated is None or abs(stored - generated) <= 1e-5
    return {
        "status": "MATCHED" if all(checks.values()) else "MISMATCH",
        "checks": checks,
        "max_allowed_delta": 1e-5,
    }


def _pair_id(match_id: str, source_cutoff: str, frozen_input_digest: str | None) -> str:
    material = f"{NAMESPACE}|{match_id}|{source_cutoff}|{frozen_input_digest or 'missing'}|{SCHEMA_VERSION}"
    return "MS-SHADOW-PAIR-" + _sha256_bytes(material.encode("utf-8"))[:32]


def _challenger_prediction_id(pair_id: str) -> str:
    return f"shadow-c:{pair_id}"


def _base_pair(record: Mapping[str, Any], *, frozen_input_digest: str | None) -> dict[str, Any]:
    eligibility = _freeze_eligibility(record)
    match_id = str(record.get("match_id") or record.get("match_key") or "")
    match_key = str(record.get("match_key") or "")
    source_cutoff = str(record.get("source_cutoff_at") or "")
    pair_id = _pair_id(match_id, source_cutoff, frozen_input_digest)
    champion = _stored_champion_output(
        record,
        frozen_input_digest=frozen_input_digest,
        eligibility=eligibility,
    )
    champion.update(
        {
            "match_id": match_id,
            "source_cutoff": source_cutoff or None,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "namespace": NAMESPACE,
        "pair_id": pair_id,
        "pair_status": "CHALLENGER_ABSTAIN",
        "match_id": match_id,
        "match_key": match_key,
        "kickoff_at": record.get("kickoff_at"),
        "source_cutoff": source_cutoff or None,
        "freeze_created_at": record.get("freeze_created_at"),
        "freeze_eligibility": eligibility,
        "frozen_input_digest": frozen_input_digest,
        "canonical_model_input_sha256": record.get("canonical_model_input_sha256"),
        "input_snapshot_ref": _record_snapshot_ref(record) if record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") else None,
        "champion_prediction_id": record.get("prediction_id"),
        "challenger_prediction_id": _challenger_prediction_id(pair_id),
        "champion": champion,
        "challenger": None,
        "champion_preserved": True,
        "same_fixture": True,
        "same_source_cutoff": bool(source_cutoff),
        "same_freeze_eligibility": True,
        "same_frozen_input_digest": bool(frozen_input_digest),
        "post_match_input_used_for_generation": False,
        "production_enabled": False,
        "user_visible": False,
        "promotion_eligible": False,
    }


def _finalize_pair(pair: dict[str, Any]) -> dict[str, Any]:
    polluted = sorted(FORBIDDEN_CAPTURE_KEYS.intersection(pair))
    if polluted:
        raise ValueError("post-match fields are forbidden in shadow capture: " + ", ".join(polluted))
    unsigned = deepcopy(pair)
    unsigned.pop("pair_digest", None)
    pair["pair_digest"] = _sha256_bytes(canonical_json(unsigned).encode("utf-8"))
    return pair


def capture_pair(
    record: Mapping[str, Any],
    *,
    snapshot_root: Path = ROOT,
    expected_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one immutable Champion/C pair; C failure is isolated as ABSTAIN."""

    if not isinstance(record, Mapping):
        raise ValueError("frozen record must be an object")
    initial_digest = expected_snapshot_sha256
    pair: dict[str, Any] | None = None
    try:
        snapshot, context, digest = _load_frozen_input(
            record,
            Path(snapshot_root),
            expected_snapshot_sha256,
        )
        pair = _base_pair(record, frozen_input_digest=digest)
        pair["source_cutoff"] = str(record.get("source_cutoff_at") or snapshot.get("source_cutoff_at") or "") or None
        pair["same_source_cutoff"] = bool(pair["source_cutoff"])
        result = build_automatic_model(context)
        champion_model = result.get("model") if isinstance(result, dict) else None
        if not isinstance(champion_model, dict):
            raise ValueError("CHAMPION_REPLAY_NO_MODEL")
        parity = _champion_parity(record, champion_model)
        pair["champion_reproduction"] = parity
        if parity["status"] != "MATCHED":
            raise ValueError("CHAMPION_REPLAY_MISMATCH")
        eligibility = pair["freeze_eligibility"]
        pair["champion"] = _output_from_matrix(
            build_score_matrix(float(champion_model["lambda_home"]), float(champion_model["lambda_away"])),
            lambda_home=float(champion_model["lambda_home"]),
            lambda_away=float(champion_model["lambda_away"]),
            candidate_id="champion",
            model_family=str(champion_model.get("method") or record.get("model_family") or "recent_form_market_calibrated_poisson_v2"),
            namespace=CHAMPION_NAMESPACE,
            frozen_input_digest=digest,
            freeze_eligibility=eligibility,
            prediction_id=str(record.get("prediction_id") or ""),
            prediction_sha256=str(record.get("prediction_sha256") or "") or None,
            rho=_number(champion_model.get("rho")) or 0.0,
        )
        pair["challenger"] = build_challenger_c_output(context)
        for output in (pair["champion"], pair["challenger"]):
            output.update(
                {
                    "match_id": pair["match_id"],
                    "source_cutoff": pair["source_cutoff"],
                    "frozen_input_digest": digest,
                    "freeze_eligibility": deepcopy(eligibility),
                }
            )
        pair["challenger"].update({"prediction_id": _challenger_prediction_id(pair["pair_id"])})
        pair["pair_status"] = "PAIRED"
        pair["same_frozen_input_digest"] = pair["champion"]["frozen_input_digest"] == pair["challenger"]["frozen_input_digest"]
        pair["integrity"] = {
            "same_match_id": pair["match_id"] == str(record.get("match_id") or record.get("match_key") or ""),
            "same_source_cutoff": pair["same_source_cutoff"],
            "same_freeze_eligibility": pair["champion"]["freeze_eligibility"] == pair["challenger"]["freeze_eligibility"],
            "same_frozen_input_digest": pair["same_frozen_input_digest"],
        }
        if not all(pair["integrity"].values()):
            raise ValueError("PAIRED_IDENTITY_MISMATCH")
    except Exception as error:
        if pair is None:
            pair = _base_pair(record, frozen_input_digest=initial_digest)
        pair["pair_status"] = "CHALLENGER_ABSTAIN"
        pair["challenger"] = None
        pair["champion_preserved"] = True
        pair["challenger_abstain_reason"] = f"{type(error).__name__}:{error}"
        pair["champion_reproduction"] = {"status": "NOT_AVAILABLE"}
    return _finalize_pair(pair)


def _persist_json(path: Path, value: Mapping[str, Any], label: str) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = canonical_json(value)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return {"status": "created", "path": path, "document": deepcopy(dict(value))}
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ShadowCaptureConflictError(f"existing {label} is unreadable: {path}") from error
        if not isinstance(existing, dict) or canonical_json(existing) != serialized:
            identifier = value.get("pair_id") or value.get("milestone") or path.name
            raise ShadowCaptureConflictError(f"{label} content conflict: {identifier}")
        return {"status": "existing", "path": path, "document": existing}


def persist_pair(pair: Mapping[str, Any], pair_root: Path = DEFAULT_PAIR_ROOT) -> dict[str, Any]:
    if not isinstance(pair, Mapping) or not pair.get("pair_id"):
        raise ValueError("pair must contain pair_id")
    if FORBIDDEN_CAPTURE_KEYS.intersection(pair):
        raise ValueError("post-match fields are forbidden in shadow capture")
    return _persist_json(Path(pair_root) / f"{pair['pair_id']}.json", pair, "shadow pair")


def load_persisted_pairs(pair_root: Path = DEFAULT_PAIR_ROOT) -> list[dict[str, Any]]:
    pairs = []
    for path in sorted(Path(pair_root).glob("MS-SHADOW-PAIR-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION:
            pairs.append(value)
    return pairs


def _reliability_bins(probabilities: Iterable[float], observed: Iterable[bool]) -> list[dict[str, Any]]:
    pairs = [(max(0.0, min(1.0, float(probability))), bool(value)) for probability, value in zip(probabilities, observed)]
    bins = []
    for index in range(5):
        lower, upper = index / 5, (index + 1) / 5
        bucket = [
            pair for pair in pairs
            if lower <= pair[0] < upper or (index == 4 and lower <= pair[0] <= upper)
        ]
        bins.append(
            {
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "count": len(bucket),
                "mean_predicted_probability": round(fmean(item[0] for item in bucket), 9) if bucket else None,
                "observed_frequency": round(fmean(float(item[1]) for item in bucket), 9) if bucket else None,
            }
        )
    return bins


def _ece(probabilities: list[float], observed: list[bool]) -> float | None:
    pairs = [(float(probability), bool(value)) for probability, value in zip(probabilities, observed)]
    if not pairs:
        return None
    bins = _reliability_bins(probabilities, observed)
    total = len(pairs)
    return round(
        sum(
            item["count"] / total * abs(item["mean_predicted_probability"] - item["observed_frequency"])
            for item in bins
            if item["count"]
        ),
        9,
    )


def _binary_metrics(probabilities: list[float], observed: list[bool]) -> dict[str, Any]:
    sample = len(observed)
    if not sample:
        return {
            "sample_count": 0,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
            "ece": None,
            "reliability_bins": _reliability_bins([], []),
        }
    log_loss = fmean(-math.log(max(EPSILON, min(1.0 - EPSILON, probability if observed_value else 1.0 - probability))) for probability, observed_value in zip(probabilities, observed))
    return {
        "sample_count": sample,
        "accuracy": round(sum((probability >= 0.5) == actual for probability, actual in zip(probabilities, observed)) / sample, 9),
        "brier": round(fmean((probability - float(actual)) ** 2 for probability, actual in zip(probabilities, observed)), 9),
        "log_loss": round(log_loss, 9),
        "ece": _ece(probabilities, observed),
        "reliability_bins": _reliability_bins(probabilities, observed),
    }


def _multiclass_metrics(probabilities: list[dict[str, float]], actuals: list[str]) -> dict[str, Any]:
    sample = len(actuals)
    if not sample:
        return {"sample_count": 0, "accuracy": None, "brier": None, "log_loss": None, "ece": None}
    per_class_ece = []
    for outcome in OUTCOMES:
        per_class_ece.append(
            _ece(
                [float(row.get(outcome, 0.0)) for row in probabilities],
                [actual == outcome for actual in actuals],
            )
        )
    return {
        "sample_count": sample,
        "accuracy": round(sum(max(row, key=row.get) == actual for row, actual in zip(probabilities, actuals)) / sample, 9),
        "brier": round(fmean(sum((float(row.get(key, 0.0)) - float(key == actual)) ** 2 for key in OUTCOMES) for row, actual in zip(probabilities, actuals)), 9),
        "log_loss": round(fmean(-math.log(max(EPSILON, min(1.0 - EPSILON, float(row.get(actual, 0.0))))) for row, actual in zip(probabilities, actuals)), 9),
        "ece": round(fmean(value for value in per_class_ece if value is not None), 9),
    }


def _distribution_from_output(output: Mapping[str, Any]) -> dict[tuple[int, int], float]:
    rows = output.get("exact_score_distribution")
    if not isinstance(rows, list):
        return {}
    distribution = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        score = _score_pair(row.get("score"))
        probability = _number(row.get("probability"))
        if score is not None and probability is not None:
            distribution[score] = probability
    return distribution


def _quantiles(values: Iterable[float]) -> dict[str, float | None]:
    ordered = sorted(float(value) for value in values if _number(value) is not None)
    if not ordered:
        return {key: None for key in ("P10", "P25", "P50", "P75", "P90")}

    def quantile(probability: float) -> float:
        position = (len(ordered) - 1) * probability
        lower, upper = math.floor(position), math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        key: round(quantile(probability), 9)
        for key, probability in (("P10", 0.10), ("P25", 0.25), ("P50", 0.50), ("P75", 0.75), ("P90", 0.90))
    }


def _empty_candidate_metrics() -> dict[str, Any]:
    empty_binary = _binary_metrics([], [])
    return {
        "sample_count": 0,
        "one_x_two": _multiclass_metrics([], []),
        "exact_score": {
            "sample_count": 0,
            "top1_hit_rate": None,
            "top3_hit_rate": None,
            "nll": None,
            "mean_probability_assigned_to_actual_score": None,
        },
        "btts": deepcopy(empty_binary),
        "ou_2_5": deepcopy(empty_binary),
        "lambda": {
            "median_abs_gap": None,
            "gap_lt_0_25_share": None,
            "gap_lt_0_5_share": None,
            "lambda_total_distribution": _quantiles([]),
        },
        "distribution": {
            "one_one_top1_share": None,
            "top1_support_size": 0,
            "home_margin_top1_share": None,
            "draw_top1_share": None,
            "away_margin_top1_share": None,
            "high_score_top1_share": None,
            "top1_score_counts": {},
        },
        "right_tail": {
            key: {
                "sample_count": 0,
                "mean_probability": None,
                "observed_frequency": None,
                "brier": None,
                "ece": None,
                "reliability_bins": _reliability_bins([], []),
            }
            for key in TAIL_KEYS
        },
    }


def _candidate_metrics(outputs: list[Mapping[str, Any]], actual_scores: list[tuple[int, int]]) -> dict[str, Any]:
    if not outputs:
        return _empty_candidate_metrics()
    actual_outcomes = [_actual_outcome(score) for score in actual_scores]
    probabilities = [dict(output.get("probabilities") or {}) for output in outputs]
    btts_probs = [float(output.get("btts_probability") or 0.0) for output in outputs]
    ou_probs = [float(output.get("ou_2_5_probability") or 0.0) for output in outputs]
    btts_actuals = [home > 0 and away > 0 for home, away in actual_scores]
    ou_actuals = [home + away >= 3 for home, away in actual_scores]
    top1_hits, top3_hits, actual_probabilities, score_nll = [], [], [], []
    gaps, totals, top1_scores = [], [], []
    tail_probabilities: dict[str, list[float]] = {key: [] for key in TAIL_KEYS}
    tail_actuals: dict[str, list[bool]] = {key: [] for key in TAIL_KEYS}
    for output, actual in zip(outputs, actual_scores):
        actual_text = _score_text(actual)
        top1 = str(output.get("score_top1") or "")
        top3 = [str(value) for value in output.get("score_top3") or []]
        distribution = _distribution_from_output(output)
        actual_probability = distribution.get(actual)
        top1_hits.append(top1 == actual_text)
        top3_hits.append(actual_text in top3)
        if actual_probability is not None:
            actual_probabilities.append(actual_probability)
            score_nll.append(-math.log(max(EPSILON, actual_probability)))
        home_lambda = _number(output.get("lambda_home"))
        away_lambda = _number(output.get("lambda_away"))
        if home_lambda is not None and away_lambda is not None:
            gaps.append(abs(home_lambda - away_lambda))
            totals.append(home_lambda + away_lambda)
        parsed_top1 = _score_pair(top1)
        if parsed_top1 is not None:
            top1_scores.append(parsed_top1)
        tails = output.get("tail_probabilities") if isinstance(output.get("tail_probabilities"), Mapping) else {}
        for key in TAIL_KEYS:
            tail_probabilities[key].append(float(tails.get(key) or 0.0))
            threshold = int(key.rsplit("_", 1)[-1])
            tail_actuals[key].append(actual[0] + actual[1] >= threshold)
    sample = len(actual_scores)
    counts: dict[str, int] = {}
    for score in top1_scores:
        counts[_score_text(score)] = counts.get(_score_text(score), 0) + 1
    return {
        "sample_count": sample,
        "one_x_two": _multiclass_metrics(probabilities, actual_outcomes),
        "exact_score": {
            "sample_count": sample,
            "top1_hit_rate": round(sum(top1_hits) / sample, 9),
            "top3_hit_rate": round(sum(top3_hits) / sample, 9),
            "nll": round(fmean(score_nll), 9) if score_nll else None,
            "mean_probability_assigned_to_actual_score": round(fmean(actual_probabilities), 9) if actual_probabilities else None,
        },
        "btts": _binary_metrics(btts_probs, btts_actuals),
        "ou_2_5": _binary_metrics(ou_probs, ou_actuals),
        "lambda": {
            "median_abs_gap": round(median(gaps), 9) if gaps else None,
            "gap_lt_0_25_share": round(sum(value < 0.25 for value in gaps) / len(gaps), 9) if gaps else None,
            "gap_lt_0_5_share": round(sum(value < 0.5 for value in gaps) / len(gaps), 9) if gaps else None,
            "lambda_total_distribution": _quantiles(totals),
        },
        "distribution": {
            "one_one_top1_share": round(sum(score == (1, 1) for score in top1_scores) / sample, 9) if sample else None,
            "top1_support_size": len(counts),
            "home_margin_top1_share": round(sum(home > away for home, away in top1_scores) / sample, 9) if sample else None,
            "draw_top1_share": round(sum(home == away for home, away in top1_scores) / sample, 9) if sample else None,
            "away_margin_top1_share": round(sum(home < away for home, away in top1_scores) / sample, 9) if sample else None,
            "high_score_top1_share": round(sum(home + away >= 4 for home, away in top1_scores) / sample, 9) if sample else None,
            "top1_score_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        },
        "right_tail": {
            key: {
                "sample_count": len(tail_actuals[key]),
                "mean_probability": round(fmean(tail_probabilities[key]), 9) if tail_probabilities[key] else None,
                "observed_frequency": round(fmean(float(value) for value in tail_actuals[key]), 9) if tail_actuals[key] else None,
                "brier": _binary_metrics(tail_probabilities[key], tail_actuals[key])["brier"],
                "ece": _binary_metrics(tail_probabilities[key], tail_actuals[key])["ece"],
                "reliability_bins": _reliability_bins(tail_probabilities[key], tail_actuals[key]),
            }
            for key in TAIL_KEYS
        },
    }


def _actual_for_pair(pair: Mapping[str, Any], results: Mapping[str, Any]) -> tuple[int, int] | None:
    keys = (
        str(pair.get("pair_id") or ""),
        str(pair.get("match_id") or ""),
        str(pair.get("champion_prediction_id") or ""),
        str(pair.get("challenger_prediction_id") or ""),
    )
    value: Any = None
    for key in keys:
        if key and key in results:
            value = results[key]
            break
    if isinstance(value, Mapping):
        value = value.get("actual_score") or value.get("score") or value
    return _score_pair(value)


def _integrity_failures(pairs: Iterable[Mapping[str, Any]]) -> list[str]:
    failures = []
    for pair in pairs:
        if pair.get("pair_status") != "PAIRED":
            continue
        integrity = pair.get("integrity") if isinstance(pair.get("integrity"), Mapping) else {}
        for key, value in integrity.items():
            if value is not True:
                failures.append(f"{pair.get('pair_id')}:{key}")
        if pair.get("post_match_input_used_for_generation") is not False:
            failures.append(f"{pair.get('pair_id')}:post_match_input")
    return failures


def _metric_collapse(champion: Mapping[str, Any], challenger: Mapping[str, Any]) -> list[str]:
    """Operational early-kill sentinels, not a promotion gate or tuner."""

    checks = []
    for path, threshold, label in (
        (("one_x_two", "brier"), 0.10, "1x2_brier"),
        (("one_x_two", "log_loss"), 0.20, "1x2_log_loss"),
        (("btts", "brier"), 0.08, "btts_brier"),
        (("ou_2_5", "brier"), 0.08, "ou_2_5_brier"),
    ):
        left = _number((champion.get(path[0]) or {}).get(path[1]))
        right = _number((challenger.get(path[0]) or {}).get(path[1]))
        if left is not None and right is not None and right - left > threshold:
            checks.append(label)
    return checks


def evaluate_paired_cohort(
    pairs: Iterable[Mapping[str, Any]],
    verified_results: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate only verified results supplied after capture.

    The result map is deliberately separate from capture.  Actual scores are
    never accepted by the prediction-generation functions above.
    """

    pair_list = [dict(pair) for pair in pairs]
    result_map = dict(verified_results or {})
    selected: list[tuple[dict[str, Any], tuple[int, int]]] = []
    for pair in pair_list:
        if pair.get("pair_status") != "PAIRED":
            continue
        actual = _actual_for_pair(pair, result_map)
        if actual is not None:
            selected.append((pair, actual))
    actual_scores = [actual for _, actual in selected]
    champion_outputs = [pair["champion"] for pair, _ in selected if isinstance(pair.get("champion"), Mapping)]
    challenger_outputs = [pair["challenger"] for pair, _ in selected if isinstance(pair.get("challenger"), Mapping)]
    champion_metrics = _candidate_metrics(champion_outputs, actual_scores)
    challenger_metrics = _candidate_metrics(challenger_outputs, actual_scores)
    integrity_failures = _integrity_failures(pair_list)
    collapse = _metric_collapse(champion_metrics, challenger_metrics)
    verified_count = len(selected)
    early_triggers = integrity_failures + collapse
    if verified_count <= EARLY_KILL_WINDOW and early_triggers:
        early_status = "SHADOW_EARLY_STOP_RECOMMENDED"
    elif verified_count > EARLY_KILL_WINDOW:
        early_status = "WINDOW_CLOSED"
    else:
        early_status = "NOT_TRIGGERED"
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "verified_paired_count": verified_count,
        "paired_count": sum(pair.get("pair_status") == "PAIRED" for pair in pair_list),
        "skipped_unverified_pair_count": sum(
            pair.get("pair_status") == "PAIRED" and _actual_for_pair(pair, result_map) is None
            for pair in pair_list
        ),
        "post_match_input_used_for_generation": False,
        "actual_results_used_for_evaluation_only": True,
        "candidates": {
            "champion": champion_metrics,
            "challenger": challenger_metrics,
        },
        "btts_calibration_watch": {
            "status": "TRACKING" if verified_count else "PENDING_MINIMUM_SAMPLE",
            "champion_ece": champion_metrics["btts"]["ece"],
            "challenger_ece": challenger_metrics["btts"]["ece"],
            "champion_brier": champion_metrics["btts"]["brier"],
            "challenger_brier": challenger_metrics["btts"]["brier"],
            "champion_reliability_bins": champion_metrics["btts"]["reliability_bins"],
            "challenger_reliability_bins": challenger_metrics["btts"]["reliability_bins"],
        },
        "early_kill": {
            "window_matches": EARLY_KILL_WINDOW,
            "status": early_status,
            "triggers": early_triggers,
            "integrity_failures": integrity_failures,
            "metric_collapse_sentinels": collapse,
        },
    }


def checkpoint_status(verified_paired_count: int) -> dict[str, Any]:
    count = max(0, int(verified_paired_count))
    if count >= PROMOTION_REVIEW_MINIMUM:
        status = "PROMOTION_REVIEW_READY"
        next_threshold = None
    elif count >= MIN_PAIRED_VERIFIED:
        status = "CHECKPOINT"
        next_threshold = PROMOTION_REVIEW_MINIMUM
    else:
        status = "NOT_REACHED"
        next_threshold = MIN_PAIRED_VERIFIED
    return {
        "status": status,
        "verified_paired_count": count,
        "checkpoint_minimum": MIN_PAIRED_VERIFIED,
        "promotion_review_minimum": PROMOTION_REVIEW_MINIMUM,
        "next_threshold": next_threshold,
        "auto_promote": False,
    }


def build_shadow_document(
    pairs: Iterable[Mapping[str, Any]],
    verified_results: Mapping[str, Any] | None = None,
    *,
    source_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pair_list = [deepcopy(dict(pair)) for pair in pairs]
    evaluation = evaluate_paired_cohort(pair_list, verified_results)
    paired_count = sum(pair.get("pair_status") == "PAIRED" for pair in pair_list)
    abstain_count = sum(pair.get("pair_status") == "CHALLENGER_ABSTAIN" for pair in pair_list)
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "namespace": NAMESPACE,
        "candidate_id": CANDIDATE_ID,
        "capture_contract": {
            "same_fixture": True,
            "same_source_cutoff": True,
            "same_freeze_eligibility": True,
            "same_frozen_input_digest": True,
            "pair_status_values": ["PAIRED", "CHALLENGER_ABSTAIN"],
            "champion_unchanged": True,
            "production_enabled": False,
            "user_visible": False,
            "promotion_enabled": False,
            "post_match_input_used_for_generation": False,
            "formula_locked": "PRED-TRUST-3 market-side-only hybrid C",
        },
        "source_pins": {
            "accepted_production_run": ACCEPTED_PRODUCTION_RUN,
            "accepted_writeback_commit": ACCEPTED_WRITEBACK_COMMIT,
            "pinned_unique_final_legal_prematch_matches": PINNED_UNIQUE_MATCHES,
            "pinned_verified_90m_matches": PINNED_VERIFIED_MATCHES,
            "manifest": deepcopy(dict(source_manifest or {})),
        },
        "counts": {
            "pairs": len(pair_list),
            "paired": paired_count,
            "challenger_abstain": abstain_count,
        },
        "checkpoint": checkpoint_status(evaluation["verified_paired_count"]),
        "evaluation": evaluation,
        "pairs": pair_list,
        "production_protection": {
            "champion_namespace": CHAMPION_NAMESPACE,
            "challenger_namespace": CANDIDATE_NAMESPACE,
            "formal_prospective_ledger_touched": False,
            "frozen_champion_rewritten": False,
            "automatic_promotion": False,
        },
    }


def persist_document(document: Mapping[str, Any], output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    return _persist_json(Path(output), document, "shadow document")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _load_pinned_record(root: Path, manifest_path: Path, prediction_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    from prediction_trust_2_replay import _load_pinned_records

    records, manifest = _load_pinned_records(root, manifest_path)
    wanted = str(prediction_id or manifest["selected_records"][0]["prediction_id"])
    by_id = {str(record.get("prediction_id")): record for record in records}
    if wanted not in by_id:
        raise ValueError(f"prediction is not in the pinned 217-match cohort: {wanted}")
    entries = {str(entry.get("prediction_id")): entry for entry in manifest.get("selected_records") or []}
    return by_id[wanted], entries[wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root containing frozen records")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prediction-id", help="one pinned final Champion prediction; defaults to first manifest entry")
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--results", type=Path, help="separate verified-result map for evaluation only")
    args = parser.parse_args()
    record, entry = _load_pinned_record(args.root, args.manifest, args.prediction_id)
    pair = capture_pair(
        record,
        snapshot_root=args.root,
        expected_snapshot_sha256=entry.get("input_snapshot_sha256"),
    )
    persisted = persist_pair(pair, args.pair_root)
    results = _load_json(args.results) if args.results else {}
    pairs = [pair]
    if args.results:
        by_id = {str(item.get("pair_id")): item for item in load_persisted_pairs(args.pair_root)}
        by_id[pair["pair_id"]] = pair
        pairs = [by_id[key] for key in sorted(by_id)]
    document = build_shadow_document(
        pairs,
        results,
        source_manifest={
            "schema_version": _load_json(args.manifest).get("schema_version"),
            "selected_match_count": _load_json(args.manifest).get("selected_match_count"),
            "verified_match_count": _load_json(args.manifest).get("verified_match_count"),
        },
    )
    document_write = persist_document(document, args.output)
    print(json.dumps({
        "milestone": MILESTONE,
        "pair_status": pair["pair_status"],
        "pair_id": pair["pair_id"],
        "pair_path": str(persisted["path"]),
        "document_path": str(document_write["path"]),
        "verified_paired_count": document["evaluation"]["verified_paired_count"],
        "checkpoint": document["checkpoint"]["status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
