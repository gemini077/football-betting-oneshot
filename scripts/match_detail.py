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
    from .formal_market_projection import FORMAL_MARKET_STATUS_LABELS, verify_formal_markets
except ImportError:
    from exact_distribution import EXACT_DISTRIBUTION_CELL_COUNT, EXACT_DISTRIBUTION_MAX_GOALS
    from formal_market_projection import FORMAL_MARKET_STATUS_LABELS, verify_formal_markets

try:
    from .closed_beta_copy import render_closed_beta_notice
except ImportError:
    from closed_beta_copy import render_closed_beta_notice


SHANGHAI = timezone(timedelta(hours=8))


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
        ("\u4e3b\u80dc", probabilities.get("home")),
        ("\u5e73", probabilities.get("draw")),
        ("\u5ba2\u80dc", probabilities.get("away")),
    ]
    numeric = [(_percent_number(value) or 0.0) for _, value in values]
    maximum = max(numeric) if any(numeric) else None
    cards = []
    for (label, value), number in zip(values, numeric):
        if value is None or maximum is None:
            continue
        highest = " probability-highest" if number == maximum else ""
        cards.append(
            f'<div class="probability-card{highest}" data-probability="{number:.6f}">'
            f'<span class="probability-label">{label}</span>'
            f"<strong>{_percent(number)}</strong>"
            f'<div class="probability-track" aria-hidden="true"><span style="width:{number * 100:.1f}%"></span></div>'
            "</div>"
        )
    if not cards:
        return ""
    return (
        '<section class="probability-section" aria-labelledby="probability-title">'
        '<div class="section-kicker">\u7b2c\u4e00\u5c42\u5224\u65ad</div><h2 id="probability-title">\u80dc\u5e73\u8d1f\u6982\u7387</h2>'
        '<div class="hero-probabilities">' + "".join(cards) + "</div></section>"
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


def _goal_values(model: dict[str, Any]) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    btts = model.get("btts") if isinstance(model.get("btts"), dict) else {}
    btts_yes = _percent_number(btts.get("yes"))
    btts_no = _percent_number(btts.get("no"))
    btts_values = (btts_yes, btts_no) if btts_yes is not None and btts_no is not None else None

    totals = model.get("totals")
    under = over = None
    if isinstance(totals, dict):
        under = _percent_number(totals.get("under_2_5") or totals.get("under"))
        over = _percent_number(totals.get("over_2_5") or totals.get("over"))
    elif isinstance(totals, list):
        under = sum(
            _percent_number(item.get("probability")) or 0.0
            for item in totals
            if isinstance(item, dict) and str(item.get("goals") or "").strip() in {"0", "1", "2"}
        )
        if under or any(isinstance(item, dict) and item.get("probability") is not None for item in totals):
            over = max(0.0, 1.0 - under)
    totals_values = (under, over) if under is not None and over is not None else None
    return btts_values, totals_values


def _render_goals(contract: dict[str, Any]) -> str:
    btts, totals = _goal_values(_model(contract))
    cards = []
    if btts:
        cards.append(
            '<article class="goal-card"><span class="goal-card-label">\u53cc\u65b9\u8fdb\u7403</span>'
            f"<strong>\u662f {_percent(btts[0])} / \u5426 {_percent(btts[1])}</strong></article>"
        )
    if totals:
        cards.append(
            '<article class="goal-card"><span class="goal-card-label">\u5927\u5c0f2.5（O/U）</span>'
            f"<strong>\u5c0f {_percent(totals[0])} / \u5927 {_percent(totals[1])}</strong></article>"
        )
    if not cards:
        return ""
    return (
        '<section class="detail-section goals-section" id="goals">'
        '<div class="section-heading"><div><div class="section-kicker">\u8fdb\u7403\u73af\u5883</div>'
        '<h2>\u8fdb\u7403\u4fe1\u53f7</h2></div><p>\u7531\u5f53\u524d\u6a21\u578b\u6982\u7387\u8ba1\u7b97</p></div>'
        '<div class="goal-grid">' + "".join(cards) + "</div></section>"
    )


_FORMAL_MARKET_LABELS = {
    "exact_score": "Exact",
    "jc_total_goals": "JC\u603b\u8fdb\u7403",
    "jc_handicap": "JC\u8ba9\u7403",
}
_FORMAL_SELECTION_LABELS = {
    "home": "H",
    "draw": "D",
    "away": "A",
}


def _formal_markets(contract: dict[str, Any]) -> dict[str, Any]:
    value = contract.get("formal_markets")
    return value if isinstance(value, dict) else {}


def _formal_exact_is_available(contract: dict[str, Any]) -> bool:
    formal = _formal_markets(contract)
    item = _formal_market_item(formal, "exact_score")
    return _formal_status(item) == "AVAILABLE" and isinstance(item.get("contract"), dict)


def _formal_market_item(formal: dict[str, Any], key: str) -> dict[str, Any]:
    markets = formal.get("markets")
    item = markets.get(key) if isinstance(markets, dict) else None
    return item if isinstance(item, dict) else {"status": "NOT_RECORDED"}


def _formal_status(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "NOT_RECORDED").upper()
    return status if status in FORMAL_MARKET_STATUS_LABELS else "UNAVAILABLE"


def _formal_status_reason(status: str) -> str:
    if status == "NOT_RECORDED":
        return "\u65e7\u8bb0\u5f55\u6ca1\u6709\u8be5\u6b63\u5f0f\u73a9\u6cd5\u7684\u51bb\u7ed3\u5408\u7ea6\uff0c\u672a\u56de\u7b97\u3002"
    if status == "UNAVAILABLE":
        return "\u8be5\u73a9\u6cd5\u7684\u51bb\u7ed3\u5408\u7ea6\u4e0d\u53ef\u7528\uff1b\u5176\u4ed6\u6b63\u5f0f\u73a9\u6cd5\u4ecd\u72ec\u7acb\u5c55\u793a\u3002"
    return ""


def _formal_probability(value: Any) -> str:
    number = _percent_number(value)
    return f"{number * 100:.2f}%" if number is not None else "\u2014"


def _formal_unavailable_html(key: str, item: dict[str, Any]) -> str:
    status = _formal_status(item)
    label = _FORMAL_MARKET_LABELS[key]
    status_label = FORMAL_MARKET_STATUS_LABELS.get(status, status)
    return (
        f'<div class="formal-market-unavailable status-{status.lower()}" '
        f'data-formal-market="{html.escape(key, quote=True)}" '
        f'data-formal-market-status="{html.escape(status, quote=True)}">'
        f'<strong>{_esc(label)}</strong><span>{_esc(status_label)}</span>'
        f'<p>{_esc(_formal_status_reason(status))}</p></div>'
    )


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
            f'<div class="exact-compact-row" data-formal-compact-score="{score}" '
            f'data-formal-compact-rank="{rank}" data-formal-compact-probability="{probability:.12f}">'
            f'<span class="exact-compact-score"><b>#{rank}</b>{html.escape(score)}</span>'
            f'<span class="exact-compact-bar" aria-hidden="true"><span style="width:{probability * 100:.2f}%"></span></span>'
            f'<strong class="exact-compact-probability">{_formal_probability(probability)}</strong></div>'
        )
    return (
        '<div class="exact-compact" data-formal-exact-compact="true" '
        f'data-formal-compact-source-cell-count="{len(selected) + remainder_count}" '
        f'data-formal-compact-top-count="{len(selected)}" '
        f'data-formal-compact-remainder-count="{remainder_count}" '
        f'data-formal-compact-remainder-probability="{remainder:.12f}" '
        'aria-label="移动端 Exact 冻结概率摘要">'
        '<div class="exact-compact-heading"><h4>Exact 紧凑概率</h4><span>冻结格 Top 6</span></div>'
        '<div class="exact-compact-list">'
        + "".join(rows)
        + '</div>'
        f'<div class="exact-compact-remainder"><span>其余 {remainder_count} 个已表示格</span>'
        f'<strong>{_formal_probability(remainder)}</strong></div>'
        '<p class="exact-compact-note">仅合计 0–12 × 0–12 内其余已表示格；显式范围之外的比分未表示，不是已知尾部。</p>'
        '</div>'
    )


def _render_exact_formal_market(item: dict[str, Any]) -> str:
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else None
    if _formal_status(item) != "AVAILABLE" or contract is None:
        return _formal_unavailable_html("exact_score", item)
    cells = contract.get("cells") if isinstance(contract.get("cells"), list) else []
    by_score = {
        (cell.get("home_goals"), cell.get("away_goals")): cell
        for cell in cells
        if isinstance(cell, dict)
    }
    max_goals = EXACT_DISTRIBUTION_MAX_GOALS
    headers = "".join(f'<th scope="col">{goal}</th>' for goal in range(max_goals + 1))
    rows = []
    for home in range(max_goals + 1):
        cells_html = []
        for away in range(max_goals + 1):
            cell = by_score.get((home, away))
            probability = _percent_number(cell.get("probability")) if cell else None
            probability_attr = f' data-probability="{probability:.6f}"' if probability is not None else ""
            cells_html.append(
                f'<td data-formal-cell-home="{home}" data-formal-cell-away="{away}"{probability_attr}>'
                f'{_formal_probability(probability)}</td>'
            )
        rows.append(f'<tr><th scope="row">{home}</th>{"".join(cells_html)}</tr>')
    return (
        '<div class="formal-market-panel formal-exact-panel" data-formal-market="exact_score" '
        'data-formal-market-status="AVAILABLE">'
        '<div class="formal-panel-heading"><h3>Exact</h3>'
        f'<span>{EXACT_DISTRIBUTION_CELL_COUNT}\u683c\u00b7\u663e\u5f0f\u7f51\u683c</span></div>'
        + _render_exact_compact_projection(contract)
        + '<details open class="exact-full-disclosure" data-formal-exact-disclosure>'
        '<summary>\u67e5\u770b\u5b8c\u6574\u51bb\u7ed3 169 \u683c\u77e9\u9635</summary>'
        '<p class="exact-disclosure-cue">\u79fb\u52a8\u7aef\u6253\u5f00\u540e\u5728 Exact \u533a\u57df\u5185\u5de6\u53f3\u6ed1\u52a8\uff1bH \u4e3a\u4e3b\u961f\u8fdb\u7403\uff0cA \u4e3a\u5ba2\u961f\u8fdb\u7403\u3002</p>'
        '<div class="exact-grid-wrap" role="region" tabindex="0" aria-label="\u51bb\u7ed3 Exact 169 \u683c\u6982\u7387\u77e9\u9635\uff1bH \u4e3a\u4e3b\u961f\u8fdb\u7403\uff0cA \u4e3a\u5ba2\u961f\u8fdb\u7403">'
        '<table class="exact-grid"><caption class="sr-only">\u51bb\u7ed3 Exact 169 \u683c\uff1a\u4e3b\u961f\u8fdb\u7403 H \u00d7 \u5ba2\u961f\u8fdb\u7403 A</caption><thead><tr><th scope="col">H\\A</th>'
        + headers
        + '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div></details>'
        '<p class="formal-market-note">\u4ec5\u5c55\u793a\u51bb\u7ed3\u5408\u7ea6\u4e2d 0\u201312 \u7403\u7684 169 \u4e2a\u663e\u5f0f\u683c\uff1b\u4e0d\u4f2a\u9020\u65e0\u9650\u5c3e\u90e8\u3002</p>'
        '</div>'
    )


def _render_total_formal_market(item: dict[str, Any]) -> str:
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else None
    if _formal_status(item) != "AVAILABLE" or contract is None:
        return _formal_unavailable_html("jc_total_goals", item)
    probabilities = contract.get("probabilities") if isinstance(contract.get("probabilities"), dict) else {}
    top = contract.get("top_selection")
    order = contract.get("selection_order") if isinstance(contract.get("selection_order"), list) else []
    rows = []
    for bucket in order:
        number = _percent_number(probabilities.get(bucket))
        top_class = " formal-market-top" if bucket == top else ""
        rows.append(
            f'<div class="formal-total-row{top_class}" data-formal-selection="{html.escape(str(bucket), quote=True)}">'
            f'<span>{_esc(bucket)}</span><div class="formal-total-bar" aria-hidden="true"><span style="width:{(number or 0.0) * 100:.1f}%"></span></div>'
            f'<strong>{_formal_probability(number)}</strong></div>'
        )
    return (
        '<div class="formal-market-panel" data-formal-market="jc_total_goals" data-formal-market-status="AVAILABLE">'
        '<div class="formal-panel-heading"><h3>JC\u603b\u8fdb\u7403</h3><span>0\u20136\uff0c7+</span></div>'
        '<div class="formal-total-list">' + "".join(rows) + '</div>'
        '<p class="formal-market-note">\u53ea\u8bfb\u51bb\u7ed3\u7684 official JC \u603b\u8fdb\u7403\u5408\u7ea6\u3002</p>'
        '</div>'
    )


def _render_handicap_formal_market(item: dict[str, Any]) -> str:
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else None
    if _formal_status(item) != "AVAILABLE" or contract is None:
        return _formal_unavailable_html("jc_handicap", item)
    probabilities = contract.get("probabilities") if isinstance(contract.get("probabilities"), dict) else {}
    order = contract.get("selection_order") if isinstance(contract.get("selection_order"), list) else []
    top = contract.get("top_selection")
    cards = []
    for selection in order:
        number = _percent_number(probabilities.get(selection))
        top_class = " formal-market-top" if selection == top else ""
        code = _FORMAL_SELECTION_LABELS.get(str(selection), str(selection))
        cards.append(
            f'<div class="formal-handicap-card{top_class}" data-formal-selection="{html.escape(str(selection), quote=True)}">'
            f'<span>{html.escape(code, quote=True)}</span><strong>{_formal_probability(number)}</strong>'
            f'<em>{_esc(selection)}</em></div>'
        )
    line = contract.get("official_integer_line", contract.get("line"))
    return (
        '<div class="formal-market-panel" data-formal-market="jc_handicap" data-formal-market-status="AVAILABLE">'
        f'<div class="formal-panel-heading"><h3>JC\u8ba9\u7403 H/D/A</h3><span>\u5b98\u65b9\u6574\u6570\u8ba9\u7403 {html.escape(str(line), quote=True)}</span></div>'
        '<div class="formal-handicap-grid">' + "".join(cards) + '</div>'
        '<p class="formal-market-note">H=\u4e3b\u80dc\uff0cD=\u5e73\uff0cA=\u5ba2\u80dc\uff1b\u53ea\u8bfb\u51bb\u7ed3\u7684\u6574\u6570\u8ba9\u7403\u5408\u7ea6\u3002</p>'
        '</div>'
    )


def _render_formal_markets(contract: dict[str, Any]) -> str:
    formal = _formal_markets(contract)
    markets = formal.get("markets")
    if not isinstance(markets, dict):
        return ""
    items = {key: _formal_market_item(formal, key) for key in _FORMAL_MARKET_LABELS}
    status_matrix = "".join(
        f'<span class="formal-market-status status-{_formal_status(item).lower()}" '
        f'data-formal-market-status="{_formal_status(item)}">{_esc(_FORMAL_MARKET_LABELS[key])} '
        f'{_esc(FORMAL_MARKET_STATUS_LABELS.get(_formal_status(item), _formal_status(item)))}</span>'
        for key, item in items.items()
    )
    return (
        '<section class="detail-section formal-markets-section" id="formal-markets">'
        '<div class="section-heading"><div><div class="section-kicker">\u51bb\u7ed3\u8d5b\u524d\u5408\u7ea6</div>'
        '<h2>\u6b63\u5f0f\u73a9\u6cd5\u6982\u7387</h2></div>'
        '<p>\u53ea\u8bfb\u51bb\u7ed3\u7684 Exact \u4e0e official JC</p></div>'
        '<div class="formal-market-status-matrix" aria-label="\u6b63\u5f0f\u73a9\u6cd5\u72b6\u6001">'
        + status_matrix
        + '</div><div class="formal-market-grid">'
        + _render_exact_formal_market(items["exact_score"])
        + _render_total_formal_market(items["jc_total_goals"])
        + _render_handicap_formal_market(items["jc_handicap"])
        + '''</div><script>
(() => {
  const disclosures = document.querySelectorAll('[data-formal-exact-disclosure]');
  const isMobile = window.matchMedia('(max-width: 560px)').matches;
  disclosures.forEach((disclosure) => {
    if (isMobile) disclosure.open = false;
  });
})();
</script></section>'''
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


def _render_key_evidence(contract: dict[str, Any]) -> str:
    evidence = contract.get("evidence") or {}
    probabilities = _probabilities(contract)
    blocks = []
    form_html = _render_form(evidence)
    if form_html:
        blocks.append(form_html)

    outcome_values = [
        ("\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("\u5e73", _percent_number(probabilities.get("draw"))),
        ("\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    ]
    outcome_values = [(label, value) for label, value in outcome_values if value is not None]
    score_rows = _score_rows(contract, limit=3)
    derived = []
    if outcome_values:
        outcome = max(outcome_values, key=lambda item: item[1])
        derived.append(f"\u5f53\u524d\u80dc\u5e73\u8d1f\u4e2d\uff0c{outcome[0]}\u6982\u7387\u6700\u9ad8\uff08{_percent(outcome[1])}\uff09\u3002")
    if score_rows:
        primary = score_rows[0]
        alternatives = "\u3001".join(row["score"] for row in score_rows[1:3])
        suffix = f"\uff1b\u66ff\u4ee3\u6bd4\u5206\u4e3a{alternatives}" if alternatives else ""
        derived.append(f'\u6700\u9ad8\u6982\u7387\u6bd4\u5206\u4e3a{primary["score"]}\uff08{_percent(primary["probability"])}\uff09{suffix}\uff0c\u5b83\u4e0d\u662f\u786e\u5b9a\u8d5b\u679c\u3002')
    if derived:
        blocks.append(
            '<article class="evidence-block"><h3>\u5f53\u524d\u5224\u65ad</h3><p>'
            + "<br>".join(_esc(value) for value in derived)
            + "</p></article>"
        )

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
        '<div class="section-heading"><div><div class="section-kicker">\u4e3a\u4ec0\u4e48</div><h2>\u5173\u952e\u4f9d\u636e</h2></div>'
        '<p>\u53ea\u5c55\u793a\u5f53\u524d\u8bb0\u5f55\u4e2d\u771f\u5b9e\u5b58\u5728\u7684\u89e3\u91ca</p></div><div class="evidence-grid">'
        + "".join(blocks)
        + "</div></section>"
    )


def _market_comparison(contract: dict[str, Any]) -> dict[str, float] | None:
    market = contract.get("market")
    if not isinstance(market, dict):
        evidence_market = (contract.get("evidence") or {}).get("market")
        market = evidence_market if isinstance(evidence_market, dict) else {}
    comparison = market.get("model_comparison") if isinstance(market, dict) else None
    if not isinstance(comparison, dict):
        return None
    model_home = _percent_number(comparison.get("model_home_probability"))
    market_home = _percent_number(comparison.get("market_home_probability"))
    if model_home is None or market_home is None:
        return None
    return {"model_home": model_home, "market_home": market_home}


def _render_market_comparison(contract: dict[str, Any]) -> str:
    comparison = _market_comparison(contract)
    if comparison is None:
        return ""
    difference = comparison["model_home"] - comparison["market_home"]
    direction = "\u4f4e\u4e8e" if difference < 0 else "\u9ad8\u4e8e"
    return (
        '<section class="detail-section market-section" id="market">'
        '<div class="section-heading"><div><div class="section-kicker">\u771f\u5b9e\u5bf9\u7167</div><h2>\u6a21\u578b\u4e0e\u5e02\u573a</h2></div>'
        '<p>\u4ec5\u5728\u540c\u65f6\u5b58\u5728\u4e24\u4fa7\u6982\u7387\u65f6\u663e\u793a</p></div><div class="market-compare">'
        f'<div><span>\u6a21\u578b \u00b7 \u4e3b\u80dc</span><strong>{_percent(comparison["model_home"])}</strong></div>'
        f'<div><span>\u5e02\u573a\u65e0 vig \u00b7 \u4e3b\u80dc</span><strong>{_percent(comparison["market_home"])}</strong></div>'
        f"<p>\u6a21\u578b\u4e3b\u80dc\u6982\u7387{direction}\u5e02\u573a {abs(difference) * 100:.1f} \u4e2a\u767e\u5206\u70b9\u3002</p>"
        "</div></section>"
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
    source_quality = contract.get("source_quality") or (contract.get("evidence") or {}).get("source_quality") or {}
    status = _status_code(contract)
    rows = []
    frozen_at = timestamps.get("prediction_frozen_at") or timestamps.get("freeze_created_at")
    if frozen_at:
        rows.append(f'<div class="trust-lock"><strong>\u8d5b\u524d\u9884\u6d4b\u5df2\u9501\u5b9a\u4e8e {_esc(_format_datetime(frozen_at))}</strong><span>\u8d5b\u540e\u4e0d\u4fee\u6539</span></div>')
    elif status == "FROZEN":
        rows.append('<div class="trust-lock"><strong>\u8d5b\u524d\u9884\u6d4b\u5df2\u9501\u5b9a</strong><span>\u8d5b\u540e\u4e0d\u4fee\u6539</span></div>')
    cutoff = timestamps.get("source_cutoff_at") or timestamps.get("evidence_updated_at") or source_quality.get("recent_form_captured_at")
    if cutoff:
        rows.append(f'<div class="trust-line"><span>\u6570\u636e\u622a\u6b62</span><strong>{_esc(_format_datetime(cutoff, include_date=True))}</strong></div>')
    references = _source_items(contract)
    if references:
        list_html = "".join(f"<li>{_esc(item)}</li>" for item in references[:5])
        rows.append(f'<div class="trust-source"><span>\u6765\u6e90</span><ul>{list_html}</ul></div>')
    technical = _render_technical_details(contract)
    if technical:
        rows.append(technical)
    if not rows:
        return ""
    title = "\u53ef\u4fe1\u5ea6\u4e0e\u6765\u6e90" if references else "\u8d5b\u524d\u8bb0\u5f55"
    kicker = "\u53ef\u4fe1\u5ea6" if references else "\u8bb0\u5f55"
    return f'<aside class="trust-panel" id="sources"><div class="section-kicker">{kicker}</div><h2>{title}</h2>' + "".join(rows) + "</aside>"


def _result_score(result: dict[str, Any]) -> tuple[int, int] | None:
    text = str(result.get("score_90m") or "").strip()
    try:
        home, away = text.split("-", 1)
        return int(home), int(away)
    except (ValueError, TypeError):
        return None


def _outcome(score: tuple[int, int]) -> str:
    return "\u4e3b\u80dc" if score[0] > score[1] else "\u5ba2\u80dc" if score[0] < score[1] else "\u5e73"


def _formal_verification_label(key: str, verification: dict[str, Any]) -> str:
    status = str(verification.get("verification_status") or "NOT_RECORDED").upper()
    if status == "VERIFIED":
        actual = verification.get("actual_selection") or "\u2014"
        if key == "jc_handicap":
            actual = _FORMAL_SELECTION_LABELS.get(str(actual), str(actual))
        if key == "exact_score":
            rank = verification.get("actual_rank")
            rank_text = f"frozen rank #{rank}" if isinstance(rank, int) and rank > 0 else "frozen rank unavailable"
            support = str(verification.get("represented_support_status") or "UNAVAILABLE")
            return f"{actual} · {rank_text} · {support}"
        hit = "\uff0c\u8d5b\u524d\u9996\u9009\u547d\u4e2d" if verification.get("top_selection_hit") else "\uff0c\u8d5b\u524d\u9996\u9009\u672a\u547d\u4e2d"
        return f"{actual}{hit}"
    if status == "OUT_OF_EXPLICIT_SUPPORT":
        actual = verification.get("actual_selection") or "\u2014"
        support = str(verification.get("represented_support_status") or "OUT_OF_EXPLICIT_SUPPORT")
        return f"{actual} · {support} · \u672a\u8ba1\u5165 frozen rank / probability"
    if status == "NOT_RECORDED":
        return "\u672a\u8bb0\u5f55"
    if status == "UNAVAILABLE":
        return "\u4e0d\u53ef\u7528"
    if status == "INVALID_90M_SCORE":
        return "\u8d5b\u679c\u65e0\u6cd5\u6838\u9a8c"
    return status


def _render_formal_verification(verification: dict[str, dict[str, Any]]) -> str:
    if not isinstance(verification, dict):
        return ""
    rows = []
    for key in _FORMAL_MARKET_LABELS:
        item = verification.get(key) if isinstance(verification.get(key), dict) else {}
        status = str(item.get("verification_status") or "NOT_RECORDED").upper()
        detail = _formal_verification_label(key, item)
        probability = item.get("actual_probability")
        probability_text = f"\uff1b\u8be5\u7ed3\u679c\u5728\u51bb\u7ed3\u5408\u7ea6\u4e2d\u4e3a {_formal_probability(probability)}" if probability is not None else ""
        rows.append(
            f'<div class="formal-verification-row status-{html.escape(status.lower(), quote=True)}" '
            f'data-formal-verification-market="{html.escape(key, quote=True)}" '
            f'data-formal-verification-status="{html.escape(status, quote=True)}" '
            f'data-formal-actual-rank="{html.escape(str(item.get("actual_rank") or ""), quote=True)}" '
            f'data-formal-support-status="{html.escape(str(item.get("represented_support_status") or ""), quote=True)}">'
            f'<span>{_esc(_FORMAL_MARKET_LABELS[key])}</span>'
            f'<strong>{_esc(detail)}</strong>'
            f'<em>{_esc(probability_text)}</em></div>'
        )
    return (
        '<div class="formal-verification"><div class="formal-verification-heading">'
        '<strong>\u6b63\u5f0f\u73a9\u6cd5\u6838\u9a8c</strong>'
        '<span>\u4ec5\u6309 90 \u5206\u949f + \u8865\u65f6\u7684\u5df2\u6838\u9a8c\u8d5b\u679c</span></div>'
        + "".join(rows)
        + '</div>'
    )


def _completed_comparison(contract: dict[str, Any]) -> dict[str, Any]:
    result = contract.get("result") or {}
    score = _result_score(result) if isinstance(result, dict) else None
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
    formal_verification = verify_formal_markets(
        _formal_markets(contract),
        score,
    )
    return {
        "actual_score": actual_score,
        "primary_score": primary,
        "exact_status": exact_status,
        "predicted_direction": predicted,
        "actual_direction": actual_outcome,
        "direction_status": direction_status,
        "formal_market_verification": formal_verification,
    }


def _render_completed_result(contract: dict[str, Any]) -> str:
    result = contract.get("result") or {}
    if not isinstance(result, dict) or not result.get("score_90m"):
        return ""
    verified = _format_datetime(result.get("verified_at"), include_date=True)
    verified_html = f"<span>\u6838\u9a8c\u4e8e {verified}</span>" if verified else ""
    comparison = _completed_comparison(contract)
    value = lambda key: _esc(comparison.get(key) or "\u2014")
    facts = (
        '<div class="completed-facts">'
        f'<div><span>\u5b9e\u9645\u6bd4\u5206</span><strong>{value("actual_score")}</strong></div>'
        f'<div><span>\u5f53\u65f6\u6700\u9ad8\u6982\u7387\u6bd4\u5206</span><strong>{value("primary_score")}</strong></div>'
        f'<div><span>\u6bd4\u5206</span><strong>{value("exact_status")}</strong></div>'
        f'<div><span>\u5f53\u65f6\u0031X2\u65b9\u5411</span><strong>{value("predicted_direction")}</strong></div>'
        f'<div><span>\u5b9e\u9645\u65b9\u5411</span><strong>{value("actual_direction")}</strong></div>'
        f'<div><span>\u65b9\u5411</span><strong>{value("direction_status")}</strong></div>'
        '</div>'
    )
    formal_verification_html = _render_formal_verification(comparison.get("formal_market_verification") or {})
    return (
        '<section class="result-panel" id="result"><div class="section-kicker">\u8d5b\u540e\u9a8c\u8bc1</div><h2>\u5b9e\u9645\u8d5b\u679c</h2>'
        f'<div class="actual-score">{_display_score(result.get("score_90m"))}</div>'
        f'<div class="actual-meta"><strong>90\u5206\u949f\u8d5b\u679c</strong>{verified_html}</div>'
        + facts
        + formal_verification_html
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
    :root { --bg:#F7F5F1; --surface:#FFFFFF; --ink:#111111; --muted:#6B7280; --line:#E5E7EB; --accent:#FF6A00; --soft:#FFF2E8; --max:1240px; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }
    a { color:inherit; }
    .page { width:min(calc(100% - 40px), var(--max)); margin:0 auto; padding:18px 0 52px; }
    .site-header { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:6px 0 18px; }
    .brand { display:flex; align-items:baseline; gap:10px; text-decoration:none; }
    .brand-name { font-size:20px; font-weight:850; letter-spacing:-.05em; }
    .brand-subtitle,.eyebrow,.section-kicker { color:var(--muted); font-size:11px; letter-spacing:.09em; }
    .header-actions { display:flex; align-items:center; gap:14px; }
    .back { color:var(--muted); text-decoration:none; font-size:13px; }
    .back:hover { color:var(--ink); }
    .detail-nav { display:none; flex-wrap:wrap; gap:16px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); padding:10px 0; margin-bottom:18px; }
    .detail-nav a { color:var(--muted); text-decoration:none; font-size:12px; }
    .detail-nav a:hover { color:var(--accent); }
    .detail-layout { display:grid; grid-template-columns:minmax(0,1fr) 286px; gap:36px; align-items:start; }
    .detail-main { min-width:0; }
    .match-identity { padding:8px 0 20px; border-bottom:1px solid var(--line); }
    .match-meta { display:flex; flex-wrap:wrap; gap:5px 12px; color:var(--muted); font-size:12px; }
    .match-identity h1 { margin:9px 0 0; font-size:clamp(28px,3.6vw,46px); line-height:1.08; letter-spacing:-.06em; font-weight:820; }
    .match-identity h1 span { color:var(--muted); font-weight:450; letter-spacing:-.02em; }
    .quality-warning { display:flex; align-items:flex-start; gap:10px; margin:18px 0 0; padding:10px 12px; border-left:3px solid var(--accent); background:var(--soft); }
    .quality-warning strong { font-size:13px; }
    .quality-warning span { color:var(--muted); font-size:12px; }
    .pilot-note { display:inline-flex; margin-top:12px; color:#A34700; font-size:12px; }
    .result-panel,.status-panel { margin:20px 0 0; padding:19px 0; border-top:2px solid var(--accent); border-bottom:1px solid var(--line); }
    .result-panel h2,.status-panel h2 { margin:3px 0 2px; font-size:22px; letter-spacing:-.03em; }
    .actual-score { margin:12px 0 1px; font-size:56px; line-height:1; font-weight:850; letter-spacing:-.08em; }
    .actual-meta { display:flex; flex-wrap:wrap; gap:8px 12px; color:var(--muted); font-size:12px; }
    .result-panel p { margin:10px 0 0; color:var(--muted); }
    .completed-facts { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; margin-top:16px; }
    .completed-facts > div { padding:9px 10px; border:1px solid var(--line); background:var(--surface); }
    .completed-facts span,.completed-facts strong { display:block; }
    .completed-facts span { color:var(--muted); font-size:11px; }
    .completed-facts strong { margin-top:3px; font-size:14px; font-variant-numeric:tabular-nums; }
    .status-panel { display:flex; gap:13px; align-items:flex-start; border-top-color:var(--line); }
    .status-mark { display:grid; place-items:center; width:25px; height:25px; border-radius:50%; background:var(--soft); color:var(--accent); font-weight:800; }
    .status-panel p { margin:7px 0 0; color:var(--muted); }
    .detail-section { padding:26px 0; border-bottom:1px solid var(--line); }
    .section-heading { display:flex; align-items:end; justify-content:space-between; gap:18px; margin-bottom:14px; }
    .section-heading h2 { margin:3px 0 0; font-size:23px; letter-spacing:-.04em; }
    .section-heading p { margin:0; color:var(--muted); font-size:12px; text-align:right; }
    .hero-probabilities { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
    .probability-card { min-width:0; padding:13px 13px 12px; border:1px solid var(--line); background:var(--surface); }
    .probability-card.probability-highest { border-color:var(--accent); }
    .probability-label { display:block; color:var(--muted); font-size:12px; }
    .probability-card strong { display:block; margin-top:3px; font-size:28px; line-height:1; letter-spacing:-.06em; font-variant-numeric:tabular-nums; }
    .probability-track,.score-bar { overflow:hidden; background:#F0EFEC; }
    .probability-track { height:5px; margin-top:14px; }
    .probability-track span,.score-bar span { display:block; height:100%; background:var(--accent); }
    .score-list { display:grid; gap:0; }
    .score-row { display:grid; grid-template-columns:100px minmax(80px,1fr) 64px; align-items:center; gap:13px; min-height:35px; border-top:1px solid var(--line); }
    .score-row:first-child { border-top:0; }
    .score-name { display:flex; align-items:baseline; gap:8px; min-width:0; }
    .score-name strong { font-size:18px; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }
    .score-name span { color:var(--muted); font-size:11px; white-space:nowrap; }
    .score-bar { height:7px; }
    .score-probability { text-align:right; font-variant-numeric:tabular-nums; }
    .section-note,.source-line { margin:11px 0 0; color:var(--muted); font-size:12px; }
    .goal-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
    .goal-card { padding:14px; border:1px solid var(--line); background:var(--surface); }
    .goal-card-label { display:block; color:var(--muted); font-size:12px; }
    .goal-card strong { display:block; margin-top:5px; font-size:18px; font-variant-numeric:tabular-nums; letter-spacing:-.03em; }
    .formal-market-status-matrix { display:flex; flex-wrap:wrap; gap:5px; margin:-2px 0 12px; }
    .formal-market-status { padding:4px 7px; border:1px solid var(--line); background:var(--surface); color:var(--muted); font-size:11px; white-space:nowrap; }
    .formal-market-status.status-available { border-color:#B7D8C1; color:var(--ink); }
    .formal-market-status.status-unavailable { border-color:#F2C4A8; color:#A34700; }
    .formal-market-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .formal-market-panel { min-width:0; padding:14px; border:1px solid var(--line); background:var(--surface); }
    .formal-exact-panel { grid-column:1/-1; }
    .formal-panel-heading { display:flex; align-items:baseline; justify-content:space-between; gap:10px; margin-bottom:10px; }
    .formal-panel-heading h3 { margin:0; font-size:15px; }
    .formal-panel-heading span { color:var(--muted); font-size:11px; text-align:right; }
    .formal-market-note { margin:9px 0 0; color:var(--muted); font-size:11px; }
    .exact-compact { display:none; }
    .exact-full-disclosure { margin-top:2px; }
    .exact-full-disclosure:not([open]) > :not(summary) { display:none; }
    .exact-full-disclosure > summary { padding:3px 0 7px; cursor:pointer; font-size:12px; font-weight:700; }
    .exact-disclosure-cue { margin:0 0 8px; color:var(--muted); font-size:11px; }
    .exact-grid-wrap { max-width:100%; overflow-x:auto; }
    .exact-grid { width:100%; min-width:650px; border-collapse:collapse; table-layout:fixed; font-size:10px; font-variant-numeric:tabular-nums; }
    .exact-grid th,.exact-grid td { width:7.14%; padding:5px 3px; border:1px solid var(--line); text-align:center; white-space:nowrap; }
    .exact-grid th { background:#FAF9F6; color:var(--muted); font-weight:650; }
    .exact-grid td { color:var(--ink); }
    .formal-total-list { display:grid; gap:2px; }
    .formal-total-row { display:grid; grid-template-columns:30px minmax(0,1fr) 52px; align-items:center; gap:8px; min-height:27px; border-top:1px solid var(--line); font-size:11px; font-variant-numeric:tabular-nums; }
    .formal-total-row:first-child { border-top:0; }
    .formal-total-row > span { color:var(--muted); }
    .formal-total-row > strong { text-align:right; font-weight:650; }
    .formal-total-row.formal-market-top > span { color:var(--ink); font-weight:700; }
    .formal-total-bar { height:5px; overflow:hidden; background:#F0EFEC; }
    .formal-total-bar span { display:block; height:100%; background:var(--accent); }
    .formal-handicap-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:5px; }
    .formal-handicap-card { min-width:0; padding:10px 7px; border:1px solid var(--line); text-align:center; }
    .formal-handicap-card.formal-market-top { border-color:var(--accent); }
    .formal-handicap-card span,.formal-handicap-card strong,.formal-handicap-card em { display:block; }
    .formal-handicap-card span { color:var(--muted); font-size:11px; }
    .formal-handicap-card strong { margin-top:2px; font-size:18px; font-variant-numeric:tabular-nums; }
    .formal-handicap-card em { margin-top:2px; color:var(--muted); font-size:10px; font-style:normal; }
    .formal-market-unavailable { min-height:116px; padding:11px; border:1px dashed var(--line); background:#FAF9F6; }
    .formal-market-unavailable strong,.formal-market-unavailable span { display:inline-block; }
    .formal-market-unavailable span { margin-left:7px; color:var(--muted); font-size:11px; }
    .formal-market-unavailable p { margin:9px 0 0; color:var(--muted); font-size:11px; }
    .formal-market-unavailable.status-unavailable { border-color:#F2C4A8; }
    .formal-verification { margin-top:16px; padding-top:12px; border-top:1px solid var(--line); }
    .formal-verification-heading { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px; margin-bottom:5px; }
    .formal-verification-heading strong { font-size:13px; }
    .formal-verification-heading span { color:var(--muted); font-size:11px; }
    .formal-verification-row { display:grid; grid-template-columns:95px minmax(0,1fr) minmax(120px,1fr); gap:10px; align-items:baseline; padding:7px 0; border-top:1px solid var(--line); font-size:11px; }
    .formal-verification-row > span { color:var(--muted); }
    .formal-verification-row > strong { font-weight:650; }
    .formal-verification-row > em { color:var(--muted); font-style:normal; text-align:right; }
    .formal-verification-row.status-unavailable > strong,.formal-verification-row.status-not_recorded > strong { color:#A34700; }
    .evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .evidence-block { padding:15px; border:1px solid var(--line); background:var(--surface); }
    .evidence-block h3 { margin:0 0 10px; font-size:15px; }
    .evidence-block p { margin:0; }
    .evidence-fact { display:flex; justify-content:space-between; gap:10px; padding:8px 0; border-top:1px solid var(--line); font-size:12px; }
    .evidence-fact:first-of-type { border-top:0; }
    .evidence-fact span { color:var(--muted); }
    .evidence-fact strong { text-align:right; font-weight:650; }
    .evidence-subheading { margin-top:10px; color:var(--muted); font-size:11px; }
    .support-list { margin:4px 0 0; padding-left:17px; }
    .support-list li { margin:4px 0; }
    .market-compare { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
    .market-compare > div { padding:14px; border:1px solid var(--line); background:var(--surface); }
    .market-compare span { display:block; color:var(--muted); font-size:12px; }
    .market-compare strong { display:block; margin-top:4px; font-size:24px; font-variant-numeric:tabular-nums; }
    .market-compare p { grid-column:1/-1; margin:0; color:var(--muted); font-size:12px; }
    .trust-panel { position:sticky; top:18px; padding:17px; border:1px solid var(--line); background:var(--surface); }
    .trust-panel h2 { margin:3px 0 15px; font-size:21px; letter-spacing:-.04em; }
    .trust-lock { padding:11px 0 13px; border-top:2px solid var(--accent); border-bottom:1px solid var(--line); }
    .trust-lock strong,.trust-lock span { display:block; }
    .trust-lock strong { font-size:13px; }
    .trust-lock span { margin-top:3px; color:var(--muted); font-size:12px; }
    .trust-line,.trust-source { padding:11px 0; border-bottom:1px solid var(--line); font-size:12px; }
    .trust-line span,.trust-source > span { display:block; color:var(--muted); }
    .trust-line strong { display:block; margin-top:3px; font-weight:650; }
    .trust-source ul { margin:5px 0 0; padding-left:17px; color:var(--muted); overflow-wrap:anywhere; }
    .technical-details { margin-top:12px; border-top:1px solid var(--line); }
    .technical-details summary { padding:11px 0; cursor:pointer; color:var(--ink); font-size:12px; }
    .technical-list { border-top:1px solid var(--line); }
    .technical-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.3fr); gap:10px; padding:7px 0; border-bottom:1px solid var(--line); font-size:11px; }
    .technical-row span { color:var(--muted); }
    .technical-row code { overflow-wrap:anywhere; text-align:right; font:inherit; }
    .closed-beta { margin-top:32px; padding-top:13px; border-top:1px solid var(--line); color:var(--muted); font-size:11px; }
    .closed-beta strong,.closed-beta span { display:block; margin-top:4px; }
    .detail-footer { display:flex; justify-content:space-between; gap:12px; padding-top:18px; color:var(--muted); font-size:11px; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media (max-width:900px) {
      .page { width:min(calc(100% - 28px), var(--max)); }
      .detail-layout { grid-template-columns:1fr; gap:0; }
      .trust-panel { position:static; margin-top:21px; }
    }
    @media (max-width:560px) {
      .page { width:calc(100% - 20px); padding-top:11px; }
      .site-header { padding-bottom:13px; }
      .brand-subtitle { display:none; }
      .detail-nav { display:none; }
      .match-identity { padding-bottom:20px; }
      .match-identity h1 { font-size:31px; line-height:1.12; }
      .quality-warning { display:block; }
      .quality-warning strong { display:inline; margin-right:7px; }
      .quality-warning span { display:inline; }
      .section-heading { display:block; }
      .section-heading p { margin-top:4px; text-align:left; }
      .hero-probabilities { gap:5px; }
      .probability-card { padding:11px 9px; }
      .probability-card strong { font-size:23px; }
      .completed-facts { grid-template-columns:repeat(2,minmax(0,1fr)); gap:5px; }
      .completed-facts > div { padding:8px; }
      .formal-market-grid { grid-template-columns:1fr; }
      .formal-exact-panel { grid-column:auto; }
      .formal-market-panel { padding:11px; }
      .exact-compact { display:block; }
      .exact-compact-heading { display:flex; align-items:baseline; justify-content:space-between; gap:8px; margin-bottom:8px; }
      .exact-compact-heading h4 { margin:0; font-size:13px; }
      .exact-compact-heading span { color:var(--muted); font-size:11px; }
      .exact-compact-list { display:grid; gap:2px; }
      .exact-compact-row { display:grid; grid-template-columns:64px minmax(0,1fr) 58px; align-items:center; gap:8px; min-height:29px; border-top:1px solid var(--line); }
      .exact-compact-row:first-child { border-top:0; }
      .exact-compact-score { font-size:13px; font-variant-numeric:tabular-nums; white-space:nowrap; }
      .exact-compact-score b { margin-right:5px; color:var(--muted); font-size:11px; font-weight:650; }
      .exact-compact-bar { height:6px; overflow:hidden; background:#F0EFEC; }
      .exact-compact-bar > span { display:block; height:100%; background:var(--accent); }
      .exact-compact-probability { text-align:right; font-size:13px; font-variant-numeric:tabular-nums; }
      .exact-compact-remainder { display:flex; align-items:baseline; justify-content:space-between; gap:8px; margin-top:7px; padding-top:7px; border-top:1px solid var(--line); font-size:12px; }
      .exact-compact-remainder strong { font-size:13px; font-variant-numeric:tabular-nums; }
      .exact-compact-note { margin:7px 0 0; color:var(--muted); font-size:11px; }
      .exact-full-disclosure { margin-top:10px; border-top:1px solid var(--line); }
      .exact-full-disclosure > summary { min-height:34px; padding:9px 0 7px; }
      .exact-grid-wrap { overflow-x:auto; }
      .exact-grid { min-width:650px; font-size:10px; }
      .exact-grid th,.exact-grid td { padding:5px 3px; overflow:visible; }
      .formal-verification-row { grid-template-columns:72px minmax(0,1fr); gap:5px 8px; }
      .formal-verification-row > em { grid-column:2; text-align:left; }
      .score-row { grid-template-columns:40px minmax(45px,1fr) 44px; gap:8px; min-height:29px; }
      .score-name { display:flex; align-items:baseline; gap:6px; }
      .score-name strong { font-size:15px; }
      .score-name span { display:none; }
      .score-probability { font-size:12px; }
      .goal-grid,.evidence-grid,.market-compare { grid-template-columns:1fr; }
      .market-compare p { grid-column:auto; }
      .detail-footer { display:block; }
      .detail-footer span { display:block; margin-top:5px; }
    }
    @media (max-width:360px) {
      .page { width:calc(100% - 16px); }
      .match-identity h1 { font-size:28px; }
      .probability-card strong { font-size:20px; }
      .formal-panel-heading { display:block; }
      .formal-panel-heading span { display:block; margin-top:3px; text-align:left; }
      .exact-compact-row { grid-template-columns:56px minmax(0,1fr) 54px; gap:6px; }
      .exact-compact-probability { font-size:12px; }
      .score-row { grid-template-columns:40px minmax(35px,1fr) 42px; gap:6px; }
    }
"""


def render_match_detail(contract: dict[str, Any]) -> str:
    identity = contract.get("identity") or {}
    status = contract.get("status") or {}
    status_code = _status_code(contract)
    serving = status_code == "FROZEN"
    result = contract.get("result") if isinstance(contract.get("result"), dict) else {}
    quality = contract.get("prediction_quality_health")
    exact_score_serving = (
        exact_score_serving_presentation(quality)
        if isinstance(quality, dict)
        else {"state": "NORMAL", "label": "", "note": ""}
    )
    quality_warning = ""
    if serving and exact_score_serving["state"] != "NORMAL":
        quality_warning = (
            f'<div class="quality-warning" role="status"><strong>{_esc(exact_score_serving["label"])}</strong>'
            f'<span>{_esc(exact_score_serving["note"])}</span></div>'
        )
    pilot_note = (
        '<div class="pilot-note">\u8bd5\u8fd0\u884c\u9884\u6d4b \u00b7 \u4ec5\u4f9b\u89c2\u5bdf</div>'
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
    result_html = _render_completed_result(contract) if serving else ""
    probability_html = _render_probability_cards(contract) if serving else ""
    formal_markets_html = _render_formal_markets(contract) if serving else ""
    score_html = (
        _render_score_distribution(contract)
        if serving and not _formal_exact_is_available(contract)
        else ""
    )
    goals_html = _render_goals(contract) if serving else ""
    evidence_html = _render_key_evidence(contract) if serving else ""
    market_html = _render_market_comparison(contract) if serving else ""
    if serving:
        forecast_html = "".join(
            [
                '<section class="detail-section forecast-section" id="analysis">',
                probability_html,
                formal_markets_html,
                score_html,
                goals_html,
                "</section>",
            ]
        )
        deeper_html = (
            f'<div class="deeper-details" id="deeper-analysis">{evidence_html}{market_html}</div>'
            if evidence_html or market_html
            else ""
        )
    else:
        forecast_html = _render_status_panel(contract)
        deeper_html = ""
    trust_html = _render_trust(contract) if serving else ""
    nav_items = []
    if serving:
        nav_items.append('<a href="#analysis">\u9884\u6d4b</a>')
        if score_html:
            nav_items.append('<a href="#score-distribution">\u6bd4\u5206</a>')
        if goals_html:
            nav_items.append('<a href="#goals">\u8fdb\u7403\u4fe1\u53f7</a>')
        if formal_markets_html:
            nav_items.append('<a href="#formal-markets">\u6b63\u5f0f\u73a9\u6cd5</a>')
        if evidence_html:
            nav_items.append('<a href="#evidence">\u5173\u952e\u4f9d\u636e</a>')
        if market_html:
            nav_items.append('<a href="#market">\u6a21\u578b\u4e0e\u5e02\u573a</a>')
        if trust_html:
            nav_items.append('<a href="#sources">\u6765\u6e90</a>')
    nav_html = f'<nav class="detail-nav" aria-label="\u9875\u9762\u5185\u5bfc\u822a">{"".join(nav_items)}</nav>' if nav_items else ""
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
<main class="page">
<header class="site-header">
  <a class="brand" href="../../prediction_dashboard/latest.html"><span class="brand-name">FBOS</span><span class="brand-subtitle">\u8d5b\u524d\u6982\u7387 \u00b7 \u8d5b\u540e\u9a8c\u8bc1</span></a>
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
    {forecast_html}
    {deeper_html}
  </div>
  {trust_html}
</div>
{closed_beta}
<footer class="detail-footer"><span>\u8d5b\u524d\u8bb0\u5f55\u4fdd\u6301\u4e0d\u53d8\uff1b\u8d5b\u540e\u7ed3\u679c\u5355\u72ec\u6838\u9a8c\u3002</span><span>\u9875\u9762\u6570\u636e\u6765\u81ea\u5f53\u524d\u53ef\u7528\u7684\u6bd4\u8d5b\u8bb0\u5f55\u3002</span></footer>
</main>
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
