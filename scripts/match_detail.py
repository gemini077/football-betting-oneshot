#!/usr/bin/env python3
"""Render the shared static match-detail page from an analysis contract."""

from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url
except ImportError:
    from match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url

try:
    from .exact_score_serving_policy import exact_score_serving_presentation
except ImportError:
    from exact_score_serving_policy import exact_score_serving_presentation

try:
    from .exact_distribution import EXACT_DISTRIBUTION_CELL_COUNT, EXACT_DISTRIBUTION_MAX_GOALS
    from .formal_market_projection import FORMAL_MARKET_STATUS_LABELS
except ImportError:
    from exact_distribution import EXACT_DISTRIBUTION_CELL_COUNT, EXACT_DISTRIBUTION_MAX_GOALS
    from formal_market_projection import FORMAL_MARKET_STATUS_LABELS

try:
    from .closed_beta_copy import render_closed_beta_notice
except ImportError:
    from closed_beta_copy import render_closed_beta_notice


SHANGHAI = timezone(timedelta(hours=8))
DASH = "\u2014"


def _esc(value: Any, fallback: str = "") -> str:
    if value is None or value == "":
        return html.escape(fallback)
    return html.escape(str(value))


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percent(value: Any) -> str:
    number = _finite(value)
    return f"{number * 100:.1f}%" if number is not None else ""


def _percent_number(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and 0 <= number <= 1 else None


def _format_datetime(value: Any, *, include_date: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        parsed = parsed.astimezone(SHANGHAI)
        if include_date:
            return f"{parsed.month}\u6708{parsed.day}\u65e5 {parsed.hour:02d}:{parsed.minute:02d}"
        return f"{parsed.hour:02d}:{parsed.minute:02d}"
    except ValueError:
        return text.replace("T", " ")[:16]


def _display_score(value: Any) -> str:
    return _esc(value)


def _status_code(contract: dict[str, Any]) -> str:
    return str((contract.get("status") or {}).get("code") or "PENDING").strip().upper()


def _status_class(contract: dict[str, Any]) -> str:
    status = _status_code(contract).lower()
    if (contract.get("governance") or {}).get("pilot_excluded"):
        return "pilot"
    return {
        "frozen": "recorded",
        "insufficient_data": "insufficient",
        "prediction_failed": "failed",
        "missed_prematch_window": "missed",
        "current_job_state_conflict": "conflict",
    }.get(status, status)


_USER_STATUS_LABELS = {
    "CURRENT_JOB_STATE_CONFLICT": "\u672c\u573a\u72b6\u6001\u5f85\u786e\u8ba4",
    "FROZEN": "\u5df2\u5f62\u6210\u9884\u6d4b",
    "PENDING": "\u9884\u6d4b\u5c1a\u672a\u5f62\u6210",
    "INSUFFICIENT_DATA": "\u6570\u636e\u4e0d\u8db3\uff0c\u6682\u4e0d\u9884\u6d4b",
    "PREDICTION_FAILED": "\u672c\u573a\u672a\u5f62\u6210\u6709\u6548\u9884\u6d4b",
    "MISSED_PREMATCH_WINDOW": "\u672a\u5f62\u6210\u5408\u6cd5\u8d5b\u524d\u9884\u6d4b",
}


def _user_status_label(status: dict[str, Any]) -> str:
    code = str(status.get("code") or "").strip().upper()
    return _USER_STATUS_LABELS.get(code, "\u672c\u573a\u72b6\u6001\u5f85\u786e\u8ba4")


def _status_explanation(status: dict[str, Any]) -> str:
    code = str(status.get("code") or "").strip().upper()
    defaults = {
        "CURRENT_JOB_STATE_CONFLICT": "\u5f53\u524d\u6bd4\u8d5b\u72b6\u6001\u5f85\u786e\u8ba4\uff0c\u6682\u4e0d\u5f62\u6210\u9884\u6d4b\u3002",
        "PENDING": "\u9884\u6d4b\u5c1a\u672a\u5f62\u6210\uff0c\u5f53\u524d\u4e0d\u663e\u793a\u6b63\u5f0f\u6982\u7387\u3002",
        "INSUFFICIENT_DATA": "\u5f53\u524d\u6570\u636e\u4e0d\u8db3\uff0c\u6682\u4e0d\u5f62\u6210\u6b63\u5f0f\u9884\u6d4b\u3002",
        "PREDICTION_FAILED": "\u9884\u6d4b\u672a\u6210\u529f\uff0c\u5f53\u524d\u4e0d\u663e\u793a\u6b63\u5f0f\u6982\u7387\u3002",
        "MISSED_PREMATCH_WINDOW": "\u5df2\u9519\u8fc7\u8d5b\u524d\u7a97\u53e3\uff0c\u5f53\u524d\u4e0d\u8865\u5199\u9884\u6d4b\u3002",
    }
    reason = str(status.get("reason_text") or "").strip()
    if reason and not reason.isupper() and "_" not in reason:
        return reason
    return defaults.get(code, "")


def _model(contract: dict[str, Any]) -> dict[str, Any]:
    model = contract.get("model")
    if isinstance(model, dict):
        return model
    evidence_model = (contract.get("evidence") or {}).get("model")
    return evidence_model if isinstance(evidence_model, dict) else {}


def _probabilities(contract: dict[str, Any]) -> dict[str, Any]:
    hero = contract.get("hero") or {}
    model = _model(contract)
    probabilities = hero.get("probabilities") or model.get("probabilities") or {}
    return probabilities if isinstance(probabilities, dict) else {}


def _score_rows(contract: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    model = _model(contract)
    hero = contract.get("hero") or {}
    raw = (
        model.get("score_distribution")
        or model.get("top_scores")
        or hero.get("score_distribution")
        or contract.get("candidate_scores")
        or []
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(raw, dict):
        raw = [raw]
    for index, item in enumerate(raw if isinstance(raw, list) else [], 1):
        if isinstance(item, dict):
            score = str(item.get("score") or "").strip()
            probability = _percent_number(item.get("probability"))
            rank = item.get("rank") or index
        else:
            score = str(item or "").strip()
            probability = None
            rank = index
        if not score or score in seen or probability is None:
            continue
        seen.add(score)
        rows.append({"score": score, "probability": probability, "rank": rank})
    return rows[:limit]


def _render_probability_cards(contract: dict[str, Any]) -> str:
    probabilities = _probabilities(contract)
    values = [
        ("home", "\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("draw", "\u5e73", _percent_number(probabilities.get("draw"))),
        ("away", "\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    ]
    if any(value is None for _, _, value in values):
        return (
            '<section class="probability-section lane-unavailable" aria-labelledby="probability-title">'
            '<div class="section-kicker">\u7b2c\u4e00\u5c42\u5224\u65ad</div><h2 id="probability-title">\u80dc\u5e73\u8d1f\u6982\u7387</h2>'
            '<p>\u80dc\u5e73\u8d1f\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u9875\u9762\u4e0d\u8865\u5199\u7f3a\u5931\u7684\u6982\u7387\u3002</p></section>'
        )
    numeric = [value for _, _, value in values if value is not None]
    total = sum(numeric)
    if total <= 0:
        return (
            '<section class="probability-section lane-unavailable" aria-labelledby="probability-title">'
            '<div class="section-kicker">\u7b2c\u4e00\u5c42\u5224\u65ad</div><h2 id="probability-title">\u80dc\u5e73\u8d1f\u6982\u7387</h2>'
            '<p>\u80dc\u5e73\u8d1f\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u9875\u9762\u4e0d\u8865\u5199\u7f3a\u5931\u7684\u6982\u7387\u3002</p></section>'
        )
    leader = max(values, key=lambda item: item[2] or 0.0)[0]
    cards = []
    legend = []
    segments = []
    aria_values = []
    for key, label, number in values:
        assert number is not None
        highest = " probability-highest" if key == leader else ""
        cards.append(
            f'<div class="probability-card{highest}" data-probability="{number:.6f}">'
            f'<span class="probability-label">{label}</span><strong>{_percent(number)}</strong></div>'
        )
        leader_copy = '<small>\u76f8\u5bf9\u5360\u4f18</small>' if key == leader else '<small>&nbsp;</small>'
        legend.append(
            f'<div class="probability-legend-item {key}{" is-leading" if key == leader else ""}">'
            f'<span>{label}</span><strong>{_percent(number)}</strong>{leader_copy}</div>'
        )
        segments.append(
            f'<span class="probability-segment {key}" style="width:{number / total * 100:.3f}%" aria-hidden="true"></span>'
        )
        aria_values.append(f"{label} {_percent(number)}")
    aria_label = "\uFF1B".join(aria_values)
    return (
        '<section class="probability-section" aria-labelledby="probability-title">'
        '<div class="section-kicker">\u7b2c\u4e00\u5c42\u5224\u65ad</div><h2 id="probability-title">\u80dc\u5e73\u8d1f\u6982\u7387</h2>'
        '<div class="hero-probabilities">' + "".join(cards) + '</div>'
        '<div class="probability-strip-wrap">'
        f'<div class="probability-strip" role="img" aria-label="\u80dc\u5e73\u8d1f\u6982\u7387\uFF1A{aria_label}">'
        + "".join(segments)
        + '</div><div class="probability-legend">'
        + "".join(legend)
        + '</div></div></section>'
    )

def _score_serving_context(contract: dict[str, Any]) -> dict[str, str]:
    quality = contract.get("prediction_quality_health")
    if isinstance(quality, dict):
        return exact_score_serving_presentation(quality)
    return {"state": "NORMAL", "label": "", "note": ""}


def _render_score_distribution(contract: dict[str, Any]) -> str:
    rows = _score_rows(contract)
    if not rows:
        return ""
    serving = _score_serving_context(contract)
    local_warning = serving["state"] != "NORMAL"
    rendered = []
    for index, row in enumerate(rows):
        score = _display_score(row["score"])
        number = row["probability"]
        primary = " score-primary" if index == 0 and not local_warning else ""
        label = "\u6700\u9ad8\u6982\u7387" if index == 0 else "\u66ff\u4ee3\u6bd4\u5206"
        width = number * 100
        rendered.append(
            f'<div class="score-row{primary}" data-probability="{number:.6f}" '
            f'data-score-serving-state="{html.escape(serving["state"], quote=True)}">'
            f'<div class="score-name"><strong>{score}</strong><span>{label}</span></div>'
            f'<div class="score-bar" aria-hidden="true"><span style="width:{width:.1f}%"></span></div>'
            f'<strong class="score-probability">{_percent(number)}</strong>'
            "</div>"
        )
    section_title = (
        f'\u6a21\u578b\u539f\u59cb\u6bd4\u5206 \u00b7 {serving.get("local_label") or serving["label"]}'
        if local_warning
        else "\u6bd4\u5206\u6982\u7387 \u00b7 \u4e0d\u662f\u786e\u5b9a\u7b54\u6848"
    )
    section_note = (
        serving["note"]
        if local_warning
        else "\u6bcf\u4e00\u884c\u90fd\u662f\u8d5b\u524d\u6982\u7387\uff0c\u4e0d\u4ee3\u8868\u786e\u5b9a\u8d5b\u679c\u3002"
    )
    return (
        '<section class="detail-section score-section" id="score-distribution">'
        '<div class="section-heading"><div><div class="section-kicker">\u7ed3\u679c\u5206\u5e03</div>'
        f'<h2>{section_title}</h2></div><p>\u6bcf\u4e00\u884c\u4e3a\u7edd\u5bf9\u6bd4\u5206\u6982\u7387</p></div>'
        '<div class="score-list">' + "".join(rendered) + "</div>"
        f'<p class="section-note">{section_note}</p></section>'
    )


def _total_goal_distribution(contract: dict[str, Any]) -> list[tuple[str, float]]:
    totals = _model(contract).get("totals")
    if not isinstance(totals, list):
        return []
    buckets: dict[str, float] = {}
    for item in totals:
        if not isinstance(item, dict):
            continue
        number = _percent_number(item.get("probability"))
        if number is None:
            continue
        raw_goals = str(item.get("goals") or item.get("total") or "").strip()
        if raw_goals.endswith("+"):
            try:
                bucket = "4+" if int(raw_goals[:-1]) >= 4 else raw_goals
            except ValueError:
                continue
        elif raw_goals.isdigit():
            bucket = raw_goals if int(raw_goals) <= 3 else "4+"
        else:
            continue
        buckets[bucket] = buckets.get(bucket, 0.0) + number
    order = ["0", "1", "2", "3", "4+"]
    return [(bucket, buckets[bucket]) for bucket in order if bucket in buckets]


def _render_goals(contract: dict[str, Any]) -> str:
    rows = _total_goal_distribution(contract)
    if not rows:
        return (
            '<section class="detail-section goals-section lane-unavailable" id="goals">'
            '<div class="section-heading"><div><div class="section-kicker">\u8fdb\u7403\u5206\u5e03</div>'
            '<h2>\u603b\u8fdb\u7403\u5206\u5e03</h2></div><p>\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684\u8fdb\u7403\u5206\u5e03</p></div>'
            '<p>\u603b\u8fdb\u7403\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u9875\u9762\u4e0d\u8865\u5199\u7f3a\u5931\u7684\u5206\u5e03\u3002</p></section>'
        )
    top = max(rows, key=lambda item: item[1])
    rendered = []
    for bucket, number in rows:
        rendered.append(
            f'<div class="goal-row" data-goals="{html.escape(bucket, quote=True)}">'
            f'<span>{html.escape(bucket)}</span>'
            f'<div class="goal-bar" aria-hidden="true"><span style="width:{number * 100:.1f}%"></span></div>'
            f'<strong>{_percent(number)}</strong></div>'
        )
    return (
        '<section class="detail-section goals-section" id="goals">'
        '<div class="section-heading"><div><div class="section-kicker">\u8fdb\u7403\u5206\u5e03</div>'
        '<h2>\u603b\u8fdb\u7403\u5206\u5e03</h2></div><p>\u5f53\u524d\u6a21\u578b\u6982\u7387</p></div>'
        f'<div class="goal-grid">{"".join(rendered)}</div>'
        f'<p class="section-note">\u5206\u5e03\u6700\u9ad8\u6bb5\uff1a{html.escape(top[0])} \u00b7 {_percent(top[1])}\u3002\u4e0d\u4ee3\u8868\u786e\u5b9a\u8d5b\u679c\u3002</p>'
        '</section>'
    )


def _formal_markets(contract: dict[str, Any]) -> dict[str, Any]:
    value = contract.get("formal_markets")
    return value if isinstance(value, dict) else {}


def _formal_market_item(formal: dict[str, Any], key: str) -> dict[str, Any]:
    markets = formal.get("markets")
    item = markets.get(key) if isinstance(markets, dict) else None
    return item if isinstance(item, dict) else {"status": "NOT_RECORDED"}


def _formal_status(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "NOT_RECORDED").upper()
    return status if status in FORMAL_MARKET_STATUS_LABELS else "UNAVAILABLE"


def _exact_compact_projection(
    contract: dict[str, Any],
    *,
    limit: int = 6,
) -> tuple[list[dict[str, Any]], float, int]:
    """Project the frozen finite cells without replaying or renormalizing them."""

    def exact_cell_sort_key(cell: dict[str, Any]) -> tuple[float, int, int]:
        return (
            -float(cell.get("probability") or 0.0),
            int(cell.get("home_goals")),
            int(cell.get("away_goals")),
        )

    cells = [cell for cell in contract.get("cells", []) if isinstance(cell, dict)]
    ranked = sorted(cells, key=exact_cell_sort_key)
    selected = ranked[:limit]
    remainder = math.fsum(float(cell.get("probability") or 0.0) for cell in ranked[limit:])
    return selected, remainder, max(0, len(ranked) - len(selected))


def _render_exact_compact_projection(contract: dict[str, Any]) -> str:
    selected, remainder, remainder_count = _exact_compact_projection(contract)
    rows = []
    for rank, cell in enumerate(selected, start=1):
        home = int(cell.get("home_goals"))
        away = int(cell.get("away_goals"))
        probability = _percent_number(cell.get("probability")) or 0.0
        score = f"{home}-{away}"
        rows.append(
            f'<div class="exact-compact-row" data-exact-compact-score="{score}" '
            f'data-exact-compact-rank="{rank}" data-exact-compact-probability="{probability:.12f}">'
            f'<span class="exact-compact-score"><b>#{rank}</b>{html.escape(score)}</span>'
            f'<span class="exact-compact-bar" aria-hidden="true"><span style="width:{probability * 100:.2f}%"></span></span>'
            f'<strong class="exact-compact-probability">{_percent(probability)}</strong></div>'
        )
    return (
        '<div class="exact-compact" data-exact-compact="true" '
        f'data-exact-compact-source-cell-count="{len(selected) + remainder_count}" '
        f'data-exact-compact-top-count="{len(selected)}" '
        f'data-exact-compact-remainder-count="{remainder_count}" '
        f'data-exact-compact-remainder-probability="{remainder:.12f}" '
        'aria-label="\u79fb\u52a8\u7aef\u6bd4\u5206\u6982\u7387\u6458\u8981">'
        '<div class="exact-compact-heading"><h3>\u6bd4\u5206\u6982\u7387</h3><span>\u524d 6 \u4e2a\u5df2\u8868\u793a\u6bd4\u5206</span></div>'
        '<div class="exact-compact-list">'
        + "".join(rows)
        + '</div>'
        f'<div class="exact-compact-remainder"><span>\u5176\u4f59\u5df2\u8868\u793a\u6bd4\u5206\u5408\u8ba1</span>'
        f'<strong>{_percent(remainder)}</strong></div>'
        '<p class="exact-compact-note">\u4ec5\u5408\u8ba1 0\u201312 \u00d7 0\u201312 \u5185\u5176\u4f59\u5df2\u8868\u793a\u6bd4\u5206\uff1b\u8303\u56f4\u5916\u4e0d\u63a8\u7b97\u3002</p>'
        '</div>'
    )

def _render_exact_formal_market(item: dict[str, Any], *, serving_state: str = "NORMAL") -> str:
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else None
    status = _formal_status(item)
    if status != "AVAILABLE" or contract is None:
        return (
            '<section class="detail-section exact-section lane-unavailable" id="score-distribution" '
            f'data-exact-state="UNAVAILABLE" data-exact-status="{html.escape(status, quote=True)}">'
            '<div class="section-heading"><div><div class="section-kicker">\u6bd4\u5206\u5206\u5e03</div>'
            '<h2>\u6bd4\u5206\u6982\u7387</h2></div><p>\u5f53\u524d\u6ca1\u6709\u53ef\u6838\u9a8c\u7684\u5b8c\u6574\u6bd4\u5206\u6982\u7387</p></div>'
            '<p>\u6bd4\u5206\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u672a\u8bb0\u5f55\u7684\u5206\u5e03\u4e0d\u8865\u5199\u3002</p></section>'
        )
    cells = contract.get("cells") if isinstance(contract.get("cells"), list) else []
    by_score = {
        (cell.get("home_goals"), cell.get("away_goals")): cell
        for cell in cells
        if isinstance(cell, dict)
    }
    max_goals = EXACT_DISTRIBUTION_MAX_GOALS
    max_probability = max(
        (_percent_number(cell.get("probability")) or 0.0 for cell in cells if isinstance(cell, dict)),
        default=0.0,
    )
    headers = "".join(f'<th scope="col">{goal}</th>' for goal in range(max_goals + 1))
    rows = []
    for home in range(max_goals + 1):
        cells_html = []
        for away in range(max_goals + 1):
            cell = by_score.get((home, away))
            probability = _percent_number(cell.get("probability")) if cell else None
            probability_attr = f' data-probability="{probability:.6f}"' if probability is not None else ""
            alpha = probability / max_probability if probability is not None and max_probability else 0.0
            style = f' style="--cell-alpha:{alpha:.3f}"' if probability is not None else ""
            cell_text = _percent(probability) if probability is not None else "\u2014"
            cells_html.append(
                f'<td data-exact-cell-home="{home}" data-exact-cell-away="{away}"{probability_attr}{style}>'
                f'{cell_text}</td>'
            )
        rows.append(f'<tr><th scope="row">{home}</th>{"".join(cells_html)}</tr>')
    selected, _, _ = _exact_compact_projection(contract)
    primary = selected[0] if selected else None
    primary_summary = (
        f'{int(primary["home_goals"])}-{int(primary["away_goals"])} \u00b7 {_percent(primary.get("probability"))}'
        if primary
        else "\u2014"
    )
    section_title = "\u6bd4\u5206\u6982\u7387\u5206\u5e03" if serving_state == "NORMAL" else "\u6bd4\u5206\u6982\u7387\u5206\u5e03\uff08\u4ec5\u4f9b\u89c2\u5bdf\uff09"
    quality_note = "" if serving_state == "NORMAL" else '<span>\u5f53\u524d\u4ec5\u4f9b\u89c2\u5bdf</span>'
    return (
        f'<section class="detail-section exact-section" id="score-distribution" data-exact-state="{html.escape(serving_state, quote=True)}" data-exact-status="AVAILABLE">'
        '<div class="section-heading"><div><div class="section-kicker">\u6bd4\u5206\u5206\u5e03</div>'
        f'<h2>{section_title}</h2></div><p>\u6bcf\u4e00\u683c\u4e3a\u5bf9\u5e94\u6bd4\u5206\u7684\u7edd\u5bf9\u6982\u7387</p></div>'
        f'<div class="exact-summary"><strong>\u6700\u9ad8\u6982\u7387\u6bd4\u5206\uff1a{html.escape(primary_summary)}</strong>{quality_note}</div>'
        + _render_exact_compact_projection(contract)
        + '<details open class="exact-full-disclosure" data-exact-disclosure>'
        '<summary>\u67e5\u770b\u5b8c\u6574 169 \u683c\u77e9\u9635</summary>'
        '<p class="exact-disclosure-cue">\u4e3b\u961f\u8fdb\u7403\u4e3a H\uff0c\u5ba2\u961f\u8fdb\u7403\u4e3a A\uff1b\u79fb\u52a8\u7aef\u5c55\u5f00\u540e\u5728\u77e9\u9635\u533a\u57df\u5185\u6a2a\u5411\u67e5\u770b\u3002</p>'
        '<div class="exact-grid-wrap" role="region" tabindex="0" aria-label="\u6bd4\u5206\u6982\u7387 169 \u683c\u77e9\u9635\uff1b\u4e3b\u961f\u8fdb\u7403 H\uff0c\u5ba2\u961f\u8fdb\u7403 A">'
        '<table class="exact-grid"><caption class="sr-only">\u6bd4\u5206\u6982\u7387 169 \u683c\uff1a\u4e3b\u961f\u8fdb\u7403 H \u00d7 \u5ba2\u961f\u8fdb\u7403 A</caption><thead><tr><th scope="col">H\\A</th>'
        + headers
        + '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div></details>'
        '<p class="exact-grid-caption">\u4ec5\u5c55\u793a\u5f53\u524d\u8bb0\u5f55\u4e2d\u7684 0\u201312 \u00d7 0\u201312 \u663e\u5f0f\u683c\uff1b\u5176\u4f59\u5df2\u8868\u793a\u6bd4\u5206\u5408\u8ba1\u89c1\u4e0a\u65b9\uff0c\u8303\u56f4\u5916\u4e0d\u63a8\u7b97\u3002</p>'
        '<script>(() => { const disclosures = document.querySelectorAll("[data-exact-disclosure]"); const isMobile = window.matchMedia("(max-width: 560px)").matches; disclosures.forEach((disclosure) => { if (isMobile) disclosure.open = false; }); })();</script>'
        '</section>'
    )

def _format_change_delta(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return "\u2014"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f} \u4e2a\u767e\u5206\u70b9"


def _format_change_gap(seconds: Any) -> str:
    number = _finite(seconds)
    if number is None or number < 0:
        return ""
    minutes = int(round(number / 60))
    if minutes < 60:
        return f"\u7ea6 {minutes} \u5206\u949f"
    hours, remainder = divmod(minutes, 60)
    if hours < 24:
        return f"\u7ea6 {hours} \u5c0f\u65f6" if remainder == 0 else f"\u7ea6 {hours} \u5c0f\u65f6 {remainder} \u5206\u949f"
    days, remainder = divmod(hours, 24)
    return f"\u7ea6 {days} \u5929" if remainder == 0 else f"\u7ea6 {days} \u5929 {remainder} \u5c0f\u65f6"


def _render_change_rows(items: Any, *, include_ranks: bool = False) -> str:
    if not isinstance(items, list):
        return '<p class="change-empty">\u5f53\u524d\u6ca1\u6709\u53ef\u6bd4\u53d8\u5316\u3002</p>'
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        before = _percent_number(item.get("before"))
        now = _percent_number(item.get("now"))
        label = _esc(item.get("label") or item.get("key"), DASH)
        rank = ""
        if include_ranks:
            rank = (
                f'<span class="change-rank">#{_esc(item.get("before_rank"), DASH)} \u2192 '
                f'#{_esc(item.get("now_rank"), DASH)}</span>'
            )
        rows.append(
            f'<div class="change-row" data-change-key="{html.escape(str(item.get("key") or ""), quote=True)}">'
            f'<span class="change-label">{label}{rank}</span>'
            f'<span class="change-before-now"><span>{_esc(_percent(before), DASH)}</span>'
            f'<b aria-hidden="true">\u2192</b><strong>{_esc(_percent(now), DASH)}</strong></span>'
            f'<span class="change-delta">{_esc(_format_change_delta(item.get("delta_probability_points")))}</span>'
            '</div>'
        )
    return "".join(rows) if rows else '<p class="change-empty">\u5f53\u524d\u6ca1\u6709\u660e\u663e\u53d8\u5316\u3002</p>'


def _render_change_lane(name: str, lane: dict[str, Any]) -> str:
    labels = {"ft_1x2": "\u80dc\u5e73\u8d1f\u6982\u7387", "exact_score": "\u6bd4\u5206\u6982\u7387"}
    title = labels.get(name, "\u5f53\u524d\u6982\u7387")
    status = str(lane.get("status") or "UNAVAILABLE").upper()
    if status == "UNAVAILABLE":
        return (
            f'<article class="change-lane change-lane-unavailable" data-change-lane="{html.escape(name, quote=True)}" '
            f'data-change-lane-status="{status}"><h3>{title}</h3>'
            '<p>\u5f53\u524d\u6ca1\u6709\u53ef\u6bd4\u7684\u8d5b\u524d\u8bb0\u5f55\uff0c\u6682\u4e0d\u5c55\u793a\u53d8\u5316\u3002</p></article>'
        )
    if name == "exact_score":
        support = lane.get("support") if isinstance(lane.get("support"), dict) else {}
        support_text = (
            f'\u57fa\u4e8e {html.escape(str(support.get("cell_count") or DASH))} \u4e2a\u6bd4\u5206\u683c\uff1b'
            '\u4ec5\u5c55\u793a\u6709\u8bb0\u5f55\u7684\u53d8\u5316\u3002'
        )
        rows = _render_change_rows(lane.get("items"), include_ranks=True)
        if not lane.get("items"):
            rows = '<p class="change-empty">\u5f53\u524d\u6ca1\u6709\u660e\u663e\u53d8\u5316\u3002</p>'
        return (
            f'<article class="change-lane change-lane-wide" data-change-lane="{name}" '
            f'data-change-lane-status="{status}"><h3>{title}</h3>'
            f'<div class="change-rows">{rows}</div><p class="change-lane-note">{support_text}</p></article>'
        )
    rows = _render_change_rows(lane.get("items"))
    return (
        f'<article class="change-lane" data-change-lane="{name}" '
        f'data-change-lane-status="{status}"><h3>{title}</h3>'
        f'<div class="change-rows">{rows}</div></article>'
    )


def _render_change_awareness(contract: dict[str, Any]) -> str:
    change = contract.get("change_awareness")
    if not isinstance(change, dict):
        return ""
    status = str(change.get("status") or "UNAVAILABLE").upper()
    current = change.get("current_snapshot") if isinstance(change.get("current_snapshot"), dict) else {}
    previous = change.get("previous_snapshot") if isinstance(change.get("previous_snapshot"), dict) else {}
    if status != "AVAILABLE" or not previous:
        return (
            '<section class="detail-section change-awareness-section change-awareness-unavailable" '
            'id="change-awareness" data-change-awareness="true" '
            f'data-change-awareness-status="{html.escape(status, quote=True)}">'
            '<div class="section-heading"><div><div class="section-kicker">\u8d5b\u524d\u53d8\u5316</div>'
            '<h2>\u6682\u65e0\u53ef\u6bd4\u7684\u8d5b\u524d\u8bb0\u5f55</h2></div><p>\u5f53\u524d\u9884\u6d4b\u4fdd\u6301\u4e0d\u53d8</p></div>'
            '<p class="change-unavailable-copy">\u5f53\u524d\u6ca1\u6709\u5408\u6cd5\u7684\u66f4\u65e9\u8d5b\u524d\u5feb\u7167\uff0c\u6682\u4e0d\u8865\u5199\u53d8\u5316\u3002</p></section>'
        )
    previous_time = _format_datetime(
        previous.get("chronology_timestamp")
        or previous.get("source_cutoff_at")
        or previous.get("freeze_created_at"),
        include_date=True,
    )
    current_time = _format_datetime(
        current.get("chronology_timestamp")
        or current.get("source_cutoff_at")
        or current.get("freeze_created_at"),
        include_date=True,
    )
    gap = _format_change_gap(change.get("elapsed_seconds"))
    timeline = " \u00b7 ".join(value for value in (f"\u6b64\u524d {previous_time}" if previous_time else "", f"\u5f53\u524d {current_time}" if current_time else "", gap) if value)
    empty_timeline = "\u53ea\u663e\u793a\u771f\u5b9e\u53d8\u5316"
    markets = change.get("markets") if isinstance(change.get("markets"), dict) else {}
    lanes = "".join(
        _render_change_lane(name, markets.get(name) if isinstance(markets.get(name), dict) else {})
        for name in ("ft_1x2", "exact_score")
    )
    return (
        '<section class="detail-section change-awareness-section" id="change-awareness" '
        'data-change-awareness="true" data-change-awareness-status="AVAILABLE" '
        f'data-change-awareness-current-id="{html.escape(str(current.get("prediction_id") or ""), quote=True)}" '
        f'data-change-awareness-previous-id="{html.escape(str(previous.get("prediction_id") or ""), quote=True)}">'
        '<div class="section-heading"><div><div class="section-kicker">\u8d5b\u524d\u53d8\u5316</div>'
        '<h2>\u770b\u6e05\u4e00\u6b21\u53d8\u5316</h2></div>'
        f'<p>{html.escape(timeline or empty_timeline)}</p></div>'
        f'<div class="change-lane-grid">{lanes}</div>'
        '<p class="section-note">\u53ea\u5c55\u793a\u5f53\u524d\u8bb0\u5f55\u95f4\u7684\u53ef\u6bd4\u53d8\u5316\uff1b\u4e0d\u5bf9\u53d8\u5316\u4f5c\u56e0\u679c\u63a8\u65ad\u3002</p></section>'
    )


def _render_form(evidence: dict[str, Any]) -> str:
    fundamentals = evidence.get("fundamentals") if isinstance(evidence.get("fundamentals"), dict) else {}
    form = fundamentals.get("recent_form") if isinstance(fundamentals.get("recent_form"), dict) else {}
    rows = []
    labels = {
        "home_overall": "\u4e3b\u961f\u8fd1\u51b5",
        "home_home": "\u4e3b\u961f\u4e3b\u573a",
        "away_overall": "\u5ba2\u961f\u8fd1\u51b5",
        "away_away": "\u5ba2\u961f\u5ba2\u573a",
    }
    fields = (("matches", "\u573a"), ("wins", "\u80dc"), ("draws", "\u5e73"), ("losses", "\u8d1f"), ("goals_for", "\u8fdb\u7403"), ("goals_against", "\u5931\u7403"))
    for key, label in labels.items():
        values = form.get(key)
        if not isinstance(values, dict):
            continue
        facts = []
        for field, field_label in fields:
            value = values.get(field)
            if value is not None:
                facts.append(f"{field_label}{_esc(value)}")
        if facts:
            separator = " \u00b7 "
            rows.append(f'<div class="evidence-fact"><span>{label}</span><strong>{separator.join(facts)}</strong></div>')
    if not rows:
        return ""
    captured = _format_datetime(fundamentals.get("captured_at"), include_date=True)
    captured_html = f'<p class="source-line">\u91c7\u96c6\u4e8e {captured}</p>' if captured else ""
    return '<article class="evidence-block"><h3>\u8fd1\u671f\u8868\u73b0</h3>' + "".join(rows) + captured_html + "</article>"


def _support_lines(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("conclusion") or item.get("label")
        if text:
            lines.append(f"<li>{_esc(text)}</li>")
    return '<ul class="support-list">' + "".join(lines) + "</ul>" if lines else ""


def _render_key_takeaways(contract: dict[str, Any], *, exact_state: str = "NORMAL") -> str:
    probabilities = _probabilities(contract)
    takeaways: list[str] = []
    outcomes = [
        ("\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("\u5e73", _percent_number(probabilities.get("draw"))),
        ("\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    ]
    outcomes = [(label, value) for label, value in outcomes if value is not None]
    if outcomes:
        label, number = max(outcomes, key=lambda item: item[1])
        takeaways.append(f"{label}\u76f8\u5bf9\u5360\u4f18 \u00b7 {_percent(number)}")
    goals = _total_goal_distribution(contract)
    if goals:
        bucket, number = max(goals, key=lambda item: item[1])
        takeaways.append(f"\u603b\u8fdb\u7403\u5206\u5e03\u6700\u9ad8\u6bb5\uff1a{bucket} \u00b7 {_percent(number)}")
    exact_item = _formal_market_item(_formal_markets(contract), "exact_score")
    exact_contract = exact_item.get("contract") if _formal_status(exact_item) == "AVAILABLE" else None
    if isinstance(exact_contract, dict):
        selected, _, _ = _exact_compact_projection(exact_contract)
        if selected:
            primary = selected[0]
            exact_copy = f"\u6700\u9ad8\u6982\u7387\u6bd4\u5206\uff1a{int(primary['home_goals'])}-{int(primary['away_goals'])} \u00b7 {_percent(primary.get('probability'))}"
            if exact_state != "NORMAL":
                exact_copy += " \u00b7 \u4ec5\u4f9b\u89c2\u5bdf"
            takeaways.append(exact_copy)
    if not takeaways:
        return ""
    items = "".join(f'<div class="takeaway">{html.escape(value)}</div>' for value in takeaways[:3])
    return (
        '<section class="detail-section decision-context" id="decision-context">'
        '<div class="section-heading"><div><div class="section-kicker">\u51b3\u7b56\u8bed\u5883</div>'
        '<h2>\u8bfb\u61c2\u8fd9\u573a\u6bd4\u8d5b</h2></div>'
        '<p>\u53ea\u7ffb\u8bd1\u5f53\u524d\u8bb0\u5f55\u91cc\u5df2\u5b58\u5728\u7684\u6982\u7387</p></div>'
        f'<div class="takeaways">{items}</div></section>'
    )

def _render_key_evidence(contract: dict[str, Any]) -> str:
    evidence = contract.get("evidence") or {}
    blocks = []
    form_html = _render_form(evidence)
    if form_html:
        blocks.append(form_html)

    hero = contract.get("hero") or {}
    support_html = _support_lines(hero.get("supports"))
    conflict_html = _support_lines(hero.get("conflicts"))
    if support_html or conflict_html:
        parts = ['<article class="evidence-block"><h3>\u5173\u952e\u4f9d\u636e</h3>']
        if support_html:
            parts.append('<div class="evidence-subheading">\u652f\u6301</div>' + support_html)
        if conflict_html:
            parts.append('<div class="evidence-subheading">\u5206\u6b67</div>' + conflict_html)
        parts.append("</article>")
        blocks.append("".join(parts))

    for section in contract.get("analysis_sections") or []:
        if not isinstance(section, dict):
            continue
        supports = _support_lines(section.get("supports"))
        conflicts = _support_lines(section.get("conflicts"))
        conclusion = str(section.get("conclusion") or "").strip()
        explanation = str(section.get("explanation") or "").strip()
        if not (supports or conflicts or conclusion):
            continue
        if "\u6ca1\u6709\u53ef\u8ffd\u6eaf\u7684\u6b63\u5f0f\u5206\u6790\u7ed3\u8bba" in conclusion or "\u539f\u59cb\u57fa\u672c\u9762" in explanation:
            continue
        text = conclusion or explanation
        if not text:
            continue
        section_title = _esc(section.get("title"), "\u5173\u952e\u4f9d\u636e")
        parts = [f'<article class="evidence-block"><h3>{section_title}</h3><p>{_esc(text)}</p>']
        if supports:
            parts.append('<div class="evidence-subheading">\u652f\u6301</div>' + supports)
        if conflicts:
            parts.append('<div class="evidence-subheading">\u5206\u6b67</div>' + conflicts)
        parts.append("</article>")
        blocks.append("".join(parts))

    if not blocks:
        return ""
    return (
        '<section class="detail-section evidence-section" id="evidence">'
        '<div class="section-heading"><div><div class="section-kicker">UNDERSTAND MATCH</div><h2>\u5173\u952e\u4f9d\u636e</h2></div>'
        '<p>\u53ea\u5c55\u793a\u5f53\u524d\u8bb0\u5f55\u4e2d\u771f\u5b9e\u5b58\u5728\u7684\u89e3\u91ca</p></div><div class="evidence-grid">'
        + "".join(blocks)
        + "</div></section>"
    )

def _market_comparison(contract: dict[str, Any]) -> dict[str, Any] | None:
    market = contract.get("market")
    if not isinstance(market, dict):
        evidence_market = (contract.get("evidence") or {}).get("market")
        market = evidence_market if isinstance(evidence_market, dict) else {}
    comparison = market.get("model_comparison") if isinstance(market, dict) else None
    if not isinstance(comparison, dict):
        return None
    labels = {"home": "\u4e3b\u80dc", "draw": "\u5e73", "away": "\u5ba2\u80dc"}
    model_probabilities = comparison.get("model_probabilities")
    market_probabilities = comparison.get("market_probabilities")
    if not isinstance(model_probabilities, dict):
        model_probabilities = {}
    if not isinstance(market_probabilities, dict):
        market_probabilities = {}
    rows = []
    for key in ("home", "draw", "away"):
        model_value = _percent_number(
            model_probabilities.get(key)
            or comparison.get(f"model_{key}_probability")
            or comparison.get(f"model_{key}")
        )
        market_value = _percent_number(
            market_probabilities.get(key)
            or comparison.get(f"market_{key}_probability")
            or comparison.get(f"market_{key}")
        )
        if model_value is None or market_value is None:
            continue
        rows.append({"key": key, "label": labels[key], "model": model_value, "market": market_value})
    return {"rows": rows, "devigged": bool(comparison.get("market_is_devigged") or comparison.get("is_devigged"))} if rows else None


def _render_market_comparison(contract: dict[str, Any]) -> str:
    comparison = _market_comparison(contract)
    if comparison is None:
        return ""
    market_label = "\u5e02\u573a\uff08\u53bb\u6c34\uff09" if comparison.get("devigged") else "\u5e02\u573a"
    cells = []
    deltas = []
    for row in comparison["rows"]:
        difference = row["model"] - row["market"]
        sign = "+" if difference >= 0 else ""
        cells.append(
            f'<div><span>{row["label"]} \u00b7 \u6a21\u578b</span><strong>{_percent(row["model"])}</strong></div>'
            f'<div><span>{row["label"]} \u00b7 {market_label}</span><strong>{_percent(row["market"])}</strong></div>'
        )
        deltas.append(f'{row["label"]} {sign}{difference * 100:.1f} \u4e2a\u767e\u5206\u70b9')
    delta_text = "\uFF1B".join(deltas)
    return (
        '<section class="detail-section market-section" id="market">'
        '<div class="section-heading"><div><div class="section-kicker">\u771f\u5b9e\u5bf9\u7167</div><h2>\u5e02\u573a\u5bf9\u7167</h2></div>'
        '<p>\u4ec5\u5728\u540c\u65f6\u5b58\u5728\u4e24\u4fa7\u6982\u7387\u65f6\u663e\u793a</p></div><div class="market-compare">'
        + "".join(cells)
        + f'<p>\u6a21\u578b\u76f8\u5bf9\u5e02\u573a\u7684\u5dee\u5f02\uff1a{delta_text}\u3002\u5dee\u5f02\u672c\u8eab\u4e0d\u8868\u793a\u597d\u574f\u3002</p>'
        + '</div></section>'
    )

def _source_items(contract: dict[str, Any]) -> list[str]:
    source_quality = contract.get("source_quality") or (contract.get("evidence") or {}).get("source_quality") or {}
    refs = list(source_quality.get("source_references") or [])
    refs.extend((_model(contract).get("source_references") or []) if isinstance(_model(contract), dict) else [])
    market = contract.get("market") or (contract.get("evidence") or {}).get("market") or {}
    if isinstance(market, dict):
        refs.extend(market.get("source_refs") or [])
    result = []
    seen: set[str] = set()
    for ref in refs:
        if isinstance(ref, dict):
            value = ref.get("path") or ref.get("url") or ref.get("source")
        else:
            value = ref
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(Path(text).name or text)
    return result


def _render_technical_details(contract: dict[str, Any]) -> str:
    model = _model(contract)
    governance = contract.get("governance") or {}
    status = contract.get("status") or {}
    source_quality = contract.get("source_quality") or (contract.get("evidence") or {}).get("source_quality") or {}
    timestamps = contract.get("timestamps") or {}
    pairs = [
        ("model_family", model.get("model_family") or governance.get("model_family")),
        ("release_version", model.get("release_version") or governance.get("release_version")),
        ("provider", source_quality.get("provider")),
        ("data_grade", source_quality.get("data_grade") or governance.get("data_grade") or model.get("data_grade")),
        ("base_input_quality", source_quality.get("base_input_quality") or governance.get("base_input_quality") or model.get("base_input_quality")),
        ("prediction_id", governance.get("prediction_id") or governance.get("prediction_record_ref")),
        ("job_id", contract.get("job_id") or governance.get("job_id")),
        ("selected_prediction_id", contract.get("selected_prediction_id") or governance.get("selected_prediction_id")),
        ("prediction_frozen_at", timestamps.get("prediction_frozen_at")),
        ("source_cutoff_at", timestamps.get("source_cutoff_at")),
        ("input_snapshot_ref", source_quality.get("input_snapshot_ref") or governance.get("input_snapshot_ref")),
        ("status_code", status.get("code")),
    ]
    rows = []
    for key, value in pairs:
        if value is None or value == "":
            continue
        rows.append(f'<div class="technical-row"><span>{_esc(key)}</span><code>{_esc(value)}</code></div>')
    if not rows:
        return ""
    return '<details class="technical-details"><summary>\u6280\u672f\u8be6\u60c5</summary><div class="technical-list">' + "".join(rows) + "</div></details>"


def _render_trust(contract: dict[str, Any]) -> str:
    timestamps = contract.get("timestamps") or {}
    status = _status_code(contract)
    rows = []
    recorded_at = timestamps.get("prediction_frozen_at") or timestamps.get("freeze_created_at")
    if recorded_at:
        rows.append(
            f'<div class="trust-lock"><strong>\u8d5b\u524d\u8bb0\u5f55\uff1a{_esc(_format_datetime(recorded_at, include_date=True))}</strong>'
            '<span>\u8d5b\u540e\u4e0d\u4fee\u6539</span></div>'
        )
    elif status == "FROZEN":
        rows.append('<div class="trust-lock"><strong>\u8d5b\u524d\u8bb0\u5f55\u5df2\u4fdd\u5b58</strong><span>\u8d5b\u540e\u4e0d\u4fee\u6539</span></div>')
    references = _source_items(contract)
    if references:
        list_html = "".join(f"<li>{_esc(item)}</li>" for item in references[:5])
        rows.append(f'<div class="trust-source"><span>\u53c2\u8003\u6765\u6e90</span><ul>{list_html}</ul></div>')
    technical = _render_technical_details(contract)
    if technical:
        rows.append(technical)
    if not rows:
        return ""
    title = "\u53ef\u4fe1\u5ea6\u4e0e\u6765\u6e90" if references else "\u8d5b\u524d\u8bb0\u5f55"
    kicker = "\u8bb0\u5f55\u4e0e\u65b9\u6cd5" if references else "\u8bb0\u5f55\u8bf4\u660e"
    return f'<section class="trust-panel" id="sources"><div class="section-kicker">{kicker}</div><h2>{title}</h2>' + "".join(rows) + "</section>"

def _result_score(result: dict[str, Any]) -> tuple[int, int] | None:
    text = str(result.get("score_90m") or "").strip()
    try:
        home, away = text.split("-", 1)
        return int(home), int(away)
    except (ValueError, TypeError):
        return None


def _outcome(score: tuple[int, int]) -> str:
    return "\u4e3b\u80dc" if score[0] > score[1] else "\u5ba2\u80dc" if score[0] < score[1] else "\u5e73"


def _completed_comparison(contract: dict[str, Any]) -> dict[str, Any]:
    result = contract.get("result") or {}
    score = _result_score(result) if isinstance(result, dict) else None
    exact_item = _formal_market_item(_formal_markets(contract), "exact_score")
    exact_contract = exact_item.get("contract") if _formal_status(exact_item) == "AVAILABLE" else None
    primary = ""
    if isinstance(exact_contract, dict):
        selected, _, _ = _exact_compact_projection(exact_contract)
        if selected:
            primary = f'{int(selected[0]["home_goals"])}-{int(selected[0]["away_goals"])}'
    if not primary:
        primary = str((contract.get("hero") or {}).get("primary_score") or _model(contract).get("unique_score") or "").strip()
    probabilities = _probabilities(contract)
    choices = (
        ("\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("\u5e73", _percent_number(probabilities.get("draw"))),
        ("\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    )
    predicted = max(choices, key=lambda item: item[1] if item[1] is not None else -1)[0] if any(value is not None for _, value in choices) else ""
    actual_score = f"{score[0]}-{score[1]}" if score else ""
    actual_outcome = _outcome(score) if score else ""
    exact_status = "\u547d\u4e2d" if primary and actual_score and primary == actual_score else "\u672a\u547d\u4e2d" if primary and actual_score else "\u5f85\u786e\u8ba4"
    direction_status = "\u547d\u4e2d" if predicted and actual_outcome and predicted == actual_outcome else "\u672a\u547d\u4e2d" if predicted and actual_outcome else "\u5f85\u786e\u8ba4"
    return {
        "actual_score": actual_score,
        "primary_score": primary,
        "exact_status": exact_status,
        "predicted_direction": predicted,
        "actual_direction": actual_outcome,
        "direction_status": direction_status,
    }

def _render_completed_result(contract: dict[str, Any]) -> str:
    result = contract.get("result") or {}
    if not isinstance(result, dict) or not result.get("score_90m"):
        return ""
    verified = _format_datetime(result.get("verified_at"), include_date=True)
    verified_html = f"<span>\u6838\u9a8c\u4e8e {verified}</span>" if verified else ""
    comparison = _completed_comparison(contract)
    value = lambda key: _esc(comparison.get(key) or DASH)
    facts = (
        '<div class="completed-facts">'
        f'<div><span>\u5b9e\u9645\u6bd4\u5206</span><strong>{value("actual_score")}</strong></div>'
        f'<div><span>\u8d5b\u524d\u6700\u9ad8\u6982\u7387\u6bd4\u5206</span><strong>{value("primary_score")}</strong></div>'
        f'<div><span>\u6bd4\u5206</span><strong>{value("exact_status")}</strong></div>'
        f'<div><span>\u8d5b\u524d 1X2 \u65b9\u5411</span><strong>{value("predicted_direction")}</strong></div>'
        f'<div><span>\u5b9e\u9645\u65b9\u5411</span><strong>{value("actual_direction")}</strong></div>'
        f'<div><span>\u65b9\u5411</span><strong>{value("direction_status")}</strong></div>'
        '</div>'
    )
    return (
        '<section class="result-panel" id="result"><div class="section-kicker">\u8d5b\u540e\u9a8c\u8bc1</div><h2>\u5b9e\u9645\u8d5b\u679c</h2>'
        f'<div class="actual-score">{_display_score(result.get("score_90m"))}</div>'
        f'<div class="actual-meta"><strong>90\u5206\u949f\u8d5b\u679c</strong>{verified_html}</div>'
        + facts
        + "</section>"
    )

def _render_verification(contract: dict[str, Any]) -> str:
    result = contract.get("result") or {}
    score = _result_score(result) if isinstance(result, dict) else None
    if score is None:
        return ""
    comparison = _completed_comparison(contract)
    placeholder = "\u2014"
    rows = [
        f'<div class="verification-row"><span>\u6bd4\u5206</span><strong>{_esc(comparison["exact_status"])}</strong><em>\u8d5b\u524d\u6700\u9ad8\u6982\u7387 {_display_score(comparison["primary_score"]) if comparison["primary_score"] else placeholder}</em></div>',
        f'<div class="verification-row"><span>1X2\u65b9\u5411</span><strong>{_esc(comparison["direction_status"])}</strong><em>\u8d5b\u524d\u5224\u65ad {_esc(comparison["predicted_direction"] or placeholder)} \u00b7 \u5b9e\u9645 {_esc(comparison["actual_direction"] or placeholder)}</em></div>',
    ]
    return (
        '<section class="detail-section verification-section" id="verification">'
        '<div class="section-heading"><div><div class="section-kicker">\u56de\u770b</div><h2>\u9884\u6d4b vs \u5b9e\u9645</h2></div>'
        '<p>\u53ea\u6bd4\u8f83\u9501\u5b9a\u7684\u8d5b\u524d\u8bb0\u5f55</p></div><div class="verification-list">'
        + "".join(rows)
        + "</div></section>"
    )


def _render_status_panel(contract: dict[str, Any]) -> str:
    status = contract.get("status") or {}
    label = _user_status_label(status)
    explanation = _status_explanation(status)
    return (
        '<section class="status-panel"><div class="status-mark">!</div><div><div class="section-kicker">\u5f53\u524d\u6bd4\u8d5b</div>'
        f"<h2>{_esc(label)}</h2><p>{_esc(explanation)}</p></div></section>"
    )


DETAIL_CSS = """
    :root {
      --shell-bg:#07111A; --workspace-bg:#F7F7F5; --surface:#FFFFFF; --surface-subtle:#FAFAF8;
      --ink:#121417; --muted:#626870; --quiet:#8B9198; --line:#E6E7E4;
      --accent:#FF6A00; --accent-soft:#FFF1E8;
      --home:#1F5EA8; --draw:#A9ADB2; --away:#E23B3B;
      --matrix-low:#F3F7F2; --matrix-high:#4A9A62;
      --warning:#B75C00; --warning-soft:#FFF4E8; --danger:#B42318; --danger-soft:#FFF1F0; --verified:#18794E;
      --max:1240px;
    }
    * { box-sizing:border-box; }
    html { background:var(--shell-bg); scroll-behavior:smooth; }
    body { min-width:0; margin:0; background:var(--workspace-bg); color:var(--ink); font:14px/1.5 Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; -webkit-font-smoothing:antialiased; }
    a { color:inherit; }
    button { font:inherit; }
    a:focus-visible,button:focus-visible,summary:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
    [hidden] { display:none !important; }
    .app-shell { display:grid; grid-template-columns:184px minmax(0,1fr); min-height:100vh; }
    .side-rail { display:flex; flex-direction:column; min-height:100vh; padding:30px 18px 22px; background:var(--shell-bg); color:#F5F7F8; }
    .rail-brand { display:block; text-decoration:none; }
    .rail-mark { display:block; font-size:25px; font-weight:750; letter-spacing:-.06em; }
    .rail-caption { display:block; margin-top:3px; color:#A9B3BB; font-size:10px; line-height:1.4; letter-spacing:.12em; text-transform:uppercase; }
    .rail-nav { display:grid; gap:5px; margin-top:54px; }
    .nav-item { display:flex; align-items:baseline; justify-content:space-between; gap:8px; min-height:44px; padding:11px 10px; border-left:2px solid transparent; color:#A9B3BB; font-size:13px; text-decoration:none; }
    .nav-item small { color:#65727C; font-size:9px; letter-spacing:.06em; text-transform:uppercase; }
    .nav-item:hover,.nav-item.active { border-left-color:var(--accent); background:rgba(255,255,255,.06); color:#FFF; }
    .nav-item.active small { color:#F6A26D; }
    .rail-footer { margin-top:auto; padding:14px 10px 0; border-top:1px solid rgba(255,255,255,.12); color:#7F8B94; font-size:10px; }
    .rail-footer strong { display:block; color:#D7DDE1; font-size:11px; font-weight:650; }
    .rail-footer span { display:block; margin-top:4px; }
    .workspace { min-width:0; background:var(--workspace-bg); }
    .mobile-topbar { display:none; }
    .page { width:min(calc(100% - 48px),var(--max)); margin:0 auto; padding:28px 0 42px; }
    .site-header { display:flex; align-items:center; justify-content:space-between; gap:20px; padding-bottom:17px; border-bottom:1px solid var(--line); }
    .brand { display:flex; align-items:baseline; gap:12px; min-width:0; color:var(--ink); text-decoration:none; }
    .brand-name { flex:0 0 auto; font-size:18px; font-weight:750; letter-spacing:-.05em; }
    .brand-subtitle { color:var(--muted); font-size:10px; letter-spacing:.1em; text-transform:uppercase; }
    .header-actions { display:flex; align-items:center; gap:14px; color:var(--muted); font-size:11px; }
    .back { text-decoration:none; }
    .back:hover { color:var(--accent); }
    .eyebrow,.section-kicker { color:var(--quiet); font-size:10px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
    .detail-nav { display:flex; flex-wrap:wrap; gap:5px 15px; margin:15px 0 0; padding-bottom:2px; color:var(--muted); font-size:11px; }
    .detail-nav a { padding:6px 0; text-decoration:none; }
    .detail-nav a:hover { color:var(--accent); }
    .detail-layout { display:block; }
    .detail-main { min-width:0; }
    .match-identity { padding:28px 0 23px; border-bottom:1px solid var(--line); }
    .match-meta { color:var(--muted); font-size:12px; }
    .match-identity h1 { max-width:100%; margin:11px 0 0; font-size:28px; line-height:1.18; letter-spacing:-.045em; overflow-wrap:anywhere; }
    .match-identity h1 span { color:var(--muted); font-weight:450; }
    .quality-warning,.pilot-note { margin-top:15px; padding:11px 14px; border-left:3px solid var(--warning); background:var(--warning-soft); color:var(--warning); font-size:12px; }
    .quality-warning strong { color:var(--ink); }
    .quality-warning span { margin-left:8px; color:var(--muted); }
    .pilot-note { border-left-color:var(--line); background:transparent; color:var(--muted); }
    .detail-section,.result-panel,.status-panel { margin-top:24px; padding:20px; border:1px solid var(--line); border-radius:12px; background:var(--surface); }
    .section-heading { display:flex; align-items:baseline; justify-content:space-between; gap:18px; margin-bottom:16px; }
    .section-heading h2 { margin:4px 0 0; font-size:17px; line-height:1.2; letter-spacing:-.025em; }
    .section-heading p { max-width:45%; margin:0; color:var(--muted); font-size:11px; text-align:right; }
    .forecast-section { padding:0; border:0; background:transparent; }
    .probability-section { margin-top:24px; padding:20px; border:1px solid var(--line); border-radius:12px; background:var(--surface); }
    .probability-section h2 { margin:4px 0 16px; font-size:17px; letter-spacing:-.025em; }
    .hero-probabilities { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; border:1px solid var(--line); background:var(--line); }
    .probability-card { min-width:0; padding:15px; background:var(--surface); }
    .probability-card.probability-highest { background:var(--surface-subtle); }
    .probability-label { display:block; color:var(--muted); font-size:12px; }
    .probability-card strong { display:block; margin-top:4px; font-size:24px; line-height:1; font-variant-numeric:tabular-nums; }
    .probability-card.probability-highest strong { font-weight:800; }
    .probability-track { display:none; }
    .probability-strip-wrap { margin-top:17px; }
    .probability-strip { display:flex; width:100%; height:9px; overflow:hidden; border-radius:99px; background:var(--line); }
    .probability-segment { display:block; min-width:2px; height:100%; }
    .probability-segment.home { background:var(--home); }
    .probability-segment.draw { background:var(--draw); }
    .probability-segment.away { background:var(--away); }
    .probability-legend { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:11px; }
    .probability-legend-item { display:flex; align-items:baseline; gap:7px; min-width:0; font-size:12px; }
    .probability-legend-item::before { content:""; flex:0 0 8px; width:8px; height:8px; border-radius:50%; background:var(--draw); }
    .probability-legend-item.home::before { background:var(--home); }
    .probability-legend-item.away::before { background:var(--away); }
    .probability-legend-item strong { font-size:14px; font-variant-numeric:tabular-nums; }
    .probability-legend-item.is-leading strong { font-weight:800; }
    .probability-legend-item small { color:var(--muted); font-size:10px; }
    .lane-unavailable { border-style:dashed; background:var(--surface-subtle); }
    .lane-unavailable p { margin:7px 0 0; color:var(--muted); font-size:12px; }
    .exact-section { margin-top:24px; }
    .exact-summary { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin:-4px 0 14px; }
    .exact-summary strong { font-size:15px; font-variant-numeric:tabular-nums; }
    .exact-summary span { color:var(--muted); font-size:11px; }
    .exact-compact { display:none; }
    .exact-full-disclosure { margin-top:4px; }
    .exact-full-disclosure > summary { padding:4px 0 9px; cursor:pointer; font-size:12px; font-weight:700; }
    .exact-disclosure-cue { margin:0 0 9px; color:var(--muted); font-size:11px; }
    .exact-grid-wrap { max-width:100%; overflow-x:auto; overscroll-behavior-inline:contain; }
    .exact-grid { width:100%; min-width:720px; border-collapse:collapse; table-layout:fixed; font-size:10px; font-variant-numeric:tabular-nums; }
    .exact-grid th,.exact-grid td { width:7.14%; padding:6px 3px; border:1px solid var(--line); text-align:center; white-space:nowrap; }
    .exact-grid th { background:var(--surface-subtle); color:var(--muted); font-weight:650; }
    .exact-grid td { --cell-alpha:0; background:var(--matrix-low); color:var(--ink); }
    @supports (background:color-mix(in srgb, white, black)) { .exact-grid td[data-probability] { background:color-mix(in srgb,var(--matrix-high) calc(12% + var(--cell-alpha) * 78%),var(--matrix-low)); } }
    .exact-grid-caption { margin:9px 0 0; color:var(--muted); font-size:11px; }
    .exact-full-disclosure:not([open]) > :not(summary) { display:none; }
    .score-list { display:grid; gap:2px; }
    .score-row { display:grid; grid-template-columns:90px minmax(0,1fr) 60px; gap:12px; align-items:center; min-height:33px; border-top:1px solid var(--line); font-size:12px; }
    .score-row:first-child { border-top:0; }
    .score-name { display:flex; align-items:baseline; gap:7px; }
    .score-name strong { font-size:15px; font-variant-numeric:tabular-nums; }
    .score-name span { color:var(--muted); font-size:10px; }
    .score-bar { height:6px; overflow:hidden; background:var(--line); }
    .score-bar > span { display:block; height:100%; background:var(--accent); }
    .score-probability { text-align:right; font-size:12px; font-variant-numeric:tabular-nums; }
    .section-note { margin:12px 0 0; color:var(--muted); font-size:11px; }
    .goals-section { margin-top:24px; }
    .goal-grid { display:grid; gap:3px; }
    .goal-row { display:grid; grid-template-columns:44px minmax(0,1fr) 58px; gap:10px; align-items:center; min-height:29px; border-top:1px solid var(--line); font-size:12px; font-variant-numeric:tabular-nums; }
    .goal-row:first-child { border-top:0; }
    .goal-row > span { color:var(--muted); }
    .goal-row > strong { text-align:right; }
    .goal-bar { height:6px; overflow:hidden; background:var(--line); }
    .goal-bar > span { display:block; height:100%; background:var(--accent); }
    .decision-context { margin-top:24px; }
    .takeaways { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
    .takeaway { min-width:0; padding:13px 14px; border-left:3px solid var(--accent); background:var(--accent-soft); font-size:13px; font-weight:650; overflow-wrap:anywhere; }
    .change-awareness-section { margin-top:24px; }
    .change-lane-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    .change-lane { min-width:0; padding:13px; border:1px solid var(--line); background:var(--surface-subtle); }
    .change-lane-wide { grid-column:1/-1; }
    .change-lane h3 { margin:0 0 9px; font-size:13px; }
    .change-rows { display:grid; }
    .change-row { display:grid; grid-template-columns:82px minmax(100px,1fr) 92px; gap:9px; align-items:center; min-height:28px; border-top:1px solid var(--line); font-size:11px; font-variant-numeric:tabular-nums; }
    .change-row:first-child { border-top:0; }
    .change-label { min-width:0; overflow-wrap:anywhere; }
    .change-before-now { display:flex; align-items:baseline; gap:7px; }
    .change-before-now > span { color:var(--muted); }
    .change-delta { color:var(--muted); text-align:right; }
    .change-lane-note,.change-empty,.change-unavailable-copy { margin:9px 0 0; color:var(--muted); font-size:11px; }
    .change-rank { display:block; color:var(--muted); font-size:10px; }
    .deeper-details { margin-top:24px; }
    .evidence-section { margin-top:0; }
    .evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    .evidence-block { min-width:0; padding:15px; border:1px solid var(--line); background:var(--surface); }
    .evidence-block h3 { margin:0 0 10px; font-size:14px; }
    .evidence-block p { margin:0; }
    .evidence-fact { display:flex; justify-content:space-between; gap:10px; padding:8px 0; border-top:1px solid var(--line); font-size:12px; }
    .evidence-fact:first-of-type { border-top:0; }
    .evidence-fact span { color:var(--muted); }
    .evidence-fact strong { text-align:right; font-weight:650; }
    .evidence-subheading { margin-top:10px; color:var(--muted); font-size:11px; }
    .support-list { margin:4px 0 0; padding-left:17px; }
    .support-list li { margin:4px 0; }
    .market-section { margin-top:8px; }
    .market-compare { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    .market-compare > div { padding:14px; border:1px solid var(--line); background:var(--surface-subtle); }
    .market-compare span { display:block; color:var(--muted); font-size:11px; }
    .market-compare strong { display:block; margin-top:4px; font-size:22px; font-variant-numeric:tabular-nums; }
    .market-compare p { grid-column:1/-1; margin:0; color:var(--muted); font-size:11px; }
    .trust-panel { margin-top:24px; padding:18px 20px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:transparent; }
    .trust-panel h2 { margin:5px 0 14px; font-size:18px; letter-spacing:-.03em; }
    .trust-lock { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px; padding:10px 0 12px; border-top:2px solid var(--accent); border-bottom:1px solid var(--line); }
    .trust-lock strong { font-size:13px; }
    .trust-lock span { color:var(--muted); font-size:12px; }
    .trust-source { padding:11px 0; border-bottom:1px solid var(--line); font-size:12px; }
    .trust-source > span { color:var(--muted); }
    .trust-source ul { display:flex; flex-wrap:wrap; gap:5px 18px; margin:6px 0 0; padding-left:17px; color:var(--muted); overflow-wrap:anywhere; }
    .technical-details { margin-top:12px; }
    .technical-details summary { padding:10px 0; cursor:pointer; color:var(--ink); font-size:12px; }
    .technical-list { border-top:1px solid var(--line); }
    .technical-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.3fr); gap:10px; padding:7px 0; border-bottom:1px solid var(--line); font-size:11px; }
    .technical-row span { color:var(--muted); }
    .technical-row code { overflow-wrap:anywhere; text-align:right; font:inherit; }
    .result-panel { margin-top:24px; }
    .actual-score { margin-top:7px; font-size:40px; font-weight:800; line-height:1; letter-spacing:-.06em; font-variant-numeric:tabular-nums; }
    .actual-meta { display:flex; flex-wrap:wrap; gap:7px 12px; align-items:baseline; margin-top:9px; color:var(--muted); font-size:11px; }
    .actual-meta strong { color:var(--verified); font-weight:700; }
    .completed-facts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; margin-top:18px; border:1px solid var(--line); background:var(--line); }
    .completed-facts > div { min-width:0; padding:11px; background:var(--surface); }
    .completed-facts span,.completed-facts strong { display:block; }
    .completed-facts span { color:var(--muted); font-size:11px; }
    .completed-facts strong { margin-top:3px; font-size:13px; overflow-wrap:anywhere; }
    .verification-section { margin-top:8px; }
    .verification-list { display:grid; }
    .verification-row { display:grid; grid-template-columns:82px minmax(70px,auto) minmax(0,1fr); gap:10px; align-items:baseline; padding:9px 0; border-top:1px solid var(--line); font-size:12px; }
    .verification-row > span,.verification-row > em { color:var(--muted); }
    .verification-row > em { font-style:normal; text-align:right; }
    .status-panel { display:flex; gap:14px; align-items:flex-start; background:var(--surface); }
    .status-mark { display:grid; place-items:center; flex:0 0 28px; width:28px; height:28px; border-radius:50%; background:var(--warning-soft); color:var(--warning); font-weight:800; }
    .status-panel h2 { margin:4px 0 6px; font-size:17px; }
    .status-panel p { margin:0; color:var(--muted); font-size:12px; }
    .closed-beta { margin-top:30px; padding-top:13px; border-top:1px solid var(--line); color:var(--muted); font-size:11px; }
    .closed-beta strong,.closed-beta span { display:block; margin-top:4px; }
    .detail-footer { display:flex; justify-content:space-between; gap:12px; padding-top:18px; color:var(--muted); font-size:11px; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media (max-width:980px) {
      .app-shell { grid-template-columns:156px minmax(0,1fr); }
      .side-rail { padding-left:14px; padding-right:14px; }
    }
    @media (max-width:820px) {
      .app-shell { display:block; }
      .side-rail { display:none; }
      .mobile-topbar { display:flex; align-items:center; justify-content:space-between; min-height:56px; padding:0 16px; background:var(--shell-bg); color:#F5F7F8; }
      .mobile-topbar a { font-weight:750; letter-spacing:-.05em; text-decoration:none; }
      .mobile-topbar span { color:#B7C0C7; font-size:12px; }
      .page { width:calc(100% - 32px); padding-top:18px; }
      .site-header { align-items:baseline; padding-bottom:14px; }
      .detail-nav { gap:3px 13px; margin-top:11px; }
      .match-identity { padding-top:22px; }
      .match-identity h1 { font-size:23px; }
    }
    @media (max-width:560px) {
      .page { width:calc(100% - 20px); padding-top:11px; }
      .brand-subtitle,.eyebrow { display:none; }
      .header-actions { gap:9px; }
      .header-actions .eyebrow { display:none; }
      .detail-nav { display:flex; max-width:100%; overflow:hidden; }
      .detail-nav a { min-height:36px; padding:9px 0; }
      .match-identity { padding-bottom:18px; }
      .match-identity h1 { font-size:20px; line-height:1.22; }
      .quality-warning { display:block; }
      .quality-warning span { display:block; margin:5px 0 0; }
      .detail-section,.result-panel,.status-panel,.probability-section { margin-top:18px; padding:15px; border-radius:10px; }
      .section-heading { display:block; margin-bottom:12px; }
      .section-heading p { max-width:none; margin-top:5px; text-align:left; }
      .hero-probabilities { grid-template-columns:repeat(3,minmax(0,1fr)); }
      .probability-card { padding:11px 9px; }
      .probability-card strong { font-size:19px; }
      .probability-label { font-size:11px; }
      .probability-legend { gap:6px; }
      .probability-legend-item { gap:5px; font-size:11px; }
      .probability-legend-item strong { font-size:13px; }
      .probability-legend-item small { display:block; font-size:10px; }
      .takeaways { grid-template-columns:1fr; gap:5px; }
      .change-lane-grid,.evidence-grid,.market-compare { grid-template-columns:1fr; }
      .change-lane-wide { grid-column:auto; }
      .change-row { grid-template-columns:64px minmax(90px,1fr) 78px; gap:6px; }
      .change-before-now { gap:5px; }
      .change-delta { font-size:10px; }
      .exact-compact { display:block; }
      .exact-compact-heading { display:flex; align-items:baseline; justify-content:space-between; gap:8px; margin-bottom:8px; }
      .exact-compact-heading h3 { margin:0; font-size:13px; }
      .exact-compact-heading span { color:var(--muted); font-size:11px; }
      .exact-compact-list { display:grid; gap:2px; }
      .exact-compact-row { display:grid; grid-template-columns:64px minmax(0,1fr) 58px; gap:8px; align-items:center; min-height:29px; border-top:1px solid var(--line); }
      .exact-compact-row:first-child { border-top:0; }
      .exact-compact-score { font-size:13px; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .exact-compact-score b { margin-right:5px; color:var(--muted); font-size:11px; font-weight:650; }
      .exact-compact-bar { height:6px; overflow:hidden; background:var(--line); }
      .exact-compact-bar > span { display:block; height:100%; background:var(--accent); }
      .exact-compact-probability { text-align:right; font-size:13px; font-variant-numeric:tabular-nums; }
      .exact-compact-remainder { display:flex; align-items:baseline; justify-content:space-between; gap:8px; margin-top:7px; padding-top:7px; border-top:1px solid var(--line); font-size:12px; }
      .exact-compact-remainder strong { font-size:13px; font-variant-numeric:tabular-nums; }
      .exact-compact-note { margin:7px 0 0; color:var(--muted); font-size:11px; }
      .exact-full-disclosure { margin-top:10px; border-top:1px solid var(--line); }
      .exact-full-disclosure > summary { min-height:36px; padding:10px 0 7px; }
      .exact-grid-wrap { overflow-x:auto; }
      .exact-grid { min-width:720px; font-size:10px; }
      .exact-grid th,.exact-grid td { padding:6px 3px; }
      .goal-grid { gap:2px; }
      .goal-row { grid-template-columns:39px minmax(0,1fr) 54px; gap:8px; }
      .completed-facts { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .completed-facts > div { padding:9px; }
      .verification-row { grid-template-columns:68px minmax(65px,auto) minmax(0,1fr); gap:7px; }
      .verification-row > em { text-align:right; }
      .actual-score { font-size:35px; }
      .trust-panel { margin-top:18px; padding:15px 0; }
      .trust-source ul { display:block; }
      .trust-source li { margin-top:4px; }
      .detail-footer { display:block; }
      .detail-footer span { display:block; margin-top:5px; }
    }
    @media (max-width:360px) {
      .mobile-topbar { padding-left:12px; padding-right:12px; }
      .page { width:calc(100% - 16px); }
      .site-header { gap:8px; }
      .match-identity h1 { font-size:18px; }
      .match-meta { font-size:11px; overflow-wrap:anywhere; }
      .probability-card { padding-left:6px; padding-right:6px; }
      .probability-card strong { font-size:17px; }
      .probability-legend-item { gap:3px; font-size:10px; }
      .probability-legend-item::before { flex-basis:6px; width:6px; height:6px; }
      .probability-legend-item strong { font-size:12px; }
      .exact-compact-row { grid-template-columns:56px minmax(0,1fr) 54px; gap:6px; }
      .exact-compact-probability { font-size:12px; }
      .change-row { grid-template-columns:54px minmax(80px,1fr) 72px; gap:5px; }
      .verification-row { grid-template-columns:59px minmax(57px,auto) minmax(0,1fr); gap:5px; font-size:11px; }
    }
"""



def render_match_detail(contract: dict[str, Any]) -> str:
    identity = contract.get("identity") or {}
    status = contract.get("status") or {}
    status_code = _status_code(contract)
    serving = status_code in {"FROZEN", "COMPLETED"}
    result = contract.get("result") if isinstance(contract.get("result"), dict) else {}
    serving_context = _score_serving_context(contract)
    quality_warning = ""
    if serving and serving_context["state"] != "NORMAL":
        warning_label = "\u6bd4\u5206\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf" if serving_context["state"] == "DEGRADED" else "\u6bd4\u5206\u6982\u7387\u8d28\u91cf\u5f85\u786e\u8ba4"
        warning_note = "\u4fdd\u7559\u539f\u59cb\u6bd4\u5206\u6982\u7387\uff0c\u6682\u4e0d\u5c55\u5f00\u89e3\u8bfb\u3002"
        quality_warning = (
            f'<div class="quality-warning" role="status"><strong>{warning_label}</strong>'
            f'<span>{warning_note}</span></div>'
        )
    pilot_note = (
        '<div class="pilot-note">\u5f53\u524d\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf</div>'
        if serving and (contract.get("governance") or {}).get("pilot_excluded")
        else ""
    )
    kickoff = _format_datetime(identity.get("kickoff_at"), include_date=True)
    home = _esc(identity.get("home"), "\u4e3b\u961f")
    away = _esc(identity.get("away"), "\u5ba2\u961f")
    meta = " \u00b7 ".join(
        value for value in (_esc(identity.get("competition")), _esc(identity.get("match_num")), _esc(kickoff)) if value
    )
    title = f"{home} vs {away} \u00b7 \u6bd4\u8d5b\u8be6\u60c5"
    result_html = _render_completed_result(contract) if result.get("score_90m") else ""
    verification_html = _render_verification(contract) if result.get("score_90m") else ""
    probability_html = _render_probability_cards(contract) if serving else ""
    exact_html = (
        _render_exact_formal_market(
            _formal_market_item(_formal_markets(contract), "exact_score"),
            serving_state=serving_context["state"],
        )
        if serving
        else ""
    )
    goals_html = _render_goals(contract) if serving else ""
    takeaways_html = _render_key_takeaways(contract, exact_state=serving_context["state"]) if serving else ""
    change_awareness_html = _render_change_awareness(contract) if serving else ""
    evidence_html = _render_key_evidence(contract) if serving else ""
    market_html = _render_market_comparison(contract) if serving else ""
    if serving:
        forecast_html = (
            '<div class="forecast-section" id="analysis">'
            + probability_html
            + exact_html
            + goals_html
            + '</div>'
        )
        decision_parts = [part for part in (takeaways_html, change_awareness_html, market_html) if part]
        decision_html = "".join(decision_parts)
        deeper_html = f'<div class="deeper-details">{evidence_html}</div>' if evidence_html else ""
    else:
        forecast_html = _render_status_panel(contract)
        decision_html = ""
        deeper_html = ""
    trust_html = _render_trust(contract) if serving else ""
    nav_items = []
    if serving:
        nav_items.append('<a href="#analysis">\u6982\u7387\u6838\u5fc3</a>')
        if takeaways_html:
            nav_items.append('<a href="#decision-context">\u51b3\u7b56\u8bed\u5883</a>')
        if verification_html:
            nav_items.append('<a href="#verification">\u6838\u9a8c</a>')
        if change_awareness_html:
            nav_items.append('<a href="#change-awareness">\u8d5b\u524d\u53d8\u5316</a>')
        if exact_html:
            nav_items.append('<a href="#score-distribution">\u6bd4\u5206</a>')
        if goals_html:
            nav_items.append('<a href="#goals">\u603b\u8fdb\u7403</a>')
        if evidence_html:
            nav_items.append('<a href="#evidence">\u5173\u952e\u4f9d\u636e</a>')
        if market_html:
            nav_items.append('<a href="#market">\u5e02\u573a\u5bf9\u7167</a>')
        if trust_html:
            nav_items.append('<a href="#sources">\u8bb0\u5f55\u4e0e\u6765\u6e90</a>')
    nav_html = f'<nav class="detail-nav" aria-label="\u9875\u9762\u5185\u5bfc">{"".join(nav_items)}</nav>' if nav_items else ""
    closed_beta = render_closed_beta_notice("closed-beta")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{DETAIL_CSS}</style>
</head>
<body class="detail-page status-{_esc(_status_class(contract))}">
<div class="app-shell">
<aside class="side-rail">
  <a class="rail-brand" href="../../prediction_dashboard/latest.html"><span class="rail-mark">FBOS</span><span class="rail-caption">Football Prediction<br>Intelligence</span></a>
  <nav class="rail-nav" aria-label="\u4e3b\u5bfc\u822a">
    <a class="nav-item active" href="../../prediction_dashboard/latest.html"><span>\u4eca\u65e5\u6bd4\u8d5b</span><small>Matches</small></a>
    <a class="nav-item" href="../../prediction_dashboard/latest.html#historical-results"><span>\u5386\u53f2\u9a8c\u8bc1</span><small>History</small></a>
  </nav>
  <div class="rail-footer"><strong>\u8d5b\u524d\u5206\u6790</strong><span>\u53ea\u5c55\u793a\u80fd\u6539\u53d8\u5f53\u524d\u5224\u65ad\u7684\u5185\u5bb9\u3002</span></div>
</aside>
<main class="workspace">
<div class="mobile-topbar"><a href="../../prediction_dashboard/latest.html">FBOS</a><span>\u6bd4\u8d5b\u8be6\u60c5</span></div>
<div class="page">
<header class="site-header">
  <a class="brand" href="../../prediction_dashboard/latest.html"><span class="brand-name">FBOS</span><span class="brand-subtitle">Football Prediction Intelligence</span></a>
  <div class="header-actions"><a class="back" href="../../prediction_dashboard/latest.html">\u2190 \u4eca\u65e5\u6bd4\u8d5b</a><span class="eyebrow">\u6bd4\u8d5b\u8be6\u60c5</span></div>
</header>
{nav_html}
<div class="detail-layout">
  <div class="detail-main">
    <section class="match-identity" id="conclusion">
      <div class="match-meta"><span>{meta}</span></div>
      <h1>{home} <span>vs</span> {away}</h1>
      {quality_warning}
      {pilot_note}
    </section>
    {result_html}
    {verification_html}
    {forecast_html}
    {decision_html}
    {deeper_html}
    {trust_html}
  </div>
</div>
{closed_beta}
<footer class="detail-footer"><span>\u8d5b\u524d\u8bb0\u5f55\u4fdd\u6301\u4e0d\u53d8\uff1b\u8d5b\u540e\u7ed3\u679c\u5355\u72ec\u6838\u9a8c\u3002</span><span>\u9875\u9762\u6570\u636e\u6765\u81ea\u5f53\u524d\u53ef\u7528\u7684\u6bd4\u8d5b\u8bb0\u5f55\u3002</span></footer>
</div>
</main>
</div>
</body>
</html>"""



def write_match_detail_page(contract: dict[str, Any], output_root: Path) -> Path:
    match_id = str((contract.get("identity") or {}).get("match_id") or "")
    if not match_id:
        raise ValueError("contract has no match_id")
    target = Path(output_root) / match_id / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_match_detail(contract), encoding="utf-8")
    return target


def build_static_match_pages(
    *,
    business_dates: Iterable[str] | None = None,
    site_matches_root: Path,
    contract_root: Path = MATCH_ANALYSIS_ROOT,
    **roots: Any,
) -> list[Path]:
    contracts = build_match_contracts(business_dates=business_dates, output_root=contract_root, **roots)
    pages = [write_match_detail_page(contract, site_matches_root) for contract in contracts]
    return pages


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="business date to build")
    parser.add_argument("--output", type=Path, default=Path("site") / "matches")
    parser.add_argument("--contract-root", type=Path, default=MATCH_ANALYSIS_ROOT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else Path(__file__).resolve().parents[1] / args.output
    contract_root = args.contract_root if args.contract_root.is_absolute() else Path(__file__).resolve().parents[1] / args.contract_root
    pages = build_static_match_pages(
        business_dates=[args.date] if args.date else None,
        site_matches_root=output,
        contract_root=contract_root,
    )
    print(json.dumps({"pages_written": len(pages), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
