import json
from pathlib import Path
import pytest
from team_identity import _registry, normalize_team_name, team_similarity

@pytest.mark.parametrize(("left", "right"), [
 ("\u66fc\u57ce", "\u66fc\u5f7b\u65af\u7279\u57ce"),
 ("\u5df4\u9ece\u5723\u66fc", "\u5df4\u9ece\u5723\u65e5\u8033\u66fc"),
])
def test_verified_alias_pairs_score_one(left,right):
 assert team_similarity(left,right)[0] == 1.0

@pytest.mark.parametrize(("raw", "clean"), [
 ("\u66fc\u5f7b\u65af\u7279\u57ce(\u4e3b)", "\u66fc\u5f7b\u65af\u7279\u57ce"),
 ("\u5df4\u9ece\u5723\u65e5\u8033\u66fc(\u4e3b)", "\u5df4\u9ece\u5723\u65e5\u8033\u66fc"),
])
def test_display_home_marker_cleanup(raw,clean):
 assert normalize_team_name(raw) == normalize_team_name(clean)

def test_existing_getafe_alias_remains_available():
 canonical,_=_registry()
 assert canonical["getafe"] == "getafecf"
 assert team_similarity("Getafe","Getafe CF")[0] == 1.0

def test_manchester_united_is_not_manchester_city():
 assert team_similarity("\u66fc\u57ce","\u66fc\u8054")[0] < .75

def test_psg_does_not_match_other_paris_club():
 assert team_similarity("\u5df4\u9ece\u5723\u66fc","\u5df4\u9eceFC")[0] < .75

def test_new_aliases_have_no_cross_group_collision():
 rows=json.loads((Path(__file__).resolve().parents[1]/"data/team_aliases.json").read_text(encoding="utf-8"))["teams"]
 for canonical,aliases in (("\u66fc\u5f7b\u65af\u7279\u57ce",{"\u66fc\u57ce","\u66fc\u5f7b\u65af\u7279\u57ce"}),("\u5df4\u9ece\u5723\u65e5\u8033\u66fc",{"\u5df4\u9ece\u5723\u66fc","\u5df4\u9ece\u5723\u65e5\u8033\u66fc"})):
  key=normalize_team_name(canonical)
  for alias in aliases:
   matches=[r for r in rows if normalize_team_name(alias)==normalize_team_name(r["canonical"]) or normalize_team_name(alias) in {normalize_team_name(a) for a in r.get("aliases",[])}]
   assert len(matches)==1 and normalize_team_name(matches[0]["canonical"])==key

def test_reversed_orientation_components_do_not_match():
 assert team_similarity("\u66fc\u57ce","\u4f0a\u666e\u65af\u7ef4\u5947")[0] < .75
 assert team_similarity("\u4f0a\u666e\u65af","\u66fc\u5f7b\u65af\u7279\u57ce")[0] < .75

def test_registry_maps_new_aliases_to_expected_canonicals():
 canonical,_=_registry()
 assert canonical["\u66fc\u57ce"] == "\u66fc\u5f7b\u65af\u7279\u57ce"
 assert canonical["\u5df4\u9ece\u5723\u66fc"] == "\u5df4\u9ece\u5723\u65e5\u8033\u66fc"


def test_paris_fc_does_not_match_psg_alias():
 assert team_similarity("\u5df4\u9eceFC","\u5df4\u9ece\u5723\u66fc")[0] < .75

def test_paris_fc_does_not_match_psg_canonical():
 assert team_similarity("\u5df4\u9eceFC","\u5df4\u9ece\u5723\u65e5\u8033\u66fc")[0] < .75

def test_latin_paris_fc_remains_distinct_from_psg():
 assert team_similarity("Paris FC","\u5df4\u9ece\u5723\u65e5\u8033\u66fc")[0] < .75

@pytest.mark.parametrize(("left","right"), [
 ("Getafe","Getafe CF"),
 ("\u66fc\u57ce","\u66fc\u5f7b\u65af\u7279\u57ce"),
 ("\u5df4\u9ece\u5723\u66fc","\u5df4\u9ece\u5723\u65e5\u8033\u66fc"),
])
def test_existing_and_new_verified_identities_still_match(left,right):
 assert team_similarity(left,right)[0] == 1.0
