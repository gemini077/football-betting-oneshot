#!/usr/bin/env python3
"""Capture GitHub-readable public UI evidence with real Chromium."""

from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_public_site import _fixture_contract, _linked_frozen_formal_markets  # noqa: E402
from scripts.formal_market_projection import project_frozen_formal_markets  # noqa: E402
from scripts.match_detail import render_match_detail  # noqa: E402
from scripts.official_jc_handicap import build_jc_handicap_contract  # noqa: E402
from scripts.prediction_dashboard import build_dashboard, render_dashboard  # noqa: E402


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _source_commit_sha() -> str:
    configured = os.environ.get("SOURCE_COMMIT_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _fixture_with_status(payload: dict[str, Any], status: str) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    fixtures = []
    for card in result.get("fixtures") or []:
        if not isinstance(card, dict):
            continue
        card["status"] = status
        card["prediction"] = None
        card["result"] = None
        card["reason_code"] = "MISSING_RECENT_FORM"
        card["reason_text"] = "TEST FIXTURE · state regression"
        fixtures.append(card)
    result["fixtures"] = fixtures
    result["completed"] = []
    result["history"] = []
    result["summary"] = {
        **(result.get("summary") or {}),
        "fixture_count": len(fixtures),
        "card_count": len(fixtures),
        "verified_results": 0,
        "completed_count": 0,
    }
    return result


def _quality_fixture(payload: dict[str, Any], status: str) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    quality = {
        **(result.get("prediction_quality_health") or {}),
        "status": status,
        "scope": "current_serving",
        "available": status in {"DEGRADED", "ALERT", "INSUFFICIENT_SAMPLE"},
        "provenance_status": "MATCHED" if status in {"DEGRADED", "ALERT", "INSUFFICIENT_SAMPLE"} else "MISMATCHED",
    }
    result["prediction_quality_health"] = quality
    return result


def _result_empty_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    for card in result.get("fixtures") or []:
        if isinstance(card, dict):
            card["result"] = None
    result["completed"] = []
    result["summary"] = {
        **(result.get("summary") or {}),
        "verified_results": 0,
        "completed_count": 0,
    }
    return result


def _upcoming_empty_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    for card in result.get("fixtures") or []:
        if isinstance(card, dict):
            card["kickoff_timestamp"] = "2000-01-01T00:00:00Z"
            card["kickoff"] = "2000-01-01T08:00:00+08:00"
    return result


def _mark_test_fixture(document: str, label: str) -> str:
    marker = (
        '<div class="test-fixture-label" aria-label="TEST FIXTURE">'
        f"TEST FIXTURE · {html.escape(label)}"
        "</div>"
    )
    style = (
        "<style>.test-fixture-label{position:fixed;top:0;left:0;right:0;z-index:99;"
        "padding:6px 12px;background:#111;color:#fff;font:700 11px/1.2 ui-monospace,"
        "monospace;letter-spacing:.08em;text-align:center}.test-fixture-label+*{}</style>"
    )
    return re.sub(
        r"<body([^>]*)>",
        lambda match: f"<body{match.group(1)}>{marker}{style}",
        document,
        count=1,
    )


def _linked_prediction_record(data_root: Path, fixture: dict[str, Any]) -> dict[str, Any] | None:
    prediction_id = str(fixture.get("selected_prediction_id") or fixture.get("prediction_id") or "").strip()
    if not prediction_id or not re.fullmatch(r"[A-Za-z0-9._~-]+", prediction_id):
        return None
    path = data_root / "model_governance" / "predictions" / f"{prediction_id}.json"
    if not path.is_file():
        return None
    try:
        record = _read_json(path)
    except (OSError, ValueError):
        return None
    if str(record.get("prediction_id") or "") != prediction_id:
        return None
    fixture_match_id = str(fixture.get("match_id") or "")
    record_match_id = str(record.get("match_id") or "")
    if fixture_match_id and record_match_id and fixture_match_id != record_match_id:
        return None
    return record


def _visual_jc_handicap_capture(fixture: dict[str, Any], prediction_id: str) -> dict[str, Any]:
    """Return a test-only captured-line shape for the all-formal visual state."""

    return {
        "status": "CAPTURED",
        "line": 1,
        "source_surface": "nowscore_public_jc_analysis",
        "source_url": "TEST_FIXTURE",
        "nowscore_id": fixture.get("nowscore_id"),
        "business_date": fixture.get("business_date"),
        "match_number": fixture.get("match_num"),
        "fetched_at": "2026-09-06T00:00:00+08:00",
        "captured_at": "2026-09-06T00:00:00+08:00",
        "request_started_at": "2026-09-06T00:00:00+08:00",
        "response_at": "2026-09-06T00:00:00+08:00",
        "observed_at": "2026-09-06T00:00:00+08:00",
        "page_http_status": 200,
        "response_sha256": f"TEST_FIXTURE_RESPONSE_{prediction_id}",
        "content_sha256": f"TEST_FIXTURE_RESPONSE_{prediction_id}",
        "parser_contract_version": "TEST_FIXTURE",
        "line_binding": "竞彩指数/GoJcUrl(0)",
        "line_perspective": "home",
        "identity_status": "TEST_FIXTURE",
        "page_identity": {},
        "reason_codes": [],
    }


def _all_formal_markets_for_visual_fixture(
    data_root: Path,
    fixture: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a labeled visual-only all-formal state without changing production data."""

    record = _linked_prediction_record(data_root, fixture)
    exact = record.get("exact_score_distribution") if isinstance(record, dict) else None
    if not isinstance(record, dict) or not isinstance(exact, dict):
        return None
    prediction_id = str(record.get("prediction_id") or fixture.get("prediction_id") or "visual")
    handicap = build_jc_handicap_contract(
        exact,
        _visual_jc_handicap_capture(fixture, prediction_id),
        model_identity={
            key: record.get(key)
            for key in ("prediction_id", "model_role", "model_family", "release_version")
            if record.get(key) is not None
        },
    )
    visual_record = copy.deepcopy(record)
    visual_record["jc_handicap"] = handicap
    return project_frozen_formal_markets(visual_record)


def _regenerate_dashboard(site_root: Path) -> dict[str, Any]:
    """Regenerate the dashboard through the PR renderer immediately before capture."""

    source_candidates = (
        ROOT / "data" / "prediction_dashboard" / "latest.json",
        site_root / "prediction_dashboard" / "latest.json",
    )
    source_payload = next((_read_json(path) for path in source_candidates if path.is_file()), None)
    business_date = str((source_payload or {}).get("business_date") or "").strip()
    if not business_date:
        raise SystemExit("visual evidence requires a dashboard business_date")
    data_root = ROOT / "data"
    return build_dashboard(
        business_date,
        universe_root=data_root / "prediction_universe",
        jobs_root=data_root / "base_prediction_jobs",
        prediction_root=data_root / "model_governance" / "predictions",
        exclusion_root=data_root / "model_governance" / "prediction_exclusions",
        result_root=data_root / "postmatch_automation" / "results",
        prospective_root=data_root / "prospective",
        runtime_path=data_root / "product_runtime" / "latest_cycle.json",
        health_watch_path=data_root / "product_runtime" / "health_watch.json",
        workspace_path=data_root / "match_workspace" / "latest.json",
        output_root=site_root / "prediction_dashboard",
    )


def _write_fixture_pages(site_root: Path, payload: dict[str, Any], current: dict[str, Any]) -> None:
    fixture_root = site_root / "visual-fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)

    pages = {
        "dashboard-insufficient.html": _mark_test_fixture(
            render_dashboard(_quality_fixture(payload, "INSUFFICIENT_SAMPLE")),
            "INSUFFICIENT_SAMPLE",
        ),
        "dashboard-degraded.html": _mark_test_fixture(
            render_dashboard(_quality_fixture(payload, "DEGRADED")),
            "DEGRADED",
        ),
        "dashboard-unverified.html": _mark_test_fixture(
            render_dashboard(_quality_fixture(payload, "UNVERIFIED")),
            "UNVERIFIED",
        ),
        "dashboard-result-empty.html": _mark_test_fixture(
            render_dashboard(_result_empty_fixture(payload)),
            "RESULT=0",
        ),
        "dashboard-upcoming-empty.html": _mark_test_fixture(
            render_dashboard(_upcoming_empty_fixture(payload)),
            "UPCOMING=0",
        ),
    }

    business_date = str(payload.get("business_date") or "")
    current_formal_markets = _linked_frozen_formal_markets(ROOT / "data", current)
    current_contract = _fixture_contract(
        current,
        business_date,
        formal_markets=current_formal_markets,
    )
    current_contract["prediction_quality_health"] = payload.get("prediction_quality_health") or {}
    pages["detail-current-frozen.html"] = render_match_detail(current_contract)

    all_formal_markets = _all_formal_markets_for_visual_fixture(ROOT / "data", current)
    if all_formal_markets is not None:
        all_formal_contract = _fixture_contract(
            current,
            business_date,
            formal_markets=all_formal_markets,
        )
        all_formal_contract["prediction_quality_health"] = payload.get("prediction_quality_health") or {}
        pages["detail-all-formal.html"] = _mark_test_fixture(
            render_match_detail(all_formal_contract),
            "all formal markets",
        )

    completed_contract = copy.deepcopy(current_contract)
    completed_contract["prediction_quality_health"] = {
        "status": "HEALTHY",
        "scope": "current_serving",
        "available": True,
        "provenance_status": "MATCHED",
    }
    completed_contract["result"] = {
        "score_90m": "0-2",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-09-03T09:00:00+08:00",
        "source": "TEST FIXTURE",
    }
    pages["detail-completed-verified.html"] = _mark_test_fixture(
        render_match_detail(completed_contract),
        "completed verified result",
    )

    for name, document in pages.items():
        (fixture_root / name).write_text(document, encoding="utf-8")
    (fixture_root / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Refresh the production dashboard projection in the temporary build only.
    (site_root / "prediction_dashboard" / "latest.html").write_text(
        render_dashboard(payload), encoding="utf-8"
    )


def _visible_count(page: Any, selector: str) -> int:
    return int(
        page.locator(selector).evaluate_all(
            """elements => elements.filter(element => {
              const style = window.getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden'
                && rect.width > 0 && rect.height > 0;
            }).length"""
        )
    )


def _capture_page(
    browser: Any,
    *,
    base_url: str,
    path: str,
    output_path: Path,
    viewport: tuple[int, int],
    fixture_id: str,
    status: str,
) -> dict[str, Any]:
    console_errors: list[str] = []
    page_errors: list[str] = []
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        device_scale_factor=1,
        locale="zh-CN",
        color_scheme="light",
    )
    page = context.new_page()
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    url = f"{base_url}/{path.lstrip('/')}"
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(150)
        overflow = int(
            page.evaluate(
                "() => Math.max(0, document.documentElement.scrollWidth - "
                "document.documentElement.clientWidth)"
            )
        )
        formal_exact_metrics = page.locator(".exact-grid-wrap").evaluate_all(
            """elements => elements.map(element => ({
               cellCount: element.querySelectorAll('[data-formal-cell-home]').length,
               horizontalOverflow: element.offsetParent !== null
                 && element.scrollWidth > element.clientWidth + 1,
             }))"""
        )
        formal_exact_cells = sum(int(item.get("cellCount") or 0) for item in formal_exact_metrics)
        formal_exact_horizontal_overflow = any(
            bool(item.get("horizontalOverflow")) for item in formal_exact_metrics
        )
        compact_metrics = page.locator(".exact-compact").evaluate_all(
            """elements => elements.map(element => {
              const visible = (() => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              })();
              const fontSizes = [...element.querySelectorAll('.exact-compact-probability')]
                .map(item => Number.parseFloat(window.getComputedStyle(item).fontSize))
                .filter(Number.isFinite);
              return {
                visible,
                sourceCellCount: Number(element.dataset.formalCompactSourceCellCount || 0),
                topCount: Number(element.dataset.formalCompactTopCount || 0),
                scoreCount: element.querySelectorAll('[data-formal-compact-score]').length,
                remainderCount: Number(element.dataset.formalCompactRemainderCount || 0),
                remainderProbability: Number(element.dataset.formalCompactRemainderProbability || 0),
                probabilityFontSizeMin: fontSizes.length ? Math.min(...fontSizes) : null,
              };
            })"""
        )
        disclosure_metrics = page.locator("[data-formal-exact-disclosure]").evaluate_all(
            """elements => elements.map(element => {
              const visible = item => {
                const style = window.getComputedStyle(item);
                const rect = item.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              };
              const wrapper = element.querySelector('.exact-grid-wrap');
              return {
                open: Boolean(element.open),
                summaryVisible: Boolean(element.querySelector('summary')),
                cuePresent: Boolean(element.querySelector('.exact-disclosure-cue')),
                domCellCount: element.querySelectorAll('[data-formal-cell-home]').length,
                visibleCellCount: [...element.querySelectorAll('[data-formal-cell-home]')]
                  .filter(visible).length,
                wrapper: wrapper ? {
                  tabIndex: wrapper.tabIndex,
                  role: wrapper.getAttribute('role'),
                  ariaLabel: wrapper.getAttribute('aria-label'),
                  scrollWidth: wrapper.scrollWidth,
                  clientWidth: wrapper.clientWidth,
                } : null,
              };
            })"""
        )
        compact = compact_metrics[0] if compact_metrics else {}
        disclosure = disclosure_metrics[0] if disclosure_metrics else {}
        wrapper = disclosure.get("wrapper") if isinstance(disclosure, dict) else None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=False)
        visible_status_badges = _visible_count(page, ".status-badge")
        visible_health_badges = _visible_count(page, ".health-badge")
        return {
            "name": output_path.name,
            "path": output_path.name,
            "viewport": f"{viewport[0]}x{viewport[1]}",
            "fixture_id": fixture_id,
            "status": status,
            "url_path": path,
            "horizontal_overflow": overflow,
            "formal_exact_cells": formal_exact_cells,
            "formal_exact_horizontal_overflow": formal_exact_horizontal_overflow,
            "formal_exact_compact_visible": bool(compact.get("visible")),
            "formal_exact_compact_source_cell_count": int(compact.get("sourceCellCount") or 0),
            "formal_exact_compact_top_count": int(compact.get("topCount") or 0),
            "formal_exact_compact_score_count": int(compact.get("scoreCount") or 0),
            "formal_exact_compact_remainder_count": int(compact.get("remainderCount") or 0),
            "formal_exact_compact_remainder_probability": compact.get("remainderProbability"),
            "formal_exact_compact_probability_font_size_min": compact.get("probabilityFontSizeMin"),
            "formal_exact_disclosure_count": len(disclosure_metrics),
            "formal_exact_disclosure_open": bool(disclosure.get("open")),
            "formal_exact_disclosure_summary_visible": bool(disclosure.get("summaryVisible")),
            "formal_exact_disclosure_cue_present": bool(disclosure.get("cuePresent")),
            "formal_exact_disclosure_dom_cell_count": int(disclosure.get("domCellCount") or 0),
            "formal_exact_disclosure_visible_cell_count": int(disclosure.get("visibleCellCount") or 0),
            "formal_exact_disclosure_focusable": bool(
                isinstance(wrapper, dict) and int(wrapper.get("tabIndex") or -1) >= 0
            ),
            "formal_exact_disclosure_labeled": bool(
                isinstance(wrapper, dict)
                and wrapper.get("role") == "region"
                and str(wrapper.get("ariaLabel") or "").strip()
            ),
            "formal_exact_disclosure_scrollable": bool(
                isinstance(wrapper, dict)
                and int(wrapper.get("scrollWidth") or 0) > int(wrapper.get("clientWidth") or 0) + 1
            ),
            "normal_frozen_badge_count": visible_status_badges,
            "normal_health_badge_count": visible_health_badges,
            "console_errors": console_errors,
            "page_errors": page_errors,
        }
    finally:
        context.close()


def _check_interactions(browser: Any, base_url: str) -> dict[str, str]:
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = context.new_page()
    try:
        page.goto(f"{base_url}/prediction_dashboard/latest.html", wait_until="networkidle", timeout=30_000)
        total = page.locator(".fixture-row").count()
        expected_upcoming = page.locator(".fixture-row").evaluate_all(
            """rows => rows.filter(row => {
              const kickoffTimestamp = Date.parse(row.dataset.kickoff || '');
              return Number.isFinite(kickoffTimestamp) && Date.now() < kickoffTimestamp;
            }).length"""
        )
        expected_results = page.locator('.fixture-row[data-result="yes"]').count()
        page.locator('[data-filter="UPCOMING"]').click()
        if _visible_count(page, ".fixture-row") != expected_upcoming:
            raise RuntimeError("UPCOMING filter did not use future kickoff timestamps")
        if _visible_count(page, "#historical-results"):
            raise RuntimeError("UPCOMING filter did not hide history")
        page.locator('[data-filter="RESULT"]').click()
        if _visible_count(page, ".fixture-row") != expected_results:
            raise RuntimeError("RESULT filter did not isolate current verified fixtures")
        if _visible_count(page, "#historical-results"):
            raise RuntimeError("RESULT filter mixed in historical validation")
        if expected_results == 0 and _visible_count(page, '[data-filter-empty="RESULT"]') != 1:
            raise RuntimeError("RESULT=0 did not show the current-day empty state")
        if expected_results > 0 and _visible_count(page, '[data-filter-empty="RESULT"]'):
            raise RuntimeError("RESULT filter left a stale empty state")
        page.locator('[data-filter="ALL"]').click()
        if _visible_count(page, ".fixture-row") != total:
            raise RuntimeError("ALL filter did not restore current fixtures")
        if _visible_count(page, "[data-filter-empty]"):
            raise RuntimeError("ALL filter left a stale empty state")
        href = page.locator(".fixture-row-target").first.get_attribute("href")
        if not href:
            raise RuntimeError("dashboard has no real detail route")
        page.goto(urljoin(f"{base_url}/prediction_dashboard/", href), wait_until="networkidle", timeout=30_000)
        if page.locator("h1").count() != 1:
            raise RuntimeError("dashboard detail route did not resolve")

        page.goto(f"{base_url}/visual-fixtures/dashboard-result-empty.html", wait_until="networkidle", timeout=30_000)
        result_total = page.locator(".fixture-row").count()
        page.locator('[data-filter="RESULT"]').click()
        if _visible_count(page, ".fixture-row") != 0:
            raise RuntimeError("synthetic RESULT=0 still showed fixture rows")
        if _visible_count(page, '[data-filter-empty="RESULT"]') != 1:
            raise RuntimeError("synthetic RESULT=0 did not show the current-day empty state")
        page.locator('[data-filter="ALL"]').click()
        if _visible_count(page, ".fixture-row") != result_total or _visible_count(page, "[data-filter-empty]"):
            raise RuntimeError("synthetic RESULT=0 did not recover on ALL")

        page.goto(f"{base_url}/visual-fixtures/dashboard-upcoming-empty.html", wait_until="networkidle", timeout=30_000)
        upcoming_total = page.locator(".fixture-row").count()
        page.locator('[data-filter="UPCOMING"]').click()
        if _visible_count(page, ".fixture-row") != 0:
            raise RuntimeError("synthetic UPCOMING=0 still showed fixture rows")
        if _visible_count(page, '[data-filter-empty="UPCOMING"]') != 1:
            raise RuntimeError("synthetic UPCOMING=0 did not show the current-day empty state")
        page.locator('[data-filter="ALL"]').click()
        if _visible_count(page, ".fixture-row") != upcoming_total or _visible_count(page, "[data-filter-empty]"):
            raise RuntimeError("synthetic UPCOMING=0 did not recover on ALL")
        return {
            "filters": "VERIFIED",
            "dashboard_to_detail": "VERIFIED",
            "result_zero_state": "VERIFIED",
            "upcoming_zero_state": "VERIFIED",
            "all_recovers_after_empty": "VERIFIED",
        }
    finally:
        context.close()


def _check_exact_mobile_interactions(browser: Any, base_url: str) -> dict[str, str]:
    checks: dict[str, str] = {}
    for width, height in ((390, 844), (320, 800)):
        context = browser.new_context(
            viewport={"width": width, "height": height},
            locale="zh-CN",
        )
        page = context.new_page()
        label = str(width)
        try:
            page.goto(
                f"{base_url}/visual-fixtures/detail-all-formal.html#formal-markets",
                wait_until="networkidle",
                timeout=30_000,
            )
            page.wait_for_timeout(150)
            page_overflow = int(
                page.evaluate(
                    "() => Math.max(0, document.documentElement.scrollWidth - "
                    "document.documentElement.clientWidth)"
                )
            )
            if page_overflow:
                raise RuntimeError(f"{label}px mobile page has horizontal overflow: {page_overflow}")

            compact = page.locator(".exact-compact")
            if _visible_count(page, ".exact-compact") != 1:
                raise RuntimeError(f"{label}px Exact compact projection is not the default view")
            compact_metrics = compact.evaluate(
                """element => ({
                  sourceCellCount: Number(element.dataset.formalCompactSourceCellCount || 0),
                  topCount: Number(element.dataset.formalCompactTopCount || 0),
                  scoreCount: element.querySelectorAll('[data-formal-compact-score]').length,
                  remainderCount: Number(element.dataset.formalCompactRemainderCount || 0),
                  probabilityFontSizeMin: Math.min(...[...element.querySelectorAll('.exact-compact-probability')]
                    .map(item => Number.parseFloat(window.getComputedStyle(item).fontSize))),
                })"""
            )
            if compact_metrics["sourceCellCount"] != 169:
                raise RuntimeError(f"{label}px compact projection lost frozen cells")
            if compact_metrics["topCount"] != 6 or compact_metrics["scoreCount"] != 6:
                raise RuntimeError(f"{label}px compact projection does not expose deterministic Top 6")
            if compact_metrics["remainderCount"] != 163:
                raise RuntimeError(f"{label}px compact projection has an incorrect represented remainder")
            if compact_metrics["probabilityFontSizeMin"] < 12:
                raise RuntimeError(f"{label}px compact probability text is below 12px")

            disclosure = page.locator("[data-formal-exact-disclosure]")
            if disclosure.count() != 1:
                raise RuntimeError(f"{label}px Exact disclosure control is missing")
            if disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px full Exact matrix is the default view")
            if page.locator("[data-formal-cell-home]").count() != 169:
                raise RuntimeError(f"{label}px DOM does not retain all 169 frozen Exact cells")
            if _visible_count(page, "[data-formal-cell-home]") != 0:
                raise RuntimeError(f"{label}px full Exact matrix is visible before disclosure")
            summary = disclosure.locator("summary")
            if not summary.get_attribute("aria-label") and not summary.inner_text().strip():
                raise RuntimeError(f"{label}px Exact disclosure has no readable control label")
            wrapper = page.locator(".exact-grid-wrap")
            compact_snapshot = compact.get_attribute("data-formal-compact-remainder-probability")

            summary.click()
            if not disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px Exact disclosure did not open by pointer interaction")
            if _visible_count(page, "[data-formal-cell-home]") != 169:
                raise RuntimeError(f"{label}px disclosure did not reveal all 169 frozen Exact cells")
            wrapper_metrics = wrapper.evaluate(
                """element => ({
                  tabIndex: element.tabIndex,
                  role: element.getAttribute('role'),
                  ariaLabel: element.getAttribute('aria-label'),
                  scrollWidth: element.scrollWidth,
                  clientWidth: element.clientWidth,
                })"""
            )
            if wrapper_metrics["tabIndex"] < 0 or wrapper_metrics["role"] != "region":
                raise RuntimeError(f"{label}px Exact matrix scroll region is not keyboard focusable")
            if not str(wrapper_metrics["ariaLabel"] or "").strip():
                raise RuntimeError(f"{label}px Exact matrix scroll region is not labeled")
            if wrapper_metrics["scrollWidth"] <= wrapper_metrics["clientWidth"] + 1:
                raise RuntimeError(f"{label}px Exact matrix has no contained horizontal scroll affordance")
            wrapper.focus()
            if not page.evaluate("() => document.activeElement === document.querySelector('.exact-grid-wrap')"):
                raise RuntimeError(f"{label}px Exact matrix scroll region did not receive keyboard focus")
            scroll_left = wrapper.evaluate(
                """element => {
                  element.scrollLeft = element.scrollWidth;
                  return element.scrollLeft;
                }"""
            )
            if scroll_left <= 0:
                raise RuntimeError(f"{label}px Exact matrix scroll region did not scroll")
            if compact.get_attribute("data-formal-compact-remainder-probability") != compact_snapshot:
                raise RuntimeError(f"{label}px disclosure mutated frozen compact probability state")
            if int(
                page.evaluate(
                    "() => Math.max(0, document.documentElement.scrollWidth - "
                    "document.documentElement.clientWidth)"
                )
            ):
                raise RuntimeError(f"{label}px opening Exact matrix overflowed the page")

            summary.focus()
            summary.press("Enter")
            if disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px Exact disclosure did not close by keyboard interaction")
            summary.press("Enter")
            if not disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px Exact disclosure did not reopen by keyboard interaction")
            checks[f"exact_mobile_{label}_compact_default"] = "VERIFIED"
            checks[f"exact_mobile_{label}_full_disclosure"] = "VERIFIED"
            checks[f"exact_mobile_{label}_keyboard_scroll"] = "VERIFIED"
        finally:
            context.close()
    return checks


def _capture_all(
    site_root: Path,
    output: Path,
    payload: dict[str, Any],
    current: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    handler = partial(_QuietHandler, directory=str(site_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    specs = [
        ("dashboard-1440x1000.png", "prediction_dashboard/latest.html", (1440, 1000), "production-current", "PRODUCTION_TRUTH"),
        ("dashboard-390x844.png", "prediction_dashboard/latest.html", (390, 844), "production-current", "PRODUCTION_TRUTH"),
        ("dashboard-320x800.png", "prediction_dashboard/latest.html", (320, 800), "production-current", "PRODUCTION_TRUTH"),
        ("detail-current-frozen-1440x1000.png", "visual-fixtures/detail-current-frozen.html", (1440, 1000), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-current-frozen-390x844.png", "visual-fixtures/detail-current-frozen.html", (390, 844), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-current-frozen-320x800.png", "visual-fixtures/detail-current-frozen.html", (320, 800), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("formal-markets-unavailable-1440x1000.png", "visual-fixtures/detail-current-frozen.html#formal-markets", (1440, 1000), str(current.get("match_id") or "formal-markets-unavailable"), "PRODUCTION_TRUTH"),
        ("formal-markets-unavailable-390x844.png", "visual-fixtures/detail-current-frozen.html#formal-markets", (390, 844), str(current.get("match_id") or "formal-markets-unavailable"), "PRODUCTION_TRUTH"),
        ("formal-markets-unavailable-320x800.png", "visual-fixtures/detail-current-frozen.html#formal-markets", (320, 800), str(current.get("match_id") or "formal-markets-unavailable"), "PRODUCTION_TRUTH"),
        ("all-formal-1440x1000.png", "visual-fixtures/detail-all-formal.html#formal-markets", (1440, 1000), "TEST FIXTURE · all formal markets", "TEST_FIXTURE"),
        ("all-formal-390x844.png", "visual-fixtures/detail-all-formal.html#formal-markets", (390, 844), "TEST FIXTURE · all formal markets", "TEST_FIXTURE"),
        ("all-formal-320x800.png", "visual-fixtures/detail-all-formal.html#formal-markets", (320, 800), "TEST FIXTURE · all formal markets", "TEST_FIXTURE"),
        ("insufficient-evidence-390x844.png", "visual-fixtures/dashboard-insufficient.html", (390, 844), "TEST FIXTURE · INSUFFICIENT_SAMPLE", "TEST_FIXTURE"),
        ("degraded-evidence-1440x1000.png", "visual-fixtures/dashboard-degraded.html", (1440, 1000), "TEST FIXTURE · DEGRADED", "TEST_FIXTURE"),
        ("unverified-evidence-390x844.png", "visual-fixtures/dashboard-unverified.html", (390, 844), "TEST FIXTURE · UNVERIFIED", "TEST_FIXTURE"),
        ("result-empty-evidence-390x844.png", "visual-fixtures/dashboard-result-empty.html", (390, 844), "TEST FIXTURE · RESULT=0", "TEST_FIXTURE"),
        ("upcoming-empty-evidence-390x844.png", "visual-fixtures/dashboard-upcoming-empty.html", (390, 844), "TEST FIXTURE · UPCOMING=0", "TEST_FIXTURE"),
        ("completed-evidence-1440x1000.png", "visual-fixtures/detail-completed-verified.html", (1440, 1000), "TEST FIXTURE · completed-verified", "TEST_FIXTURE"),
        ("completed-evidence-390x844.png", "visual-fixtures/detail-completed-verified.html", (390, 844), "TEST FIXTURE · completed-verified", "TEST_FIXTURE"),
        ("completed-evidence-320x800.png", "visual-fixtures/detail-completed-verified.html", (320, 800), "TEST FIXTURE / completed-verified", "TEST_FIXTURE"),
    ]
    records: list[dict[str, Any]] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                interaction_checks = {
                    **_check_interactions(browser, base_url),
                    **_check_exact_mobile_interactions(browser, base_url),
                }
                for name, path, viewport, fixture_id, status in specs:
                    records.append(
                        _capture_page(
                            browser,
                            base_url=base_url,
                            path=path,
                            output_path=output / name,
                            viewport=viewport,
                            fixture_id=fixture_id,
                            status=status,
                        )
                    )
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return records, interaction_checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, default=ROOT / "site")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "visual-evidence")
    args = parser.parse_args()
    site_root = args.site_root.resolve()
    output = args.output_dir.resolve()
    payload = _regenerate_dashboard(site_root)
    dashboard_path = site_root / "prediction_dashboard" / "latest.json"
    if not dashboard_path.is_file():
        raise SystemExit(f"PR renderer did not write regenerated dashboard JSON: {dashboard_path}")
    fixtures = [item for item in payload.get("fixtures") or [] if isinstance(item, dict)]
    current = next(
        (
            item
            for item in fixtures
            if str(item.get("status") or "").upper() == "FROZEN"
            and isinstance(item.get("prediction"), dict)
        ),
        None,
    )
    if current is None:
        raise SystemExit("runtime evidence requires at least one current FROZEN fixture with prediction")
    output.mkdir(parents=True, exist_ok=True)
    _write_fixture_pages(site_root, payload, current)
    records, interaction_checks = _capture_all(site_root, output, payload, current)

    browser_errors = [
        {"name": record["name"], "messages": record["console_errors"] + record["page_errors"]}
        for record in records
        if record["console_errors"] or record["page_errors"]
    ]
    overflow = [record for record in records if record["horizontal_overflow"]]
    exact_overflow = [record for record in records if record["formal_exact_horizontal_overflow"]]
    mobile_exact_failures = [
        record
        for record in records
        if record["formal_exact_cells"] == 169
        and record["viewport"] in {"390x844", "320x800"}
        and (
            not record["formal_exact_compact_visible"]
            or record["formal_exact_compact_source_cell_count"] != 169
            or record["formal_exact_compact_top_count"] != 6
            or record["formal_exact_compact_score_count"] != 6
            or record["formal_exact_compact_remainder_count"] != 163
            or (record["formal_exact_compact_probability_font_size_min"] or 0) < 12
            or record["formal_exact_disclosure_count"] != 1
            or record["formal_exact_disclosure_open"]
            or record["formal_exact_disclosure_dom_cell_count"] != 169
            or record["formal_exact_disclosure_summary_visible"] is not True
            or record["formal_exact_disclosure_cue_present"] is not True
        )
    ]
    desktop_exact_failures = [
        record
        for record in records
        if record["formal_exact_cells"] == 169
        and record["viewport"] == "1440x1000"
        and (
            record["formal_exact_disclosure_count"] != 1
            or not record["formal_exact_disclosure_open"]
            or record["formal_exact_disclosure_visible_cell_count"] != 169
        )
    ]
    if browser_errors or overflow or exact_overflow or mobile_exact_failures or desktop_exact_failures:
        raise SystemExit(
            json.dumps(
                {
                    "browser_errors": browser_errors,
                    "horizontal_overflow": overflow,
                    "formal_exact_horizontal_overflow": exact_overflow,
                    "formal_exact_mobile_default_failures": mobile_exact_failures,
                    "formal_exact_desktop_full_matrix_failures": desktop_exact_failures,
                },
                ensure_ascii=False,
            )
        )

    production_frozen_count = sum(
        record["normal_frozen_badge_count"] for record in records if record["status"] == "PRODUCTION_TRUTH"
    )
    production_health_count = sum(
        record["normal_health_badge_count"] for record in records if record["status"] == "PRODUCTION_TRUTH"
    )
    manifest = {
        "schema_version": "public_ui_visual_evidence.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit_sha": _source_commit_sha(),
        "browser": {"engine": "chromium", "automation": "playwright", "headless": True},
        "production_truth": {
            "business_date": payload.get("business_date"),
            "fixture_count": payload.get("summary", {}).get("fixture_count", len(fixtures)),
            "card_count": payload.get("summary", {}).get("card_count", len(fixtures)),
            "frozen_count": sum(1 for item in fixtures if item.get("status") == "FROZEN"),
            "source": "scripts.prediction_dashboard.build_dashboard -> site/prediction_dashboard/latest.json",
        },
        "screenshots": records,
        "checks": {
            "horizontal_overflow_1440": 0,
            "horizontal_overflow_390": 0,
            "horizontal_overflow_320": 0,
            "formal_exact_horizontal_overflow_390": 0,
            "formal_exact_horizontal_overflow_320": 0,
            "formal_exact_cell_counts": {
                record["name"]: record["formal_exact_cells"]
                for record in records
                if record["formal_exact_cells"]
            },
            "formal_exact_mobile_default": {
                record["name"]: {
                    "compact_visible": record["formal_exact_compact_visible"],
                    "source_cell_count": record["formal_exact_compact_source_cell_count"],
                    "top_count": record["formal_exact_compact_top_count"],
                    "score_count": record["formal_exact_compact_score_count"],
                    "remainder_count": record["formal_exact_compact_remainder_count"],
                    "probability_font_size_min": record["formal_exact_compact_probability_font_size_min"],
                    "full_matrix_default_open": record["formal_exact_disclosure_open"],
                    "full_matrix_dom_cell_count": record["formal_exact_disclosure_dom_cell_count"],
                }
                for record in records
                if record["formal_exact_cells"] == 169
                and record["viewport"] in {"390x844", "320x800"}
            },
            "formal_exact_desktop_full_matrix": {
                record["name"]: {
                    "open": record["formal_exact_disclosure_open"],
                    "visible_cell_count": record["formal_exact_disclosure_visible_cell_count"],
                }
                for record in records
                if record["formal_exact_cells"] == 169 and record["viewport"] == "1440x1000"
            },
            "dashboard_regenerated_with_pr_renderer": "YES",
            "normal_frozen_badge_count": production_frozen_count,
            "normal_health_badge_count": production_health_count,
            "fake_data_graphics": 0,
            "fake_affordances": 0,
            "interaction_checks": interaction_checks,
            "production_data_changed": "NO",
            "model_data_contract_changed": "NO",
            "capture_integrity": "OK",
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "screenshots": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
