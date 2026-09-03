#!/usr/bin/env python3
"""Recover frozen recent-form competition provenance without network access.

This research-only audit answers the pre-registered
RECENT-FORM-COMPETITION-PROVENANCE-RECOVERY-1 question.  It selects the exact
61-match cohort accepted by PR #166, reconstructs the canonical frozen model
input from ``input.prematch_fundamentals.recent_form``, and recovers unresolved
competition labels only from raw cache files explicitly referenced and hashed
by the same immutable input snapshot.  The existing FRIENDLY_EXCLUDED route is
permitted only after the outcome-blind gate passes.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from risk_engine import dixon_coles_score_matrix  # noqa: E402


MILESTONE = "RECENT-FORM-COMPETITION-PROVENANCE-RECOVERY-1"
CHAMPION_MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
RESULT_SCOPE = "regulation_90m_plus_stoppage"
BOOTSTRAP_SEED = 20260903
DEFAULT_BOOTSTRAP_REPLICATES = 4000
MIN_EVALUABLE_UNIQUE_MATCHES = 50
MIN_UNIVERSE_SAMPLE = 20
COMPONENTS = ("home_overall", "home_home", "away_overall", "away_away")
VARIANTS = ("FRIENDLY_EXCLUDED",)
SCORE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")

DEFAULT_EVIDENCE_ROOT = PROJECT_ROOT / "data" / "prospective" / "football_evidence"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_PREDICTION_ROOT = PROJECT_ROOT / "data" / "model_governance" / "predictions"
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "model_governance" / "input_snapshots"
DEFAULT_RAW_CACHE_ROOT = PROJECT_ROOT / "data" / "source_cache" / "nowscore" / "raw"
DEFAULT_EXECUTION_LABEL = "LOCAL_WORKSPACE"

ACCEPTED_COHORT_REFERENCE = {
    "pull_request": 166,
    "accepted_head": "362ff0dffc55b0b7a2d6bc813a7f23e771f8cf7c",
    "workflow": 33763987132,
    "artifact": 9896705931,
}

UNIVERSES = (
    "CLUB_BIG5_TOP_LEAGUE",
    "CLUB_OTHER_TOP_LEAGUE",
    "CLUB_LOWER_DIVISION",
    "CLUB_DOMESTIC_CUP",
    "CLUB_CONTINENTAL",
    "NATIONAL_TEAM",
    "UNKNOWN_OR_MIXED",
)

METRICS = (
    "exact_score_nll",
    "actual_score_mean_probability",
    "top1_accuracy",
    "top3_accuracy",
    "top5_accuracy",
    "one_x_two_brier",
    "one_x_two_log_loss",
    "ou_2_5_brier",
    "btts_brier",
    "home_goal_mae",
    "home_goal_bias",
    "away_goal_mae",
    "away_goal_bias",
    "total_goal_mae",
    "total_goal_bias",
    "top1_score_concentration_mean_probability",
    "top1_score_1_1_share",
    "score_1_1_probability_mean",
)

FRIENDLY_LABELS = frozenset({"球会友谊", "球會友誼"})

# These are the exact target-match keys and latest legal prediction IDs from
# PR #166's accepted artifact.  Keeping the pair, rather than only the match
# key, makes a changed snapshot selection fail closed.
EXPECTED_COHORT = {
    "FBOS-202608290100-18dfb7e9df": "FBOS-PRED-29ca1a00ff0fe13524f785df",
    "FBOS-202608290200-18f3735b53": "FBOS-PRED-6356469b021735f0c90c63a9",
    "FBOS-202608290200-cc085d9cc6": "FBOS-PRED-9d40b18a6194f5a2531e65c0",
    "FBOS-202608290230-0a22a3adb3": "FBOS-PRED-1835155a06d6ac46365229bb",
    "FBOS-202608290245-86b5c937a4": "FBOS-PRED-100a195f3bab85ce63ae5a42",
    "FBOS-202608290300-a88bc3fa35": "FBOS-PRED-d26067b4233cdd2eab4859d4",
    "FBOS-202608290330-d9c7b7118b": "FBOS-PRED-76e5a3431bbf74a3d53c7ea9",
    "FBOS-202608291700-224436a36a": "FBOS-PRED-75ada2656cfdf6a7bb38ddd3",
    "FBOS-202608291730-a0da4dbd29": "FBOS-PRED-9aeed6e598fe0c0ff4b53c3d",
    "FBOS-202608291800-0d19f435b5": "FBOS-PRED-932af38398d671028664180d",
    "FBOS-202608291830-2be7b28f29": "FBOS-PRED-c4a3fece40743d093fb9c6b0",
    "FBOS-202608291900-2659c20476": "FBOS-PRED-a2e3a9bfe9715587694e263f",
    "FBOS-202608291930-816ff4b44c": "FBOS-PRED-458f4bae69655746a678f048",
    "FBOS-202608292100-21c3ea757c": "FBOS-PRED-7f17b789b2e465021486910d",
    "FBOS-202608292130-2e1f7626b7": "FBOS-PRED-4ac91d2297ef19285be2c8b6",
    "FBOS-202608292130-c460378ee5": "FBOS-PRED-6007c61ea0beae25bb4923a6",
    "FBOS-202608292200-3668cc2366": "FBOS-PRED-659dfab68989105b372e928c",
    "FBOS-202608292200-b9d591b2a3": "FBOS-PRED-fa8cc7ee304575ea5ca1aeb9",
    "FBOS-202608292300-b8036f9762": "FBOS-PRED-1925eef1d8dd3b9b223c774d",
    "FBOS-202608292315-e037b78b36": "FBOS-PRED-79b3e19629b90215c82aaf2a",
    "FBOS-202608300030-173996ba53": "FBOS-PRED-f1b08c6cf3d35fb87fb94ebd",
    "FBOS-202608300030-2332e71505": "FBOS-PRED-6b6a7541f0dc48cf98728518",
    "FBOS-202608300030-b284e94c16": "FBOS-PRED-83efcf5a2cf1a5dcaeb7b9b9",
    "FBOS-202608300030-ba773f40b9": "FBOS-PRED-109c72a59bb0d2055d08dcc8",
    "FBOS-202608300045-04a25a1ad9": "FBOS-PRED-f6cfe190b5b59a72af43f04f",
    "FBOS-202608300100-c1c6f9a466": "FBOS-PRED-be40d31f003f2bdc599e7dec",
    "FBOS-202608300100-d76acfaa2a": "FBOS-PRED-d6e0bc308b3eb657babbba15",
    "FBOS-202608300245-dd2d5dc45f": "FBOS-PRED-8d7a63a56a208d31ed99608a",
    "FBOS-202608300330-c7af399447": "FBOS-PRED-a4c062b5e02f18505888d08b",
    "FBOS-202608301815-e2551b7616": "FBOS-PRED-0fd5b9aa8f45489428d8f6ed",
    "FBOS-202608301830-61d5c05bf5": "FBOS-PRED-8e9061d436c52f9e6ba3037a",
    "FBOS-202608301830-b076c9a937": "FBOS-PRED-9721b5cb0abf35e89d6e3bb1",
    "FBOS-202608301930-f13be44452": "FBOS-PRED-23a8eb91a722c27d4c49156d",
    "FBOS-202608302000-a4e915a22d": "FBOS-PRED-e9236e68303e30d273eaa0a4",
    "FBOS-202608302030-56608cd4cb": "FBOS-PRED-7d4e781213bc0befe198ff55",
    "FBOS-202608302030-e7ed2bd3e5": "FBOS-PRED-ef01ae6e2c68abc4ee68ab74",
    "FBOS-202608302100-33647ada3d": "FBOS-PRED-aec30f0631825990c24ea13f",
    "FBOS-202608302100-4bbe7e7593": "FBOS-PRED-0e1f99f864c52ff8f4eb6a6b",
    "FBOS-202608302100-9045b65c0e": "FBOS-PRED-4cc93f102424851bedcaae3d",
    "FBOS-202608302245-937c28f3f7": "FBOS-PRED-26b3174ce319c737f4fe95a4",
    "FBOS-202608302300-f7c819b9a7": "FBOS-PRED-060a3afbd4341009b31b1f81",
    "FBOS-202608302330-3488780e79": "FBOS-PRED-2a5c7b58dd47931bf74395b9",
    "FBOS-202608302330-f1c8cc9a15": "FBOS-PRED-18e2f803160bcbcf316415f5",
    "FBOS-202608310030-d4e3b34791": "FBOS-PRED-3147dc7bbd78154b16f3bd97",
    "FBOS-202608310130-3ece2285eb": "FBOS-PRED-1aec165d8cae61f3fb948341",
    "FBOS-202608310200-45c20faf16": "FBOS-PRED-c9fc32dfc87e08752b2bf28b",
    "FBOS-202608310245-9bf0da2c06": "FBOS-PRED-c3d747d6e7e0e440d65922d6",
    "FBOS-202608310245-c3f8734cde": "FBOS-PRED-7a64511f62654d1674ecccef",
    "FBOS-202608310245-efe897a8e6": "FBOS-PRED-998262c8f3c9e18e1722d65d",
    "FBOS-202608310300-910132c529": "FBOS-PRED-a8f4f5367a82333e550333ae",
    "FBOS-202608310330-ebf8ea8163": "FBOS-PRED-12b267759ba68ff17682085a",
    "FBOS-202608310700-1a4ca05d83": "FBOS-PRED-b594cc699e8bc3089393b9c3",
    "FBOS-202609010030-aa50d55edc": "FBOS-PRED-296eeedb5b9cb00b69b00f82",
    "FBOS-202609010100-28f0df8c97": "FBOS-PRED-1fd0c0b6cfe1fb8e3574080e",
    "FBOS-202609010245-1c07512e55": "FBOS-PRED-6ab3e5708c77bdbd763edd7a",
    "FBOS-202609010245-203b078189": "FBOS-PRED-1cdfb7883be4657e99869c80",
    "FBOS-202609010300-7c61d91bce": "FBOS-PRED-d66464c9e8aeb1c8fdb75ba6",
    "FBOS-202609010315-4d787db3f3": "FBOS-PRED-00227eca095ca2bf0bc19ada",
    "FBOS-202609010315-6cd2253355": "FBOS-PRED-5c5c2abe5a15e6bb015bb59c",
    "FBOS-202609010330-d316e7142d": "FBOS-PRED-2821898be64dcfef85e96831",
    "FBOS-202609030630-b950ece651": "FBOS-PRED-d2a589ffd78cacff001507ba",
}

BIG5_LABELS = frozenset({"英超", "西甲", "意甲", "德甲", "法甲"})
OTHER_TOP_LABELS = frozenset(
    {
        "荷甲",
        "瑞典超",
        "日職聯",
        "葡超",
        "挪超",
        "巴西甲",
        "美職業",
        "韓K聯",
    }
)
LOWER_LABELS = frozenset(
    {"英冠", "西乙", "意乙", "德乙", "法乙", "法丙", "荷乙", "日職乙", "韓K2聯"}
)
CUP_LABELS = frozenset(
    {
        "巴西盃",
        "德國盃",
        "德超盃",
        "德電信盃",
        "意盃",
        "意超盃",
        "挪威盃",
        "日皇盃",
        "日聯盃",
        "瑞典盃",
        "甘伯盃",
        "美公開賽",
        "英社盾",
        "英聯盃",
        "英足總盃",
        "荷蘭盃",
        "葡盃",
        "葡聯盃",
        "葡超盃",
        "西盃",
        "歐超杯",
        "法國盃",
        "法超盃",
        "韓K盃",
        "韓國盃",
    }
)
CONTINENTAL_LABELS = frozenset(
    {"亞洲冠精英", "南美盃", "歐冠盃", "歐協聯", "歐霸盃", "解放者盃"}
)
NATIONAL_LABELS = frozenset(
    {
        "中北美杯",
        "大西洋杯",
        "國際友誼賽",
        "世界盃",
        "世界盃預選賽",
        "亞洲杯",
        "歐洲杯",
        "歐洲國家聯賽",
        "美洲杯",
        "非洲杯",
        "酋長盃",
    }
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raw = _text(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%y-%m-%d", "%Y/%m/%d", "%y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_panlu_date(value: Any) -> date | None:
    raw = _text(value)
    if not raw:
        return None
    for fmt in (
        "%y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M",
        "%y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%y-%m-%d",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return _parse_date(raw)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value.strip())
    return None


def _parse_score(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    match = SCORE_RE.fullmatch(str(value).strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _is_after(later: datetime | None, earlier: datetime | None) -> bool:
    if later is None or earlier is None:
        return False
    try:
        return later > earlier
    except TypeError:
        return False


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(seed) + int(digest[:8], 16)


def _normalise_id(value: Any) -> str:
    return _text(value)


def _normalise_competition(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).replace(" ", "")


def is_club_friendly(competition: str | None) -> bool:
    return _normalise_competition(competition) in {
        _normalise_competition(label) for label in FRIENDLY_LABELS
    }


def classify_competition(competition: str | None) -> str:
    label = _normalise_competition(competition)
    if not label or is_club_friendly(label):
        return "UNKNOWN_OR_MIXED"
    if label in BIG5_LABELS:
        return "CLUB_BIG5_TOP_LEAGUE"
    if label in OTHER_TOP_LABELS:
        return "CLUB_OTHER_TOP_LEAGUE"
    if label in LOWER_LABELS:
        return "CLUB_LOWER_DIVISION"
    if label in CUP_LABELS:
        return "CLUB_DOMESTIC_CUP"
    if label in CONTINENTAL_LABELS:
        return "CLUB_CONTINENTAL"
    if label in NATIONAL_LABELS:
        return "NATIONAL_TEAM"
    return "UNKNOWN_OR_MIXED"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _infer_subject_team_id(rows: Iterable[dict[str, Any]]) -> tuple[str | None, float]:
    counts: Counter[str] = Counter()
    valid_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        valid_count += 1
        for key in ("home_team_id", "away_team_id"):
            team_id = _normalise_id(row.get(key))
            if team_id:
                counts[team_id] += 1
    if not counts or not valid_count:
        return None, 0.0
    subject, count = counts.most_common(1)[0]
    return subject, count / valid_count


def _valid_history_row(row: Any, kickoff: datetime | None) -> bool:
    if not isinstance(row, dict):
        return False
    row_date = _parse_date(row.get("match_date"))
    home_id = _normalise_id(row.get("home_team_id"))
    away_id = _normalise_id(row.get("away_team_id"))
    home_goals = _nonnegative_int(row.get("home_goals"))
    away_goals = _nonnegative_int(row.get("away_goals"))
    return bool(
        row_date
        and kickoff
        and row_date < kickoff.date()
        and home_id
        and away_id
        and home_id != away_id
        and home_goals is not None
        and away_goals is not None
    )


def _evidence_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    kickoff = _parse_datetime(payload.get("kickoff_at"))
    captured = _parse_datetime(payload.get("evidence_captured_at"))
    cutoff = _parse_datetime(payload.get("source_cutoff_at"))
    reasons: list[str] = []
    if kickoff is None:
        reasons.append("INVALID_KICKOFF")
    if captured is None:
        reasons.append("INVALID_EVIDENCE_CAPTURE_TIME")
    elif kickoff is not None and captured >= kickoff:
        reasons.append("EVIDENCE_NOT_PREMATCH")
    if cutoff is None:
        reasons.append("INVALID_SOURCE_CUTOFF")
    elif kickoff is not None and cutoff >= kickoff:
        reasons.append("SOURCE_CUTOFF_NOT_PREMATCH")
    if not _text(payload.get("match_key")):
        reasons.append("MISSING_MATCH_KEY")

    recent = payload.get("recent_matches")
    recent = recent if isinstance(recent, dict) else {}
    home_rows = (
        recent.get("home_team") if isinstance(recent.get("home_team"), list) else []
    )
    away_rows = (
        recent.get("away_team") if isinstance(recent.get("away_team"), list) else []
    )
    home_valid = [row for row in home_rows if _valid_history_row(row, kickoff)]
    away_valid = [row for row in away_rows if _valid_history_row(row, kickoff)]
    if len(home_valid) < 10:
        reasons.append("HOME_HISTORY_TOO_SHORT")
    if len(away_valid) < 10:
        reasons.append("AWAY_HISTORY_TOO_SHORT")
    home_id, home_share = _infer_subject_team_id(home_valid)
    away_id, away_share = _infer_subject_team_id(away_valid)
    if home_id is None or home_share < 0.8:
        reasons.append("HOME_TEAM_IDENTITY_UNSTABLE")
    if away_id is None or away_share < 0.8:
        reasons.append("AWAY_TEAM_IDENTITY_UNSTABLE")
    if home_id and away_id and home_id == away_id:
        reasons.append("HOME_AWAY_IDENTITY_COLLISION")
    return {
        "usable": not reasons,
        "reasons": reasons,
        "kickoff": kickoff,
        "captured": captured,
        "home_rows": home_valid,
        "away_rows": away_valid,
        "home_subject_team_id": home_id,
        "away_subject_team_id": away_id,
        "home_identity_share": home_share,
        "away_identity_share": away_share,
    }


def _load_evidence(
    evidence_root: Path,
) -> tuple[dict[str, dict[str, Any]], int, Counter[str]]:
    records: dict[str, dict[str, Any]] = {}
    failures: Counter[str] = Counter()
    paths = sorted(evidence_root.glob("*.json"))
    for path in paths:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            failures["INVALID_EVIDENCE_JSON_OR_OBJECT"] += 1
            continue
        prediction_id = _text(payload.get("prediction_id"))
        if not prediction_id:
            failures["MISSING_PREDICTION_ID"] += 1
            continue
        if prediction_id in records:
            failures["DUPLICATE_PREDICTION_ID"] += 1
            continue
        status = _evidence_integrity(payload)
        for reason in status["reasons"]:
            failures[reason] += 1
        records[prediction_id] = {
            "path": _display_path(path),
            "payload": payload,
            "prediction_id": prediction_id,
            "match_key": _text(payload.get("match_key")),
            "match_id": _normalise_id(payload.get("match_id")),
            "kickoff": status["kickoff"],
            "captured": status["captured"],
            "usable": status["usable"],
            **status,
        }
    return records, len(paths), failures


def _resolve_snapshot_ref(ref: Any, snapshot_root: Path) -> Path:
    raw = _text(ref).replace("\\", "/")
    if not raw or Path(raw).is_absolute():
        raise ValueError("INVALID_INPUT_SNAPSHOT_REF")
    path = (PROJECT_ROOT / raw).resolve()
    root = snapshot_root.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("INPUT_SNAPSHOT_OUTSIDE_ALLOWED_ROOT") from exc
    return path


def _load_frozen_prediction(
    prediction_root: Path,
    snapshot_root: Path,
    prediction_id: str,
    match_key: str,
    evidence_kickoff: datetime,
    evidence_match_id: str,
) -> dict[str, Any]:
    path = prediction_root / f"{prediction_id}.json"
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"MISSING_OR_INVALID_FROZEN_PREDICTION:{prediction_id}")
    if _text(payload.get("prediction_id")) != prediction_id:
        raise ValueError(f"FROZEN_PREDICTION_ID_MISMATCH:{prediction_id}")
    if _text(payload.get("match_key")) != match_key:
        raise ValueError(f"FROZEN_PREDICTION_MATCH_KEY_MISMATCH:{prediction_id}")
    if evidence_match_id and _normalise_id(payload.get("match_id")) != evidence_match_id:
        raise ValueError(f"FROZEN_PREDICTION_MATCH_ID_MISMATCH:{prediction_id}")
    if payload.get("model_role") != "champion":
        raise ValueError(f"PREDICTION_NOT_CHAMPION:{prediction_id}")
    if payload.get("model_family") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"UNEXPECTED_MODEL_FAMILY:{prediction_id}")
    if payload.get("model_core_version") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"UNEXPECTED_MODEL_CORE_VERSION:{prediction_id}")
    if payload.get("prediction_status") != "formal":
        raise ValueError(f"PREDICTION_NOT_FORMAL:{prediction_id}")
    if payload.get("formal_eligible") is not True or payload.get("model_formal_eligible") is not True:
        raise ValueError(f"PREDICTION_NOT_FORMAL_ELIGIBLE:{prediction_id}")

    prediction_kickoff = _parse_datetime(payload.get("kickoff_at"))
    if prediction_kickoff is not None and prediction_kickoff != evidence_kickoff:
        raise ValueError(f"FROZEN_PREDICTION_KICKOFF_MISMATCH:{prediction_id}")
    lambda_home = _finite(payload.get("lambda_home"))
    lambda_away = _finite(payload.get("lambda_away"))
    rho = _finite(payload.get("rho"))
    if lambda_home is None or lambda_away is None or lambda_home <= 0 or lambda_away <= 0:
        raise ValueError(f"FROZEN_PREDICTION_LAMBDAS_INVALID:{prediction_id}")
    if rho is None:
        raise ValueError(f"FROZEN_PREDICTION_RHO_INVALID:{prediction_id}")

    snapshot_ref = _text(payload.get("input_snapshot_ref"))
    snapshot_path = _resolve_snapshot_ref(snapshot_ref, snapshot_root)
    snapshot = _load_json(snapshot_path)
    if not isinstance(snapshot, dict):
        raise ValueError(f"MISSING_OR_INVALID_INPUT_SNAPSHOT:{prediction_id}")
    if _text(snapshot.get("snapshot_ref")).replace("\\", "/") != snapshot_ref.replace("\\", "/"):
        raise ValueError(f"INPUT_SNAPSHOT_REF_MISMATCH:{prediction_id}")
    input_payload = snapshot.get("input")
    if not isinstance(input_payload, dict):
        raise ValueError(f"INPUT_SNAPSHOT_INPUT_MISSING:{prediction_id}")
    prematch_fundamentals = input_payload.get("prematch_fundamentals")
    canonical_recent_form = (
        prematch_fundamentals.get("recent_form")
        if isinstance(prematch_fundamentals, dict)
        else None
    )
    if not isinstance(canonical_recent_form, dict):
        raise ValueError(f"CANONICAL_RECENT_FORM_MISSING:{prediction_id}")
    source_snapshots = input_payload.get("source_snapshots")
    nowscore = source_snapshots.get("nowscore") if isinstance(source_snapshots, dict) else None
    snapshots = nowscore.get("snapshots") if isinstance(nowscore, dict) else None
    if not isinstance(snapshots, list) or len(snapshots) != 1 or not isinstance(snapshots[0], dict):
        raise ValueError(f"NOWSCORE_SNAPSHOT_SHAPE_INVALID:{prediction_id}")
    nowscore_snapshot = snapshots[0]
    context = nowscore_snapshot.get("nowscore_context")
    panlu = context.get("panlu") if isinstance(context, dict) else None
    panlu_matches = panlu.get("matches") if isinstance(panlu, dict) else None
    panlu_status = "VALID" if isinstance(panlu_matches, list) else "MISSING_OR_INVALID"
    panlu_matches = panlu_matches if isinstance(panlu_matches, list) else []
    legacy_recent_form = (
        (nowscore_snapshot.get("shuju") or {}).get("recent_form")
        if isinstance(nowscore_snapshot.get("shuju"), dict)
        else None
    )
    source_refs = snapshot.get("source_refs")
    source_refs = source_refs if isinstance(source_refs, list) else []
    source_hashes = snapshot.get("source_hashes")
    source_hashes = source_hashes if isinstance(source_hashes, dict) else {}
    return {
        "path": _display_path(path),
        "prediction_id": prediction_id,
        "match_key": match_key,
        "match_id": evidence_match_id or _normalise_id(payload.get("match_id")),
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "rho": rho,
        "model_family": payload.get("model_family"),
        "model_role": payload.get("model_role"),
        "prediction_status": payload.get("prediction_status"),
        "formal_eligible": payload.get("formal_eligible"),
        "input_snapshot_ref": snapshot_ref,
        "input_snapshot_id": snapshot.get("snapshot_id"),
        "nowscore_snapshot": nowscore_snapshot,
        "panlu_matches": panlu_matches,
        "panlu_status": panlu_status,
        "canonical_recent_form": canonical_recent_form,
        "canonical_form_source": (
            prematch_fundamentals.get("form_source")
            if isinstance(prematch_fundamentals, dict)
            else None
        ),
        "legacy_recent_form": legacy_recent_form,
        "source_refs": [str(ref) for ref in source_refs if isinstance(ref, str)],
        "source_hashes": {
            str(ref): value for ref, value in source_hashes.items() if isinstance(ref, str)
        },
    }


def _subject_history(
    rows: list[dict[str, Any]],
    *,
    subject_id: str | None,
    target_kickoff: datetime,
    side_label: str,
) -> list[dict[str, Any]]:
    if not subject_id:
        raise ValueError(f"{side_label.upper()}_SUBJECT_TEAM_ID_UNAVAILABLE")
    output: list[dict[str, Any]] = []
    for source_index, row in enumerate(rows):
        home_id = _normalise_id(row.get("home_team_id"))
        away_id = _normalise_id(row.get("away_team_id"))
        row_date = _parse_date(row.get("match_date"))
        home_goals = _nonnegative_int(row.get("home_goals"))
        away_goals = _nonnegative_int(row.get("away_goals"))
        if subject_id not in {home_id, away_id} or home_id == away_id:
            raise ValueError(f"{side_label.upper()}_HISTORY_SUBJECT_ID_CONFLICT")
        if row_date is None or home_goals is None or away_goals is None:
            raise ValueError(f"{side_label.upper()}_HISTORY_ROW_INVALID")
        if row_date >= target_kickoff.date():
            raise ValueError(f"{side_label.upper()}_HISTORY_NOT_PREMATCH")
        subject_is_home = home_id == subject_id
        output.append(
            {
                "match_date": row_date.isoformat(),
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "goals_for": home_goals if subject_is_home else away_goals,
                "goals_against": away_goals if subject_is_home else home_goals,
                "subject_is_home": subject_is_home,
                "source_index": source_index,
            }
        )
    output.sort(key=lambda row: (row["match_date"], -row["source_index"]), reverse=True)
    return output


def _component_windows(
    home_history: list[dict[str, Any]], away_history: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    home_home = [row for row in home_history if row["subject_is_home"]]
    away_away = [row for row in away_history if not row["subject_is_home"]]
    windows = {
        "home_overall": home_history[:10],
        "home_home": home_home[:10],
        "away_overall": away_history[:10],
        "away_away": away_away[:10],
    }
    for component, rows in windows.items():
        if len(rows) != 10:
            raise ValueError(f"{component.upper()}_HISTORY_TOO_SHORT")
    return windows


def _component_aggregate(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "matches": len(rows),
        "goals_for": sum(int(row["goals_for"]) for row in rows),
        "goals_against": sum(int(row["goals_against"]) for row in rows),
    }


def _form_anatomy(form: Mapping[str, Any]) -> dict[str, float | None]:
    def rate(component: Any, field: str) -> float | None:
        if not isinstance(component, dict):
            return None
        count = _nonnegative_int(component.get("matches"))
        value = _finite(component.get(field))
        if count is None or count <= 0 or value is None:
            return None
        result = value / count
        return result if math.isfinite(result) else None

    home_overall = form.get("home_overall")
    home_home = form.get("home_home")
    away_overall = form.get("away_overall")
    away_away = form.get("away_away")
    home_venue = _mean_or_none(
        [rate(home_home, "goals_for"), rate(away_away, "goals_against")]
    )
    away_venue = _mean_or_none(
        [rate(away_away, "goals_for"), rate(home_home, "goals_against")]
    )
    home_general = _mean_or_none(
        [rate(home_overall, "goals_for"), rate(away_overall, "goals_against")]
    )
    away_general = _mean_or_none(
        [rate(away_overall, "goals_for"), rate(home_overall, "goals_against")]
    )
    home_form = _mean_or_none([home_venue, home_venue, home_general])
    away_form = _mean_or_none([away_venue, away_venue, away_general])
    return {
        "home_venue": home_venue,
        "away_venue": away_venue,
        "home_general": home_general,
        "away_general": away_general,
        "home_form": home_form,
        "away_form": away_form,
        "form_total": (
            home_form + away_form
            if home_form is not None and away_form is not None
            else None
        ),
    }


def _mean_or_none(values: Iterable[float | None]) -> float | None:
    clean: list[float] = []
    for value in values:
        number = _finite(value)
        if number is not None:
            clean.append(number)
    return fmean(clean) if clean else None


def _reconstruct_recent_form(
    windows: Mapping[str, list[dict[str, Any]]], frozen_form: Any
) -> dict[str, Any]:
    reconstructed = {component: _component_aggregate(windows[component]) for component in COMPONENTS}
    mismatches: list[dict[str, Any]] = []
    if not isinstance(frozen_form, dict):
        mismatches.append(
            {
                "component": None,
                "reason": "FROZEN_RECENT_FORM_MISSING",
            }
        )
        return {
            "exact": False,
            "reconstructed": reconstructed,
            "frozen": None,
            "mismatches": mismatches,
            "reconstructed_anatomy": _form_anatomy(reconstructed),
            "frozen_anatomy": None,
        }
    for component in COMPONENTS:
        expected = frozen_form.get(component)
        if not isinstance(expected, dict):
            mismatches.append(
                {"component": component, "reason": "FROZEN_COMPONENT_MISSING"}
            )
            continue
        actual = reconstructed[component]
        component_mismatch = {
            key: {"reconstructed": actual[key], "frozen": expected.get(key)}
            for key in ("matches", "goals_for", "goals_against")
            if _nonnegative_int(expected.get(key)) != actual[key]
        }
        if component_mismatch:
            mismatches.append(
                {
                    "component": component,
                    "reason": "FROZEN_COMPONENT_MISMATCH",
                    "fields": component_mismatch,
                }
            )
    frozen_normalized = {
        component: {
            key: _nonnegative_int((frozen_form.get(component) or {}).get(key))
            for key in ("matches", "goals_for", "goals_against")
        }
        for component in COMPONENTS
        if isinstance(frozen_form.get(component), dict)
    }
    return {
        "exact": not mismatches and set(frozen_normalized) == set(COMPONENTS),
        "reconstructed": reconstructed,
        "frozen": frozen_normalized,
        "mismatches": mismatches,
        "reconstructed_anatomy": _form_anatomy(reconstructed),
        "frozen_anatomy": _form_anatomy(frozen_form),
    }


def _panlu_key(
    home_team_id: Any,
    away_team_id: Any,
    match_date: Any,
    home_goals: Any,
    away_goals: Any,
) -> tuple[str, str, str, int, int] | None:
    parsed_date = _parse_date(match_date)
    home_score = _nonnegative_int(home_goals)
    away_score = _nonnegative_int(away_goals)
    home_id = _normalise_id(home_team_id)
    away_id = _normalise_id(away_team_id)
    if not parsed_date or not home_id or not away_id:
        return None
    if home_score is None or away_score is None:
        return None
    return home_id, away_id, parsed_date.isoformat(), home_score, away_score


def _build_panlu_index(
    panlu_matches: list[Any],
) -> tuple[dict[tuple[str, str, str, int, int], list[dict[str, Any]]], Counter[str]]:
    index: dict[tuple[str, str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    failures: Counter[str] = Counter()
    for source_index, row in enumerate(panlu_matches):
        if not isinstance(row, dict):
            failures["INVALID_PANLU_ROW"] += 1
            continue
        full_time = row.get("full_time")
        if not isinstance(full_time, dict):
            failures["PANLU_FULL_TIME_MISSING"] += 1
            continue
        key = _panlu_key(
            row.get("home_team_id"),
            row.get("away_team_id"),
            _parse_panlu_date(row.get("kickoff")),
            full_time.get("home"),
            full_time.get("away"),
        )
        if key is None:
            failures["PANLU_JOIN_KEY_INVALID"] += 1
            continue
        index[key].append(
            {
                "source_index": source_index,
                "match_id": _normalise_id(row.get("match_id")),
                "competition": _text(row.get("competition")),
                "key": key,
            }
        )
    return index, failures


def _literal_js_array(text: str, name: str) -> list[Any]:
    """Read one literal array from the frozen Nowscore analysis JavaScript."""
    found = re.search(
        rf"(?:var\s+)?{re.escape(name)}\s*=\s*(\[.*?\]);",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not found:
        return []
    try:
        value = ast.literal_eval(found.group(1))
    except (SyntaxError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _raw_analysis_competition_index(
    text: str,
    *,
    source_ref: str,
) -> tuple[
    dict[tuple[str, str, str, int, int], list[dict[str, Any]]],
    dict[str, Any],
]:
    """Parse only IDs, date, 90m score and explicit sclass mapping from raw JS.

    Team names, league tokens and page text are deliberately ignored.  The
    parser is literal-only so a raw cache file cannot introduce a guessed
    competition label.
    """
    class_rows = _literal_js_array(text, "sclassNames")
    competition_by_id: dict[str, str] = {}
    for row in class_rows:
        if not isinstance(row, dict):
            continue
        class_id = _normalise_id(
            row.get("SclassId")
            if row.get("SclassId") is not None
            else row.get("sclass_id")
            if row.get("sclass_id") is not None
            else row.get("id")
        )
        label = _text(
            row.get("cn")
            or row.get("name")
            or row.get("sclassName")
            or row.get("big")
        )
        if class_id and label:
            competition_by_id[class_id] = label

    index: dict[tuple[str, str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    invalid_rows = 0
    unlabeled_rows = 0
    parsed_rows = 0
    seen: set[tuple[tuple[str, str, str, int, int], str]] = set()
    arrays_found = 0
    for array_name in ("h_data", "a_data"):
        rows = _literal_js_array(text, array_name)
        if re.search(
            rf"(?:var\s+)?{re.escape(array_name)}\s*=\s*\[",
            text,
            re.IGNORECASE,
        ):
            arrays_found += 1
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) < 10:
                invalid_rows += 1
                continue
            key = _panlu_key(row[4], row[6], row[0], row[8], row[9])
            if key is None:
                invalid_rows += 1
                continue
            competition = competition_by_id.get(_normalise_id(row[1]))
            if not competition:
                unlabeled_rows += 1
                continue
            dedupe_key = (key, _normalise_competition(competition))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            parsed_rows += 1
            index[key].append(
                {
                    "source_ref": source_ref,
                    "source_index": row_index,
                    "source_array": array_name,
                    "competition": competition,
                    "key": key,
                }
            )
    evidence = {
        "parser": "literal_js_arrays:h_data,a_data,sclassNames; IDs/date/full-time-score only",
        "source_ref": source_ref,
        "status": "PARSED" if arrays_found == 2 and parsed_rows else "PARSE_INCOMPLETE",
        "arrays_found": arrays_found,
        "class_mapping_count": len(competition_by_id),
        "parsed_rows": parsed_rows,
        "invalid_rows": invalid_rows,
        "unlabeled_rows": unlabeled_rows,
    }
    return index, evidence


def _source_hash_for(source_hashes: Mapping[str, Any], source_ref: str) -> str | None:
    normalized = source_ref.replace("\\", "/")
    for key, value in source_hashes.items():
        if str(key).replace("\\", "/") == normalized:
            return _text(value) or None
    return None


def _raw_cache_evidence(
    frozen: Mapping[str, Any],
    *,
    raw_cache_root: Path,
) -> tuple[
    dict[tuple[str, str, str, int, int], list[dict[str, Any]]],
    dict[str, Any],
]:
    """Verify referenced local raw files and parse only hash-valid analysis JS."""
    root = raw_cache_root.resolve()
    raw_prefix = "data/source_cache/nowscore/raw/"
    references: list[dict[str, Any]] = []
    raw_index: dict[tuple[str, str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    parsed_files = 0
    for source_ref in frozen.get("source_refs", []):
        normalized_ref = str(source_ref).replace("\\", "/")
        if not normalized_ref.startswith(raw_prefix):
            continue
        relative_ref = normalized_ref[len(raw_prefix) :]
        if not relative_ref or Path(relative_ref).is_absolute():
            continue
        candidate = (root / Path(relative_ref)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        filename = candidate.name
        recorded_hash = _source_hash_for(frozen.get("source_hashes", {}), normalized_ref)
        present = candidate.is_file()
        computed_hash = (
            hashlib.sha256(candidate.read_bytes()).hexdigest() if present else None
        )
        hash_valid = bool(
            present
            and recorded_hash
            and re.fullmatch(r"[0-9a-fA-F]{64}", recorded_hash)
            and computed_hash == recorded_hash.lower()
        )
        status = (
            "HASH_VALID"
            if hash_valid
            else "MISSING"
            if not present
            else "HASH_MISSING"
            if not recorded_hash
            else "HASH_MISMATCH"
        )
        parser_evidence: dict[str, Any] | None = None
        if hash_valid and filename.endswith("_analysis.js"):
            try:
                raw_text = candidate.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                status = "READ_ERROR"
                parser_evidence = {
                    "parser": "literal_js_arrays:h_data,a_data,sclassNames; IDs/date/full-time-score only",
                    "status": "READ_ERROR",
                    "error": type(exc).__name__,
                }
            else:
                parsed_index, parser_evidence = _raw_analysis_competition_index(
                    raw_text,
                    source_ref=normalized_ref,
                )
                if parser_evidence["status"] == "PARSED":
                    parsed_files += 1
                    for key, rows in parsed_index.items():
                        raw_index[key].extend(rows)
                else:
                    status = "PARSE_INCOMPLETE"
        references.append(
            {
                "source_ref": normalized_ref,
                "local_path": str(candidate),
                "recorded_sha256": recorded_hash,
                "computed_sha256": computed_hash,
                "is_analysis_js": filename.endswith("_analysis.js"),
                "present": present,
                "hash_valid": hash_valid,
                "status": status,
                "parser": parser_evidence,
            }
        )
    analysis_references = [row for row in references if row["is_analysis_js"]]
    return raw_index, {
        "root": str(root),
        "references": references,
        "referenced_count": len(references),
        "analysis_referenced_count": len(analysis_references),
        "present_count": sum(row["present"] for row in references),
        "analysis_present_count": sum(row["present"] for row in analysis_references),
        "hash_valid_count": sum(row["hash_valid"] for row in references),
        "analysis_hash_valid_count": sum(row["hash_valid"] for row in analysis_references),
        "parsed_analysis_file_count": parsed_files,
        "parser": "literal_js_arrays:h_data,a_data,sclassNames; IDs/date/full-time-score only",
    }


def _distinct_competitions(candidates: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        _normalise_competition(candidate.get("competition"))
        for candidate in candidates
        if _normalise_competition(candidate.get("competition"))
    }


def _join_from_index(
    history_row: Mapping[str, Any],
    index: Mapping[tuple[str, str, str, int, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    key = _panlu_key(
        history_row.get("home_team_id"),
        history_row.get("away_team_id"),
        history_row.get("match_date"),
        history_row.get("home_goals"),
        history_row.get("away_goals"),
    )
    candidates = list(index.get(key, [])) if key is not None else []
    if len(candidates) != 1:
        return {
            "status": "AMBIGUOUS" if len(candidates) > 1 else "UNRESOLVED",
            "reason": (
                "COMPETITION_LABEL_AMBIGUOUS"
                if len(candidates) > 1
                else "COMPETITION_LABEL_UNRESOLVED"
            ),
            "key": list(key) if key is not None else None,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
    candidate = candidates[0]
    competition = _text(candidate.get("competition"))
    if not competition:
        return {
            "status": "UNRESOLVED",
            "reason": "COMPETITION_LABEL_UNRESOLVED",
            "key": list(key) if key is not None else None,
            "candidate_count": 1,
            "candidates": candidates,
        }
    return {
        "status": "JOINED",
        "reason": None,
        "key": list(key) if key is not None else None,
        "candidate_count": 1,
        "match_id": candidate.get("match_id"),
        "competition": competition,
        "competition_normalized": _normalise_competition(competition),
        "is_club_friendly": is_club_friendly(competition),
        "universe": classify_competition(competition),
        "candidate": candidate,
    }


def _join_competition(
    history_row: Mapping[str, Any],
    panlu_index: Mapping[tuple[str, str, str, int, int], list[dict[str, Any]]],
    raw_index: Mapping[tuple[str, str, str, int, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    panlu_join = _join_from_index(history_row, panlu_index)
    raw_join = _join_from_index(history_row, raw_index or {})
    raw_labels = _distinct_competitions(raw_join.get("candidates", []))
    if panlu_join["status"] == "AMBIGUOUS":
        panlu_join["provenance_source"] = "PANLU"
        panlu_join["raw_status"] = raw_join["status"]
        panlu_join["raw_candidates"] = raw_join.get("candidates", [])
        return panlu_join
    if panlu_join["status"] == "JOINED":
        if raw_join["status"] == "JOINED":
            if _normalise_competition(panlu_join["competition"]) != _normalise_competition(
                raw_join["competition"]
            ):
                return {
                    **panlu_join,
                    "status": "CONFLICT",
                    "reason": "COMPETITION_LABEL_CONFLICT",
                    "provenance_source": "PANLU_AND_RAW_CACHE_CONFLICT",
                    "raw_competition": raw_join.get("competition"),
                    "raw_candidates": raw_join.get("candidates", []),
                }
        elif raw_labels and _normalise_competition(panlu_join["competition"]) not in raw_labels:
            return {
                **panlu_join,
                "status": "CONFLICT",
                "reason": "COMPETITION_LABEL_CONFLICT",
                "provenance_source": "PANLU_AND_RAW_CACHE_CONFLICT",
                "raw_candidates": raw_join.get("candidates", []),
            }
        panlu_join["provenance_source"] = "PANLU"
        panlu_join["raw_status"] = raw_join["status"]
        panlu_join["raw_candidates"] = raw_join.get("candidates", [])
        return panlu_join
    if raw_join["status"] == "JOINED":
        raw_join["provenance_source"] = "RAW_CACHE"
        raw_join["raw_status"] = "JOINED"
        raw_join["panlu_status"] = panlu_join["status"]
        raw_join["panlu_candidates"] = panlu_join.get("candidates", [])
        return raw_join
    if raw_join["status"] == "AMBIGUOUS":
        raw_join["provenance_source"] = "RAW_CACHE"
        raw_join["panlu_status"] = panlu_join["status"]
        raw_join["panlu_candidates"] = panlu_join.get("candidates", [])
        return raw_join
    panlu_join["provenance_source"] = "UNRESOLVED"
    panlu_join["raw_status"] = raw_join["status"]
    panlu_join["raw_candidates"] = raw_join.get("candidates", [])
    return panlu_join


def _row_public(
    component: str, index: int, row: Mapping[str, Any], join: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "component": component,
        "window_index": index,
        "match_date": row.get("match_date"),
        "home_team_id": row.get("home_team_id"),
        "away_team_id": row.get("away_team_id"),
        "home_goals": row.get("home_goals"),
        "away_goals": row.get("away_goals"),
        "goals_for": row.get("goals_for"),
        "goals_against": row.get("goals_against"),
        "subject_is_home": row.get("subject_is_home"),
        "competition_join": dict(join),
    }


def _filtered_component(
    rows: list[dict[str, Any]], *, component: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    remaining = [
        row
        for row in rows
        if row.get("_join", {}).get("status") == "JOINED"
        and not row.get("_join", {}).get("is_club_friendly", False)
    ]
    goals_for = sum(int(row["goals_for"]) for row in remaining)
    goals_against = sum(int(row["goals_against"]) for row in remaining)
    count = len(remaining)
    return (
        {
            "component": component,
            "original_matches": len(rows),
            "remaining_matches": count,
            "excluded_friendly_matches": len(rows) - count,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "goals_for_rate": goals_for / count if count else None,
            "goals_against_rate": goals_against / count if count else None,
            "no_backfill": True,
        },
        remaining,
    )


def _rate(summary: Mapping[str, Any], field: str) -> float | None:
    value = summary.get(field)
    return _finite(value)


def _compute_outcome_blind_eligibility(
    windows: Mapping[str, list[dict[str, Any]]],
    reconstruction: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if not reconstruction.get("exact"):
        reasons.append("RECONSTRUCTION_MISMATCH")
    filtered_components: dict[str, dict[str, Any]] = {}
    filtered_rows: dict[str, list[dict[str, Any]]] = {}
    for component in COMPONENTS:
        summary, rows = _filtered_component(windows[component], component=component)
        filtered_components[component] = summary
        filtered_rows[component] = rows

    for component in ("home_overall", "away_overall"):
        if filtered_components[component]["remaining_matches"] < 3:
            reasons.append(f"{component.upper()}_FILTERED_HISTORY_BELOW_3")

    home_venue_fallback = filtered_components["home_home"]["remaining_matches"] < 3
    away_venue_fallback = filtered_components["away_away"]["remaining_matches"] < 3
    home_venue_source = "home_overall" if home_venue_fallback else "home_home"
    away_venue_source = "away_overall" if away_venue_fallback else "away_away"
    home_venue = _mean_or_none(
        [
            _rate(filtered_components[home_venue_source], "goals_for_rate"),
            _rate(filtered_components[away_venue_source], "goals_against_rate"),
        ]
    )
    away_venue = _mean_or_none(
        [
            _rate(filtered_components[away_venue_source], "goals_for_rate"),
            _rate(filtered_components[home_venue_source], "goals_against_rate"),
        ]
    )
    home_general = _mean_or_none(
        [
            _rate(filtered_components["home_overall"], "goals_for_rate"),
            _rate(filtered_components["away_overall"], "goals_against_rate"),
        ]
    )
    away_general = _mean_or_none(
        [
            _rate(filtered_components["away_overall"], "goals_for_rate"),
            _rate(filtered_components["home_overall"], "goals_against_rate"),
        ]
    )
    home_form = _mean_or_none([home_venue, home_venue, home_general])
    away_form = _mean_or_none([away_venue, away_venue, away_general])
    filtered_form = {
        "home_venue": home_venue,
        "away_venue": away_venue,
        "home_general": home_general,
        "away_general": away_general,
        "home_form": home_form,
        "away_form": away_form,
        "form_total": (
            home_form + away_form
            if home_form is not None and away_form is not None
            else None
        ),
        "home_venue_source": home_venue_source,
        "away_venue_source": away_venue_source,
    }
    raw_anatomy = reconstruction.get("reconstructed_anatomy") or {}
    for side in ("home", "away"):
        denominator = _finite(raw_anatomy.get(f"{side}_form"))
        if denominator is None or denominator <= 0:
            reasons.append(f"{side.upper()}_A0_DENOMINATOR_INVALID")
    for key in ("home_form", "away_form"):
        value = _finite(filtered_form.get(key))
        if value is None or value <= 0:
            reasons.append(f"FILTERED_{key.upper()}_INVALID")
    eligible = not reasons
    return {
        "eligible": eligible,
        "reasons": sorted(set(reasons)),
        "filtered_components": filtered_components,
        "filtered_form": filtered_form,
        "filtered_rows": filtered_rows,
        "fallbacks": {
            "home_venue_to_filtered_overall": home_venue_fallback,
            "away_venue_to_filtered_overall": away_venue_fallback,
        },
        "no_backfill": True,
        "actual_outcome_read": False,
    }


def _build_observation(
    evidence: Mapping[str, Any],
    frozen: Mapping[str, Any],
    *,
    raw_cache_root: Path,
) -> dict[str, Any]:
    home_history = _subject_history(
        evidence["home_rows"],
        subject_id=evidence["home_subject_team_id"],
        target_kickoff=evidence["kickoff"],
        side_label="home",
    )
    away_history = _subject_history(
        evidence["away_rows"],
        subject_id=evidence["away_subject_team_id"],
        target_kickoff=evidence["kickoff"],
        side_label="away",
    )
    windows = _component_windows(home_history, away_history)
    reconstruction = _reconstruct_recent_form(
        windows,
        frozen["canonical_recent_form"],
    )
    legacy_reconstruction = _reconstruct_recent_form(
        windows,
        frozen.get("legacy_recent_form"),
    )
    legacy_corroboration = {
        "present": isinstance(frozen.get("legacy_recent_form"), dict),
        "exact_against_reconstructed_history": legacy_reconstruction["exact"],
        "mismatches": legacy_reconstruction["mismatches"],
        "source": "input.source_snapshots.nowscore.snapshots[0].shuju.recent_form",
    }
    panlu_index, panlu_failures = _build_panlu_index(frozen["panlu_matches"])
    raw_index, raw_cache = _raw_cache_evidence(
        frozen,
        raw_cache_root=raw_cache_root,
    )
    joined_windows: dict[str, list[dict[str, Any]]] = {}
    public_component_rows: list[dict[str, Any]] = []
    for component in COMPONENTS:
        joined_windows[component] = []
        for index, row in enumerate(windows[component]):
            join = _join_competition(row, panlu_index, raw_index)
            internal = dict(row)
            internal["_join"] = join
            joined_windows[component].append(internal)
            public_component_rows.append(_row_public(component, index, row, join))
    join_statuses = [
        row["_join"]["status"]
        for rows in joined_windows.values()
        for row in rows
    ]
    friendly_rows = [
        row
        for rows in joined_windows.values()
        for row in rows
        if row["_join"].get("is_club_friendly") is True
    ]
    joined_rows = [
        row
        for rows in joined_windows.values()
        for row in rows
        if row["_join"]["status"] == "JOINED"
    ]
    universes = sorted(
        {
            row["_join"]["universe"]
            for row in joined_rows
            if row["_join"].get("universe") in UNIVERSES
        }
    )
    eligibility = _compute_outcome_blind_eligibility(joined_windows, reconstruction)
    return {
        "match_key": evidence["match_key"],
        "prediction_id": evidence["prediction_id"],
        "match_id": evidence["match_id"],
        "kickoff": evidence["kickoff"],
        "evidence_captured_at": evidence["captured"],
        "home_subject_team_id": evidence["home_subject_team_id"],
        "away_subject_team_id": evidence["away_subject_team_id"],
        "home_identity_share": evidence["home_identity_share"],
        "away_identity_share": evidence["away_identity_share"],
        "home_history_n": len(home_history),
        "away_history_n": len(away_history),
        "frozen_champion": {
            key: frozen[key]
            for key in (
                "path",
                "prediction_id",
                "match_key",
                "match_id",
                "lambda_home",
                "lambda_away",
                "lambda_total",
                "rho",
                "model_family",
                "model_role",
                "prediction_status",
                "formal_eligible",
                "input_snapshot_ref",
                "input_snapshot_id",
                "canonical_form_source",
            )
        },
        "reconstruction": reconstruction,
        "legacy_recent_form_corroboration": legacy_corroboration,
        "competition_join": {
            "panlu_match_count": len(frozen["panlu_matches"]),
            "panlu_status": frozen["panlu_status"],
            "panlu_invalid_rows": dict(sorted(panlu_failures.items())),
            "component_rows": len(public_component_rows),
            "joined_rows": sum(status == "JOINED" for status in join_statuses),
            "panlu_resolved_rows": sum(
                row["_join"].get("provenance_source") == "PANLU"
                and row["_join"]["status"] == "JOINED"
                for rows in joined_windows.values()
                for row in rows
            ),
            "raw_cache_recovered_rows": sum(
                row["_join"].get("provenance_source") == "RAW_CACHE"
                and row["_join"]["status"] == "JOINED"
                for rows in joined_windows.values()
                for row in rows
            ),
            "unresolved_rows": sum(status == "UNRESOLVED" for status in join_statuses),
            "ambiguous_rows": sum(status == "AMBIGUOUS" for status in join_statuses),
            "conflict_rows": sum(status == "CONFLICT" for status in join_statuses),
            "all_resolved": all(status == "JOINED" for status in join_statuses),
            "competition_labels": sorted(
                {
                    row["_join"].get("competition")
                    for row in joined_rows
                    if row["_join"].get("competition")
                }
            ),
        },
        "component_rows": public_component_rows,
        "friendly_component_row_count": len(friendly_rows),
        "component_row_count": len(public_component_rows),
        "friendly_component_row_share": (
            len(friendly_rows) / len(public_component_rows)
            if public_component_rows
            else None
        ),
        "history_universes": universes,
        "outcome_blind_eligibility": eligibility,
        "raw_cache": raw_cache,
        "_component_windows": joined_windows,
        "_frozen_full": frozen,
        "_kickoff": evidence["kickoff"],
    }


def _select_cohort(
    evidence_records: Mapping[str, Mapping[str, Any]],
    expected_cohort: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_match_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    expected_keys = set(expected_cohort)
    for record in evidence_records.values():
        if record.get("match_key") in expected_keys and record.get("usable"):
            by_match_key[record["match_key"]].append(dict(record))
    selected: list[dict[str, Any]] = []
    for match_key in sorted(expected_keys):
        records = by_match_key.get(match_key, [])
        legal = [record for record in records if record.get("captured") is not None]
        if not legal:
            failures.append(
                {
                    "kind": "COHORT_SNAPSHOT_SELECTION",
                    "match_key": match_key,
                    "reason": "NO_LEGAL_PREMATCH_EVIDENCE_SNAPSHOT",
                }
            )
            continue
        selected_record = max(
            legal, key=lambda record: (record["captured"], record["prediction_id"])
        )
        expected_prediction_id = expected_cohort[match_key]
        if selected_record["prediction_id"] != expected_prediction_id:
            failures.append(
                {
                    "kind": "COHORT_IDENTITY_MISMATCH",
                    "match_key": match_key,
                    "expected_prediction_id": expected_prediction_id,
                    "selected_prediction_id": selected_record["prediction_id"],
                    "reason": "LATEST_LEGAL_SNAPSHOT_SELECTION_CHANGED",
                }
            )
        selected.append(selected_record)
    selected.sort(key=lambda record: (record["kickoff"], record["match_key"]))
    actual_pairs = {record["match_key"]: record["prediction_id"] for record in selected}
    if set(actual_pairs) != expected_keys:
        failures.append(
            {
                "kind": "COHORT_IDENTITY_MISMATCH",
                "reason": "EXPECTED_61_MATCH_KEY_SET_CHANGED",
                "missing_match_keys": sorted(expected_keys - set(actual_pairs)),
                "unexpected_match_keys": sorted(set(actual_pairs) - expected_keys),
            }
        )
    return selected, failures


def _aggregate_metrics(
    rows: list[dict[str, Any]], variant: str
) -> dict[str, float | None]:
    if not rows:
        return {metric: None for metric in METRICS}
    values = [row["variants"][variant] for row in rows]
    return {
        metric: round(fmean(float(value[metric]) for value in values), 9)
        for metric in METRICS
    }


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _paired_bootstrap(
    rows: list[dict[str, Any]],
    variant: str,
    *,
    seed: int,
    replicates: int,
) -> dict[str, dict[str, Any]]:
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    if not rows:
        return {
            metric: {
                "point_estimate_variant_minus_champion": None,
                "bootstrap_ci_95": [None, None],
                "seed": seed,
                "replicates": replicates,
                "sample_n": 0,
            }
            for metric in METRICS
        }
    differences = {
        metric: [
            float(row["variants"][variant][metric])
            - float(row["variants"]["CHAMPION"][metric])
            for row in rows
        ]
        for metric in METRICS
    }
    points = {metric: fmean(values) for metric, values in differences.items()}
    rng = random.Random(seed)
    bootstrap_values = {metric: [] for metric in METRICS}
    sample_size = len(rows)
    for _ in range(replicates):
        indices = [rng.randrange(sample_size) for _ in range(sample_size)]
        for metric in METRICS:
            bootstrap_values[metric].append(
                fmean(differences[metric][index] for index in indices)
            )
    return {
        metric: {
            "point_estimate_variant_minus_champion": round(points[metric], 9),
            "bootstrap_ci_95": [
                round(_quantile(bootstrap_values[metric], 0.025), 9),
                round(_quantile(bootstrap_values[metric], 0.975), 9),
            ],
            "seed": seed,
            "replicates": replicates,
            "sample_n": sample_size,
            "method": "paired_nonparametric_bootstrap_resampling_unique_matches",
        }
        for metric in METRICS
    }


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if _finite(value) is not None]
    if not clean:
        return {
            "count": 0,
            "mean": None,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
        }
    return {
        "count": len(clean),
        "mean": round(fmean(clean), 9),
        "min": round(min(clean), 9),
        "p25": round(_quantile(clean, 0.25), 9),
        "median": round(median(clean), 9),
        "p75": round(_quantile(clean, 0.75), 9),
        "max": round(max(clean), 9),
    }


def _direction(delta: float | None, *, lower_is_better: bool) -> str:
    if delta is None:
        return "UNAVAILABLE"
    if abs(delta) <= 1e-12:
        return "NO_CHANGE"
    if lower_is_better:
        return "IMPROVES" if delta < 0 else "WORSENS"
    return "IMPROVES" if delta > 0 else "WORSENS"


def _outcome_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    output = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home, away), probability in matrix.items():
        output["home" if home > away else "draw" if home == away else "away"] += probability
    return output


def _variant_observation(
    *,
    actual_home: int,
    actual_away: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> dict[str, Any]:
    matrix = dixon_coles_score_matrix(
        {"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": rho}
    )
    actual_score = (actual_home, actual_away)
    if not matrix or actual_score not in matrix:
        raise ValueError("SCORE_MATRIX_MISSING_ACTUAL_SCORE")
    probabilities = _outcome_probabilities(matrix)
    actual_outcome = (
        "home" if actual_home > actual_away else "draw" if actual_home == actual_away else "away"
    )
    ordered = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    top_scores = [score for score, _ in ordered]
    over_probability = sum(
        probability
        for (home, away), probability in matrix.items()
        if home + away >= 3
    )
    btts_probability = sum(
        probability
        for (home, away), probability in matrix.items()
        if home > 0 and away > 0
    )
    actual_probability = matrix[actual_score]
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "rho": rho,
        "exact_score_nll": -math.log(max(actual_probability, 1e-15)),
        "actual_score_mean_probability": actual_probability,
        "top1_accuracy": float(actual_score == top_scores[0]),
        "top3_accuracy": float(actual_score in set(top_scores[:3])),
        "top5_accuracy": float(actual_score in set(top_scores[:5])),
        "one_x_two_brier": sum(
            (probabilities[key] - float(key == actual_outcome)) ** 2
            for key in ("home", "draw", "away")
        )
        / 3.0,
        "one_x_two_log_loss": -math.log(max(probabilities[actual_outcome], 1e-15)),
        "ou_2_5_brier": (
            over_probability - float(actual_home + actual_away >= 3)
        )
        ** 2,
        "btts_brier": (
            btts_probability - float(actual_home > 0 and actual_away > 0)
        )
        ** 2,
        "home_goal_mae": abs(lambda_home - actual_home),
        "home_goal_bias": lambda_home - actual_home,
        "away_goal_mae": abs(lambda_away - actual_away),
        "away_goal_bias": lambda_away - actual_away,
        "total_goal_mae": abs(lambda_home + lambda_away - actual_home - actual_away),
        "total_goal_bias": lambda_home + lambda_away - actual_home - actual_away,
        "top1_score_concentration_mean_probability": ordered[0][1],
        "top1_score_1_1_share": float(top_scores[0] == (1, 1)),
        "score_1_1_probability_mean": matrix.get((1, 1), 0.0),
        "top1_score": f"{top_scores[0][0]}-{top_scores[0][1]}",
        "one_x_two_probabilities": probabilities,
        "over_2_5_probability": over_probability,
        "btts_probability": btts_probability,
    }


def _load_authoritative_results(
    result_root: Path,
) -> tuple[dict[str, dict[str, Any]], int, Counter[str], list[dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}
    failures: Counter[str] = Counter()
    rejected: list[dict[str, Any]] = []
    paths = sorted(result_root.glob("*.json"))
    for path in paths:
        payload = _load_json(path)
        if not isinstance(payload, dict):
            failures["INVALID_RESULT_JSON_OR_OBJECT"] += 1
            rejected.append({"path": _display_path(path), "reasons": ["INVALID_RESULT_JSON_OR_OBJECT"]})
            continue
        match_key = _text(payload.get("match_key"))
        scope = _text(payload.get("scope"))
        kickoff = _parse_datetime(payload.get("kickoff_at") or payload.get("kickoff_local"))
        verified = _parse_datetime(payload.get("verified_at"))
        score = _parse_score(payload.get("result_90m"))
        reasons: list[str] = []
        if not match_key:
            reasons.append("RESULT_MISSING_MATCH_KEY")
        if scope != RESULT_SCOPE:
            reasons.append("RESULT_SCOPE_NOT_REGULATION_90M")
        if kickoff is None:
            reasons.append("INVALID_RESULT_KICKOFF")
        if verified is None:
            reasons.append("INVALID_RESULT_VERIFIED_AT")
        elif kickoff is not None and not _is_after(verified, kickoff):
            reasons.append("VERIFIED_AT_NOT_AFTER_KICKOFF")
        if score is None:
            reasons.append("RESULT_90M_UNPARSEABLE")
        if reasons:
            for reason in reasons:
                failures[reason] += 1
            rejected.append(
                {
                    "path": _display_path(path),
                    "match_key": match_key or None,
                    "result_90m": payload.get("result_90m"),
                    "reasons": sorted(set(reasons)),
                }
            )
            continue
        if match_key in results:
            failures["DUPLICATE_RESULT_MATCH_KEY"] += 1
            rejected.append(
                {
                    "path": _display_path(path),
                    "match_key": match_key,
                    "reasons": ["DUPLICATE_RESULT_MATCH_KEY"],
                }
            )
            continue
        results[match_key] = {
            "path": _display_path(path),
            "match_key": match_key,
            "kickoff": kickoff,
            "verified": verified,
            "score": score,
            "scope": scope,
        }
    return results, len(paths), failures, rejected


def _metric_deltas(
    variant_metrics: Mapping[str, Any], champion_metrics: Mapping[str, Any]
) -> dict[str, float | None]:
    return {
        metric: (
            variant_metrics.get(metric) - champion_metrics.get(metric)
            if variant_metrics.get(metric) is not None
            and champion_metrics.get(metric) is not None
            else None
        )
        for metric in METRICS
    }


def _scope_summary(rows: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    output: dict[str, Any] = {
        "scope": scope,
        "n": len(rows),
        "sample_status": (
            "SUFFICIENT"
            if len(rows) >= MIN_UNIVERSE_SAMPLE
            else "DESCRIPTIVE_ONLY_INSUFFICIENT_SAMPLE"
        ),
        "strong_conclusion_allowed": len(rows) >= MIN_UNIVERSE_SAMPLE,
        "basis": "unique target match with at least one joined frozen component row in scope",
        "friendly_component_row_count": sum(
            int(row["friendly_component_row_count"]) for row in rows
        ),
        "component_row_count": sum(int(row["component_row_count"]) for row in rows),
        "variants": {},
    }
    if output["component_row_count"]:
        output["friendly_component_row_share"] = (
            output["friendly_component_row_count"] / output["component_row_count"]
        )
    else:
        output["friendly_component_row_share"] = None
    if rows and "variants" in rows[0]:
        for variant in ("CHAMPION", *VARIANTS):
            metrics = _aggregate_metrics(rows, variant)
            payload: dict[str, Any] = {"metrics": metrics}
            if variant != "CHAMPION":
                champion = _aggregate_metrics(rows, "CHAMPION")
                deltas = _metric_deltas(metrics, champion)
                payload["metric_deltas_vs_champion"] = deltas
                payload["exact_score_nll_direction"] = _direction(
                    deltas["exact_score_nll"], lower_is_better=True
                )
            output["variants"][variant] = payload
    return output


def _chronology_thirds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row["_kickoff"], row["match_key"]))
    base, remainder = divmod(len(ordered), 3)
    sizes = [base + (1 if index < remainder else 0) for index in range(3)]
    output: list[dict[str, Any]] = []
    cursor = 0
    for label, size in zip(("earliest_third", "middle_third", "latest_third"), sizes):
        subset = ordered[cursor : cursor + size]
        cursor += size
        scope = _scope_summary(subset, label)
        scope["match_keys"] = [row["match_key"] for row in subset]
        scope["actual_outcome_read"] = bool(subset and "variants" in subset[0])
        output.append(scope)
    return output


def _public_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            key: _public_value(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_public_value(item) for item in value)
    return value


def _build_competition_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    label_counts: Counter[str] = Counter()
    universe_counts: Counter[str] = Counter()
    unresolved: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    joined_rows = unresolved_rows = ambiguous_rows = conflict_rows = 0
    panlu_resolved_rows = raw_cache_recovered_rows = 0
    component_rows = 0
    friendly_rows = 0
    raw_cache_references = raw_cache_present = raw_cache_hash_valid = 0
    raw_analysis_references = raw_analysis_present = raw_analysis_hash_valid = 0
    raw_analysis_parsed = 0
    raw_references: list[dict[str, Any]] = []
    per_match: list[dict[str, Any]] = []
    for observation in observations:
        component_rows += int(observation["component_row_count"])
        friendly_rows += int(observation["friendly_component_row_count"])
        joined_rows += int(observation["competition_join"]["joined_rows"])
        panlu_resolved_rows += int(observation["competition_join"]["panlu_resolved_rows"])
        raw_cache_recovered_rows += int(
            observation["competition_join"]["raw_cache_recovered_rows"]
        )
        unresolved_rows += int(observation["competition_join"]["unresolved_rows"])
        ambiguous_rows += int(observation["competition_join"]["ambiguous_rows"])
        conflict_rows += int(observation["competition_join"]["conflict_rows"])
        raw_cache = observation["raw_cache"]
        raw_cache_references += int(raw_cache["referenced_count"])
        raw_cache_present += int(raw_cache["present_count"])
        raw_cache_hash_valid += int(raw_cache["hash_valid_count"])
        raw_analysis_references += int(raw_cache["analysis_referenced_count"])
        raw_analysis_present += int(raw_cache["analysis_present_count"])
        raw_analysis_hash_valid += int(raw_cache["analysis_hash_valid_count"])
        raw_analysis_parsed += int(raw_cache["parsed_analysis_file_count"])
        for reference in raw_cache["references"]:
            raw_references.append(
                {"match_key": observation["match_key"], **reference}
            )
        for row in observation["component_rows"]:
            join = row["competition_join"]
            if join.get("status") == "JOINED":
                label = _text(join.get("competition"))
                if label:
                    label_counts[label] += 1
                    universe_counts[join.get("universe", "UNKNOWN_OR_MIXED")] += 1
            elif join.get("status") == "AMBIGUOUS":
                ambiguous.append(
                    {
                        "match_key": observation["match_key"],
                        "component": row["component"],
                        "window_index": row["window_index"],
                        "reason": join.get("reason"),
                        "key": join.get("key"),
                        "candidate_count": join.get("candidate_count"),
                    }
                )
            elif join.get("status") == "CONFLICT":
                conflicts.append(
                    {
                        "match_key": observation["match_key"],
                        "component": row["component"],
                        "window_index": row["window_index"],
                        "reason": join.get("reason"),
                        "key": join.get("key"),
                        "competition": join.get("competition"),
                        "raw_competition": join.get("raw_competition"),
                    }
                )
            else:
                unresolved.append(
                    {
                        "match_key": observation["match_key"],
                        "component": row["component"],
                        "window_index": row["window_index"],
                        "reason": join.get("reason"),
                        "key": join.get("key"),
                    }
                )
        per_match.append(
            {
                "match_key": observation["match_key"],
                "component_rows": observation["component_row_count"],
                "friendly_component_rows": observation["friendly_component_row_count"],
                "friendly_component_row_share": observation["friendly_component_row_share"],
                "competition_join_all_resolved": observation["competition_join"]["all_resolved"],
                "panlu_resolved_rows": observation["competition_join"]["panlu_resolved_rows"],
                "raw_cache_recovered_rows": observation["competition_join"][
                    "raw_cache_recovered_rows"
                ],
                "conflict_rows": observation["competition_join"]["conflict_rows"],
                "raw_cache_status": {
                    "referenced_count": raw_cache["referenced_count"],
                    "present_count": raw_cache["present_count"],
                    "hash_valid_count": raw_cache["hash_valid_count"],
                    "parsed_analysis_file_count": raw_cache["parsed_analysis_file_count"],
                },
                "history_universes": observation["history_universes"],
            }
        )
    return {
        "truth_source": "same immutable input_snapshot.source_snapshots.nowscore.snapshots[0].nowscore_context.panlu.matches",
        "target_competition_not_inferred": True,
        "component_rows_total": component_rows,
        "joined_rows": joined_rows,
        "panlu_resolved_rows": panlu_resolved_rows,
        "raw_cache_recovered_rows": raw_cache_recovered_rows,
        "unresolved_rows": unresolved_rows,
        "ambiguous_rows": ambiguous_rows,
        "conflict_rows": conflict_rows,
        "competition_label_distribution": dict(sorted(label_counts.items())),
        "competition_universe_row_distribution": dict(sorted(universe_counts.items())),
        "club_friendly_normalization": "NFKC plus whitespace removal; exact semantic match only",
        "club_friendly_labels": sorted(FRIENDLY_LABELS),
        "club_friendly_component_rows": friendly_rows,
        "club_friendly_component_row_share": (
            friendly_rows / component_rows if component_rows else None
        ),
        "unresolved": unresolved,
        "ambiguous": ambiguous,
        "conflicts": conflicts,
        "raw_cache": {
            "referenced_count": raw_cache_references,
            "present_count": raw_cache_present,
            "hash_valid_count": raw_cache_hash_valid,
            "analysis_referenced_count": raw_analysis_references,
            "analysis_present_count": raw_analysis_present,
            "analysis_hash_valid_count": raw_analysis_hash_valid,
            "parsed_analysis_file_count": raw_analysis_parsed,
            "recovered_component_rows": raw_cache_recovered_rows,
            "references": raw_references,
        },
        "per_unique_match": per_match,
    }


def _raw_cache_status(raw_cache: Mapping[str, Any]) -> str:
    if not raw_cache.get("referenced_count"):
        return "NO_REFERENCED_RAW_CACHE"
    if not raw_cache.get("present_count"):
        return "REFERENCED_RAW_CACHE_UNAVAILABLE"
    if not raw_cache.get("hash_valid_count"):
        return "REFERENCED_RAW_CACHE_HASH_INVALID_OR_MISSING"
    if not raw_cache.get("parsed_analysis_file_count"):
        return "HASH_VALID_RAW_ANALYSIS_NOT_PARSED"
    return "HASH_VALID_RAW_ANALYSIS_AVAILABLE"


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = fmean(xs)
    mean_y = fmean(ys)
    centered_x = [value - mean_x for value in xs]
    centered_y = [value - mean_y for value in ys]
    denominator = math.sqrt(
        sum(value * value for value in centered_x)
        * sum(value * value for value in centered_y)
    )
    if denominator <= 0 or not math.isfinite(denominator):
        return None
    return sum(x * y for x, y in zip(centered_x, centered_y)) / denominator


def _run_counterfactual(
    observations: list[dict[str, Any]],
    result_map: Mapping[str, Mapping[str, Any]],
    *,
    bootstrap_replicates: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for observation in observations:
        result = result_map.get(observation["match_key"])
        if result is None:
            failures.append(
                {
                    "kind": "RESULT_JOIN",
                    "match_key": observation["match_key"],
                    "reason": "STRICT_AUTHORITATIVE_RESULT_MISSING",
                }
            )
            continue
        try:
            actual_home, actual_away = result["score"]
            frozen = observation["_frozen_full"]
            filtered = observation["outcome_blind_eligibility"]["filtered_form"]
            raw_anatomy = observation["reconstruction"]["reconstructed_anatomy"]
            home_denominator = _finite(raw_anatomy.get("home_form"))
            away_denominator = _finite(raw_anatomy.get("away_form"))
            home_filtered = _finite(filtered.get("home_form"))
            away_filtered = _finite(filtered.get("away_form"))
            if (
                home_denominator is None
                or away_denominator is None
                or home_filtered is None
                or away_filtered is None
                or home_denominator <= 0
                or away_denominator <= 0
            ):
                raise ValueError("FRIENDLY_EXCLUDED_RATIO_DENOMINATOR_INVALID")
            home_ratio = home_filtered / home_denominator
            away_ratio = away_filtered / away_denominator
            if not math.isfinite(home_ratio) or not math.isfinite(away_ratio):
                raise ValueError("FRIENDLY_EXCLUDED_RATIO_NON_FINITE")
            lambda_home = frozen["lambda_home"] * home_ratio
            lambda_away = frozen["lambda_away"] * away_ratio
            if (
                not math.isfinite(lambda_home)
                or not math.isfinite(lambda_away)
                or lambda_home <= 0
                or lambda_away <= 0
            ):
                raise ValueError("FRIENDLY_EXCLUDED_LAMBDA_INVALID")
            variants = {
                "CHAMPION": _variant_observation(
                    actual_home=actual_home,
                    actual_away=actual_away,
                    lambda_home=frozen["lambda_home"],
                    lambda_away=frozen["lambda_away"],
                    rho=frozen["rho"],
                ),
                "FRIENDLY_EXCLUDED": _variant_observation(
                    actual_home=actual_home,
                    actual_away=actual_away,
                    lambda_home=lambda_home,
                    lambda_away=lambda_away,
                    rho=frozen["rho"],
                ),
            }
            evaluated_row = dict(observation)
            evaluated_row.update(
                {
                    "actual_home": actual_home,
                    "actual_away": actual_away,
                    "actual_total": actual_home + actual_away,
                    "variants": variants,
                }
            )
            evaluated.append(evaluated_row)
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(
                {
                    "kind": "COUNTERFACTUAL",
                    "match_key": observation["match_key"],
                    "reason": str(exc),
                }
            )
    evaluated.sort(key=lambda row: (row["_kickoff"], row["match_key"]))
    if failures:
        return evaluated, failures
    variant_summaries: dict[str, Any] = {}
    champion_metrics = _aggregate_metrics(evaluated, "CHAMPION")
    for variant in ("CHAMPION", *VARIANTS):
        metrics = _aggregate_metrics(evaluated, variant)
        payload: dict[str, Any] = {"metrics": metrics}
        if variant != "CHAMPION":
            payload["metric_deltas_vs_champion"] = _metric_deltas(
                metrics, champion_metrics
            )
            payload["paired_bootstrap"] = _paired_bootstrap(
                evaluated,
                variant,
                seed=_stable_seed(BOOTSTRAP_SEED, variant),
                replicates=bootstrap_replicates,
            )
            payload["ratio_distribution"] = {
                "home_ratio": _distribution(
                    row["outcome_blind_eligibility"]["filtered_form"]["home_form"]
                    / row["reconstruction"]["reconstructed_anatomy"]["home_form"]
                    for row in evaluated
                ),
                "away_ratio": _distribution(
                    row["outcome_blind_eligibility"]["filtered_form"]["away_form"]
                    / row["reconstruction"]["reconstructed_anatomy"]["away_form"]
                    for row in evaluated
                ),
            }
        variant_summaries[variant] = payload
    # Store aggregate payload on each row's shared result list through a private
    # field; the caller serializes the summaries separately.
    return evaluated, [{"kind": "AGGREGATES", "variant_summaries": variant_summaries}]


def _decision(
    observations: list[dict[str, Any]],
    variant_summaries: Mapping[str, Any],
    *,
    structural_failure: bool,
    evaluation_failures: list[dict[str, Any]],
    minimum_evaluable_unique_matches: int,
) -> tuple[str, dict[str, Any]]:
    evaluated_n = len(observations)
    if structural_failure:
        return "FAIL_CLOSED", {
            "evaluated_unique_matches": evaluated_n,
            "minimum_evaluable_unique_matches": minimum_evaluable_unique_matches,
            "structural_gate_passed": False,
        }
    if evaluation_failures:
        return "FAIL_CLOSED", {
            "evaluated_unique_matches": evaluated_n,
            "minimum_evaluable_unique_matches": minimum_evaluable_unique_matches,
            "structural_gate_passed": True,
            "evaluation_failures": evaluation_failures,
        }
    if evaluated_n < minimum_evaluable_unique_matches:
        return "SCOPE_EVIDENCE_NOT_RECOVERABLE", {
            "evaluated_unique_matches": evaluated_n,
            "minimum_evaluable_unique_matches": minimum_evaluable_unique_matches,
            "structural_gate_passed": True,
            "threshold_passed": False,
            "friendlies_counterfactual_route": "RETIRED_FOR_CURRENT_COHORT",
        }
    champion = variant_summaries["CHAMPION"]["metrics"]
    friendly = variant_summaries["FRIENDLY_EXCLUDED"]["metrics"]
    deltas = variant_summaries["FRIENDLY_EXCLUDED"]["metric_deltas_vs_champion"]
    nll_improved = friendly["exact_score_nll"] < champion["exact_score_nll"]
    actual_probability_non_lower = (
        friendly["actual_score_mean_probability"]
        >= champion["actual_score_mean_probability"] - 1e-12
    )
    top3_non_lower = friendly["top3_accuracy"] >= champion["top3_accuracy"] - 1e-12
    secondary_metrics = ("one_x_two_brier", "ou_2_5_brier", "btts_brier")
    secondary_non_worse = sum(
        deltas[metric] is not None and deltas[metric] <= 1e-12
        for metric in secondary_metrics
    )
    ci = (
        variant_summaries["FRIENDLY_EXCLUDED"]["paired_bootstrap"]["exact_score_nll"][
            "bootstrap_ci_95"
        ]
    )
    ci_entirely_below_zero = ci[1] < 0

    universe_summaries = [
        _scope_summary(
            [
                row
                for row in observations
                if universe in row["history_universes"]
            ],
            universe,
        )
        for universe in UNIVERSES
    ]
    sufficient_universes = {
        item["scope"]: item
        for item in universe_summaries
        if item["n"] >= MIN_UNIVERSE_SAMPLE
    }
    big5_delta = (
        sufficient_universes.get("CLUB_BIG5_TOP_LEAGUE", {})
        .get("variants", {})
        .get("FRIENDLY_EXCLUDED", {})
        .get("metric_deltas_vs_champion", {})
        .get("exact_score_nll")
    )
    other_delta = (
        sufficient_universes.get("CLUB_OTHER_TOP_LEAGUE", {})
        .get("variants", {})
        .get("FRIENDLY_EXCLUDED", {})
        .get("metric_deltas_vs_champion", {})
        .get("exact_score_nll")
    )
    universe_guardrail = not (
        big5_delta is not None
        and other_delta is not None
        and ((big5_delta < 0 < other_delta) or (other_delta < 0 < big5_delta))
    )
    thirds = _chronology_thirds(observations)
    third_deltas = [
        (
            item.get("variants", {})
            .get("FRIENDLY_EXCLUDED", {})
            .get("metric_deltas_vs_champion", {})
            .get("exact_score_nll")
        )
        for item in thirds
        if item["n"] >= MIN_UNIVERSE_SAMPLE
    ]
    chronology_guardrail = not (
        third_deltas
        and any(delta < 0 for delta in third_deltas if delta is not None)
        and any(delta > 0 for delta in third_deltas if delta is not None)
    )
    robustness_gate = (
        nll_improved
        and actual_probability_non_lower
        and top3_non_lower
        and secondary_non_worse >= 2
        and universe_guardrail
        and chronology_guardrail
    )
    if not nll_improved or not actual_probability_non_lower or not top3_non_lower:
        decision = "REJECTED"
    elif not universe_guardrail or not chronology_guardrail:
        decision = "REJECTED"
    elif robustness_gate and ci_entirely_below_zero:
        decision = "STRONG_SCOPE_SURVIVOR"
    elif robustness_gate:
        decision = "SCOPE_SURVIVOR"
    else:
        decision = "INCONCLUSIVE"
    return decision, {
        "evaluated_unique_matches": evaluated_n,
        "minimum_evaluable_unique_matches": minimum_evaluable_unique_matches,
        "threshold_passed": True,
        "FRIENDLY_EXCLUDED_exact_score_nll_improved": nll_improved,
        "FRIENDLY_EXCLUDED_actual_score_mean_probability_non_lower": actual_probability_non_lower,
        "FRIENDLY_EXCLUDED_top3_non_lower": top3_non_lower,
        "secondary_non_worse_count": secondary_non_worse,
        "secondary_non_worse_required": 2,
        "secondary_brier_metrics": list(secondary_metrics),
        "paired_nll_bootstrap_ci_95": ci,
        "paired_nll_ci_entirely_below_zero": ci_entirely_below_zero,
        "universe_guardrail_passed": universe_guardrail,
        "chronology_guardrail_passed": chronology_guardrail,
        "big5_exact_score_nll_delta": big5_delta,
        "other_top_exact_score_nll_delta": other_delta,
        "paired_delta_sign_convention": "FRIENDLY_EXCLUDED minus Champion; lower exact-score NLL is better",
    }


def run(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
    raw_cache_root: Path = DEFAULT_RAW_CACHE_ROOT,
    execution_label: str = DEFAULT_EXECUTION_LABEL,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    expected_cohort: Mapping[str, str] = EXPECTED_COHORT,
    minimum_evaluable_unique_matches: int = MIN_EVALUABLE_UNIQUE_MATCHES,
) -> dict[str, Any]:
    evidence_records, evidence_file_count, evidence_failures = _load_evidence(
        evidence_root
    )
    selected_evidence, cohort_failures = _select_cohort(
        evidence_records, expected_cohort
    )
    observations: list[dict[str, Any]] = []
    observation_failures: list[dict[str, Any]] = []
    for evidence in selected_evidence:
        try:
            frozen = _load_frozen_prediction(
                prediction_root,
                snapshot_root,
                evidence["prediction_id"],
                evidence["match_key"],
                evidence["kickoff"],
                evidence["match_id"],
            )
            observations.append(
                _build_observation(
                    evidence,
                    frozen,
                    raw_cache_root=raw_cache_root,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            observation_failures.append(
                {
                    "kind": "STRUCTURAL_OBSERVATION",
                    "prediction_id": evidence["prediction_id"],
                    "match_key": evidence["match_key"],
                    "reason": str(exc),
                }
            )
    observations.sort(key=lambda row: (row["_kickoff"], row["match_key"]))
    cohort_identity_ok = not cohort_failures and len(observations) == len(expected_cohort)
    reconstruction_exact_count = sum(
        bool(row["reconstruction"]["exact"]) for row in observations
    )
    reconstruction_mismatches = [
        {
            "match_key": row["match_key"],
            "prediction_id": row["prediction_id"],
            "mismatches": row["reconstruction"]["mismatches"],
        }
        for row in observations
        if not row["reconstruction"]["exact"]
    ]
    competition_summary = _build_competition_summary(observations)
    structural_failure = bool(
        cohort_failures
        or observation_failures
        or not cohort_identity_ok
        or reconstruction_exact_count != len(expected_cohort)
        or competition_summary["conflict_rows"] > 0
    )
    eligible_observations = [
        row
        for row in observations
        if row["reconstruction"]["exact"]
        and row["competition_join"]["all_resolved"]
        and row["outcome_blind_eligibility"]["eligible"]
    ]
    eligible_observations.sort(key=lambda row: (row["_kickoff"], row["match_key"]))
    fallback_counts = Counter()
    exclusion_counts = Counter()
    sample_size_distribution: dict[str, Counter[str]] = {
        component: Counter() for component in COMPONENTS
    }
    ineligible: list[dict[str, Any]] = []
    for row in observations:
        eligibility = row["outcome_blind_eligibility"]
        for key, used in eligibility["fallbacks"].items():
            if used:
                fallback_counts[key] += 1
        for component, component_summary in eligibility["filtered_components"].items():
            sample_size_distribution[component][
                str(component_summary["remaining_matches"])
            ] += 1
            exclusion_counts[component] += int(
                component_summary["excluded_friendly_matches"]
            )
        if row not in eligible_observations:
            join = row["competition_join"]
            join_reasons = []
            if join["unresolved_rows"]:
                join_reasons.append("COMPETITION_LABEL_UNRESOLVED")
            if join["ambiguous_rows"]:
                join_reasons.append("COMPETITION_LABEL_AMBIGUOUS")
            if join["conflict_rows"]:
                join_reasons.append("COMPETITION_LABEL_CONFLICT")
            ineligible.append(
                {
                    "match_key": row["match_key"],
                    "reasons": sorted(
                        set(
                            row["outcome_blind_eligibility"]["reasons"]
                            + join_reasons
                        )
                    ),
                }
            )
    eligible_n = len(eligible_observations)
    outcome_blind_gate_passed = (
        not structural_failure and eligible_n >= minimum_evaluable_unique_matches
    )
    outcome_blind_summary = {
        "actual_outcome_read": False,
        "gate_passed": outcome_blind_gate_passed,
        "eligible_unique_matches": eligible_n,
        "minimum_eligible_unique_matches": minimum_evaluable_unique_matches,
        "exclusion_counts_by_component": dict(sorted(exclusion_counts.items())),
        "fallback_counts": dict(sorted(fallback_counts.items())),
        "component_sample_size_distribution": {
            component: dict(sorted(counter.items(), key=lambda item: int(item[0])))
            for component, counter in sample_size_distribution.items()
        },
        "no_backfill": all(
            row["outcome_blind_eligibility"]["no_backfill"] for row in observations
        ),
        "eligible_match_keys": [row["match_key"] for row in eligible_observations],
        "ineligible": ineligible,
    }

    variant_summaries: dict[str, Any] = {}
    evaluation_failures: list[dict[str, Any]] = []
    result_file_count = 0
    result_failures: Counter[str] = Counter()
    rejected_results: list[dict[str, Any]] = []
    actual_outcome_read = False
    if outcome_blind_gate_passed:
        result_map, result_file_count, result_failures, rejected_results = (
            _load_authoritative_results(result_root)
        )
        actual_outcome_read = True
        evaluated_observations, aggregate_records = _run_counterfactual(
            eligible_observations,
            result_map,
            bootstrap_replicates=bootstrap_replicates,
        )
        evaluation_failures = aggregate_records if aggregate_records and aggregate_records[0].get("kind") != "AGGREGATES" else []
        if not evaluation_failures and aggregate_records:
            variant_summaries = aggregate_records[0]["variant_summaries"]
        if len(evaluated_observations) != len(eligible_observations):
            evaluation_failures.append(
                {
                    "kind": "RESULT_COHORT",
                    "reason": "EVALUATED_COHORT_CHANGED",
                    "eligible_unique_matches": len(eligible_observations),
                    "evaluated_unique_matches": len(evaluated_observations),
                }
            )
        if not evaluation_failures and result_failures:
            missing = sorted(
                set(row["match_key"] for row in eligible_observations)
                - set(result_map)
            )
            if missing:
                evaluation_failures.append(
                    {
                        "kind": "RESULT_COHORT",
                        "reason": "STRICT_RESULT_MISSING_FOR_ELIGIBLE_MATCH",
                        "missing_match_keys": missing,
                    }
                )
        if not evaluation_failures:
            for row in evaluated_observations:
                row["outcome_blind_eligibility"]["actual_outcome_read"] = True
            eligible_observations = evaluated_observations
            outcome_blind_summary["actual_outcome_read"] = True
            outcome_blind_summary["evaluated_unique_matches"] = len(evaluated_observations)
    decision, decision_evidence = _decision(
        eligible_observations if actual_outcome_read else [],
        variant_summaries,
        structural_failure=structural_failure,
        evaluation_failures=evaluation_failures,
        minimum_evaluable_unique_matches=minimum_evaluable_unique_matches,
    )
    status = "FAIL_CLOSED" if decision == "FAIL_CLOSED" else "DECIDED"
    if decision == "SCOPE_EVIDENCE_NOT_RECOVERABLE":
        status = "SCOPE_EVIDENCE_NOT_RECOVERABLE"

    public_observations = [_public_value(row) for row in observations]
    public_evaluated = [_public_value(row) for row in eligible_observations]
    evaluated_for_relationship = eligible_observations if actual_outcome_read else []
    relationship_rows = [
        row
        for row in evaluated_for_relationship
        if "variants" in row and row["friendly_component_row_share"] is not None
    ]
    relationship = {
        "status": "DESCRIPTIVE_ONLY" if relationship_rows else "NOT_EVALUATED_BEFORE_OUTCOME_GATE",
        "n": len(relationship_rows),
        "pearson_friendly_share_vs_nll_delta": _correlation(
            [
                float(row["friendly_component_row_share"])
                for row in relationship_rows
            ],
            [
                float(
                    row["variants"]["FRIENDLY_EXCLUDED"]["exact_score_nll"]
                    - row["variants"]["CHAMPION"]["exact_score_nll"]
                )
                for row in relationship_rows
            ],
        ),
        "warning": "descriptive only; no parameter fit or tuning",
    }
    guardrail_rows = (
        eligible_observations
        if actual_outcome_read and not evaluation_failures
        else observations
    )
    universe_rows = {
        universe: [
            row for row in guardrail_rows if universe in row["history_universes"]
        ]
        for universe in UNIVERSES
    }
    competition_universe = [
        _scope_summary(universe_rows[universe], universe) for universe in UNIVERSES
    ]
    chronology_thirds = _chronology_thirds(guardrail_rows)
    settlement_gate = {
        "actual_outcome_read": actual_outcome_read,
        "evidence_files": evidence_file_count,
        "usable_prematch_evidence_snapshots": sum(
            bool(record["usable"]) for record in evidence_records.values()
        ),
        "authoritative_result_files_read": result_file_count,
        "strict_valid_authoritative_results": (
            result_file_count - sum(result_failures.values()) if actual_outcome_read else None
        ),
        "scope_required": RESULT_SCOPE,
        "result_90m_required": True,
        "verified_at_required_after_kickoff": True,
        "failure_reasons": dict(sorted(result_failures.items())),
        "rejected_authoritative_records": rejected_results,
    }
    source = {
        "accepted_cohort_reference": {
            **ACCEPTED_COHORT_REFERENCE,
            "selection_rule": "latest legal prematch evidence_captured_at per match_key; tie-break prediction_id",
        },
        "champion_model_family": CHAMPION_MODEL_FAMILY,
        "prospective_evidence_root": _display_path(evidence_root),
        "frozen_prediction_root": _display_path(prediction_root),
        "immutable_input_snapshot_root": _display_path(snapshot_root),
        "authoritative_result_root": _display_path(result_root),
        "competition_truth": "same immutable input snapshot panlu.matches, then referenced hash-valid local raw analysis.js only",
        "canonical_recent_form_truth": "input.prematch_fundamentals.recent_form",
        "legacy_recent_form_role": "secondary provenance corroboration only",
        "network_access": "NO_NETWORK",
        "execution_label": execution_label,
        "raw_cache_root": str(raw_cache_root.resolve()),
        "postmatch_reviews_used": False,
        "provider_added": False,
        "target_outcome_used_for_scope_or_eligibility": False,
    }
    cohort = {
        "expected_unique_matches": len(expected_cohort),
        "selected_latest_legal_unique_matches": len(selected_evidence),
        "observed_unique_matches": len(observations),
        "evaluated_unique_matches": len(eligible_observations) if actual_outcome_read else 0,
        "one_match_one_observation": len({row["match_key"] for row in observations})
        == len(observations),
        "identity_match_to_pr163": cohort_identity_ok,
        "selection_used_actual_outcome": False,
        "selection_rule": "latest legal prematch evidence_captured_at per match_key; tie-break prediction_id",
        "selected_prediction_ids": [row["prediction_id"] for row in selected_evidence],
        "selected_match_keys": [row["match_key"] for row in selected_evidence],
        "expected_match_keys": sorted(expected_cohort),
    }
    controls = {
        "research_only": True,
        "production_changes": "NO",
        "champion_changes": "NO",
        "market_changes": "NO",
        "provider_changes": "NO",
        "frozen_prediction_changes": "NO",
        "results_truth_changes": "NO",
        "serving_changes": "NO",
        "selector_changes": "NO",
        "calibration_changes": "NO",
        "rho_changes": "NO",
        "promotion": "NO",
        "counterfactual_count": 1 if outcome_blind_gate_passed else 0,
        "counterfactual_name": "FRIENDLY_EXCLUDED",
        "counterfactual_route_retired": decision == "SCOPE_EVIDENCE_NOT_RECOVERABLE",
    }
    raw_provenance = {
        **competition_summary["raw_cache"],
        "execution_label": execution_label,
        "cache_root": str(raw_cache_root.resolve()),
        "status": _raw_cache_status(competition_summary["raw_cache"]),
        "github_reproducibility": (
            "RAW_CACHE_NOT_TRACKED_OR_PRESENT_ON_GITHUB_RUNNER"
            if execution_label == "GITHUB_ACTIONS_RUNNER"
            else "LOCAL_WORKSPACE_EVIDENCE_ONLY"
        ),
        "source_policy": "selected immutable input snapshot source_refs/source_hashes only; no network fallback",
        "path_binding": "raw_cache_root plus exact referenced relative path; reference prefix must be data/source_cache/nowscore/raw/",
    }
    return _public_value(
        {
            "schema_version": "recent_form_competition_provenance_recovery.v1",
            "milestone": MILESTONE,
            "status": status,
            "decision": decision,
            "source": source,
            "settlement_gate": settlement_gate,
            "cohort": cohort,
            "frozen_recent_form_reconstruction": {
                "selected_observation_count": len(observations),
                "exact_reconstruction_match_count": reconstruction_exact_count,
                "exact_all_selected": reconstruction_exact_count == len(expected_cohort),
                "component_rows_per_observation": 40,
                "component_rows_total": sum(
                    int(row["component_row_count"]) for row in observations
                ),
                "mismatches": reconstruction_mismatches,
                "fail_closed_if_any_selected_observation_unexplained": True,
            },
            "competition_join": competition_summary,
            "raw_provenance": raw_provenance,
            "outcome_blind_eligibility": outcome_blind_summary,
            "variants": variant_summaries,
            "primary_paired_bootstrap": (
                variant_summaries.get("FRIENDLY_EXCLUDED", {})
                .get("paired_bootstrap", {})
                .get("exact_score_nll")
            ),
            "friendlies_share_vs_nll_delta": relationship,
            "competition_universe": competition_universe,
            "chronology_thirds": chronology_thirds,
            "per_match_observations": public_observations,
            "evaluated_observations": public_evaluated,
            "decision_evidence": decision_evidence,
            "prematch_evidence_failure_reasons": dict(sorted(evidence_failures.items())),
            "cohort_failures": cohort_failures,
            "structural_failures": observation_failures,
            "evaluation_failures": evaluation_failures,
            "pre_registered_decision_rules": {
                "STRONG_SCOPE_SURVIVOR": [
                    "FRIENDLY_EXCLUDED Exact Score NLL < Champion",
                    "actual-score mean probability >= Champion",
                    "Top3 >= Champion",
                    "at least 2 of 1X2 Brier, O/U2.5 Brier, BTTS Brier non-worse",
                    "paired Exact Score NLL bootstrap 95% CI entirely < 0",
                    "sufficient Big-5 and other-top history-universe guardrails do not reverse direction",
                ],
                "SCOPE_SURVIVOR": "same primary, secondary, universe and chronology gates without CI entirely < 0",
                "INCONCLUSIVE": "NLL improves but robustness/secondary guard is incomplete",
                "REJECTED": "NLL, actual-score probability, Top3, universe or chronology guardrail fails",
                "SCOPE_EVIDENCE_NOT_RECOVERABLE": f"outcome-blind eligible unique matches < {minimum_evaluable_unique_matches}; retire the friendlies counterfactual route for this 61-match cohort",
                "FAIL_CLOSED": "any selected observation cannot be exactly explained, cohort identity changes, or an immutable join/evaluation contract fails",
            },
            "controls": controls,
            "stop_state": "STOP_AFTER_PREREGISTERED_OFFLINE_DECISION",
        }
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def build_report(summary: Mapping[str, Any]) -> str:
    source = summary.get("source") or {}
    cohort = summary.get("cohort") or {}
    reconstruction = summary.get("frozen_recent_form_reconstruction") or {}
    competition = summary.get("competition_join") or {}
    raw = summary.get("raw_provenance") or {}
    eligibility = summary.get("outcome_blind_eligibility") or {}
    decision_evidence = summary.get("decision_evidence") or {}
    lines = [
        f"# {summary.get('milestone')}",
        "",
        f"- status: {summary.get('status')}",
        f"- final decision: {summary.get('decision')}",
        "- research-only; no production, Champion, provider, frozen prediction, results truth, serving, or UI change.",
        "",
        "## Cohort identity and frozen sources",
        "",
        f"- PR #166 accepted head: {((source.get('accepted_cohort_reference') or {}).get('accepted_head'))}",
        f"- expected unique matches: {cohort.get('expected_unique_matches')}",
        f"- selected latest legal unique matches: {cohort.get('selected_latest_legal_unique_matches')}",
        f"- observed unique matches: {cohort.get('observed_unique_matches')}",
        f"- one match = one observation: {cohort.get('one_match_one_observation')}",
        f"- identity matches PR #166 / PR #163 cohort: {cohort.get('identity_match_to_pr163')}",
        f"- selection used actual outcome: {cohort.get('selection_used_actual_outcome')}",
        f"- competition truth: {source.get('competition_truth')}",
        "",
        "## A. Frozen recent-form reconstruction proof",
        "",
        "Each component is reconstructed from the subject's deterministic latest-10 window in football_evidence and compared field-by-field on matches, goals_for, and goals_against with the canonical immutable input.prematch_fundamentals.recent_form.",
        f"- selected observations: {reconstruction.get('selected_observation_count')}",
        f"- exact reconstruction matches: {reconstruction.get('exact_reconstruction_match_count')}",
        f"- exact for every selected observation: {reconstruction.get('exact_all_selected')}",
        f"- component rows: {reconstruction.get('component_rows_total')}",
        "",
        "| match_key | prediction_id | exact | component mismatch |",
        "|---|---|---|---|",
    ]
    mismatch_by_key = {
        row.get("match_key"): row for row in reconstruction.get("mismatches", []) or []
    }
    for row in summary.get("per_match_observations", []) or []:
        mismatch = mismatch_by_key.get(row.get("match_key"))
        lines.append(
            f"| {row.get('match_key')} | {row.get('prediction_id')} | {not bool(mismatch)} | {json.dumps((mismatch or {}).get('mismatches', []), ensure_ascii=False, sort_keys=True)} |"
        )
    lines.extend(
        [
            "",
            "## B. Competition-label join",
            "",
            f"- truth source: {competition.get('truth_source')}",
            f"- component rows total: {competition.get('component_rows_total')}",
            f"- joined rows: {competition.get('joined_rows')}",
            f"- panlu-resolved rows: {competition.get('panlu_resolved_rows')}",
            f"- raw-cache-recovered rows: {competition.get('raw_cache_recovered_rows')}",
            f"- unresolved rows: {competition.get('unresolved_rows')}",
            f"- ambiguous rows: {competition.get('ambiguous_rows')}",
            f"- conflict rows: {competition.get('conflict_rows')}",
            f"- friendly rows: {competition.get('club_friendly_component_rows')}",
            f"- friendly share: {_fmt(competition.get('club_friendly_component_row_share'))}",
            f"- label distribution: {json.dumps(competition.get('competition_label_distribution', {}), ensure_ascii=False, sort_keys=True)}",
            f"- universe row distribution: {json.dumps(competition.get('competition_universe_row_distribution', {}), ensure_ascii=False, sort_keys=True)}",
            "",
            "## Frozen raw-cache provenance recovery",
            "",
            f"- execution label: {raw.get('execution_label')}",
            f"- cache root: {raw.get('cache_root')}",
            f"- status: {raw.get('status')}",
            f"- referenced raw files: {raw.get('referenced_count')}",
            f"- present raw files: {raw.get('present_count')}",
            f"- hash-valid raw files: {raw.get('hash_valid_count')}",
            f"- referenced analysis.js files: {raw.get('analysis_referenced_count')}",
            f"- present analysis.js files: {raw.get('analysis_present_count')}",
            f"- hash-valid analysis.js files: {raw.get('analysis_hash_valid_count')}",
            f"- parsed analysis.js files: {raw.get('parsed_analysis_file_count')}",
            f"- recovered component rows: {raw.get('recovered_component_rows')}",
            f"- GitHub reproducibility: {raw.get('github_reproducibility')}",
            "- summary.json contains each exact referenced path, recorded SHA-256, computed SHA-256, availability status, and parser evidence; no network fallback is used.",
            "",
            "## C. Outcome-blind eligibility gate",
            "",
            f"- actual outcome read before gate: {eligibility.get('actual_outcome_read')}",
            f"- gate passed: {eligibility.get('gate_passed')}",
            f"- eligible unique matches: {eligibility.get('eligible_unique_matches')}",
            f"- minimum: {eligibility.get('minimum_eligible_unique_matches')}",
            f"- no-backfill: {eligibility.get('no_backfill')}",
            f"- exclusions by component: {json.dumps(eligibility.get('exclusion_counts_by_component', {}), ensure_ascii=False, sort_keys=True)}",
            f"- fallback counts: {json.dumps(eligibility.get('fallback_counts', {}), ensure_ascii=False, sort_keys=True)}",
            f"- component sample sizes: {json.dumps(eligibility.get('component_sample_size_distribution', {}), ensure_ascii=False, sort_keys=True)}",
            "",
        ]
    )
    if summary.get("variants"):
        lines.extend(
            [
                "## D/E. FRIENDLY_EXCLUDED versus Champion",
                "",
                "| variant | Exact Score NLL | actual-score probability | Top3 | 1X2 Brier | O/U2.5 Brier | BTTS Brier |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for variant in ("CHAMPION", "FRIENDLY_EXCLUDED"):
            metrics = (summary["variants"].get(variant) or {}).get("metrics") or {}
            lines.append(
                f"| {variant} | {_fmt(metrics.get('exact_score_nll'))} | {_fmt(metrics.get('actual_score_mean_probability'))} | {_fmt(metrics.get('top3_accuracy'))} | {_fmt(metrics.get('one_x_two_brier'))} | {_fmt(metrics.get('ou_2_5_brier'))} | {_fmt(metrics.get('btts_brier'))} |"
            )
        lines.extend(
            [
                "",
                "### Paired bootstrap",
                "",
                f"- primary paired bootstrap: {json.dumps(summary.get('primary_paired_bootstrap'), ensure_ascii=False, sort_keys=True)}",
                f"- friendlies share vs NLL delta: {json.dumps(summary.get('friendlies_share_vs_nll_delta'), ensure_ascii=False, sort_keys=True)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## D/E. Counterfactual status",
                "",
                "- FRIENDLY_EXCLUDED was not run because the outcome-blind structural gate failed or the sample was insufficient.",
                f"- counterfactual count: {(summary.get('controls') or {}).get('counterfactual_count')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Universe and chronology guardrails",
            "",
            "| scope | n | sample status | friendly share | FE NLL delta |",
            "|---|---:|---|---:|---:|",
        ]
    )
    for scope in summary.get("competition_universe", []) or []:
        delta = (
            ((scope.get("variants") or {}).get("FRIENDLY_EXCLUDED") or {})
            .get("metric_deltas_vs_champion", {})
            .get("exact_score_nll")
        )
        lines.append(
            f"| {scope.get('scope')} | {scope.get('n')} | {scope.get('sample_status')} | {_fmt(scope.get('friendly_component_row_share'))} | {_fmt(delta)} |"
        )
    lines.extend(["", "### Chronological thirds", ""])
    for scope in summary.get("chronology_thirds", []) or []:
        delta = (
            ((scope.get("variants") or {}).get("FRIENDLY_EXCLUDED") or {})
            .get("metric_deltas_vs_champion", {})
            .get("exact_score_nll")
        )
        lines.append(
            f"- {scope.get('scope')}: n={scope.get('n')}, friendly_share={_fmt(scope.get('friendly_component_row_share'))}, FE_NLL_delta={_fmt(delta)}"
        )
    lines.extend(
        [
            "",
            "## Pre-registered decision",
            "",
            f"- decision evidence: {json.dumps(decision_evidence, ensure_ascii=False, sort_keys=True)}",
            f"- final decision: {summary.get('decision')}",
            "",
            "## Stop state and controls",
            "",
            f"- controls: {json.dumps(summary.get('controls', {}), ensure_ascii=False, sort_keys=True)}",
            f"- stop_state: {summary.get('stop_state')}",
            f"- failures: {json.dumps({'cohort': summary.get('cohort_failures', []), 'structural': summary.get('structural_failures', []), 'evaluation': summary.get('evaluation_failures', [])}, ensure_ascii=False, sort_keys=True)}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("audit-artifact"),
        help="directory for summary.json and report.md",
    )
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    parser.add_argument(
        "--raw-cache-root",
        type=Path,
        default=DEFAULT_RAW_CACHE_ROOT,
        help="local Nowscore raw-cache directory; files are read only when snapshot-referenced and hash-valid",
    )
    parser.add_argument(
        "--execution-label",
        default=DEFAULT_EXECUTION_LABEL,
        help="evidence environment label recorded in the artifact",
    )
    args = parser.parse_args()
    summary = run(
        bootstrap_replicates=args.bootstrap_replicates,
        raw_cache_root=args.raw_cache_root,
        execution_label=args.execution_label,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(build_report(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "status": summary["status"],
                "expected_unique_matches": summary["cohort"]["expected_unique_matches"],
                "selected_latest_legal_unique_matches": summary["cohort"][
                    "selected_latest_legal_unique_matches"
                ],
                "observed_unique_matches": summary["cohort"]["observed_unique_matches"],
                "identity_match_to_pr163": summary["cohort"]["identity_match_to_pr163"],
                "exact_reconstruction_match_count": summary[
                    "frozen_recent_form_reconstruction"
                ]["exact_reconstruction_match_count"],
                "eligible_unique_matches": summary["outcome_blind_eligibility"][
                    "eligible_unique_matches"
                ],
                "raw_cache_status": summary["raw_provenance"]["status"],
                "raw_cache_referenced_count": summary["raw_provenance"][
                    "referenced_count"
                ],
                "raw_cache_present_count": summary["raw_provenance"]["present_count"],
                "raw_cache_hash_valid_count": summary["raw_provenance"][
                    "hash_valid_count"
                ],
                "raw_cache_recovered_component_rows": summary["raw_provenance"][
                    "recovered_component_rows"
                ],
                "actual_outcome_read": summary["settlement_gate"][
                    "actual_outcome_read"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
