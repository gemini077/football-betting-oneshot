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
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024
CREST_HOST = "info.nowscore.com"
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "div":
            element_id = attributes.get("id", "").casefold()
            if self._side is None and element_id in {"home", "guest", "away"}:
                self._side = "home" if element_id == "home" else "away"
                self._side_div_depth = 1
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
) -> dict[str, Any]:
    """Parse and verify the ordered home/away crest pair from one page."""

    parser = _NowscoreCrestParser()
    reasons: list[str] = []
    identity_reasons: list[str] = []
    try:
        parser.feed(str(page_html))
        parser.close()
    except Exception as error:  # parser failure is presentation-only fallback
        reasons.append(f"PARSER_ERROR:{type(error).__name__}")

    expected_id = _positive_int(expected_nowscore_id)
    if expected_id is not None:
        if _positive_int(parser.match_id) != expected_id:
            reason = "PAGE_NOWSCORE_ID_CONFLICT" if parser.match_id else "PAGE_NOWSCORE_ID_MISSING"
            reasons.append(reason)
            identity_reasons.append(reason)

    for side in ("home", "away"):
        team = parser.teams[side]
        if not team["name"]:
            reason = f"{side.upper()}_TEAM_NAME_MISSING"
            reasons.append(reason)
            identity_reasons.append(reason)
        if not team["team_id"]:
            reason = f"{side.upper()}_TEAM_ID_MISSING"
            reasons.append(reason)
            identity_reasons.append(reason)
        if not team["crest_url"]:
            reasons.append(f"{side.upper()}_CREST_URL_MISSING")

    expected_names = {"home": _normalise_name(expected_home), "away": _normalise_name(expected_away)}
    observed_names = {side: _normalise_name(parser.teams[side]["name"]) for side in ("home", "away")}
    if any(expected_names.values()):
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
) -> str | None:
    if team_id in team_cache:
        return team_cache[team_id]
    try:
        data = fetcher(source_url, 30)
        if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("INVALID_CREST_IMAGE_BYTES")
        extension = _image_format(data)
        if extension is None:
            raise ValueError("INVALID_CREST_IMAGE_FORMAT")
        digest = hashlib.sha256(data).hexdigest()
        filename = digest_cache.get(digest)
        if filename is None:
            filename = f"crest-{digest[:20]}.{extension}"
            asset_root.mkdir(parents=True, exist_ok=True)
            (asset_root / filename).write_bytes(data)
            digest_cache[digest] = filename
        reference = f"{asset_prefix.rstrip('/')}/{filename}"
    except Exception:
        reference = None
    team_cache[team_id] = reference
    return reference


def enrich_dashboard_crests(
    dashboard: Mapping[str, Any],
    *,
    universe: Mapping[str, Any] | None = None,
    asset_root: Path,
    fetcher: Callable[[str, float], bytes] | None = None,
    asset_prefix: str = ASSET_PREFIX,
) -> dict[str, Any]:
    """Return a copied dashboard with verified local crest asset references."""

    enriched = copy.deepcopy(dict(dashboard))
    index = _universe_index(universe)
    team_cache: dict[str, str | None] = {}
    digest_cache: dict[str, str] = {}
    request = fetcher or _fetch_bytes
    for fixture in enriched.get("fixtures") or []:
        if not isinstance(fixture, dict):
            continue
        universe_row = _fixture_universe_row(fixture, index)
        nowscore_id = _nowscore_id(fixture, universe_row)
        if nowscore_id is None:
            continue
        fixture["nowscore_id"] = nowscore_id
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
            )
        except Exception:
            parsed = {"status": "UNVERIFIED", "home": {}, "away": {}, "reasons": ["FETCH_FAILED"]}
        if parsed.get("identity_status") != "VERIFIED":
            continue
        for side in ("home", "away"):
            field = f"{side}_crest"
            if _has_renderable_source(fixture.get(field)):
                continue
            team = parsed.get(side) if isinstance(parsed.get(side), Mapping) else {}
            team_id = str(team.get("team_id") or "").strip()
            source_url = _crest_url(team.get("crest_url"), team_id)
            if not team_id or not source_url:
                continue
            reference = _asset_reference(
                source_url,
                team_id,
                asset_root=asset_root,
                asset_prefix=asset_prefix,
                fetcher=request,
                team_cache=team_cache,
                digest_cache=digest_cache,
            )
            if reference:
                fixture[field] = reference
    return enriched
