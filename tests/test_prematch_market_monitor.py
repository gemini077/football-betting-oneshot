from datetime import datetime
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from prematch_market_monitor import due_matches

def test_due_matches_only_returns_analyzed_near_kickoff():
    workspace={"matches":[{"id":"1","report_state":"已分析","kickoff":"2026-07-16 03:00"},{"id":"2","report_state":"未分析","kickoff":"2026-07-16 02:30"},{"id":"3","report_state":"已分析","kickoff":"2026-07-17 03:00"}]}
    assert [row["id"] for row in due_matches(workspace,datetime.fromisoformat("2026-07-15 23:00"))] == ["1"]
