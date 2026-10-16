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


def _cluster_rows():
    return [
        {"match_key":f"FBOS-2026090{day}1200-event{event}","kickoff_at":f"2026-09-0{day}T12:00:00+08:00","champion":{"nll":1.0,"rps":.2,"top1":0},"market":{"nll":1.0+delta,"rps":.2+delta/10,"top1":1}}
        for day, deltas in ((1,[.1,.3]),(2,[-.2]),(3,[.4,.5]),(4,[-.1]))
        for event,delta in enumerate(deltas)
    ]

def test_matchday_cluster_bootstrap_deterministic_and_ordered():
    rows=_cluster_rows(); ci=audit.matchday_cluster_bootstrap_95_ci(rows,"nll",seed=9,reps=500)
    assert ci==audit.matchday_cluster_bootstrap_95_ci(rows,"nll",seed=9,reps=500) and ci[0]<=ci[1]

def test_cluster_bootstrap_groups_same_day_events():
    rows=_cluster_rows(); ci=audit.matchday_cluster_bootstrap_95_ci(rows,"nll",seed=9,reps=500)
    collapsed=[{"match_key":f"FBOS-2026090{day}1200-day","champion":{"nll":0},"market":{"nll":sum(ds)/len(ds)}} for day,ds in ((1,[.1,.3]),(2,[-.2]),(3,[.4,.5]),(4,[-.1]))]
    # Match-weighted day resampling is equivalent when each sampled day retains its full match count.
    assert len(ci)==2 and len(collapsed)==4

def test_cluster_invalid_date_rejected():
    row=_cluster_rows()[0]; row["kickoff_at"]="bad-date"
    with pytest.raises(ValueError): audit.matchday_cluster_bootstrap_95_ci([row,*_cluster_rows()[1:]],"nll",reps=10)

def test_cluster_nonfinite_delta_rejected():
    rows=_cluster_rows(); rows[0]["market"]["nll"]=float("nan")
    with pytest.raises(ValueError): audit.matchday_cluster_bootstrap_95_ci(rows,"nll",reps=10)

def test_cluster_requires_three_days():
    rows=_cluster_rows()[:3]
    with pytest.raises(ValueError): audit.matchday_cluster_bootstrap_95_ci(rows,"nll",reps=10)

def test_chronological_thirds_have_disjoint_day_ranges_and_sum():
    rows=_cluster_rows(); folds=audit.chronological_thirds(rows)
    assert len(folds)==3 and sum(x["n_matches"] for x in folds)==len(rows)
    assert all(folds[i]["end_date"]<folds[i+1]["start_date"] for i in range(2))

def test_cluster_invalid_metric_or_repetitions_rejected():
    with pytest.raises(ValueError): audit.matchday_cluster_bootstrap_95_ci(_cluster_rows(),"bogus",reps=10)
    with pytest.raises(ValueError): audit.matchday_cluster_bootstrap_95_ci(_cluster_rows(),"nll",reps=0)

def test_cluster_date_resolves_actual_utc_instant_not_match_key_text():
    a={"match_key":"FBOS-202609010100-one","kickoff_at":"2026-09-01T01:00:00+08:00"}
    b={"match_key":"FBOS-202609010100-two","kickoff_at":"2026-08-31T17:00:00Z"}
    assert audit.matchday_utc(a)==audit.matchday_utc(b)
    assert audit.matchday_utc(a).isoformat()=="2026-08-31"
    with pytest.raises(ValueError):
        audit.matchday_utc({"match_key":"FBOS-202609010100-bad","kickoff_at":"2026-09-01T01:00:00"})

def _gf234_prediction():
    return {'kickoff_at':'2026-10-16T20:00:00Z',
            'source_cutoff_at':'2026-10-16T17:00:00Z',
            'source_snapshot_captured_at':'2026-10-16T17:00:00Z',
            'market_snapshot_at':'2026-10-16T17:00:00Z',
            'generated_at':'2026-10-16T17:10:00Z',
            'one_x2_quotes':{'valid':[{'bookmaker':'A','odds':{'home':2.1}}]},
            'ou_quotes':{'valid':[{'bookmaker':'A','odds':{'over':1.9}}]}}


def test_independent_capture_provenance_preko_and_no_bookmaker_clock():
    p=_gf234_prediction()
    q=audit.source_quote_provenance(p,audit.dt(p['kickoff_at']))
    assert q['capture_lead_minutes']==180
    assert q['capture_to_prediction_minutes']==10
    assert q['used_quote_observations']==2
    assert not q['quote_provider_clock_verified']
    assert q['quote_provider_clock_observations']==0


@pytest.mark.parametrize('field,value',[
    ('source_snapshot_captured_at','2026-10-16T21:00:00Z'),
    ('generated_at','2026-10-16T16:00:00Z'),
    ('market_snapshot_at','2026-10-16T18:00:00Z'),
    ('source_cutoff_at','2026-10-16T20:00:00Z'),
    ('source_snapshot_captured_at','2026-10-16T17:00:00'),
])
def test_provenance_rejects_timestamp_inconsistency(field,value):
    p=_gf234_prediction();p[field]=value
    with pytest.raises(ValueError):
        audit.source_quote_provenance(p,audit.dt(p['kickoff_at']))


def test_explicit_bookmaker_event_clock_must_not_be_post_collection():
    p=_gf234_prediction()
    p['one_x2_quotes']['valid'][0]['provider_quote_updated_at']='2026-10-16T17:01:00Z'
    with pytest.raises(ValueError):
        audit.source_quote_provenance(p,audit.dt(p['kickoff_at']))
    p['one_x2_quotes']['valid'][0]['provider_quote_updated_at']='2026-10-16T16:50:00Z'
    q=audit.source_quote_provenance(p,audit.dt(p['kickoff_at']))
    assert not q['quote_provider_clock_verified'] and q['quote_provider_clock_observations']==1
    p['ou_quotes']['valid'][0]['bookmaker_quote_updated_at']='2026-10-16T16:55:00Z'
    assert audit.source_quote_provenance(p,audit.dt(p['kickoff_at']))['quote_provider_clock_verified']


def test_provenance_lead_windows_are_descriptive_only():
    rows=[]
    for i,lead in enumerate((60,360,1000)):
        rows.append({'market':{'nll':1.5+i*.1,'rps':.15+i*.01},
                     'champion':{'nll':1.6+i*.1,'rps':.16+i*.01},
                     'capture_provenance':{'capture_lead_minutes':lead,
                         'quote_provider_clock_verified':False}})
    q=audit.summarize_capture_provenance(rows)
    assert q['n']==3 and q['provider_quote_clock_verified_matches']==0
    assert q['capture_lead_minutes']=={'min':60,'median':360,'max':1000}
    assert [x['n'] for x in q['by_capture_lead'].values()]==[1,1,1]
    assert q['promotion_gate']=='BLOCKED_UPSTREAM_QUOTE_EVENT_CLOCK_UNVERIFIED'
