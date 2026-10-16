import hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
from scripts.market_score_math import fit_market_lambdas

BASE = "https://raw.githubusercontent.com/gemini077/football-betting-oneshot/main/"
DASH = "https://gemini077.github.io/football-betting-oneshot/prediction_dashboard/latest.json"

def timestamp(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError("missing_timestamp")
    try: d=datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as e: raise ValueError("invalid_timestamp") from e
    if d.tzinfo is None: raise ValueError("naive_timestamp")
    return d.astimezone(timezone.utc)

def number(value, name):
    if isinstance(value, bool): raise ValueError("invalid_"+name)
    try: n=float(value)
    except Exception as e: raise ValueError("invalid_"+name) from e
    if not math.isfinite(n): raise ValueError("nonfinite_"+name)
    return n

def single_named(rows, key, value):
    if not isinstance(rows,list): raise ValueError("missing_"+key)
    found=[r for r in rows if isinstance(r,dict) and str(r.get(key,"" )).strip().lower()==value]
    if len(found)!=1: raise ValueError(("duplicate_" if len(found)>1 else "missing_")+value)
    return found[0]

def inverse_normalize(values):
    vals=[number(v,"odds") for v in values]
    if any(v<=1 for v in vals): raise ValueError("odds_not_above_one")
    inv=[1/v for v in vals]; total=sum(inv)
    if not math.isfinite(total) or total<=0: raise ValueError("invalid_probability_sum")
    return [v/total for v in inv]

def market_targets(snap):
    try:
        ns=snap["input"]["source_snapshots"]["nowscore"]["snapshots"]
        if not isinstance(ns,list) or not ns or not isinstance(ns[0],dict): raise ValueError("missing_nowscore_snapshot")
        raw=ns[0]
        w=single_named(raw.get("ouzhi",{}).get("bookmakers"),"name","bet365")
        d=single_named(raw.get("daxiao",{}).get("companies"),"name","bet365")
        spf=w.get("spf_current")
        if isinstance(spf,dict):
            if any(k not in spf for k in ("home","draw","away")): raise ValueError("invalid_spf_current")
            spf=[spf[k] for k in ("home","draw","away")]
        elif isinstance(spf,(list,tuple)) and len(spf)==3:
            pass
        else: raise ValueError("invalid_spf_current")
        wdl=inverse_normalize(spf)
        line=number(d.get("current_line"),"line")
        if not math.isfinite(line) or abs((line*2)-round(line*2))>1e-9 or int(round(line*2))%2!=1: raise ValueError("line_not_x5")
        over=1+number(d.get("current_over_water"),"over_water")
        under=1+number(d.get("current_under_water"),"under_water")
        if over<=0 or under<=0: raise ValueError("nonpositive_water_odds")
        ou=inverse_normalize([over,under])[0]
        return wdl,{str(line):ou}
    except (KeyError,TypeError) as e: raise ValueError("missing_market_field") from e

def poisson_pmf(lam, k):
    lam=number(lam,"lambda")
    if lam<0 or k<0: raise ValueError("invalid_poisson_input")
    return math.exp(-lam + k*math.log(lam)-math.lgamma(k+1)) if lam else (1.0 if k==0 else 0.0)

def score_grid(home, away):
    h=[poisson_pmf(home,i) for i in range(13)]; a=[poisson_pmf(away,j) for j in range(13)]
    cells=[(i,j,h[i]*a[j]) for i in range(13) for j in range(13)]
    total=sum(x[2] for x in cells)
    if not math.isfinite(total) or total<=0: raise ValueError("invalid_grid")
    return [{"score":f"{i}-{j}","probability":p/total} for i,j,p in sorted(cells,key=lambda x:(-x[2],x[0],x[1]))]

def top_scores(grid,n): return [x["score"] for x in grid[:n]]
def excluded(row):
    return bool(row.get("pilot_excluded")) or str(row.get("status","")).upper()=="EXCLUDED" or str(row.get("reason_code","")).upper().startswith("EXCLUD")
def eligible_rows(rows, now):
    out=[]; seen=set(); reasons={}
    for r in rows:
        mid=str(r.get("match_id",""))
        try:
            if r.get("status")!="FROZEN": raise ValueError("not_frozen")
            if not mid: raise ValueError("missing_match_id")
            if mid in seen: raise ValueError("duplicate_match_id")
            seen.add(mid)
            if excluded(r): raise ValueError("excluded_row")
            ko=timestamp(r.get("kickoff_timestamp")); fr=timestamp(r.get("selected_freeze_created_at")); cut=timestamp(r.get("selected_source_cutoff_at"))
            if ko.date().isoformat()!="2026-10-16": raise ValueError("not_target_date")
            if ko<=now: raise ValueError("not_future")
            if cut>=ko: raise ValueError("cutoff_not_preko")
            if fr>=ko or fr<cut: raise ValueError("invalid_freeze_time")
            p=r.get("prediction") or {}
            if not isinstance(p.get("input_snapshot_ref"),str) or not p["input_snapshot_ref"].strip(): raise ValueError("missing_snapshot_ref")
            out.append(r)
        except ValueError as e: reasons[str(e)]=reasons.get(str(e),0)+1
    return out,reasons

def snapshot_record(row, snapshot_bytes, now):
    snap=json.loads(snapshot_bytes)
    cutoff=timestamp(row["selected_source_cutoff_at"]); ko=timestamp(row["kickoff_timestamp"])
    ns=snap["input"]["source_snapshots"]["nowscore"]["snapshots"]
    if not isinstance(ns,list) or not ns: raise ValueError("missing_nowscore_snapshot")
    fetched=timestamp(ns[0].get("fetched_at")); source_cut=timestamp(snap.get("source_cutoff_at"))
    if source_cut!=cutoff: raise ValueError("snapshot_source_cutoff_mismatch")
    if fetched!=cutoff: raise ValueError("nowscore_fetched_at_mismatch")
    if source_cut>=ko or fetched>=ko: raise ValueError("snapshot_not_preko")
    if fetched>now: raise ValueError("capture_clock_before_source")
    wdl,ou=market_targets(snap); lh,la=fit_market_lambdas(wdl,ou); grid=score_grid(lh,la)
    p=row["prediction"]
    top3=p.get("score_top3") or []
    if not isinstance(top3,list): raise ValueError("invalid_original_top3")
    original_top3=[(x if isinstance(x,str) else x.get("score")) for x in top3[:3]]
    dist=p.get("score_distribution")
    if not isinstance(dist,list) or len(dist)<5: raise ValueError("incomplete_original_top5")
    original_top5=[x.get("score") for x in dist[:5] if isinstance(x,dict)]
    if len(original_top5)!=5 or any(not isinstance(x,str) or not x for x in original_top5) or len(set(original_top5))!=5: raise ValueError("invalid_original_top5")
    digest=hashlib.sha256(snapshot_bytes).hexdigest()
    cells=score_grid(0,0) if False else sorted(grid,key=lambda x:tuple(map(int,x["score"].split("-"))))
    if len(cells)!=169 or len({x["score"] for x in cells})!=169 or abs(sum(x["probability"] for x in cells)-1)>1e-12: raise ValueError("invalid_pmf_169")
    return {"match_id":str(row["match_id"]),"date":"2026-10-16","original_model":{"top1":p.get("unique_score") or p.get("primary_score"),"top3":original_top3,"top5":original_top5},"original_cutoff":row["selected_source_cutoff_at"],"original_freeze_created_at":row["selected_freeze_created_at"],"kickoff_timestamp":row["kickoff_timestamp"],"input_snapshot_ref":p["input_snapshot_ref"],"selected_prediction_id":row.get("selected_prediction_id"),"fixed_bookmaker":"bet365","market":{"top1":top_scores(grid,1),"top3":top_scores(grid,3),"top5":top_scores(grid,5),"pmf_169":cells},"snapshot_sha256":digest,"snapshot_source_cutoff_at":snap["source_cutoff_at"],"nowscore_fetched_at":ns[0]["fetched_at"],"source_time":"CAPTURE_ONLY"}
