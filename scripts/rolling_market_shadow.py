"""Bounded monthly pre-kickoff market score-distribution shadow capture."""
from __future__ import annotations
import argparse, gzip, hashlib, importlib.util, json, math, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_DAY = 4
MAX_MONTH = 124
MAX_GZIP = 1024 * 1024
SOURCE_TIME = "CAPTURE_ONLY_ORIGINAL_BOOK_QUOTE_TIME_UNVERIFIED"

class LedgerError(ValueError): pass

def utc(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError("invalid_timestamp")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None: raise ValueError("naive_timestamp")
    return d.astimezone(timezone.utc)

def compact(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(b): return hashlib.sha256(b).hexdigest()

def modules(repo_root):
    # Normal package imports first; temp/self-contained fallback is the pinned modules beside this script.
    try:
        from greenfield.research import gf214_preko_bet365_shadow as gf214
        from greenfield.research import gf215_preko_pair_blend as gf215
        return gf214, gf215
    except ImportError:
        here = Path(__file__).resolve().parent
        def load(name, p):
            spec = importlib.util.spec_from_file_location(name, p)
            if spec is None or spec.loader is None: raise ImportError(name)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
        a = Path(repo_root) / "greenfield/research/gf214_preko_bet365_shadow.py"
        b = Path(repo_root) / "greenfield/research/gf215_preko_pair_blend.py"
        return load("_gf214", a if a.is_file() else here / "gf214.py"), load("_gf215", b if b.is_file() else here / "gf215.py")

def _safe_ref(root, ref):
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute() or ".." in Path(ref).parts: raise ValueError("invalid_source_ref")
    p = (root / ref).resolve()
    if root.resolve() not in p.parents: raise ValueError("invalid_source_ref")
    return p

def _finite_grid(raw, gf215):
    grid = gf215.validate_grid(raw)
    if len(grid) != 169 or any(not math.isfinite(x) for x in grid.values()): raise ValueError("invalid_pmf_169")
    return grid

def _rank(grid, n, gf215): return gf215.rank(grid, n)

def _entry_key(row): return (str(row.get("match_id", "")), str(row.get("selected_prediction_id", "")))

def validate_ledger(path, month, gf215):
    if not path.exists(): return []
    raw = path.read_bytes()
    if len(raw) > MAX_GZIP: raise LedgerError("ledger_too_large")
    try:
        payload = gzip.decompress(raw)
        rows = json.loads(payload)
    except Exception as e: raise LedgerError("ledger_corrupt") from e
    if not isinstance(rows, list) or compact(rows) != payload: raise LedgerError("ledger_noncanonical")
    if len(rows) > MAX_MONTH: raise LedgerError("month_cap_exceeded")
    seen = set(); dates = {}
    for r in rows:
        if not isinstance(r, dict): raise LedgerError("invalid_ledger_row")
        if r.get("research_only") is not True: raise LedgerError("not_research_only")
        mid, pid = _entry_key(r); date = r.get("kickoff_utc_date")
        if not mid or not pid or not isinstance(date, str) or date[:7] != month: raise LedgerError("invalid_ledger_identity")
        k=(date,mid)
        if k in seen: raise LedgerError("ledger_duplicate")
        seen.add(k); dates[date] = dates.get(date, 0)+1
        if dates[date] > MAX_DAY: raise LedgerError("day_cap_exceeded")
        if "result" in r or "ft" in r or "odds" in r or "raw_quote" in r: raise LedgerError("forbidden_ledger_field")
        market = _finite_grid(r.get("market_pmf_169"), gf215)
        if len(market)!=169: raise LedgerError("invalid_market_pmf")
        tops=r.get("original_top5"); combined=r.get("combined_top5")
        if not isinstance(tops,list) or len(tops)!=5 or not isinstance(combined,list) or len(combined)!=5: raise LedgerError("invalid_top5")
    return rows

def capture_one(row, repo_root, now, gf214, gf215):
    mid = str(row.get("match_id", "")); pid = row.get("selected_prediction_id")
    if not mid or not isinstance(pid,str) or not pid or Path(pid).name != pid: raise ValueError("missing_identity")
    if row.get("status") != "FROZEN": raise ValueError("not_frozen")
    
    ko = utc(row.get("kickoff_timestamp")); cut = utc(row.get("selected_source_cutoff_at")); freeze=utc(row.get("selected_freeze_created_at"))
    if ko <= now: raise ValueError("not_future")
    if ko-cut < __import__('datetime').timedelta(minutes=15): raise ValueError("cutoff_buffer_under_15m")
    if cut>freeze or freeze>=ko: raise ValueError("invalid_freeze_order")
    ref=(row.get("prediction") or {}).get("input_snapshot_ref")
    snap_path=_safe_ref(repo_root,ref); snap_bytes=snap_path.read_bytes()
    snap=json.loads(snap_bytes)
    ns=snap["input"]["source_snapshots"]["nowscore"]["snapshots"]
    if not isinstance(ns,list) or len(ns)!=1: raise ValueError("nowscore_snapshot_not_unique")
    # Original quote must be a unique Bet365 source in each market and match exact cutoff.
    if utc(ns[0].get("fetched_at")) != cut: raise ValueError("quote_time_mismatch")
    if utc(snap.get("source_cutoff_at")) != cut: raise ValueError("snapshot_cutoff_mismatch")
    src_path=repo_root/"data/model_governance/predictions"/(pid+".json")
    src_bytes=src_path.read_bytes(); src=json.loads(src_bytes)
    # Compare actual UTC instants: public dashboard uses Z, frozen models may use +08:00.
    if utc(src.get("kickoff_at")) != ko: raise ValueError("frozen_kickoff_mismatch")
    expected={"selected_prediction_id":pid,"original_cutoff":row["selected_source_cutoff_at"],"original_freeze_created_at":row["selected_freeze_created_at"],"kickoff_timestamp":src["kickoff_at"]}
    champ=_finite_grid(gf215.validate_source(src,expected,now),gf215)
    market_record=gf214.snapshot_record(row,snap_bytes,now)
    # GF214's GF216-era date literal is corrected to the actual UTC kickoff date.
    market_record["date"] = ko.date().isoformat()
    pmf=[]
    for cell in market_record["market"]["pmf_169"]:
        h,a=map(int,cell["score"].split("-")); pmf.append({"home_goals":h,"away_goals":a,"probability":cell["probability"]})
    market=_finite_grid(pmf,gf215)
    blend=gf215.blend(champ,market)
    original_top5=_rank(champ,5,gf215)
    if len(original_top5)!=5 or len(set(original_top5))!=5: raise ValueError("invalid_original_top5")
    return {"research_only":True,"kickoff_utc_date":ko.date().isoformat(),"match_id":mid,"selected_prediction_id":pid,
      "champion_source_sha256":digest(src_bytes),"snapshot_sha256":digest(snap_bytes),
      "source_cutoff_at":row["selected_source_cutoff_at"],"freeze_created_at":row["selected_freeze_created_at"],"kickoff_timestamp":row["kickoff_timestamp"],
      "input_snapshot_ref":ref,"source_time":SOURCE_TIME,"market_pmf_169":[{"home_goals":h,"away_goals":a,"probability":market[h,a]} for h in range(13) for a in range(13)],
      "original_top5":original_top5,"market_top1":_rank(market,1,gf215),"market_top3":_rank(market,3,gf215),"market_top5":_rank(market,5,gf215),
      "combined_top1":_rank(blend,1,gf215),"combined_top3":_rank(blend,3,gf215),"combined_top5":_rank(blend,5,gf215)}

def _atomic_write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def run(repo_root, now=None, max_per_day=4, output_root=None, dry_run=False):
    root=Path(repo_root).resolve(); now=utc(now) if now else datetime.now(timezone.utc)
    if not isinstance(max_per_day,int) or isinstance(max_per_day,bool) or not 1<=max_per_day<=MAX_DAY: raise ValueError("max_per_day_must_be_1_to_4")
    gf214,gf215=modules(root)
    dash=json.loads((root/"data/prediction_dashboard/latest.json").read_bytes()); fixtures=dash.get("fixtures")
    if not isinstance(fixtures,list): raise ValueError("missing_fixtures")
    out=Path(output_root) if output_root else root/"data/prediction_quality/research_shadow_monthly"
    # Validate every existing month before processing anything: corruption is fail-closed/no-write.
    ledgers={}
    import re
    for p in sorted(out.glob("*.json.gz")):
        month=p.name.removesuffix(".json.gz")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",month): raise LedgerError("invalid_month_filename")
        ledgers[month]=validate_ledger(p,month,gf215)
    reasons={}; candidates=[]; seen=set()
    for row in fixtures:
        if not isinstance(row,dict) or row.get("status")!="FROZEN": continue
        try:
            k=(utc(row.get("kickoff_timestamp")).date().isoformat(),str(row.get("match_id","")))
            if not k[1]: raise ValueError("missing_match_id")
            if k in seen: raise ValueError("duplicate_date_match_id")
            seen.add(k)
            ko=utc(row.get("kickoff_timestamp"))
            if ko<=now: raise ValueError("not_future")
            candidates.append((ko,str(row.get("match_id","")),row))
        except Exception as e: reasons[str(e)]=reasons.get(str(e),0)+1
    candidates.sort(key=lambda x:(x[0],x[1]))
    counts={}
    for existing in ledgers.values():
        for record in existing:
            day=record["kickoff_utc_date"]; counts[day]=counts.get(day,0)+1
    additions={}; processed=0
    for ko,mid,row in candidates:
        date=ko.date().isoformat(); month=date[:7]; key=(date,mid)
        prior=next((r for r in ledgers.get(month,[]) if (r.get("kickoff_utc_date"),r.get("match_id"))==key),None)
        if prior:
            if prior.get("selected_prediction_id") != row.get("selected_prediction_id"):
                reasons["existing_record_conflict"]=reasons.get("existing_record_conflict",0)+1
            continue
        if counts.get(date,0)>=max_per_day: reasons["daily_cap_reached"]=reasons.get("daily_cap_reached",0)+1; continue
        try: record=capture_one(row,root,now,gf214,gf215)
        except Exception as e:
            reason=str(e) if str(e) else type(e).__name__; reasons[reason]=reasons.get(reason,0)+1; continue
        counts[date]=counts.get(date,0)+1; additions.setdefault(month,[]).append(record); processed+=1
    prepared=[]
    for month,newrows in sorted(additions.items()):
        merged=sorted(ledgers.get(month,[])+newrows,key=lambda r:(r["kickoff_utc_date"],r["match_id"]))
        if len(merged)>MAX_MONTH: raise LedgerError("month_cap_exceeded")
        gz=gzip.compress(compact(merged),mtime=0)
        if len(gz)>MAX_GZIP: raise LedgerError("ledger_too_large")
        path=out/(month+".json.gz")
        prepared.append((path,gz,month,len(newrows)))
    written=[]
    for path,gz,month,nrows in prepared:
        if not dry_run: _atomic_write(path,gz)
        written.append({"month":month,"rows":nrows,"bytes":len(gz),"sha256":digest(gz),"dry_run":dry_run})
    return {"captured":processed,"writes":written,"skipped":sum(reasons.values()),"reasons":dict(sorted(reasons.items())),"dry_run":dry_run}

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--repo-root",required=True); ap.add_argument("--now",help="ISO timestamp for deterministic tests only"); ap.add_argument("--max-per-day",type=int,default=4); ap.add_argument("--output-root"); ap.add_argument("--dry-run",action="store_true")
    a=ap.parse_args(argv)
    try: result=run(a.repo_root,a.now,a.max_per_day,a.output_root,a.dry_run)
    except LedgerError as e: print(json.dumps({"error":str(e),"writes":[]},sort_keys=True)); return 2
    print(json.dumps(result,sort_keys=True,separators=(",",":"))); return 0
if __name__=="__main__": raise SystemExit(main())

