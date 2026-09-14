from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.match_analysis import assemble_match_analysis  # noqa: E402
from scripts.match_detail import _render_match_analysis_article, render_match_detail  # noqa: E402


DATE = "2026-09-11"
BENCHMARK_IDS = ("2996143", "2995342", "3019134", "2993794", "3018812")


def _contract(match_id: str) -> dict:
    return assemble_match_analysis(DATE, match_id)


def test_five_benchmark_articles_are_connected_and_public_safe():
    for match_id in BENCHMARK_IDS:
        article = _contract(match_id)["match_analysis_article"]

        assert article["contract_version"] == "match_analysis_article.v2"
        assert article["status"] == "AVAILABLE"
        assert [item["role"] for item in article["paragraphs"]] == [
            "thesis",
            "recent_process",
            "teams_and_rest",
            "market",
            "counterevidence",
            "forecast",
        ]
        serialized = json.dumps(article, ensure_ascii=False).casefold()
        for forbidden in (
            "parse_uncertain",
            "model_family",
            "release_version",
            "data_grade",
            "truth gate",
            "xg",
            "sharp",
            "trap",
        ):
            assert forbidden not in serialized


def test_benchmark_primitives_keep_alignment_outlier_and_conflict_visible():
    az = _contract("2996143")["match_analysis_article"]
    assert az["result_process_alignment"] == "supportive"
    assert az["market_relationship"] == "aligned"
    assert az["identifiability"] == "HIGH"

    nurnberg = _contract("3019134")["match_analysis_article"]
    assert nurnberg["result_process_alignment"] == "contradictory"
    assert nurnberg["market_relationship"] == "conflicting"
    assert nurnberg["outlier_concentration"] == {
        "status": "PRESENT",
        "side": "away",
        "dimension": "goals_for",
        "value": 9,
        "share": 0.692308,
        "window_total": 13,
        "match_date": "2026-08-22",
        "discount_raw_totals": True,
    }
    assert nurnberg["identifiability"] == "LOW"
    assert "9" in nurnberg["paragraphs"][4]["text"]

    venezia = _contract("2993794")["match_analysis_article"]
    union = _contract("3018812")["match_analysis_article"]
    assert venezia["market_relationship"] == "conflicting"
    assert venezia["identifiability"] == "LOW"
    assert union["market_relationship"] == "conflicting"
    assert union["identifiability"] in {"MEDIUM", "LOW"}


def test_low_identifiability_weakens_exact_score_language_and_article_is_first():
    contract = _contract("2993794")
    article = contract["match_analysis_article"]
    assert article["forecast"]["exact_score_cluster"]["primary_score"] is None
    assert article["forecast"]["exact_score_cluster"]["unique_score_allowed"] is False

    html = render_match_detail(contract)
    rendered_article = _render_match_analysis_article(contract)
    article_start = html.index('id="analysis-article"')
    primary_start = html.index('class="grid3 primary-grid"')
    assert article_start < primary_start
    assert 'data-article-version="match_analysis_article.v2"' in rendered_article
    assert 'data-identifiability="LOW"' in rendered_article
    assert "不设唯一首选" in rendered_article


def test_article_is_deterministic_without_mutating_prediction_record():
    prediction_path = ROOT / "data/model_governance/predictions/FBOS-PRED-2c1954b82f30ee7155f39b4e.json"
    before = prediction_path.read_bytes()
    first = copy.deepcopy(_contract("3019134")["match_analysis_article"])
    second = _contract("3019134")["match_analysis_article"]
    assert first == second
    assert prediction_path.read_bytes() == before
