from scripts.team_identity import team_similarity, _registry
from scripts.nowscore_markets import _verified


def test_atletico_alias_is_exact_and_registry_is_narrow():
    assert team_similarity("马竞", "马德里竞技")[0] == 1
    aliases, _ = _registry()
    assert aliases["马竞"] == "马德里竞技"
    assert aliases["马德里竞技"] == "马德里竞技"
    assert "马德里" not in aliases
    assert "竞技" not in aliases
    assert aliases.get("皇家马德里") != "马德里竞技"


def test_nowscore_confirmed_fixture_identity_accepts_only_matching_event():
    target = {"home": "西班牙人", "away": "马竞", "kickoff": "2026-10-17T20:00:00+08:00"}
    page = {"home_team": "西班牙人", "away_team": "马德里竞技", "kickoff_local": "2026-10-17 20:00"}
    assert _verified(target, page, maximum_minutes=180) == (True, [])

    assert "AWAY_TEAM_MISMATCH" in _verified(target, {**page, "away_team": "皇家马德里"})[1]
    assert "HOME_TEAM_MISMATCH" in _verified(target, {**page, "home_team": "巴塞罗那"})[1]
    assert "KICKOFF_MISMATCH" in _verified(target, {**page, "kickoff_local": "2026-10-17 23:01"})[1]
