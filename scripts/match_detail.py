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

try:
    from .public_ui_shared import render_beginner_help, render_public_document, render_team_badge
except ImportError:
    from public_ui_shared import render_beginner_help, render_public_document, render_team_badge


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


def _lane_serving_state(contract: dict[str, Any], lane: str) -> str:
    quality = contract.get("prediction_quality_health")
    if not isinstance(quality, dict):
        return "CAUTION" if lane == "ft_1x2" else "UNVERIFIED"
    authority = quality.get("lane_serving_authority")
    lane_authority = authority.get(lane) if isinstance(authority, dict) else None
    if isinstance(lane_authority, dict) and lane_authority.get("canonical") is True:
        state = str(lane_authority.get("state") or "").strip().upper()
        if state in {"NORMAL", "CAUTION", "DEGRADED", "UNVERIFIED"}:
            return state
    return "CAUTION" if lane == "ft_1x2" else "UNVERIFIED"


def _render_probability_cards(contract: dict[str, Any]) -> str:
    probabilities = _probabilities(contract)
    lane_state = _lane_serving_state(contract, "ft_1x2")
    lane_note = (
        '<p class="lane-status-note">\u5f53\u524d\u4ec5\u4f5c\u8d5b\u524d\u5206\u6790\u53c2\u8003</p>'
        if lane_state != "NORMAL"
        else ""
    )
    values = [
        ("home", "\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("draw", "\u5e73", _percent_number(probabilities.get("draw"))),
        ("away", "\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    ]
    section_attrs = f'data-one-x-two-serving-state="{html.escape(lane_state, quote=True)}"'
    if any(value is None for _, _, value in values):
        return (
            f'<article class="probability-section panel probability-panel lane-unavailable" id="probability" {section_attrs} aria-labelledby="probability-title">'
            '<h2 id="probability-title">\u80dc / \u5e73 / \u8d1f\u6982\u7387 <i class="info-i">i</i></h2>'
            f'{lane_note}<p>\u80dc\u5e73\u8d1f\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u9875\u9762\u4e0d\u8865\u5199\u7f3a\u5931\u7684\u6982\u7387\u3002</p></article>'
        )
    numeric = [value for _, _, value in values if value is not None]
    total = sum(numeric)
    if total <= 0:
        return (
            f'<article class="probability-section panel probability-panel lane-unavailable" id="probability" {section_attrs} aria-labelledby="probability-title">'
            '<h2 id="probability-title">\u80dc / \u5e73 / \u8d1f\u6982\u7387 <i class="info-i">i</i></h2>'
            f'{lane_note}<p>\u80dc\u5e73\u8d1f\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u9875\u9762\u4e0d\u8865\u5199\u7f3a\u5931\u7684\u6982\u7387\u3002</p></article>'
        )
    leader = max(values, key=lambda item: item[2] or 0.0)[0]
    cards = []
    segments = []
    aria_values = []
    for key, label, number in values:
        assert number is not None
        highest = " probability-highest" if key == leader else ""
        leader_note = "\u76f8\u5bf9\u5360\u4f18" if key == leader else chr(160)
        cards.append(
            f'<div class="probability-card{highest}" data-probability="{number:.6f}">'
            f'<span class="probability-label {key}-t">{label}</span><strong class="{key}-t">{_percent(number)}</strong>'
            f'<small>{leader_note}</small></div>'
        )
        segments.append(
            f'<span class="probability-segment {key}" style="width:{number / total * 100:.3f}%" aria-hidden="true"></span>'
        )
        aria_values.append(f"{label} {_percent(number)}")
    aria_label = "\uFF1B".join(aria_values)
    return (
        f'<article class="probability-section panel probability-panel" id="probability" {section_attrs} aria-labelledby="probability-title">'
        '<h2 id="probability-title">\u80dc / \u5e73 / \u8d1f\u6982\u7387 <i class="info-i">i</i></h2>'
        f'{lane_note}'
        '<div class="prob-cells">' + "".join(cards) + '</div>'
        f'<div class="probbar probability-strip" role="img" aria-label="\u80dc\u5e73\u8d1f\u6982\u7387\uff1a{aria_label}">'
        + "".join(segments)
        + '</div><div class="prob-caption">\u8d5b\u524d\u6a21\u578b\u6982\u7387 \u00b7 \u6700\u5927\u9879\u53ea\u662f\u76f8\u5bf9\u5360\u4f18</div></article>'
    )


def _score_serving_context(contract: dict[str, Any]) -> dict[str, str]:
    quality = contract.get("prediction_quality_health")
    if isinstance(quality, dict):
        return exact_score_serving_presentation(quality)
    return exact_score_serving_presentation(None)


def _exact_quality_warning(serving_state: str) -> str:
    if serving_state == "NORMAL":
        return ""
    message = (
        "\u6bd4\u5206\u6982\u7387\u8d28\u91cf\u5f85\u786e\u8ba4"
        if serving_state == "UNVERIFIED"
        else "\u6bd4\u5206\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf"
    )
    return (
        f'<p class="quality-warning exact-quality-warning" '
        f'data-exact-warning-state="{html.escape(serving_state, quote=True)}">{message}</p>'
    )


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


def _exact_distribution_contract(contract: dict[str, Any]) -> dict[str, Any] | None:
    item = _formal_market_item(_formal_markets(contract), "exact_score")
    exact_contract = item.get("contract") if _formal_status(item) == "AVAILABLE" else None
    return exact_contract if isinstance(exact_contract, dict) else None


def _total_goal_distribution(contract: dict[str, Any]) -> list[tuple[str, float]]:
    exact_contract = _exact_distribution_contract(contract)
    cells = exact_contract.get("cells") if isinstance(exact_contract, dict) else None
    if not isinstance(cells, list):
        return []
    buckets: dict[str, float] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        try:
            total_goals = int(cell.get("home_goals")) + int(cell.get("away_goals"))
        except (TypeError, ValueError):
            continue
        probability = _percent_number(cell.get("probability"))
        if probability is None:
            continue
        bucket = str(total_goals) if total_goals <= 3 else "4+"
        buckets[bucket] = buckets.get(bucket, 0.0) + probability
    order = ["0", "1", "2", "3", "4+"]
    return [(bucket, buckets[bucket]) for bucket in order if bucket in buckets]


def _render_goals(contract: dict[str, Any]) -> str:
    rows = _total_goal_distribution(contract)
    source_copy = "\u7531\u5f53\u524d\u6bd4\u5206\u5206\u5e03\u6c47\u603b"
    title_copy = "\u603b\u8fdb\u7403\u5206\u5e03"
    if not rows:
        return (
            '<article class="panel supporting-panel goals-panel lane-unavailable" id="goals" '
            f'data-goals-source="exact-score"><h2>{title_copy} <i class="info-i">i</i></h2>'
            f'<p>{source_copy}</p><p>\u5f53\u524d\u6ca1\u6709\u53ef\u6838\u9a8c\u7684 Exact \u6bd4\u5206\u5206\u5e03\uff0c\u4e0d\u8865\u5199\u603b\u8fdb\u7403\u6982\u7387\u3002</p></article>'
        )
    top = max(rows, key=lambda item: item[1])
    top_probability = top[1] or 0.0
    bars = []
    for bucket, number in rows:
        height = number / top_probability * 100 if top_probability else 0.0
        bars.append(
            f'<div class="bar-item" data-goals="{html.escape(bucket, quote=True)}">'
            f'<div class="bar-value">{_percent(number)}</div>'
            f'<div class="bar-col"><span style="height:{height:.1f}%"></span></div>'
            f'<div class="bar-label">{html.escape(bucket)}</div></div>'
        )
    return (
        '<article class="panel supporting-panel goals-panel" id="goals" data-goals-source="exact-score">'
        f'<h2>{title_copy} <i class="info-i">i</i></h2>'
        f'<div class="bars">{"".join(bars)}</div>'
        f'<div class="subtle-note">\u8f85\u52a9\u89c2\u5bdf \u00b7 {source_copy}\uff0c\u4e0d\u7b49\u540c\u4e8e\u72ec\u7acb\u6b63\u5f0f\u73a9\u6cd5\u3002</div>'
        '</article>'
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
    limit: int = 3,
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
        '<div class="exact-compact-heading"><h3>\u6700\u53ef\u80fd\u6bd4\u5206\uff08\u524d3\uff09</h3><span>\u524d 3 \u4e2a\u5df2\u8bb0\u5f55\u6bd4\u5206</span></div>'
        '<div class="exact-compact-list">'
        + "".join(rows)
        + '</div>'
        f'<div class="exact-compact-remainder"><span>\u672a\u5217\u51fa\u6bd4\u5206\u5408\u8ba1</span>'
        f'<strong>{_percent(remainder)}</strong></div>'
        '<p class="exact-compact-note">\u8be5\u5408\u8ba1\u6765\u81ea\u5df2\u8bb0\u5f55\u7684\u6bd4\u5206\u5206\u5e03\uff1b\u4e0d\u8865\u5199\u7f3a\u5931\u6bd4\u5206\u3002</p>'
        '</div>'
    )

def _render_exact_formal_market(item: dict[str, Any], *, serving_state: str = "NORMAL") -> str:
    contract = item.get("contract") if isinstance(item.get("contract"), dict) else None
    status = _formal_status(item)
    if status != "AVAILABLE" or contract is None:
        return (
            '<article class="panel exact-panel lane-unavailable" id="score-distribution" '
            f'data-exact-state="UNAVAILABLE" data-exact-status="{html.escape(status, quote=True)}">'
            '<div class="score-title-row"><h2>\u6bd4\u5206\u6982\u7387</h2><small>\u5f53\u524d\u6ca1\u6709\u53ef\u6838\u9a8c\u7684\u5b8c\u6574\u6bd4\u5206\u6982\u7387</small></div>'
            + _exact_quality_warning(serving_state)
            + '<p>\u6bd4\u5206\u6982\u7387\u6682\u4e0d\u53ef\u7528\uff1b\u672a\u8bb0\u5f55\u7684\u5206\u5e03\u4e0d\u8865\u5199\u3002</p></article>'
        )
    cells = contract.get("cells") if isinstance(contract.get("cells"), list) else []
    by_score = {
        (cell.get("home_goals"), cell.get("away_goals")): cell
        for cell in cells
        if isinstance(cell, dict)
    }
    max_goals = EXACT_DISTRIBUTION_MAX_GOALS

    def bucket(value: Any) -> str:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return ""
        return str(number) if number < 4 else "4+"

    signature_buckets = ("0", "1", "2", "3", "4+")
    signature_values: dict[tuple[str, str], float] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        home_bucket = bucket(cell.get("home_goals"))
        away_bucket = bucket(cell.get("away_goals"))
        probability = _percent_number(cell.get("probability"))
        if home_bucket not in signature_buckets or away_bucket not in signature_buckets or probability is None:
            continue
        key = (home_bucket, away_bucket)
        signature_values[key] = math.fsum((signature_values.get(key, 0.0), probability))
    signature_max = max(signature_values.values(), default=0.0)
    signature_rank = {
        key: index
        for index, (key, _value) in enumerate(
            sorted(signature_values.items(), key=lambda entry: (-entry[1], entry[0]))
        )
    }

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

    exact_quality_warning = _exact_quality_warning(serving_state)
    signature_headers = "".join(f'<th scope="col">{html.escape(label)}</th>' for label in signature_buckets)
    signature_rows = []
    for home_bucket in signature_buckets:
        signature_cells = []
        for away_bucket in signature_buckets:
            key = (home_bucket, away_bucket)
            probability = signature_values.get(key)
            if probability is None:
                signature_cells.append('<td class="signature-cell">\u2014</td>')
                continue
            rank = signature_rank.get(key, 99)
            highlight = f" hi{rank + 1}" if rank < 3 else ""
            alpha = probability / signature_max if signature_max else 0.0
            signature_cells.append(
                f'<td class="signature-cell{highlight}" data-signature-cell-home="{html.escape(home_bucket, quote=True)}" '
                f'data-signature-cell-away="{html.escape(away_bucket, quote=True)}" '
                f'data-signature-probability="{probability:.6f}" style="--cell-alpha:{alpha:.3f}">{_percent(probability)}</td>'
            )
        signature_rows.append(f'<tr><th scope="row">{html.escape(home_bucket)}</th>{"".join(signature_cells)}</tr>')
    return (
        f'<article class="panel exact-panel" id="score-distribution" data-exact-state="{html.escape(serving_state, quote=True)}" data-exact-status="AVAILABLE">'
        '<div class="score-title-row"><h2>\u6bd4\u5206\u6982\u7387</h2>'
        '<small>\u6bd4\u5206\u6982\u7387\u5206\u5e03</small></div>'
        + exact_quality_warning
        + '<table class="score-grid signature-grid" aria-label="\u6bd4\u5206\u6982\u7387\u7b7e\u540d\u77e9\u9635\uff1b\u884c\u4e3a\u4e3b\u961f\u8fdb\u7403\uff0c\u5217\u4e3a\u5ba2\u961f\u8fdb\u7403">'
        '<caption class="sr-only">\u6bd4\u5206\u6982\u7387\u7b7e\u540d\u77e9\u9635\uff1a\u884c\u4e3a\u4e3b\u961f\u8fdb\u7403 \u00d7 \u5217\u4e3a\u5ba2\u961f\u8fdb\u7403\uff0c4+ \u4e3a\u805a\u5408\u89c6\u56fe</caption>'
        '<thead><tr><th scope="col">\u4e3b\u961f/\u5ba2\u961f</th>'
        + signature_headers
        + '</tr></thead><tbody>'
        + "".join(signature_rows)
        + '</tbody></table>'
        + _render_exact_compact_projection(contract)
        + '<details class="exact-full-disclosure" data-exact-disclosure>'
        '<summary aria-label="\u67e5\u770b\u5b8c\u6574 169 \u683c\u6bd4\u5206\u77e9\u9635">\u67e5\u770b\u5b8c\u6574 169 \u683c\u6bd4\u5206\u77e9\u9635</summary>'
        '<p class="exact-disclosure-cue">\u4e3b\u961f\u8fdb\u7403\u4e3a\u884c\uff0c\u5ba2\u961f\u8fdb\u7403\u4e3a\u5217\uff1b\u79fb\u52a8\u7aef\u5c55\u5f00\u540e\u5728\u77e9\u9635\u533a\u57df\u5185\u6a2a\u5411\u67e5\u770b\u3002</p>'
        '<div class="exact-grid-wrap" role="region" tabindex="0" aria-label="\u6bd4\u5206\u6982\u7387 169 \u683c\u77e9\u9635\uff1b\u884c\u4e3a\u4e3b\u961f\u8fdb\u7403\uff0c\u5217\u4e3a\u5ba2\u961f\u8fdb\u7403">'
        '<table class="exact-grid"><caption class="sr-only">\u6bd4\u5206\u6982\u7387 169 \u683c\uff1a\u4e3b\u961f\u8fdb\u7403 \u00d7 \u5ba2\u961f\u8fdb\u7403</caption><thead><tr><th scope="col">\u4e3b\u961f/\u5ba2\u961f</th>'
        + headers
        + '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div></details>'
        '<p class="exact-grid-caption">\u5b8c\u6574\u652f\u6301\u4fdd\u7559\u5728\u5c55\u5f00\u540e\uff1b\u9996\u5c4f\u4f7f\u7528 0\u20133 + 4+ \u7684\u7b7e\u540d\u77e9\u9635\u5feb\u901f\u9605\u8bfb\u3002</p>'
        '<script>(() => { const disclosures = document.querySelectorAll("[data-exact-disclosure]"); const isMobile = window.matchMedia("(max-width: 560px)").matches; disclosures.forEach((disclosure) => { if (isMobile) disclosure.open = false; }); })();</script>'
        '</article>'
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
            'data-evidence-role="MISSING_OR_UNVERIFIED" '
            f'data-change-awareness-status="{html.escape(status, quote=True)}">'
            '<div class="section-heading"><div><div class="evidence-role">\u7f3a\u5931\u6216\u672a\u786e\u8ba4</div><div class="section-kicker">\u8d5b\u524d\u53d8\u5316</div>'
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
        'data-change-awareness="true" data-evidence-role="MARKET_REACTION" data-change-awareness-status="AVAILABLE" '
        f'data-change-awareness-current-id="{html.escape(str(current.get("prediction_id") or ""), quote=True)}" '
        f'data-change-awareness-previous-id="{html.escape(str(previous.get("prediction_id") or ""), quote=True)}">'
        '<div class="section-heading"><div><div class="evidence-role">\u5e02\u573a\u53d8\u5316</div><div class="section-kicker">\u8d5b\u524d\u53d8\u5316</div>'
        '<h2>\u770b\u6e05\u4e00\u6b21\u53d8\u5316</h2></div>'
        f'<p>{html.escape(timeline or empty_timeline)}</p></div>'
        f'<div class="change-lane-grid">{lanes}</div>'
        '<p class="section-note">\u53ea\u5c55\u793a\u5f53\u524d\u8bb0\u5f55\u95f4\u7684\u53ef\u6bd4\u53d8\u5316\uff1b\u4e0d\u5bf9\u53d8\u5316\u4f5c\u56e0\u679c\u63a8\u65ad\u3002</p></section>'
    )


_EVIDENCE_ROLE_LABELS = {
    "MODEL_INPUT": "\u6a21\u578b\u8f93\u5165",
    "MARKET_REACTION": "\u5e02\u573a\u53d8\u5316",
    "CONTEXT_ONLY": "\u80cc\u666f\u4fe1\u606f",
    "MISSING_OR_UNVERIFIED": "\u7f3a\u5931\u6216\u672a\u786e\u8ba4",
}


def _normalise_evidence_role(value: Any) -> str | None:
    role = str(value or "").strip().upper().replace("-", "_")
    return role if role in _EVIDENCE_ROLE_LABELS else None


def _render_public_form(public_evidence: dict[str, Any], identity: dict[str, Any]) -> str:
    recent_form = public_evidence.get("recent_form")
    if not isinstance(recent_form, dict):
        return ""
    rows = []
    labels = {
        "home": (identity.get("home") or "主队", "主场"),
        "away": (identity.get("away") or "客队", "客场"),
    }
    for side in ("home", "away"):
        values = recent_form.get(side)
        if not isinstance(values, dict):
            continue
        fields = ("matches", "wins", "draws", "losses", "goals_for", "goals_against")
        if any(isinstance(values.get(field), bool) or not isinstance(values.get(field), int) for field in fields):
            continue
        if values["matches"] <= 0 or values["wins"] + values["draws"] + values["losses"] != values["matches"]:
            continue
        team, venue = labels[side]
        rows.append(
            '<div class="form-compare-row" role="row">'
            f'<span role="cell"><strong>{_esc(team)}</strong></span>'
            f'<span role="cell">{_esc(venue)} {values["matches"]}场</span>'
            f'<span role="cell" class="form-record">{values["wins"]}-{values["draws"]}-{values["losses"]}</span>'
            f'<span role="cell">{values["goals_for"]}</span>'
            f'<span role="cell">{values["goals_against"]}</span>'
            '</div>'
        )
    if not rows:
        return ""
    return (
        '<article class="evidence-block evidence-primary" data-evidence-role="MODEL_INPUT" data-public-evidence="recent-form">'
        '<div class="evidence-role">模型输入</div><h3>近期表现</h3>'
        '<div class="form-compare" role="table" aria-label="双方近期主客场表现">'
        '<div class="form-compare-row form-compare-head" role="row">'
        '<span role="columnheader">队伍</span><span role="columnheader">范围</span>'
        '<span role="columnheader">胜-平-负</span><span role="columnheader">进球</span><span role="columnheader">失球</span>'
        '</div>'
        + "".join(rows)
        + '</div><p class="source-line">已有主客场近况记录</p></article>'
    )


def _render_public_context(public_evidence: dict[str, Any], identity: dict[str, Any]) -> str:
    context_rows = []
    coach = public_evidence.get("coach")
    if isinstance(coach, dict):
        coach_names = []
        for side in ("home", "away"):
            name = coach.get(side)
            if name not in (None, ""):
                coach_names.append(f'{_esc(identity.get(side) or ("主队" if side == "home" else "客队"))}：{_esc(name)}')
        if coach_names:
            context_rows.append(
                f'<div class="evidence-fact"><span>教练</span><strong>{" · ".join(coach_names)}</strong></div>'
            )
    referee = public_evidence.get("referee")
    if referee not in (None, ""):
        context_rows.append(f'<div class="evidence-fact"><span>裁判</span><strong>{_esc(referee)}</strong></div>')
    if not context_rows:
        return ""
    return (
        '<article class="evidence-block" data-evidence-role="CONTEXT_ONLY" data-public-evidence="context">'
        '<div class="evidence-role">背景信息</div><h3>教练与裁判</h3>'
        + "".join(context_rows)
        + '</article>'
    )


def _render_form(evidence: dict[str, Any], identity: dict[str, Any] | None = None) -> str:
    identity = identity if isinstance(identity, dict) else {}
    if isinstance(evidence.get("prematch_evidence"), dict):
        return _render_public_form(evidence["prematch_evidence"], identity)
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
    return (
        '<article class="evidence-block" data-evidence-role="MODEL_INPUT">'
        '<div class="evidence-role">\u6a21\u578b\u8f93\u5165</div><h3>\u8fd1\u671f\u8868\u73b0</h3>'
        + "".join(rows)
        + captured_html
        + "</article>"
    )


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


def _role_text_items(value: Any, *, default_role: str | None = None) -> list[tuple[str, str]]:
    values = value if isinstance(value, list) else [value]
    rows: list[tuple[str, str]] = []
    for item in values:
        if isinstance(item, dict):
            role = _normalise_evidence_role(item.get("evidence_role") or item.get("role")) or default_role
            text = item.get("text") or item.get("label") or item.get("summary") or item.get("reason")
        else:
            role = default_role
            text = item
        if role and text not in (None, ""):
            rows.append((role, str(text)))
    return rows


def _render_role_block(role: str, title: str, texts: list[str]) -> str:
    if not texts:
        return ""
    role_label = _EVIDENCE_ROLE_LABELS[role]
    items = "".join(f"<li>{_esc(text)}</li>" for text in texts)
    return (
        f'<article class="evidence-block" data-evidence-role="{role}">'
        f'<div class="evidence-role">{role_label}</div><h3>{_esc(title)}</h3>'
        f'<ul class="support-list">{items}</ul></article>'
    )


def _render_key_takeaways(contract: dict[str, Any], *, exact_state: str = "UNVERIFIED") -> str:
    probabilities = _probabilities(contract)
    takeaways: list[tuple[str, str, str, str, str]] = []
    outcomes = [
        ("\u4e3b\u80dc", _percent_number(probabilities.get("home"))),
        ("\u5e73", _percent_number(probabilities.get("draw"))),
        ("\u5ba2\u80dc", _percent_number(probabilities.get("away"))),
    ]
    outcomes = [(label, value) for label, value in outcomes if value is not None]
    if outcomes:
        label, number = max(outcomes, key=lambda item: item[1])
        takeaways.append(("\u4e3b", "", f"{label}\u76f8\u5bf9\u5360\u4f18", "\u4e09\u79cd\u8d5b\u679c\u4e2d\u6700\u9ad8\uff0c\u4f46\u4ec5\u662f\u76f8\u5bf9\u5360\u4f18\u3002", _percent(number)))
    exact_contract = _exact_distribution_contract(contract)
    if isinstance(exact_contract, dict):
        selected, _, _ = _exact_compact_projection(exact_contract)
        if selected:
            primary = selected[0]
            score = f'{int(primary["home_goals"])}-{int(primary["away_goals"])}'
            takeaways.append(("\u25ce", "orange", "\u6700\u9ad8\u6982\u7387\u6bd4\u5206\u4ecd\u4e0d\u9ad8", f"{score} \u53ea\u662f\u5206\u5e03\u4e2d\u7684\u6700\u5927\u5355\u683c\u3002", _percent(primary.get("probability"))))
    if not takeaways:
        return ""
    items = []
    for icon, tone, title, detail, value in takeaways[:4]:
        tone_class = f" {tone}" if tone else ""
        items.append(
            f'<div class="take-row"><span class="take-icon{tone_class}">{icon}</span>'
            f'<div class="take-copy"><strong>{html.escape(title)}</strong><span>{html.escape(detail)}</span></div>'
            f'<span class="take-val">{html.escape(value or DASH)}</span></div>'
        )
    return (
        '<article class="panel takeaway-panel decision-context" id="decision-context">'
        '<h2>\u5173\u952e\u7ed3\u8bba</h2>'
        f'<div class="take-list">{"".join(items)}</div>'
        '<div class="panel-link"><span>\u67e5\u770b\u5b8c\u6574\u5206\u6790</span><span>\u203a</span></div></article>'
    )

def _render_key_evidence(contract: dict[str, Any]) -> str:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    identity = contract.get("identity") if isinstance(contract.get("identity"), dict) else {}
    blocks = []
    form_html = _render_form(evidence, identity)
    if form_html:
        blocks.append(form_html)
    public_evidence = evidence.get("prematch_evidence")
    if isinstance(public_evidence, dict):
        context_html = _render_public_context(public_evidence, identity)
        if context_html:
            blocks.append(context_html)

    role_sources = (
        ("MARKET_REACTION", ("market_reaction", "market_changes"), "MARKET_REACTION"),
        ("CONTEXT_ONLY", ("context_only", "background", "background_info"), "CONTEXT_ONLY"),
        ("MISSING_OR_UNVERIFIED", ("missing_or_unverified", "missing"), "MISSING_OR_UNVERIFIED"),
    )
    for role, keys, default_role in role_sources:
        items: list[str] = []
        for key in keys:
            for item_role, text in _role_text_items(evidence.get(key), default_role=default_role):
                if item_role == role:
                    items.append(text)
        block = _render_role_block(role, _EVIDENCE_ROLE_LABELS[role], items)
        if block:
            blocks.append(block)

    hero = contract.get("hero") if isinstance(contract.get("hero"), dict) else {}
    explicit_items: dict[str, list[str]] = {role: [] for role in _EVIDENCE_ROLE_LABELS}
    for group in (hero.get("supports"), hero.get("conflicts")):
        for item_role, text in _role_text_items(group):
            explicit_items[item_role].append(text)
    for role, texts in explicit_items.items():
        block = _render_role_block(role, "\u5173\u952e\u8bb0\u5f55", texts)
        if block:
            blocks.append(block)

    source_quality = evidence.get("source_quality") if isinstance(evidence.get("source_quality"), dict) else {}
    missing = source_quality.get("missing")
    missing_items = [text for role, text in _role_text_items(missing, default_role="MISSING_OR_UNVERIFIED") if role == "MISSING_OR_UNVERIFIED"]
    missing_block = _render_role_block("MISSING_OR_UNVERIFIED", _EVIDENCE_ROLE_LABELS["MISSING_OR_UNVERIFIED"], missing_items)
    if missing_block and not any('data-evidence-role="MISSING_OR_UNVERIFIED"' in block for block in blocks):
        blocks.append(missing_block)

    if not blocks:
        return ""
    return (
        '<article class="panel evidence-panel evidence-section" id="evidence">'
        '<div class="evidence-panel-heading"><div class="evidence-role">UNDERSTAND MATCH</div><h2>\u8d5b\u524d\u4f9d\u636e</h2>'
        '<p>\u53ea\u5c55\u793a\u5df2\u660e\u786e\u6807\u6ce8\u89d2\u8272\u7684\u8bc1\u636e</p></div><div class="evidence-grid">'
        + "".join(blocks)
        + "</div></article>"
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
    rows = comparison["rows"]
    scale = max((max(row["model"], row["market"]) for row in rows), default=0.0) or 1.0
    labels_html = "".join(f'<div>{html.escape(row["label"])}</div>' for row in rows)
    bars_html = "".join(
        f'<div class="mini-bars"><span class="m" style="height:{row["model"] / scale * 46:.1f}px"></span>'
        f'<span class="k" style="height:{row["market"] / scale * 46:.1f}px"></span></div>'
        for row in rows
    )
    delta_html = "".join(
        f'<div class="delta {"pos" if row["model"] >= row["market"] else "neg"}">'
        f'{"+" if row["model"] >= row["market"] else ""}{(row["model"] - row["market"]) * 100:.1f}pp</div>'
        for row in rows
    )
    delta_text = "\uff1b".join(
        f'{row["label"]} {"+" if row["model"] >= row["market"] else ""}{(row["model"] - row["market"]) * 100:.1f} \u4e2a\u767e\u5206\u70b9'
        for row in rows
    )
    columns = f' style="grid-template-columns:66px repeat({len(rows)},minmax(0,1fr))"'
    return (
        '<article class="panel supporting-panel market-panel" id="market">'
        '<h2>\u6a21\u578b vs \u5e02\u573a\uff08\u80dc / \u5e73 / \u8d1f\uff09</h2>'
        f'<div class="compare-head"><span>\u6a21\u578b</span><span>{market_label}</span></div>'
        f'<div class="compare-grid"{columns}><div></div>{labels_html}<div></div>{bars_html}<div></div>{delta_html}</div>'
        f'<div class="subtle-note">\u5dee\u5f02\u8868\u793a\u6a21\u578b\u76f8\u5bf9\u5e02\u573a\u7684\u504f\u79bb\uff1a{html.escape(delta_text)}\u3002\u4e0d\u4ee3\u8868\u597d\u574f\u3002</div>'
        '</article>'
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
    recorded_at = timestamps.get("prediction_frozen_at") or timestamps.get("freeze_created_at")
    recorded_text = _format_datetime(recorded_at, include_date=True) if recorded_at else "\u5df2\u4fdd\u5b58"
    references = _source_items(contract)
    source_text = " \u00b7 ".join(references[:2]) if references else "\u5f53\u524d\u53ef\u7528\u7684\u8d5b\u524d\u8bb0\u5f55"
    exact_state_code = _score_serving_context(contract).get("state") or "UNVERIFIED"
    exact_state = {
        "NORMAL": "\u53ef\u7528",
        "CAUTION": "\u4ec5\u4f9b\u89c2\u5bdf",
        "DEGRADED": "\u4ec5\u4f9b\u89c2\u5bdf",
        "UNVERIFIED": "\u5f85\u786e\u8ba4",
    }.get(exact_state_code, "\u5f85\u786e\u8ba4")
    items = [
        ("\u25f7", "\u8d5b\u524d\u8bb0\u5f55", f"{recorded_text} \u00b7 \u8d5b\u540e\u4e0d\u4fee\u6539"),
        ("\u25a3", "\u6570\u636e\u6765\u6e90", source_text),
        ("\u25f7", "\u6982\u7387\u53e3\u5f84", f"\u6bd4\u5206\u5c42{exact_state}"),
        ("\u25a4", "\u65b9\u6cd5\u8bf4\u660e", "\u6280\u672f\u7ec6\u8282\u4e0b\u6c89"),
        ("\u2713", "\u8d5b\u540e\u9a8c\u8bc1", "90\u5206\u949f + \u4f24\u505c\u8865\u65f6\u540c\u53e3\u5f84\u4fdd\u7559"),
    ]
    trust_items = "".join(
        f'<div class="trust-item"><span class="trust-ico">{html.escape(icon)}</span><div><strong>{html.escape(title)}</strong><span>{html.escape(text)}</span></div></div>'
        for icon, title, text in items
    )
    technical = _render_technical_details(contract)
    return f'<section class="trust-strip detail-trust" id="data-method">{trust_items}</section>{technical}'

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
        f'<div><span>\u8d5b\u524d\u80dc / \u5e73 / \u8d1f\u65b9\u5411</span><strong>{value("predicted_direction")}</strong></div>'
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
        f'<div class="verification-row"><span>\u80dc / \u5e73 / \u8d1f\u65b9\u5411</span><strong>{_esc(comparison["direction_status"])}</strong><em>\u8d5b\u524d\u5224\u65ad {_esc(comparison["predicted_direction"] or placeholder)} \u00b7 \u5b9e\u9645 {_esc(comparison["actual_direction"] or placeholder)}</em></div>',
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


DETAIL_CSS = r"""
.detail-page .content { padding-top: 12px; }
.detail-page .topbar { color: var(--ink); }
.detail-page .crumbs .back { text-decoration: none; }
.detail-page .crumbs strong { font-size: var(--type-support); }
.detail-page .utility strong,
.detail-page .utility a { color: var(--ink); font-size: var(--type-support); }
.detail-page .hero { grid-template-columns: minmax(0,1fr) 150px minmax(0,1fr); min-height: 122px; column-gap: 18px; margin-top: 0; padding: 17px 24px; }
.detail-page .hero > .team { justify-content: flex-end; gap: 12px; }
.detail-page .hero > .team.right { justify-content: flex-start; }
.detail-page .hero .team-badge { flex-basis: 62px; width: 62px; height: 62px; }
.detail-page .hero .team-badge[data-crest-kind="fallback"] { border-radius: 10px; }
.detail-page .hero .team h1 { font-size: var(--type-display); }
.detail-page .kick { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.detail-page .hero-vs { color: var(--orange); font-size: var(--type-meta); letter-spacing: .16em; }
.detail-page .kick strong { font-size: calc(24px * var(--ui-text-scale)); }
.detail-page .team-copy { min-width: 0; }
.detail-page .team h1 { overflow-wrap: anywhere; }
.detail-page .team-meta:empty { display: none; }
.detail-page .tabs { margin-bottom: 0; }
.detail-page .quality-warning,
.detail-page .pilot-note { margin: 10px 0 0; padding: 9px 12px; border-left: 2px solid var(--warning); background: var(--warning-soft); color: var(--warning); font-size: var(--type-support); }
.detail-page .quality-warning strong { color: var(--ink); }
.detail-page .quality-warning span { margin-left: 7px; color: var(--muted); }
.detail-page .pilot-note { border-left-color: var(--line-2); background: transparent; color: var(--muted); }
.detail-page .primary-grid { grid-template-columns: minmax(230px,.88fr) minmax(360px,1.3fr) minmax(245px,.9fr); align-items: start; gap: 10px; margin-top: 10px; }
.detail-page .supporting-grid { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px; margin-top: 9px; }
.detail-page .supporting-grid > .panel { flex: 1 1 320px; min-height: 0; }
.detail-page .supporting-grid > .panel:only-child { flex: 1 1 100%; width: 100%; display: grid; grid-template-columns: minmax(130px,.7fr) minmax(260px,1.2fr) minmax(160px,.8fr); align-items: center; gap: 14px; }
.detail-page .supporting-grid > .panel:only-child .bars { width: min(100%, 520px); justify-self: center; }
.detail-page .primary-grid > .panel { min-height: 0; }
.detail-page .exact-panel { border-top: 2px solid #6FA879; }
.detail-page .takeaway-panel { border-top: 2px solid var(--line-2); }
.detail-page .probability-section { overflow: hidden; }
.detail-page .probability-section h2 { margin-bottom: 11px; }
.detail-page .probability-section .prob-cells { border: 1px solid var(--line); border-radius: 8px; background: var(--line); gap: 1px; }
.detail-page .probability-section .probability-card { min-width: 0; padding: 11px 9px 10px; background: var(--card); text-align: center; }
.detail-page .probability-section .probability-card.probability-highest { background: #fffaf6; }
.detail-page .probability-section .probability-label,
.detail-page .probability-section .probability-card strong,
.detail-page .probability-section .probability-card small { display: block; }
.detail-page .probability-section .probability-label { font-size: var(--type-meta); }
.detail-page .probability-section .probability-card strong { margin-top: 8px; font-size: calc(24px * var(--ui-text-scale)); line-height: 1; font-weight: 760; font-variant-numeric: tabular-nums; }
.detail-page .probability-section .probability-card small { min-height: 14px; margin-top: 7px; color: var(--muted); font-size: var(--type-meta); }
.detail-page .probability-strip { height: 8px; margin-top: 14px; }
.detail-page .probability-strip span { display: block; min-width: 2px; height: 100%; }
.detail-page .lane-status-note { margin: 0 0 9px; color: var(--warning); font-size: var(--type-meta); }
.detail-page .lane-unavailable p { margin: 8px 0 0; color: var(--muted); font-size: var(--type-support); }
.detail-page .exact-panel { overflow: hidden; }
.detail-page .exact-panel .score-title-row { margin-bottom: 8px; }
.detail-page .exact-panel .score-title-row h2 { margin-bottom: 0; }
.detail-page .exact-panel .score-title-row small { max-width: 48%; color: var(--muted); font-size: var(--type-meta); text-align: right; }
.detail-page .signature-grid { table-layout: fixed; border-spacing: 2px; font-size: var(--matrix-type); }
.detail-page .signature-grid th { padding: 2px; color: var(--muted); font-weight: 700; }
.detail-page .signature-grid td { padding: 6px 2px; border-radius: 2px; background: #f1f6f0; font-variant-numeric: tabular-nums; }
.detail-page .signature-grid td[data-signature-probability] { --cell-alpha: 0; }
@supports (background: color-mix(in srgb, white, black)) {
  .detail-page .signature-grid td[data-signature-probability] { background: color-mix(in srgb, #2f8d49 calc(12% + var(--cell-alpha) * 78%), #eef5ed); }
}
.detail-page .signature-grid td.hi1 { background: #92bc93; font-weight: 760; }
.detail-page .signature-grid td.hi2 { background: #b7d0b7; }
.detail-page .signature-grid td.hi3 { background: #d4e3d2; }
.detail-page .exact-compact { display: block; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line); }
.detail-page .exact-compact-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.detail-page .exact-compact-heading h3 { margin: 0; font-size: var(--type-support); }
.detail-page .exact-compact-heading span { color: var(--muted); font-size: var(--type-meta); }
.detail-page .exact-compact-list { display: grid; gap: 1px; }
.detail-page .exact-compact-row { display: grid; grid-template-columns: 76px minmax(0,1fr) 60px; gap: 8px; align-items: center; min-height: 32px; border-top: 1px solid var(--line); }
.detail-page .exact-compact-row:first-child { border-top: 0; }
.detail-page .exact-compact-score { font-size: var(--type-support); font-variant-numeric: tabular-nums; white-space: nowrap; }
.detail-page .exact-compact-score b { margin-right: 4px; color: var(--muted); font-size: var(--type-meta); font-weight: 650; }
.detail-page .exact-compact-bar { height: 6px; overflow: hidden; background: var(--line); }
.detail-page .exact-compact-bar > span { display: block; height: 100%; background: var(--orange); }
.detail-page .exact-compact-probability { text-align: right; font-size: var(--type-support); font-variant-numeric: tabular-nums; }
.detail-page .exact-compact-remainder { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line); font-size: var(--type-meta); }
.detail-page .exact-compact-remainder strong { font-size: var(--type-support); font-variant-numeric: tabular-nums; }
.detail-page .exact-compact-note { margin: 7px 0 0; color: var(--muted); font-size: var(--type-meta); }
.detail-page .exact-full-disclosure { margin-top: 8px; border-top: 1px solid var(--line); }
.detail-page .exact-full-disclosure > summary { display: flex; align-items: center; min-height: 44px; padding: 8px 0; cursor: pointer; color: var(--ink); font-size: var(--type-support); font-weight: 700; }
.detail-page .exact-full-disclosure:not([open]) > :not(summary) { display: none; }
.detail-page .exact-disclosure-cue { margin: 0 0 8px; color: var(--muted); font-size: var(--type-meta); }
.detail-page .exact-grid-wrap { max-width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; }
.detail-page .exact-grid { width: 100%; min-width: 720px; table-layout: fixed; border-collapse: collapse; font-size: var(--matrix-type); font-variant-numeric: tabular-nums; }
.detail-page .exact-grid th,
.detail-page .exact-grid td { width: 7.14%; padding: 5px 2px; border: 1px solid var(--line); text-align: center; white-space: nowrap; }
.detail-page .exact-grid th { background: var(--card-soft); color: var(--muted); font-weight: 650; }
.detail-page .exact-grid td { --cell-alpha: 0; background: #f1f6f0; }
@supports (background: color-mix(in srgb, white, black)) {
  .detail-page .exact-grid td[data-probability] { background: color-mix(in srgb, #2f8d49 calc(12% + var(--cell-alpha) * 78%), #eef5ed); }
}
.detail-page .exact-grid-caption { margin: 8px 0 0; color: var(--muted); font-size: var(--type-meta); }
.detail-page .top3line { margin-top: 8px; padding-top: 7px; font-size: var(--type-support); }
.detail-page .supporting-panel { min-height: 0; }
.detail-page .supporting-panel h2 { margin-bottom: 11px; }
.detail-page .goals-panel .bars { height: 86px; }
.detail-page .goals-panel .bar-col { height: 50px; }
.detail-page .goals-panel .bar-col span { background: var(--blue); }
.detail-page .goals-panel .subtle-note { min-height: 0; margin-top: 4px; }
.detail-page .market-panel .subtle-note { min-height: 22px; }
.detail-page .market-panel .compare-head { margin-bottom: 6px; }
.detail-page .market-panel .compare-grid { min-height: 85px; }
.detail-page .evidence-panel { overflow: hidden; }
.detail-page .evidence-panel-heading { margin-bottom: 7px; }
.detail-page .evidence-panel-heading .evidence-role { margin-bottom: 3px; }
.detail-page .evidence-panel-heading h2 { margin-bottom: 3px; }
.detail-page .evidence-panel-heading p { margin: 0; color: var(--muted); font-size: var(--type-meta); }
.detail-page .evidence-grid { display: grid; grid-template-columns: 1fr; gap: 0; }
.detail-page .evidence-block { min-width: 0; padding: 8px 0; border: 0; border-top: 1px solid var(--line); background: transparent; }
.detail-page .evidence-block:first-child { border-top: 0; }
.detail-page .evidence-role { margin-bottom: 4px; color: var(--orange); font-size: var(--type-label); font-weight: 750; letter-spacing: .08em; }
.detail-page .evidence-block h3 { margin: 0 0 6px; font-size: var(--type-support); }
.detail-page .evidence-fact { padding: 5px 0; font-size: var(--type-support); }
.detail-page .evidence-fact strong { max-width: 70%; font-size: var(--type-support); }
.detail-page .form-compare { display: grid; margin-top: 4px; border: 1px solid var(--line); font-size: var(--type-meta); font-variant-numeric: tabular-nums; }
.detail-page .form-compare-row { display: grid; grid-template-columns: minmax(82px,1.15fr) minmax(54px,.8fr) minmax(64px,.9fr) minmax(46px,.65fr) minmax(46px,.65fr); gap: 6px; align-items: center; min-width: 0; padding: 7px 8px; border-top: 1px solid var(--line); }
.detail-page .form-compare-row:first-child { border-top: 0; }
.detail-page .form-compare-row > span { min-width: 0; overflow-wrap: anywhere; }
.detail-page .form-compare-head { color: var(--muted); background: var(--card-soft); font-size: var(--type-meta); }
.detail-page .form-compare-row:not(.form-compare-head) strong { color: var(--ink); font-size: var(--type-support); }
.detail-page .form-record { font-weight: 750; }
.detail-page .source-line { margin: 5px 0 0; color: var(--muted); font-size: var(--type-meta); }
.detail-page .support-list { margin: 3px 0 0; padding-left: 14px; font-size: var(--type-support); }
.detail-page .support-list li { margin: 3px 0; }
.detail-page .detail-section,
.detail-page .result-panel,
.detail-page .status-panel { margin-top: 10px; padding: 13px 0 14px; border-top: 1px solid var(--line-2); border-bottom: 1px solid var(--line); background: transparent; }
.detail-page .section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.detail-page .section-heading h2 { margin: 3px 0 0; font-size: var(--type-section); letter-spacing: -.025em; }
.detail-page .section-heading p { max-width: 48%; margin: 0; color: var(--muted); font-size: var(--type-support); text-align: right; }
.detail-page .section-kicker { color: var(--quiet); font-size: var(--type-label); font-weight: 700; letter-spacing: .12em; }
.detail-page .change-awareness-section { margin-top: 10px; }
.detail-page .change-lane-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 8px; }
.detail-page .change-lane { min-width: 0; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); }
.detail-page .change-lane-wide { grid-column: 1 / -1; }
.detail-page .change-lane h3 { margin: 0 0 7px; font-size: var(--type-support); }
.detail-page .change-rows { display: grid; }
.detail-page .change-row { display: grid; grid-template-columns: 76px minmax(90px,1fr) 88px; gap: 8px; align-items: center; min-height: 40px; border-top: 1px solid var(--line); font-size: var(--type-support); font-variant-numeric: tabular-nums; }
.detail-page .change-row:first-child { border-top: 0; }
.detail-page .change-before-now { display: flex; align-items: baseline; gap: 5px; }
.detail-page .change-before-now > span { color: var(--muted); }
.detail-page .change-delta { color: var(--muted); text-align: right; }
.detail-page .change-lane-note,
.detail-page .change-empty,
.detail-page .change-unavailable-copy,
.detail-page .section-note { margin: 8px 0 0; color: var(--muted); font-size: var(--type-meta); }
.detail-page .deeper-details { margin-top: 10px; }
.detail-page .result-panel { margin-top: 10px; }
.detail-page .result-panel h2 { margin: 3px 0 0; font-size: var(--type-section); }
.detail-page .actual-score { margin-top: 6px; font-size: 34px; font-weight: 800; line-height: 1; letter-spacing: -.06em; font-variant-numeric: tabular-nums; }
.detail-page .actual-meta { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-top: 8px; color: var(--muted); font-size: var(--type-support); }
.detail-page .actual-meta strong { color: var(--verified); }
.detail-page .completed-facts { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 1px; margin-top: 13px; border: 1px solid var(--line); background: var(--line); }
.detail-page .completed-facts > div { min-width: 0; padding: 8px; background: var(--card); }
.detail-page .completed-facts span,
.detail-page .completed-facts strong { display: block; }
.detail-page .completed-facts span { color: var(--muted); font-size: var(--type-meta); }
.detail-page .completed-facts strong { margin-top: 3px; font-size: var(--type-support); overflow-wrap: anywhere; }
.detail-page .verification-section { margin-top: 8px; }
.detail-page .verification-list { display: grid; }
.detail-page .verification-row { display: grid; grid-template-columns: 74px minmax(64px,auto) minmax(0,1fr); gap: 9px; align-items: baseline; padding: 7px 0; border-top: 1px solid var(--line); font-size: var(--type-support); }
.detail-page .verification-row > span,
.detail-page .verification-row > em { color: var(--muted); }
.detail-page .verification-row > em { font-style: normal; text-align: right; }
.detail-page .status-panel { display: flex; gap: 12px; align-items: flex-start; padding: 15px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.detail-page .status-mark { display: grid; place-items: center; flex: 0 0 26px; width: 26px; height: 26px; border-radius: 50%; background: var(--warning-soft); color: var(--warning); font-weight: 800; }
.detail-page .status-panel h2 { margin: 3px 0 5px; font-size: var(--type-section); }
.detail-page .status-panel p { margin: 0; color: var(--muted); font-size: var(--type-support); }
.detail-page .detail-trust { margin-top: 10px; }
.detail-page .technical-details { margin-top: 8px; }
.detail-page .technical-details summary { padding: 8px 0; cursor: pointer; color: var(--ink); font-size: var(--type-support); }
.detail-page .technical-list { border-top: 1px solid var(--line); }
.detail-page .technical-row { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.3fr); gap: 9px; padding: 6px 0; border-bottom: 1px solid var(--line); font-size: var(--type-meta); }
.detail-page .technical-row span { color: var(--muted); }
.detail-page .technical-row code { overflow-wrap: anywhere; text-align: right; font: inherit; }
.detail-page .closed-beta-notice { margin: 10px 14px 0; }
.detail-page .detail-footer { display: flex; justify-content: space-between; gap: 14px; margin: 0 14px; padding: 12px 0 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: var(--type-meta); }
.detail-page .detail-footer span { min-width: 0; }
.detail-page .detail-principles { margin-left: 14px; margin-right: 14px; }
.detail-page .detail-copyright { padding-left: 14px; padding-right: 14px; }

@media (max-width: 820px) {
  .detail-page .content { padding: 0 14px 71px; }
  .detail-page .hero { grid-template-columns: minmax(0,1fr) 72px minmax(0,1fr); min-height: 100px; column-gap: 5px; padding: 10px 0; }
  .detail-page .hero > .team { gap: 6px; }
  .detail-page .hero .team-badge { flex-basis: 42px; width: 42px; height: 42px; }
  .detail-page .hero .team h1 { font-size: var(--type-body); font-weight: 800; line-height: 1.15; }
  .detail-page .hero-vs { font-size: var(--type-meta); }
  .detail-page .kick { gap: 1px; }
  .detail-page .kick small { font-size: var(--type-meta); }
  .detail-page .kick strong { font-size: calc(17px * var(--ui-text-scale)); font-weight: 700; }
  .detail-page .kick span { max-width: 72px; font-size: var(--type-meta); line-height: 1.2; text-align: center; }
  .detail-page .quality-warning,
  .detail-page .pilot-note { margin-top: 8px; }
  .detail-page .primary-grid { margin-top: 0; }
  .detail-page .supporting-grid { display: block; margin-top: 0; }
  .detail-page .supporting-grid > .panel,
  .detail-page .supporting-grid > .panel:only-child { width: auto; flex: none; display: block; }
  .detail-page .panel { padding: 14px 0; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; box-shadow: none; }
  .detail-page .probability-section .probability-card { padding: 7px 4px 8px; }
  .detail-page .probability-section .probability-card strong { font-size: calc(19px * var(--ui-text-scale)); }
  .detail-page .probability-section .probability-card small { display: none; }
  .detail-page .probability-strip { height: 6px; margin-top: 11px; }
  .detail-page .prob-caption { display: none; }
  .detail-page .exact-panel .score-title-row small { display: none; }
  .detail-page .signature-grid { font-size: calc(10px * var(--ui-text-scale)); border-spacing: 1px; }
  .detail-page .signature-grid td { padding: 4px 1px; }
  .detail-page .exact-compact { display: block; margin-top: 10px; }
  .detail-page .exact-compact-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 7px; }
  .detail-page .exact-compact-heading h3 { margin: 0; font-size: var(--type-support); }
  .detail-page .exact-compact-heading span { color: var(--muted); font-size: var(--type-meta); }
  .detail-page .exact-compact-list { display: grid; gap: 1px; }
  .detail-page .exact-compact-row { display: grid; grid-template-columns: 60px minmax(0,1fr) 53px; gap: 7px; align-items: center; min-height: 40px; border-top: 1px solid var(--line); }
  .detail-page .exact-compact-row:first-child { border-top: 0; }
  .detail-page .exact-compact-score { font-size: var(--type-support); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .detail-page .exact-compact-score b { margin-right: 4px; color: var(--muted); font-size: var(--type-meta); font-weight: 650; }
  .detail-page .exact-compact-bar { height: 5px; overflow: hidden; background: var(--line); }
  .detail-page .exact-compact-bar > span { display: block; height: 100%; background: var(--orange); }
  .detail-page .exact-compact-probability { text-align: right; font-size: var(--type-support); font-variant-numeric: tabular-nums; }
  .detail-page .exact-compact-remainder { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--line); font-size: var(--type-meta); }
  .detail-page .exact-compact-remainder strong { font-size: var(--type-support); font-variant-numeric: tabular-nums; }
  .detail-page .exact-compact-note { margin: 6px 0 0; color: var(--muted); font-size: var(--type-meta); }
  .detail-page .exact-full-disclosure { margin-top: 8px; }
  .detail-page .exact-full-disclosure > summary { min-height: 44px; padding: 9px 0 6px; }
  .detail-page .exact-grid-wrap { overflow-x: auto; }
  .detail-page .exact-grid { min-width: 720px; font-size: calc(9px * var(--ui-text-scale)); }
  .detail-page .exact-grid th,
  .detail-page .exact-grid td { padding: 5px 2px; }
  .detail-page .supporting-panel { min-height: 0; }
  .detail-page .bars { height: 100px; }
  .detail-page .bar-col { height: 56px; }
  .detail-page .change-lane-grid,
  .detail-page .evidence-grid { grid-template-columns: 1fr; }
  .detail-page .form-compare-row { grid-template-columns: minmax(60px,1.05fr) minmax(44px,.7fr) minmax(54px,.85fr) repeat(2,minmax(40px,.6fr)); gap: 4px; padding: 7px 5px; }
  .detail-page .change-lane-wide { grid-column: auto; }
  .detail-page .change-row { grid-template-columns: 62px minmax(80px,1fr) 74px; gap: 6px; min-height: 40px; }
  .detail-page .section-heading { display: block; margin-bottom: 9px; }
  .detail-page .section-heading p { max-width: none; margin-top: 4px; text-align: left; }
  .detail-page .completed-facts { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .detail-page .verification-row { grid-template-columns: 64px minmax(59px,auto) minmax(0,1fr); gap: 7px; }
  .detail-page .verification-row > em { text-align: right; }
  .detail-page .actual-score { font-size: 32px; }
  .detail-page .detail-trust { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); margin-top: 10px; }
  .detail-page .detail-trust .trust-item { min-width: 0; padding: 10px 8px; border-right: 0; border-bottom: 1px solid var(--line); }
  .detail-page .detail-trust .trust-item:nth-child(odd) { border-right: 1px solid var(--line); }
  .detail-page .detail-trust .trust-item strong { font-size: var(--type-meta); }
  .detail-page .detail-trust .trust-item span { font-size: var(--type-meta); }
  .detail-page .detail-principles,
  .detail-page .detail-copyright,
  .detail-page .detail-footer { display: none; }
  .detail-page .closed-beta-notice { margin: 8px 0 0; }
}

@media (max-width: 360px) {
  .detail-page .content { padding-left: 12px; padding-right: 12px; }
  .detail-page .hero { grid-template-columns: minmax(0,1fr) 64px minmax(0,1fr); min-height: 96px; }
  .detail-page .hero .team-badge { flex-basis: 38px; width: 38px; height: 38px; }
  .detail-page .hero .team h1 { font-size: var(--type-body); }
  .detail-page .kick strong { font-size: calc(16px * var(--ui-text-scale)); }
  .detail-page .probability-section .probability-card strong { font-size: calc(18px * var(--ui-text-scale)); }
  .detail-page .signature-grid { font-size: calc(10px * var(--ui-text-scale)); }
  .detail-page .exact-compact-row { grid-template-columns: 55px minmax(0,1fr) 51px; gap: 5px; }
  .detail-page .change-row { grid-template-columns: 55px minmax(70px,1fr) 68px; gap: 5px; }
  .detail-page .verification-row { grid-template-columns: 58px minmax(55px,auto) minmax(0,1fr); gap: 5px; font-size: var(--type-support); }
}
"""



def render_match_detail(contract: dict[str, Any]) -> str:
    identity = contract.get("identity") or {}
    status = contract.get("status") or {}
    status_code = _status_code(contract)
    serving = status_code in {"FROZEN", "COMPLETED"}
    result = contract.get("result") if isinstance(contract.get("result"), dict) else {}
    serving_context = _score_serving_context(contract)
    # Exact-state caution is rendered once inside the affected score lane.
    quality_warning = ""
    pilot_note = (
        '<div class="pilot-note">\u5f53\u524d\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf</div>'
        if serving and (contract.get("governance") or {}).get("pilot_excluded")
        else ""
    )
    home_value = identity.get("home") or "\u4e3b\u961f"
    away_value = identity.get("away") or "\u5ba2\u961f"
    home = _esc(home_value)
    away = _esc(away_value)
    home_badge = render_team_badge(
        home_value,
        identity.get("home_crest") or identity.get("home_logo") or identity.get("home_badge"),
        side="home",
        variant="crest",
    )
    away_badge = render_team_badge(
        away_value,
        identity.get("away_crest") or identity.get("away_logo") or identity.get("away_badge"),
        side="away",
        variant="crest",
    )
    kickoff_at = identity.get("kickoff_at") or identity.get("kickoff")
    kickoff_date = _format_datetime(kickoff_at, include_date=True) or "\u65f6\u95f4\u5f85\u5b9a"
    kickoff_time = _format_datetime(kickoff_at) or DASH
    venue = _esc(identity.get("venue") or identity.get("stadium") or "\u8d5b\u524d\u8bb0\u5f55")
    competition = _esc(identity.get("competition"), "\u6bd4\u8d5b")
    match_number = _esc(identity.get("match_num"), "")
    crumb_match = f'<span>{match_number}</span>' if match_number else f'<span>{html.escape(kickoff_date)}</span>'
    home_meta_value = identity.get("home_rank") or identity.get("home_position") or identity.get("home_meta") or ""
    away_meta_value = identity.get("away_rank") or identity.get("away_position") or identity.get("away_meta") or ""
    home_meta = f'<div class="team-meta">{_esc(home_meta_value)}</div>' if home_meta_value else ""
    away_meta = f'<div class="team-meta">{_esc(away_meta_value)}</div>' if away_meta_value else ""
    status_label = _user_status_label(status)
    status_line = "\u5df2\u5b8c\u6210" if status_code == "COMPLETED" else "\u8d5b\u524d\u5df2\u9501\u5b9a" if status_code == "FROZEN" else status_label
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
        primary_html = f'<section class="grid3 primary-grid">{probability_html}{exact_html}{takeaways_html}</section>'
        supporting_html = f'<section class="grid3 second supporting-grid">{goals_html}{market_html}</section>'
        analysis_html = evidence_html + primary_html + supporting_html + change_awareness_html + (trust_html := _render_trust(contract))
    else:
        trust_html = ""
        analysis_html = _render_status_panel(contract)
    utility_html = '<div class="utility"><a href="#beginner-help">\u600e\u4e48\u770b</a></div>'
    beginner_help_html = render_beginner_help()
    market_tab = '<a class="tab" href="#market">\u5e02\u573a</a>' if market_html else ''
    evidence_tab = '<a class="tab" href="#evidence">\u4f9d\u636e</a>' if evidence_html else ''
    tabs_html = (
        '<nav class="tabs" aria-label="\u6bd4\u8d5b\u8be6\u60c5\u5bfc\u822a">'
        '<a class="tab active" href="#conclusion">\u6982\u89c8</a>'
        '<a class="tab" href="#analysis">\u6982\u7387</a>'
        f'{market_tab}{evidence_tab}</nav>'
    )
    closed_beta = render_closed_beta_notice("closed-beta")
    closed_beta_html = f'<div id="closed-beta">{closed_beta}</div>'
    footer_html = (
        '<section class="footer-principles detail-principles"><div class="principle-title">OneShot Principles</div>'
        '<div class="principles">'
        '<div class="principle"><span class="principle-icon">\u2606</span><div><strong>\u6e05\u6670\u4f18\u5148</strong><span>\u5148\u770b\u771f\u6b63\u6539\u53d8\u5224\u65ad\u7684\u5185\u5bb9\u3002</span></div></div>'
        '<div class="principle"><span class="principle-icon">\u25c9</span><div><strong>\u6982\u7387\u8bda\u5b9e</strong><span>\u6700\u9ad8\u4e0d\u7b49\u4e8e\u786e\u5b9a\u3002</span></div></div>'
        '<div class="principle"><span class="principle-icon">\u25c7</span><div><strong>\u72ec\u7acb\u5224\u65ad</strong><span>\u6a21\u578b\u4e0e\u5224\u65ad\u5e76\u5217\u6bd4\u8f83\u3002</span></div></div>'
        '<div class="principle"><span class="principle-icon">\u2713</span><div><strong>\u4e00\u81f4\u9a8c\u8bc1</strong><span>\u8d5b\u524d\u8bb0\u5f55\u8d5b\u540e\u4e0d\u4fee\u6539\u3002</span></div></div>'
        '<div class="principle"><span class="principle-icon">\u25a3</span><div><strong>\u6709\u4e0a\u4e0b\u6587\u7684\u6570\u636e</strong><span>\u6570\u5b57\u5fc5\u987b\u80fd\u89e3\u91ca\u3002</span></div></div>'
        '</div></section>'
        '<div class="copyright detail-copyright"><span>\u00a9 2026 OneShot</span><span>Closed Beta</span><span>\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003</span></div>'
    )
    content_html = f"""
<section class="page detail-page">
<header class="topbar">
  <div class="crumbs"><a class="back" href="../../prediction_dashboard/latest.html" aria-label="\u8fd4\u56de\u4eca\u65e5\u6bd4\u8d5b">\u2190</a><strong>{competition}</strong><span>\u00b7</span>{crumb_match}</div>
  {utility_html}
</header>
<div class="content">
  <section class="hero" id="conclusion" data-matchup="true" aria-label="{home} VS {away}">
    <div class="team matchup-side matchup-home">{home_badge}<div class="team-copy"><h1>{home}</h1>{home_meta}</div></div>
    <div class="kick"><span class="matchup-vs hero-vs" aria-hidden="true">VS</span><small>{html.escape(kickoff_date)}</small><strong>{html.escape(kickoff_time)}</strong><span>{venue} \u00b7 {html.escape(status_line)}</span></div>
    <div class="team right matchup-side matchup-away"><div class="team-copy"><h1>{away}</h1>{away_meta}</div>{away_badge}</div>
  </section>
  {tabs_html}
  {quality_warning}
  {pilot_note}
  {result_html}
  {verification_html}
  <div id="analysis" class="detail-analysis">{analysis_html}</div>
  {beginner_help_html}
</div>
{closed_beta_html}
{footer_html}
<footer class="detail-footer"><span>\u8d5b\u524d\u8bb0\u5f55\u4fdd\u6301\u4e0d\u53d8\uff1b\u8d5b\u540e\u7ed3\u679c\u5355\u72ec\u6838\u9a8c\u3002</span><span>\u9875\u9762\u6570\u636e\u6765\u81ea\u5f53\u524d\u53ef\u7528\u7684\u6bd4\u8d5b\u8bb0\u5f55\u3002</span></footer>
</section>
"""
    return render_public_document(
        title=f"{home_value} vs {away_value} \u00b7 \u6bd4\u8d5b\u8be6\u60c5",
        css=DETAIL_CSS,
        content_html=content_html,
        dashboard_href="../../prediction_dashboard/latest.html",
        history_href="../../prediction_dashboard/latest.html#historical-results",
        sources_href="#data-method" if serving else "../../prediction_dashboard/latest.html#data-method",
        help_href="#beginner-help",
        mobile_label=f"{home_value} vs {away_value}",
        body_class=f"detail-page status-{_status_class(contract)}",
        mobile_variant="detail",
    )



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
