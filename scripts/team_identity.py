#!/usr/bin/env python3
"""Shared cross-provider team identity and safe similarity helpers."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "data" / "team_aliases.json"

_HTML_TAG = re.compile(r"<[^>]+>")
_DISPLAY_MARKERS = re.compile(r"[\(（\[]\s*(?:主|中|中立|女|女子|U\d{1,2})\s*[\)）\]]", re.I)
_CHINESE_SUFFIXES = ("足球俱乐部", "俱乐部", "足球队", "联队", "球队", "队")
_LATIN_TOKENS = {"fc", "afc", "cf", "fk", "sk", "if", "bk", "club", "football"}


def clean_display_name(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _HTML_TAG.sub("", text)
    text = _DISPLAY_MARKERS.sub("", text)
    return unicodedata.normalize("NFKC", text).strip()


def normalize_team_name(value: Any) -> str:
    text = clean_display_name(value).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def compact_team_name(value: Any) -> str:
    text = clean_display_name(value).casefold()
    for suffix in _CHINESE_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
            break
    latin = [token for token in re.findall(r"[a-z0-9]+", text) if token not in _LATIN_TOKENS]
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
    return "".join(latin) + chinese


@lru_cache(maxsize=8)
def _registry(path_text: str = str(ALIASES_PATH)) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    rows = payload.get("teams") if isinstance(payload, dict) else payload
    canonical_by_name: dict[str, str] = {}
    groups: dict[str, frozenset[str]] = {}
    if isinstance(rows, dict):
        rows = [{"canonical": key, "aliases": value if isinstance(value, list) else [value]} for key, value in rows.items()]
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        canonical = normalize_team_name(row.get("canonical"))
        names = {canonical, compact_team_name(row.get("canonical"))}
        for alias in row.get("aliases") or []:
            names.update({normalize_team_name(alias), compact_team_name(alias)})
        names.discard("")
        frozen = frozenset(names)
        for name in names:
            canonical_by_name[name] = canonical
            groups[name] = frozen
    return canonical_by_name, groups


def reload_registry() -> None:
    _registry.cache_clear()


def team_names(value: Any) -> set[str]:
    normalized, compact = normalize_team_name(value), compact_team_name(value)
    _, groups = _registry()
    result = {normalized, compact}
    for token in tuple(result):
        result.update(groups.get(token) or ())
    result.discard("")
    return result


def canonical_team(value: Any) -> str:
    normalized, compact = normalize_team_name(value), compact_team_name(value)
    canonical, _ = _registry()
    return canonical.get(normalized) or canonical.get(compact) or normalized


def _is_cjk(value: str) -> bool:
    return bool(value) and not re.search(r"[a-z]", value)


def team_similarity(left: Any, right: Any) -> tuple[float, str]:
    left_names, right_names = team_names(left), team_names(right)
    if left_names & right_names:
        return 1.0, "confirmed_alias_or_exact"
    best = 0.0
    basis = "no_match"
    for first in left_names:
        for second in right_names:
            shorter, longer = sorted((first, second), key=len)
            if len(shorter) >= 2 and _is_cjk(shorter) and (longer.startswith(shorter) or longer.endswith(shorter)):
                if 0.92 > best:
                    best, basis = 0.92, "safe_chinese_prefix_or_suffix"
                continue
            if min(len(first), len(second)) >= 4 and (first in second or second in first):
                if 0.88 > best:
                    best, basis = 0.88, "long_substring"
                continue
            ratio = SequenceMatcher(None, first, second).ratio()
            if ratio >= 0.86 and ratio * 0.92 > best:
                best, basis = ratio * 0.92, "high_similarity"
    return round(best, 6), basis
