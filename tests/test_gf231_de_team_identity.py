from scripts.team_identity import _registry, team_similarity
from scripts.nowscore_markets import _verified

FIXTURES=[
    ({"home":"埃沃斯堡","away":"奥格斯堡","kickoff":"2026-10-17 21:30"},
     {"home_team":"埃弗斯堡(主)","away_team":"奥格斯堡","kickoff_local":"2026/10/17 21:30"}),
    ({"home":"不来梅","away":"帕德博恩","kickoff":"2026-10-17 21:30"},
     {"home_team":"云达不莱梅(主)","away_team":"帕德博恩","kickoff_local":"2026/10/17 21:30"})
]
def test_exact_alias_provenance_and_no_duplicate_token_collisions():
    canonical,_=_registry()
    assert canonical["埃沃斯堡"]=="埃弗斯堡"
    assert canonical["不来梅"]=="云达不莱梅"
    assert canonical["werderbremen"]=="云达不莱梅"
    for a,b in [("埃沃斯堡","埃弗斯堡"),("不来梅","云达不莱梅")]:
        assert team_similarity(a,b)[0]==1.0

def test_same_nowscore_provider_fixture_identity_accepts_only_exact_alias():
    for target,page in FIXTURES:
        assert _verified(target,page,maximum_minutes=180)==(True,[])
        assert "HOME_TEAM_MISMATCH" in _verified(target,{**page,"home_team":"拜仁慕尼黑"},maximum_minutes=180)[1]
        assert "AWAY_TEAM_MISMATCH" in _verified(target,{**page,"away_team":"美因茨"},maximum_minutes=180)[1]
        assert "KICKOFF_MISMATCH" in _verified(target,{**page,"kickoff_local":"2026-10-18 01:00"},maximum_minutes=180)[1]

def test_mixed_script_second_team_and_reserves_fail_closed():
    for left,right in [("不来梅","不来梅SV"),("不来梅","不来梅U19"),
                       ("云达不莱梅","云达不莱梅U21"),("埃沃斯堡","埃弗斯堡II")]:
        assert team_similarity(left,right)[0] < 0.75,(left,right,team_similarity(left,right))
