import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prematch_fundamentals import collect_prematch_fundamentals


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_collects_checked_fields_and_does_not_claim_no_injuries():
    scoreboard = {"events": [{"id": "99", "name": "Away at Home", "date": "2026-07-15T18:15Z"}]}
    summary = {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1"}},
            {"homeAway": "away", "team": {"id": "2"}},
        ]}]},
        "gameInfo": {"venue": {"fullName": "Test Stadium", "address": {"city": "Test City"}}},
        "rosters": [],
        "lastFiveGames": [{"events": [{
            "homeTeamId": "2", "awayTeamId": "1", "score": "2-1",
            "gameDate": "2026-07-07T18:00Z", "competitionName": "Qualifier",
            "links": [{"href": "https://example.test/first-leg"}],
        }]}],
    }

    def opener(request, timeout=0):
        payload = summary if "summary" in request.full_url else scoreboard
        return Response(json.dumps(payload).encode())

    deep = {"shuju": {"recent_form": {"home_overall": {
        "matches": 10, "wins": 7, "draws": 1, "losses": 2,
        "goals_for": 20, "goals_against": 9,
    }}}}
    result = collect_prematch_fundamentals({"kickoff": "2026-07-16 02:15"}, deep, opener)
    values = {row["label"]: row["value"] for row in result["items"]}
    assert values["比赛场地"] == "Test Stadium · Test City"
    assert values["确认首发"].startswith("尚未发布")
    assert "不等同于无人伤停" in values["伤停核验"]
    assert values["最近直接交锋"].startswith("2-1")


def test_refuses_ambiguous_kickoff_match():
    events = {"events": [
        {"id": "1", "date": "2026-07-15T18:15Z"},
        {"id": "2", "date": "2026-07-15T18:15Z"},
    ]}

    def opener(request, timeout=0):
        return Response(json.dumps(events).encode())

    result = collect_prematch_fundamentals({"kickoff": "2026-07-16 02:15"}, {}, opener)
    assert result["status"] == "近期攻防已核验；未能唯一匹配外部赛程"
    assert "候选2场" in result["items"][-1]["value"]
