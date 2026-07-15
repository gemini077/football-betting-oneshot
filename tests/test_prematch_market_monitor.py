from datetime import datetime
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
import prematch_market_monitor as monitor
from prematch_market_monitor import due_matches

def test_due_matches_only_returns_analyzed_near_kickoff():
    workspace={"matches":[{"id":"1","report_state":"已分析","kickoff":"2026-07-16 03:00"},{"id":"2","report_state":"未分析","kickoff":"2026-07-16 02:30"},{"id":"3","report_state":"已分析","kickoff":"2026-07-17 03:00"}]}
    assert [row["id"] for row in due_matches(workspace,datetime.fromisoformat("2026-07-15 23:00"))] == ["1"]

def test_due_matches_runs_each_checkpoint_once():
    workspace={"matches":[{"id":"1","report_state":"已分析","kickoff":"2026-07-16 03:00"}]}
    now=datetime.fromisoformat("2026-07-15 23:00")
    assert due_matches(workspace,now,state={})[0]["_monitor_stage"] == "T-6H"
    assert due_matches(workspace,now,state={"1":{"T-6H":"done"}}) == []
    final=datetime.fromisoformat("2026-07-16 02:00")
    assert due_matches(workspace,final,state={"1":{"T-6H":"done"}})[0]["_monitor_stage"] == "T-90M"

def test_refresh_fundamentals_preserves_form_and_updates_time_sensitive_facts(tmp_path, monkeypatch):
    analysis=tmp_path/"analysis.json"
    analysis.write_text('{"fundamentals":{"items":[{"label":"近期状态","value":"保留"}]}}',encoding="utf-8")
    monkeypatch.setattr(monitor,"collect_prematch_fundamentals",lambda match,deep:{
        "status":"已重查",
        "items":[{"label":"首发名单","value":"尚未公布"}],
        "sources":[{"label":"官方比赛页","url":"https://example.com"}],
    })

    assert monitor.refresh_fundamentals(analysis,{"home":"主队","away":"客队"}) == "已重查"
    payload=monitor.load_json(analysis)
    assert [item["label"] for item in payload["fundamentals"]["items"]] == ["近期状态","首发名单"]
    assert payload["fundamentals"]["sources"][0]["url"] == "https://example.com"
