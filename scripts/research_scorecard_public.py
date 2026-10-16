"""Public, research-only rendering for the optional GF216 paired score review."""
from __future__ import annotations
import html, json, math, re
from pathlib import Path
from typing import Any
SCHEMA = "gf216.strict_paired_score_eval.v1"
ROLLING_SCHEMA = "gf221.rolling_paired_score_eval.v1"
METHODS = (("champion", "Champion"), ("bet365", "\u5e02\u573a\u57fa\u7ebf"), ("blend_50_50", "\u56fa\u5b9a50-50"))
def _valid(p: Any) -> bool:
    if not isinstance(p,dict) or p.get("schema") not in (SCHEMA, ROLLING_SCHEMA): return False
    s,matches=p.get("summary"),p.get("matches")
    if not isinstance(s,dict) or not isinstance(matches,list): return False
    if any(not isinstance(s.get(k),int) or isinstance(s[k],bool) or s[k]<0 for k in ("settled","pending","excluded")): return False
    methods=s.get("methods")
    if not isinstance(methods,dict): return False
    for key,_ in METHODS:
        m=methods.get(key)
        if not isinstance(m,dict) or not isinstance(m.get("nll_matches"),int) or isinstance(m.get("nll_matches"),bool) or m["nll_matches"]<0: return False
        for k in ("top1","top3","top5","mean_nll"):
            v=m.get(k)
            if v is not None and (not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v)): return False
    if len(matches) != s["settled"] + s["pending"] + s["excluded"]: return False
    for k,_ in METHODS:
        m=methods[k]
        if m["nll_matches"] > s["settled"]: return False
        if s["settled"] == 0 and any(m.get(v) is not None for v in ("top1","top3","top5","mean_nll")): return False
        for v in ("top1","top3","top5"):
            p=m.get(v)
            if p is not None and not 0 <= p <= 1: return False
        if m.get("mean_nll") is not None and (m["mean_nll"] < 0 or m["nll_matches"] == 0): return False
    return all(isinstance(r,dict) and isinstance(r.get("match_id"),str) and r.get("state") in ("PENDING","SETTLED","EXCLUDED") for r in matches)
def _fmt(v,pct=False): return "—" if v is None else (f"{v*100:.1f}%" if pct else f"{v:.4f}")
def render_report(p: dict[str,Any]) -> str:
    if not _valid(p): raise ValueError("invalid scorecard schema")
    s=p["summary"]; rows=[]
    rolling=p["schema"]==ROLLING_SCHEMA
    page_title="滚动比分预测复盘" if rolling else "三组比分预测复盘"
    cohort_note="按真实赛前来源冻结，每 UTC 日最多 4 场，非全部赛事覆盖。" if rolling else "固定六场赛前冻结研究样本。"
    for k,label in METHODS:
        m=s["methods"][k]; nll=m["mean_nll"] if m["nll_matches"] else None
        rows.append("<tr><th>"+label+"</th>"+"".join("<td>"+_fmt(m[x],True)+"</td>" for x in ("top1","top3","top5"))+"<td>"+_fmt(nll)+"</td></tr>")
    matches=[]
    for r in p["matches"]:
        matches.append("<tr><td>"+html.escape(r["match_id"],quote=True)+"</td><td>"+html.escape(r["state"],quote=True)+"</td><td>"+html.escape(str(r.get("reason","")),quote=True)+"</td></tr>")
    note="\u5c1a\u65e0\u5df2\u9a8c\u6536\u8d5b\u679c\uff0c\u4e0d\u80fd\u6bd4\u8f83\u547d\u4e2d\u7387\u6216\u63d0\u5347" if s["settled"]==0 else "\u4ec5\u5c55\u793a\u5df2\u9a8c\u6536\u914d\u5bf9\u6837\u672c\u7684\u7814\u7a76\u6bd4\u8f83\uff0c\u4e0d\u4ee3\u8868\u6b63\u5f0f\u8bc4\u4f30\u6216\u63a8\u5e7f\u7ed3\u8bba"
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u7814\u7a76\u590d\u76d8 | Football Prediction Day</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f6f7f5;color:#1d2925;font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:980px;margin:44px auto 80px;padding:0 24px}}
nav,.muted,.overline{{font-size:13px;color:#61726a}}
nav a{{color:#345d50;text-decoration:none}}nav a:hover{{text-decoration:underline}}
.overline{{letter-spacing:.12em;text-transform:uppercase;margin:20px 0 6px}}
h1{{font-size:32px;font-weight:690;letter-spacing:-.02em;margin:0 0 8px}}
h2{{font-size:18px;margin:0 0 16px}}
.notice{{border-left:3px solid #647e70;background:#eaf0eb;padding:14px 18px;margin:24px 0;border-radius:0 6px 6px 0}}
.stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:20px 0}}
.stat{{background:white;border:1px solid #e1e7e2;padding:14px 18px;border-radius:8px}}
.stat b{{display:block;font-size:28px;font-variant-numeric:tabular-nums}}
section{{background:#fff;border:1px solid #e0e6e1;border-radius:10px;padding:22px;margin-top:18px;overflow:auto}}
table{{border-collapse:collapse;width:100%;min-width:580px}}
th,td{{text-align:left;border-bottom:1px solid #edf0ec;padding:11px 12px;font-variant-numeric:tabular-nums}}
th{{font-weight:650}}thead{{background:#f7f9f7}}.muted{{margin:12px 0 0}}
@media(max-width:600px){{main{{margin-top:20px;padding:0 14px}}.stats{{gap:7px}}.stat{{padding:10px}}.stat b{{font-size:22px}}h1{{font-size:28px}}section{{padding:13px}}}}
</style></head><body><main>
<nav><a href="../prediction_dashboard/latest.html">\u2190 \u8fd4\u56de\u6bcf\u65e5\u9884\u6d4b</a></nav>
<div class="overline">RESEARCH ONLY / \u7814\u7a76\u6837\u672c</div>
<h1>{page_title}</h1>
<p class="muted">Champion \u00b7 Bet365 \u5e02\u573a\u57fa\u7ebf \u00b7 \u56fa\u5b9a 50/50 \u7ec4\u5408</p>
<p class="muted">{cohort_note}</p>
<div class="notice">{note}</div>
<div class="stats">
 <div class="stat"><span>\u5df2\u9a8c\u6536</span><b>{s['settled']}</b></div>
 <div class="stat"><span>\u5f85\u6838\u9a8c</span><b>{s['pending']}</b></div>
 <div class="stat"><span>\u5df2\u6392\u9664</span><b>{s['excluded']}</b></div>
</div>
<section><h2>\u4e09\u7ec4\u540c\u573a\u9884\u6d4b\u5bf9\u7167</h2>
<table><thead><tr><th>\u65b9\u6cd5</th><th>Top 1</th><th>Top 3</th><th>Top 5</th><th>\u5e73\u5747 NLL</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="muted">\u540d\u6b21\u547d\u4e2d\u7387\u4ec5\u6839\u636e\u5df2\u6838\u9a8c\u540c\u573a\u6bd4\u8d5b\u8ba1\u7b97\u3002NLL \u53ea\u5bf9\u4e09\u7ec4\u6982\u7387\u5747\u6709\u6548\u7684\u914d\u5bf9\u6837\u672c\u8ba1\u5206\u3002</p>
</section>
<section><h2>\u51bb\u7ed3\u6837\u672c\u660e\u7ec6</h2>
<table><thead><tr><th>\u6bd4\u8d5b ID</th><th>\u6838\u9a8c\u72b6\u6001</th><th>\u539f\u56e0</th></tr></thead>
<tbody>{''.join(matches) or '<tr><td colspan="3">\u65e0\u6837\u672c</td></tr>'}</tbody></table></section>
<p class="muted">\u4ec5\u7528\u4e8e\u7814\u7a76\uff0c\u4e0d\u4ee3\u8868\u6b63\u5f0f Champion \u6216\u6295\u6ce8\u5efa\u8bae\u3002</p>
</main></body></html>'''
def publish_optional(source: Path, output: Path) -> bool:
    try:
        p=json.loads(Path(source).read_text(encoding="utf-8"))
        if not _valid(p): return False
        clean={"schema":p["schema"],"summary":p["summary"],"matches":[{k:r[k] for k in ("match_id","state","reason") if k in r} for r in p["matches"]]}
        report=render_report(clean); dashboard=Path(output)/"prediction_dashboard"/"latest.html"
        text=dashboard.read_text(encoding="utf-8"); text=re.sub(r'<a class="research-scorecard-link"[^>]*>\u7814\u7a76\u590d\u76d8</a>','',text)
        pos=text.lower().rfind("</body>")
        if pos<0: return False
        link='<p><a class="research-scorecard-link" href="../research/scorecard.html">\u7814\u7a76\u590d\u76d8</a></p>\n'
        target=Path(output)/"research"/"scorecard.html"; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(report,encoding="utf-8"); (target.parent/"scorecard.json").write_text(json.dumps(clean,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        dashboard.write_text(text[:pos]+link+text[pos:],encoding="utf-8"); return True
    except (OSError,ValueError,TypeError,KeyError): return False
