import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import result_federation_shadow as shadow  # noqa: E402


def test_reep_indexes_map_aliases_to_provider_ids():
    teams = (
        "key_wikidata,name,key_sofascore,key_fotmob\n"
        "Q1,Liverpool F.C.,44,8650\n"
        "Q2,Fulham F.C.,43,9879\n"
    )
    names = (
        "key_wikidata,name,alias\n"
        "Q1,Liverpool F.C.,利物浦|Liverpool\n"
        "Q2,Fulham F.C.,富勒姆|Fulham\n"
    )

    team_index, aliases = shadow.build_reep_indexes(teams, names)

    assert aliases[shadow._norm("利物浦")] == {"Q1"}
    assert aliases[shadow._norm("富勒姆")] == {"Q2"}
    assert team_index["Q1"]["key_sofascore"] == "44"
    assert team_index["Q1"]["key_fotmob"] == "8650"


def test_wikidata_candidate_requires_unique_football_club():
    payload = {
        "search": [
            {"id": "Q1", "label": "利物浦", "description": "association football club in Liverpool, England", "match": {"text": "利物浦"}},
            {"id": "Q2", "label": "利物浦市", "description": "city in England", "match": {"text": "利物浦"}},
        ]
    }
    assert shadow.choose_wikidata_candidate(payload, "利物浦")["id"] == "Q1"

    ambiguous = {
        "search": [
            {"id": "Q1", "label": "A", "description": "association football club", "match": {"text": "X"}},
            {"id": "Q2", "label": "B", "description": "association football club", "match": {"text": "Y"}},
        ]
    }
    assert shadow.choose_wikidata_candidate(ambiguous, "未知") is None


def test_sofascore_exact_provider_identity_and_normaltime_score():
    kickoff = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 100,
            "startTimestamp": int(kickoff.timestamp()),
            "homeTeam": {"id": 44, "name": "Liverpool"},
            "awayTeam": {"id": 43, "name": "Fulham"},
            "status": {"type": "finished"},
            "homeScore": {"current": 0, "normaltime": 0},
            "awayScore": {"current": 0, "normaltime": 0},
        },
        {
            "id": 101,
            "startTimestamp": int(kickoff.timestamp()),
            "homeTeam": {"id": 999, "name": "Other"},
            "awayTeam": {"id": 43, "name": "Fulham"},
            "status": {"type": "finished"},
        },
    ]

    event = shadow.match_sofascore_event(
        events, home_id="44", away_id="43", kickoff=kickoff
    )
    summary = shadow.sofascore_summary(event)

    assert summary["event_id"] == 100
    assert summary["status"] == "FINISHED"
    assert summary["score_90m_candidate"] == "0-0"
    assert summary["score_basis"] == "normaltime"


def test_provider_identity_rejects_wrong_kickoff_and_duplicate_matches():
    kickoff = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
    wrong_time = {
        "id": 100,
        "startTimestamp": int((kickoff.replace(hour=18)).timestamp()),
        "homeTeam": {"id": 44},
        "awayTeam": {"id": 43},
    }
    assert shadow.match_sofascore_event(
        [wrong_time], home_id="44", away_id="43", kickoff=kickoff
    ) is None

    good = {
        "id": 101,
        "startTimestamp": int(kickoff.timestamp()),
        "homeTeam": {"id": 44},
        "awayTeam": {"id": 43},
    }
    duplicate = dict(good, id=102)
    assert shadow.match_sofascore_event(
        [good, duplicate], home_id="44", away_id="43", kickoff=kickoff
    ) is None


def test_fotmob_exact_provider_identity_and_finished_score():
    kickoff = datetime(2026, 9, 9, 19, 0, tzinfo=timezone.utc)
    rows = [
        {
            "id": 555,
            "timeTS": int(kickoff.timestamp() * 1000),
            "home": {"id": 10, "name": "Charlton Athletic"},
            "away": {"id": 20, "name": "Queens Park Rangers"},
            "status": {
                "finished": True,
                "started": True,
                "cancelled": False,
                "scoreStr": "0 - 0",
                "reason": {"short": "FT"},
            },
        }
    ]

    event = shadow.match_fotmob_event(
        rows, home_id="10", away_id="20", kickoff=kickoff
    )
    summary = shadow.fotmob_summary(event)

    assert summary["event_id"] == 555
    assert summary["status"] == "FINISHED"
    assert summary["score_fulltime_candidate"] == "0-0"


def test_adjudication_requires_agreement_for_consensus():
    sofa = {"identity": "MATCHED", "status": "FINISHED", "score_90m_candidate": "2-1"}
    fotmob = {"identity": "MATCHED", "status": "FINISHED", "score_fulltime_candidate": "2-1"}
    assert shadow.adjudicate(sofa, fotmob) == {
        "decision": "CONSENSUS_FINISHED_SCORE",
        "score_90m_candidate": "2-1",
    }

    conflict = dict(fotmob, score_fulltime_candidate="1-1")
    assert shadow.adjudicate(sofa, conflict)["decision"] == "CONFLICT"


def test_non_played_consensus_never_becomes_a_score():
    sofa = {"identity": "MATCHED", "status": "POSTPONED"}
    fotmob = {"identity": "MATCHED", "status": "CANCELLED"}
    result = shadow.adjudicate(sofa, fotmob)
    assert result["decision"] == "CONSENSUS_NON_PLAYED"
    assert "score_90m_candidate" not in result


def test_shadow_contract_explicitly_forbids_formal_write(monkeypatch, tmp_path):
    monkeypatch.setattr(shadow, "TRUST_PATH", tmp_path / "trust.json")
    (tmp_path / "trust.json").write_text(json.dumps({"history": []}), encoding="utf-8")
    monkeypatch.setattr(shadow, "_request_text", lambda _url: "key_wikidata,name,key_sofascore,key_fotmob\n")
    report = shadow.run_shadow()
    assert report["formal_write_authorized"] is False
    assert report["target_count"] == 0
