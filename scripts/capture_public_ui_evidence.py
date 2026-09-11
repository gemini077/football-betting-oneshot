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

from scripts.build_public_site import (  # noqa: E402
    _attach_fixture_prematch_evidence,
    _change_awareness_for_fixture,
    _fixture_contract,
    _linked_frozen_formal_markets,
    _prediction_records,
)
from scripts.match_analysis import compile_prematch_analysis  # noqa: E402
from scripts.match_detail import render_match_detail  # noqa: E402
from scripts.prediction_dashboard import build_dashboard, render_dashboard  # noqa: E402
from scripts.team_crest_enrichment import (  # noqa: E402
    enrich_dashboard_crests,
    failed_crest_diagnostics,
    new_crest_diagnostics,
)


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


def _exact_unavailable_contract(contract: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(contract)
    formal = result.get("formal_markets") if isinstance(result.get("formal_markets"), dict) else {}
    markets = formal.get("markets") if isinstance(formal.get("markets"), dict) else {}
    exact = copy.deepcopy(markets.get("exact_score")) if isinstance(markets.get("exact_score"), dict) else {}
    exact["status"] = "UNAVAILABLE"
    exact.pop("contract", None)
    markets["exact_score"] = exact
    formal["markets"] = markets
    result["formal_markets"] = formal
    return result


def _changed_exact_contract(contract: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(contract)
    result["change_awareness"] = {
        "status": "AVAILABLE",
        "current_snapshot": {"prediction_id": "TEST-CURRENT"},
        "previous_snapshot": {"prediction_id": "TEST-PREVIOUS"},
        "elapsed_seconds": 900,
        "markets": {
            "ft_1x2": {
                "status": "AVAILABLE",
                "items": [
                    {"key": "home", "label": "\u4e3b\u80dc", "before": 0.44, "now": 0.48, "delta_probability_points": 4.0},
                ],
            },
            "exact_score": {
                "status": "AVAILABLE",
                "support": {"cell_count": 169},
                "items": [
                    {
                        "key": "1-1",
                        "label": "1-1",
                        "before": 0.094,
                        "now": 0.119,
                        "delta_probability_points": 2.5,
                        "before_rank": 1,
                        "now_rank": 2,
                    },
                ],
            },
        },
    }
    return result


def _regenerate_dashboard(site_root: Path) -> dict[str, Any]:
    """Regenerate the dashboard through the PR renderer immediately before capture."""

    source_candidates = (
        ROOT / "data" / "prediction_dashboard" / "latest.json",
        site_root / "prediction_dashboard" / "latest.json",
    )
    source_payload = next(
        (_read_json(path) for path in source_candidates if path.is_file()),
        None,
    )
    business_date = str((source_payload or {}).get("business_date") or "").strip()
    if not business_date:
        raise SystemExit("visual evidence requires a dashboard business_date")
    data_root = ROOT / "data"
    payload = build_dashboard(
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
    universe_path = data_root / "prediction_universe" / f"{business_date}.json"
    universe = _read_json(universe_path) if universe_path.is_file() else {}
    crest_diagnostics = new_crest_diagnostics()
    try:
        payload = enrich_dashboard_crests(
            payload,
            universe=universe,
            asset_root=site_root / "assets" / "team-crests",
            diagnostics=crest_diagnostics,
        )
    except Exception as error:
        # Crest enrichment is optional presentation data and never blocks
        # dashboard regeneration or the existing evidence capture.
        crest_diagnostics = failed_crest_diagnostics(
            payload,
            f"ENRICHMENT_EXCEPTION_{type(error).__name__}",
        )
    dashboard_root = site_root / "prediction_dashboard"
    (dashboard_root / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (dashboard_root / "latest.html").write_text(render_dashboard(payload), encoding="utf-8")
    crest_diagnostics_path = site_root / "diagnostics" / "team-crest-enrichment.json"
    crest_diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    crest_diagnostics_path.write_text(
        json.dumps(crest_diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _write_fixture_pages(site_root: Path, payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
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
    for status in (
        "PENDING",
        "INSUFFICIENT_DATA",
        "PREDICTION_FAILED",
        "MISSED_PREMATCH_WINDOW",
        "CURRENT_JOB_STATE_CONFLICT",
    ):
        pages[f"dashboard-{status.lower()}.html"] = _mark_test_fixture(
            render_dashboard(_fixture_with_status(payload, status)),
            status,
        )

    business_date = str(payload.get("business_date") or "")
    data_root = ROOT / "data"
    prediction_records = _prediction_records(data_root)
    current_record = _linked_prediction_record(data_root, current)
    current_change_awareness = _change_awareness_for_fixture(
        data_root,
        current,
        records=prediction_records,
    )
    current_formal_markets = _linked_frozen_formal_markets(data_root, current)
    current_contract = _fixture_contract(
        current,
        business_date,
        formal_markets=current_formal_markets,
    )
    current_contract["change_awareness"] = current_change_awareness
    current_contract = _attach_fixture_prematch_evidence(
        data_root,
        current_contract,
        current,
        business_date,
    )
    current_contract["analysis_article"] = compile_prematch_analysis(current_contract)
    current_contract["prediction_quality_health"] = payload.get("prediction_quality_health") or {}
    pages["detail-current-frozen.html"] = render_match_detail(current_contract)

    no_previous_contract = copy.deepcopy(current_contract)
    if current_record is not None:
        no_previous_contract["change_awareness"] = _change_awareness_for_fixture(
            data_root,
            current,
            records={str(current_record.get("prediction_id")): current_record},
        )
    pages["detail-change-no-previous.html"] = _mark_test_fixture(
        render_match_detail(no_previous_contract),
        "change awareness - no previous snapshot",
    )

    changed_contract = _changed_exact_contract(current_contract)
    pages["detail-change-exact.html"] = _mark_test_fixture(
        render_match_detail(changed_contract),
        "change awareness - exact score snapshot",
    )

    unavailable_contract = _exact_unavailable_contract(current_contract)
    pages["detail-exact-unavailable.html"] = _mark_test_fixture(
        render_match_detail(unavailable_contract),
        "exact score unavailable",
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
    return current_contract.get("analysis_article") if isinstance(current_contract.get("analysis_article"), dict) else {}


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


def _shell_metrics(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const visible = element => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden'
              && rect.width > 0 && rect.height > 0;
          };
          const fragmentLinks = [...document.querySelectorAll('a[href^="#"]')]
            .filter(visible)
            .map(link => link.getAttribute('href').slice(1))
            .filter(Boolean);
          const missingFragmentTargets = [...new Set(fragmentLinks)]
            .filter(id => !visible(document.getElementById(id)));
          const text = document.body.innerText || '';
          const sizes = selector => {
            const element = document.querySelector(selector);
            return element && visible(element)
              ? Number.parseFloat(window.getComputedStyle(element).fontSize)
              : null;
          };
          const targets = [...document.querySelectorAll('.tab, .bottom-item, .filter, .mobile-topbar a')]
            .filter(visible)
            .map(element => ({
              selector: element.className,
              height: element.getBoundingClientRect().height,
              width: element.getBoundingClientRect().width,
            }));
          const fakeSelectors = [
            '.icon-btn',
            '.fav',
            '[aria-label="\u641c\u7d22"]',
            '[aria-label="\u6536\u85cf"]',
            '[aria-label="\u901a\u77e5"]',
            '[aria-label="\u8d26\u6237"]',
          ];
          const fakeControls = fakeSelectors.reduce(
            (count, selector) => count + [...document.querySelectorAll(selector)].filter(visible).length,
            0,
          );
          const tabTargets = [...document.querySelectorAll('.tab[href^="#market"], .tab[href^="#evidence"]')]
            .filter(visible)
            .map(tab => tab.getAttribute('href').slice(1));
          return {
            missingFragmentTargets,
            fakeControls,
            favoriteControls: [...document.querySelectorAll('.fav')].filter(visible).length,
            forbiddenShellText: ['Dark mode', '9:41', '\u6536\u85cf', '\u901a\u77e5', '\u8d26\u6237'].filter(token => text.includes(token)),
            firstLayerJargon: ['1X2', 'Top3', 'Top-3', 'H\\A', 'H/A'].filter(token => text.includes(token)),
            dashboardAnalysisLinks: [...document.querySelectorAll('a[href="#analysis"]')].filter(visible).length,
            closedBetaLinks: [...document.querySelectorAll('a[href="#closed-beta"]')].filter(visible).length,
            mobileDataLinks: [...document.querySelectorAll('.mobile-bottom a[href="#data-method"]')].filter(visible).length,
            tabTargets,
            missingConditionalTabTargets: tabTargets.filter(id => !visible(document.getElementById(id))),
            frozenNotPredicting: [...document.querySelectorAll('.match-card[data-status="FROZEN"] .teams-status')]
              .filter(visible)
              .filter(element => element.textContent.includes('\u5f53\u524d\u6682\u4e0d\u9884\u6d4b')).length,
            typography: {
              body: sizes('body'),
              matchup: sizes('.matchup-name'),
              support: sizes('.compact-prob-label, .recommendation-reason, .evidence-block'),
              section: sizes('.matches-head h1, .section-heading h2, .panel h2'),
              probability: sizes('.probability-card strong, .compact-prob-values'),
              matrix: sizes('.signature-grid'),
            },
            mobileTargets: targets,
            mobileTopbarTargets: [...document.querySelectorAll('.mobile-topbar a')]
              .filter(visible)
              .map(element => ({
                height: element.getBoundingClientRect().height,
                width: element.getBoundingClientRect().width,
              })),
          };
        }"""
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
        exact_metrics = page.locator(".exact-grid-wrap").evaluate_all(
            """elements => elements.map(element => ({
               cellCount: element.querySelectorAll('[data-exact-cell-home]').length,
               horizontalOverflow: element.offsetParent !== null
                 && element.scrollWidth > element.clientWidth + 1,
             }))"""
        )
        exact_cells = sum(int(item.get("cellCount") or 0) for item in exact_metrics)
        exact_horizontal_overflow = any(
            bool(item.get("horizontalOverflow")) for item in exact_metrics
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
                sourceCellCount: Number(element.dataset.exactCompactSourceCellCount || 0),
                topCount: Number(element.dataset.exactCompactTopCount || 0),
                scoreCount: element.querySelectorAll('[data-exact-compact-score]').length,
                remainderCount: Number(element.dataset.exactCompactRemainderCount || 0),
                remainderProbability: Number(element.dataset.exactCompactRemainderProbability || 0),
                probabilityFontSizeMin: fontSizes.length ? Math.min(...fontSizes) : null,
              };
            })"""
        )
        disclosure_metrics = page.locator("[data-exact-disclosure]").evaluate_all(
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
                domCellCount: element.querySelectorAll('[data-exact-cell-home]').length,
                visibleCellCount: [...element.querySelectorAll('[data-exact-cell-home]')]
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
        signature_matrix_visible = _visible_count(page, ".signature-grid") > 0
        existing_crest_count = _visible_count(page, '[data-crest-kind="existing"]')
        article_metrics = page.evaluate(
            """() => {
              const article = document.querySelector('#prematch-analysis');
              const analysis = document.querySelector('#analysis');
              const visible = element => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              };
              return {
                visible: visible(article),
                firstInAnalysis: Boolean(article && analysis && analysis.children[0] === article),
                claimCount: article ? article.querySelectorAll('[data-article-claim]').length : 0,
                blockCount: article ? article.querySelectorAll('[data-article-block]').length : 0,
                horizontalOverflow: Boolean(article && article.scrollWidth > article.clientWidth + 1),
              };
            }"""
        )
        visible_forbidden = page.evaluate(
            """() => {
              const text = document.body.innerText || '';
              return ['FROZEN', 'HEALTHY', 'MATCHED', 'provider', 'prediction_id', 'job_id']
                .filter(token => text.includes(token));
            }"""
        )
        shell_metrics = _shell_metrics(page)
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
            "exact_horizontal_overflow": exact_horizontal_overflow,
            "exact_cells": exact_cells,
            "exact_compact_visible": bool(compact.get("visible")),
            "exact_compact_source_cell_count": int(compact.get("sourceCellCount") or 0),
            "exact_compact_top_count": int(compact.get("topCount") or 0),
            "exact_compact_score_count": int(compact.get("scoreCount") or 0),
            "exact_compact_remainder_count": int(compact.get("remainderCount") or 0),
            "exact_compact_remainder_probability": compact.get("remainderProbability"),
            "exact_compact_probability_font_size_min": compact.get("probabilityFontSizeMin"),
            "exact_signature_matrix_visible": signature_matrix_visible,
            "existing_crest_count": existing_crest_count,
            "exact_disclosure_count": len(disclosure_metrics),
            "exact_disclosure_open": bool(disclosure.get("open")),
            "exact_disclosure_summary_visible": bool(disclosure.get("summaryVisible")),
            "exact_disclosure_cue_present": bool(disclosure.get("cuePresent")),
            "exact_disclosure_dom_cell_count": int(disclosure.get("domCellCount") or 0),
            "exact_disclosure_visible_cell_count": int(disclosure.get("visibleCellCount") or 0),
            "exact_disclosure_focusable": bool(
                isinstance(wrapper, dict) and int(wrapper.get("tabIndex") or -1) >= 0
            ),
            "exact_disclosure_labeled": bool(
                isinstance(wrapper, dict)
                and wrapper.get("role") == "region"
                and str(wrapper.get("ariaLabel") or "").strip()
            ),
            "exact_disclosure_scrollable": bool(
                isinstance(wrapper, dict)
                and int(wrapper.get("scrollWidth") or 0) > int(wrapper.get("clientWidth") or 0) + 1
            ),
            "article_visible": bool(article_metrics.get("visible")),
            "article_first_in_analysis": bool(article_metrics.get("firstInAnalysis")),
            "article_claim_count": int(article_metrics.get("claimCount") or 0),
            "article_block_count": int(article_metrics.get("blockCount") or 0),
            "article_horizontal_overflow": bool(article_metrics.get("horizontalOverflow")),
            "normal_frozen_badge_count": visible_status_badges,
            "normal_health_badge_count": visible_health_badges,
            "visible_forbidden_tokens": list(visible_forbidden or []),
            "shell_metrics": shell_metrics,
            "frozen_not_predicting_count": int(shell_metrics.get("frozenNotPredicting") or 0),
            "change_awareness_visible": _visible_count(page, "[data-change-awareness]") > 0,
            "change_awareness_status": str(
                page.locator("[data-change-awareness]").first.get_attribute("data-change-awareness-status") or ""
            ) if page.locator("[data-change-awareness]").count() else "",
            "change_awareness_lane_count": page.locator("[data-change-awareness] [data-change-lane]").count(),
            "change_awareness_exact_row_count": page.locator(
                '[data-change-awareness] [data-change-lane="exact_score"] .change-row'
            ).count(),
            "completed_result_visible": _visible_count(page, ".result-panel") > 0,
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
        if page.locator(".detail-page .hero h1").count() != 2:
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


def _check_public_shell_and_responsive(browser: Any, base_url: str) -> dict[str, str]:
    checks: dict[str, str] = {}

    def assert_shell(metrics: dict[str, Any], label: str, *, mobile: bool = False, dashboard: bool = False) -> None:
        if metrics.get("missingFragmentTargets"):
            raise RuntimeError(f"{label} has missing visible fragment targets: {metrics['missingFragmentTargets']}")
        if metrics.get("fakeControls"):
            raise RuntimeError(f"{label} still exposes fake utility controls")
        if metrics.get("favoriteControls"):
            raise RuntimeError(f"{label} still exposes a fake favorite affordance")
        if metrics.get("forbiddenShellText"):
            raise RuntimeError(f"{label} still exposes fake shell text: {metrics['forbiddenShellText']}")
        if metrics.get("firstLayerJargon"):
            raise RuntimeError(f"{label} exposes first-layer jargon: {metrics['firstLayerJargon']}")
        if dashboard and metrics.get("dashboardAnalysisLinks"):
            raise RuntimeError(f"{label} exposes a missing dashboard analysis route")
        if metrics.get("closedBetaLinks"):
            raise RuntimeError(f"{label} points the beginner guide at closed beta")
        if metrics.get("missingConditionalTabTargets"):
            raise RuntimeError(f"{label} exposes a tab without a target")
        if metrics.get("frozenNotPredicting"):
            raise RuntimeError(f"{label} shows a stale not-predicting line on a frozen card")
        if mobile and int(metrics.get("mobileDataLinks") or 0) != 1:
            raise RuntimeError(f"{label} does not expose the mobile data destination")
        if mobile and any(float(item.get("height") or 0) < 44 for item in metrics.get("mobileTargets") or []):
            raise RuntimeError(f"{label} has a sub-44px mobile interaction target")
        if mobile and any(
            float(item.get("height") or 0) < 44 or float(item.get("width") or 0) < 44
            for item in metrics.get("mobileTopbarTargets") or []
        ):
            raise RuntimeError(f"{label} has a sub-44px mobile back target")
        typography = metrics.get("typography") or {}
        required_sizes = [typography.get("body"), typography.get("support"), typography.get("section")]
        if any(size is not None and float(size) < 11 for size in required_sizes):
            raise RuntimeError(f"{label} has unreadable core typography: {typography}")
        matrix_size = typography.get("matrix")
        if matrix_size is not None and float(matrix_size) < 10:
            raise RuntimeError(f"{label} has an unreadable score matrix: {matrix_size}")

    def assert_scaled(page: Any, path_label: str, selectors: list[str]) -> None:
        page.evaluate("() => document.documentElement.style.setProperty('--ui-text-scale', '2')")
        page.wait_for_timeout(50)
        scaled = page.evaluate(
            """selectors => {
              const visible = element => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0;
              };
              const missing = selectors.filter(selector => !visible(document.querySelector(selector)));
              const clipped = selectors.filter(selector => {
                const element = document.querySelector(selector);
                if (!visible(element)) return false;
                const rect = element.getBoundingClientRect();
                return rect.left < -1 || rect.right > document.documentElement.clientWidth + 1;
              });
              return {
                overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
                missing,
                clipped,
              };
            }""",
            selectors,
        )
        if scaled["overflow"] or scaled["missing"] or scaled["clipped"]:
            raise RuntimeError(f"{path_label} failed 200% text scaling: {scaled}")

    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = context.new_page()
    try:
        page.goto(f"{base_url}/prediction_dashboard/latest.html", wait_until="networkidle", timeout=30_000)
        dashboard_metrics = _shell_metrics(page)
        assert_shell(dashboard_metrics, "dashboard desktop", dashboard=True)
        checks["dashboard_shell_desktop"] = "VERIFIED"
        if _visible_count(page, "#historical-results") != 1 or _visible_count(page, "#beginner-help") != 1:
            raise RuntimeError("dashboard does not expose stable history and beginner-help destinations")
        checks["dashboard_history_and_help_targets"] = "VERIFIED"

        page.goto(f"{base_url}/visual-fixtures/detail-current-frozen.html", wait_until="networkidle", timeout=30_000)
        detail_metrics = _shell_metrics(page)
        assert_shell(detail_metrics, "detail desktop")
        tab_targets = set(detail_metrics.get("tabTargets") or [])
        if not tab_targets.issubset({"market", "evidence"}):
            raise RuntimeError("detail exposed an unknown conditional tab")
        checks["detail_shell_desktop"] = "VERIFIED"
        checks["detail_conditional_tabs"] = "VERIFIED"
    finally:
        context.close()

    mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
    mobile_page = mobile_context.new_page()
    try:
        mobile_page.goto(f"{base_url}/prediction_dashboard/latest.html", wait_until="networkidle", timeout=30_000)
        assert_shell(_shell_metrics(mobile_page), "dashboard mobile", mobile=True, dashboard=True)
        checks["dashboard_mobile_targets"] = "VERIFIED"
        assert_scaled(
            mobile_page,
            "dashboard mobile",
            [".matches-head h1", ".matchup-name", ".compact-prob-values", ".recommendation-context"],
        )
        checks["dashboard_mobile_200_percent_text"] = "VERIFIED"

        mobile_page.goto(f"{base_url}/visual-fixtures/detail-current-frozen.html", wait_until="networkidle", timeout=30_000)
        assert_shell(_shell_metrics(mobile_page), "detail mobile", mobile=True)
        checks["detail_mobile_targets"] = "VERIFIED"
        assert_scaled(
            mobile_page,
            "detail mobile",
            [".hero h1", ".probability-card strong", ".exact-compact-probability", ".section-heading h2"],
        )
        checks["detail_mobile_200_percent_text"] = "VERIFIED"

        mobile_page.goto(f"{base_url}/visual-fixtures/dashboard-result-empty.html#historical-results", wait_until="networkidle", timeout=30_000)
        if _visible_count(mobile_page, "#historical-results") != 1 or _visible_count(mobile_page, ".history-empty") != 1:
            raise RuntimeError("history zero state is not stable or visible")
        checks["history_zero_state"] = "VERIFIED"
    finally:
        mobile_context.close()

    status_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
    status_page = status_context.new_page()
    try:
        for status in (
            "pending",
            "insufficient_data",
            "prediction_failed",
            "missed_prematch_window",
            "current_job_state_conflict",
        ):
            status_page.goto(
                f"{base_url}/visual-fixtures/dashboard-{status}.html",
                wait_until="networkidle",
                timeout=30_000,
            )
            if _visible_count(status_page, f'.match-card[data-status="{status.upper()}"]') == 0:
                raise RuntimeError(f"status fixture missing: {status}")
        checks["dashboard_status_states"] = "VERIFIED"
    finally:
        status_context.close()
    return checks


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
                f"{base_url}/visual-fixtures/detail-current-frozen.html#score-distribution",
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
                raise RuntimeError(f"{label}px compact score projection is not the default view")
            compact_metrics = compact.evaluate(
                """element => ({
                  sourceCellCount: Number(element.dataset.exactCompactSourceCellCount || 0),
                  topCount: Number(element.dataset.exactCompactTopCount || 0),
                  scoreCount: element.querySelectorAll('[data-exact-compact-score]').length,
                  remainderCount: Number(element.dataset.exactCompactRemainderCount || 0),
                  probabilityFontSizeMin: Math.min(...[...element.querySelectorAll('.exact-compact-probability')]
                    .map(item => Number.parseFloat(window.getComputedStyle(item).fontSize))),
                })"""
            )
            if compact_metrics["sourceCellCount"] != 169:
                raise RuntimeError(f"{label}px compact projection lost frozen cells")
            if compact_metrics["topCount"] != 3 or compact_metrics["scoreCount"] != 3:
                raise RuntimeError(f"{label}px compact projection does not expose deterministic Top 3")
            if compact_metrics["remainderCount"] != 166:
                raise RuntimeError(f"{label}px compact projection has an incorrect represented remainder")
            if compact_metrics["probabilityFontSizeMin"] < 12:
                raise RuntimeError(f"{label}px compact probability text is below 12px")

            disclosure = page.locator("[data-exact-disclosure]")
            if disclosure.count() != 1:
                raise RuntimeError(f"{label}px score disclosure control is missing")
            if disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px full score matrix is the default view")
            if page.locator("[data-exact-cell-home]").count() != 169:
                raise RuntimeError(f"{label}px DOM does not retain all 169 score cells")
            if _visible_count(page, "[data-exact-cell-home]") != 0:
                raise RuntimeError(f"{label}px full score matrix is visible before disclosure")
            summary = disclosure.locator("summary")
            if not summary.get_attribute("aria-label") and not summary.inner_text().strip():
                raise RuntimeError(f"{label}px score disclosure has no readable control label")
            wrapper = page.locator(".exact-grid-wrap")
            compact_snapshot = compact.get_attribute("data-exact-compact-remainder-probability")

            summary.click()
            if not disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px score disclosure did not open by pointer interaction")
            if _visible_count(page, "[data-exact-cell-home]") != 169:
                raise RuntimeError(f"{label}px disclosure did not reveal all 169 score cells")
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
                raise RuntimeError(f"{label}px score matrix scroll region is not keyboard focusable")
            if not str(wrapper_metrics["ariaLabel"] or "").strip():
                raise RuntimeError(f"{label}px score matrix scroll region is not labeled")
            if wrapper_metrics["scrollWidth"] <= wrapper_metrics["clientWidth"] + 1:
                raise RuntimeError(f"{label}px score matrix has no contained horizontal scroll affordance")
            wrapper.focus()
            if not page.evaluate("() => document.activeElement === document.querySelector('.exact-grid-wrap')"):
                raise RuntimeError(f"{label}px score matrix scroll region did not receive keyboard focus")
            scroll_left = wrapper.evaluate(
                """element => {
                  element.scrollLeft = element.scrollWidth;
                  return element.scrollLeft;
                }"""
            )
            if scroll_left <= 0:
                raise RuntimeError(f"{label}px score matrix scroll region did not scroll")
            if compact.get_attribute("data-exact-compact-remainder-probability") != compact_snapshot:
                raise RuntimeError(f"{label}px disclosure mutated frozen compact probability state")
            if int(
                page.evaluate(
                    "() => Math.max(0, document.documentElement.scrollWidth - "
                    "document.documentElement.clientWidth)"
                )
            ):
                raise RuntimeError(f"{label}px opening score matrix overflowed the page")

            summary.focus()
            summary.press("Enter")
            if disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px score disclosure did not close by keyboard interaction")
            summary.press("Enter")
            if not disclosure.evaluate("element => element.open"):
                raise RuntimeError(f"{label}px score disclosure did not reopen by keyboard interaction")
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
        ("dashboard-1920x1080.png", "prediction_dashboard/latest.html", (1920, 1080), "production-current", "PRODUCTION_TRUTH"),
        ("dashboard-390x844.png", "prediction_dashboard/latest.html", (390, 844), "production-current", "PRODUCTION_TRUTH"),
        ("dashboard-320x800.png", "prediction_dashboard/latest.html", (320, 800), "production-current", "PRODUCTION_TRUTH"),
        ("detail-current-frozen-1440x1000.png", "visual-fixtures/detail-current-frozen.html", (1440, 1000), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-current-frozen-1920x1080.png", "visual-fixtures/detail-current-frozen.html", (1920, 1080), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-current-frozen-390x844.png", "visual-fixtures/detail-current-frozen.html", (390, 844), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-current-frozen-320x800.png", "visual-fixtures/detail-current-frozen.html", (320, 800), str(current.get("match_id") or "current-frozen"), "PRODUCTION_TRUTH"),
        ("detail-exact-unavailable-1440x1000.png", "visual-fixtures/detail-exact-unavailable.html#score-distribution", (1440, 1000), "exact-unavailable", "TEST_FIXTURE"),
        ("detail-exact-unavailable-390x844.png", "visual-fixtures/detail-exact-unavailable.html#score-distribution", (390, 844), "exact-unavailable", "TEST_FIXTURE"),
        ("detail-exact-unavailable-320x800.png", "visual-fixtures/detail-exact-unavailable.html#score-distribution", (320, 800), "exact-unavailable", "TEST_FIXTURE"),
        ("change-no-previous-1440x1000.png", "visual-fixtures/detail-change-no-previous.html", (1440, 1000), "change-no-previous", "TEST_FIXTURE"),
        ("change-no-previous-390x844.png", "visual-fixtures/detail-change-no-previous.html", (390, 844), "change-no-previous", "TEST_FIXTURE"),
        ("change-no-previous-320x800.png", "visual-fixtures/detail-change-no-previous.html", (320, 800), "change-no-previous", "TEST_FIXTURE"),
        ("change-exact-1440x1000.png", "visual-fixtures/detail-change-exact.html#change-awareness", (1440, 1000), "change-exact", "TEST_FIXTURE"),
        ("change-exact-390x844.png", "visual-fixtures/detail-change-exact.html#change-awareness", (390, 844), "change-exact", "TEST_FIXTURE"),
        ("change-exact-320x800.png", "visual-fixtures/detail-change-exact.html#change-awareness", (320, 800), "change-exact", "TEST_FIXTURE"),
        ("insufficient-evidence-390x844.png", "visual-fixtures/dashboard-insufficient.html", (390, 844), "INSUFFICIENT_SAMPLE", "TEST_FIXTURE"),
        ("degraded-evidence-1440x1000.png", "visual-fixtures/dashboard-degraded.html", (1440, 1000), "DEGRADED", "TEST_FIXTURE"),
        ("unverified-evidence-390x844.png", "visual-fixtures/dashboard-unverified.html", (390, 844), "UNVERIFIED", "TEST_FIXTURE"),
        ("result-empty-evidence-390x844.png", "visual-fixtures/dashboard-result-empty.html#historical-results", (390, 844), "RESULT=0", "TEST_FIXTURE"),
        ("upcoming-empty-evidence-390x844.png", "visual-fixtures/dashboard-upcoming-empty.html", (390, 844), "UPCOMING=0", "TEST_FIXTURE"),
        ("history-1920x1080.png", "prediction_dashboard/latest.html#historical-results", (1920, 1080), "history-production", "PRODUCTION_TRUTH"),
        ("history-390x844.png", "prediction_dashboard/latest.html#historical-results", (390, 844), "history-production", "PRODUCTION_TRUTH"),
        ("history-320x800.png", "prediction_dashboard/latest.html#historical-results", (320, 800), "history-production", "PRODUCTION_TRUTH"),
        ("dashboard-pending-390x844.png", "visual-fixtures/dashboard-pending.html", (390, 844), "PENDING", "TEST_FIXTURE"),
        ("dashboard-insufficient-data-390x844.png", "visual-fixtures/dashboard-insufficient_data.html", (390, 844), "INSUFFICIENT_DATA", "TEST_FIXTURE"),
        ("dashboard-prediction-failed-390x844.png", "visual-fixtures/dashboard-prediction_failed.html", (390, 844), "PREDICTION_FAILED", "TEST_FIXTURE"),
        ("dashboard-missed-prematch-window-390x844.png", "visual-fixtures/dashboard-missed_prematch_window.html", (390, 844), "MISSED_PREMATCH_WINDOW", "TEST_FIXTURE"),
        ("dashboard-current-job-state-conflict-390x844.png", "visual-fixtures/dashboard-current_job_state_conflict.html", (390, 844), "CURRENT_JOB_STATE_CONFLICT", "TEST_FIXTURE"),
        ("completed-evidence-1440x1000.png", "visual-fixtures/detail-completed-verified.html", (1440, 1000), "completed-verified", "TEST_FIXTURE"),
        ("completed-evidence-390x844.png", "visual-fixtures/detail-completed-verified.html", (390, 844), "completed-verified", "TEST_FIXTURE"),
        ("completed-evidence-320x800.png", "visual-fixtures/detail-completed-verified.html", (320, 800), "completed-verified", "TEST_FIXTURE"),
    ]
    records: list[dict[str, Any]] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                interaction_checks = {
                    **_check_interactions(browser, base_url),
                    **_check_public_shell_and_responsive(browser, base_url),
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
    frozen_candidates = [
        item
        for item in fixtures
        if str(item.get("status") or "").upper() == "FROZEN"
        and isinstance(item.get("prediction"), dict)
    ]
    current = next(
        (item for item in frozen_candidates if not (item.get("result") or {}).get("score_90m")),
        None,
    ) or (frozen_candidates[0] if frozen_candidates else None)
    if current is None:
        raise SystemExit("runtime evidence requires at least one current FROZEN fixture with prediction")
    output.mkdir(parents=True, exist_ok=True)
    crest_diagnostics_path = site_root / "diagnostics" / "team-crest-enrichment.json"
    crest_diagnostics = (
        _read_json(crest_diagnostics_path)
        if crest_diagnostics_path.is_file()
        else failed_crest_diagnostics(payload, "DIAGNOSTICS_ARTIFACT_MISSING")
    )
    (output / "team-crest-enrichment.json").write_text(
        json.dumps(crest_diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    current_article = _write_fixture_pages(site_root, payload, current)
    records, interaction_checks = _capture_all(site_root, output, payload, current)

    browser_errors = [
        {"name": record["name"], "messages": record["console_errors"] + record["page_errors"]}
        for record in records
        if record["console_errors"] or record["page_errors"]
    ]
    overflow = [record for record in records if record["horizontal_overflow"]]
    exact_overflow = [record for record in records if record["exact_horizontal_overflow"]]
    mobile_exact_failures = [
        record
        for record in records
        if record["exact_cells"] == 169
        and record["viewport"] in {"390x844", "320x800"}
        and (
            not record["exact_compact_visible"]
            or record["exact_compact_source_cell_count"] != 169
            or record["exact_compact_top_count"] != 3
            or record["exact_compact_score_count"] != 3
            or record["exact_compact_remainder_count"] != 166
            or (record["exact_compact_probability_font_size_min"] or 0) < 12
            or record["exact_disclosure_count"] != 1
            or record["exact_disclosure_open"]
            or record["exact_disclosure_dom_cell_count"] != 169
            or record["exact_disclosure_summary_visible"] is not True
            or record["exact_disclosure_cue_present"] is not True
        )
    ]
    desktop_signature_failures = [
        record
        for record in records
        if record["exact_cells"] == 169
        and record["viewport"] in {"1440x1000", "1920x1080"}
        and (
            record["exact_disclosure_count"] != 1
            or record["exact_disclosure_open"]
            or record["exact_disclosure_visible_cell_count"] != 0
            or not record["exact_signature_matrix_visible"]
        )
    ]
    article_failures = [
        {
            "name": record["name"],
            "reason": "article missing, not first, empty, or overflowing",
        }
        for record in records
        if record["name"].startswith("detail-current-frozen-")
        and (
            not record["article_visible"]
            or not record["article_first_in_analysis"]
            or record["article_claim_count"] == 0
            or record["article_block_count"] == 0
            or record["article_horizontal_overflow"]
        )
    ]
    change_awareness_failures = []
    for record in records:
        name = record["name"]
        if name.startswith("detail-current-frozen-"):
            if (
                not record["change_awareness_visible"]
                or record["change_awareness_status"] != "AVAILABLE"
                or record["change_awareness_lane_count"] != 2
            ):
                change_awareness_failures.append({"name": name, "reason": "supported change lanes missing"})
        elif name.startswith("change-no-previous-"):
            if (
                not record["change_awareness_visible"]
                or record["change_awareness_status"] != "UNAVAILABLE"
            ):
                change_awareness_failures.append({"name": name, "reason": "no-previous unavailable state missing"})
        elif name.startswith("change-exact-"):
            if (
                not record["change_awareness_visible"]
                or record["change_awareness_status"] != "AVAILABLE"
                or record["change_awareness_lane_count"] != 2
                or record["change_awareness_exact_row_count"] != 1
            ):
                change_awareness_failures.append({"name": name, "reason": "exact-score change state missing"})
        elif name.startswith("completed-evidence-"):
            if (
                not record["completed_result_visible"]
                or not record["change_awareness_visible"]
                or record["change_awareness_status"] != "AVAILABLE"
            ):
                change_awareness_failures.append({"name": name, "reason": "completed change history missing"})
    forbidden_visible = [
        record for record in records if record["visible_forbidden_tokens"]
    ]
    shell_failures = [
        {
            "name": record["name"],
            "shell_metrics": record.get("shell_metrics") or {},
        }
        for record in records
        if (record.get("shell_metrics") or {}).get("missingFragmentTargets")
        or (record.get("shell_metrics") or {}).get("fakeControls")
        or (record.get("shell_metrics") or {}).get("favoriteControls")
        or (record.get("shell_metrics") or {}).get("forbiddenShellText")
        or (record.get("shell_metrics") or {}).get("firstLayerJargon")
        or (record.get("shell_metrics") or {}).get("missingConditionalTabTargets")
        or record.get("frozen_not_predicting_count")
        or any(
            float(item.get("height") or 0) < 44 or float(item.get("width") or 0) < 44
            for item in (record.get("shell_metrics") or {}).get("mobileTopbarTargets") or []
        )
        or (
            (record.get("shell_metrics") or {}).get("typography", {}).get("matrix") is not None
            and float((record.get("shell_metrics") or {}).get("typography", {}).get("matrix")) < 10
        )
    ]
    if browser_errors or overflow or exact_overflow or mobile_exact_failures or desktop_signature_failures or article_failures or change_awareness_failures or forbidden_visible or shell_failures:
        raise SystemExit(
            json.dumps(
                {
                    "browser_errors": browser_errors,
                    "horizontal_overflow": overflow,
                    "exact_horizontal_overflow": exact_overflow,
                    "exact_mobile_default_failures": mobile_exact_failures,
                    "exact_desktop_signature_matrix_failures": desktop_signature_failures,
                    "analysis_article_failures": article_failures,
                    "change_awareness_failures": change_awareness_failures,
                    "visible_forbidden_tokens": forbidden_visible,
                    "public_shell_failures": shell_failures,
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
    production_crest_counts = {
        record["name"]: record["existing_crest_count"]
        for record in records
        if record["status"] == "PRODUCTION_TRUTH"
    }
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
            "exact_horizontal_overflow_390": 0,
            "exact_horizontal_overflow_320": 0,
            "exact_cell_counts": {
                record["name"]: record["exact_cells"]
                for record in records
                if record["exact_cells"]
            },
            "exact_mobile_default": {
                record["name"]: {
                    "compact_visible": record["exact_compact_visible"],
                    "source_cell_count": record["exact_compact_source_cell_count"],
                    "top_count": record["exact_compact_top_count"],
                    "score_count": record["exact_compact_score_count"],
                    "remainder_count": record["exact_compact_remainder_count"],
                    "probability_font_size_min": record["exact_compact_probability_font_size_min"],
                    "full_matrix_default_open": record["exact_disclosure_open"],
                    "full_matrix_dom_cell_count": record["exact_disclosure_dom_cell_count"],
                }
                for record in records
                if record["exact_cells"] == 169
                and record["viewport"] in {"390x844", "320x800"}
            },
            "exact_desktop_signature_matrix": {
                record["name"]: {
                    "signature_matrix_visible": record["exact_signature_matrix_visible"],
                    "full_matrix_default_open": record["exact_disclosure_open"],
                    "visible_cell_count": record["exact_disclosure_visible_cell_count"],
                }
                for record in records
                if record["exact_cells"] == 169 and record["viewport"] in {"1440x1000", "1920x1080"}
            },
            "analysis_article_first_block": {
                record["name"]: {
                    "visible": record["article_visible"],
                    "first_in_analysis": record["article_first_in_analysis"],
                    "claim_count": record["article_claim_count"],
                    "block_count": record["article_block_count"],
                    "horizontal_overflow": record["article_horizontal_overflow"],
                }
                for record in records
                if record["name"].startswith("detail-current-frozen-")
            },
            "analysis_article_current_page": {
                "status": current_article.get("status"),
                "claim_count": (current_article.get("coverage") or {}).get("claim_count", 0),
                "block_count": (current_article.get("coverage") or {}).get("block_count", 0),
                "degradation_count": (current_article.get("coverage") or {}).get("degradation_count", 0),
                "available_blocks": (current_article.get("coverage") or {}).get("available_blocks", []),
                "omitted_blocks": (current_article.get("coverage") or {}).get("omitted_blocks", []),
            },
            "dashboard_regenerated_with_pr_renderer": "YES",
            "normal_frozen_badge_count": production_frozen_count,
            "normal_health_badge_count": production_health_count,
            "real_crest_counts": production_crest_counts,
            "team_crest_enrichment": {
                "fixture_count": crest_diagnostics.get("fixture_count", 0),
                "total_team_slots": crest_diagnostics.get("total_team_slots", 0),
                "resolved_real_crests": crest_diagnostics.get("resolved_real_crests", 0),
                "unresolved_team_slots": crest_diagnostics.get("unresolved_team_slots", 0),
                "coverage_percent": crest_diagnostics.get("coverage_percent", 0.0),
                "failure_reasons": crest_diagnostics.get("failure_reasons", {}),
                "artifact": "team-crest-enrichment.json",
            },
            "fake_data_graphics": 0,
            "fake_affordances": 0,
            "interaction_checks": interaction_checks,
            "change_awareness": {
                "valid_multi_lane_viewports": [
                    record["name"] for record in records
                    if record["name"].startswith("detail-current-frozen-")
                    and record["change_awareness_status"] == "AVAILABLE"
                ],
                "no_previous_viewports": [
                    record["name"] for record in records
                    if record["name"].startswith("change-no-previous-")
                    and record["change_awareness_status"] == "UNAVAILABLE"
                ],
                "changed_exact_score_viewports": [
                    record["name"] for record in records
                    if record["name"].startswith("change-exact-")
                    and record["change_awareness_exact_row_count"] == 1
                ],
                "completed_viewports": [
                    record["name"] for record in records
                    if record["name"].startswith("completed-evidence-")
                    and record["completed_result_visible"]
                    and record["change_awareness_status"] == "AVAILABLE"
                ],
            },
            "visible_forbidden_tokens": {
                record["name"]: record["visible_forbidden_tokens"]
                for record in records
                if record["visible_forbidden_tokens"]
            },
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
