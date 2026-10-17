import importlib.util
import json
from pathlib import Path

import pytest

P = Path(__file__).parents[1] / "scripts/pme_forward_public.py"
spec = importlib.util.spec_from_file_location("forward_public", P)
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


def report():
    methods = {}
    for m in pub.METHODS:
        methods[m] = {"n": 2, "nll": 1.2, "rps_1x2": .5, "top1": 1, "top3": 2,
                      "top5": 2, "expected_1_1": .4, "observed_1_1": 1,
                      "delta_vs_champion": {"secret": "discard"}}
    segs = []
    for i, day in enumerate(("2026-01-01", "2026-01-02", "2026-01-03")):
        segs.append({"utc_matchday": day, "training_n": 10 + i, "training_days": 3 + i,
                     "test_n": 2, "coefficients": {f: 1.0 for f in pub.FAMILIES}, "methods": methods,
                     "private_path": "never publish", "raw_matrix": [[1, 2]]})
    return {"schema": pub.SCHEMA, "mode": "RESEARCH_ONLY_PREQUENTIAL", "evaluated_days": 3,
            "segments": segs, "raw_quote": "private"}


def test_public_allowlist_weighting_and_page_bounds(tmp_path, monkeypatch):
    raw = report()
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    site = tmp_path / "site"
    base = site / "research"
    base.mkdir(parents=True)
    scorecard = base / "scorecard.html"
    scorecard.write_text("<html><main><h1>Scorecard</h1></main></html>", encoding="utf-8")
    assert pub.publish_optional(tmp_path, site)
    data = json.loads((base / "pme-forward.json").read_text(encoding="utf-8"))
    page = (base / "pme-forward.html").read_text(encoding="utf-8")
    assert data["n"] == 6 and data["pooled"]["champion"]["nll"] == 1.2
    assert data["pooled"]["champion"]["expected_1_1"] == pytest.approx(1.2)
    assert data["pooled"]["champion"]["observed_1_1"] == 3
    assert "raw_quote" not in json.dumps(data) and "private_path" not in json.dumps(data)
    assert page.count('class="research-forward-score-link"') == 1
    assert page.count('href="scorecard.html"') == 1
    assert "quote event clocks are unverified" in page
    assert "Expected / observed actual 1-1" in page and "1.20 / 3" in page
    assert scorecard.read_text(encoding="utf-8").count('class="research-forward-score-link"') == 1
    assert len(page.encode()) <= 120 * 1024
    scorecard_after_first = scorecard.read_text(encoding="utf-8")
    assert pub.publish_optional(tmp_path, tmp_path / "site")
    assert (base / "pme-forward.html").read_text(encoding="utf-8").count('class="research-forward-score-link"') == 1
    assert scorecard.read_text(encoding="utf-8").count('class="research-forward-score-link"') == 1
    assert scorecard.read_text(encoding="utf-8") == scorecard_after_first


def test_rejects_nan_invalid_fields_and_oversized_segments(tmp_path, monkeypatch):
    raw = report(); raw["segments"][0]["methods"]["champion"]["nll"] = float("nan")
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    assert not (tmp_path / "site/research/pme-forward.html").exists()
    raw = report(); raw["segments"][0]["coefficients"]["pmf_power"] = 999
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    raw = report(); raw["segments"][0]["methods"]["pmf_power"]["observed_1_1"] = 0
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    raw = report(); raw["segments"].extend(raw["segments"] * 2000)
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False


def test_xss_injection_rejected_and_unavailable_has_no_broken_link(tmp_path, monkeypatch):
    raw = report(); raw["segments"][0]["utc_matchday"] = '<img src=x onerror=alert(1)>'
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    assert not (tmp_path / "site/research/pme-forward.html").exists()
    base = tmp_path / "site/research"
    base.mkdir(parents=True)
    scorecard = base / "scorecard.html"
    scorecard.write_text("<main>paired page</main>", encoding="utf-8")
    monkeypatch.setattr(pub.calibration, "build", lambda root: (_ for _ in ()).throw(FileNotFoundError("fixture missing")))
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    assert not (tmp_path / "site/research/pme-forward.html").exists()
    assert scorecard.read_text(encoding="utf-8") == "<main>paired page</main>"


def test_missing_scorecard_does_not_write_forward_artifacts_or_change_paired_output(tmp_path, monkeypatch):
    raw = report()
    monkeypatch.setattr(pub.calibration, "build", lambda root: json.dumps(raw).encode())
    base = tmp_path / "site/research"
    base.mkdir(parents=True)
    paired = base / "pme-paired.html"
    paired.write_text("paired stays as-is", encoding="utf-8")
    assert pub.publish_optional(tmp_path, tmp_path / "site") is False
    assert paired.read_text(encoding="utf-8") == "paired stays as-is"
    assert not (base / "pme-forward.html").exists()
    assert not (base / "pme-forward.json").exists()

