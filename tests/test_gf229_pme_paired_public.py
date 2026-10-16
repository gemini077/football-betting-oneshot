import copy
import importlib.util
import json
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "data/prediction_quality/pure_market_exact_prospective_1/champion_market_paired_review.json"
spec = importlib.util.spec_from_file_location("paired_public", BASE / "scripts/pme_paired_public.py")
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


def report():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def site(tmp_path):
    research = tmp_path / "research"
    research.mkdir(parents=True, exist_ok=True)
    (research / "scorecard.html").write_text("<html><main><h1>Scorecard</h1></main></html>", encoding="utf-8")


def test_real_report_renders_expected_metrics_and_provenance(tmp_path):
    site(tmp_path)
    assert public.publish_optional(SOURCE, tmp_path)
    page = (tmp_path / "research/pme-paired.html").read_text(encoding="utf-8")
    for text in ("14 / 90", "17 / 90", "28 / 90", "31 / 90", "44 / 90", "47 / 90", "3.0495", "2.9153", "0.18723", "0.16555", "CAPTURE_ONLY", "latest_by_match", "169 格", "441 格"):
        assert text in page


def test_top1_test_displayed(tmp_path):
    site(tmp_path)
    assert public.publish_optional(SOURCE, tmp_path)
    assert "p = 0.5078" in (tmp_path / "research/pme-paired.html").read_text(encoding="utf-8")


def test_unsafe_match_key_is_escaped(tmp_path):
    site(tmp_path)
    data = report()
    data["matches"][0]["match_key"] = '<script>alert("x")</script>'
    source = tmp_path / "unsafe.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert public.publish_optional(source, tmp_path)
    page = (tmp_path / "research/pme-paired.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert '<script>alert("x")</script>' not in page


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version="wrong"),
    lambda d: d.update(n=0),
    lambda d: d["summary"]["market"].update(top1=91),
    lambda d: d["summary"]["champion"].update(nll=float("nan")),
    lambda d: d["deltas"]["nll"].update(paired_bootstrap_95_ci=[1, -1]),
    lambda d: d["tests"]["top1_mcnemar"].update(two_sided_exact_p=1.1),
    lambda d: d["matches"][0].update(actual="not-a-score"),
])
def test_invalid_report_rejected_without_site_change(tmp_path, mutate):
    site(tmp_path)
    before = (tmp_path / "research/scorecard.html").read_bytes()
    data = report()
    mutate(data)
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert public.publish_optional(source, tmp_path) is False
    assert (tmp_path / "research/scorecard.html").read_bytes() == before
    assert not (tmp_path / "research/pme-paired.html").exists()


def test_missing_report_leaves_existing_site_intact(tmp_path):
    site(tmp_path)
    before = (tmp_path / "research/scorecard.html").read_bytes()
    assert public.publish_optional(tmp_path / "missing.json", tmp_path) is False
    assert (tmp_path / "research/scorecard.html").read_bytes() == before


def test_link_is_idempotent_on_repeat_publish(tmp_path):
    site(tmp_path)
    assert public.publish_optional(SOURCE, tmp_path)
    assert public.publish_optional(SOURCE, tmp_path)
    page = (tmp_path / "research/scorecard.html").read_text(encoding="utf-8")
    assert page.count("research-historical-paired-link") == 1


def test_outputs_are_bounded_and_exclude_raw_quote_data(tmp_path):
    site(tmp_path)
    data = report()
    data["raw_bookmaker_quote"] = {"odds": [1.23, 4.56]}
    source = tmp_path / "report.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert public.publish_optional(source, tmp_path)
    payload = (tmp_path / "research/pme-paired.json").read_text(encoding="utf-8")
    assert "raw_bookmaker_quote" not in payload and "1.23" not in payload
    assert len((tmp_path / "research/pme-paired.html").read_bytes()) < 400 * 1024
    assert len((tmp_path / "research/pme-paired.json").read_bytes()) < 400 * 1024
    assert len(json.loads(payload)["matches"]) <= 250


def test_zero_values_are_not_substituted_for_missing_metrics(tmp_path):
    site(tmp_path)
    data = report()
    del data["summary"]["champion"]["top1"]
    source = tmp_path / "missing_metric.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert public.publish_optional(source, tmp_path) is False
    assert not (tmp_path / "research/pme-paired.html").exists()


def test_legacy_report_still_renders_with_cluster_unavailable(tmp_path):
    site(tmp_path)
    data=report();data.pop("robustness",None);data.pop("capture_provenance",None)
    for metric in ("nll","rps"):
        data["deltas"][metric].pop("matchday_cluster_bootstrap_95_ci",None)
    legacy=tmp_path/"legacy.json";legacy.write_text(json.dumps(data),encoding="utf-8")
    assert public.publish_optional(legacy,tmp_path)
    page=(tmp_path/"research/pme-paired.html").read_text(encoding="utf-8")
    assert "not available" in page and "stability" in page

def test_optional_cluster_fields_render_and_are_allowlisted(tmp_path):
    site(tmp_path); data=report()
    data["deltas"]["nll"]["matchday_cluster_bootstrap_95_ci"]=[-.4,-.1]
    data["deltas"]["rps"]["matchday_cluster_bootstrap_95_ci"]=[-.05,-.01]
    data["robustness"]={"cluster_days":9,"chronological_thirds":[{"segment":i,"start_date":f"2026-09-0{i}","end_date":f"2026-09-0{i}","n_matches":30,"n_matchdays":3,"market_minus_champion_mean_nll":-.1,"market_minus_champion_mean_rps":-.01,"champion_top1":5,"market_top1":6} for i in range(1,4)],"chronological_thirds_label":"stability check only; no training or tuning"}
    path=tmp_path/"new.json"; path.write_text(json.dumps(data),encoding="utf-8")
    assert public.publish_optional(path,tmp_path)
    page=(tmp_path/"research/pme-paired.html").read_text(encoding="utf-8")
    payload=json.loads((tmp_path/"research/pme-paired.json").read_text(encoding="utf-8"))
    assert "Matchday-cluster paired bootstrap" in page and "stability check only" in page and payload["robustness"]["cluster_days"]==9

def test_invalid_optional_cluster_interval_fails_closed(tmp_path):
    data=report(); data["deltas"]["nll"]["matchday_cluster_bootstrap_95_ci"]=[1,-1]
    data["robustness"]={"cluster_days":3,"chronological_thirds":[{"n_matches":30,"n_matchdays":1,"market_minus_champion_mean_nll":0,"market_minus_champion_mean_rps":0,"champion_top1":1,"market_top1":1} for _ in range(3)]}
    assert not public._valid(data)

def _gf234_report():
    data=report()
    n=data['n']
    data['capture_provenance']={
       'n':n,'source_capture_before_kickoff':n,
       'provider_quote_clock_verified_matches':0,
       'provider_quote_clock_missing_matches':n,
       'capture_lead_minutes':{'min':63.1,'median':314.64,'max':2781.27},
       'by_capture_lead':{'0_to_3h':{'n':20,'market_minus_champion_nll':-.15,'market_minus_champion_rps':-.02},
                          '3_to_12h':{'n':55,'market_minus_champion_nll':-.10,'market_minus_champion_rps':-.01},
                          'over_12h':{'n':n-75,'market_minus_champion_nll':-.2,'market_minus_champion_rps':-.03}},
       'promotion_gate':'BLOCKED_UPSTREAM_QUOTE_EVENT_CLOCK_UNVERIFIED'}
    return data


def test_source_quote_clock_audit_visible_and_fail_closed(tmp_path):
    site(tmp_path)
    data=_gf234_report()
    source=tmp_path/'source.json';source.write_text(json.dumps(data),encoding='utf8')
    assert public.publish_optional(source,tmp_path)
    page=(tmp_path/'research/pme-paired.html').read_text(encoding='utf8')
    assert '赛前数据时钟审计' in page
    assert '0 / 90' in page
    assert '3–12 小时' in page
    exposed=json.loads((tmp_path/'research/pme-paired.json').read_text(encoding='utf8'))
    assert exposed['capture_provenance']['provider_quote_clock_verified_matches']==0
    data['capture_provenance']['provider_quote_clock_verified_matches']=data['n']+1
    assert not public._valid(data)
    data=_gf234_report();data['capture_provenance']['capture_lead_minutes']['min']=-1
    assert not public._valid(data)
    data=_gf234_report();data['capture_provenance']['by_capture_lead']['0_to_3h']['n']+=1
    assert not public._valid(data)
