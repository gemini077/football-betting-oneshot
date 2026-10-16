import math, pytest
from greenfield.research.gf214_preko_bet365_shadow import timestamp, number, single_named, inverse_normalize, market_targets, score_grid, top_scores, snapshot_record

def test_timestamp_normalizes_offset(): assert timestamp("2026-10-16T00:00:00Z").isoformat()=="2026-10-16T00:00:00+00:00"
def test_naive_timestamp_rejected():
    with pytest.raises(ValueError): timestamp("2026-10-16T00:00:00")
def test_nonfinite_rejected():
    with pytest.raises(ValueError): number(float("nan"),"x")
def test_boolean_rejected():
    with pytest.raises(ValueError): number(True,"x")
def test_odds_at_or_below_one_rejected():
    with pytest.raises(ValueError,match="above_one"): inverse_normalize([1,2,3])
def test_duplicate_bet365_rejected():
    with pytest.raises(ValueError,match="duplicate"): single_named([{"name":"bet365"},{"name":"bet365"}],"name","bet365")
def test_inverse_normalization(): assert inverse_normalize([2,4,4])==pytest.approx([.5,.25,.25])
def test_wrong_line_rejected():
    s={"input":{"source_snapshots":{"nowscore":{"snapshots":[{"ouzhi":{"bookmakers":[{"name":"bet365","spf_current":{"home":2,"draw":3,"away":4}}]},"daxiao":{"companies":[{"name":"bet365","current_line":"2.25","current_over_water":.9,"current_under_water":.9}]}}]}}}}
    with pytest.raises(ValueError,match="x5"): market_targets(s)
def test_grid_169_normalized_stable():
    a=score_grid(1.2,1.4); b=score_grid(1.2,1.4)
    assert len(a)==169 and sum(x["probability"] for x in a)==pytest.approx(1)
    assert a==b and top_scores(a,5)==["1-1","0-1","1-0","1-2","2-1"]
def test_market_exact_bet365_only():
    s={"input":{"source_snapshots":{"nowscore":{"snapshots":[{"ouzhi":{"bookmakers":[{"name":"other","spf_current":{"home":1,"draw":1,"away":1}},{"name":"bet365","spf_current":{"home":2,"draw":4,"away":4}}]},"daxiao":{"companies":[{"name":"bet365","current_line":"2.5","current_over_water":1,"current_under_water":1}]}}]}}}}
    w,o=market_targets(s); assert w==pytest.approx([.5,.25,.25]) and o=={"2.5":pytest.approx(.5)}
def test_recorded_frozen_nowscore_named_shape():
    s={"input":{"source_snapshots":{"nowscore":{"snapshots":[{"ouzhi":{"bookmakers":[{"name":"bet365","spf_current":{"home":2.73,"draw":3.95,"away":1.98}}]},"daxiao":{"companies":[{"name":"bet365","current_line":"2.5","current_over_water":.9,"current_under_water":.95}]}}]}}}}
    w,_=market_targets(s); inv=[1/2.73,1/3.95,1/1.98]; total=sum(inv); assert w==pytest.approx([x/total for x in inv])
def test_missing_named_spf_rejected():
    with pytest.raises(ValueError,match="invalid_spf_current"):
        market_targets({"input":{"source_snapshots":{"nowscore":{"snapshots":[{"ouzhi":{"bookmakers":[{"name":"bet365","spf_current":{"home":2,"draw":3}}]},"daxiao":{"companies":[{"name":"bet365","current_line":2.5,"current_over_water":.9,"current_under_water":.9}]}}]}}}})
def test_pmf_has_explicit_cell_labels():
    g=score_grid(1.1,1.2); assert len({x["score"] for x in g})==169 and all("probability" in x for x in g)
