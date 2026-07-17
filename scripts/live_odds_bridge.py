#!/usr/bin/env python3
"""Local read-only receiver for live odds captured by the Chrome bridge.

The receiver intentionally has no code path that touches bankroll, open bets,
or lock state. It stores sanitized analysis-input events in an immutable,
datetime-named capture directory.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from live_ev_reprice import RepriceValidationError, evaluate_request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "live_odds_bridge" / "captures"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MODEL_VERSION = "v0.17.0"
MODULE_VERSION = "v0.8.1"

CORRECT_SCORE_MARKET_CODES = {
    "7",       # 全场波胆
    "341",     # 上半场波胆
    "1100484", # 全场高倍波胆
    "1100485", # 上半场高倍波胆
}
DEFAULT_ALLOWED_PAGE_HOSTS = {"user-pc-new.hl99yjjpf.com"}
WORKSPACE_ALLOWED_ORIGINS = {"https://gemini077.github.io"}
RUNTIME_STATE_PATH = PROJECT_ROOT / "05_RUNTIME_STATE.json"
DEFAULT_EV_PROFILE_ROOT = PROJECT_ROOT / "data" / "live_ev_profiles"
WORKSPACE_SELECTION_PATH = PROJECT_ROOT / "data" / "match_workspace" / "selected_matches.json"
ANALYSIS_JOB_LOG_ROOT = PROJECT_ROOT / "data" / "analysis_jobs"
GITHUB_REPOSITORY = "gemini077/football-betting-oneshot"
SAFE_MATCH_ID = re.compile(r"^[0-9]{1,30}$")
ALLOWED_MATCH_API_PATHS = {
    "/v1/w/matchDetail/getMatchDetailPB",
    "/v1/w/matchDetail/getMatchOddsInfo1PB",
    "/v1/w/matchDetail/getMatchOddsInfo2PB",
    "/v1/w/structureMatchBaseInfoByMids",
    "/v1/w/structureMatchBaseInfoByMidsPB",
}
ALLOWED_SOURCE_TYPES = {
    "api_response",
    "worker_message",
    "shared_worker_message",
    "websocket_message",
}
SENSITIVE_KEY = re.compile(
    r"(?:pass(?:word|wd)?|pwd|token|secret|cookie|authorization|auth|session|"
    r"account|username|user_name|user_?info|user_?id|uid|phone|mobile|email|"
    r"bank|balance|wallet|credit|"
    r"withdraw|deposit|realname|identity|id_card|otp|captcha)",
    re.IGNORECASE,
)
BEARER_VALUE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
JWT_VALUE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
MAX_API_STRING = 1_200_000
MAX_API_DECOMPRESSED_BYTES = 20_000_000


class BridgeValidationError(ValueError):
    """Raised when an incoming bridge event violates the protocol."""


def _now() -> datetime:
    return datetime.now().astimezone()


def launch_selected_analysis(match: dict) -> dict:
    """Queue one owner-selected analysis without navigating the browser."""
    match_id = str(match.get("id") or "").strip()
    business_date = str(match.get("business_date") or "").strip()
    if not match_id or not business_date:
        raise BridgeValidationError("match id and business_date are required")
    label = f"{match.get('home')} vs {match.get('away')}"
    gh_candidates = [
        os.environ.get("FBOS_GH_PATH"), shutil.which("gh"),
        r"D:\Software\GitHub CLI\gh.exe",
    ]
    gh = next((path for path in gh_candidates if path and Path(path).exists()), None)
    if gh:
        completed = subprocess.run(
            [
                gh, "workflow", "run", "analyze-selected.yml",
                "--repo", GITHUB_REPOSITORY,
                "-f", f"business_date={business_date}",
                "-f", f"match_id={match_id}",
                "-f", f"match={label}",
            ],
            cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if completed.returncode == 0:
            return {"status": "queued", "mode": "github_workflow_dispatch"}
        raise BridgeValidationError((completed.stderr or completed.stdout or "workflow dispatch failed").strip())

    stamp = _now().strftime("%Y%m%d_%H%M%S")
    ANALYSIS_JOB_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = ANALYSIS_JOB_LOG_ROOT / f"{stamp}_{re.sub(r'[^0-9A-Za-z_-]+', '_', match_id)}.log"
    command = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "deepseek_auto_analysis.py"),
        "--date", business_date, "--match-id", match_id,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    return {
        "status": "queued", "mode": "local_fallback", "pid": process.pid,
        "log": log_path.relative_to(PROJECT_ROOT).as_posix(),
    }


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def sanitize(value: Any, *, depth: int = 0, max_depth: int = 8, max_string: int = 20000) -> Any:
    """Remove credential/account fields and bound recursive payload size."""

    if depth > max_depth:
        return "[DEPTH_LIMIT]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = BEARER_VALUE.sub("[REDACTED_BEARER]", value)
        text = JWT_VALUE.sub("[REDACTED_JWT]", text)
        return text[:max_string]
    if isinstance(value, list):
        return [
            sanitize(item, depth=depth + 1, max_depth=max_depth, max_string=max_string)
            for item in value[:500]
        ]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:500]:
            key_text = str(key)[:200]
            if SENSITIVE_KEY.search(key_text):
                continue
            cleaned[key_text] = sanitize(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string=max_string,
            )
        return cleaned
    return str(value)[:2000]


def _parse_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def canonicalize_inbound_payload(payload: Any) -> Any:
    """Decode logged inbound WebSocket JSON and reject echoed outbound messages."""

    payload = _parse_json_string(payload)
    if not isinstance(payload, dict):
        return payload

    if payload.get("cmd") != "js_code":
        return payload

    data = payload.get("data")
    if not isinstance(data, dict):
        return payload

    fun = data.get("fun")
    params = data.get("param")
    if not isinstance(params, list):
        return payload

    if fun == "window.postMessage":
        for item in params:
            if isinstance(item, dict) and item.get("cmd") == "WS_MSG_SEND":
                raise BridgeValidationError("outbound websocket event is not allowed")
        return payload

    if fun == "wslog.send_msg":
        decoded = list(params)
        for index, item in enumerate(decoded[:-1]):
            if item == "WS---S:":
                raise BridgeValidationError("outbound websocket log is not allowed")
            if item == "WS---R:":
                decoded[index + 1] = _parse_json_string(decoded[index + 1])
        return {**payload, "data": {**data, "param": decoded}}

    return payload


def decode_match_api_payload(payload: Any) -> Any:
    """Decode bounded Base64+Gzip JSON returned by allowlisted match APIs."""

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
        return payload
    encoded = re.sub(r"\s+", "", payload["data"])
    if not encoded.startswith("H4sI") or len(encoded) > MAX_API_STRING:
        return payload
    try:
        compressed = base64.b64decode(encoded, validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            decoded_bytes = stream.read(MAX_API_DECOMPRESSED_BYTES + 1)
    except (binascii.Error, EOFError, OSError, ValueError):
        return payload
    if len(decoded_bytes) > MAX_API_DECOMPRESSED_BYTES:
        raise BridgeValidationError("decompressed api_response exceeds size limit")
    try:
        decoded = json.loads(decoded_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            **payload,
            "_fbos_data_encoding": "base64_gzip_non_json",
            "_fbos_decompressed_bytes": len(decoded_bytes),
        }
    return {
        **payload,
        "data": decoded,
        "_fbos_data_encoding": "base64_gzip_json",
        "_fbos_decompressed_bytes": len(decoded_bytes),
    }


def _scaled_decimal_odds(value: Any) -> float | None:
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return round(numeric / 100000, 5)


def _odds_scale_matches_display(raw_odds: Any, display_price: Any) -> bool:
    decimal_odds = _scaled_decimal_odds(raw_odds)
    if decimal_odds is None:
        return False
    try:
        displayed = float(str(display_price))
    except (TypeError, ValueError):
        return False
    if displayed > 0:
        displayed_decimal = 1 + displayed
    elif displayed < 0:
        displayed_decimal = 1 + (1 / abs(displayed))
    else:
        return False
    return abs(decimal_odds - displayed_decimal) <= 0.02


def _canonical_handicap_line(market_code: Any, market_line: Any, selection: dict) -> str:
    """Give correct-score quotes one stable score line across API and WebSocket payloads."""

    line = str(market_line or "").strip()
    code = str(market_code or "")
    if code not in CORRECT_SCORE_MARKET_CODES:
        return line

    score = line or str(selection.get("ot") or "").strip()
    if re.fullmatch(r"\d+[:\-]\d+", score):
        return score.replace(":", "-")
    return line


def _iter_hls2(value: Any):
    if isinstance(value, dict):
        hls2 = value.get("hls2")
        if isinstance(hls2, dict):
            for market_code, markets in hls2.items():
                if isinstance(markets, list):
                    for market in markets:
                        if isinstance(market, dict):
                            yield str(market_code), market
        for item in value.values():
            yield from _iter_hls2(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_hls2(item)


def _iter_api_markets(value: Any):
    if isinstance(value, dict):
        if value.get("mid") and value.get("hpid") is not None and isinstance(value.get("hl"), list):
            yield value
        for item in value.values():
            yield from _iter_api_markets(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_api_markets(item)


def _iter_match_metadata(value: Any):
    if isinstance(value, dict):
        match_id = value.get("mid")
        name_keys = {"mhn", "man", "tn"}
        if match_id and any(value.get(key) for key in name_keys):
            yield value
        for item in value.values():
            yield from _iter_match_metadata(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_match_metadata(item)


def _iter_market_definitions(value: Any, inherited_mid: str = ""):
    if isinstance(value, dict):
        match_id = str(value.get("mid") or inherited_mid or "")
        if value.get("hpid") is not None and value.get("hpn"):
            yield match_id, value
        for item in value.values():
            yield from _iter_market_definitions(item, match_id)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_market_definitions(item, inherited_mid)


def normalize_event(event: dict) -> list[dict]:
    """Return auditable market/clock rows without interpreting bet direction."""

    rows: list[dict] = []
    payload = event.get("payload")
    base = {
        "schema_version": "1.0",
        "captured_at": event.get("captured_at"),
        "received_at": event.get("received_at"),
        "page_url": event.get("page_url"),
        "analysis_input_only": True,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
        "in_play_betting_enabled": False,
    }

    if isinstance(payload, dict) and payload.get("cmd") == "match_mst_upd":
        data = payload.get("data")
        updates = data.get("list") if isinstance(data, dict) else None
        if isinstance(updates, list):
            for update in updates:
                if not isinstance(update, dict) or not update.get("mid"):
                    continue
                rows.append({
                    **base,
                    "record_type": "match_clock",
                    "match_id": str(update.get("mid")),
                    "match_status": update.get("mst"),
                    "match_period": update.get("mmp"),
                    "server_time_ms": update.get("_server_time"),
                })

    seen_metadata: set[tuple] = set()
    for match in _iter_match_metadata(payload):
        row = {
            **base,
            "record_type": "match_metadata",
            "match_id": str(match.get("mid") or ""),
            "home_name": match.get("mhn"),
            "away_name": match.get("man"),
            "tournament_name": match.get("tn"),
            "kickoff_timestamp": match.get("mgt"),
            "home_score": match.get("mhs"),
            "away_score": match.get("mas"),
            "score_data": match.get("msc"),
            "match_status": match.get("mst"),
            "match_period": match.get("mmp"),
            "sport_id": match.get("csid"),
        }
        identity = tuple(str(row.get(key) or "") for key in (
            "match_id", "home_name", "away_name", "home_score", "away_score", "match_status", "match_period"
        ))
        if identity not in seen_metadata:
            seen_metadata.add(identity)
            rows.append(row)

    seen_definitions: set[tuple[str, str, str]] = set()
    for match_id, market in _iter_market_definitions(payload):
        identity = (match_id, str(market.get("hpid") or ""), str(market.get("hpn") or ""))
        if identity in seen_definitions:
            continue
        seen_definitions.add(identity)
        rows.append({
            **base,
            "record_type": "market_definition",
            "match_id": match_id,
            "market_code": str(market.get("hpid") or ""),
            "market_name": market.get("hpn"),
            "market_name_secondary": market.get("hpn2"),
            "market_type": market.get("hpt"),
        })

    for market_code, market in _iter_hls2(payload):
        selections = market.get("ol")
        if not isinstance(selections, list):
            continue
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            rows.append({
                **base,
                "record_type": "odds_quote",
                "match_id": str(market.get("mid") or ""),
                "market_code": str(market.get("hpid") or market_code),
                "child_market_code": str(market.get("chpid") or ""),
                "market_id": str(market.get("hid") or ""),
                "market_type": market.get("hmt"),
                "market_status": market.get("hs"),
                "handicap_line": _canonical_handicap_line(
                    market.get("hpid") or market_code,
                    market.get("hv"),
                    selection,
                ),
                "selection_code": selection.get("ot"),
                "selection_id": str(selection.get("oid") or ""),
                "selection_status": selection.get("os"),
                "raw_odds": selection.get("ov"),
                "base_raw_odds": selection.get("obv"),
                "inferred_decimal_odds": _scaled_decimal_odds(selection.get("ov")),
                "display_price": selection.get("ov2"),
                "odds_encoding": "scaled_integer_1e5_inferred",
                "odds_scale_verified": _odds_scale_matches_display(
                    selection.get("ov"), selection.get("ov2")
                ),
                "odds_scale_verification_basis": (
                    "direct_display_price_crosscheck"
                    if _odds_scale_matches_display(selection.get("ov"), selection.get("ov2"))
                    else None
                ),
                "source_timestamp_ms": market.get("t"),
            })

    for market in _iter_api_markets(payload):
        market_code = str(market.get("hpid") or "")
        match_id = str(market.get("mid") or "")
        if not market_code or not match_id:
            continue
        for line in market.get("hl") or []:
            if not isinstance(line, dict) or not isinstance(line.get("ol"), list):
                continue
            for selection in line["ol"]:
                if not isinstance(selection, dict):
                    continue
                raw_odds = selection.get("ov")
                display_price = selection.get("ov2")
                rows.append({
                    **base,
                    "record_type": "odds_quote",
                    "match_id": match_id,
                    "market_code": market_code,
                    "market_name": market.get("hpn"),
                    "child_market_code": str(market.get("chpid") or market_code),
                    "market_id": str(line.get("hid") or ""),
                    "market_type": line.get("hmt"),
                    "market_status": line.get("hs"),
                    "handicap_line": _canonical_handicap_line(
                        market_code,
                        line.get("hv") or selection.get("on") or "",
                        selection,
                    ),
                    "selection_code": selection.get("ot"),
                    "selection_name": selection.get("otv") or selection.get("ott"),
                    "selection_id": str(selection.get("oid") or ""),
                    "selection_status": selection.get("os"),
                    "raw_odds": raw_odds,
                    "base_raw_odds": selection.get("obv"),
                    "inferred_decimal_odds": _scaled_decimal_odds(raw_odds),
                    "display_price": display_price,
                    "odds_encoding": "scaled_integer_1e5_inferred",
                    "odds_scale_verified": _odds_scale_matches_display(raw_odds, display_price),
                    "odds_scale_verification_basis": (
                        "direct_display_price_crosscheck"
                        if _odds_scale_matches_display(raw_odds, display_price)
                        else None
                    ),
                    "source_timestamp_ms": market.get("ctsp"),
                })
    return rows


def validate_event(
    event: Any,
    *,
    allowed_page_hosts: set[str] | None = None,
    max_event_bytes: int = 1_500_000,
) -> dict:
    """Validate and sanitize one event without mutating the caller's object."""

    if not isinstance(event, dict):
        raise BridgeValidationError("event must be a JSON object")
    if _json_size(event) > max_event_bytes:
        raise BridgeValidationError("event exceeds size limit")

    allowed_page_hosts = allowed_page_hosts or DEFAULT_ALLOWED_PAGE_HOSTS
    page_url = str(event.get("page_url") or "")
    parsed = urlparse(page_url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_page_hosts:
        raise BridgeValidationError("page_url is not an allowed HTTPS host")

    source_type = str(event.get("source_type") or "")
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise BridgeValidationError("unsupported source_type")
    transport_meta_raw = event.get("transport_meta") or {}
    if source_type == "api_response":
        if not isinstance(transport_meta_raw, dict):
            raise BridgeValidationError("api_response transport_meta must be an object")
        if transport_meta_raw.get("request_path") not in ALLOWED_MATCH_API_PATHS:
            raise BridgeValidationError("api_response path is not allowlisted")

    captured_at = str(event.get("captured_at") or "")
    if not captured_at:
        raise BridgeValidationError("captured_at is required")
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BridgeValidationError("captured_at must be ISO-8601") from exc

    raw_payload = canonicalize_inbound_payload(event.get("payload"))
    if source_type == "api_response":
        raw_payload = decode_match_api_payload(raw_payload)
    payload = sanitize(
        raw_payload,
        max_depth=12,
        max_string=MAX_API_STRING if source_type == "api_response" else 20000,
    )
    if payload in (None, {}, []):
        raise BridgeValidationError("payload is empty after sanitization")

    result = {
        "schema_version": "1.0",
        "captured_at": captured_at,
        "received_at": _now().isoformat(),
        "source_type": source_type,
        "page_url": parsed._replace(
            query="",
            fragment=parsed.fragment.split("?", 1)[0],
        ).geturl(),
        "page_title": sanitize(str(event.get("page_title") or "")),
        "session_id": sanitize(str(event.get("session_id") or "unknown"))[:120],
        "sequence": int(event.get("sequence") or 0),
        "transport_meta": sanitize(transport_meta_raw),
        "payload": payload,
        "analysis_input_only": True,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
        "in_play_betting_enabled": False,
    }
    if _json_size(result) > max_event_bytes:
        raise BridgeValidationError("sanitized event exceeds size limit")
    return result


def event_fingerprint(event: dict) -> str:
    identity = {
        "source_type": event.get("source_type"),
        "page_url": event.get("page_url"),
        "payload": event.get("payload"),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BridgeStore:
    """Thread-safe append-only event store with bounded fingerprint memory."""

    def __init__(self, output_root: Path = DEFAULT_OUTPUT_ROOT, *, stamp: str | None = None, store_raw_events: bool = False):
        self.started_at = _now()
        self.stamp = stamp or self.started_at.strftime("%Y%m%d_%H%M%S")
        self.run_dir = self._unique_run_dir(Path(output_root), self.stamp)
        self.events_path = self.run_dir / f"{self.stamp}_live_odds_events.jsonl"
        self.normalized_path = self.run_dir / f"{self.stamp}_normalized_market_events.jsonl"
        self.manifest_path = self.run_dir / f"{self.stamp}_bridge_manifest.json"
        self.first_quotes_path = Path(output_root).parent / "first_quotes.json"
        self._lock = threading.Lock()
        self._fingerprints: deque[str] = deque(maxlen=10000)
        self._fingerprint_set: set[str] = set()
        self._latest_quotes: dict[tuple[str, str, str, str], dict] = {}
        self._normalized_state: dict[tuple[str, str, str, str, str], str] = {}
        self.store_raw_events = store_raw_events
        self._latest_clocks: dict[str, dict] = {}
        self._latest_match_metadata: dict[str, dict] = {}
        self._latest_match_activity_ms: dict[str, int] = {}
        self._market_definitions: dict[tuple[str, str], dict] = {}
        self._odds_scale_verified_matches: set[str] = set()
        self.received = 0
        self.stored = 0
        self.deduplicated = 0
        self.rejected = 0
        self.normalized_records = 0
        self.odds_quotes = 0
        self.match_clock_updates = 0
        self.match_metadata_updates = 0
        self.market_definitions = 0
        self._first_quote_archive = self._load_first_quote_archive()
        self._write_manifest()

    def _load_first_quote_archive(self) -> dict:
        try:
            value = json.loads(self.first_quotes_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        value.setdefault("schema_version", "1.0")
        value.setdefault("matches", {})
        return value

    def _write_first_quote_archive(self) -> None:
        self.first_quotes_path.parent.mkdir(parents=True, exist_ok=True)
        self._first_quote_archive["updated_at"] = _now().isoformat()
        temporary = self.first_quotes_path.with_name(f".{self.first_quotes_path.name}.tmp")
        temporary.write_text(
            json.dumps(self._first_quote_archive, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.first_quotes_path)

    @staticmethod
    def _unique_run_dir(root: Path, stamp: str) -> Path:
        candidate = root / stamp
        suffix = 1
        while candidate.exists():
            candidate = root / f"{stamp}_{suffix:02d}"
            suffix += 1
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    def _write_manifest(self) -> None:
        manifest = {
            "model_name": "Football Betting OneShot",
            "model_version": MODEL_VERSION,
            "module": "live_odds_bridge",
            "module_version": MODULE_VERSION,
            "mode": "read_only_shadow",
            "started_at": self.started_at.isoformat(),
            "schema": "schemas/live_odds_event.schema.json",
            "normalized_schema": "schemas/live_odds_normalized_event.schema.json",
            "events_file": self.events_path.name if self.store_raw_events else None,
            "raw_event_storage": self.store_raw_events,
            "normalized_events_file": self.normalized_path.name,
            "analysis_input_only": True,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
            "in_play_betting_enabled": False,
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(self, event: dict) -> tuple[bool, str]:
        fingerprint = event_fingerprint(event)
        with self._lock:
            self.received += 1
            page_match = re.search(r"#/details/(\d+)", str(event.get("page_url") or ""), re.IGNORECASE)
            if page_match:
                # Activity is updated even when the payload is deduplicated. A
                # quiet but still-open market page must not make an unchanged
                # quote look disconnected.
                self._latest_match_activity_ms[page_match.group(1)] = int(time.time() * 1000)
            if fingerprint in self._fingerprint_set:
                self.deduplicated += 1
                return False, fingerprint
            if len(self._fingerprints) == self._fingerprints.maxlen:
                oldest = self._fingerprints.popleft()
                self._fingerprint_set.discard(oldest)
            self._fingerprints.append(fingerprint)
            self._fingerprint_set.add(fingerprint)
            stored_event = {**event, "fingerprint": fingerprint}
            normalized_rows = normalize_event(stored_event)
            if not normalized_rows:
                if self.store_raw_events:
                    with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                        handle.write(json.dumps(stored_event, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.stored += 1
                return True, fingerprint
            changed_rows = []
            for row in normalized_rows:
                state_key = (
                    str(row.get("record_type") or ""), str(row.get("match_id") or ""),
                    str(row.get("market_code") or ""), str(row.get("handicap_line") or ""),
                    str(row.get("selection_code") or ""),
                )
                stable = {key: value for key, value in row.items() if key not in {
                    "captured_at", "received_at", "source_timestamp_ms", "fingerprint", "sequence", "session_id"
                }}
                state_hash = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                if self._normalized_state.get(state_key) == state_hash:
                    continue
                self._normalized_state[state_key] = state_hash
                changed_rows.append(row)
            normalized_rows = changed_rows
            if not normalized_rows:
                self.deduplicated += 1
                return False, fingerprint
            if self.store_raw_events:
                with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(stored_event, ensure_ascii=False, separators=(",", ":")) + "\n")
            if normalized_rows:
                archive_changed = False
                directly_verified_matches = {
                    str(row.get("match_id") or "")
                    for row in normalized_rows
                    if row.get("record_type") == "odds_quote"
                    and row.get("odds_scale_verified") is True
                    and row.get("match_id")
                }
                self._odds_scale_verified_matches.update(directly_verified_matches)
                for row in normalized_rows:
                    if (
                        row.get("record_type") == "odds_quote"
                        and row.get("inferred_decimal_odds") is not None
                        and str(row.get("match_id") or "") in self._odds_scale_verified_matches
                        and row.get("odds_scale_verified") is not True
                    ):
                        row["odds_scale_verified"] = True
                        row["odds_scale_verification_basis"] = "same_match_ov_field_peer_crosscheck"
                with self.normalized_path.open("a", encoding="utf-8", newline="\n") as handle:
                    for row in normalized_rows:
                        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        self.normalized_records += 1
                        if row.get("record_type") == "odds_quote":
                            self.odds_quotes += 1
                            key = (
                                str(row.get("match_id") or ""),
                                str(row.get("market_code") or ""),
                                str(row.get("handicap_line") or ""),
                                str(row.get("selection_code") or ""),
                            )
                            self._latest_quotes[key] = row
                            if row.get("odds_scale_verified") is True and row.get("inferred_decimal_odds") is not None:
                                match_id = str(row.get("match_id") or "")
                                archive_match = self._first_quote_archive["matches"].setdefault(
                                    match_id, {"metadata": None, "quotes": {}}
                                )
                                archive_key = "|".join(key[1:])
                                if archive_key not in archive_match["quotes"]:
                                    archive_match["quotes"][archive_key] = row
                                    archive_changed = True
                        elif row.get("record_type") == "match_clock":
                            self.match_clock_updates += 1
                            self._latest_clocks[str(row.get("match_id") or "")] = row
                        elif row.get("record_type") == "match_metadata":
                            self.match_metadata_updates += 1
                            self._latest_match_metadata[str(row.get("match_id") or "")] = row
                            match_id = str(row.get("match_id") or "")
                            archive_match = self._first_quote_archive["matches"].setdefault(
                                match_id, {"metadata": None, "quotes": {}}
                            )
                            if archive_match.get("metadata") is None:
                                archive_match["metadata"] = row
                                archive_changed = True
                        elif row.get("record_type") == "market_definition":
                            self.market_definitions += 1
                            definition_key = (
                                str(row.get("match_id") or ""),
                                str(row.get("market_code") or ""),
                            )
                            self._market_definitions[definition_key] = row
                if archive_changed:
                    self._write_first_quote_archive()
            self.stored += 1
            return True, fingerprint

    def latest(self, match_id: str | None = None, *, active_only: bool = True) -> dict:
        with self._lock:
            quotes = list(self._latest_quotes.values())
            clocks = list(self._latest_clocks.values())
            metadata = list(self._latest_match_metadata.values())
            definitions = dict(self._market_definitions)
            activity = dict(self._latest_match_activity_ms)
        if match_id:
            quotes = [row for row in quotes if row.get("match_id") == match_id]
            clocks = [row for row in clocks if row.get("match_id") == match_id]
            metadata = [row for row in metadata if row.get("match_id") == match_id]
        if active_only:
            quotes = [
                row for row in quotes
                if row.get("market_status") == 0
                and row.get("selection_status") == 1
                and row.get("inferred_decimal_odds") is not None
            ]
        now_ms = int(time.time() * 1000)
        selected_activity_ms = activity.get(str(match_id or "")) if match_id else None
        match_activity = {
            "match_id": match_id,
            "last_seen_ms": selected_activity_ms,
            "age_ms": max(0, now_ms - selected_activity_ms) if selected_activity_ms else None,
            "basis": "allowed_match_page_event_heartbeat",
        }
        quotes = [
            {
                **row,
                "market_name": (
                    definitions.get((str(row.get("match_id") or ""), str(row.get("market_code") or "")))
                    or definitions.get(("", str(row.get("market_code") or "")))
                    or {}
                ).get("market_name"),
                "quote_age_ms": max(0, now_ms - int(row["source_timestamp_ms"]))
                if str(row.get("source_timestamp_ms") or "").isdigit()
                else None,
            }
            for row in quotes
        ]
        quotes.sort(key=lambda row: (
            str(row.get("match_id") or ""),
            str(row.get("market_code") or ""),
            str(row.get("handicap_line") or ""),
            str(row.get("selection_code") or ""),
        ))
        clocks.sort(key=lambda row: str(row.get("match_id") or ""))
        metadata.sort(key=lambda row: str(row.get("match_id") or ""))
        return {
            "ok": True,
            "service": "Football Betting OneShot live odds bridge",
            "model_version": MODEL_VERSION,
            "mode": "read_only_shadow",
            "match_id_filter": match_id,
            "active_only": active_only,
            "quote_count": len(quotes),
            "match_clock_count": len(clocks),
            "match_metadata_count": len(metadata),
            "quotes": quotes,
            "match_clocks": clocks,
            "match_metadata": metadata,
            "match_activity": match_activity,
            "analysis_input_only": True,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
            "in_play_betting_enabled": False,
        }

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "Football Betting OneShot live odds bridge",
            "model_version": MODEL_VERSION,
            "module_version": MODULE_VERSION,
            "mode": "read_only_shadow",
            "started_at": self.started_at.isoformat(),
            "run_dir": str(self.run_dir),
            "received": self.received,
            "stored": self.stored,
            "deduplicated": self.deduplicated,
            "rejected": self.rejected,
            "normalized_records": self.normalized_records,
            "odds_quotes": self.odds_quotes,
            "match_clock_updates": self.match_clock_updates,
            "match_metadata_updates": self.match_metadata_updates,
            "market_definitions": self.market_definitions,
            "normalized_events_file": str(self.normalized_path),
            "raw_event_storage": self.store_raw_events,
            "analysis_input_only": True,
            "lock_state_changed": False,
            "bankroll_state_changed": False,
            "in_play_betting_enabled": False,
        }


def _allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    # Self-contained analysis reports are opened from file:// and browsers send
    # the opaque Origin value "null".  The service remains bound to loopback,
    # and event payloads still pass the target-host/schema validation below.
    return origin == "null" or origin.startswith("chrome-extension://")


def _allowed_workspace_origin(origin: str | None) -> bool:
    """Allow only the published workspace (and local file previews) to queue analysis."""
    return not origin or origin == "null" or origin in WORKSPACE_ALLOWED_ORIGINS


def public_model_state() -> dict:
    """Expose only the local model bankroll/risk fields needed by the overlay."""
    try:
        state = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    bankroll = state.get("bankroll") or {}
    exposure = state.get("exposure") or {}
    rules = state.get("execution_rules") or {}
    return {
        "ok": True,
        "model_name": state.get("model_name") or "Football Betting OneShot",
        "model_version": state.get("model_version") or MODEL_VERSION,
        "bankroll": {
            "current_balance": bankroll.get("current_balance"),
            "currency": bankroll.get("currency") or "CNY",
            "status": bankroll.get("status"),
        },
        "exposure": {
            "current_open_exposure": exposure.get("current_open_exposure", 0.0),
            "open_bet_count": len(exposure.get("open_bets") or []),
        },
        "risk_limits": {
            "daily_exposure_cap_pct": 0.05,
            "single_match_cap_pct": 0.05,
            "fixed_stake_min": 2.0,
            "fixed_stake_max": 3.0,
        },
        "requires_explicit_lock_confirmation": bool(rules.get("requires_explicit_lock_confirmation", True)),
        "in_play_betting_enabled": bool(rules.get("in_play_betting", False)),
        "contains_channel_account_data": False,
    }


def public_ev_profile(match_id: str, *, profile_root: Path = DEFAULT_EV_PROFILE_ROOT) -> dict:
    """Return the current analysis-owned profile for one numeric live match id."""
    normalized = str(match_id or "").strip()
    if not SAFE_MATCH_ID.fullmatch(normalized):
        raise BridgeValidationError("match_id must contain digits only")
    profile_path = Path(profile_root) / "current" / f"{normalized}.json"
    if not profile_path.exists():
        return {"ok": True, "found": False, "match_id": normalized, "profile": None}
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeValidationError("current EV profile is unreadable") from exc
    if not isinstance(profile, dict) or str((profile.get("match") or {}).get("match_id")) != normalized:
        raise BridgeValidationError("current EV profile match_id mismatch")
    return {
        "ok": True,
        "found": True,
        "match_id": normalized,
        "profile": profile,
        "analysis_input_only": True,
        "execution_authorized": False,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
    }


def make_handler(
    store: BridgeStore,
    *,
    allowed_page_hosts: set[str] | None = None,
    max_body_bytes: int = 2_000_000,
    ev_profile_root: Path | None = None,
    analysis_launcher=launch_selected_analysis,
):
    allowed_page_hosts = allowed_page_hosts or DEFAULT_ALLOWED_PAGE_HOSTS
    ev_profile_root = ev_profile_root or DEFAULT_EV_PROFILE_ROOT

    class Handler(BaseHTTPRequestHandler):
        server_version = "FBOSLiveOddsBridge/0.8.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin and _allowed_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_workspace_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin and _allowed_workspace_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            if urlparse(self.path).path.rstrip("/") == "/v1/analysis-selections":
                origin = self.headers.get("Origin")
                if not _allowed_workspace_origin(origin):
                    self._send_workspace_json(403, {"ok": False, "error": "origin_not_allowed"})
                    return
                self.send_response(204)
                if origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()
                return
            origin = self.headers.get("Origin")
            if not _allowed_origin(origin):
                self._send_json(403, {"ok": False, "error": "origin_not_allowed"})
                return
            self.send_response(204)
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            request_url = urlparse(self.path)
            if request_url.path.rstrip("/") in ("", "/v1/health"):
                self._send_json(200, store.health())
                return
            if request_url.path.rstrip("/") == "/v1/latest":
                query = parse_qs(request_url.query)
                match_id = str((query.get("match_id") or [""])[0]).strip() or None
                active_text = str((query.get("active_only") or ["true"])[0]).lower()
                active_only = active_text not in {"0", "false", "no"}
                self._send_json(200, store.latest(match_id, active_only=active_only))
                return
            if request_url.path.rstrip("/") == "/v1/model-state":
                self._send_json(200, public_model_state())
                return
            if request_url.path.rstrip("/") == "/v1/ev-profile":
                query = parse_qs(request_url.query)
                match_id = str((query.get("match_id") or [""])[0]).strip()
                try:
                    self._send_json(200, public_ev_profile(match_id, profile_root=ev_profile_root))
                except BridgeValidationError as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                return
            if request_url.path.rstrip("/") == "/v1/analysis-selections":
                selections = []
                try:
                    selections = json.loads(WORKSPACE_SELECTION_PATH.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                self._send_workspace_json(200, {
                    "ok": True, "selected": selections, "automatic_analysis": True,
                    "execution_authorized": False, "lock_state_changed": False,
                })
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            request_path = urlparse(self.path).path.rstrip("/")
            if request_path == "/v1/analysis-selections":
                try:
                    if not _allowed_workspace_origin(self.headers.get("Origin")):
                        raise BridgeValidationError("origin_not_allowed")
                    length = int(self.headers.get("Content-Length") or 0)
                    if length <= 0 or length > 100_000:
                        raise BridgeValidationError("invalid_body_size")
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    match = payload.get("match") or {}
                    allowed = {key: match.get(key) for key in (
                        "id", "match_num", "home", "away", "league", "kickoff", "business_date"
                    )}
                    if not str(allowed.get("id") or "").strip() or not str(allowed.get("home") or "").strip() or not str(allowed.get("away") or "").strip():
                        raise BridgeValidationError("match id, home and away are required")
                    allowed["selected_at"] = _now().isoformat()
                    allowed["analysis_requested"] = True
                    rows = []
                    try:
                        rows = json.loads(WORKSPACE_SELECTION_PATH.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                    rows = [row for row in rows if str(row.get("id")) != str(allowed["id"])]
                    rows.append(allowed)
                    WORKSPACE_SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
                    temporary = WORKSPACE_SELECTION_PATH.with_suffix(".tmp")
                    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                    temporary.replace(WORKSPACE_SELECTION_PATH)
                    job = analysis_launcher(allowed)
                    self._send_workspace_json(202, {
                        "ok": True, "selected": allowed, "automatic_analysis": True,
                        "analysis_job": job,
                        "execution_authorized": False, "lock_state_changed": False,
                    })
                except (UnicodeDecodeError, json.JSONDecodeError, BridgeValidationError, ValueError) as exc:
                    self._send_workspace_json(400, {"ok": False, "error": str(exc)})
                return
            if request_path not in {"/v1/events", "/v1/reprice"}:
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            origin = self.headers.get("Origin")
            if not _allowed_origin(origin):
                store.rejected += 1
                self._send_json(403, {"ok": False, "error": "origin_not_allowed"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > max_body_bytes:
                store.rejected += 1
                self._send_json(413, {"ok": False, "error": "invalid_body_size"})
                return
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if request_path == "/v1/reprice":
                    match_id = str((payload.get("contract") or {}).get("match_id") or "").strip()
                    if not match_id:
                        raise RepriceValidationError("contract.match_id is required")
                    result = evaluate_request(payload, latest_payload=store.latest(match_id, active_only=True))
                    result["ok"] = True
                    self._send_json(200, result)
                    return
                clean = validate_event(
                    payload,
                    allowed_page_hosts=allowed_page_hosts,
                    max_event_bytes=max_body_bytes,
                )
                stored, fingerprint = store.record(clean)
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                BridgeValidationError,
                RepriceValidationError,
                ValueError,
            ) as exc:
                store.rejected += 1
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(
                202,
                {
                    "ok": True,
                    "stored": stored,
                    "deduplicated": not stored,
                    "fingerprint": fingerprint,
                },
            )

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Football Betting OneShot 滚球只读赔率桥接器")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--store-raw-events", action="store_true", help="调试时才保存完整原始事件；默认仅保存变化后的标准化赔率")
    parser.add_argument(
        "--allowed-page-host",
        action="append",
        default=[],
        help="允许采集的HTTPS页面主机，可重复；默认仅目标滚球站点",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("安全限制：桥接器只能绑定本机回环地址")
    allowed_hosts = set(args.allowed_page_host) or set(DEFAULT_ALLOWED_PAGE_HOSTS)
    store = BridgeStore(Path(args.output_root), store_raw_events=args.store_raw_events)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, allowed_page_hosts=allowed_hosts))
    print(json.dumps({
        "service": "Football Betting OneShot live odds bridge",
        "mode": "read_only_shadow",
        "listen": f"http://{args.host}:{args.port}",
        "health": f"http://{args.host}:{args.port}/v1/health",
        "allowed_page_hosts": sorted(allowed_hosts),
        "run_dir": str(store.run_dir),
        "in_play_betting_enabled": False,
        "lock_state_changed": False,
    }, ensure_ascii=False, indent=2))
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

