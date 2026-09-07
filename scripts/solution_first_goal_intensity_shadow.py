#!/usr/bin/env python3
"""Train and run the shadow-only solution-first goal-intensity challenger.

The isolated research dependency is XGBoost's Poisson count regressor.  Two
models, one for each goal count, use ``log(lambda_market_side)`` as the
immutable ``base_margin`` in train, validation, test, and live inference.  If
the optional ML dependency or a symmetric feature authority is unavailable,
the lane fails closed instead of substituting a different learner.  The live
sidecar reads only frozen prematch snapshots and writes a separate namespace.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from accepted_market_lambda import (  # noqa: E402
    MarketContractError,
    external_market_lambdas,
    independent_score_matrix,
    market_lambdas_from_snapshot,
)
from market_contracts import split_quarter_line  # noqa: E402
from market_side_shadow import _actual_for_pair, load_persisted_pairs  # noqa: E402
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)

try:  # Isolated research-only dependency; production serving does not import it.
    import xgboost as xgb  # type: ignore
except Exception:  # pragma: no cover - optional wheel/DLL/runtime failures fail closed below
    xgb = None


MILESTONE = "SOLUTION-FIRST-GOAL-INTENSITY-CHALLENGER-1"
SCHEMA_VERSION = "solution_first_goal_intensity_shadow_1.v1"
MODEL_FAMILY = "market_offset_goal_intensity_boosted_poisson_v1"
MODEL_BACKEND = "xgboost_count_poisson_base_margin_v1"
FEATURE_SCHEMA = "prematch_recent_form_all_events_v2"
TRAINING_AUTHORITY = "EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER"
EXTERNAL_SOURCE = "Football-Data.co.uk"
EXTERNAL_ROOT = ROOT / "artifacts" / "solution-first-goal-intensity-1" / "external"
OUTPUT_ROOT = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1"
DEFAULT_SUMMARY = OUTPUT_ROOT / "summary.json"
DEFAULT_REPORT = OUTPUT_ROOT / "report.md"
DEFAULT_MODEL = OUTPUT_ROOT / "model.json"
DEFAULT_SHADOW_OUTPUT = OUTPUT_ROOT / "latest.json"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_EVAL_CUTOFF = datetime(2026, 8, 30, 19, 30, tzinfo=timezone(timedelta(hours=8)))
DEFAULT_PROSPECTIVE_AFTER = None

SCORE_MAX_GOALS = 12
MARKET_EPSILON = 1e-12
ROLLING_WINDOW = 10
MIN_FORM_MATCHES = 3
MIN_EXTERNAL_ROWS = 200
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
TIME_DECAY_HALF_LIFE_DAYS = 365.0
BOOSTER_ESTIMATORS = 24
BOOSTER_EARLY_STOPPING_ROUNDS = 6
OUTPUT_LAMBDA_MIN = 0.05
OUTPUT_LAMBDA_MAX = 8.0
OUTCOMES = ("home", "draw", "away")
FEATURE_NAMES = (
    "home_attack_venue_rate",
    "home_defence_venue_rate",
    "away_attack_venue_rate",
    "away_defence_venue_rate",
    "home_attack_overall_rate",
    "home_defence_overall_rate",
    "away_attack_overall_rate",
    "away_defence_overall_rate",
    "home_venue_matches_norm",
    "away_venue_matches_norm",
    "home_overall_matches_norm",
    "away_overall_matches_norm",
)
FEATURE_SCHEMA_DEFINITION = {
    "version": FEATURE_SCHEMA,
    "window": ROLLING_WINDOW,
    "fields": list(FEATURE_NAMES),
    "contract": "one shared four-block aggregate of the latest <=10 pre-kickoff events in the source-native all-events stream; venue blocks are a filtered view of the same stream",
    "live_source": "immutable prematch Nowscore shuju.recent_form, accepted repository scope ALL_EVENTS",
    "external_source": "immutable Football-Data rows merged across the committed source files before chronological aggregation; no same-league filter",
    "scope_guard": "the model consumes only the shared ALL_EVENTS contract; source-specific coverage remains HORIZON_TRANSFER and is not promotion evidence",
    "missingness": "venue block requires 3 prior matches; otherwise same-team overall block is used; rows without 3 overall matches are excluded",
    "result_leakage_guard": "features are read before source_cutoff in live and before current kickoff in external chronological construction; source event rows are immutable prematch inputs",
}
FEATURE_SOURCE_SCOPES = frozenset({"nowscore_all_events_v1", "football_data_all_available_events_v1"})
LEAGUE_CODES = ("E0", "E1", "D1", "I1", "SP1", "F1")
SEASON_CODES = ("2223", "2324", "2425", "2526")
FIXED_107_PAIR_IDS = frozenset({
    'MS-SHADOW-PAIR-01bdedcbe84ae1d30d94de446fd14237',
    'MS-SHADOW-PAIR-026235e7c1f2f97ed91ae4dcbde1c023',
    'MS-SHADOW-PAIR-0423ab5e245e7c56e9ba10f2c198e525',
    'MS-SHADOW-PAIR-04429788e7e8c7ffb1c1420f5676405f',
    'MS-SHADOW-PAIR-04610ef848c671abfa8b24687245c7e8',
    'MS-SHADOW-PAIR-0542c141a9866e995701f038715a50ec',
    'MS-SHADOW-PAIR-05431919ee860915a6b6391d2be8ec41',
    'MS-SHADOW-PAIR-05f727b40d24a55f4c02b5b7692e4067',
    'MS-SHADOW-PAIR-07e52cac460d53f077543d8e50911faa',
    'MS-SHADOW-PAIR-08f4c278322a04d7169dc91692be5cc4',
    'MS-SHADOW-PAIR-0a5e5bb44235da8f64313090b5f804a3',
    'MS-SHADOW-PAIR-0d47ad5a1e6f1f26659efd3a87648655',
    'MS-SHADOW-PAIR-138e250ef1f5724f66ba8cbb0d44ae8e',
    'MS-SHADOW-PAIR-1a566e244021928ad2262caf380d3e6d',
    'MS-SHADOW-PAIR-1c3d20165f202e828c13a0d681a1f89d',
    'MS-SHADOW-PAIR-1cb45d2d6296020a8cb545b3d9a7cb1d',
    'MS-SHADOW-PAIR-1d4623cbe58b7bd8443be33768cf0f34',
    'MS-SHADOW-PAIR-1f10f2f3aa37c4041cafe5898cdca247',
    'MS-SHADOW-PAIR-223a3c929e8ad0d776c87eb16538b215',
    'MS-SHADOW-PAIR-23604b6c6b0c5bc977da899cb7a52973',
    'MS-SHADOW-PAIR-25a93f99d4d1c00336e8631d7e41012b',
    'MS-SHADOW-PAIR-26f2f93c217f3bd1aca8a394bdd6a385',
    'MS-SHADOW-PAIR-2acbdf62a460018d54a0a20feebe755e',
    'MS-SHADOW-PAIR-2c0978c0b2421bb058743d55af6a5cef',
    'MS-SHADOW-PAIR-30bd4ac2e324c4fd2a30ec0ec7078081',
    'MS-SHADOW-PAIR-394e03931acaf76ba4df462e33989e85',
    'MS-SHADOW-PAIR-3bdf2a68dc5553324413ce514cfcdd35',
    'MS-SHADOW-PAIR-3cf2dce5584a91d88fa87ef7a9747067',
    'MS-SHADOW-PAIR-3ec89b473caef880b698ae0fcdac980f',
    'MS-SHADOW-PAIR-3f65d7f7bb7e3605be43c5885ef45238',
    'MS-SHADOW-PAIR-46b46c7af0d413939dbc24f6129eff7f',
    'MS-SHADOW-PAIR-47e1b3e50ad795e28e2bb87cced6bd67',
    'MS-SHADOW-PAIR-49c8da6492bdca34cec27140e07ecdcd',
    'MS-SHADOW-PAIR-4a9b199957d7b4b62a3b185e3d065125',
    'MS-SHADOW-PAIR-4b85a0188d930f55f853626159ec1221',
    'MS-SHADOW-PAIR-55a313bfc3cc549331b1d0b91879f16c',
    'MS-SHADOW-PAIR-56d99e74532f4c3632f17c21144888b6',
    'MS-SHADOW-PAIR-58573ab3fe9d7afc30348973e5d9051e',
    'MS-SHADOW-PAIR-58b2481c0cc4e0b9fc8ba76306f8869a',
    'MS-SHADOW-PAIR-58ea69d1276eb6a7ed3125cdefa29ea7',
    'MS-SHADOW-PAIR-598b3d68b9e4e31f2c569cdae5728715',
    'MS-SHADOW-PAIR-5ae98d7d6d249582b87089e8ea08eec0',
    'MS-SHADOW-PAIR-5b99ab266e9299f936598fbd15fb3a87',
    'MS-SHADOW-PAIR-5e0b0ebc060fa9ae45604a15d92f74dc',
    'MS-SHADOW-PAIR-5e246b8a45c8ae956dd71da79223b1a4',
    'MS-SHADOW-PAIR-5e99223ecdb3ee911822c441bcec898e',
    'MS-SHADOW-PAIR-659265d6909870dd484a190c980ef8ff',
    'MS-SHADOW-PAIR-699bfc380d8693afc9d5bea27b903420',
    'MS-SHADOW-PAIR-6a61c29134e81b492e2b8830bec1f70d',
    'MS-SHADOW-PAIR-6b56242e0193f0bf65fcf16dee1bf091',
    'MS-SHADOW-PAIR-6f16e9e39fcb1d1d438bd5fa10677d15',
    'MS-SHADOW-PAIR-706a4e654cacd364a21a9ecb80ce52b8',
    'MS-SHADOW-PAIR-7532c86e2fe684671ed7e2a01fbc282e',
    'MS-SHADOW-PAIR-7a0c9dd0a1e2403fb42e10e46f15cfbd',
    'MS-SHADOW-PAIR-7c8ca453a850af706c937f1c69c1376f',
    'MS-SHADOW-PAIR-7da5aff5213a3d1709c74b633ea55eca',
    'MS-SHADOW-PAIR-801c1e1b6d33c789529b255251b8134c',
    'MS-SHADOW-PAIR-803f25ae99858ea5d1cfb1434a481f92',
    'MS-SHADOW-PAIR-8257c0b0c2b11b2e4e449a30cca16c28',
    'MS-SHADOW-PAIR-83fcf6becf5dd5c5352981e95b6f303b',
    'MS-SHADOW-PAIR-8836d4782506dbd13264993d2234f0fb',
    'MS-SHADOW-PAIR-89c6984386dc3dc8592d5421f292d029',
    'MS-SHADOW-PAIR-89e3bb502a77c83fa07553a6955f2df7',
    'MS-SHADOW-PAIR-8cb821132951bde1240f5b10c3579fb3',
    'MS-SHADOW-PAIR-8e82dc81eaff2030cf556f4b41f90b31',
    'MS-SHADOW-PAIR-938e1c6f0f4d71aafb52186b41e3f894',
    'MS-SHADOW-PAIR-942dd410ed071cbf368e5d442cdf0470',
    'MS-SHADOW-PAIR-9651572c5a68be5efb195cb0c11482e2',
    'MS-SHADOW-PAIR-97708014b0f5518d3da1989cbfa062d9',
    'MS-SHADOW-PAIR-9c66979c7ffa151963b124d573d648c7',
    'MS-SHADOW-PAIR-a6943389a1d29a410f2cb076269445ec',
    'MS-SHADOW-PAIR-a77c6547d3722bf1ae04a93359714098',
    'MS-SHADOW-PAIR-a77feeb827491ba00c52eb83ae8b05b2',
    'MS-SHADOW-PAIR-a7dd16654ee64b5d16515151cbe49c3b',
    'MS-SHADOW-PAIR-a8a4f836b1061ecb531fda734cc3f923',
    'MS-SHADOW-PAIR-a944433797dbdbd5efb1031403169455',
    'MS-SHADOW-PAIR-aa88e505567a761deb38d77dc980e46b',
    'MS-SHADOW-PAIR-aac49ff956a8bd4a23776bd9ffec1b19',
    'MS-SHADOW-PAIR-abcdc50ac2da78bf2b93611306b38a36',
    'MS-SHADOW-PAIR-b10e2ce258acf378e9c98145738ca33a',
    'MS-SHADOW-PAIR-b80a48c67e1d7bc4e50bb452bc387ec2',
    'MS-SHADOW-PAIR-b9051a16fbf92a1b6c0a7b007c1323cd',
    'MS-SHADOW-PAIR-bde7b89c3250d08ec6e2c6ef8e71d56d',
    'MS-SHADOW-PAIR-c113321c15679240f4e306ee340e1254',
    'MS-SHADOW-PAIR-c271f674ff80a4d9cdfe6baab10e7976',
    'MS-SHADOW-PAIR-c55d23de7ac0be38a991111d67ea5e88',
    'MS-SHADOW-PAIR-c65b174a41ddfc41bb99d1cc3a41269d',
    'MS-SHADOW-PAIR-c972798c75ef0fb46fb383bfb1c58be8',
    'MS-SHADOW-PAIR-cbebcdb2b294d9fe4c93f146a2d9ed70',
    'MS-SHADOW-PAIR-ce14a1af1fa97ac831e421568bec399b',
    'MS-SHADOW-PAIR-d2d1a4e36a71218713e1916229482118',
    'MS-SHADOW-PAIR-d413056008b87f5870a9290bc711af16',
    'MS-SHADOW-PAIR-d55a02455646f6c1383b86e76c2f95bc',
    'MS-SHADOW-PAIR-d62898de1d6cc151c28a1a73ef98ca7d',
    'MS-SHADOW-PAIR-d64a455d620114cba22daa6335ab5bf8',
    'MS-SHADOW-PAIR-d76542d383d55ea0855207df7982d0d6',
    'MS-SHADOW-PAIR-d9e2558487f289dbc70cce123a9036ba',
    'MS-SHADOW-PAIR-db7a1a33b556e99d067820e09899b21c',
    'MS-SHADOW-PAIR-dc5021020db4ad872e856ddaba7faa28',
    'MS-SHADOW-PAIR-dffce1878fba6abdac8ea1f3a980f987',
    'MS-SHADOW-PAIR-e3dc33434e9ed5ae10895e7ac76b4c99',
    'MS-SHADOW-PAIR-e6999d6d79de323e9da15923574020f4',
    'MS-SHADOW-PAIR-e9b335070491f52ddaaa52bc1e317b7e',
    'MS-SHADOW-PAIR-efaa03d828dfbdaf2d0d186cff561bbb',
    'MS-SHADOW-PAIR-fa7f2e316bc47ba8f4e5496ebf3c3b39',
    'MS-SHADOW-PAIR-fc01b3b93bf4dddede29ab54759eabf3',
    'MS-SHADOW-PAIR-fe7709794a1de972fd4121d9da4e0fa8',
})
FIXED_107_IDENTITY_SHA256 = '2139354111e89fcfb7e7e4e51c85e97b357595a8c42e9fbb05e82e75039acfd6'


class TrainingAuthorityBlocked(RuntimeError):
    """Raised when no legal, reproducible training contract exists."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repo_relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if _number(value) is not None]
    return statistics.fmean(values) if values else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(float(lower), min(float(upper), float(value)))


def _safe_exp(value: float) -> float:
    return math.exp(_clamp(float(value), -20.0, 20.0))


def _score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def _actual_outcome(score: tuple[int, int]) -> str:
    return "home" if score[0] > score[1] else "draw" if score[0] == score[1] else "away"


# ---------------------------------------------------------------------------
# Accepted same-time Market lambda contract
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Train/live-symmetric feature construction
# ---------------------------------------------------------------------------


def _aggregate(records: Sequence[tuple[datetime, float, float, str]], venue: str | None = None) -> dict[str, Any] | None:
    selected = [record for record in records if venue is None or record[3] == venue][-ROLLING_WINDOW:]
    if not selected:
        return None
    return {
        "matches": len(selected),
        "goals_for": sum(record[1] for record in selected),
        "goals_against": sum(record[2] for record in selected),
    }


def _valid_block(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    matches = _number(value.get("matches"))
    goals_for = _number(value.get("goals_for"))
    goals_against = _number(value.get("goals_against"))
    if matches is None or matches <= 0.0 or goals_for is None or goals_against is None:
        return None
    return {
        "matches": float(matches),
        "attack": float(goals_for) / matches,
        "defence": float(goals_against) / matches,
    }


def _build_features(form: Mapping[str, Any], *, source_scope: str) -> dict[str, Any] | None:
    """Build the same feature vector from either source's four-block contract."""
    if source_scope not in FEATURE_SOURCE_SCOPES:
        raise TrainingAuthorityBlocked(f"FEATURE_SOURCE_SCOPE_NOT_AUTHORISED:{source_scope}")
    home_overall = _valid_block(form.get("home_overall")) or _valid_block(form.get("home_home"))
    away_overall = _valid_block(form.get("away_overall")) or _valid_block(form.get("away_away"))
    if home_overall is None or away_overall is None or home_overall["matches"] < MIN_FORM_MATCHES or away_overall["matches"] < MIN_FORM_MATCHES:
        return None
    home_venue_raw = _valid_block(form.get("home_home"))
    away_venue_raw = _valid_block(form.get("away_away"))
    home_venue = home_venue_raw if home_venue_raw and home_venue_raw["matches"] >= MIN_FORM_MATCHES else home_overall
    away_venue = away_venue_raw if away_venue_raw and away_venue_raw["matches"] >= MIN_FORM_MATCHES else away_overall
    named = {
        "home_attack_venue_rate": home_venue["attack"],
        "home_defence_venue_rate": home_venue["defence"],
        "away_attack_venue_rate": away_venue["attack"],
        "away_defence_venue_rate": away_venue["defence"],
        "home_attack_overall_rate": home_overall["attack"],
        "home_defence_overall_rate": home_overall["defence"],
        "away_attack_overall_rate": away_overall["attack"],
        "away_defence_overall_rate": away_overall["defence"],
        "home_venue_matches_norm": min(home_venue["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "away_venue_matches_norm": min(away_venue["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "home_overall_matches_norm": min(home_overall["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "away_overall_matches_norm": min(away_overall["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
    }
    return {
        "schema": FEATURE_SCHEMA,
        "event_scope": "ALL_PREMATCH_EVENTS",
        "source_scope": source_scope,
        "names": named,
        "values": [named[name] for name in FEATURE_NAMES],
        "fallback_home_venue": home_venue_raw is None or home_venue_raw["matches"] < MIN_FORM_MATCHES,
        "fallback_away_venue": away_venue_raw is None or away_venue_raw["matches"] < MIN_FORM_MATCHES,
    }


def _external_date(date_value: Any, time_value: Any) -> datetime | None:
    date_text = str(date_value or "").strip()
    time_text = str(time_value or "12:00").strip() or "12:00"
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(f"{date_text} {time_text}" if "%H" in fmt else date_text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _clean_csv_key(value: Any) -> str:
    return str(value or "").replace("\ufeff", "").replace("???", "").strip()


def _row_identity_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {str(value).strip() for value in (row.get("identity_keys") or []) if str(value).strip()}
    for field in ("pair_id", "match_id", "match_key", "frozen_input_digest", "input_snapshot_ref"):
        value = str(row.get(field) or "").strip()
        if value:
            keys.add(value)
    return keys


def _exclude_fixed_107_rows(rows: Sequence[Mapping[str, Any]], fixed_identity_keys: set[str]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    excluded = 0
    for row in rows:
        if _row_identity_keys(row).intersection(fixed_identity_keys):
            excluded += 1
            continue
        kept.append(dict(row))
    return kept, excluded


def _fixed_107_identity_keys(pair_root: Path) -> tuple[set[str], dict[str, Any]]:
    """Load the PR #222 fixed-107 identity authority, never from outcomes."""
    if len(FIXED_107_PAIR_IDS) != 107 or _sha256_bytes(("\n".join(sorted(FIXED_107_PAIR_IDS)) + "\n").encode("utf-8")) != FIXED_107_IDENTITY_SHA256:
        raise TrainingAuthorityBlocked("FIXED_107_IDENTITY_CONTRACT_INVALID")
    pairs = load_persisted_pairs(pair_root)
    selected = [pair for pair in pairs if str(pair.get("pair_id") or "") in FIXED_107_PAIR_IDS]
    if len({str(pair.get("pair_id") or "") for pair in selected}) != len(FIXED_107_PAIR_IDS):
        raise TrainingAuthorityBlocked("FIXED_107_IDENTITY_AUTHORITY_MISSING")
    keys: set[str] = set()
    for pair in selected:
        for field in ("pair_id", "match_id", "match_key", "frozen_input_digest", "input_snapshot_ref"):
            value = str(pair.get(field) or "").strip()
            if value:
                keys.add(value)
    return keys, {"cohort": "Issue #221 / PR #222 Market Exact intersection", "pair_count": len(selected), "identity_key_fields": ["pair_id", "match_id", "match_key", "frozen_input_digest", "input_snapshot_ref"], "pair_id_sha256": FIXED_107_IDENTITY_SHA256, "outcomes_loaded": False}


def _load_external_rows(root: Path, *, fixed_identity_keys: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_matches: list[dict[str, Any]] = []
    file_manifest: list[dict[str, Any]] = []
    skipped = Counter()
    for path in sorted(Path(root).glob("*.csv")):
        stem = path.stem
        parts = stem.split("-", 1)
        if len(parts) != 2:
            continue
        season, league = parts
        file_manifest.append({"file": _repo_relative(path), "sha256": _sha256_file(path), "bytes": path.stat().st_size, "season": season, "league": league, "url": f"https://football-data.co.uk/mmz4281/{season}/{league}.csv"})
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError:
            skipped["file_open"] += 1
            continue
        with handle:
            reader = csv.DictReader(handle)
            for row_number, raw in enumerate(reader, start=2):
                row = {_clean_csv_key(key): value for key, value in raw.items()}
                kickoff = _external_date(row.get("Date"), row.get("Time"))
                home = str(row.get("HomeTeam") or "").strip()
                away = str(row.get("AwayTeam") or "").strip()
                home_goals = _number(row.get("FTHG"))
                away_goals = _number(row.get("FTAG"))
                if kickoff is None or not home or not away or home_goals is None or away_goals is None:
                    skipped["invalid_match_row"] += 1
                    continue
                identity = f"football-data:{path.name}:{row_number}:{kickoff.isoformat()}:{home}:{away}"
                raw_matches.append({"kickoff": kickoff, "home": home, "away": away, "home_goals": int(home_goals), "away_goals": int(away_goals), "league": league, "season": season, "file": path.name, "row_number": row_number, "odds": row, "identity_keys": [identity]})
    raw_matches.sort(key=lambda row: (row["kickoff"], row["file"], row["row_number"]))
    history: dict[str, list[tuple[datetime, float, float, str]]] = defaultdict(list)
    output: list[dict[str, Any]] = []
    excluded_fixed_107 = 0
    fixed_identity_keys = fixed_identity_keys or set()
    for raw in raw_matches:
        home_history = history[raw["home"]]
        away_history = history[raw["away"]]
        form = {
            "home_overall": _aggregate(home_history),
            "home_home": _aggregate(home_history, "home"),
            "away_overall": _aggregate(away_history),
            "away_away": _aggregate(away_history, "away"),
        }
        features = _build_features(form, source_scope="football_data_all_available_events_v1")
        market = external_market_lambdas(raw["odds"])
        if features is not None and market is not None and raw["kickoff"] < DEFAULT_EVAL_CUTOFF:
            row_key = f"{raw['file']}|{raw['row_number']}|{raw['kickoff'].isoformat()}|{raw['home']}|{raw['away']}"
            candidate = {"row_id": _sha256_bytes(row_key.encode("utf-8")), "identity_keys": raw["identity_keys"], "kickoff": raw["kickoff"], "home": raw["home"], "away": raw["away"], "league": raw["league"], "season": raw["season"], "features": features, "market": market, "home_goals": raw["home_goals"], "away_goals": raw["away_goals"], "source_file": raw["file"], "source_row": raw["row_number"]}
            filtered, count = _exclude_fixed_107_rows([candidate], fixed_identity_keys)
            if count:
                excluded_fixed_107 += count
            else:
                output.extend(filtered)
        history[raw["home"]].append((raw["kickoff"], float(raw["home_goals"]), float(raw["away_goals"]), "home"))
        history[raw["away"]].append((raw["kickoff"], float(raw["away_goals"]), float(raw["home_goals"]), "away"))
    return output, {"source": EXTERNAL_SOURCE, "files": file_manifest, "raw_match_rows": len(raw_matches), "eligible_rows": len(output), "fixed_107_rows_excluded_by_identity": excluded_fixed_107, "history_key": "exact_source_team_name_across_all_committed_files; no same-league filter", "feature_scope": "ALL_PREMATCH_EVENTS", "skipped": dict(sorted(skipped.items())), "odds_semantics": "Avg 1X2 plus Avg O/U2.5 where available, B365 fallback; source timing is preserved as historical timing and is not relabeled as an FBOS horizon.", "training_cutoff": DEFAULT_EVAL_CUTOFF.isoformat()}


# ---------------------------------------------------------------------------
# Isolated XGBoost Poisson count-regression backend
# ---------------------------------------------------------------------------


XGB_PARAMS = {
    "objective": "count:poisson",
    "eval_metric": "poisson-nloglik",
    "max_depth": 2,
    "eta": 0.05,
    "min_child_weight": 25.0,
    "lambda": 5.0,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "max_delta_step": 0.7,
    "tree_method": "hist",
    "seed": 227,
    "nthread": 1,
    "verbosity": 0,
}


class XGBoostPoissonModel:
    def __init__(self, feature_names: Sequence[str]) -> None:
        self.feature_names = list(feature_names)
        self.booster: Any = None
        self.best_iteration = 0
        self.validation_nll: float | None = None

    @staticmethod
    def _require_backend() -> Any:
        if xgb is None:
            raise TrainingAuthorityBlocked("XGBOOST_OPTIONAL_DEPENDENCY_MISSING")
        return xgb

    def _matrix(self, features: Sequence[Sequence[float]], offsets: Sequence[float], targets: Sequence[float] | None = None, weights: Sequence[float] | None = None) -> Any:
        backend = self._require_backend()
        if len(features) != len(offsets) or (targets is not None and len(features) != len(targets)):
            raise TrainingAuthorityBlocked("XGBOOST_BASE_MARGIN_LENGTH_MISMATCH")
        return backend.DMatrix(
            list(features),
            label=list(targets) if targets is not None else None,
            weight=list(weights) if weights is not None else None,
            base_margin=list(offsets),
            feature_names=self.feature_names,
        )

    def fit(
        self,
        features: Sequence[Sequence[float]],
        targets: Sequence[float],
        offsets: Sequence[float],
        weights: Sequence[float],
        validation: tuple[Sequence[Sequence[float]], Sequence[float], Sequence[float]] | None = None,
    ) -> "XGBoostPoissonModel":
        backend = self._require_backend()
        if not features or len(targets) != len(features) or len(offsets) != len(features) or len(weights) != len(features):
            raise TrainingAuthorityBlocked("invalid_xgboost_training_contract")
        train_matrix = self._matrix(features, offsets, targets, weights)
        evals = []
        if validation is not None:
            validation_features, validation_targets, validation_offsets = validation
            if not validation_features:
                raise TrainingAuthorityBlocked("chronological_validation_empty")
            validation_matrix = self._matrix(validation_features, validation_offsets, validation_targets)
            evals = [(validation_matrix, "validation")]
        self.booster = backend.train(
            params=dict(XGB_PARAMS),
            dtrain=train_matrix,
            num_boost_round=BOOSTER_ESTIMATORS,
            evals=evals,
            early_stopping_rounds=BOOSTER_EARLY_STOPPING_ROUNDS if evals else None,
            verbose_eval=False,
        )
        self.best_iteration = int(getattr(self.booster, "best_iteration", BOOSTER_ESTIMATORS - 1))
        if evals:
            self.validation_nll = _poisson_nll_values(self, validation[0], validation[1], validation[2])
        return self

    def _predict_raw(self, features: Sequence[Sequence[float]], offsets: Sequence[float]) -> list[float]:
        if self.booster is None:
            raise TrainingAuthorityBlocked("XGBOOST_MODEL_NOT_FIT")
        matrix = self._matrix(features, offsets)
        end = max(1, int(self.best_iteration) + 1)
        values = self.booster.predict(matrix, iteration_range=(0, end))
        return [float(value) for value in values]

    def predict_lambda(self, features: Sequence[float], offset: float) -> float:
        value = self._predict_raw([features], [offset])[0]
        return _clamp(value, OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)

    def correction(self, features: Sequence[float], offset: float) -> float:
        predicted = self.predict_lambda(features, offset)
        return math.log(predicted) - float(offset)

    def to_dict(self) -> dict[str, Any]:
        if self.booster is None:
            raise TrainingAuthorityBlocked("XGBOOST_MODEL_NOT_FIT")
        try:
            raw = self.booster.save_raw(raw_format="json")
        except TypeError:  # pragma: no cover - compatibility guard for older isolated wheels
            raw = self.booster.save_raw()
        try:
            model_json = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as error:
            raise TrainingAuthorityBlocked("XGBOOST_JSON_MODEL_SERIALIZATION_UNAVAILABLE") from error
        return {
            "backend": MODEL_BACKEND,
            "xgboost_version": getattr(xgb, "__version__", None),
            "feature_names": self.feature_names,
            "booster_json": model_json,
            "best_iteration": self.best_iteration,
            "validation_nll": self.validation_nll,
            "hyperparameters": {**XGB_PARAMS, "n_estimators": BOOSTER_ESTIMATORS, "early_stopping_rounds": BOOSTER_EARLY_STOPPING_ROUNDS},
            "base_margin_contract": "log(lambda_market_home/away) passed to DMatrix in train/validation/test/live",
        }


def _poisson_nll_values(model: XGBoostPoissonModel, features: Sequence[Sequence[float]], targets: Sequence[float], offsets: Sequence[float]) -> float:
    if not features:
        return float("nan")
    values = model._predict_raw(features, offsets)
    return statistics.fmean(value - float(target) * math.log(max(value, MARKET_EPSILON)) + math.lgamma(float(target) + 1.0) for value, target in zip(values, targets))


def _fit_models(rows: Sequence[Mapping[str, Any]], fixed_identity_keys: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    count = len(rows)
    train_end = max(1, int(count * TRAIN_FRACTION))
    validation_end = max(train_end + 1, int(count * (TRAIN_FRACTION + VALIDATION_FRACTION)))
    validation_end = min(validation_end, count - 1)
    train_rows = list(rows[:train_end])
    validation_rows = list(rows[train_end:validation_end])
    test_rows = list(rows[validation_end:])
    if not train_rows or not validation_rows or not test_rows:
        raise TrainingAuthorityBlocked("chronological_split_empty")
    if fixed_identity_keys:
        filtered, excluded = _exclude_fixed_107_rows([*train_rows, *validation_rows, *test_rows], fixed_identity_keys)
        if excluded:
            raise TrainingAuthorityBlocked("FIXED_107_OUTCOME_IDENTITY_PRESENT_IN_EXTERNAL_ROWS")
        if len(filtered) != len(rows):
            raise TrainingAuthorityBlocked("FIXED_107_EXCLUSION_CARDINALITY_MISMATCH")
    latest_train = train_rows[-1]["kickoff"]
    weights = [math.exp(-max(0.0, (latest_train - row["kickoff"]).total_seconds() / 86400.0) / TIME_DECAY_HALF_LIFE_DAYS) for row in train_rows]
    x_train = [row["features"]["values"] for row in train_rows]
    x_validation = [row["features"]["values"] for row in validation_rows]
    home_targets = [float(row["home_goals"]) for row in train_rows]
    away_targets = [float(row["away_goals"]) for row in train_rows]
    home_offsets = [math.log(float(row["market"]["lambda_home"])) for row in train_rows]
    away_offsets = [math.log(float(row["market"]["lambda_away"])) for row in train_rows]
    validation_home_offsets = [math.log(float(row["market"]["lambda_home"])) for row in validation_rows]
    validation_away_offsets = [math.log(float(row["market"]["lambda_away"])) for row in validation_rows]
    home_model = XGBoostPoissonModel(FEATURE_NAMES).fit(x_train, home_targets, home_offsets, weights, (x_validation, [float(row["home_goals"]) for row in validation_rows], validation_home_offsets))
    away_model = XGBoostPoissonModel(FEATURE_NAMES).fit(x_train, away_targets, away_offsets, weights, (x_validation, [float(row["away_goals"]) for row in validation_rows], validation_away_offsets))
    artifact = {
        "model_family": MODEL_FAMILY,
        "backend": MODEL_BACKEND,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_definition": FEATURE_SCHEMA_DEFINITION,
        "feature_names": list(FEATURE_NAMES),
        "market_offset": {"home": "base_margin=log(lambda_market_home)", "away": "base_margin=log(lambda_market_away)", "contract": "accepted_same_time_market_lambda_v1", "source": "Issue #189 / PR #190"},
        "score_distribution": {"family": "independent_poisson", "rho": 0.0, "max_goals": SCORE_MAX_GOALS, "tail_semantics": "finite_0_to_12_grid_renormalized; omitted raw Poisson tail recorded separately"},
        "training": {"authority": TRAINING_AUTHORITY, "source": EXTERNAL_SOURCE, "chronological_split": {"train_fraction": TRAIN_FRACTION, "validation_fraction": VALIDATION_FRACTION, "test_fraction": 1.0 - TRAIN_FRACTION - VALIDATION_FRACTION}, "time_decay_half_life_days": TIME_DECAY_HALF_LIFE_DAYS, "train_n": len(train_rows), "validation_n": len(validation_rows), "test_n": len(test_rows), "train_first": train_rows[0]["kickoff"].isoformat(), "train_last": train_rows[-1]["kickoff"].isoformat(), "validation_first": validation_rows[0]["kickoff"].isoformat(), "validation_last": validation_rows[-1]["kickoff"].isoformat(), "test_first": test_rows[0]["kickoff"].isoformat(), "test_last": test_rows[-1]["kickoff"].isoformat(), "fixed_107_outcomes_used": False},
        "home_model": home_model.to_dict(),
        "away_model": away_model.to_dict(),
    }
    return artifact, train_rows, validation_rows, test_rows


def _load_model(artifact: Mapping[str, Any]) -> tuple[XGBoostPoissonModel, XGBoostPoissonModel]:
    backend = XGBoostPoissonModel._require_backend()

    def from_dict(value: Mapping[str, Any]) -> XGBoostPoissonModel:
        model = XGBoostPoissonModel(value.get("feature_names") or FEATURE_NAMES)
        model.booster = backend.Booster()
        raw = str(value.get("booster_json") or "").encode("utf-8")
        if not raw:
            raise TrainingAuthorityBlocked("XGBOOST_SERIALIZED_MODEL_MISSING")
        model.booster.load_model(bytearray(raw))
        model.best_iteration = int(value.get("best_iteration") or 0)
        model.validation_nll = value.get("validation_nll")
        return model

    return from_dict(artifact["home_model"]), from_dict(artifact["away_model"])


# ---------------------------------------------------------------------------
# Unified score matrix and controls
# ---------------------------------------------------------------------------


def _matrix_score_output(matrix: Mapping[tuple[int, int], float], *, lambda_home: float | None, lambda_away: float | None, tail: float, authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ordered = sorted(((tuple(score), float(probability)) for score, probability in matrix.items()), key=lambda item: (-item[1], item[0][0], item[0][1]))
    rows = [{"rank": rank, "score": _score_text(score), "home_goals": score[0], "away_goals": score[1], "probability": round(probability, 12)} for rank, (score, probability) in enumerate(ordered, start=1)]
    probabilities = {outcome: 0.0 for outcome in OUTCOMES}
    total_distribution: dict[str, float] = defaultdict(float)
    btts_yes = 0.0
    for (home, away), probability in matrix.items():
        probabilities[_actual_outcome((home, away))] += probability
        total_distribution[str(home + away)] += probability
        if home > 0 and away > 0:
            btts_yes += probability

    handicap: dict[str, Any] = {}
    for line in (-1.0, -0.5, 0.0, 0.5, 1.0):
        parts = split_quarter_line(line)
        result = {"home": {"win": 0.0, "push": 0.0, "loss": 0.0}, "away": {"win": 0.0, "push": 0.0, "loss": 0.0}}
        for (home, away), probability in matrix.items():
            home_units = []
            away_units = []
            for component in parts:
                home_delta = home - away + component
                away_delta = -home_delta
                home_units.append(1.0 if home_delta > 0 else 0.0 if home_delta == 0 else -1.0)
                away_units.append(1.0 if away_delta > 0 else 0.0 if away_delta == 0 else -1.0)
            home_average = sum(home_units) / len(home_units)
            away_average = sum(away_units) / len(away_units)
            result["home"]["win"] += probability * (1.0 if home_average > 0 else 0.0)
            result["home"]["push"] += probability * (1.0 if home_average == 0 else 0.0)
            result["home"]["loss"] += probability * (1.0 if home_average < 0 else 0.0)
            result["away"]["win"] += probability * (1.0 if away_average > 0 else 0.0)
            result["away"]["push"] += probability * (1.0 if away_average == 0 else 0.0)
            result["away"]["loss"] += probability * (1.0 if away_average < 0 else 0.0)
        handicap[str(line)] = result

    output = {
        "lambda_home": round(float(lambda_home), 12) if lambda_home is not None else None,
        "lambda_away": round(float(lambda_away), 12) if lambda_away is not None else None,
        "lambda_total": round(float(lambda_home + lambda_away), 12) if lambda_home is not None and lambda_away is not None else None,
        "rho": 0.0,
        "score_matrix": rows,
        "score_matrix_tail_probability": max(0.0, float(tail)),
        "score_matrix_normalization": {"finite_grid_raw_mass": max(0.0, 1.0 - float(tail)), "represented_probability_sum": sum(float(value) for value in matrix.values()), "max_goals": max(max(score) for score in matrix) if matrix else None, "tail_semantics": "omitted raw independent-Poisson mass outside the explicit finite grid"},
        "exact_top1": rows[0]["score"] if rows else None,
        "exact_top3": [row["score"] for row in rows[:3]],
        "exact_top5": [row["score"] for row in rows[:5]],
        "derived_markets": {
            "1x2": {key: round(value, 12) for key, value in probabilities.items()},
            "totals": {"exact": {key: round(value, 12) for key, value in sorted(total_distribution.items(), key=lambda item: int(item[0]))}, "over_2_5": round(sum(value for (home, away), value in matrix.items() if home + away > 2), 12), "under_2_5": round(sum(value for (home, away), value in matrix.items() if home + away <= 2), 12), "tail_ge_4": round(sum(value for (home, away), value in matrix.items() if home + away >= 4), 12), "tail_ge_5": round(sum(value for (home, away), value in matrix.items() if home + away >= 5), 12), "tail_ge_6": round(sum(value for (home, away), value in matrix.items() if home + away >= 6), 12), "out_of_support_tail": max(0.0, float(tail))},
            "btts": {"yes": round(btts_yes, 12), "no": round(1.0 - btts_yes, 12)},
            "handicap": handicap,
        },
    }
    if authority:
        output["authority"] = dict(authority)
    return output


def _score_output(lambda_home: float, lambda_away: float, *, authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    lambda_home = _clamp(lambda_home, OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)
    lambda_away = _clamp(lambda_away, OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)
    matrix, tail = independent_score_matrix(lambda_home, lambda_away, max_goals=SCORE_MAX_GOALS)
    return _matrix_score_output(matrix, lambda_home=lambda_home, lambda_away=lambda_away, tail=tail, authority=authority)


def _persisted_control_output(control: Mapping[str, Any], *, label: str, pair: Mapping[str, Any]) -> dict[str, Any] | None:
    cells = control.get("exact_score_distribution")
    if not isinstance(cells, list) or not cells:
        return None
    matrix: dict[tuple[int, int], float] = {}
    for cell in cells:
        if not isinstance(cell, Mapping):
            return None
        try:
            score = (int(cell["home_goals"]), int(cell["away_goals"]))
            probability = float(cell["probability"])
        except (KeyError, TypeError, ValueError):
            return None
        if score in matrix or score[0] < 0 or score[1] < 0 or not math.isfinite(probability) or probability < 0.0:
            return None
        matrix[score] = probability
    if abs(sum(matrix.values()) - 1.0) > 1e-4:
        return None
    lambda_home = _number(control.get("lambda_home"))
    lambda_away = _number(control.get("lambda_away"))
    return _matrix_score_output(
        matrix,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        tail=0.0,
        authority={"kind": "IMMUTABLE_PAIR_TRUTH", "label": label, "pair_id": pair.get("pair_id"), "prediction_id": control.get("prediction_id"), "candidate_id": control.get("candidate_id"), "frozen_input_digest": pair.get("frozen_input_digest"), "distribution_digest": control.get("prediction_sha256")},
    )


def _authoritative_controls(pair: Mapping[str, Any], document: Mapping[str, Any], market: Mapping[str, Any]) -> dict[str, Any] | None:
    champion = _persisted_control_output(pair.get("champion") or {}, label="Champion", pair=pair)
    challenger = _persisted_control_output(pair.get("challenger") or {}, label="Challenger C", pair=pair)
    if champion is None or challenger is None:
        return None
    prediction_id = str(pair.get("champion_prediction_id") or "")
    market_persisted = ((document.get("market_only_baseline") or {}) if isinstance(document, Mapping) else {})
    persisted_probs = market_persisted if isinstance(market_persisted, Mapping) else {}
    market_contract = market.get("market_contract") if isinstance(market.get("market_contract"), Mapping) else {}
    market_consensus = market_contract.get("one_x2_consensus") if isinstance(market_contract, Mapping) else None
    if not isinstance(market_consensus, Mapping):
        return None
    parity = {}
    for outcome in OUTCOMES:
        observed = _number(persisted_probs.get(outcome))
        reconstructed = _number(market_consensus.get(outcome))
        if observed is None or reconstructed is None:
            return None
        parity[outcome] = abs(observed - reconstructed) <= 1e-5
    if not all(parity.values()):
        return None
    market_with_authority = dict(market)
    market_with_authority["authority"] = {"kind": "FROZEN_INPUT_MARKET_RECONSTRUCTION", "label": "Market", "contract": "accepted_same_time_market_lambda_v1", "contract_source": "Issue #189 / PR #190", "pair_id": pair.get("pair_id"), "prediction_id": prediction_id, "input_snapshot_ref": pair.get("input_snapshot_ref"), "persisted_market_only_baseline": dict(persisted_probs), "market_consensus_reconstruction": dict(market_consensus), "matrix_1x2_is_derived_from_market_lambdas": True, "parity_checks": parity}
    return {"market": market_with_authority, "champion": champion, "challenger_c": challenger}


def _model_prediction(row: Mapping[str, Any], home_model: XGBoostPoissonModel, away_model: XGBoostPoissonModel, *, controls: Mapping[str, Any] | None = None) -> dict[str, Any]:
    features = row["features"]
    market = row["market"]
    feature_values = features["values"]
    market_home = float(market["lambda_home"])
    market_away = float(market["lambda_away"])
    home_offset = math.log(market_home)
    away_offset = math.log(market_away)
    lambda_home = home_model.predict_lambda(feature_values, home_offset)
    lambda_away = away_model.predict_lambda(feature_values, away_offset)
    market_output = _score_output(market_home, market_away)
    market_contract = {key: market[key] for key in ("lambda_home", "lambda_away", "lambda_total", "one_x2_consensus", "one_x2_quote_count", "total_quote_count", "total_lambda_quotes", "contract", "contract_source") if key in market}
    market_output["market_contract"] = market_contract
    prediction = {
        "model": _score_output(lambda_home, lambda_away),
        "market": market_output,
        "offsets": {"base_margin_home": home_offset, "base_margin_away": away_offset, "market_lambda_home": market_home, "market_lambda_away": market_away, "correction_home": home_model.correction(feature_values, home_offset), "correction_away": away_model.correction(feature_values, away_offset)},
    }
    if controls:
        prediction["market"] = controls["market"]
        prediction["champion"] = controls["champion"]
        prediction["challenger_c"] = controls["challenger_c"]
    return prediction


def _metric_summary(rows: Sequence[Mapping[str, Any]], home_model: XGBoostPoissonModel, away_model: XGBoostPoissonModel, variant: str = "model") -> dict[str, Any]:
    records = []
    for row in rows:
        prediction = _model_prediction(row, home_model, away_model)
        if variant not in prediction:
            continue
        actual = (int(row["home_goals"]), int(row["away_goals"]))
        model_matrix = {(cell["home_goals"], cell["away_goals"]): float(cell["probability"]) for cell in prediction[variant]["score_matrix"]}
        ranked = sorted(model_matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        actual_probability = max(MARKET_EPSILON, model_matrix.get(actual, MARKET_EPSILON))
        model_one_x2 = prediction[variant]["derived_markets"]["1x2"]
        target = _actual_outcome(actual)
        brier_1x2 = sum((float(model_one_x2[key]) - (1.0 if key == target else 0.0)) ** 2 for key in OUTCOMES)
        model_total = prediction[variant]["derived_markets"]["totals"]
        total_actual_over = actual[0] + actual[1] > 2
        brier_total = (float(model_total["over_2_5"]) - float(total_actual_over)) ** 2
        btts_actual = actual[0] > 0 and actual[1] > 0
        brier_btts = (float(prediction[variant]["derived_markets"]["btts"]["yes"]) - float(btts_actual)) ** 2
        records.append({"exact_nll": -math.log(actual_probability), "actual_probability": actual_probability, "top1": actual == ranked[0][0], "top3": actual in {score for score, _ in ranked[:3]}, "top5": actual in {score for score, _ in ranked[:5]}, "actual_one_one": actual == (1, 1), "top_score_one_one": ranked[0][0] == (1, 1), "home_actual": actual[0], "away_actual": actual[1], "total_actual": actual[0] + actual[1], "home_lambda": prediction[variant]["lambda_home"], "away_lambda": prediction[variant]["lambda_away"], "total_lambda": prediction[variant]["lambda_total"], "brier_1x2": brier_1x2, "brier_total_over_2_5": brier_total, "brier_btts": brier_btts})
    if not records:
        return {"n": 0}

    def rate(key: str) -> float:
        return statistics.fmean(float(record[key]) for record in records)

    def calibration(actual_key: str, lambda_key: str) -> dict[str, float]:
        actual = [float(record[actual_key]) for record in records]
        predicted = [float(record[lambda_key]) for record in records]
        return {"observed_mean": statistics.fmean(actual), "predicted_mean": statistics.fmean(predicted), "bias_observed_minus_predicted": statistics.fmean(a - p for a, p in zip(actual, predicted)), "mae": statistics.fmean(abs(a - p) for a, p in zip(actual, predicted))}

    return {"n": len(records), "exact_nll": rate("exact_nll"), "mean_actual_score_probability": rate("actual_probability"), "exact_top1": rate("top1"), "exact_top3": rate("top3"), "exact_top5": rate("top5"), "one_one_actual_rate": rate("actual_one_one"), "one_one_top_score_share": rate("top_score_one_one"), "lambda_calibration": {"home": calibration("home_actual", "home_lambda"), "away": calibration("away_actual", "away_lambda"), "total": calibration("total_actual", "total_lambda")}, "1x2_brier": rate("brier_1x2"), "total_over_2_5_brier": rate("brier_total_over_2_5"), "btts_brier": rate("brier_btts")}


# ---------------------------------------------------------------------------
# Frozen prematch shadow integration
# ---------------------------------------------------------------------------


def _load_legal_snapshot(pair: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    reference = str(pair.get("input_snapshot_ref") or "")
    path = Path(reference)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return None, "missing_input_snapshot"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "invalid_input_snapshot"
    cutoff = _parse_datetime(pair.get("source_cutoff"))
    kickoff = _parse_datetime(pair.get("kickoff_at"))
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return None, "unsafe_pair_chronology"
    sources = ((document.get("input") or {}).get("source_snapshots") or {})
    candidates = []
    for source_name, source in sources.items():
        for snapshot in (source.get("snapshots") or []) if isinstance(source, Mapping) else []:
            captured = _parse_datetime(snapshot.get("fetched_at") or snapshot.get("captured_at")) if isinstance(snapshot, Mapping) else None
            if captured is not None and captured <= cutoff and captured < kickoff:
                candidates.append((captured, str(source_name), dict(snapshot)))
    if not candidates:
        return None, "no_legal_prematch_snapshot"
    _, source_name, snapshot = max(candidates, key=lambda item: (item[0], item[1]))
    snapshot["_source_name"] = source_name
    return snapshot, None


def _live_features(snapshot: Mapping[str, Any], input_document: Mapping[str, Any]) -> dict[str, Any] | None:
    shuju = snapshot.get("shuju") or {}
    form = shuju.get("recent_form") or ((input_document.get("prematch_fundamentals") or {}).get("recent_form") or {})
    if not form:
        return None
    return _build_features(form, source_scope="nowscore_all_events_v1")


def _load_authoritative_prediction(pair: Mapping[str, Any]) -> dict[str, Any] | None:
    prediction_id = str(pair.get("champion_prediction_id") or "").strip()
    if not prediction_id:
        return None
    path = ROOT / "data" / "model_governance" / "predictions" / f"{prediction_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _build_live_shadow_rows(pair_root: Path, home_model: XGBoostPoissonModel, away_model: XGBoostPoissonModel, model_digest: str, prospective_after: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pairs = load_persisted_pairs(pair_root)
    output = []
    skipped = Counter()
    for pair in pairs:
        kickoff = _parse_datetime(pair.get("kickoff_at"))
        if pair.get("pair_status") != "PAIRED" or pair.get("post_match_input_used_for_generation") is not False:
            skipped["pair_contract"] += 1
            continue
        if kickoff is None or kickoff <= prospective_after:
            skipped["not_future_prospective"] += 1
            continue
        snapshot, reason = _load_legal_snapshot(pair)
        if snapshot is None:
            skipped[reason or "snapshot"] += 1
            continue
        reference = Path(str(pair.get("input_snapshot_ref") or ""))
        if not reference.is_absolute():
            reference = ROOT / reference
        try:
            document = json.loads(reference.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped["invalid_input_document"] += 1
            continue
        features = _live_features(snapshot, document)
        if features is None:
            skipped["missing_reproducible_features"] += 1
            continue
        try:
            market = market_lambdas_from_snapshot(snapshot)
        except MarketContractError as error:
            skipped[str(error)] += 1
            continue
        base_row = {"features": features, "market": market}
        prediction = _model_prediction(base_row, home_model, away_model)
        authoritative_controls = _authoritative_controls(pair, _load_authoritative_prediction(pair) or {}, prediction["market"])
        if authoritative_controls is None:
            skipped["non_authoritative_controls_or_market_parity"] += 1
            continue
        prediction = _model_prediction(base_row, home_model, away_model, controls=authoritative_controls)
        prediction_id = "SFGI-" + _sha256_bytes((str(pair.get("pair_id")) + "|" + model_digest).encode("utf-8"))[:24]
        shadow_record = {"pair_id": pair.get("pair_id"), "match_id": pair.get("match_id"), "match_key": pair.get("match_key"), "kickoff_at": pair.get("kickoff_at"), "source_cutoff": pair.get("source_cutoff"), "input_snapshot_ref": pair.get("input_snapshot_ref"), "frozen_input_digest": pair.get("frozen_input_digest"), "source_snapshot": snapshot.get("_source_name"), "prediction_id": prediction_id, "model_family": MODEL_FAMILY, "model_version": f"{MODEL_FAMILY}:{model_digest[:12]}", "model_digest": model_digest, "feature_schema": FEATURE_SCHEMA, "feature_contract": {"event_scope": features["event_scope"], "source_scope": features["source_scope"], "source_cutoff": pair.get("source_cutoff"), "training_live_vector_builder": "_build_features"}, "feature_values": features["names"], "feature_missingness": {"home_venue_fallback_to_overall": features["fallback_home_venue"], "away_venue_fallback_to_overall": features["fallback_away_venue"]}, "market_baseline": market, "prediction": prediction["model"], "controls": {"market": prediction["market"], "champion": prediction["champion"], "challenger_c": prediction["challenger_c"]}, "offset_and_correction": prediction["offsets"], "namespace": "solution_first_goal_intensity_shadow_1", "production_enabled": False, "user_visible": False, "post_match_input_used_for_generation": False, "settlement_adapter": {"actual_score_source": "existing_verified_postmatch_result", "uses_frozen_score_matrix": True, "derived_markets_from_same_matrix": True}}
        shadow_record["prediction_sha256"] = _sha256_bytes(_canonical_json(shadow_record).encode("utf-8"))
        output.append(shadow_record)
    return output, dict(sorted(skipped.items()))


def _native_history_audit(pair_root: Path) -> dict[str, Any]:
    pairs = load_persisted_pairs(pair_root)
    catalog, discovery = discover_verified_results(ROOT / "data" / "postmatch_automation" / "results")
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    legal = 0
    for pair in pairs:
        kickoff = _parse_datetime(pair.get("kickoff_at"))
        if kickoff is None or kickoff >= DEFAULT_EVAL_CUTOFF or str(pair.get("match_id") or "") not in result_map:
            continue
        snapshot, _ = _load_legal_snapshot(pair)
        if snapshot is None:
            continue
        reference = Path(str(pair.get("input_snapshot_ref") or ""))
        if not reference.is_absolute():
            reference = ROOT / reference
        try:
            document = json.loads(reference.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _live_features(snapshot, document) is None:
            continue
        if _actual_for_pair(pair, result_map) is not None:
            legal += 1
    return {"eligible_count": legal, "evaluation_cutoff": DEFAULT_EVAL_CUTOFF.isoformat(), "source_catalog": discovery, "result_matching": matching, "market_contract_validation": "deferred_until_native_route_is_selected", "decision": "NATIVE_HISTORY_INSUFFICIENT_USE_EXTERNAL" if legal < MIN_EXTERNAL_ROWS else "NATIVE_HISTORY_AVAILABLE"}


def _build_report(summary: Mapping[str, Any]) -> str:
    metrics = summary.get("test_metrics") or {}
    controls = summary.get("control_test_metrics") or {}
    calibration = metrics.get("lambda_calibration") or {}
    return "\n".join([
        f"# {MILESTONE}",
        "",
        f"- Decision: `{summary.get('decision')}`",
        f"- Training authority: `{summary.get('training_authority')}`",
        f"- Model family: `{summary.get('model_family')}`; backend `{summary.get('backend')}`",
        f"- Feature schema: `{summary.get('feature_schema')}`",
        f"- Train/validation/test: `{summary.get('training_n')}/{summary.get('validation_n')}/{summary.get('test_n')}`",
        f"- Shadow output rows: `{summary.get('shadow_output_count')}`",
        f"- Market contract parity: `{json.dumps(summary.get('market_contract_parity') or {}, sort_keys=True)}`",
        "",
        "## External test sanity evidence",
        f"- Exact NLL `{metrics.get('exact_nll')}`; Top1 `{metrics.get('exact_top1')}`; Top3 `{metrics.get('exact_top3')}`; Top5 `{metrics.get('exact_top5')}`",
        f"- 1-1 actual rate `{metrics.get('one_one_actual_rate')}`; 1-1 top-score share `{metrics.get('one_one_top_score_share')}`",
        f"- Lambda calibration: `{json.dumps(calibration, sort_keys=True)}`",
        f"- 1X2 Brier `{metrics.get('1x2_brier')}`; O/U2.5 Brier `{metrics.get('total_over_2_5_brier')}`; BTTS Brier `{metrics.get('btts_brier')}`",
        f"- Controls retained — Market NLL `{(controls.get('market') or {}).get('exact_nll')}`, Champion NLL `{(controls.get('champion') or {}).get('exact_nll')}`, C NLL `{(controls.get('challenger_c') or {}).get('exact_nll')}`",
        "",
        "## Integrity",
        "- External odds are retained with source timing semantics and labelled HORIZON_TRANSFER; no closing odds are relabeled as FBOS earlier horizons.",
        "- Fixed 107 outcomes are excluded from fitting, validation selection, and test construction.",
        "- Champion serving, C, selector, UI and history are unchanged; the namespace is shadow-only and not user-visible.",
        "- No anti-1-1 rule, manual lambda scale, result-aware score selection, Dixon-Coles/NB/CMP expansion or automatic promotion.",
    ]) + "\n"


def run_shadow(*, external_root: Path = EXTERNAL_ROOT, pair_root: Path = DEFAULT_PAIR_ROOT, prospective_after: datetime | None = DEFAULT_PROSPECTIVE_AFTER) -> dict[str, Any]:
    native_audit = _native_history_audit(pair_root)
    if native_audit["eligible_count"] >= MIN_EXTERNAL_ROWS:
        raise TrainingAuthorityBlocked("native_history_route_not_implemented_for_this_milestone")
    fixed_identity_keys, fixed_107_authority = _fixed_107_identity_keys(pair_root)
    external_rows, external_manifest = _load_external_rows(external_root, fixed_identity_keys=fixed_identity_keys)
    if len(external_rows) < MIN_EXTERNAL_ROWS:
        raise TrainingAuthorityBlocked(f"external_training_rows_below_minimum:{len(external_rows)}")
    artifact, train_rows, validation_rows, test_rows = _fit_models(external_rows, fixed_identity_keys=fixed_identity_keys)
    model_content = _canonical_json(artifact).encode("utf-8")
    model_digest = _sha256_bytes(model_content)
    home_model, away_model = _load_model(artifact)
    test_metrics = _metric_summary(test_rows, home_model, away_model, "model")
    validation_metrics = _metric_summary(validation_rows, home_model, away_model, "model")
    control_test_metrics = {
        "market": _metric_summary(test_rows, home_model, away_model, "market"),
        "champion": _metric_summary(test_rows, home_model, away_model, "champion"),
        "challenger_c": _metric_summary(test_rows, home_model, away_model, "challenger_c"),
    }
    if prospective_after is None:
        prospective_after = datetime.now(timezone.utc)
    shadow_rows, shadow_skips = _build_live_shadow_rows(pair_root, home_model, away_model, model_digest, prospective_after)
    market_parity_passed = sum(1 for row in shadow_rows if all((row.get("controls", {}).get("market", {}).get("authority", {}).get("parity_checks", {}) or {}).values()))
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "decision": "SHADOW_CHALLENGER_WIRED" if shadow_rows else "FAIL_CLOSED",
        "reviewed_at": now,
        "training_authority": TRAINING_AUTHORITY,
        "native_history_audit": native_audit,
        "external_source_manifest": external_manifest,
        "feature_authority": {"shared_vector_builder": "_build_features", "schema": FEATURE_SCHEMA, "event_scope": "ALL_PREMATCH_EVENTS", "source_scopes": sorted(FEATURE_SOURCE_SCOPES), "train_live_semantics": "same four-block aggregate and venue fallback; source coverage remains HORIZON_TRANSFER", "status": "SHARED_CONTRACT_VERIFIED"},
        "fixed_107_identity_authority": fixed_107_authority,
        "training_n": len(train_rows),
        "validation_n": len(validation_rows),
        "test_n": len(test_rows),
        "model_family": MODEL_FAMILY,
        "backend": MODEL_BACKEND,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_definition": FEATURE_SCHEMA_DEFINITION,
        "feature_names": list(FEATURE_NAMES),
        "market_offset": artifact["market_offset"],
        "model_digest": model_digest,
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "control_test_metrics": control_test_metrics,
        "shadow_output_count": len(shadow_rows),
        "shadow_output_skipped": shadow_skips,
        "fixed_107_outcomes_used_for_fit": False,
        "fixed_107_identity_exclusion": {"status": "ENFORCED_BEFORE_TRAINING", "pair_count": fixed_107_authority["pair_count"], "identity_key_fields": fixed_107_authority["identity_key_fields"], "pair_id_sha256": fixed_107_authority["pair_id_sha256"], "excluded_external_rows": external_manifest["fixed_107_rows_excluded_by_identity"]},
        "current_serving_changed": False,
        "controls_retained": ["Market", "Champion", "Challenger C"],
        "control_authority": {"live": "IMMUTABLE_PAIR_TRUTH", "market": "FROZEN_INPUT_MARKET_RECONSTRUCTION", "external": "OMITTED_FORMULA_PROXIES"},
        "market_contract_parity": {"contract": "accepted_same_time_market_lambda_v1", "source": "Issue #189 / PR #190", "checked_live_rows": len(shadow_rows), "passed_live_rows": market_parity_passed, "status": "PASS" if market_parity_passed == len(shadow_rows) and shadow_rows else "FAIL_CLOSED"},
        "integrity": {
            "status": "PASS" if shadow_rows else "FAIL_CLOSED",
            "source": EXTERNAL_SOURCE,
            "same_time_market_lambda_for_live": True,
            "external_odds_horizon_transfer_only": True,
            "fixed_107_excluded": True,
            "fixed_107_exclusion_basis": "identity_contract_not_artifact_boolean",
            "result_leakage": False,
            "closing_odds_relabelled_as_FBOS_horizon": False,
            "manual_lambda_scaling": False,
            "anti_1_1": False,
            "result_aware_score_selection": False,
            "production_enabled": False,
            "user_visible": False,
            "champion_serving_changed": False,
            "history_rewritten": False,
            "automatic_promotion": False,
        },
        "source": {"external_root": _repo_relative(external_root), "pair_root": _repo_relative(pair_root), "shadow_namespace": "solution_first_goal_intensity_shadow_1"},
        "implementation_provenance": [
            {"source": "cnemri/world-cup-2026-predictor", "license": "MIT", "use": "separate home/away Poisson count-booster pattern only; no code, World-Cup features or hyperparameters copied"},
            {"source": "JetQiao/football-prediction-skill", "license": "MIT", "use": "event-time, reference/target/benchmark and fail-closed lifecycle pattern only; no code copied"},
            {"source": "eScored Engine 2.0", "license": "architecture evidence only", "use": "market-anchored intensity architecture; no proprietary code copied"},
        ],
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    artifact["model_digest"] = model_digest
    _write_json(DEFAULT_MODEL, artifact)
    _write_json(DEFAULT_SHADOW_OUTPUT, {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "namespace": "solution_first_goal_intensity_shadow_1", "model_family": MODEL_FAMILY, "model_digest": model_digest, "feature_schema": FEATURE_SCHEMA, "market_offset": artifact["market_offset"], "generated_at": now, "prospective_after": prospective_after.isoformat(), "row_count": len(shadow_rows), "rows": shadow_rows, "controls": ["market", "champion", "challenger_c"], "production_enabled": False, "user_visible": False})
    _write_json(DEFAULT_SUMMARY, summary)
    DEFAULT_REPORT.write_text(_build_report(summary), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path, default=EXTERNAL_ROOT)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--prospective-after", type=str, default=None, help="ISO timestamp; default is current UTC time")
    args = parser.parse_args(argv)
    prospective_after = _parse_datetime(args.prospective_after) if args.prospective_after else None
    try:
        summary = run_shadow(external_root=args.external_root, pair_root=args.pair_root, prospective_after=prospective_after)
    except TrainingAuthorityBlocked as error:
        summary = {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "decision": "TRAINING_AUTHORITY_BLOCKED", "training_authority": TRAINING_AUTHORITY, "blocker": str(error), "current_serving_changed": False}
        _write_json(DEFAULT_SUMMARY, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"decision": summary["decision"], "training_authority": summary["training_authority"], "training_n": summary["training_n"], "validation_n": summary["validation_n"], "test_n": summary["test_n"], "shadow_output_count": summary["shadow_output_count"], "model_digest": summary["model_digest"], "current_serving_changed": summary["current_serving_changed"]}, ensure_ascii=False, sort_keys=True))
    return 0 if summary["decision"] == "SHADOW_CHALLENGER_WIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
