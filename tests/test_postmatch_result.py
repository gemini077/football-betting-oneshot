import io
import json
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from postmatch_result import fetch_nowscore_result, verify_schedule  # noqa: E402


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def response_for(page: str) -> Response:
    return Response(page.encode("utf-8"))


def test_live_state_header_score_is_not_used_as_final_result():
    page = '<script>var state = 2;</script><p class="odds_hd_bf"><strong>1:0</strong></p>'
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)):
        result, _source, error = fetch_nowscore_result(101)
    assert result is None
    assert "result_not_final" in error


def test_non_final_state_one_header_score_is_not_used():
    page = '<script>var state=1;</script><p class="odds_hd_bf"><strong>2:1</strong></p>'
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)):
        result, _source, error = fetch_nowscore_result(102)
    assert result is None
    assert "result_not_final" in error


def test_missing_state_header_score_is_not_used():
    page = '<p class="odds_hd_bf"><strong>1:1</strong></p>'
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)):
        result, _source, error = fetch_nowscore_result(103)
    assert result is None
    assert "result_not_final" in error


def test_final_state_allows_timeline_score():
    page = '''
    <script>var state=-1;</script>
    <tr data-kind="1"><td>home</td><td></td><td><b>45'</b></td><td></td><td></td></tr>
    '''
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)):
        result, _source, error = fetch_nowscore_result(104)
    assert result["score_90m"] == "1-0"
    assert error is None


def test_final_state_allows_header_fallback_when_timeline_is_unusable():
    page = '<script>var state=-1;</script><p class="odds_hd_bf"><strong>3:2</strong></p>'
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)):
        result, _source, error = fetch_nowscore_result(105)
    assert result["score_90m"] == "3-2"
    assert error is None


def test_espn_finality_contract_remains_completed_post_period_two():
    payload = {
        "events": [{
            "id": "espn-final",
            "date": "2026-07-28T15:00Z",
            "status": {"period": 2, "type": {"state": "post", "completed": True}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Home FC"}, "score": "1"},
                {"homeAway": "away", "team": {"displayName": "Away FC"}, "score": "0"},
            ]}],
        }],
    }

    class JsonResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    from postmatch_result import fetch_espn_result

    def opener(_request, timeout=0):
        return JsonResponse(json.dumps(payload).encode("utf-8"))

    result, _source, error = fetch_espn_result({
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_local": "2026-07-28T23:00:00+08:00",
    }, opener)
    assert result["score_90m"] == "1-0"
    assert error is None


def test_espn_incomplete_event_is_not_final():
    payload = {
        "events": [{
            "id": "espn-live",
            "date": "2026-07-28T15:00Z",
            "status": {"period": 1, "type": {"state": "in", "completed": False}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Home FC"}, "score": "1"},
                {"homeAway": "away", "team": {"displayName": "Away FC"}, "score": "0"},
            ]}],
        }],
    }

    class JsonResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    from postmatch_result import fetch_espn_result

    def opener(_request, timeout=0):
        return JsonResponse(json.dumps(payload).encode("utf-8"))

    result, _source, error = fetch_espn_result({
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_local": "2026-07-28T23:00:00+08:00",
    }, opener)
    assert result is None
    assert error == "result_not_final"


def test_live_nowscore_result_is_not_written_to_result_store(tmp_path):
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(json.dumps({
        "match_key": "shuju:999",
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_local": "2026-07-28T18:00:00+08:00",
        "nowscore_id": 999,
        "review_due_at": "2026-07-28T20:15:00+08:00",
        "status": "scheduled",
        "verification_attempts": 0,
        "retry_policy": {"maximum_retries": 1, "retry_after_minutes": 45},
    }), encoding="utf-8")
    page = '<script>var state=2;</script><p class="odds_hd_bf"><strong>1:0</strong></p>'
    now = datetime(2026, 7, 28, 21, 0, tzinfo=timezone(timedelta(hours=8)))
    with patch("postmatch_result.urllib.request.urlopen", return_value=response_for(page)), \
         patch("postmatch_result.fetch_espn_result", return_value=(None, None, "result_not_final")):
        outcome = verify_schedule(schedule_path, now, tmp_path / "results")
    assert outcome["status"] == "retry_scheduled"
    assert not (tmp_path / "results").exists()
