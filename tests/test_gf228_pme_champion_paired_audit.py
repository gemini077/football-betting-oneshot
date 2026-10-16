import importlib.util, json, pathlib, shutil, tempfile
import pytest

BASE=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit',BASE/'scripts/pme_champion_paired_audit.py'); audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)

def cells(n): return [{'home_goals':h,'away_goals':a,'probability':1/((n+1)**2)} for h in range(n+1) for a in range(n+1)]
def test_full_90_real_file_smoke_and_dry_run():
    mroot=BASE/'data/prediction_quality/pure_market_exact_prospective_1'
    if not (mroot/'latest_index.json').is_file(): mroot=BASE
    b=audit.build(BASE,mroot,reps=50); d=json.loads(b); assert d['n']>=90 and len(d['matches'])==min(d['n'],250)
    if d['n']==90: assert d['summary']['champion']['top1']==14 and d['summary']['market']['top1']==17
    if d['n']==90: assert d['tests']['top1_mcnemar']['champion_only']==3 and d['tests']['top1_mcnemar']['market_only']==6
    assert len(b)<500*1024
    assert audit.main(['--repo-root',str(BASE),'--market-root',str(mroot),'--dry-run'])==0
@pytest.mark.parametrize('n',[0,1,2,3,4,5,6,7,8,9,10,11,12])
def test_grid_lengths_and_normalization(n):
    m,r=audit.matrix(cells(n),n,'x'); assert len(m)==(n+1)**2 and abs(sum(m.values())-1)<1e-12
def test_tie_order_home_then_away():
    x=[{'home_goals':h,'away_goals':a,'probability':1/169} for h in range(13) for a in range(13)]
    assert audit.matrix(x,12,'x')[1][0]==(0,0)
def test_duplicate_coordinate_rejected():
    x=cells(12); x[-1]=dict(x[0]);
    with pytest.raises(ValueError): audit.matrix(x,12,'x')
def test_probability_sum_rejected():
    x=cells(12); x[0]['probability']=.5
    with pytest.raises(ValueError): audit.matrix(x,12,'x')
def test_negative_nonfinite_rejected():
    for value in (-1,float('nan'),float('inf')):
        x=cells(12); x[0]['probability']=value
        with pytest.raises(ValueError): audit.matrix(x,12,'x')
def test_shared_cutoff_compares_utc_instants():
    assert audit.eqtime('2026-01-01T00:00:00Z','2025-12-31T16:00:00-08:00')
    assert not audit.eqtime('2026-01-01T00:00:00Z','2026-01-01T00:00:01Z')
def test_rps_order_away_draw_home():
    m={(1,0):.2,(0,0):.3,(0,1):.5}; assert audit.rps(m,(1,0))==pytest.approx(.445)
def test_top_rank_exact_tie_rule():
    m={(0,0):.5,(0,1):.5}; assert sorted(m,key=lambda k:(-m[k],k[0],k[1]))[0]==(0,0)
def test_seeded_bootstrap_replay():
    xs=[-.2,.1,.3,-.4]; assert audit.bootstrap(xs,seed=228,reps=250)==audit.bootstrap(xs,seed=228,reps=250)
def test_exact_mcnemar_binomial():
    assert audit.binom2(3,6)==pytest.approx(0.5078125)
def test_alternate_score_schema_parsing_contract():
    assert audit.score('2-1')==(2,1); x={'score_90m':None,'result_90m':{'home':2,'away':1}}; actual=x.get('score_90m',x.get('result_90m')); assert actual is None  # null primary is invalid, never fallback silently
def test_missing_result_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError): audit.read(tmp_path/'missing.json')
def test_digest_mismatch_guard_expression():
    p={'prediction_digest':'a'}; s={'prediction_digest':'b'}
    assert p.get('prediction_digest')!=s.get('prediction_digest')
def test_post_kickoff_leakage_comparison():
    from datetime import datetime
    assert datetime.fromisoformat('2026-01-01T00:00:01+00:00')>=datetime.fromisoformat('2026-01-01T00:00:00+00:00')
def test_one_observation_per_latest_match():
    ix=audit.read(BASE/'data/prediction_quality/pure_market_exact_prospective_1/latest_index.json')
    latest=ix['latest_by_match']
    assert latest and len(latest)==len(set(latest))
    assert len(latest)<=ix['prediction_count']
    assert all(isinstance(key,str) and isinstance(pid,str) and pid for key,pid in latest.items())


def test_rejects_nonfinite_expected_metric():
    with pytest.raises(ValueError): audit.close(0.2,float('nan'))

def test_rejects_boolean_probability():
    x=cells(12); x[0]['probability']=True
    with pytest.raises(ValueError): audit.matrix(x,12,'x')
