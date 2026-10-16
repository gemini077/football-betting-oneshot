"""Deterministic 50/50 Champion/market 169-cell pre-kickoff pool."""
import math
from datetime import datetime, timezone

def utc(s):
    d=datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None: raise ValueError("timestamp lacks offset")
    return d.astimezone(timezone.utc)

def validate_grid(cells):
    if isinstance(cells,dict):
        cells=[{"home_goals":k[0],"away_goals":k[1],"probability":v} for k,v in cells.items()]
    if not isinstance(cells,list) or len(cells)!=169: raise ValueError("grid must contain 169 cells")
    out={}
    for c in cells:
        h,a=c["home_goals"],c["away_goals"]; v=c["probability"]
        if type(h) is not int or type(a) is not int or not 0<=h<=12 or not 0<=a<=12: raise ValueError("score outside 0..12")
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0: raise ValueError("invalid probability")
        k=(h,a)
        if k in out: raise ValueError("duplicate score")
        out[k]=float(v)
    if len(out)!=169 or abs(math.fsum(out.values())-1)>1e-10: raise ValueError("incomplete or unnormalized grid")
    return out

def validate_source(src, expected, now):
    for k,v in expected.items():
        field={"selected_prediction_id":"prediction_id","original_cutoff":"source_cutoff_at","original_freeze_created_at":"freeze_created_at","kickoff_timestamp":"kickoff_at"}.get(k,k)
        if src.get(field)!=v: raise ValueError("frozen identity mismatch: "+field)
    dist=src.get("exact_score_distribution",{})
    if dist.get("status")!="FORMAL_EXACT_DISTRIBUTION_FROZEN": raise ValueError("not frozen formal distribution")
    grid=validate_grid(dist.get("cells"))
    if not utc(src["source_cutoff_at"])<=utc(src["freeze_created_at"])<utc(src["kickoff_at"]): raise ValueError("invalid as-of ordering")
    if utc(src["freeze_created_at"])>=now or utc(src["kickoff_at"])<=now: raise ValueError("future leakage or kickoff reached")
    return grid

def rank(g,n): return [f"{h}-{a}" for (h,a),v in sorted(g.items(),key=lambda x:(-x[1],x[0][0],x[0][1]))[:n]]
def blend(champ,market):
    c=validate_grid(champ); m=validate_grid(market)
    return {(h,a):0.5*c[h,a]+0.5*m[h,a] for h in range(13) for a in range(13)}
def distances(c,m):
    keys=set(c)|set(m); tv=.5*math.fsum(abs(c[k]-m[k]) for k in keys); mid={k:(c[k]+m[k])/2 for k in keys}; js=.5*math.fsum(x*math.log2(x/mid[k]) for k,x in c.items() if x>0)+.5*math.fsum(x*math.log2(x/mid[k]) for k,x in m.items() if x>0)
    return js,tv
