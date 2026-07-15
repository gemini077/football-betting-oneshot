import unittest

from scripts.fetch_football_data import _match_filter


class MatchFilterTests(unittest.TestCase):
    def setUp(self):
        self.matches = [
            {
                "matchId": "2040514",
                "matchNum": "周三202",
                "homeTeam": "苏捷斯卡",
                "awayTeam": "阿拉木图",
                "league": "欧冠",
            },
            {
                "matchId": "2040513",
                "matchNum": "周三201",
                "homeTeam": "比森",
                "awayTeam": "克拉克斯",
                "league": "欧冠",
            },
        ]

    def test_filters_exact_pair_with_vs_separator(self):
        rows = _match_filter(self.matches, "苏捷斯卡 vs 阿拉木图")
        self.assertEqual(["2040514"], [row["matchId"] for row in rows])

    def test_filters_pair_without_spaces_and_case_insensitively(self):
        rows = _match_filter(self.matches, "比森VS克拉克斯")
        self.assertEqual(["2040513"], [row["matchId"] for row in rows])

    def test_preserves_single_team_and_match_id_search(self):
        self.assertEqual("2040514", _match_filter(self.matches, "苏捷斯卡")[0]["matchId"])
        self.assertEqual("2040513", _match_filter(self.matches, "2040513")[0]["matchId"])


if __name__ == "__main__":
    unittest.main()
