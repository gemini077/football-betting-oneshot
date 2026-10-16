import pytest
from datetime import datetime, timezone
from greenfield.research.gf215_preko_pair_blend import *

def grid(): return [{"home_goals":h,"away_goals":a,"probability":(1.0 if (h,a)==(0,0) else 0.0)} for h in range(13) for a in range(13)]
def src(): return {"prediction_id":"P","match_id":"M","source_cutoff_at":"2026-10-16T01:00:00Z","freeze_created_at":"2026-10-16T01:01:00+00:00","kickoff_at":"2026-10-16T16:30:00Z","exact_score_distribution":{"status":"FORMAL_EXACT_DISTRIBUTION_FROZEN","cells":grid()}}
def test_complete(): assert len(validate_grid(grid()))==169
def test_missing_cell():
 with pytest.raises(ValueError): validate_grid(grid()[:-1])
def test_duplicate_cell():
 g=grid(); g[-1]=dict(g[0])
 with pytest.raises(ValueError): validate_grid(g)
def test_sum():
 g=grid();g[0]["probability"]=.5
 with pytest.raises(ValueError): validate_grid(g)
def test_asof_offsets_and_future(): assert validate_source(src(),{"selected_prediction_id":"P","match_id":"M","original_cutoff":"2026-10-16T01:00:00Z","original_freeze_created_at":"2026-10-16T01:01:00+00:00","kickoff_timestamp":"2026-10-16T16:30:00Z"},datetime(2026,10,16,3,tzinfo=timezone.utc))[(0,0)]==1
def test_mismatch_checksum_identity():
 with pytest.raises(ValueError): validate_source(src(),{"selected_prediction_id":"wrong"},datetime(2026,10,16,3,tzinfo=timezone.utc))
def test_kickoff_guard():
 with pytest.raises(ValueError): validate_source(src(),{},datetime(2026,10,17,tzinfo=timezone.utc))
def test_tie_integer_stable():
 g={(h,a):1/169 for h in range(13) for a in range(13)}; assert rank(g,3)==["0-0","0-1","0-2"]
def test_blend_exact():
 a=grid();b=grid();b[-1]["probability"]=1;b[0]["probability"]=0
 z=blend(a,b);assert z[(0,0)]==.5 and z[(12,12)]==.5
def test_distances_finite_bounded():
 a=validate_grid(grid());b=dict(a);b[(0,0)]=0;b[(12,12)]=1
 js,tv=distances(a,b);assert 0<=js<=1 and 0<=tv<=1
def test_no_result_fields_in_source_use(): assert "result" not in src() and "actual" not in src()

def test_probability_bool_rejected():
 g=grid();g[0]["probability"]=True
 with pytest.raises(ValueError): validate_grid(g)
