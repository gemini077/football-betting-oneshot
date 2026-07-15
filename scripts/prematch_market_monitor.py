#!/usr/bin/env python3
"""Refresh public pre-match markets only for analyzed matches near kickoff."""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

from prematch_fundamentals import collect_prematch_fundamentals

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "data" / "match_workspace" / "latest.json"
INPUT_ROOT = ROOT / "data" / "analysis_inputs" / "automated"
STATE_PATH = ROOT / "data" / "market_history" / "monitor_state.json"

def load_json(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def parse_time(value):
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError): return None

def due_stage(match, now, hours_before=6.0):
    kickoff=parse_time(match.get("kickoff"))
    if kickoff is None: return None
    if kickoff.tzinfo is None and now.tzinfo is not None: kickoff=kickoff.replace(tzinfo=now.tzinfo)
    minutes=(kickoff-now).total_seconds()/60
    if 90 < minutes <= hours_before*60: return "T-6H"
    if 5 <= minutes <= 90: return "T-90M"
    return None

def due_matches(workspace, now, hours_before=6.0, state=None):
    state=state or {}
    rows=[]
    for match in workspace.get("matches") or []:
        if match.get("report_state") != "已分析": continue
        stage=due_stage(match,now,hours_before)
        if stage and stage not in (state.get(str(match.get("id") or "")) or {}):
            rows.append({**match,"_monitor_stage":stage})
    return sorted(rows,key=lambda row:row.get("kickoff") or "")

def matching_analysis(match):
    match_id=str(match.get("id") or ""); home=str(match.get("home") or ""); away=str(match.get("away") or "")
    for path in sorted(INPUT_ROOT.glob("*.json"), reverse=True):
        try: candidate=(load_json(path).get("match") or {})
        except (OSError,json.JSONDecodeError): continue
        if match_id and str(candidate.get("match_id") or "") == match_id: return path
        if candidate.get("home") == home and candidate.get("away") == away: return path
    return None

def run_json(command, timeout=240):
    completed=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,encoding="utf-8",timeout=timeout)
    if completed.returncode: raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)

def refresh_fundamentals(analysis_path, match):
    """Re-check time-sensitive public facts without discarding existing form rows."""
    payload=load_json(analysis_path)
    checked=collect_prematch_fundamentals(match,{})
    fundamentals=payload.setdefault("fundamentals",{})
    merged={str(item.get("label") or ""):item for item in fundamentals.get("items") or [] if item.get("label")}
    for item in checked.get("items") or []:
        label=str(item.get("label") or "")
        if label: merged[label]=item
    fundamentals["items"]=list(merged.values())
    fundamentals["status"]=checked.get("status") or fundamentals.get("status")
    fundamentals["sources"]=checked.get("sources") or fundamentals.get("sources") or []
    Path(analysis_path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return checked.get("status")

def refresh_match(match):
    analysis=matching_analysis(match)
    label=f"{match.get('home')} vs {match.get('away')}"
    if analysis is None: return {"match":label,"status":"skipped_missing_analysis"}
    fetched=run_json([sys.executable,"scripts/fetch_football_data.py","--date",str(match.get("business_date")),"--match",label,"--deep","--no-cache"])
    fundamentals_status=refresh_fundamentals(analysis,match)
    report=run_json([sys.executable,"scripts/generate_analysis_report.py","--fetch-manifest",fetched["manifest"],"--analysis-json",str(analysis)])
    return {"match":label,"status":"refreshed","report":report.get("html"),"fundamentals":fundamentals_status}

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--now"); parser.add_argument("--hours-before",type=float,default=6.0); parser.add_argument("--count-due",action="store_true"); args=parser.parse_args()
    now=parse_time(args.now) if args.now else datetime.now().astimezone()
    if now is None: raise SystemExit("--now must be an ISO timestamp")
    workspace=load_json(WORKSPACE) if WORKSPACE.exists() else {"matches":[]}
    state=load_json(STATE_PATH) if STATE_PATH.exists() else {}
    due=due_matches(workspace,now,args.hours_before,state)
    if args.count_due:
        print(len(due)); return 0
    results=[]
    for match in due:
        try:
            result=refresh_match(match); result["stage"]=match["_monitor_stage"]; results.append(result)
            if result.get("status") == "refreshed":
                state.setdefault(str(match.get("id") or ""),{})[match["_monitor_stage"]]=now.isoformat()
        except Exception as error: results.append({"match":f"{match.get('home')} vs {match.get('away')}","status":"error","error":str(error)[:500]})
    if any(row.get("status") == "refreshed" for row in results):
        STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
        STATE_PATH.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
        run_json([sys.executable,"scripts/match_workspace.py","--date",str(workspace.get("target_date") or now.date().isoformat())])
        subprocess.run([sys.executable,"scripts/build_public_site.py"],cwd=ROOT,check=True)
    print(json.dumps({"checked_at":now.isoformat(),"due":len(results),"results":results},ensure_ascii=False,indent=2))
    return 1 if any(row.get("status") == "error" for row in results) else 0

if __name__ == "__main__": raise SystemExit(main())
