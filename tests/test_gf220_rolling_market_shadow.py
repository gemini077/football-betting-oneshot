import gzip, hashlib, importlib.util, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
import pytest

BASE=Path(__file__).resolve().parents[1]
SCRIPT=BASE/'scripts/rolling_market_shadow.py'
spec=importlib.util.spec_from_file_location('gf220_runner',SCRIPT)
runner=importlib.util.module_from_spec(spec); sys.modules[spec.name]=runner; spec.loader.exec_module(runner)
gf214,gf215=runner.modules(BASE)
gf214.fit_market_lambdas=lambda wdl,ou:(1.4,1.1)
NOW='2026-10-16T19:00:00Z'

def fixture(root, day='2026-10-16', mid='M1', pid=None, cutoff=None, ko=None, frozen=True, formal=False):
    pid=pid or 'P-'+mid
    ko=ko or f'{day}T20:00:00Z'
    cutoff=cutoff or f'{day}T18:00:00Z'
    freeze=cutoff
    ref=f'data/snapshots/{mid}.json'
    snap={'source_cutoff_at':cutoff,'input':{'source_snapshots':{'nowscore':{'snapshots':[{
      'fetched_at':cutoff,'ouzhi':{'bookmakers':[{'name':'Bet365','spf_current':{'home':2.2,'draw':3.2,'away':3.4}}]},
      'daxiao':{'companies':[{'name':'bet365','current_line':2.5,'current_over_water':0.82,'current_under_water':0.91}]}}
    ]}}}}
    sp=root/ref; sp.parent.mkdir(parents=True,exist_ok=True); sb=json.dumps(snap,separators=(',',':')).encode(); sp.write_bytes(sb)
    cells=[{'home_goals':h,'away_goals':a,'probability':1/169} for h in range(13) for a in range(13)]
    model={'prediction_id':pid,'source_cutoff_at':cutoff,'freeze_created_at':freeze,'kickoff_at':ko,
      'exact_score_distribution':{'status':'FORMAL_EXACT_DISTRIBUTION_FROZEN','cells':cells}}
    mp=root/'data/model_governance/predictions'/f'{pid}.json'; mp.parent.mkdir(parents=True,exist_ok=True); mb=json.dumps(model,separators=(',',':')).encode(); mp.write_bytes(mb)
    top=[f'{i}-{i}' for i in range(5)]
    return {'match_id':mid,'business_date':'2026-10-15','status':'FROZEN' if frozen else 'SCHEDULED',
      'formal_prospective':formal,'selected_prediction_id':pid,'selected_source_cutoff_at':cutoff,
      'selected_freeze_created_at':freeze,'kickoff_timestamp':ko,'prediction':{'input_snapshot_ref':ref,
      'score_distribution':[{'score':x,'probability':0.2} for x in top], 'score_top3':top[:3], 'unique_score':top[0]}}

def setup(tmp_path, rows):
    root=tmp_path/'repo'; root.mkdir(exist_ok=True); dash=root/'data/prediction_dashboard/latest.json'; dash.parent.mkdir(parents=True); dash.write_text(json.dumps({'fixtures':rows}))
    for r in rows:
        # fixture() creates artifacts in root already
        pass
    out=tmp_path/'out'
    runner.modules=lambda _: (gf214,gf215)
    return root,out

def run(root,out,rows,now=NOW,cap=4):
    d=root/'data/prediction_dashboard/latest.json'; d.write_text(json.dumps({'fixtures':rows}))
    return runner.run(root,now,max_per_day=cap,output_root=out)

def read_rows(out,month='2026-10'):
    return json.loads(gzip.decompress((out/f'{month}.json.gz').read_bytes()))

def test_mass_169_and_no_outcome_or_odds(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r]); result=run(root,out,[r])
    rows=read_rows(out); assert result['captured']==1
    pmf=rows[0]['market_pmf_169']; assert len(pmf)==169 and abs(sum(x['probability'] for x in pmf)-1)<1e-10
    assert rows[0]['research_only'] is True
    assert not {'ft','result','odds','raw_quote'} & rows[0].keys()

def test_formal_dashboard_false_is_allowed_by_frozen_source(tmp_path):
    r=fixture(tmp_path/'repo',formal=False); root,out=setup(tmp_path,[r]); assert run(root,out,[r])['captured']==1

def test_non_frozen_rejected(tmp_path):
    r=fixture(tmp_path/'repo',frozen=False); root,out=setup(tmp_path,[r]); assert run(root,out,[r])['captured']==0
    assert not list(out.glob('*.gz'))

def test_cutoff_must_precede_kickoff_by_15_minutes(tmp_path):
    r=fixture(tmp_path/'repo',cutoff='2026-10-16T19:50:00Z'); root,out=setup(tmp_path,[r]); assert run(root,out,[r])['captured']==0
    assert 'cutoff_buffer_under_15m' in run(root,out,[r])['reasons']

def test_duplicate_date_match_rejected_once(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r,r.copy()]); res=run(root,out,[r,r.copy()])
    assert res['captured']==1 and res['reasons']['duplicate_date_match_id']==1

def test_corrupt_ledger_fails_closed_without_new_files(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r]); out.mkdir(); bad=out/'2026-10.json.gz'; bad.write_bytes(b'corrupt')
    with pytest.raises(runner.LedgerError): run(root,out,[r])
    assert list(out.iterdir())==[bad] and bad.read_bytes()==b'corrupt'

def test_stale_prediction_version_conflicts_without_overwrite(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r]); run(root,out,[r]); p=out/'2026-10.json.gz'; before=p.read_bytes()
    newer=r.copy(); newer['selected_prediction_id']='P-NEW'
    res=run(root,out,[newer]); assert res['captured']==0 and res['reasons']['existing_record_conflict']==1
    assert p.read_bytes()==before

def test_four_per_utc_day_cap(tmp_path):
    rows=[fixture(tmp_path/'repo',mid=f'M{i}') for i in range(5)]; root,out=setup(tmp_path,rows)
    res=run(root,out,rows); assert res['captured']==4 and len(read_rows(out))==4
    assert res['reasons']['daily_cap_reached']==1
    before=(out/'2026-10.json.gz').read_bytes()
    replay=run(root,out,rows); assert replay['captured']==0 and replay['reasons']['daily_cap_reached']==1
    assert (out/'2026-10.json.gz').read_bytes()==before

def test_month_rollover_two_month_files(tmp_path):
    a=fixture(tmp_path/'repo',day='2026-10-31',mid='OCT',ko='2026-10-31T23:50:00Z',cutoff='2026-10-31T23:00:00Z')
    b=fixture(tmp_path/'repo',day='2026-11-01',mid='NOV',ko='2026-11-01T20:00:00Z',cutoff='2026-10-31T23:00:00Z')
    root,out=setup(tmp_path,[a,b]); res=run(root,out,[a,b],now='2026-10-31T23:30:00Z'); assert res['captured']==2
    assert {p.name for p in out.glob('*.json.gz')}=={'2026-10.json.gz','2026-11.json.gz'}

def test_replay_idempotent_gzip_bytes(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r]); run(root,out,[r]); p=out/'2026-10.json.gz'; first=p.read_bytes()
    res=run(root,out,[r]); assert res['captured']==0 and not res['writes']; assert p.read_bytes()==first
    assert hashlib.sha256(first).hexdigest()==hashlib.sha256(p.read_bytes()).hexdigest()

def test_malformed_market_source_rejected(tmp_path):
    r=fixture(tmp_path/'repo'); root,out=setup(tmp_path,[r]); snap=root/r['prediction']['input_snapshot_ref']; obj=json.loads(snap.read_text())
    obj['input']['source_snapshots']['nowscore']['snapshots'][0]['ouzhi']['bookmakers'].append({'name':'bet365','spf_current':[2,3,4]})
    snap.write_text(json.dumps(obj)); res=run(root,out,[r]); assert res['captured']==0 and 'duplicate_bet365' in res['reasons']

def test_after_kickoff_never_captured(tmp_path):
    r=fixture(tmp_path/'repo',day='2026-10-15',ko='2026-10-15T10:00:00Z',cutoff='2026-10-15T08:00:00Z')
    root,out=setup(tmp_path,[r]); res=run(root,out,[r]); assert res['captured']==0 and not list(out.glob('*.gz'))




def test_equivalent_timezone_in_frozen_source(tmp_path):
    r=fixture(tmp_path/'repo')
    root,out=setup(tmp_path,[r])
    p=root/'data/model_governance/predictions'/f"{r['selected_prediction_id']}.json"
    data=json.loads(p.read_text(encoding='utf8'))
    data['kickoff_at']='2026-10-17T04:00:00+08:00'  # Same instant as 20:00Z
    p.write_text(json.dumps(data),encoding='utf8')
    assert run(root,out,[r])['captured']==1

def test_genuinely_different_kickoff_rejected(tmp_path):
    r=fixture(tmp_path/'repo')
    root,out=setup(tmp_path,[r])
    p=root/'data/model_governance/predictions'/f"{r['selected_prediction_id']}.json"
    data=json.loads(p.read_text(encoding='utf8'))
    data['kickoff_at']='2026-10-17T05:00:00+08:00'  # One hour later
    p.write_text(json.dumps(data),encoding='utf8')
    result=run(root,out,[r])
    assert result['captured']==0
    assert result['reasons']['frozen_kickoff_mismatch']==1
