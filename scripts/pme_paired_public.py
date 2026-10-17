"""Public, research-only presentation for GF228 paired historical evaluation."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "gf228.paired_champion_market.v1"
METHODS = ("champion", "market")
TOPS = ("top1", "top3", "top5")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid(report: Any) -> bool:
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA:
        return False
    n = report.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return False
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return False
    for method in METHODS:
        row = summary.get(method)
        if not isinstance(row, dict):
            return False
        previous = -1
        for key in TOPS:
            count = row.get(key)
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= n or count < previous:
                return False
            previous = count
        if any(not _number(row.get(key)) for key in ("nll", "rps")):
            return False
        if not 0 <= row["rps"] <= 1 or row["nll"] < 0:
            return False
    calibration = report.get("score_calibration")
    if calibration is not None:
        if not isinstance(calibration, dict) or type(calibration.get("n")) is not int or calibration["n"] != n: return False
        observed, methods = calibration.get("observed1_1_count"), calibration.get("methods")
        if type(observed) is not int or not 0 <= observed <= n or not isinstance(methods, dict): return False
        for method in METHODS:
            row = methods.get(method)
            if not isinstance(row, dict) or type(row.get("observed_1_1_count")) is not int or row["observed_1_1_count"] != observed: return False
            for key in ("expected_1_1_count", "expected_top1_hits"):
                if not _number(row.get(key)) or not 0 <= row[key] <= n: return False
            for key in ("observed_1_1_count", "modal_1_1_top1_count", "observed_top1_hits"):
                if type(row.get(key)) is not int or not 0 <= row[key] <= n: return False
            subset = row.get("one_one_modal_subset")
            if not isinstance(subset, dict) or type(subset.get("count")) is not int or not 0 <= subset["count"] <= n: return False
            if subset["count"] != row["modal_1_1_top1_count"] or not _number(subset.get("expected_1_1_count")) or not 0 <= subset["expected_1_1_count"] <= subset["count"]: return False
            if type(subset.get("observed_1_1_count")) is not int or not 0 <= subset["observed_1_1_count"] <= min(subset["count"], observed): return False
        if not isinstance(calibration.get("description"), str) or not calibration["description"]: return False
    deltas = report.get("deltas")
    if not isinstance(deltas, dict):
        return False
    for metric in ("nll", "rps"):
        item = deltas.get(metric)
        if not isinstance(item, dict) or not _number(item.get("market_minus_champion_mean")):
            return False
        ci = item.get("paired_bootstrap_95_ci")
        if not isinstance(ci, list) or len(ci) != 2 or not all(_number(x) for x in ci) or ci[0] > ci[1]:
            return False
    if "robustness" in report:
        rob=report["robustness"]
        if not isinstance(rob,dict) or type(rob.get("cluster_days")) is not int or rob["cluster_days"]<3: return False
        thirds=rob.get("chronological_thirds")
        if not isinstance(thirds,list) or len(thirds)!=3: return False
        if any(not isinstance(x,dict) or type(x.get("n_matches")) is not int or x["n_matches"]<0 for x in thirds): return False
        if sum(x["n_matches"] for x in thirds)!=n: return False
        for x in thirds:
            if type(x.get("n_matchdays")) is not int or x["n_matchdays"]<0: return False
            if any(not _number(x.get(k)) for k in ("market_minus_champion_mean_nll","market_minus_champion_mean_rps")): return False
            if any(type(x.get(k)) is not int or x[k]<0 for k in ("champion_top1","market_top1")): return False
        for metric in ("nll","rps"):
            ci=report["deltas"][metric].get("matchday_cluster_bootstrap_95_ci")
            if not isinstance(ci,list) or len(ci)!=2 or not all(_number(v) for v in ci) or ci[0]>ci[1]: return False
    if 'capture_provenance' in report:
        q=report['capture_provenance']
        if not isinstance(q,dict) or type(q.get('n')) is not int or q['n']!=n: return False
        verified=q.get('provider_quote_clock_verified_matches')
        missing=q.get('provider_quote_clock_missing_matches')
        if type(verified) is not int or type(missing) is not int or verified<0 or missing<0 or verified+missing!=n: return False
        if q.get('source_capture_before_kickoff')!=n: return False
        if q.get('promotion_gate') not in ('BLOCKED_UPSTREAM_QUOTE_EVENT_CLOCK_UNVERIFIED','RESEARCH_ONLY_NO_AUTOMATIC_PROMOTION'): return False
        if (verified<n)!=(q['promotion_gate']=='BLOCKED_UPSTREAM_QUOTE_EVENT_CLOCK_UNVERIFIED'): return False
        lead=q.get('capture_lead_minutes')
        if not isinstance(lead,dict) or any(not _number(lead.get(k)) for k in ('min','median','max')): return False
        if not 0<lead['min']<=lead['median']<=lead['max']: return False
        bins=q.get('by_capture_lead')
        if not isinstance(bins,dict) or set(bins)!= {'0_to_3h','3_to_12h','over_12h'}: return False
        total=0
        for b in bins.values():
            if not isinstance(b,dict) or type(b.get('n')) is not int or b['n']<0: return False
            total+=b['n']
            for field in ('market_minus_champion_nll','market_minus_champion_rps'):
                val=b.get(field)
                if (b['n']==0 and val is not None) or (b['n']>0 and not _number(val)): return False
        if total!=n: return False
    tests = report.get("tests")
    mcnemar = tests.get("top1_mcnemar") if isinstance(tests, dict) else None
    p = mcnemar.get("two_sided_exact_p") if isinstance(mcnemar, dict) else None
    if not _number(p) or not 0 <= p <= 1:
        return False
    matches = report.get("matches")
    if not isinstance(matches, list) or len(matches) > 5000:
        return False
    if len(matches) != min(n, 250):
        return False
    for match in matches:
        if not isinstance(match, dict) or any(not isinstance(match.get(k), str) or not match[k] for k in ("match_key", "actual")):
            return False
        if not _score(match["actual"]):
            return False
        for method in METHODS:
            side = match.get(method)
            if not isinstance(side, dict) or not isinstance(side.get("score1"), str) or not _score(side["score1"]):
                return False
            if any(type(side.get(k)) is not int or side[k] not in (0, 1) for k in TOPS):
                return False
            if calibration is not None:
                if not _number(side.get("p_1_1")) or not 0 <= side["p_1_1"] <= 1 or not _number(side.get("p_top1")) or not 0 <= side["p_top1"] <= 1:
                    return False
        pair = match.get("top1")
        if not isinstance(pair, dict) or any(type(pair.get(k)) is not int or pair[k] not in (0, 1) for k in METHODS):
            return False
        if calibration is not None and (type(match.get("is_actual_1_1")) is not bool or match["is_actual_1_1"] != (match["actual"] == "1-1")):
            return False
    return True


def _score(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 2 and all(x.isdigit() for x in parts)


def _clean(report: dict[str, Any]) -> dict[str, Any]:
    # Explicit allowlist: raw quote/bookmaker payloads and unrelated provenance are excluded.
    return {
        "schema_version": report["schema_version"],
        "n": report["n"],
        "source_cutoff_policy": report.get("source_cutoff_policy"),
        "quote_clock_policy": report.get("quote_clock_policy"),
        "control": report.get("control"),
        "methods": report.get("methods"),
        "summary": {m: {k: report["summary"][m][k] for k in (*TOPS, "nll", "rps", "score_1_1_top1")} for m in METHODS},
        **({"score_calibration": {"n": report["score_calibration"]["n"], "observed1_1_count": report["score_calibration"]["observed1_1_count"], "description": report["score_calibration"]["description"], "methods": {m: {k: report["score_calibration"]["methods"][m][k] for k in ("expected_1_1_count", "observed_1_1_count", "modal_1_1_top1_count", "expected_top1_hits", "observed_top1_hits")} | {"one_one_modal_subset": dict(report["score_calibration"]["methods"][m]["one_one_modal_subset"])} for m in METHODS}}} if "score_calibration" in report else {}),
        "deltas": {k: {**{x: report["deltas"][k][x] for x in ("market_minus_champion_mean", "paired_bootstrap_95_ci")}, **({"matchday_cluster_bootstrap_95_ci": report["deltas"][k]["matchday_cluster_bootstrap_95_ci"]} if "matchday_cluster_bootstrap_95_ci" in report["deltas"][k] else {})} for k in ("nll", "rps")},
        "robustness": report.get("robustness"),
        "capture_provenance": report.get("capture_provenance"),
        "tests": {"top1_mcnemar": {k: report["tests"]["top1_mcnemar"].get(k) for k in ("champion_only", "market_only", "two_sided_exact_p", "interpretation")}},
        "matches": [{"match_key": r["match_key"], "actual": r["actual"], "top1": r["top1"],
                     **({"is_actual_1_1": r["is_actual_1_1"]} if "is_actual_1_1" in r else {}),
                     "champion": {k: r["champion"][k] for k in ("score1", *TOPS, "p_1_1", "p_top1") if k in r["champion"]},
                     "market": {k: r["market"][k] for k in ("score1", *TOPS, "p_1_1", "p_top1") if k in r["market"]}} for r in report["matches"][:250]],
    }


def _render(data: dict[str, Any]) -> str:
    s = data["summary"]
    esc = lambda value: html.escape(str(value), quote=True)
    rows = "".join("<tr><th>" + label + "</th>" + "".join(f"<td>{s[method][k]} / {data['n']}</td>" for k in TOPS) +
                   f"<td>{s[method]['nll']:.4f}</td><td>{s[method]['rps']:.5f}</td></tr>"
                   for method, label in (("champion", "Champion"), ("market", "市场基线（研究）")))
    matches = "".join("<tr><td>" + esc(r["match_key"]) + "</td><td>" + esc(r["actual"]) + "</td><td>" +
                      esc(r["champion"]["score1"]) + "</td><td>" + esc(r["market"]["score1"]) + "</td></tr>" for r in data["matches"])
    ci_nll = data["deltas"]["nll"]["paired_bootstrap_95_ci"]
    ci_rps = data["deltas"]["rps"]["paired_bootstrap_95_ci"]
    p = data["tests"]["top1_mcnemar"]["two_sided_exact_p"]
    calibration = data.get("score_calibration")
    calibration_html = ""
    if calibration:
        crows = "".join(f"<tr><th>{esc(label)}</th><td>{calibration['methods'][method]['expected_1_1_count']:.2f} / {calibration['methods'][method]['observed_1_1_count']} (modal 1-1 top1: {calibration['methods'][method]['modal_1_1_top1_count']})</td><td>{calibration['methods'][method]['expected_top1_hits']:.2f} / {calibration['methods'][method]['observed_top1_hits']}</td><td>{calibration['methods'][method]['one_one_modal_subset']['count']} / {calibration['methods'][method]['one_one_modal_subset']['expected_1_1_count']:.2f} / {calibration['methods'][method]['one_one_modal_subset']['observed_1_1_count']}</td></tr>" for method, label in (("champion", "Champion"), ("market", "Market")))
        calibration_html = f"<section><h2>冻结比分概率诊断（研究用途）</h2><p>实际 1-1 与汇总 p(1,1) 对比的是概率和观测；众数 1-1 仅统计其为单场最高概率比分，两者并不等同。这是描述性指标，不构成系统性过度自信的证据，也不触发模型晋级。</p><table><thead><tr><th>方法</th><th>预期 / 实际 1-1；众数 1-1 Top1 场数</th><th>预期 / 实际 Top1 命中</th><th>1-1 众数子集：场数 / 预期 / 实际 1-1</th></tr></thead><tbody>{crows}</tbody></table><p>{esc(calibration['description'])}</p></section>"
    robustness = data.get("robustness") or {}
    thirds = robustness.get("chronological_thirds", [])
    cluster_nll = data["deltas"]["nll"].get("matchday_cluster_bootstrap_95_ci", [None,None])
    cluster_rps = data["deltas"]["rps"].get("matchday_cluster_bootstrap_95_ci", [None,None])
    cluster_text = (f"NLL [{cluster_nll[0]:.4f}, {cluster_nll[1]:.4f}], RPS [{cluster_rps[0]:.5f}, {cluster_rps[1]:.5f}] (days={robustness.get('cluster_days')})" if all(_number(x) for x in cluster_nll+cluster_rps) else "not available")
    clock=data.get('capture_provenance') or {}
    if clock:
        nclock=clock['provider_quote_clock_verified_matches']
        lead=clock['capture_lead_minutes']
        bin_names={'0_to_3h':'0–3 小时','3_to_12h':'3–12 小时','over_12h':'12 小时以上'}
        bin_text='；'.join(f"{bin_names[k]} {v['n']} 场（市场−Champion NLL {v['market_minus_champion_nll']:+.4f}）" if v['n'] else f"{bin_names[k]} 0 场" for k,v in clock['by_capture_lead'].items())
        capture_notice=(f"<p><strong>赛前数据时钟审计：</strong>{clock['source_capture_before_kickoff']} / {data['n']} 场在开赛前抓取；"
                        f"最短提前 {lead['min']:.1f} 分钟，中位 {lead['median']:.1f} 分钟，最长 {lead['max']:.1f} 分钟。"
                        f"独立博彩公司报价更新时间完整可核验：{nclock} / {data['n']} 场。"
                        f"分层仅为探索性统计：{esc(bin_text)}。仍不得自动升级 Champion。</p>")
    else:
        capture_notice=''
    third_rows = "".join(f"<tr><td>{x['segment']}</td><td>{esc(x['start_date'])} ? {esc(x['end_date'])}</td><td>{x['n_matches']} / {x['n_matchdays']}</td><td>{x['market_minus_champion_mean_nll']:.4f}</td><td>{x['market_minus_champion_mean_rps']:.5f}</td><td>{x['champion_top1']} ? {x['market_top1']}</td></tr>" for x in thirds)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>历史配对回测 | Football Prediction Day</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f6f7f5;color:#1d2925;font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:980px;margin:36px auto 72px;padding:0 22px}}a{{color:#345d50}}.muted{{color:#61726a;font-size:13px}}h1{{font-size:30px;margin:12px 0 6px}}h2{{font-size:18px;margin:0 0 12px}}section{{background:#fff;border:1px solid #e0e6e1;border-radius:10px;padding:20px;margin:16px 0;overflow:auto}}.notice{{background:#eaf0eb;border-left:3px solid #647e70;padding:14px 18px;border-radius:0 6px 6px 0}}table{{border-collapse:collapse;width:100%;min-width:580px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #edf0ec;font-variant-numeric:tabular-nums}}@media(max-width:600px){{main{{margin-top:18px;padding:0 14px}}section{{padding:13px}}h1{{font-size:26px}}}}
</style></head><body><main><nav><a href="../research/scorecard.html">← 研究复盘</a> · <a href="../prediction_dashboard/latest.html">每日预测</a></nav>
<p class="muted">RESEARCH ONLY / 研究样本</p><h1>历史 {data['n']} 场 Champion / 市场配对回测</h1>
<p>按固定 unique latest_by_match 前瞻记录选择；Champion 使用完全相同 source cutoff 的冻结预测。每场单独配对。</p>
<div class="notice">仅作历史研究，不构成市场模型晋级或替换生产 Champion 的依据。源报价时间戳为 CAPTURE_ONLY（仅记录捕获时间，未验证报价时钟）。完整比分网格：Champion 169 格，市场 441 格。</div>
{capture_notice}
{calibration_html}
<section><h2>配对表现（{data['n']} 场）</h2><table><thead><tr><th>方法</th><th>Top 1</th><th>Top 3</th><th>Top 5</th><th>平均 NLL ↓</th><th>1X2 RPS ↓</th></tr></thead><tbody>{rows}</tbody></table>
<p>市场 − Champion 配对 bootstrap 95% CI：NLL [{ci_nll[0]:.4f}, {ci_nll[1]:.4f}]；RPS [{ci_rps[0]:.5f}, {ci_rps[1]:.5f}]。Top 1 双侧 exact McNemar p = {p:.4f}，未显示显著差异。</p>
<p>Top 1/3/5 命中：{s['champion']['top1']}–{s['market']['top1']} / {s['champion']['top3']}–{s['market']['top3']} / {s['champion']['top5']}–{s['market']['top5']}；NLL：{s['champion']['nll']:.4f}–{s['market']['nll']:.4f}；RPS：{s['champion']['rps']:.5f}–{s['market']['rps']:.5f}。预测众数为 1–1：Champion {s['champion']['score_1_1_top1']} 场，市场 {s['market']['score_1_1_top1']} 场。</p>
<p class="muted">指标基于合法赛前来源与同一截止时间的冻结配对；结果为 90 分钟及伤停补时。市场基线仅供研究，不作生产晋级结论。</p></section>
<section><h2>配对样本明细（最多 250 场）</h2><table><thead><tr><th>比赛键</th><th>实际比分</th><th>Champion Top 1</th><th>市场 Top 1</th></tr></thead><tbody>{matches}</tbody></table></section>
<section><h2>按比赛日聚类的稳健性检查（stability check only; no training or tuning）</h2><p>Matchday-cluster paired bootstrap 95% CI alongside the IID interval: {cluster_text}. Whole UTC matchdays are resampled; evidence, not proof, and not a promotion basis.</p><table><thead><tr><th>Chronological third</th><th>Date range</th><th>Matches / days</th><th>ΔNLL</th><th>ΔRPS</th><th>Top1 Champion / Market</th></tr></thead><tbody>{third_rows or '<tr><td colspan="6">not available</td></tr>'}</tbody></table></section>
</main></body></html>'''


def publish_optional(source: Path, output: Path) -> bool:
    try:
        report = json.loads(Path(source).read_text(encoding="utf-8"))
        if not _valid(report):
            return False
        data = _clean(report)
        page = _render(data)
        base = Path(output) / "research"
        scorecard = base / "scorecard.html"
        if not scorecard.is_file():
            return False
        score_text = scorecard.read_text(encoding="utf-8")
        link = f"<a class='research-historical-paired-link' href='pme-paired.html'>历史 {data['n']} 场配对回测</a>"
        import re
        score_text = re.sub(r"\s*<a class='research-historical-paired-link' href='pme-paired\.html'>.*?</a>", "", score_text)
        pos = score_text.lower().rfind("</main>")
        if pos < 0:
            return False
        score_text = score_text[:pos] + "\n<p>" + link + "</p>\n" + score_text[pos:]
        json_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        (base / "pme-paired.html").write_text(page, encoding="utf-8")
        (base / "pme-paired.json").write_text(json_text, encoding="utf-8")
        scorecard.write_text(score_text, encoding="utf-8")
        # Optional GF240 page runs only after the paired artifact was written.
        # Infer root solely from the canonical report hierarchy; failures are isolated.
        try:
            source_path = Path(source).resolve()
            if (len(source_path.parents) > 3 and
                    source_path.parents[0].name.startswith("pure_market_exact_prospective_") and
                    source_path.parents[1].name == "prediction_quality" and
                    source_path.parents[2].name == "data"):
                repo_root = source_path.parents[3]
                if (repo_root / "scripts" / "pme_forward_public.py").is_file():
                    import pme_forward_public
                    pme_forward_public.publish_optional(repo_root, output)
        except Exception:
            pass
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False
