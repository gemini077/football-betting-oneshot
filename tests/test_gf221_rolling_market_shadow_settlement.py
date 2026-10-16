import gzip, hashlib, json, pathlib, shutil, sys
import pytest
BASE=pathlib.Path(__file__).resolve().parents[1]
REPO=BASE; sys.path.insert(0,str(REPO/'scripts'))
from test_gf220_rolling_market_shadow import fixture, setup, run as capture_run
import rolling_market_shadow_settlement as evaluator

def compact(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def make_case(tmp_path):
    source_root=tmp_path/'repo'
    rows=[fixture(source_root,mid=f'M{i}') for i in range(4)]
    repo,months=setup(tmp_path,rows)
    for r in rows:
        p=repo/'data/model_governance/predictions'/(r['selected_prediction_id']+'.json')
        model=json.loads(p.read_text(encoding='utf8'))
        model['match_id']=r['match_id']
        model['match_key']='test-'+r['match_id']
        model['match_identity']={'home':'HOME-'+r['match_id'],'away':'AWAY-'+r['match_id']}
        p.write_text(json.dumps(model,separators=(',',':')),encoding='utf8')
    result=capture_run(repo,months,rows)
    assert result['captured']==4
    (repo/'greenfield/research').mkdir(parents=True,exist_ok=True)
    (repo/'data/postmatch_automation/results').mkdir(parents=True,exist_ok=True)
    shutil.copy(REPO/'greenfield/research/gf216_frozen_three_arm_settlement.py',repo/'greenfield/research/gf216_frozen_three_arm_settlement.py')
    ledger=json.loads(gzip.decompress((months/'2026-10.json.gz').read_bytes()))
    return repo,months,ledger

def run(repo,months,**kw): return evaluator.evaluate(repo,months,output=repo/'report.json',**kw)

def test_zero_settled_metrics_null(tmp_path):
    repo,months,_=make_case(tmp_path); out=run(repo,months,no_write=True); assert out['summary']['settled']==0 and all(v['top1'] is None and v['mean_nll'] is None for v in out['summary']['methods'].values())

def test_valid_settled_synthetic_result(tmp_path):
    repo,months,rows=make_case(tmp_path); rec=json.loads((repo/'data/model_governance/predictions'/(rows[0]['selected_prediction_id']+'.json')).read_bytes())
    h,a=rec['match_identity']['home'],rec['match_identity']['away']; result={'match_key':rec['match_key'],'home':h,'away':a,'kickoff_local':rec['kickoff_at'],'verified_at':'2026-10-16T22:00:00Z','result_90m':'1-2','scope':'regulation_90m_plus_stoppage','source':'synthetic fixture','verification_quality':'verified'}
    (repo/'data/postmatch_automation/results'/(rec['match_key']+'.json')).write_text(json.dumps(result))
    out=run(repo,months,no_write=True); assert out['summary']['settled']==1 and next(x for x in out['matches'] if x['prediction_id']==rows[0]['selected_prediction_id'])['state']=='SETTLED'

@pytest.mark.parametrize('edit,reason',[('teams','TEAM_MISMATCH'),('kickoff','KICKOFF_MISMATCH'),('scope','WRONG_SCOPE'),('early','VERIFIED_BEFORE_90M')])
def test_bad_verified_result_excluded(tmp_path,edit,reason):
    repo,months,rows=make_case(tmp_path); rec=json.loads((repo/'data/model_governance/predictions'/(rows[0]['selected_prediction_id']+'.json')).read_bytes()); ident=rec['match_identity']; result={'match_key':rec['match_key'],'home':ident['home'],'away':ident['away'],'kickoff_local':rec['kickoff_at'],'verified_at':'2026-10-16T22:00:00Z','result_90m':'1-2','scope':'regulation_90m_plus_stoppage','source':'x','verification_quality':'verified'}
    if edit=='teams': result['home']='WRONG'
    if edit=='kickoff': result['kickoff_local']='2026-10-16T19:00:00Z'
    if edit=='scope': result['scope']='extra_time_included'
    if edit=='early': result['verified_at']='2026-10-16T20:30:01Z'
    (repo/'data/postmatch_automation/results'/(rec['match_key']+'.json')).write_text(json.dumps(result)); out=run(repo,months,no_write=True); assert out['summary']['excluded']==1 and reason in {x.get('reason') for x in out['matches']}

def test_champion_source_sha_tampering_fails_closed(tmp_path):
    repo,months,rows=make_case(tmp_path); f=months/'2026-10.json.gz'; x=json.loads(gzip.decompress(f.read_bytes())); x[0]['champion_source_sha256']='0'*64; f.write_bytes(gzip.compress(compact(x),mtime=0)); dest=repo/'report.json'
    with pytest.raises(evaluator.LedgerError,match='sha_mismatch'): run(repo,months)
    assert not dest.exists()

def test_nonfinite_market_pmf_fails_before_write(tmp_path):
    repo,months,rows=make_case(tmp_path); f=months/'2026-10.json.gz'; x=json.loads(gzip.decompress(f.read_bytes())); x[0]['market_pmf_169'][0]['probability']=float('nan'); f.write_bytes(gzip.compress(json.dumps(x,allow_nan=True).encode(),mtime=0))
    with pytest.raises(evaluator.LedgerError): run(repo,months)
    assert not (repo/'report.json').exists()

def test_duplicate_ledger_identity_fails(tmp_path):
    repo,months,rows=make_case(tmp_path); f=months/'2026-10.json.gz'; x=json.loads(gzip.decompress(f.read_bytes())); x.append(x[0]); f.write_bytes(gzip.compress(compact(x),mtime=0))
    with pytest.raises(evaluator.LedgerError,match='duplicate'): run(repo,months)

def test_output_idempotent(tmp_path):
    repo,months,_=make_case(tmp_path); run(repo,months); p=repo/'report.json'; a=p.read_bytes(); stamp=p.stat().st_mtime_ns; run(repo,months); assert p.read_bytes()==a and p.stat().st_mtime_ns==stamp

def test_noncanonical_month_filename_fails(tmp_path):
    repo,months,_=make_case(tmp_path); shutil.copy(months/'2026-10.json.gz',months/'2026-13.json.gz')
    with pytest.raises(evaluator.LedgerError,match='noncanonical'): run(repo,months,no_write=True)

def test_zero_probability_nll_excluded_not_infinite(tmp_path):
    repo,months,rows=make_case(tmp_path); import importlib.util
    spec=importlib.util.spec_from_file_location('gf216',repo/'greenfield/research/gf216_frozen_three_arm_settlement.py'); gf=importlib.util.module_from_spec(spec); spec.loader.exec_module(gf)
    rec=json.loads((repo/'data/model_governance/predictions'/(rows[0]['selected_prediction_id']+'.json')).read_bytes()); ident=rec['match_identity']; zero='12-12'
    pmf={f'{h}-{a}':(0.0 if f'{h}-{a}'==zero else 1/168) for h in range(13) for a in range(13)}
    item={'match_key':rec['match_key'],'kickoff_at':rec['kickoff_at'],'identity':ident,'pmfs':{m:pmf for m in ('champion','bet365','blend_50_50')}}
    result={'match_key':rec['match_key'],'home':ident['home'],'away':ident['away'],'kickoff_local':rec['kickoff_at'],'verified_at':'2026-10-16T22:00:00Z','result_90m':zero,'scope':'regulation_90m_plus_stoppage','source':'synthetic','verification_quality':'verified'}
    (repo/'data/postmatch_automation/results'/(rec['match_key']+'.json')).write_text(json.dumps(result)); resolved=gf.resolve_result(item,repo/'data/postmatch_automation/results')
    assert resolved['state']=='SETTLED' and all(v['nll'] is None and v['nll_exclusion_reason']=='ZERO_PROBABILITY' for v in resolved['metrics'].values())

def test_freeze_after_kickoff_rejected(tmp_path):
    repo,months,_=make_case(tmp_path); f=months/'2026-10.json.gz'; x=json.loads(gzip.decompress(f.read_bytes())); x[0]['freeze_created_at']='2026-10-16T20:00:00Z'; f.write_bytes(gzip.compress(compact(x),mtime=0))
    with pytest.raises(evaluator.LedgerError,match='pre_kickoff'): run(repo,months,no_write=True)

def test_snapshot_optional_when_not_present(tmp_path):
    repo,months,_=make_case(tmp_path); out=run(repo,months,no_write=True); assert len(out['matches'])==4

def test_paired_nll_uses_same_cohort(tmp_path,monkeypatch):
    repo,months,rows=make_case(tmp_path)
    import importlib.util
    spec=importlib.util.spec_from_file_location('gf216paired',repo/'greenfield/research/gf216_frozen_three_arm_settlement.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    base=mod.resolve_result
    def fake_resolve(item,result_dir):
        out=base(item,result_dir)
        if out['state']=='SETTLED':
            out['metrics']['bet365']['nll']=None
            out['metrics']['bet365']['nll_exclusion_reason']='ZERO_PROBABILITY'
        return out
    mod.resolve_result=fake_resolve
    monkeypatch.setattr(evaluator,'load_gf216',lambda _:mod)
    for row in rows:
        rec=json.loads((repo/'data/model_governance/predictions'/(row['selected_prediction_id']+'.json')).read_bytes())
        ident=rec['match_identity']
        result={'match_key':rec['match_key'],'home':ident['home'],'away':ident['away'],'kickoff_local':rec['kickoff_at'],'verified_at':'2026-10-19T00:00:00Z','result_90m':'1-2','scope':'regulation_90m_plus_stoppage','source':'synthetic','verification_quality':'verified'}
        (repo/'data/postmatch_automation/results'/(rec['match_key']+'.json')).write_text(json.dumps(result))
    out=run(repo,months,no_write=True)
    assert out['summary']['settled']==4
    assert {x['nll_matches'] for x in out['summary']['methods'].values()}=={0}
    assert all(x['mean_nll'] is None for x in out['summary']['methods'].values())
