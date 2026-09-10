"""Thin Nowscore page adapters for the prematch evidence contract."""

from __future__ import annotations

import json
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

from nowscore_prematch_evidence import (
    FIELD_SURFACES,
    PARSER_VERSION,
    STATE_SET,
    SurfacePayload,
    _safe_text,
    parse_analysis_data,
    parse_coach_page,
    parse_panlu_page,
    parse_referee_page,
    parse_three_in_one,
)


class _DocumentParser(HTMLParser):
    """Extract headings, table rows, and visible text without retaining HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.headings: list[str] = []
        self.tables: list[list[list[str]]] = []
        self.sections: list[dict[str, Any]] = []
        self.section: dict[str, Any] | None = None
        self.heading_parts: list[str] | None = None
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell_parts: list[str] | None = None
        self.ignore_depth = 0

    def _boundary(self) -> None:
        self.text_parts.append("\n")
        if self.section is not None:
            self.section.setdefault("parts", []).append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in ("script", "style", "noscript"):
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._boundary()
            self.section = {"heading": "", "parts": [], "rows": []}
            self.sections.append(self.section)
            self.heading_parts = []
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell_parts = []
        elif tag in ("br", "p", "div", "li", "section", "article"):
            self._boundary()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in ("script", "style", "noscript"):
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if re.fullmatch(r"h[1-6]", tag) and self.heading_parts is not None:
            heading = _safe_text(" ".join(self.heading_parts))
            self.headings.append(heading)
            if self.section is not None:
                self.section["heading"] = heading
            self.heading_parts = None
        elif tag in ("td", "th") and self.row is not None and self.cell_parts is not None:
            self.row.append(_safe_text(" ".join(self.cell_parts)))
            self.cell_parts = None
        elif tag == "tr" and self.table is not None and self.row is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table:
                self.tables.append(self.table)
                if self.section is not None:
                    self.section.setdefault("rows", []).extend(self.table)
            self.table = None

    def handle_data(self, data: str) -> None:
        if self.ignore_depth or not data.strip():
            return
        self.text_parts.append(data)
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        elif self.cell_parts is not None:
            self.cell_parts.append(data)
        elif self.section is not None:
            self.section.setdefault("parts", []).append(data)


def _document(text: str) -> dict[str, Any]:
    parser = _DocumentParser()
    try:
        parser.feed(text or "")
        parser.close()
    except Exception:
        # The field adapters still expose explicit uncertainty for malformed
        # markup; they never fall back to prose or the unparsed body.
        pass
    sections = []
    for section in parser.sections:
        sections.append({
            "heading": _safe_text(section.get("heading")),
            "text": _safe_text(" ".join(section.get("parts") or []), 2000),
            "rows": [
                [_safe_text(cell, 120) for cell in row]
                for row in section.get("rows") or []
                if isinstance(row, list)
            ],
        })
    return {
        "text": _safe_text(" ".join(parser.text_parts), 12000),
        "headings": [_safe_text(value) for value in parser.headings],
        "tables": parser.tables,
        "sections": sections,
    }


def _contains(text: str, aliases: tuple[str, ...]) -> bool:
    lowered = (text or "").casefold()
    return any(alias.casefold() in lowered for alias in aliases)


def _matching_sections(document: dict[str, Any], aliases: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    for section in document.get("sections") or []:
        haystack = f"{section.get('heading') or ''} {section.get('text') or ''}"
        if _contains(haystack, aliases):
            result.append(section)
    if result:
        return result
    if _contains(str(document.get("text") or ""), aliases):
        return [{"heading": "", "text": document.get("text") or "", "rows": document.get("tables", [])[0] if document.get("tables") else []}]
    return []


def _explicit_empty(text: str) -> bool:
    return _contains(
        text,
        (
            "no data",
            "no record",
            "not available",
            "unavailable",
            "none",
            "暂无",
            "暂无资料",
            "暂无数据",
            "没有数据",
            "未提供",
            "无记录",
        ),
    )


def _date_hits(text: str) -> list[str]:
    return re.findall(
        r"(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2})?|\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})",
        text or "",
    )


def _score_hits(text: str) -> list[str]:
    return re.findall(r"\b\d{1,2}\s*[-:]\s*\d{1,2}\b", text or "")


def _numeric_values(row: list[str]) -> list[float]:
    values = []
    for cell in row:
        match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?", str(cell).strip())
        if not match:
            continue
        try:
            values.append(float(match.group(0).rstrip("%")))
        except ValueError:
            continue
    return values


def _section_evidence(
    document: dict[str, Any],
    field: str,
    aliases: tuple[str, ...],
    *,
    value_builder: Callable[[list[dict[str, Any]], str], tuple[Any, int, bool]] | None = None,
) -> tuple[str, Any, str, int, list[str]]:
    sections = _matching_sections(document, aliases)
    if not sections:
        return "ABSENT", None, "SECTION_NOT_FOUND", 0, []
    combined = " ".join(
        f"{section.get('heading') or ''} {section.get('text') or ''}"
        for section in sections
    )
    rows = [row for section in sections for row in (section.get("rows") or []) if any(row)]
    empty = _explicit_empty(combined)
    if value_builder is not None:
        value, record_count, item_found = value_builder(sections, combined)
    else:
        record_count = len(rows)
        item_found = bool(rows)
        value = {"record_count": record_count} if item_found else None
    if empty and item_found:
        return "CONFLICT", None, "EXPLICIT_EMPTY_AND_ITEMS", record_count, ["explicit_empty", "items"]
    if empty:
        return "SECTION_PRESENT_EMPTY", None, "SOURCE_EXPLICIT_EMPTY", 0, ["explicit_empty"]
    if item_found:
        return "PRESENT", value, "STRUCTURED_ITEMS_PARSED", record_count, ["items"]
    uncertainty_value = value if isinstance(value, dict) and value.get("semantic_state") else None
    return "PARSE_UNCERTAIN", uncertainty_value, "SECTION_MARKER_WITHOUT_ITEMS", 0, ["section_marker"]


def _field(
    state: str,
    *,
    value: Any = None,
    surface: str,
    reason_code: str,
    record_count: int = 0,
    semantic_state: str | None = None,
) -> dict[str, Any]:
    if state not in STATE_SET:
        state = "PARSE_UNCERTAIN"
    return {
        "state": state,
        "value": value if state == "PRESENT" else None,
        "reason_code": reason_code,
        "record_count": int(record_count or 0),
        "semantic_state": semantic_state,
        "surface": surface,
        "source_surfaces": [surface],
        "observed_at": None,
        "source_update_at": None,
        "prematch_eligible": None,
    }


def _stamp_fields(fields: dict[str, dict[str, Any]], observation: dict[str, Any]) -> None:
    observed_at = observation.get("observed_at")
    source_update_at = observation.get("source_update_at")
    eligible = None
    for item in fields.values():
        item["observed_at"] = observed_at
        item["source_update_at"] = source_update_at
        item["prematch_eligible"] = eligible


def _surface_health(
    surface: str,
    expected_markers: tuple[str, ...],
    body: str | None,
    observation: dict[str, Any],
    *,
    found_markers: list[str] | None = None,
    parsed_record_count: int = 0,
    parser_error: str | None = None,
) -> dict[str, Any]:
    found = found_markers or []
    error_code = str(observation.get("error_code") or "")
    if error_code == "ACCESS_GATED" or observation.get("http_status") in (401, 403):
        status = "ACCESS_GATED"
        drift = []
    elif error_code or body is None or observation.get("http_status", 200) >= 400:
        status = "UNAVAILABLE"
        drift = [error_code or "SURFACE_UNAVAILABLE"]
    elif parser_error:
        status = "DRIFT_SUSPECTED"
        drift = ["PARSER_EXCEPTION"]
    elif expected_markers and not found:
        status = "DRIFT_SUSPECTED"
        drift = ["EXPECTED_MARKERS_NOT_FOUND"]
    elif expected_markers and parsed_record_count == 0 and surface not in ("analysis_page", "time_page"):
        status = "DRIFT_SUSPECTED"
        drift = ["MARKERS_FOUND_BUT_NO_STRUCTURED_RECORD"]
    else:
        status = "HEALTHY"
        drift = []
    return {
        "surface": surface,
        "parser_version": PARSER_VERSION,
        "status": status,
        "expected_markers": list(expected_markers),
        "found_markers": list(found),
        "parsed_record_count": int(parsed_record_count or 0),
        "drift_reasons": drift,
        "observed_at": observation.get("observed_at"),
        "http_status": observation.get("http_status"),
    }


def _failed_fields(surface: str, error_code: str | None) -> dict[str, dict[str, Any]]:
    if error_code == "ACCESS_GATED":
        state, reason = "ACCESS_GATED", "SOURCE_ACCESS_GATED"
    elif error_code in {"HTTP_ERROR", "NETWORK_ERROR", "REQUEST_BUDGET_EXCEEDED"}:
        state, reason = "ABSENT", f"SOURCE_{error_code}"
    else:
        state, reason = "PARSE_UNCERTAIN", "SOURCE_RESPONSE_UNAVAILABLE"
    return {
        field: _field(state, surface=surface, reason_code=reason)
        for field, surfaces in FIELD_SURFACES.items()
        if surface in surfaces
    }


def _market_adapter(payload: SurfacePayload) -> dict[str, Any]:
    body = payload.body or ""
    expected = ("hide_scheduleId", "hide_matchTime", "home", "guest")
    found = [marker for marker in expected if marker.casefold() in body.casefold()]
    fields = {}
    legacy: dict[str, Any] = {}
    identity: dict[str, Any] = {}
    parse_error = None
    count = 0
    if body:
        try:
            legacy = parse_three_in_one(body)
            identity = legacy.get("identity") if isinstance(legacy.get("identity"), dict) else {}
            count = sum(int((legacy.get(key) or {}).get("total") or 0) for key in ("ouzhi", "yazhi", "daxiao"))
        except Exception as error:
            parse_error = type(error).__name__
    if parse_error:
        fields["market_context"] = _field("PARSE_UNCERTAIN", surface=payload.surface, reason_code="MARKET_PARSER_EXCEPTION")
    elif count:
        bookmakers = [
            {
                key: row.get(key)
                for key in ("name", "cid", "source_company_id", "spf_open", "spf_current")
                if key in row
            }
            for row in (legacy.get("ouzhi") or {}).get("bookmakers") or []
            if isinstance(row, dict)
        ][:50]
        asian = [
            {
                key: row.get(key)
                for key in ("name", "cid", "source_company_id", "open_handicap", "current_handicap", "current_water_home", "current_water_away")
                if key in row
            }
            for row in (legacy.get("yazhi") or {}).get("companies") or []
            if isinstance(row, dict)
        ][:50]
        totals = [
            {
                key: row.get(key)
                for key in ("name", "cid", "source_company_id", "open_line", "current_line", "current_over_water", "current_under_water")
                if key in row
            }
            for row in (legacy.get("daxiao") or {}).get("companies") or []
            if isinstance(row, dict)
        ][:50]
        fields["market_context"] = _field(
            "PRESENT",
            surface=payload.surface,
            reason_code="MARKET_TABLE_PARSED",
            record_count=count,
            value={
                "bookmaker_count": int((legacy.get("ouzhi") or {}).get("total") or 0),
                "asian_count": int((legacy.get("yazhi") or {}).get("total") or 0),
                "total_count": int((legacy.get("daxiao") or {}).get("total") or 0),
                "valid_1x2_count": sum(
                    1 for row in (legacy.get("ouzhi") or {}).get("bookmakers") or []
                    if all((row.get("spf_current") or {}).get(side) for side in ("home", "draw", "away"))
                ),
                "bookmakers": bookmakers,
                "asian_handicap": asian,
                "goal_total": totals,
            },
        )
    elif identity:
        fields["market_context"] = _field(
            "SECTION_PRESENT_EMPTY",
            surface=payload.surface,
            reason_code="MARKET_IDENTITY_PRESENT_QUOTES_EMPTY",
        )
    else:
        fields["market_context"] = _field(
            "PARSE_UNCERTAIN",
            surface=payload.surface,
            reason_code="MARKET_IDENTITY_OR_TABLE_MISSING",
        )
    _stamp_fields(fields, payload.observation)
    health = _surface_health(
        payload.surface,
        expected,
        body if payload.body is not None else None,
        payload.observation,
        found_markers=found,
        parsed_record_count=count,
        parser_error=parse_error,
    )
    return {"fields": fields, "legacy": legacy, "identity": identity, "health": health}


def _analysis_data_adapter(payload: SurfacePayload) -> dict[str, Any]:
    body = payload.body or ""
    expected = ("h_data", "a_data")
    found = [marker for marker in expected if re.search(rf"(?:var\s+)?{marker}\s*=", body)]
    parsed: dict[str, Any] = {}
    parse_error = None
    count = 0
    if body:
        try:
            parsed = parse_analysis_data(body) or {}
            recent = parsed.get("recent_matches") if isinstance(parsed, dict) else {}
            count = sum(len(recent.get(side) or []) for side in ("home_team", "away_team")) if isinstance(recent, dict) else 0
        except Exception as error:
            parse_error = type(error).__name__
    fields: dict[str, dict[str, Any]] = {}
    if parsed.get("recent_form"):
        fields["recent_form"] = _field(
            "PRESENT",
            surface=payload.surface,
            reason_code="ANALYSIS_DATA_RECENT_FORM_PARSED",
            record_count=count,
            value={
                "summary": parsed.get("recent_form"),
                "team_ids": parsed.get("team_ids") or {},
                "recent_match_count": count,
            },
        )
    elif parse_error:
        fields["recent_form"] = _field("PARSE_UNCERTAIN", surface=payload.surface, reason_code="ANALYSIS_DATA_PARSER_EXCEPTION")
    elif found:
        fields["recent_form"] = _field("PARSE_UNCERTAIN", surface=payload.surface, reason_code="ANALYSIS_DATA_MARKERS_WITHOUT_FORM")
    else:
        fields["recent_form"] = _field("ABSENT", surface=payload.surface, reason_code="ANALYSIS_DATA_MARKER_MISSING")
    _stamp_fields(fields, payload.observation)
    health = _surface_health(
        payload.surface,
        expected,
        body if payload.body is not None else None,
        payload.observation,
        found_markers=found,
        parsed_record_count=count,
        parser_error=parse_error,
    )
    return {"fields": fields, "legacy": parsed, "health": health}


SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "competition_standings_stage": ("standing", "table", "stage", "round", "积分榜", "排名", "阶段", "轮次"),
    "h2h": ("h2h", "head to head", "history meeting", "历史交锋", "交锋", "对赛"),
    "future_schedule_rest": ("future schedule", "upcoming", "next match", "future", "未来赛程", "下一场", "休息", "rest"),
    "injuries": ("injur", "伤停", "伤病"),
    "suspensions": ("suspension", "suspended", "停赛"),
    "lineup_state": ("lineup", "starting eleven", "starting", "首发", "阵容"),
    "technical_stats": ("technical", "statistics", "statistic", "技术统计", "技术面"),
}


def _competition_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
    stage_match = re.search(r"(?:stage|round|阶段|轮次)\s*[:：]?\s*([A-Za-z0-9一二三四五六七八九十-]{1,30})", combined, re.I)
    value: dict[str, Any] = {"standings_row_count": len(rows)}
    if stage_match:
        value["stage_or_round"] = _safe_text(stage_match.group(1), 40)
    return value, len(rows), bool(rows) or bool(stage_match)


def _h2h_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
    records: list[dict[str, str | None]] = []
    for row in rows:
        score = [cell for cell in row if re.fullmatch(r"\d{1,2}\s*[-:]\s*\d{1,2}", cell.strip())]
        date = [cell for cell in row if _date_hits(cell)]
        if score or date:
            records.append({
                "date": _safe_text(date[0], 40) if date else None,
                "score": _safe_text(score[0], 20) if score else None,
            })
        if len(records) >= 50:
            break
    scores = [record["score"] for record in records if record.get("score")]
    dates = [record["date"] for record in records if record.get("date")]
    count = len(records)
    return {
        "meeting_row_count": count,
        "score_count": len(scores),
        "date_count": len(dates),
        "records": records,
    }, count, bool(records)


def _future_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
    dates = [cell for row in rows for cell in row if _date_hits(cell)]
    rest = re.search(r"(?:rest|休息)\s*(?:hours?|time|时长|时间)?\s*[:：]?\s*(\d+(?:\.\d+)?)", combined, re.I)
    value: dict[str, Any] = {"future_fixture_count": len(dates)}
    if dates:
        value["explicit_schedule_tokens"] = [_safe_text(item, 40) for item in dates[:20]]
    if rest:
        value["rest_hours_source"] = float(rest.group(1))
    return value, max(len(rows), len(dates)), bool(rows or dates or rest)


def _availability_builder(kind: str) -> Callable[[list[dict[str, Any]], str], tuple[Any, int, bool]]:
    def builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
        rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
        content = " ".join(str(section.get("text") or "") for section in sections)
        item_words = {
            "injuries": ("player", "injury", "out", "疑似", "缺阵"),
            "suspensions": ("player", "suspension", "suspended", "停赛", "禁赛"),
        }[kind]
        item_found = bool(rows) or _contains(content, item_words)
        return {"record_count": len(rows), "source_semantics": kind}, len(rows), item_found
    return builder


def _lineup_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
    if _contains(combined, ("confirmed", "official", "已公布", "确定首发")):
        semantic = "CONFIRMED"
    elif _contains(combined, ("predicted", "expected", "probable", "预计", "可能")):
        semantic = "PREDICTED"
    else:
        semantic = "UNLABELLED"
    # A lineup table without an explicit confirmed/predicted source label is
    # deliberately not promoted to factual availability.
    item_found = semantic != "UNLABELLED" and (bool(rows) or bool(combined))
    return {"record_count": len(rows), "source_semantics": "lineup", "semantic_state": semantic}, len(rows), item_found


_TECHNICAL_STAT_LABELS = (
    "possession",
    "shot",
    "xg",
    "expected goal",
    "corner",
    "foul",
    "offside",
    "yellow card",
    "red card",
    "attack",
    "dangerous attack",
    "save",
    "goal kick",
    "free kick",
    "throw-in",
    "pass",
    "tackle",
    "interception",
    "clearance",
    "cross",
    "big chance",
    "dribble",
    "duel",
    "控球",
    "射门",
    "射正",
    "角球",
    "犯规",
    "越位",
    "黄牌",
    "红牌",
    "进攻",
    "危险进攻",
    "扑救",
    "球门球",
    "任意球",
    "界外球",
    "传球",
    "抢断",
    "拦截",
    "解围",
    "传中",
    "控球率",
)

_MARKET_STAT_LABELS = (
    "opening",
    "closing",
    "current odds",
    "handicap",
    "asian",
    "moneyline",
    "over/under",
    "over under",
    "odds",
    "water",
    "market",
    "price",
    "spread",
    "line",
    "1x2",
    "total",
    "over",
    "under",
    "initial",
    "初",
    "即",
    "盘口",
    "水位",
    "赔率",
    "让球",
    "大小球",
    "欧赔",
    "亚盘",
    "胜平负",
)


def _is_technical_stat_label(label: str) -> bool:
    normalized = re.sub(r"[\s:_/\\-]+", " ", str(label or "").casefold()).strip()
    if not normalized:
        return False
    if any(token.casefold() in normalized for token in _MARKET_STAT_LABELS):
        return False
    return any(token.casefold() in normalized for token in _TECHNICAL_STAT_LABELS)


def _technical_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    stats: list[dict[str, Any]] = []
    for section in sections:
        for row in section.get("rows") or []:
            values = _numeric_values(row)
            if len(values) < 2:
                continue
            label = _safe_text(row[0] if row else "", 80)
            if not _is_technical_stat_label(label):
                continue
            stats.append({"label": label, "values": values[:6]})
            if len(stats) >= 50:
                break
    return {"stat_count": len(stats), "stats": stats}, len(stats), bool(stats)


def _markup_adapter(payload: SurfacePayload, target: Mapping[str, Any]) -> dict[str, Any]:
    body = payload.body or ""
    document = _document(body)
    fields: dict[str, dict[str, Any]] = {}
    builders: dict[str, Callable[[list[dict[str, Any]], str], tuple[Any, int, bool]] | None] = {
        "competition_standings_stage": _competition_builder,
        "h2h": _h2h_builder,
        "future_schedule_rest": _future_builder,
        "injuries": _availability_builder("injuries"),
        "suspensions": _availability_builder("suspensions"),
        "lineup_state": _lineup_builder,
        "technical_stats": _technical_builder,
    }
    expected: list[str] = []
    found: list[str] = []
    parsed_count = 0
    for field, builder in builders.items():
        if payload.surface not in FIELD_SURFACES[field]:
            continue
        aliases = SECTION_ALIASES[field]
        expected.extend(aliases[:2])
        if _contains(str(document.get("text") or ""), aliases):
            found.append(aliases[0])
        state, value, reason, count, _signals = _section_evidence(
            document,
            field,
            aliases,
            value_builder=builder,
        )
        semantic = value.get("semantic_state") if isinstance(value, dict) else None
        if field == "lineup_state" and isinstance(value, dict):
            semantic = value.pop("semantic_state", None)
        fields[field] = _field(
            state,
            value=value,
            surface=payload.surface,
            reason_code=reason,
            record_count=count,
            semantic_state=semantic,
        )
        parsed_count += count
    _stamp_fields(fields, payload.observation)
    health = _surface_health(
        payload.surface,
        tuple(dict.fromkeys(expected)),
        body if payload.body is not None else None,
        payload.observation,
        found_markers=found,
        parsed_record_count=parsed_count,
    )
    return {"fields": fields, "legacy": {}, "health": health}


def _coach_adapter(payload: SurfacePayload) -> dict[str, Any]:
    body = payload.body or ""
    expected = ("hc_data", "gc_data", "coach", "教练")
    found = [marker for marker in expected if marker.casefold() in body.casefold()]
    parsed: dict[str, Any] = {}
    error = None
    count = 0
    if body:
        try:
            parsed = parse_coach_page(body) or {}
            for side in ("home", "away"):
                profile = parsed.get(side) if isinstance(parsed.get(side), dict) else {}
                count += len(profile.get("coach_records") or []) + len(profile.get("team_records") or [])
        except Exception as exc:
            error = type(exc).__name__
    home_profile = parsed.get("home") if isinstance(parsed.get("home"), dict) else {}
    away_profile = parsed.get("away") if isinstance(parsed.get("away"), dict) else {}
    value = {
        "home": {
            "name": _safe_text(home_profile.get("name"), 80) or None,
            "coach_record_count": len(home_profile.get("coach_records") or []),
            "team_record_count": len(home_profile.get("team_records") or []),
        },
        "away": {
            "name": _safe_text(away_profile.get("name"), 80) or None,
            "coach_record_count": len(away_profile.get("coach_records") or []),
            "team_record_count": len(away_profile.get("team_records") or []),
        },
    }
    fields = {
        "coach": _field(
            "PRESENT" if count or any(parsed.get(side) for side in ("home", "away")) else ("PARSE_UNCERTAIN" if body else "ABSENT"),
            value=value,
            surface=payload.surface,
            reason_code="COACH_STRUCTURED_RECORDS_PARSED" if count else "COACH_SECTION_UNCERTAIN",
            record_count=count,
        )
    }
    _stamp_fields(fields, payload.observation)
    health = _surface_health(payload.surface, expected, body if payload.body is not None else None, payload.observation, found_markers=found, parsed_record_count=count, parser_error=error)
    return {"fields": fields, "legacy": parsed, "health": health}


def _referee_adapter(payload: SurfacePayload) -> dict[str, Any]:
    body = payload.body or ""
    expected = ("referee", "裁判", "h_data", "a_data")
    found = [marker for marker in expected if marker.casefold() in body.casefold()]
    parsed: dict[str, Any] = {}
    error = None
    if body:
        try:
            parsed = parse_referee_page(body) or {}
        except Exception as exc:
            error = type(exc).__name__
    summaries = parsed.get("summaries") if isinstance(parsed, dict) else []
    count = len(summaries or []) + int(parsed.get("home_team_history_count") or 0) + int(parsed.get("away_team_history_count") or 0)
    value = {
        "name": _safe_text(parsed.get("name"), 80) or None,
        "referee_profile_present": bool(parsed.get("name")),
        "summary_count": len(summaries or []),
        "home_team_history_count": int(parsed.get("home_team_history_count") or 0),
        "away_team_history_count": int(parsed.get("away_team_history_count") or 0),
    }
    state = "PRESENT" if count or parsed.get("name") else ("PARSE_UNCERTAIN" if body else "ABSENT")
    fields = {"referee": _field(state, value=value, surface=payload.surface, reason_code="REFEREE_STRUCTURED_RECORDS_PARSED" if state == "PRESENT" else "REFEREE_SECTION_UNCERTAIN", record_count=count)}
    _stamp_fields(fields, payload.observation)
    health = _surface_health(payload.surface, expected, body if payload.body is not None else None, payload.observation, found_markers=found, parsed_record_count=count, parser_error=error)
    return {"fields": fields, "legacy": parsed, "health": health}


def _panlu_adapter(payload: SurfacePayload) -> dict[str, Any]:
    body = payload.body or ""
    expected = ("a[", "panlu", "盘路")
    found = [marker for marker in expected if marker.casefold() in body.casefold()]
    parsed: dict[str, Any] = {}
    error = None
    if body:
        try:
            parsed = parse_panlu_page(body) or {}
        except Exception as exc:
            error = type(exc).__name__
    count = int(parsed.get("count") or 0)
    fields = {
        "panlu": _field(
            "PRESENT" if count else ("PARSE_UNCERTAIN" if body else "ABSENT"),
            value={
                "match_count": count,
                "score_count": sum(bool(row.get("full_time")) for row in parsed.get("matches") or []),
                "matches": [
                    {
                        key: row.get(key)
                        for key in ("match_id", "kickoff", "full_time", "half_time", "asian_line", "total_line")
                        if key in row
                    }
                    for row in (parsed.get("matches") or [])[:60]
                    if isinstance(row, dict)
                ],
            },
            surface=payload.surface,
            reason_code="PANLU_STRUCTURED_MATCHES_PARSED" if count else "PANLU_SECTION_UNCERTAIN",
            record_count=count,
        )
    }
    _stamp_fields(fields, payload.observation)
    health = _surface_health(payload.surface, expected, body if payload.body is not None else None, payload.observation, found_markers=found, parsed_record_count=count, parser_error=error)
    return {"fields": fields, "legacy": parsed, "health": health}


def _adapter(surface: str, payload: SurfacePayload, target: Mapping[str, Any]) -> dict[str, Any]:
    error_code = payload.observation.get("error_code")
    if error_code or payload.body is None or int(payload.observation.get("http_status") or 200) >= 400:
        fields = _failed_fields(surface, error_code)
        _stamp_fields(fields, payload.observation)
        expected = {
            "market_context": ("hide_scheduleId", "hide_matchTime", "home", "guest"),
            "analysis_data": ("h_data", "a_data"),
            "analysis_page": ("standing", "h2h", "future"),
            "time_page": ("lineup", "technical", "injury"),
            "coach": ("hc_data", "gc_data"),
            "referee": ("referee", "h_data", "a_data"),
            "panlu": ("a[", "panlu"),
        }[surface]
        health = _surface_health(surface, expected, None, payload.observation)
        return {"fields": fields, "legacy": {}, "identity": {}, "health": health}
    if surface == "market_context":
        return _market_adapter(payload)
    if surface == "analysis_data":
        return _analysis_data_adapter(payload)
    if surface in ("analysis_page", "time_page"):
        return _markup_adapter(payload, target)
    if surface == "coach":
        return _coach_adapter(payload)
    if surface == "referee":
        return _referee_adapter(payload)
    if surface == "panlu":
        return _panlu_adapter(payload)
    return {"fields": {}, "legacy": {}, "health": {"surface": surface, "status": "UNAVAILABLE", "drift_reasons": ["UNKNOWN_SURFACE"]}}
