#!/usr/bin/env python3
"""Prequential score-PMF calibration research; never changes frozen inputs."""
import argparse, json, math, sys
from collections import defaultdict
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pme_champion_paired_audit as audit

GRID = (0.75, 1.0, 1.25, 1.5, 2.0)
FAMILIES = ('one_one_odds', 'draw_diagonal_odds', 'pmf_power')
EPS = 1e-15

def transform(pmf, family, coefficient):
    if coefficient not in GRID: raise ValueError('coefficient outside fixed grid')
    out={}
    for (h,a),p in pmf.items():
        if family=='one_one_odds': w=coefficient if (h,a)==(1,1) else 1.0
        elif family=='draw_diagonal_odds': w=coefficient if h==a else 1.0
        elif family=='pmf_power': w=1.0; p=max(p,EPS)**coefficient
        else: raise ValueError('unknown family')
        out[h,a]=p*w
    z=sum(out.values())
    if not math.isfinite(z) or z<=0: raise ValueError('invalid transformed normalization')
    out={k:v/z for k,v in out.items()}
    if abs(sum(out.values())-1)>1e-12: raise ValueError('transformed PMF normalization')
    return out

def choose(training, family):
    # Baseline coefficient 1 wins ties; require material mean-NLL improvement.
    base=sum(-math.log(max(x['champion'][(x['actual'][0],x['actual'][1])],EPS)) for x in training)/len(training)
    scores=[]
    for c in GRID:
        vals=[-math.log(max(transform(x['champion'],family,c)[x['actual']],EPS)) for x in training]
        scores.append((sum(vals)/len(vals),c))
    best=min(scores,key=lambda z:(round(z[0],12), z[1]!=1.0, abs(z[1]-1),z[1]))
    return 1.0 if base-best[0] < 0.005 else best[1]

def summarize(rows, pmf_key):
    n=len(rows); vals=[r[pmf_key] for r in rows]; acts=[r['actual'] for r in rows]
    metrics=[]
    for m,a in zip(vals,acts):
        rank=sorted(m,key=lambda k:(-m[k],k[0],k[1])); metrics.append(audit.metric(m,rank,a))
    return {'n':n,'nll':sum(x['nll'] for x in metrics)/n,'top1':sum(x['top1'] for x in metrics),'top3':sum(x['top3'] for x in metrics),'top5':sum(x['top5'] for x in metrics),'expected_1_1':sum(m.get((1,1),0) for m in vals),'observed_1_1':sum(a==(1,1) for a in acts),'rps_1x2':sum(x['rps'] for x in metrics)/n}

def build(root, market_root=None):
    root=Path(root); mr=Path(market_root) if market_root else root/'data/prediction_quality/pure_market_exact_prospective_1'
    ix=audit.read(mr/'latest_index.json'); entries=ix.get('predictions',[]); byid={e['prediction_id']:e for e in entries}; rows=[]
    for key,pid in sorted(ix.get('latest_by_match',{}).items()):
        e=byid.get(pid)
        if not e or not e.get('settlement_path'): continue
        checked,_=audit.load_pair(root,mr,e)  # full frozen identity/as-of/settlement validation
        p=audit.read(mr/e['prediction_path']); ref=p['champion_reference']; c=audit.read(root/'data/model_governance/predictions'/(ref['prediction_id']+'.json'))
        cm,_=audit.matrix(c['exact_score_distribution']['cells'],12,'champion'); mm,_=audit.matrix(p['score_matrix'],20,'market')
        actual=tuple(map(int,checked['actual'].split('-'))); day=audit.matchday_utc({'kickoff_at':checked['kickoff_at']})
        rows.append({'day':day.isoformat(),'key':key,'actual':actual,'champion':cm,'market':mm})
    if not 1<=len(rows)<=5000: raise ValueError('expected 1..5000 strictly validated settled unique matches')
    rows.sort(key=lambda r:(r['day'],r['key']))
    days=sorted({r['day'] for r in rows}); output=[]
    # Whole UTC day held out; >=3 prior days and >=10 prior matches before fitting.
    for day in days:
        train=[r for r in rows if r['day']<day]; test=[r for r in rows if r['day']==day]
        if len({r['day'] for r in train})<3 or len(train)<10: continue
        choices={f:choose(train,f) for f in FAMILIES}
        cohort=[]
        for r in test:
            z=dict(r); z['market_baseline']=r['market']
            for f in FAMILIES: z[f]=transform(r['champion'],f,choices[f])
            cohort.append(z)
        methods={k:summarize(cohort,k) for k in ('champion','market_baseline',*FAMILIES)}
        base=methods['champion']
        for val in methods.values(): val['delta_vs_champion']={k:val[k]-base[k] for k in ('nll','top1','top3','top5','expected_1_1','observed_1_1','rps_1x2')}
        output.append({'utc_matchday':day,'training_n':len(train),'training_days':len({r['day'] for r in train}),'test_n':len(test),'coefficients':choices,'methods':methods})
    report={'schema':'gf240.forward_score_calibration.v1','mode':'RESEARCH_ONLY_PREQUENTIAL','source_cutoff':'reuse strict GF228 load_pair as-of identity, cutoff and regulation settlement checks','max_matches':5000,'families':list(FAMILIES),'grid':list(GRID),'minimum_training':{'unique_utc_days':3,'matches':10},'tuning':'training NLL only; deterministic baseline tie preference; require >=0.005 mean NLL gain','promotion':'NONE; no significance claims','evaluated_days':len(output),'segments':output}
    data=json.dumps(report,sort_keys=True,separators=(',',':')).encode()+b'\n'
    if len(data)>200*1024: raise ValueError('report exceeds 200 KiB')
    return data

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--repo-root',required=True); ap.add_argument('--market-root'); ap.add_argument('--output'); ap.add_argument('--dry-run',action='store_true'); a=ap.parse_args(argv)
    data=build(a.repo_root,a.market_root)
    if a.output and not a.dry_run:
        target=Path(a.output); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
    elif not a.output: sys.stdout.buffer.write(data)
    return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,FileNotFoundError,TypeError) as e: raise SystemExit('FAIL CLOSED: '+str(e))

