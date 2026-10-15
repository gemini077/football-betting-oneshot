import json
from pathlib import Path
from unittest.mock import patch

from scripts import build_public_site as builder
from scripts import match_detail

IDENTITY={"match_id":"3075322","business_date":"2026-10-15","home":"克拉约瓦","away":"赫塔费","kickoff_at":"2026-10-16 00:45"}
def setup(tmp_path, *, match=None, cutoff="2026-10-15T23:30:00+08:00", created="2026-10-15T15:40:00+00:00"):
    current=tmp_path/"data/analysis_reports/current"; current.mkdir(parents=True)
    payload={"match":dict(IDENTITY, kickoff=IDENTITY["kickoff_at"]),"source_cutoff_at":cutoff,"prediction_created_at":created}
    if match: payload["match"].update(match)
    (current/"r.json").write_text(json.dumps(payload),encoding="utf-8")
    (current/"r.html").write_text("<h1>full report</h1>",encoding="utf-8")
    contract={"identity":dict(IDENTITY),"hero":{"probabilities":{"home":0.5,"draw":0.3,"away":0.2}}}
    return tmp_path/"data",contract

def publish(data,contract,out):
    captured={}
    with patch.object(builder,"_match_contracts",lambda *_: {"3075322":contract}), patch.object(builder,"render_match_detail",lambda c: captured.update(c) or "<main>match</main>"):
        builder._build_match_pages(data,out,{"3075322"},{})
    return captured

def test_valid_report_copied_and_linked(tmp_path):
    data,c=setup(tmp_path); out=tmp_path/"site"; got=publish(data,c,out)
    assert (out/"matches/3075322/analysis.html").read_text(encoding="utf-8")=="<h1>full report</h1>"
    assert got["analysis_report_href"]=="analysis.html"
    html=match_detail._render_key_takeaways(got)
    assert '<a class="panel-link" href="analysis.html">\u67e5\u770b\u81ea\u52a8\u5206\u6790\u62a5\u544a' in html
    assert r'\u67e5' not in html

def test_wrong_identity_fails_closed(tmp_path):
    data,c=setup(tmp_path,match={"home":"OTHER"}); out=tmp_path/"site"; got=publish(data,c,out)
    assert "analysis_report_href" not in got and not (out/"matches/3075322/analysis.html").exists()
    assert 'class="panel-link"' not in match_detail._render_key_takeaways(got)

def test_post_kickoff_timestamps_fail_closed(tmp_path):
    data,c=setup(tmp_path,cutoff="2026-10-16T00:45:00+08:00"); out=tmp_path/"site"; got=publish(data,c,out)
    assert "analysis_report_href" not in got and 'class="panel-link"' not in match_detail._render_key_takeaways(got)

def test_absent_report_has_no_dead_cta(tmp_path):
    data,c=setup(tmp_path); (data/"analysis_reports/current/r.json").unlink(); out=tmp_path/"site"; got=publish(data,c,out)
    assert "analysis_report_href" not in got and 'class="panel-link"' not in match_detail._render_key_takeaways(got)


def test_report_index_built_once_for_two_pages(tmp_path, monkeypatch):
    data,c=setup(tmp_path); second=dict(c); second["identity"]=dict(c["identity"],match_id="OTHER")
    monkeypatch.setattr(builder,"_match_contracts",lambda *_:{"3075322":c,"OTHER":second})
    calls=[]; original=builder._index_preko_analysis_reports
    def counted(root):
        calls.append(root); return original(root)
    monkeypatch.setattr(builder,"_index_preko_analysis_reports",counted)
    monkeypatch.setattr(builder,"render_match_detail",lambda _:"<main>match</main>")
    out=tmp_path/"site"; builder._build_match_pages(data,out,{"3075322","OTHER"},{})
    assert len(calls)==1
    assert (out/"matches/3075322/analysis.html").is_file()
    assert not (out/"matches/OTHER/analysis.html").exists()


def test_future_source_vs_prediction_rejected(tmp_path):
    data,c=setup(tmp_path,cutoff="2026-10-16T00:20:00+08:00",created="2026-10-15T15:40:00+00:00")
    out=tmp_path/"site";got=publish(data,c,out)
    assert "analysis_report_href" not in got
    assert not (out/"matches/3075322/analysis.html").exists()
