import json
from pathlib import Path
from scripts.research_scorecard_public import publish_optional, render_report, SCHEMA

def sample(settled=0):
    methods={k:{"top1":None,"top3":None,"top5":None,"mean_nll":None,"nll_matches":0} for k in ("champion","bet365","blend_50_50")}
    if settled:
        for m in methods.values(): m.update(top1=.5,top3=.75,top5=1.0,mean_nll=.8,nll_matches=settled)
    return {"schema":SCHEMA,"summary":{"settled":settled,"pending":6-settled,"excluded":0,"methods":methods},"matches":[{"match_id":f"M{i+1}","match_key":"SECRET","prediction_id":"PSECRET","state":"SETTLED" if i<settled else "PENDING","reason":"NO_VERIFIED_RESULT" if i>=settled else "","odds":"SECRET"} for i in range(6)]}
def setup(tmp):
    out=tmp/"out"; d=out/"prediction_dashboard"; d.mkdir(parents=True); (d/"latest.html").write_text("<html><body>dash</body></html>",encoding="utf-8"); return out,d/"latest.html"
def test_absent(tmp_path):
    out,dash=setup(tmp_path); assert not publish_optional(tmp_path/"none.json",out); assert not (out/"research").exists(); assert "\u7814\u7a76\u590d\u76d8" not in dash.read_text(encoding="utf-8")
def test_invalid_schema_fail_closed(tmp_path):
    out,dash=setup(tmp_path); src=tmp_path/"bad.json"; src.write_text('{"schema":"wrong"}'); assert not publish_optional(src,out); assert not (out/"research").exists()
def test_zero_settled_is_not_zero_percent_or_superiority(tmp_path):
    out,dash=setup(tmp_path); src=tmp_path/"data.json"; src.write_text(json.dumps(sample())); assert publish_optional(src,out); page=(out/"research/scorecard.html").read_text(encoding="utf-8"); assert "\u5c1a\u65e0\u5df2\u9a8c\u6536\u8d5b\u679c\uff0c\u4e0d\u80fd\u6bd4\u8f83\u547d\u4e2d\u7387\u6216\u63d0\u5347" in page; assert "0.0%" not in page
def test_settled_metrics_render(tmp_path):
    p=sample(2); page=render_report(p); assert "50.0%" in page and "0.8000" in page and "Champion" in page and "\u5e02\u573a\u57fa\u7ebf" in page and "\u56fa\u5b9a50-50" in page
def test_dynamic_html_escaped(tmp_path):
    p=sample(); p["matches"][0]["match_id"]='<img src=x onerror="x">'; page=render_report(p); assert "&lt;img" in page and "<img" not in page
def test_link_idempotent(tmp_path):
    out,dash=setup(tmp_path); src=tmp_path/"data.json"; src.write_text(json.dumps(sample())); assert publish_optional(src,out); assert publish_optional(src,out); assert dash.read_text(encoding="utf-8").count('class="research-scorecard-link"')==1
def test_source_unchanged_and_sanitized_copy(tmp_path):
    out,dash=setup(tmp_path); src=tmp_path/"data.json"; original=json.dumps(sample()); src.write_text(original); publish_optional(src,out); assert src.read_text(encoding="utf-8")==original; copied=(out/"research/scorecard.json").read_text(encoding="utf-8"); assert "SECRET" not in copied and "PSECRET" not in copied and "match_key" not in copied
def test_pending_match_state_display(tmp_path):
    p=sample(); page=render_report(p); assert "M1" in page and "PENDING" in page and "NO_VERIFIED_RESULT" in page and "RESEARCH ONLY" in page

def test_report_has_no_garbled_placeholder():
    from scripts.research_scorecard_public import render_report
    data = sample()
    output=render_report(data)
    assert "????" not in output and "\ufffd" not in output


def test_rolling_preferred_schema(tmp_path):
    from scripts.research_scorecard_public import ROLLING_SCHEMA
    p=sample()
    p['schema']=ROLLING_SCHEMA
    out,dash=setup(tmp_path)
    source=tmp_path/'rolling.json'
    source.write_text(json.dumps(p),encoding='utf8')
    assert publish_optional(source,out)
    text=(out/'research/scorecard.html').read_text(encoding='utf8')
    assert '滚动比分预测复盘' in text
    assert '每 UTC 日最多 4 场' in text
    assert '0.0%' not in text
    published=json.loads((out/'research/scorecard.json').read_text(encoding='utf8'))
    assert published['schema']==ROLLING_SCHEMA
    assert 'match_key' not in published['matches'][0]
