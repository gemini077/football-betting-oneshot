"""Bounded public rendering for strict GF240 forward score research."""
from __future__ import annotations

import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pme_forward_score_calibration as calibration

SCHEMA = "gf240.forward_score_calibration.v1"
MAX_PAGE = 120 * 1024
FAMILIES = ("one_one_odds", "draw_diagonal_odds", "pmf_power")
METHODS = ("champion", "market_baseline", *FAMILIES)
GRID = {0.75, 1.0, 1.25, 1.5, 2.0}
FORWARD_LINK = "research-forward-score-link"


def _num(x: Any) -> bool:
    return type(x) in (int, float) and math.isfinite(x)


def _valid(raw: Any) -> bool:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or raw.get("mode") != "RESEARCH_ONLY_PREQUENTIAL":
        return False
    segs = raw.get("segments")
    if not isinstance(segs, list) or not 1 <= len(segs) <= 5000 or raw.get("evaluated_days") != len(segs):
        return False
    previous = ""
    for s in segs:
        if not isinstance(s, dict): return False
        day = s.get("utc_matchday")
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day <= previous: return False
        previous = day
        if type(s.get("training_n")) is not int or s["training_n"] < 10 or type(s.get("training_days")) is not int or s["training_days"] < 3:
            return False
        if type(s.get("test_n")) is not int or not 1 <= s["test_n"] <= 5000: return False
        coeff = s.get("coefficients")
        if not isinstance(coeff, dict) or set(coeff) != set(FAMILIES) or any(not _num(coeff[k]) or coeff[k] not in GRID for k in FAMILIES): return False
        methods = s.get("methods")
        if not isinstance(methods, dict) or set(methods) != set(METHODS): return False
        for m in METHODS:
            row = methods[m]
            if not isinstance(row, dict) or row.get("n") != s["test_n"]: return False
            if any(not _num(row.get(k)) for k in ("nll", "rps_1x2", "expected_1_1")): return False
            if row["nll"] < 0 or not 0 <= row["rps_1x2"] <= 1 or not 0 <= row["expected_1_1"] <= row["n"]: return False
            if any(type(row.get(k)) is not int or not 0 <= row[k] <= row["n"] for k in ("top1", "top3", "top5")): return False
            if not row["top1"] <= row["top3"] <= row["top5"]: return False
            if type(row.get("observed_1_1")) is not int or not 0 <= row["observed_1_1"] <= row["n"]: return False
        if len({s["methods"][m]["observed_1_1"] for m in METHODS}) != 1: return False
    return True


def _public(raw: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist; discard identities, PMFs, matrices, and source paths.
    segments = []
    for s in raw["segments"]:
        segments.append({"utc_matchday": s["utc_matchday"], "training_n": s["training_n"],
                         "training_days": s["training_days"], "test_n": s["test_n"],
                         "coefficients": {f: s["coefficients"][f] for f in FAMILIES},
                         "methods": {m: {k: s["methods"][m][k] for k in ("n", "nll", "rps_1x2", "top1", "top3", "top5", "expected_1_1", "observed_1_1")} for m in METHODS}})
    pooled = {}
    total = sum(x["test_n"] for x in segments)
    for m in METHODS:
        pooled[m] = {k: sum(x["test_n"] * x["methods"][m][k] for x in segments) / total
                     for k in ("nll", "rps_1x2")}
        pooled[m]["expected_1_1"] = sum(x["methods"][m]["expected_1_1"] for x in segments)
        pooled[m]["observed_1_1"] = sum(x["methods"][m]["observed_1_1"] for x in segments)
        pooled[m].update({k: sum(x["methods"][m][k] for x in segments) for k in ("top1", "top3", "top5")})
        pooled[m]["n"] = total
    return {"schema": SCHEMA, "mode": "RESEARCH_ONLY_PREQUENTIAL", "n": total,
            "evaluated_days": len(segments), "first_day": segments[0]["utc_matchday"],
            "last_day": segments[-1]["utc_matchday"], "pooled": pooled, "segments": segments,
            "limitations": {"abstains": "Not eligible for production evaluation; no Champion promotion.",
                            "sample": "Only 9 evaluated UTC matchdays; limited evidence.",
                            "quote_clocks": "Provider quote event clocks are unverified."}}


def _render(d: dict[str, Any]) -> str:
    esc = lambda x: html.escape(str(x), quote=True)
    labels = {"champion": "Champion", "market_baseline": "Market baseline", "one_one_odds": "1-1 odds", "draw_diagonal_odds": "Draw-diagonal odds", "pmf_power": "PMF power"}
    metrics = "".join(f"<tr><th>{labels[m]}</th><td>{d['pooled'][m]['n']}</td><td>{d['pooled'][m]['nll']:.4f}</td><td>{d['pooled'][m]['rps_1x2']:.5f}</td><td>{d['pooled'][m]['top1']}</td><td>{d['pooled'][m]['top3']}</td><td>{d['pooled'][m]['top5']}</td><td>{d['pooled'][m]['expected_1_1']:.2f} / {d['pooled'][m]['observed_1_1']}</td></tr>" for m in METHODS)
    rows = []
    for s in d["segments"]:
        c = s["methods"]["champion"]
        coeffs = ", ".join("{}={:g}".format(f, s["coefficients"][f]) for f in FAMILIES)
        rows.append(f"<tr><td>{esc(s['utc_matchday'])}</td><td>{s['training_n']} / {s['training_days']}</td><td>{s['test_n']}</td><td>{esc(coeffs)}</td><td>{c['nll']:.4f}</td><td>{c['rps_1x2']:.5f}</td><td>{c['top1']}/{c['top3']}/{c['top5']}</td><td>{c['expected_1_1']:.2f} / {c['observed_1_1']}</td></tr>")
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Forward score research</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f7f4;color:#1d2925;font:15px/1.6 system-ui,sans-serif}}main{{max-width:1000px;margin:36px auto;padding:0 20px}}section{{background:#fff;border:1px solid #dfe6df;border-radius:12px;padding:20px;margin:16px 0;overflow:auto}}h1{{font-size:30px}}.notice{{background:#eaf0eb;padding:14px;border-left:4px solid #617d6d}}table{{border-collapse:collapse;width:100%;min-width:720px}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #edf0ec;font-variant-numeric:tabular-nums}}a{{color:#315d4e}}.muted{{color:#607168}}</style></head><body><main><nav><a class="research-forward-score-link" href="scorecard.html">Research scorecard</a></nav><p class="muted">RESEARCH ONLY ? GF240 forward-chaining frozen PMFs</p><h1>Forward score calibration</h1><p>Strict frozen Champion score distributions, tuned only on earlier UTC matchdays and evaluated on the next held-out day.</p><div class="notice">Research only: abstains are not eligible for production evaluation and this result does not promote or replace Champion. Evidence covers only {d['evaluated_days']} matchdays ({esc(d['first_day'])}?{esc(d['last_day'])}); provider quote event clocks are unverified.</div><section><h2>Pooled results (N={d['n']}, weighted by evaluated matches)</h2><table><thead><tr><th>Method</th><th>N</th><th>Weighted NLL ?</th><th>Weighted 1X2 RPS ?</th><th>Top 1</th><th>Top 3</th><th>Top 5</th><th>Expected / observed actual 1-1</th></tr></thead><tbody>{metrics}</tbody></table><p class="muted">Top-k values are hit counts; expected actual 1-1 is summed probability mass.</p></section><section><h2>Held-out UTC matchdays</h2><table><thead><tr><th>Test day</th><th>Prior training matches / days</th><th>Test N</th><th>Chosen coefficients</th><th>Champion NLL</th><th>Champion RPS</th><th>Champion Top 1/3/5</th><th>Expected / observed actual 1-1</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section></main></body></html>'''
    if len(page.encode("utf-8")) > MAX_PAGE:
        raise ValueError("forward public page exceeds 120 KiB")
    return page


def publish_optional(repo_root: Path, output: Path) -> bool:
    try:
        raw = json.loads(calibration.build(repo_root).decode("utf-8"))
        if not _valid(raw):
            return False
        data = _public(raw)
        page = _render(data)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(encoded.encode("utf-8")) > MAX_PAGE:
            return False
        base = Path(output) / "research"
        scorecard = base / "scorecard.html"
        if not scorecard.is_file():
            return False
        score_text = scorecard.read_text(encoding="utf-8")
        score_text = re.sub(
            r"\s*<p>\s*<a class=['\"]research-forward-score-link['\"] href=['\"]pme-forward\.html['\"]>.*?</a>\s*</p>",
            "", score_text, flags=re.IGNORECASE | re.DOTALL,
        )
        pos = score_text.lower().rfind("</main>")
        if pos < 0:
            return False
        link = '<a class="research-forward-score-link" href="pme-forward.html">Forward score calibration (research)</a>'
        score_text = score_text[:pos].rstrip() + "\n<p>" + link + "</p>\n" + score_text[pos:]
        if len(page.encode("utf-8")) > MAX_PAGE:
            return False
        # All source and output validation is complete before any published file is changed.
        base.mkdir(parents=True, exist_ok=True)
        (base / "pme-forward.json").write_text(encoded, encoding="utf-8")
        (base / "pme-forward.html").write_text(page, encoding="utf-8")
        scorecard.write_text(score_text, encoding="utf-8")
        return True
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return False

