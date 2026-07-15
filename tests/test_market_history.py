import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_history import load_history, rebuild_history  # noqa: E402


class MarketHistoryTests(unittest.TestCase):
    def test_rebuild_deduplicates_identical_market_snapshots(self):
        deep = {
            "shuju_id": 97,
            "fetched_at": "2026-07-14 00:01:00",
            "ouzhi": {"bookmakers": [{"cid": 1055, "spf_current": {"home": 2, "draw": 3, "away": 4}}]},
            "yazhi": {"companies": []},
            "daxiao": {"companies": []},
            "touzhu": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fetch_root = root / "fetch"
            for run in ("a", "b"):
                path = fetch_root / run / f"x_500_deep_2026-07-14_97.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(deep), encoding="utf-8")
            output = rebuild_history(97, fetch_root, root / "history")
            self.assertEqual(len(load_history(output)), 1)


if __name__ == "__main__":
    unittest.main()
