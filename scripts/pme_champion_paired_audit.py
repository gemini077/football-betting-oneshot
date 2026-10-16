#!/usr/bin/env python3
"""Fail-closed paired Pure Market Exact / frozen Champion audit (stdlib only)."""
import argparse, hashlib, json, math, os, random, tempfile
from datetime import datetime
from pathlib import Path

TOL=1e-7
def read(p):
    with open(p, encoding='utf-8') as f: return json.load(f)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def dt(x):
    d=datetime.fromisoformat(x.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('timestamp lacks timezone')
    return d
def eqtime(a,b): return dt(a)==dt(b)
def score(s):
    h,a=map(int,s.split('-')); return h,a
def matrix(cells, nmax, source):
    if not isinstance(cells,list) or len(cells)!=(nmax+1)**2: raise ValueError(source+' cell count')
    m={}
    for x in cells:
        h=x.get('home_goals'); a=x.get('away_goals'); p=x.get('probability')
        if type(h)!=int or type(a)!=int or not(0<=h<=nmax and 0<=a<=nmax) or (h,a) in m: raise ValueError(source+' coordinate grid')
        if isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(p) or not 0<=p<=1: raise ValueError(source+' probability')
        m[h,a]=float(p)
    if set(m)!={(h,a) for h in range(nmax+1) for a in range(nmax+1)}: raise ValueError(source+' incomplete grid')
    if abs(sum(m.values())-1)>TOL: raise ValueError(source+' normalization')
    ordered=sorted(m,key=lambda k:(-m[k],k[0],k[1]))
    return m,ordered
def rps(m, actual):
    outcomes=[0.0,0.0,0.0]
    for (h,a),p in m.items(): outcomes[0 if h>a else 1 if h==a else 2]+=p
    y=[float(actual[0]>actual[1]),float(actual[0]==actual[1]),float(actual[0]<actual[1])]
    return sum((sum(outcomes[:i+1])-sum(y[:i+1]))**2 for i in range(2))/2
def metric(m,rank,actual):
    return {'top1':int(rank[0]==actual),'top3':int(actual in rank[:3]),'top5':int(actual in rank[:5]),'nll':-math.log(m[actual]),'rps':rps(m,actual),'score1':f'{rank[0][0]}-{rank[0][1]}'}
def close(a,b,t=1e-5):
    if any(isinstance(z,bool) or not isinstance(z,(int,float)) or not math.isfinite(z) for z in (a,b)) or abs(a-b)>t: raise ValueError('reproduced settlement metric mismatch')
def load_pair(root,mroot,entry):
    key=entry['match_key']; mid=entry['prediction_id']; pp=mroot/entry['prediction_path']; sp=mroot/entry['settlement_path']
    p,s=read(pp),read(sp)
    if s.get('settlement_status')!='SETTLED' or s.get('result',{}).get('scope')!='regulation_90m_plus_stoppage': raise ValueError(key+': unsettled/wrong scope')
    if p.get('match_key')!=key or s.get('match_key')!=key or p.get('prediction_id')!=mid or s.get('prediction_id')!=mid: raise ValueError(key+': match/id mismatch')
    if not eqtime(p['kickoff_at'],entry['kickoff_at']) or not eqtime(s['kickoff_at'],entry['kickoff_at']): raise ValueError(key+': kickoff mismatch')
    if not eqtime(p['source_cutoff_at'],s['source_cutoff_at']) or not eqtime(p['source_cutoff_at'],entry['source_cutoff_at']): raise ValueError(key+': cutoff mismatch')
    if p.get('prediction_digest')!=s.get('prediction_digest'): raise ValueError(key+': digest mismatch')
    ko=dt(entry['kickoff_at']);
    if dt(p['generated_at'])>=ko: raise ValueError(key+': market generated after kickoff')
    cpair=s.get('control_pair') or {}; ref=p.get('champion_reference') or {}
    if cpair.get('match_key')!=key or not cpair.get('same_match') or not cpair.get('same_source_cutoff'): raise ValueError(key+': invalid control pair')
    if not eqtime(cpair['source_cutoff_at'],entry['source_cutoff_at']) or not eqtime(ref['source_cutoff_at'],entry['source_cutoff_at']): raise ValueError(key+': control cutoff mismatch')
    if cpair.get('prediction_id')!=ref.get('prediction_id') or cpair.get('prediction_sha256')!=ref.get('prediction_sha256'): raise ValueError(key+': control identity mismatch')
    cp=root/'data/model_governance/predictions'/(cpair['prediction_id']+'.json'); c=read(cp)
    if c.get('prediction_sha256')!=cpair.get('prediction_sha256') or c.get('match_key')!=key or not eqtime(c['source_cutoff_at'],entry['source_cutoff_at']): raise ValueError(key+': pinned champion mismatch')
    if dt(c['freeze_created_at'])>=ko: raise ValueError(key+': champion freeze post kickoff')
    cm,cr=matrix(c['exact_score_distribution']['cells'],12,'champion')
    mm,mr=matrix(p['score_matrix'],20,'market')
    ctop=c.get('score_top1')
    if isinstance(ctop,dict): ctop=ctop.get('score')
    if ctop!=f'{cr[0][0]}-{cr[0][1]}': raise ValueError(key+': champion top1 disagreement')
    result_path=root/'data/postmatch_automation/results'/(key+'.json'); result=read(result_path)
    if result.get('match_key')!=key or not eqtime(result.get('kickoff_at',result.get('kickoff_local')),entry['kickoff_at']): raise ValueError(key+': result kickoff/match mismatch')
    if result.get('scope')!='regulation_90m_plus_stoppage': raise ValueError(key+': result wrong scope')
    if dt(result['verified_at'])<=ko: raise ValueError(key+': result verification not after kickoff')
    actuals=result.get('score_90m',result.get('result_90m'))
    if isinstance(actuals,dict): actual=(int(actuals['home']),int(actuals['away']))
    elif isinstance(actuals,str): actual=score(actuals)
    else: raise ValueError(key+': missing 90m score')
    if s['result'].get('actual_score')!=f'{actual[0]}-{actual[1]}': raise ValueError(key+': settlement/result score mismatch')
    market=metric(mm,mr,actual); champ=metric(cm,cr,actual); sm=s['metrics']
    for k in ('top1','top3','top5'):
        if bool(market[k])!=bool(sm['exact_'+k]): raise ValueError(key+': settlement '+k+' mismatch')
    close(market['nll'],sm['exact_nll']); close(market['rps'],sm['ft_1x2_rps'])
    return {'match_key':key,'actual':f'{actual[0]}-{actual[1]}','top1':{'champion':champ['top1'],'market':market['top1']},'champion':champ,'market':market},[pp,sp,cp,result_path]
def mean(xs): return sum(xs)/len(xs)
def bootstrap(xs,seed=228,reps=5000):
    rng=random.Random(seed); n=len(xs); vals=[]
    for _ in range(reps): vals.append(mean([xs[rng.randrange(n)] for __ in range(n)]))
    vals.sort(); return [vals[int(.025*reps)],vals[min(reps-1,int(.975*reps))]]
def binom2(a,b):
    n=a+b
    if not n:return 1.0
    k=min(a,b); tail=sum(math.comb(n,i) for i in range(k+1))/(2**n)
    return min(1.0,2*tail)
def build(root,market_root=None,reps=5000):
    root=Path(root); mroot=Path(market_root) if market_root else root/'data/prediction_quality/pure_market_exact_prospective_1'
    index=mroot/'latest_index.json'; ix=read(index); rows=[]; files=[index]
    entries=ix.get('predictions',[]); latest=ix.get('latest_by_match',{})
    byid={e['prediction_id']:e for e in entries}
    for key,pid in sorted(latest.items()):
        e=byid.get(pid)
        if e and e.get('settlement_path'):
            row,used=load_pair(root,mroot,e); rows.append(row); files.extend(used)
    if not 1<=len(rows)<=5000: raise ValueError(f'expected 1..5000 validated unique settled observations; got {len(rows)}')
    rows.sort(key=lambda x:x['match_key'])
    summary={}
    for side in ('champion','market'):
        summary[side]={k:sum(r[side][k] for r in rows) for k in ('top1','top3','top5')}
        summary[side].update({k:mean([r[side][k] for r in rows]) for k in ('nll','rps')})
        summary[side]['score_1_1_top1']=sum(r[side]['score1']=='1-1' for r in rows)
    deltas={}
    for k in ('nll','rps'):
        v=[r['market'][k]-r['champion'][k] for r in rows]
        deltas[k]={'market_minus_champion_mean':mean(v),'paired_bootstrap_95_ci':bootstrap(v,reps=reps)}
    a=sum(r['champion']['top1'] and not r['market']['top1'] for r in rows); b=sum(r['market']['top1'] and not r['champion']['top1'] for r in rows)
    report={'schema_version':'gf228.paired_champion_market.v1','n':len(rows),'source_cutoff_policy':'same_snapshot_asof_preko','quote_clock_policy':'CAPTURE_ONLY_SOURCE_QUOTE_CLOCK_NOT_VERIFIED','control':'non_promotion_research','methods':{'observation_unit':'latest_by_match unique match_key with nonnull settlement_path','score_grid':'full exact grid; probability sum tolerance 1e-7; tie rank (-p,home,away)','nll':'-log(actual exact-score probability)','rps':'1X2 cumulative ranked probability score Away/Draw/Home divided by 2','bootstrap':{'paired':True,'repetitions':reps,'seed':228,'interval':'percentile 95%'},'top1_test':'two-sided exact McNemar binomial; descriptive only'},'summary':summary,'deltas':deltas,'tests':{'top1_mcnemar':{'champion_only':a,'market_only':b,'two_sided_exact_p':binom2(a,b),'interpretation':'descriptive; no promotion inference'}},'matches':[{'match_key':r['match_key'],'actual':r['actual'],'top1':r['top1'],'champion':{k:r['champion'][k] for k in ('score1','top1','top3','top5')},'market':{k:r['market'][k] for k in ('score1','top1','top3','top5')}} for r in rows[-250:]],'match_display_limit':250,'provenance':{'index_sha256':sha(index),'source_files_sha256':hashlib.sha256(''.join(sha(p) for p in sorted(set(files),key=str)).encode()).hexdigest()}}
    canonical=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); report['report_sha256']=hashlib.sha256(canonical).hexdigest()
    out=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()+b'\n'
    if len(out)>500*1024: raise ValueError('report exceeds 500 KiB')
    return out
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--repo-root',required=True); ap.add_argument('--market-root'); ap.add_argument('--output'); ap.add_argument('--dry-run',action='store_true'); a=ap.parse_args(argv)
    data=build(a.repo_root,a.market_root); target=Path(a.output) if a.output else Path(a.repo_root)/'data/prediction_quality/pure_market_exact_prospective_1/champion_market_paired_review.json'
    if not a.dry_run:
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists() or target.read_bytes()!=data:
            fd,tmp=tempfile.mkstemp(prefix=target.name+'.',suffix='.tmp',dir=str(target.parent))
            try:
                with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(tmp,target)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
    return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,FileNotFoundError,TypeError) as e: raise SystemExit('FAIL CLOSED: '+str(e))
