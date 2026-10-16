from __future__ import annotations
import argparse, gzip, hashlib, importlib.util, json, math, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'gf221.rolling_paired_score_eval.v1'
METHODS = ('champion', 'bet365', 'blend_50_50')
MONTH_RE = re.compile(r'\d{4}-(?:0[1-9]|1[0-2])\.json\.gz\Z')

class LedgerError(ValueError): pass

def digest(b): return hashlib.sha256(b).hexdigest()
def canonical_json(x): return (json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
def utc(value):
    if not isinstance(value, str): raise LedgerError('invalid_timestamp')
    try: dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception as e: raise LedgerError('invalid_timestamp') from e
    if dt.tzinfo is None or dt.utcoffset() is None: raise LedgerError('naive_timestamp')
    return dt.astimezone(timezone.utc)
def pmf(rows, gf216, field):
    try: out = gf216.pmf_map(rows)
    except Exception as e: raise LedgerError('invalid_' + field) from e
    if set(out) != {f'{h}-{a}' for h in range(13) for a in range(13)}: raise LedgerError('invalid_' + field + '_support')
    if not all(math.isfinite(v) and v >= 0 for v in out.values()) or abs(sum(out.values())-1) > 1e-8: raise LedgerError('unnormalized_' + field)
    return out
def rank(d, n): return sorted(d, key=lambda s: (-d[s], *map(int,s.split('-'))))[:n]
def tops_as_scores(x):
    if not isinstance(x,list) or len(x)!=5 or any(not isinstance(v,str) for v in x) or len(set(x))!=5: raise LedgerError('invalid_top5')
    return x

def load_gf216(repo):
    path=Path(repo)/'greenfield/research/gf216_frozen_three_arm_settlement.py'
    if not path.is_file(): raise LedgerError('missing_gf216_primitive')
    spec=importlib.util.spec_from_file_location('_gf216_frozen_three_arm_settlement', path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def validate_ledger(path, month, gf216):
    raw=path.read_bytes()
    try:
        blob=gzip.decompress(raw); rows=json.loads(blob.decode('utf-8'))
    except Exception as e: raise LedgerError('corrupt_gzip_or_json:' + path.name) from e
    if not isinstance(rows,list): raise LedgerError('ledger_not_list')
    # Canonical JSON body and deterministic gzip envelope as produced by GF220.
    try:
        canonical = canonical_json(rows).rstrip(b'\n')
    except (ValueError, TypeError) as e: raise LedgerError('nonfinite_or_invalid_json_value') from e
    if canonical != blob: raise LedgerError('noncanonical_ledger_json')
    if len(rows)>124: raise LedgerError('month_cap_exceeded')
    seen=set(); daily={}
    for r in rows:
        if not isinstance(r,dict): raise LedgerError('invalid_ledger_row')
        day=r.get('kickoff_utc_date'); mid=r.get('match_id'); pid=r.get('selected_prediction_id')
        if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or day[:7]!=month: raise LedgerError('invalid_ledger_identity')
        if not isinstance(mid,str) or not mid or not isinstance(pid,str) or not pid or Path(pid).name != pid: raise LedgerError('invalid_ledger_identity')
        key=(day,mid)
        if key in seen: raise LedgerError('duplicate_date_match_id')
        seen.add(key); daily[day]=daily.get(day,0)+1
        if daily[day]>4: raise LedgerError('day_cap_exceeded')
        if r.get('research_only') is not True: raise LedgerError('not_research_only')
        if any(k in r for k in ('result','ft','odds','raw_quote')): raise LedgerError('forbidden_ledger_field')
        p=pmf(r.get('market_pmf_169'),gf216,'market_pmf')
        tops_as_scores(r.get('original_top5')); tops_as_scores(r.get('market_top5')); tops_as_scores(r.get('combined_top5'))
        for field in ('kickoff_timestamp','source_cutoff_at','freeze_created_at'):
            utc(r.get(field))
        ko=utc(r['kickoff_timestamp'])
        if ko.date().isoformat()!=day: raise LedgerError('kickoff_date_mismatch')
        if not utc(r['source_cutoff_at']) < ko or not utc(r['freeze_created_at']) < ko: raise LedgerError('not_frozen_pre_kickoff')
        if not isinstance(r.get('champion_source_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',r['champion_source_sha256']): raise LedgerError('invalid_source_sha')
        if not isinstance(r.get('snapshot_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',r['snapshot_sha256']): raise LedgerError('invalid_snapshot_sha')
        # Validate probability ordering invariants once source record is loaded later.
    return rows, digest(raw)

def evaluate(repo_root, months_root=None, output=None, no_write=False):
    repo=Path(repo_root).resolve(); gf216=load_gf216(repo)
    ledgers=Path(months_root) if months_root else repo/'data/prediction_quality/research_shadow_monthly'
    files=sorted(ledgers.iterdir(), key=lambda p:p.name) if ledgers.exists() else []
    if any(p.is_file() and p.name.endswith('.json.gz') and not MONTH_RE.fullmatch(p.name) for p in files): raise LedgerError('noncanonical_month_filename')
    entries=[]; hashes={}
    for p in files:
        if p.is_file() and MONTH_RE.fullmatch(p.name):
            rows,h=validate_ledger(p,p.name[:-8],gf216); hashes[p.name]=h
            entries.extend((p,r) for r in rows)
    records_dir=repo/'data/model_governance/predictions'; results=repo/'data/postmatch_automation/results'
    matches=[]
    for path,row in entries:
        pid=row['selected_prediction_id']; source=records_dir/(pid+'.json')
        if not source.is_file(): raise LedgerError('missing_frozen_champion_source:'+pid)
        raw=source.read_bytes()
        if digest(raw)!=row['champion_source_sha256']: raise LedgerError('champion_source_sha_mismatch:'+pid)
        try: rec=json.loads(raw.decode('utf-8'))
        except Exception as e: raise LedgerError('invalid_champion_source:'+pid) from e
        if rec.get('prediction_id')!=pid or str(rec.get('match_id'))!=str(row['match_id']): raise LedgerError('champion_identity_mismatch:'+pid)
        if utc(rec.get('kickoff_at')) != utc(row['kickoff_timestamp']): raise LedgerError('champion_kickoff_mismatch:'+pid)
        if rec.get('source_cutoff_at') != row.get('source_cutoff_at') or rec.get('freeze_created_at') != row.get('freeze_created_at'): raise LedgerError('champion_freeze_mismatch:'+pid)
        ko=utc(rec['kickoff_at'])
        if not utc(rec['source_cutoff_at']) < ko or not utc(rec['freeze_created_at']) < ko: raise LedgerError('champion_not_prefreeze:'+pid)
        champ=gf216.champion_pmf(rec)
        if set(champ)!={f'{h}-{a}' for h in range(13) for a in range(13)} or any(not math.isfinite(v) or v<0 for v in champ.values()) or abs(sum(champ.values())-1)>1e-8: raise LedgerError('invalid_champion_pmf:'+pid)
        market=pmf(row['market_pmf_169'],gf216,'market_pmf')
        blend={s:(champ[s]+market[s])/2 for s in champ}
        if rank(champ,5)!=row['original_top5'] or rank(market,5)!=row['market_top5'] or rank(blend,5)!=row['combined_top5']: raise LedgerError('top5_invariant_mismatch:'+pid)
        ref=row.get('input_snapshot_ref')
        if isinstance(ref,str) and ref:
            snap=(repo/ref).resolve()
            try: snap.relative_to(repo)
            except ValueError: raise LedgerError('snapshot_ref_outside_repo')
            if snap.is_file() and digest(snap.read_bytes())!=row['snapshot_sha256']: raise LedgerError('snapshot_sha_mismatch:'+pid)
        item={'match_key':rec.get('match_key'),'kickoff_at':rec['kickoff_at'],'identity':rec.get('match_identity') or {},'pmfs':{'champion':champ,'bet365':market,'blend_50_50':blend}}
        if not isinstance(item['match_key'],str) or not item['match_key']: raise LedgerError('missing_match_key:'+pid)
        state=gf216.resolve_result(item,results)
        out={'match_id':str(row['match_id']),'match_key':item['match_key'],'prediction_id':pid,'state':state['state']}
        if state['state']=='EXCLUDED': out['reason']=state['reason']
        elif state['state']=='SETTLED': out.update({k:state[k] for k in ('score','metrics')})
        else: out['reason']=state['reason']
        matches.append(out)
    matches.sort(key=lambda x:(x['match_key'],x['match_id'],x['prediction_id']))
    settled=[x for x in matches if x['state']=='SETTLED']; summary={'settled':len(settled),'pending':sum(x['state']=='PENDING' for x in matches),'excluded':sum(x['state']=='EXCLUDED' for x in matches),'methods':{}}
    # All mean NLLs must use exactly the same matched events; never compare different cohorts.
    paired=[x for x in settled if all(x['metrics'][m]['nll'] is not None for m in METHODS)]
    for method in METHODS:
        vals=[x['metrics'][method] for x in settled]; nll=[x['metrics'][method]['nll'] for x in paired]
        summary['methods'][method]={'top1':sum(v['top1'] for v in vals)/len(vals) if vals else None,'top3':sum(v['top3'] for v in vals)/len(vals) if vals else None,'top5':sum(v['top5'] for v in vals)/len(vals) if vals else None,'mean_nll':sum(nll)/len(nll) if nll else None,'nll_matches':len(nll),'nll_excluded_zero_probability':sum(v['nll'] is None for v in vals)}
    report={'schema':SCHEMA,'summary':summary,'matches':matches,'provenance':{'monthly_ledger_sha256':hashes}}
    report['checksum_sha256']=digest(canonical_json(report))
    raw=canonical_json(report)
    if len(raw)>=1_000_000: raise LedgerError('report_too_large')
    if not no_write:
        dest=Path(output) if output else repo/'data/prediction_dashboard/gf221_rolling_shadow_review.json'
        if not dest.exists() or dest.read_bytes()!=raw:
            dest.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(prefix='.'+dest.name+'.',suffix='.tmp',dir=dest.parent)
            try:
                with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
                os.replace(tmp,dest)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
    return report

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--repo-root',required=True); ap.add_argument('--months-root'); ap.add_argument('--output'); ap.add_argument('--no-write',action='store_true'); a=ap.parse_args(argv)
    report=evaluate(a.repo_root,a.months_root,a.output,a.no_write); print(json.dumps(report['summary'],sort_keys=True,separators=(',',':'))); return 0
if __name__=='__main__': raise SystemExit(main())

