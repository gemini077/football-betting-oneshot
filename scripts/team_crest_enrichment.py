"""Bounded build-time team-crest enrichment from the existing Nowscore chain.

This module only enriches public presentation data.  It never changes fixture
selection, prediction records, model inputs, or serving authority.  Every
identity or image failure returns the caller's neutral crest fallback path.
"""

from __future__ import annotations

import copy
import hashlib
import html as html_lib
import re
import unicodedata
import urllib.request
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

try:
    from .team_identity import team_similarity
except ImportError:  # pragma: no cover - direct script execution path.
    from team_identity import team_similarity


ANALYSIS_PAGE_URL = "https://live.nowscore.com/analysis/{nowscore_id}cn.html"
ASSET_PREFIX = "../assets/team-crests"
DIAGNOSTICS_SCHEMA = "team_crest_enrichment_diagnostics.v1"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024
CREST_HOST = "info.nowscore.com"
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
EXACT_PROVIDER_STATUSES = {"EXACT_MATCH", "EXACT_PROVIDER_MATCH", "STORED_VERIFIED_BINDING"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _positive_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _fetch_bytes(url: str, timeout: float = 30) -> bytes:
    """Fetch a Nowscore-owned page/image with the existing project headers."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "identity",
            "Referer": "https://live.nowscore.com/",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_PAGE_BYTES + 1)
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("NOWSCORE_RESPONSE_TOO_LARGE")
    return body


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalise_name(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = re.sub(
        r"\s*[\(\uff08]\s*(?:\u4e3b|\u5ba2|\u4e3b\u961f|\u5ba2\u961f|home|away)\s*[\)\uff09]\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _crest_url(value: Any, team_id: str | None) -> str | None:
    if not team_id:
        return None
    raw = str(value or "").strip()
    if not raw:
        return None
    url = urljoin("https://live.nowscore.com/analysis/", raw)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != CREST_HOST:
        return None
    match = re.fullmatch(
        r"/Image/team/images/(\d+)/([^/?#]+)",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if not match or match.group(1) != team_id:
        return None
    suffix = Path(match.group(2)).suffix.casefold()
    if suffix not in IMAGE_EXTENSIONS:
        return None
    return url


class _NowscoreCrestParser(HTMLParser):
    """Read the two explicit teams in the analysis page match header."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.match_id: str | None = None
        self.teams: dict[str, dict[str, str | None]] = {
            "home": {"name": None, "team_id": None, "crest_url": None},
            "away": {"name": None, "team_id": None, "crest_url": None},
        }
        self._side: str | None = None
        self._side_div_depth = 0
        self._anchor_side: str | None = None
        self._anchor_text: list[str] = []
        self.section_sequence: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "div":
            element_id = attributes.get("id", "").casefold()
            if self._side is None and element_id in {"home", "guest", "away"}:
                self._side = "home" if element_id == "home" else "away"
                self._side_div_depth = 1
                self.section_sequence.append(self._side)
            elif self._side is not None:
                self._side_div_depth += 1
        if self._side is None:
            if tag.casefold() == "input" and attributes.get("id", "").casefold() == "hide_scheduleid":
                self.match_id = str(_positive_int(attributes.get("value")) or "") or None
            return
        if tag.casefold() == "a":
            classes = set(attributes.get("class", "").casefold().split())
            if "name" in classes and self._anchor_side is None:
                self._anchor_side = self._side
                self._anchor_text = []
                href = attributes.get("href", "")
                match = re.search(r"(?:[?&])teamid=(\d+)", href, flags=re.IGNORECASE)
                if match:
                    self.teams[self._side]["team_id"] = match.group(1)
        elif tag.casefold() == "img" and self.teams[self._side]["crest_url"] is None:
            source = attributes.get("src", "")
            team_match = re.search(
                r"/Image/team/images/(\d+)/([^/?#]+)$",
                urlsplit(urljoin("https://live.nowscore.com/analysis/", source)).path,
                flags=re.IGNORECASE,
            )
            if team_match:
                team_id = team_match.group(1)
                self.teams[self._side]["crest_url"] = _crest_url(source, team_id)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._anchor_side is not None:
            text = "".join(self._anchor_text).strip()
            if not self.teams[self._anchor_side]["name"]:
                self.teams[self._anchor_side]["name"] = text or None
            self._anchor_side = None
            self._anchor_text = []
        if tag.casefold() == "div" and self._side is not None:
            self._side_div_depth -= 1
            if self._side_div_depth <= 0:
                self._side = None
                self._side_div_depth = 0

    def handle_data(self, data: str) -> None:
        if self._anchor_side is not None:
            self._anchor_text.append(data)
        if self._side is None and self.match_id is None:
            match = re.search(r"hide_scheduleId\D+(\d+)", data, flags=re.IGNORECASE)
            if match:
                self.match_id = match.group(1)


def parse_nowscore_analysis_crests(
    page_html: str,
    *,
    expected_nowscore_id: int | str | None = None,
    expected_home: Any = None,
    expected_away: Any = None,
    exact_provider_identity: bool = False,
) -> dict[str, Any]:
    """Parse and verify the ordered home/away crest pair from one page."""

    parser = _NowscoreCrestParser()
    reasons: list[str] = []
    identity_reasons: list[str] = []
    corroboration_reasons: list[str] = []
    try:
        parser.feed(str(page_html))
        parser.close()
    except Exception as error:  # parser failure is presentation-only fallback
        parser_error = f"PARSER_ERROR:{type(error).__name__}"
        reasons.append(parser_error)
        identity_reasons.append(parser_error)

    expected_id = _positive_int(expected_nowscore_id)
    if exact_provider_identity and expected_id is None:
        identity_reasons.append("EXPECTED_NOWSCORE_ID_MISSING")
    elif expected_id is not None:
        if _positive_int(parser.match_id) != expected_id:
            reason = "PAGE_NOWSCORE_ID_CONFLICT" if parser.match_id else "PAGE_NOWSCORE_ID_MISSING"
            reasons.append(reason)
            identity_reasons.append(reason)

    if parser.section_sequence != ["home", "away"]:
        if parser.section_sequence == ["away", "home"]:
            identity_reasons.append("TEAM_SECTION_ORDER_CONFLICT")
        else:
            identity_reasons.append("AMBIGUOUS_TEAM_SECTIONS")

    for side in ("home", "away"):
        team = parser.teams[side]
        if not team["name"]:
            reason = f"{side.upper()}_TEAM_NAME_MISSING"
            if exact_provider_identity:
                corroboration_reasons.append(reason)
            else:
                reasons.append(reason)
                identity_reasons.append(reason)
        if not team["team_id"]:
            reason = f"{side.upper()}_TEAM_ID_MISSING"
            reasons.append(reason)
            identity_reasons.append(reason)
        if not team["crest_url"]:
            reasons.append(f"{side.upper()}_CREST_URL_MISSING")

    home_id = parser.teams["home"]["team_id"]
    away_id = parser.teams["away"]["team_id"]
    if home_id and away_id and home_id == away_id:
        identity_reasons.append("DUPLICATE_TEAM_ID")

    expected_names = {"home": _normalise_name(expected_home), "away": _normalise_name(expected_away)}
    observed_names = {side: _normalise_name(parser.teams[side]["name"]) for side in ("home", "away")}
    if exact_provider_identity:
        if not expected_names["home"] or not expected_names["away"]:
            corroboration_reasons.append("FIXTURE_LABEL_MISSING")
        else:
            same_scores = {
                side: team_similarity(expected_names[side], observed_names[side])[0]
                for side in ("home", "away")
            }
            reverse_scores = {
                "home": team_similarity(expected_names["home"], observed_names["away"])[0],
                "away": team_similarity(expected_names["away"], observed_names["home"])[0],
            }
            for side in ("home", "away"):
                if same_scores[side] < 0.75:
                    corroboration_reasons.append(f"{side.upper()}_TEAM_LABEL_MISMATCH")
            if all(score >= 0.75 for score in reverse_scores.values()) and all(
                score < 0.75 for score in same_scores.values()
            ):
                corroboration_reasons.append("TEAM_LABEL_ORIENTATION_MISMATCH")
                identity_reasons.append("ORIENTATION_CONFLICT")
    elif any(expected_names.values()):
        if not expected_names["home"] or not expected_names["away"]:
            identity_reasons.append("FIXTURE_ORIENTATION_MISSING")
        else:
            same_scores = {
                side: team_similarity(expected_names[side], observed_names[side])[0]
                for side in ("home", "away")
            }
            reverse_scores = {
                "home": team_similarity(expected_names["home"], observed_names["away"])[0],
                "away": team_similarity(expected_names["away"], observed_names["home"])[0],
            }
            if all(score >= 0.75 for score in reverse_scores.values()) and all(
                score < 0.75 for score in same_scores.values()
            ):
                identity_reasons.append("ORIENTATION_CONFLICT")
            else:
                if same_scores["home"] < 0.75:
                    identity_reasons.append("HOME_TEAM_IDENTITY_CONFLICT")
                if same_scores["away"] < 0.75:
                    identity_reasons.append("AWAY_TEAM_IDENTITY_CONFLICT")
    if observed_names["home"] and observed_names["home"] == observed_names["away"]:
        identity_reasons.append("AMBIGUOUS_IDENTITY")
    reasons.extend(identity_reasons)
    for side in ("home", "away"):
        team = parser.teams[side]
        crest_path = urlsplit(str(team["crest_url"] or "")).path
        crest_match = re.search(r"/Image/team/images/(\d+)/", crest_path, flags=re.IGNORECASE)
        if crest_match and team["team_id"] and crest_match.group(1) != team["team_id"]:
            reason = f"{side.upper()}_CREST_TEAM_ID_CONFLICT"
            identity_reasons.append(reason)
            reasons.append(reason)

    return {
        "status": "VERIFIED" if not reasons else "UNVERIFIED",
        "identity_status": "VERIFIED" if not identity_reasons else "UNVERIFIED",
        "match_id": parser.match_id,
        "home": dict(parser.teams["home"]),
        "away": dict(parser.teams["away"]),
        "reasons": list(dict.fromkeys(reasons)),
        "corroboration_reasons": list(dict.fromkeys(corroboration_reasons)),
    }


def _source_value(source: Any) -> str:
    if isinstance(source, Mapping):
        source = source.get("src") or source.get("url") or source.get("path")
    return str(source or "").strip()


def _has_renderable_source(source: Any) -> bool:
    value = _source_value(source).casefold()
    return bool(value) and not value.startswith(("data:", "javascript:", "blob:"))


def _fixture_value(fixture: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = fixture.get(key)
        if value not in (None, ""):
            return value
    return None


def _universe_index(universe: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in (universe or {}).get("fixtures") or []:
        if not isinstance(row, Mapping):
            continue
        for key in ("matchId", "match_id", "matchKey", "match_key"):
            value = row.get(key)
            if value not in (None, ""):
                index.setdefault(str(value), dict(row))
    return index


def _fixture_universe_row(fixture: Mapping[str, Any], index: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    for key in ("match_id", "matchId", "match_key", "matchKey"):
        value = fixture.get(key)
        if value not in (None, "") and str(value) in index:
            return index[str(value)]
    return {}


def new_crest_diagnostics() -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTICS_SCHEMA,
        "status": "COMPLETED",
        "fixture_count": 0,
        "total_team_slots": 0,
        "resolved_real_crests": 0,
        "unresolved_team_slots": 0,
        "coverage_percent": 0.0,
        "outcome_counts": {"RESOLVED": 0, "FALLBACK": 0},
        "failure_reasons": {},
        "fixtures": [],
    }


def _finalize_crest_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    records = [item for item in diagnostics.get("fixtures") or [] if isinstance(item, dict)]
    outcome_counts: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    total_slots = 0
    resolved = 0
    for record in records:
        slots = record.get("slots") if isinstance(record.get("slots"), dict) else {}
        for slot in slots.values():
            if not isinstance(slot, dict):
                continue
            total_slots += 1
            outcome = str(slot.get("outcome") or "FALLBACK")
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            if outcome == "RESOLVED":
                resolved += 1
                continue
            reasons = list(dict.fromkeys(str(reason) for reason in slot.get("reason_codes") or [] if reason))
            for reason in reasons or ["UNRESOLVED"]:
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    diagnostics.update({
        "fixture_count": len(records),
        "total_team_slots": total_slots,
        "resolved_real_crests": resolved,
        "unresolved_team_slots": total_slots - resolved,
        "coverage_percent": round((resolved / total_slots) * 100, 2) if total_slots else 0.0,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "fixtures": records,
    })
    return diagnostics


def failed_crest_diagnostics(dashboard: Mapping[str, Any], reason: str) -> dict[str, Any]:
    diagnostics = new_crest_diagnostics()
    diagnostics["status"] = "FAILED"
    for fixture in dashboard.get("fixtures") or []:
        if not isinstance(fixture, Mapping):
            continue
        slots = {
            side: {"outcome": "FALLBACK", "source": "NEUTRAL_FALLBACK", "reason_codes": [reason]}
            for side in ("home", "away")
        }
        diagnostics["fixtures"].append({
            "match_id": str(_fixture_value(fixture, "match_id", "matchId") or ""),
            "nowscore_id": None,
            "identity_mode": "UNAVAILABLE",
            "identity_status": "UNVERIFIED",
            "reason_codes": [reason],
            "corroboration_reasons": [],
            "slots": slots,
        })
    return _finalize_crest_diagnostics(diagnostics)


def _provider_identity(
    fixture: Mapping[str, Any],
    universe_row: Mapping[str, Any],
    nowscore_id: int,
) -> tuple[bool, list[str], str]:
    reasons: list[str] = []
    fixture_id = _positive_int(
        _fixture_value(fixture, "nowscore_id", "nowscoreId", "provider_match_id")
    )
    row_id = _positive_int(
        _fixture_value(universe_row, "nowscore_id", "nowscoreId", "provider_match_id")
    )
    if universe_row:
        if row_id is None:
            reasons.append("NOWSCORE_ROW_ID_MISSING")
        elif row_id != nowscore_id:
            reasons.append("NOWSCORE_IDENTITY_ID_CONFLICT")
        if fixture_id is not None and row_id is not None and fixture_id != row_id:
            reasons.append("NOWSCORE_FIXTURE_ROW_ID_CONFLICT")
        status_value = _fixture_value(universe_row, "nowscoreMatchStatus", "nowscore_match_status")
        if status_value in (None, ""):
            status_value = _fixture_value(fixture, "nowscoreMatchStatus", "nowscore_match_status")
        identity_source = "UNIVERSE_EXACT_PROVIDER_ID"
    else:
        status_value = _fixture_value(fixture, "nowscoreMatchStatus", "nowscore_match_status")
        identity_source = "FIXTURE_EXACT_PROVIDER_ID"
    status = str(status_value or "").strip().upper()
    if status not in EXACT_PROVIDER_STATUSES:
        reasons.append("NOWSCORE_MATCH_NOT_EXACT" if status else "NOWSCORE_IDENTITY_UNPROVEN")
    return not reasons, list(dict.fromkeys(reasons)), identity_source


def _nowscore_id(fixture: Mapping[str, Any], universe_row: Mapping[str, Any]) -> int | None:
    return _positive_int(
        _fixture_value(
            fixture,
            "nowscore_id",
            "nowscoreId",
            "provider_match_id",
        )
        or _fixture_value(universe_row, "nowscore_id", "nowscoreId", "provider_match_id")
    )


def _image_format(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _asset_reference(
    source_url: str,
    team_id: str,
    *,
    asset_root: Path,
    asset_prefix: str,
    fetcher: Callable[[str, float], bytes],
    team_cache: dict[str, str | None],
    digest_cache: dict[str, str],
    failure_codes: list[str] | None = None,
) -> str | None:
    if team_id in team_cache:
        if team_cache[team_id] is None and failure_codes is not None:
            failure_codes.append("IMAGE_UNAVAILABLE_CACHED")
        return team_cache[team_id]
    try:
        data = fetcher(source_url, 30)
        if not isinstance(data, bytes) or not data:
            raise ValueError("IMAGE_BYTES_INVALID")
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("IMAGE_TOO_LARGE")
        extension = _image_format(data)
        if extension is None:
            raise ValueError("IMAGE_FORMAT_INVALID")
        digest = hashlib.sha256(data).hexdigest()
        filename = digest_cache.get(digest)
        if filename is None:
            filename = f"crest-{digest[:20]}.{extension}"
            asset_root.mkdir(parents=True, exist_ok=True)
            (asset_root / filename).write_bytes(data)
            digest_cache[digest] = filename
        reference = f"{asset_prefix.rstrip('/')}/{filename}"
    except ValueError as error:
        reference = None
        if failure_codes is not None:
            failure_codes.append(str(error))
    except Exception:
        reference = None
        if failure_codes is not None:
            failure_codes.append("IMAGE_FETCH_OR_WRITE_FAILED")
    team_cache[team_id] = reference
    return reference


def _add_diagnostic_reason(record: dict[str, Any], side: str, reason: str) -> None:
    slot = record["slots"][side]
    if reason and reason not in slot["reason_codes"]:
        slot["reason_codes"].append(reason)
    if reason and reason not in record["reason_codes"]:
        record["reason_codes"].append(reason)


def _side_reasons(side: str, reasons: list[str]) -> list[str]:
    prefix = f"{side.upper()}_"
    global_reasons = {
        "AMBIGUOUS_IDENTITY",
        "AMBIGUOUS_TEAM_SECTIONS",
        "DUPLICATE_TEAM_ID",
        "ORIENTATION_CONFLICT",
        "TEAM_SECTION_ORDER_CONFLICT",
        "PAGE_NOWSCORE_ID_CONFLICT",
        "PAGE_NOWSCORE_ID_MISSING",
        "EXPECTED_NOWSCORE_ID_MISSING",
        "ANALYSIS_PAGE_FETCH_FAILED",
        "ANALYSIS_IDENTITY_UNVERIFIED",
    }
    return list(
        dict.fromkeys(
            reason
            for reason in reasons
            if reason.startswith(prefix)
            or reason in global_reasons
            or reason.startswith("PARSER_ERROR:")
        )
    )


def enrich_dashboard_crests(
    dashboard: Mapping[str, Any],
    *,
    universe: Mapping[str, Any] | None = None,
    asset_root: Path,
    fetcher: Callable[[str, float], bytes] | None = None,
    asset_prefix: str = ASSET_PREFIX,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return copied presentation data and optional build-only diagnostics."""

    enriched = copy.deepcopy(dict(dashboard))
    index = _universe_index(universe)
    team_cache: dict[str, str | None] = {}
    digest_cache: dict[str, str] = {}
    request = fetcher or _fetch_bytes
    diagnostic_payload = new_crest_diagnostics()
    for fixture in enriched.get("fixtures") or []:
        if not isinstance(fixture, dict):
            continue
        universe_row = _fixture_universe_row(fixture, index)
        fixture_id = str(_fixture_value(fixture, "match_id", "matchId") or "")
        nowscore_id = _nowscore_id(fixture, universe_row)
        record = {
            "match_id": fixture_id,
            "nowscore_id": nowscore_id,
            "identity_mode": "UNAVAILABLE",
            "identity_status": "UNVERIFIED",
            "provider_identity_reasons": [],
            "corroboration_reasons": [],
            "reason_codes": [],
            "slots": {},
        }
        for side in ("home", "away"):
            existing_source = _fixture_value(fixture, f"{side}_crest", f"{side}_logo")
            if _has_renderable_source(existing_source):
                record["slots"][side] = {
                    "outcome": "RESOLVED",
                    "source": "EXISTING_SOURCE",
                    "reason_codes": [],
                }
            else:
                record["slots"][side] = {
                    "outcome": "FALLBACK",
                    "source": "NEUTRAL_FALLBACK",
                    "reason_codes": [],
                }
        diagnostic_payload["fixtures"].append(record)
        if nowscore_id is None:
            record["reason_codes"].append("NOWSCORE_ID_MISSING")
            for side in ("home", "away"):
                if record["slots"][side]["outcome"] != "RESOLVED":
                    _add_diagnostic_reason(record, side, "NOWSCORE_ID_MISSING")
            continue
        fixture["nowscore_id"] = nowscore_id
        exact_identity, provider_reasons, identity_source = _provider_identity(
            fixture,
            universe_row,
            nowscore_id,
        )
        record["identity_mode"] = identity_source if exact_identity else "STRICT_LABEL"
        record["provider_identity_reasons"] = provider_reasons
        record["reason_codes"].extend(provider_reasons)
        if any(reason in {"NOWSCORE_ROW_ID_MISSING", "NOWSCORE_IDENTITY_ID_CONFLICT", "NOWSCORE_FIXTURE_ROW_ID_CONFLICT"} for reason in provider_reasons):
            for side in ("home", "away"):
                if record["slots"][side]["outcome"] != "RESOLVED":
                    for reason in provider_reasons:
                        _add_diagnostic_reason(record, side, reason)
            continue
        home_name = _fixture_value(fixture, "home", "homeTeam", "home_team") or _fixture_value(
            universe_row, "homeTeam", "home_team", "home"
        )
        away_name = _fixture_value(fixture, "away", "awayTeam", "away_team") or _fixture_value(
            universe_row, "awayTeam", "away_team", "away"
        )
        page_url = ANALYSIS_PAGE_URL.format(nowscore_id=nowscore_id)
        try:
            parsed = parse_nowscore_analysis_crests(
                _decode(request(page_url, 30)),
                expected_nowscore_id=nowscore_id,
                expected_home=home_name,
                expected_away=away_name,
                exact_provider_identity=exact_identity,
            )
        except Exception:
            parsed = {
                "status": "UNVERIFIED",
                "identity_status": "UNVERIFIED",
                "home": {},
                "away": {},
                "reasons": ["ANALYSIS_PAGE_FETCH_FAILED"],
                "corroboration_reasons": [],
            }
        record["identity_status"] = str(parsed.get("identity_status") or "UNVERIFIED")
        parser_reasons = [str(reason) for reason in parsed.get("reasons") or [] if reason]
        corroboration_reasons = [
            str(reason) for reason in parsed.get("corroboration_reasons") or [] if reason
        ]
        record["corroboration_reasons"] = list(dict.fromkeys(corroboration_reasons))
        record["reason_codes"].extend(parser_reasons)
        if record["identity_status"] != "VERIFIED":
            for side in ("home", "away"):
                if record["slots"][side]["outcome"] == "RESOLVED":
                    continue
                _add_diagnostic_reason(record, side, "ANALYSIS_IDENTITY_UNVERIFIED")
                for reason in _side_reasons(side, parser_reasons):
                    _add_diagnostic_reason(record, side, reason)
            continue
        for side in ("home", "away"):
            if record["slots"][side]["outcome"] == "RESOLVED":
                continue
            field = f"{side}_crest"
            team = parsed.get(side) if isinstance(parsed.get(side), Mapping) else {}
            team_id = str(team.get("team_id") or "").strip()
            source_url = _crest_url(team.get("crest_url"), team_id)
            side_reasons = _side_reasons(side, parser_reasons)
            if not team_id or not source_url:
                for reason in side_reasons or [f"{side.upper()}_CREST_URL_MISSING"]:
                    _add_diagnostic_reason(record, side, reason)
                continue
            image_failures: list[str] = []
            reference = _asset_reference(
                source_url,
                team_id,
                asset_root=asset_root,
                asset_prefix=asset_prefix,
                fetcher=request,
                team_cache=team_cache,
                digest_cache=digest_cache,
                failure_codes=image_failures,
            )
            if reference:
                fixture[field] = reference
                record["slots"][side].update({
                    "outcome": "RESOLVED",
                    "source": "NOWSCORE_LOCAL",
                    "reason_codes": [],
                })
            else:
                for reason in image_failures or ["IMAGE_UNAVAILABLE"]:
                    _add_diagnostic_reason(record, side, reason)
    finalized = _finalize_crest_diagnostics(diagnostic_payload)
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(copy.deepcopy(finalized))
    return enriched
