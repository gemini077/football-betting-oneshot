import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from core_match_selector import classify, select
from nowscore_markets import resolve_match
from team_identity import team_similarity


class ProviderIdentityTests(unittest.TestCase):
    def test_confirmed_cross_provider_aliases_are_exact(self):
        pairs = [
            ("瓦萨", "VPS瓦萨"), ("AIK索尔纳", "索尔纳"),
            ("AC奥卢", "奥卢"), ("赫尔辛基火花", "格尼斯坦"),
            ("桑纳菲尤尔", "桑德菲杰"), ("蔚山现代", "蔚山HD"),
        ]
        for left, right in pairs:
            score, basis = team_similarity(left, right)
            self.assertEqual(1.0, score, (left, right, basis))

    def test_pair_and_kickoff_resolve_unique_match(self):
        schedule = [
            {"nowscore_id": 2913665, "home_team": "奥卢", "home_team_en": "AC Oulu",
             "away_team": "格尼斯坦", "away_team_en": "Gnistan Helsinki",
             "kickoff_local": "2026-07-18T22:00+08:00"},
            {"nowscore_id": 999, "home_team": "奥卢", "home_team_en": "AC Oulu",
             "away_team": "瓦萨", "away_team_en": "VPS",
             "kickoff_local": "2026-07-18T22:00+08:00"},
        ]
        result = resolve_match("AC奥卢", "赫尔辛基火花", "2026-07-18T22:00:00+08:00", schedule)
        self.assertEqual("EXACT_MATCH", result["status"])
        self.assertEqual(2913665, result["nowscore_id"])


class CoreSelectorTests(unittest.TestCase):
    def row(self, match_id, league, kickoff, **extra):
        return {"id": match_id, "league": league, "kickoff": kickoff, "home": "A", "away": "B",
                "business_date": "2026-07-18", "spf": {"home": 2.0, "draw": 3.2, "away": 3.5}, **extra}

    def test_excludes_qualifiers_and_caps_same_kickoff(self):
        self.assertFalse(classify(self.row("q", "世界杯预选赛", "2026-07-18 20:00"))["eligible"])
        rows = [self.row(str(index), "世界杯", "2026-07-18 20:00", nowscore_id=100 + index) for index in range(5)]
        chosen = select(rows, datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(2, len(chosen))

    def test_does_not_reanalyze_existing_report(self):
        rows = [self.row("1", "英格兰超级联赛", "2026-07-18 20:00", nowscore_id=1, report_url="report.html")]
        self.assertEqual([], select(rows, datetime(2026, 7, 18, 12, tzinfo=ZoneInfo("Asia/Shanghai"))))


if __name__ == "__main__":
    unittest.main()
