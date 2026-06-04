"""W21 涨停历史写入规则回归测试。"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.collectors import quotes


class ZtHistorySnapshotTest(unittest.TestCase):
    def setUp(self):
        self._orig_file = quotes.__file__
        self._orig_cache = quotes.CACHE
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "scripts" / "collectors").mkdir(parents=True)
        (self.root / "data").mkdir()
        quotes.__file__ = str(self.root / "scripts" / "collectors" / "quotes.py")
        quotes.CACHE = {"hot_list": {}}

    def tearDown(self):
        quotes.__file__ = self._orig_file
        quotes.CACHE = self._orig_cache
        self.tmp.cleanup()

    def _history_path(self):
        return self.root / "data" / "zt_history.json"

    def test_empty_zt_stocks_do_not_save_hot_list_as_history(self):
        self._history_path().write_text(json.dumps({
            "2026-05-27": [{"code": "000001", "name": "平安银行"}],
            "2026-05-28": [{"code": "000002", "name": "万科A"}],
        }), encoding="utf-8")

        quotes._save_zt_snapshot({
            "stocks": [{"code": "301373", "name": "凌玮科技", "zhangfu": 0.0}],
            "zt_stocks": [],
        })

        history = json.loads(self._history_path().read_text(encoding="utf-8"))
        self.assertEqual(set(history.keys()), {"2026-05-27", "2026-05-28"})
        self.assertEqual(list(quotes.CACHE["hot_list"]["zt_history"].keys()),
                         ["2026-05-28", "2026-05-27"])

    def test_confirmed_zt_stocks_are_saved_and_injected_desc(self):
        self._history_path().write_text(json.dumps({
            "2026-05-27": [{"code": "000001", "name": "平安银行"}],
        }), encoding="utf-8")

        quotes._save_zt_snapshot({
            "zt_stocks": [
                {"code": "000539", "name": "粤电力A", "zhangfu": 10.03,
                 "huanshou": 5.2, "chengjiaoe": 82000, "reason": "电力"},
                {"code": "000000", "name": "ST测试", "zhangfu": 5.0},
            ],
            "stocks": [{"code": "301373", "name": "凌玮科技", "zhangfu": 0.0}],
        })

        history = json.loads(self._history_path().read_text(encoding="utf-8"))
        today = list(quotes.CACHE["hot_list"]["zt_history"].keys())[0]
        self.assertIn(today, history)
        self.assertEqual(history[today][0]["code"], "000539")
        self.assertEqual(len(history[today]), 1)
        self.assertEqual(list(quotes.CACHE["hot_list"]["zt_history"].keys())[0], today)


if __name__ == "__main__":
    unittest.main()
