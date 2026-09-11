"""Thin Nowscore page adapters for the prematch evidence contract."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
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
        self.table_records: list[dict[str, Any]] = []
        self.sections: list[dict[str, Any]] = []
        self.section: dict[str, Any] | None = None
        self.heading_parts: list[str] | None = None
        self.table: list[list[str]] | None = None
        self.table_context: dict[str, str] = {}
        self.row: list[str] | None = None
        self.cell_parts: list[str] | None = None
        self.ignore_depth = 0
        self.tag_stack: list[str] = []
        self.marker_stack: list[dict[str, Any]] = []
        self.last_markers: dict[str, str] = {}

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
        self.tag_stack.append(tag)
        class_tokens = {
            str(value or "").casefold()
            for key, value in attrs
            if key.casefold() == "class"
        }
        for marker in ("fenxibar", "resultbar", "subbar"):
            if marker in class_tokens:
                self.marker_stack.append({
                    "kind": marker,
                    "tag": tag,
                    "depth": len(self.tag_stack),
                    "parts": [],
                })
                break
        if re.fullmatch(r"h[1-6]", tag):
            self._boundary()
            self.section = {"heading": "", "parts": [], "rows": []}
            self.sections.append(self.section)
            self.heading_parts = []
        elif tag == "table":
            self.table = []
            self.table_context = dict(self.last_markers)
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
        depth = len(self.tag_stack)
        if self.marker_stack and self.marker_stack[-1].get("depth") == depth and self.marker_stack[-1].get("tag") == tag:
            marker = self.marker_stack.pop()
            value = _safe_text(" ".join(marker.get("parts") or []), 240)
            kind = str(marker.get("kind") or "")
            if kind == "fenxibar":
                self.last_markers = {"fenxibar": value}
            elif kind in {"resultbar", "subbar"}:
                self.last_markers[kind] = value
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
            self.table_records.append({
                "rows": [list(row) for row in self.table],
                "context": dict(self.table_context),
            })
            self.table = None
            self.table_context = {}
        if self.tag_stack:
            self.tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.ignore_depth or not data.strip():
            return
        self.text_parts.append(data)
        if self.marker_stack:
            self.marker_stack[-1].setdefault("parts", []).append(data)
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        elif self.cell_parts is not None:
            self.cell_parts.append(data)
        elif self.section is not None:
            self.section.setdefault("parts", []).append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


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
        "table_records": parser.table_records,
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
    "injuries": ("injur", "伤停", "伤病"),
    "suspensions": ("suspension", "suspended", "停赛"),
    "lineup_state": ("lineup", "starting eleven", "starting", "首发", "阵容"),
    "technical_stats": ("technical", "statistics", "statistic", "技术统计", "技术面"),
}


def _competition_builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
    rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
    rank_labels = ("rank", "ranking", "position", "standing", "place", "排名", "名次")
    points_labels = ("points", "point", "pts", "积分", "积分数")
    rank_fact_count = 0
    points_fact_count = 0
    for section in sections:
        section_rows = [row for row in section.get("rows") or [] if any(row)]
        if not section_rows:
            continue
        header = " ".join(section_rows[0])
        numeric_data_rows = [row for row in section_rows[1:] if _numeric_values(row)]
        if _contains(header, rank_labels):
            rank_fact_count += len(numeric_data_rows)
        if _contains(header, points_labels):
            points_fact_count += len(numeric_data_rows)
        for row in section_rows:
            numeric_cells = _numeric_values(row[1:])
            if numeric_cells and _contains(str(row[0] if row else ""), rank_labels):
                rank_fact_count += 1
            if numeric_cells and _contains(str(row[0] if row else ""), points_labels):
                points_fact_count += 1
    stage_match = re.search(r"(?:stage|round|阶段|轮次)\s*[:：]?\s*([A-Za-z0-9一二三四五六七八九十-]{1,30})", combined, re.I)
    value: dict[str, Any] = {
        "standings_row_count": len(rows),
        "rank_fact_count": rank_fact_count,
        "points_fact_count": points_fact_count,
    }
    if stage_match:
        value["stage_or_round"] = _safe_text(stage_match.group(1), 40)
    fact_count = rank_fact_count + points_fact_count + (1 if stage_match else 0)
    return value, fact_count, bool(fact_count)


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


def _availability_status_match(text: str, words: tuple[str, ...]) -> bool:
    lowered = str(text or "").casefold()
    return any(
        bool(re.search(rf"\b{re.escape(word.casefold())}\b", lowered))
        if word.isascii()
        else word.casefold() in lowered
        for word in words
    )


def _availability_structured_rows(rows: list[list[str]], kind: str) -> list[dict[str, Any]]:
    status_words = {
        "injuries": ("injured", "sidelined", "out", "doubtful", "questionable", "unfit", "illness", "伤", "伤病", "缺阵"),
        "suspensions": ("suspended", "suspension", "ban", "red card", "停赛", "禁赛", "红牌"),
    }[kind]
    generic_cells = {
        "status", "count", "player", "name", "type", "reason", "date", "injury", "injuries", "suspension", "suspensions",
    }
    structured_rows = []
    for row in rows:
        cells = [_safe_text(cell, 120) for cell in row if _safe_text(cell, 120)]
        if len(cells) < 2:
            continue
        status_cells = [cell for cell in cells if _availability_status_match(cell, status_words)]
        if not status_cells:
            continue
        subject_cells = []
        for cell in cells:
            normalized = re.sub(r"\s+", " ", cell.casefold()).strip()
            if normalized in generic_cells or _numeric_values([cell]):
                continue
            if _availability_status_match(normalized, status_words):
                continue
            subject_cells.append(cell)
        if subject_cells:
            structured_rows.append({"structured": True, "status": status_cells[0]})
    return structured_rows


def _availability_builder(kind: str) -> Callable[[list[dict[str, Any]], str], tuple[Any, int, bool]]:
    def builder(sections: list[dict[str, Any]], combined: str) -> tuple[Any, int, bool]:
        rows = [row for section in sections for row in section.get("rows") or [] if any(row)]
        structured_rows = _availability_structured_rows(rows, kind)
        count = len(structured_rows)
        return {
            "structured_record_count": count,
            "status_values": [row["status"] for row in structured_rows[:20]],
            "source_semantics": kind,
        }, count, bool(structured_rows)
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


# Issue #284 deliberately does not use SECTION_ALIASES or the document-text
# fallback.  These markers and table shapes are the only promotion path for
# the three same-ID analysis_page fields below.
_STRICT_STANDINGS_MARKERS = ("\u79ef\u5206\u6392\u540d", "standings")
_STRICT_FUTURE_MARKERS = ("\u672a\u6765\u4e09\u573a", "future schedule")
_STRICT_AVAILABILITY_MARKERS = ("\u4f24\u505c\u60c5\u51b5", "injury status")
_STRICT_STANDINGS_SPLITS = {
    "total": frozenset(("\u603b", "\u5168\u573a", "total", "overall")),
    "home": frozenset(("\u4e3b", "\u4e3b\u573a", "home")),
    "away": frozenset(("\u5ba2", "\u5ba2\u573a", "away")),
    "recent": frozenset(("\u8fd1", "\u8fd1\u51b5", "recent", "last")),
}
_STRICT_STANDINGS_COLUMNS = {
    "matches": frozenset(("\u8d5b", "\u573a", "mp", "matches")),
    "wins": frozenset(("\u80dc", "w", "wins")),
    "draws": frozenset(("\u5e73", "d", "draws")),
    "losses": frozenset(("\u8d1f", "l", "losses")),
    "goals_for": frozenset(("\u5f97", "\u8fdb", "gf", "goalsfor")),
    "goals_against": frozenset(("\u5931", "ga", "goalsagainst")),
    "goal_difference": frozenset(("\u51c0", "gd", "goaldifference")),
    "points": frozenset(("\u79ef\u5206", "\u79ef\u5206\u6570", "pts", "points")),
    "rank": frozenset(("\u6392\u540d", "rank", "ranking", "position")),
}
_STRICT_FUTURE_COLUMNS = {
    "date": frozenset(("\u65f6\u95f4", "date", "time")),
    "competition": frozenset(("\u8d5b\u4e8b", "competition", "league")),
    "home": frozenset(("\u4e3b\u961f", "home")),
    "away": frozenset(("\u5ba2\u961f", "away")),
    "interval": frozenset(("\u95f4\u9694", "interval", "rest")),
}
_STRICT_AVAILABILITY_KINDS = {
    "injury": frozenset(("\u4f24\u5458", "\u4f24\u75c5", "\u4f24\u505c", "injury", "injuries")),
    "suspension": frozenset(("\u505c\u8d5b", "suspension", "suspended")),
}
_STRICT_EMPTY_MARKERS = frozenset((
    "no data",
    "no record",
    "none",
    "unavailable",
    "\u6682\u65e0",
    "\u6682\u65e0\u6570\u636e",
    "\u6ca1\u6709\u6570\u636e",
    "\u65e0\u8bb0\u5f55",
))


def _strict_normalize(value: Any) -> str:
    return re.sub(r"[\s\u3000]+", "", _safe_text(value, 240)).casefold()


def _strict_marker_matches(value: Any, aliases: tuple[str, ...]) -> bool:
    normalized = _strict_normalize(value)
    return bool(normalized) and normalized in {_strict_normalize(alias) for alias in aliases}


def _strict_team_key(value: Any) -> str:
    text = _safe_text(value, 160)
    text = re.sub(
        r"\s*[\(\uff08]\s*(?:home|away|\u4e3b|\u5ba2)\s*[\)\uff09]\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strict_target_team_keys(target: Mapping[str, Any]) -> dict[str, str]:
    return {
        "home": _strict_team_key(target.get("identity_home") or target.get("home")),
        "away": _strict_team_key(target.get("identity_away") or target.get("away")),
    }


def _strict_bound_side(value: Any, target: Mapping[str, Any]) -> tuple[str | None, str | None]:
    raw = _safe_text(value, 160)
    if not raw:
        return None, "SIDE_BINDING_MISSING"
    keys = _strict_target_team_keys(target)
    if not keys["home"] or not keys["away"] or keys["home"] == keys["away"]:
        return None, "TARGET_SIDE_BINDING_AMBIGUOUS"
    matches = [side for side in ("home", "away") if _strict_team_key(raw) == keys[side]]
    if len(matches) == 1:
        return matches[0], None
    return None, "WRONG_TEAM_BINDING"


def _strict_table_records(document: Mapping[str, Any], markers: tuple[str, ...]) -> list[dict[str, Any]]:
    records = []
    for record in document.get("table_records") or []:
        if not isinstance(record, Mapping):
            continue
        context = record.get("context") if isinstance(record.get("context"), Mapping) else {}
        if _strict_marker_matches(context.get("fenxibar"), markers):
            records.append({
                "rows": [list(row) for row in record.get("rows") or [] if isinstance(row, list)],
                "context": dict(context),
            })
    return records


def _strict_explicit_empty(rows: list[list[str]]) -> bool:
    markers = {_strict_normalize(marker) for marker in _STRICT_EMPTY_MARKERS}
    for row in rows:
        text = _strict_normalize(" ".join(str(cell or "") for cell in row))
        if any(marker and marker in text for marker in markers):
            return True
    return False


def _strict_header_indices(row: list[str], columns: Mapping[str, frozenset[str]]) -> dict[str, int] | None:
    indices: dict[str, int] = {}
    normalized = [_strict_normalize(cell) for cell in row]
    for name, aliases in columns.items():
        matches = [index for index, cell in enumerate(normalized) if cell in aliases]
        if len(matches) != 1:
            if name == "interval":
                continue
            return None
        indices[name] = matches[0]
    return indices


def _strict_integer(value: Any) -> int | None:
    text = _safe_text(value, 40)
    if not re.fullmatch(r"[-+]?\d+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _strict_parse_standings_table(record: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str | None, dict[str, Any] | None, str | None, bool]:
    context = record.get("context") if isinstance(record.get("context"), Mapping) else {}
    side, side_reason = _strict_bound_side(context.get("resultbar"), target)
    if side_reason:
        return side, None, "STANDINGS_" + side_reason, False
    rows = record.get("rows") or []
    if rows and _strict_explicit_empty(rows) and (
        len(rows) == 1
        or all(not any(_safe_text(cell, 160) for cell in row) or _strict_explicit_empty([row]) for row in rows[1:])
    ):
        return side, None, None, True
    if not rows:
        return side, None, "STANDINGS_TABLE_ROWS_MISSING", False
    indices = _strict_header_indices(rows[0], _STRICT_STANDINGS_COLUMNS)
    if indices is None:
        return side, None, "STANDINGS_HEADER_INCOMPLETE", False
    split_rows: dict[str, dict[str, int]] = {}
    recognized = 0
    for row in rows[1:]:
        label = _strict_normalize(row[0] if row else "")
        if not label or _strict_explicit_empty([row]):
            continue
        split = next((name for name, aliases in _STRICT_STANDINGS_SPLITS.items() if label in aliases), None)
        if split is None:
            continue
        recognized += 1
        if split in split_rows or len(row) <= max(indices.values()):
            return side, None, "STANDINGS_ROW_AMBIGUOUS", False
        values: dict[str, int] = {}
        for name, index in indices.items():
            parsed = _strict_integer(row[index])
            if parsed is None:
                return side, None, "STANDINGS_ROW_MALFORMED", False
            if name != "goal_difference" and parsed < 0:
                return side, None, "STANDINGS_ROW_NEGATIVE_METRIC", False
            values[name] = parsed
        split_rows[split] = values
    if not recognized or "total" not in split_rows:
        return side, None, "STANDINGS_SPLIT_ROWS_INCOMPLETE", False
    return side, {"splits": split_rows}, None, False


def _strict_kickoff_date(value: Any) -> date | None:
    text = _safe_text(value, 80).replace("Z", "+00:00")
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _strict_future_date(value: Any) -> date | None:
    text = _safe_text(value, 80).replace(".", "-").replace("/", "-")
    match = re.fullmatch(r"(20\d{2}|\d{2})-(\d{1,2})-(\d{1,2})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", text)
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    try:
        return date(year, int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _strict_interval_days(value: Any) -> int | None:
    text = _safe_text(value, 40).casefold()
    match = re.fullmatch(r"(\d+)\s*(?:\u5929|days?|d)", text)
    if not match:
        return None
    return int(match.group(1))


def _strict_parse_future_table(record: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str | None, list[dict[str, Any]], str | None, bool]:
    context = record.get("context") if isinstance(record.get("context"), Mapping) else {}
    table_side, side_reason = _strict_bound_side(context.get("resultbar"), target)
    if side_reason:
        return table_side, [], "FUTURE_" + side_reason, False
    rows = record.get("rows") or []
    if not rows:
        return table_side, [], "FUTURE_TABLE_ROWS_MISSING", False
    if rows and _strict_explicit_empty(rows) and (
        len(rows) == 1
        or all(not any(_safe_text(cell, 160) for cell in row) or _strict_explicit_empty([row]) for row in rows[1:])
    ):
        return table_side, [], None, True
    indices = _strict_header_indices(rows[0], _STRICT_FUTURE_COLUMNS)
    if indices is None:
        return table_side, [], "FUTURE_HEADER_INCOMPLETE", False
    kickoff = _strict_kickoff_date(target.get("kickoff"))
    if kickoff is None:
        return table_side, [], "FUTURE_KICKOFF_CONTEXT_MISSING", False
    team_keys = _strict_target_team_keys(target)
    if not team_keys["home"] or not team_keys["away"] or team_keys["home"] == team_keys["away"]:
        return table_side, [], "FUTURE_TARGET_SIDE_BINDING_AMBIGUOUS", False
    fixtures: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not any(_safe_text(cell, 160) for cell in row):
            continue
        if _strict_explicit_empty([row]):
            continue
        if len(row) <= max(indices.values()):
            return table_side, [], "FUTURE_ROW_MALFORMED", False
        when = _strict_future_date(row[indices["date"]])
        competition = _safe_text(row[indices["competition"]], 120)
        home = _safe_text(row[indices["home"]], 160)
        away = _safe_text(row[indices["away"]], 160)
        if when is None or not competition or not home or not away:
            return table_side, [], "FUTURE_ROW_MALFORMED", False
        delta = (when - kickoff).days
        if delta <= 0:
            return table_side, [], "FUTURE_DATE_NOT_AFTER_KICKOFF", False
        orientations = []
        if _strict_team_key(home) in team_keys.values():
            orientations.append("home")
        if _strict_team_key(away) in team_keys.values():
            orientations.append("away")
        if len(orientations) != 1:
            return table_side, [], "FUTURE_TARGET_ORIENTATION_AMBIGUOUS", False
        target_orientation = orientations[0]
        explicit_interval = None
        if "interval" in indices:
            raw_interval = _safe_text(row[indices["interval"]], 40)
            if raw_interval not in {"", "-", "--"}:
                explicit_interval = _strict_interval_days(raw_interval)
                if explicit_interval is None:
                    return table_side, [], "FUTURE_INTERVAL_MALFORMED", False
        interval_days = explicit_interval if explicit_interval is not None else delta
        fixtures.append({
            "date": when.isoformat(),
            "competition": competition,
            "home_team": home,
            "away_team": away,
            "target_orientation": target_orientation,
            "interval_days": interval_days,
            "interval_source": "source_interval" if explicit_interval is not None else "deterministic_date_interval",
            "date_delta_days": delta,
            "interval_consistency": (
                "source_matches_date_delta"
                if explicit_interval is not None and explicit_interval == delta
                else "source_interval_authoritative"
                if explicit_interval is not None
                else "deterministic_from_dates"
            ),
        })
    if not fixtures:
        return table_side, [], "FUTURE_ROWS_MISSING", False
    return table_side, fixtures, None, False


def _strict_availability_kind(value: Any) -> str | None:
    normalized = _strict_normalize(value)
    for kind, aliases in _STRICT_AVAILABILITY_KINDS.items():
        if normalized in aliases:
            return kind
    return None


def _strict_availability_position(cells: list[str]) -> str | None:
    text = " ".join(_safe_text(cell, 120) for cell in cells)
    normalized = text.casefold()
    if re.search(r"[\(\uff08]\s*(?:\u5b88\u95e8\u5458|\u95e8\u5c06)\s*[\)\uff09]", text):
        return "goalkeeper"
    if re.search(r"[\(\uff08]\s*(?:\u540e\u536b|\u4e2d\u536b|\u8fb9\u540e\u536b|\u5de6\u540e\u536b|\u53f3\u540e\u536b)\s*[\)\uff09]", text):
        return "defender"
    if re.search(r"[\(\uff08]\s*(?:\u4e2d\u573a|\u540e\u8170|\u524d\u8170|\u8fb9\u524d\u536b)\s*[\)\uff09]", text):
        return "midfielder"
    if re.search(r"[\(\uff08]\s*(?:\u524d\u950b|\u4e2d\u950b|\u8fb9\u950b)\s*[\)\uff09]", text):
        return "forward"
    if re.search(r"\b(?:goalkeeper|keeper|gk)\b", normalized):
        return "goalkeeper"
    if re.search(r"\b(?:defender|back|cb|lb|rb)\b", normalized):
        return "defender"
    if re.search(r"\b(?:midfielder|midfield|dm|cm|am)\b", normalized):
        return "midfielder"
    if re.search(r"\b(?:forward|striker|fw|cf|ss)\b", normalized):
        return "forward"
    return None


_STRICT_AVAILABILITY_GENERIC = frozenset((
    "side", "team", "position", "player", "name", "status", "type", "reason", "date", "count",
    "\u961f", "\u7403\u5458", "\u4f4d\u7f6e", "\u72b6\u6001", "\u539f\u56e0", "\u4eba\u6570", "\u6570\u91cf",
))


def _strict_availability_side_column(rows: list[list[str]]) -> int | None:
    if not rows:
        return None
    for index, cell in enumerate(rows[0]):
        if _strict_normalize(cell) in {"side", "team", "\u961f", "\u7403\u961f"}:
            return index
    return None


def _strict_row_side(row: list[str], side_index: int | None, target: Mapping[str, Any]) -> str | None:
    if side_index is None or side_index >= len(row):
        return None
    raw = _safe_text(row[side_index], 160)
    normalized = _strict_normalize(raw)
    if normalized in {"home", "\u4e3b", "\u4e3b\u961f"}:
        return "home"
    if normalized in {"away", "\u5ba2", "\u5ba2\u961f"}:
        return "away"
    side, _reason = _strict_bound_side(raw, target)
    return side


def _strict_availability_row_fact(row: list[str], header: bool = False) -> tuple[bool, str | None, int]:
    cells = [_safe_text(cell, 160) for cell in row if _safe_text(cell, 160)]
    if not cells or _strict_explicit_empty([row]):
        return False, None, 0
    normalized = [_strict_normalize(cell) for cell in cells]
    if header and all(cell in _STRICT_AVAILABILITY_GENERIC for cell in normalized):
        return False, None, 0
    meaningful = [cell for cell in normalized if cell not in _STRICT_AVAILABILITY_GENERIC and _strict_integer(cell) is None]
    if not meaningful:
        return False, None, 0
    count = 1
    position = _strict_availability_position(cells)
    return True, position, count


def _strict_availability_field(document: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str, Any, str, int, str | None]:
    records = _strict_table_records(document, _STRICT_AVAILABILITY_MARKERS)
    if not records:
        return "ABSENT", None, "AVAILABILITY_SECTION_NOT_FOUND", 0, None
    counts: dict[str, dict[str, int | None]] = {"home": {}, "away": {}}
    position_counts: dict[str, dict[str, dict[str, int]]] = {"home": {}, "away": {}}
    observed_kinds: set[str] = set()
    bound_sections = 0
    facts = 0
    explicit_empty_sections = 0
    for record in records:
        context = record.get("context") if isinstance(record.get("context"), Mapping) else {}
        kind = _strict_availability_kind(context.get("subbar"))
        if kind is None:
            return "PARSE_UNCERTAIN", None, "AVAILABILITY_KIND_MARKER_MISSING", 0, None
        observed_kinds.add(kind)
        table_side, side_reason = _strict_bound_side(context.get("resultbar"), target)
        rows = record.get("rows") or []
        side_index = _strict_availability_side_column(rows)
        if side_reason and side_index is None:
            return "PARSE_UNCERTAIN", None, "AVAILABILITY_SIDE_BINDING_AMBIGUOUS", 0, None
        row_facts = 0
        section_sides: set[str] = set()
        for row_index, row in enumerate(rows):
            side = table_side or _strict_row_side(row, side_index, target)
            is_fact, position, row_count = _strict_availability_row_fact(row, header=row_index == 0 and side_index is not None)
            if not is_fact:
                if _strict_explicit_empty([row]) and side:
                    counts[side][kind] = 0
                    section_sides.add(side)
                    explicit_empty_sections += 1
                continue
            if side is None:
                return "PARSE_UNCERTAIN", None, "AVAILABILITY_SIDE_BINDING_AMBIGUOUS", 0, None
            section_sides.add(side)
            counts[side][kind] = int(counts[side].get(kind) or 0) + row_count
            if position:
                buckets = position_counts[side].setdefault(kind, {})
                buckets[position] = buckets.get(position, 0) + row_count
            row_facts += row_count
        if not section_sides:
            if _strict_explicit_empty(rows) and table_side:
                counts[table_side][kind] = 0
                section_sides.add(table_side)
                explicit_empty_sections += 1
            else:
                return "PARSE_UNCERTAIN", None, "AVAILABILITY_ROWS_UNCERTAIN", 0, None
        bound_sections += len(section_sides)
        facts += row_facts
    if not facts:
        if explicit_empty_sections == len(records) and bound_sections:
            return "SECTION_PRESENT_EMPTY", None, "AVAILABILITY_EXPLICIT_EMPTY", 0, None
        return "PARSE_UNCERTAIN", None, "AVAILABILITY_NO_STRUCTURED_ROWS", 0, None
    value = {
        "counts": counts,
        "position_category_counts": position_counts,
        "observed_sections": sorted(observed_kinds),
        "source_semantics": "EXPLICIT_AVAILABILITY_SECTION",
        "side_binding": "EXPLICIT_RESULT_BAR_OR_SIDE_COLUMN",
    }
    return "PRESENT", value, "AVAILABILITY_STRUCTURED_COUNTS_PARSED", facts, "EXPLICIT_AVAILABILITY_SECTION_SIDE_BOUND"


def _strict_standings_field(document: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str, Any, str, int, str | None]:
    records = _strict_table_records(document, _STRICT_STANDINGS_MARKERS)
    if not records:
        return "ABSENT", None, "STANDINGS_SECTION_NOT_FOUND", 0, None
    competition = _safe_text(target.get("competition") or target.get("league"), 120)
    if not competition:
        return "PARSE_UNCERTAIN", None, "STANDINGS_COMPETITION_CONTEXT_MISSING", 0, None
    bound: dict[str, dict[str, Any]] = {}
    empty_sides: set[str] = set()
    for record in records:
        side, parsed, reason, empty = _strict_parse_standings_table(record, target)
        if reason:
            return "PARSE_UNCERTAIN", None, reason, 0, None
        if side is None:
            return "PARSE_UNCERTAIN", None, "STANDINGS_SIDE_BINDING_MISSING", 0, None
        if empty:
            empty_sides.add(side)
            continue
        if side in bound or side in empty_sides:
            return "PARSE_UNCERTAIN", None, "STANDINGS_DUPLICATE_SIDE_TABLE", 0, None
        if parsed is None:
            return "PARSE_UNCERTAIN", None, "STANDINGS_TABLE_UNCERTAIN", 0, None
        bound[side] = parsed
    if not bound:
        if len(empty_sides) == 2:
            return "SECTION_PRESENT_EMPTY", None, "STANDINGS_EXPLICIT_EMPTY", 0, None
        return "PARSE_UNCERTAIN", None, "STANDINGS_ROWS_MISSING", 0, None
    if set(bound) != {"home", "away"}:
        return "PARSE_UNCERTAIN", None, "STANDINGS_TARGET_SIDES_INCOMPLETE", 0, None
    value = {
        "competition": competition,
        "season": _safe_text(target.get("season"), 80) or None,
        "competition_binding": "trusted_current_fixture",
        "season_binding": "same_id_analysis_page_current_context",
        "teams": bound,
        "source_semantics": "EXPLICIT_STANDINGS_TABLE",
    }
    return "PRESENT", value, "STANDINGS_STRUCTURED_TABLES_PARSED", sum(len(item["splits"]) for item in bound.values()), "EXPLICIT_STANDINGS_TABLE_SIDE_BOUND"


def _strict_future_field(document: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str, Any, str, int, str | None]:
    records = _strict_table_records(document, _STRICT_FUTURE_MARKERS)
    if not records:
        return "ABSENT", None, "FUTURE_SECTION_NOT_FOUND", 0, None
    fixtures: list[dict[str, Any]] = []
    seen_sides: set[str] = set()
    for record in records:
        side, parsed, reason, empty = _strict_parse_future_table(record, target)
        if reason:
            return "PARSE_UNCERTAIN", None, reason, 0, None
        if side is None:
            return "PARSE_UNCERTAIN", None, "FUTURE_SIDE_BINDING_MISSING", 0, None
        if side in seen_sides:
            return "PARSE_UNCERTAIN", None, "FUTURE_DUPLICATE_SIDE_TABLE", 0, None
        seen_sides.add(side)
        if empty:
            continue
        for item in parsed:
            fixtures.append(dict(item))
    if not fixtures:
        return "SECTION_PRESENT_EMPTY", None, "FUTURE_EXPLICIT_EMPTY", 0, None
    return "PRESENT", {
        "future_fixture_count": len(fixtures),
        "fixtures": fixtures,
        "source_semantics": "EXPLICIT_FUTURE_SCHEDULE_TABLE",
    }, "FUTURE_STRUCTURED_SCHEDULE_PARSED", len(fixtures), "EXPLICIT_FUTURE_SCHEDULE_SIDE_BOUND"


def _positive_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _has_domain_fact(field: str, item: Mapping[str, Any]) -> bool:
    value = item.get("value")
    if not isinstance(value, dict):
        return False
    if field == "market_context":
        return any(_positive_count(value.get(key)) > 0 for key in ("bookmaker_count", "asian_count", "total_count"))
    if field == "recent_form":
        return bool(value.get("summary")) and _positive_count(value.get("recent_match_count")) > 0
    if field == "standings_context":
        teams = value.get("teams")
        if not isinstance(teams, dict) or set(teams) != {"home", "away"}:
            return False
        for side in ("home", "away"):
            team = teams.get(side)
            if not isinstance(team, dict) or not isinstance(team.get("splits"), dict) or not team["splits"]:
                return False
        return True
    if field == "competition_standings_stage":
        return any(_positive_count(value.get(key)) > 0 for key in ("rank_fact_count", "points_fact_count")) or bool(value.get("stage_or_round"))
    if field == "h2h":
        records = value.get("records")
        return isinstance(records, list) and any(
            isinstance(record, dict) and bool(record.get("date") or record.get("score"))
            for record in records
        )
    if field == "future_schedule_rest":
        return _positive_count(value.get("future_fixture_count")) > 0 and isinstance(value.get("fixtures"), list) and bool(value["fixtures"])
    if field in {"injuries", "suspensions"}:
        return _positive_count(value.get("structured_record_count")) > 0 and bool(value.get("status_values"))
    if field == "availability_summary":
        counts = value.get("counts")
        return isinstance(counts, dict) and any(
            _positive_count((counts.get(side) or {}).get(kind)) > 0
            for side in ("home", "away")
            for kind in ("injury", "suspension")
        )
    if field == "lineup_state":
        return item.get("semantic_state") in {"CONFIRMED", "PREDICTED"}
    if field == "technical_stats":
        stats = value.get("stats")
        return isinstance(stats, list) and bool(stats) and all(
            isinstance(stat, dict)
            and _is_technical_stat_label(str(stat.get("label") or ""))
            and len(stat.get("values") or []) >= 2
            for stat in stats
        )
    if field == "coach":
        return any(
            isinstance(value.get(side), dict)
            and (
                bool(_safe_text(value[side].get("name"), 80))
                or _positive_count(value[side].get("coach_record_count")) > 0
                or _positive_count(value[side].get("team_record_count")) > 0
            )
            for side in ("home", "away")
        )
    if field == "referee":
        return bool(_safe_text(value.get("name"), 80)) or any(
            _positive_count(value.get(key)) > 0
            for key in ("summary_count", "home_team_history_count", "away_team_history_count")
        )
    if field == "panlu":
        matches = value.get("matches")
        return _positive_count(value.get("match_count")) > 0 and isinstance(matches, list) and bool(matches)
    return False


def _enforce_present_invariant(result: dict[str, Any]) -> dict[str, Any]:
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return result
    for field, item in fields.items():
        if not isinstance(item, dict) or item.get("state") != "PRESENT" or _has_domain_fact(field, item):
            continue
        item["state"] = "PARSE_UNCERTAIN"
        item["value"] = None
        item["reason_code"] = "PRESENT_INVARIANT_NO_DOMAIN_FACT"
        item["record_count"] = 0
        item["semantic_state"] = None
    return result


def _markup_adapter(payload: SurfacePayload, target: Mapping[str, Any]) -> dict[str, Any]:
    body = payload.body or ""
    document = _document(body)
    fields: dict[str, dict[str, Any]] = {}
    builders: dict[str, Callable[[list[dict[str, Any]], str], tuple[Any, int, bool]] | None] = {
        "competition_standings_stage": _competition_builder,
        "h2h": _h2h_builder,
        "injuries": _availability_builder("injuries"),
        "suspensions": _availability_builder("suspensions"),
        "lineup_state": _lineup_builder,
        "technical_stats": _technical_builder,
    }
    expected: list[str] = []
    found: list[str] = []
    parsed_count = 0
    if payload.surface == "analysis_page":
        strict_specs = (
            ("standings_context", _strict_standings_field, _STRICT_STANDINGS_MARKERS),
            ("future_schedule_rest", _strict_future_field, _STRICT_FUTURE_MARKERS),
            ("availability_summary", _strict_availability_field, _STRICT_AVAILABILITY_MARKERS),
        )
        table_records = document.get("table_records") or []
        for field, parser, markers in strict_specs:
            expected.extend(markers)
            if any(
                isinstance(record, Mapping)
                and isinstance(record.get("context"), Mapping)
                and _strict_marker_matches(record["context"].get("fenxibar"), markers)
                for record in table_records
            ):
                found.append(markers[0])
            state, value, reason, count, semantic = parser(document, target)
            fields[field] = _field(
                state,
                value=value,
                surface=payload.surface,
                reason_code=reason,
                record_count=count,
                semantic_state=semantic,
            )
            parsed_count += count
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
    coach_fact = any(
        bool(profile.get("name"))
        or _positive_count(profile.get("coach_record_count")) > 0
        or _positive_count(profile.get("team_record_count")) > 0
        for profile in (value["home"], value["away"])
    )
    fields = {
        "coach": _field(
            "PRESENT" if coach_fact else ("PARSE_UNCERTAIN" if body else "ABSENT"),
            value=value,
            surface=payload.surface,
            reason_code="COACH_STRUCTURED_FACT_PARSED" if coach_fact else "COACH_SECTION_UNCERTAIN",
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


def _raw_adapter(surface: str, payload: SurfacePayload, target: Mapping[str, Any]) -> dict[str, Any]:
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


def _adapter(surface: str, payload: SurfacePayload, target: Mapping[str, Any]) -> dict[str, Any]:
    return _enforce_present_invariant(_raw_adapter(surface, payload, target))
