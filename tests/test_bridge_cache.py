import json
import tempfile
import unittest
from pathlib import Path

from scripts import bridge


class BridgeCacheTest(unittest.TestCase):
    def test_load_cache_restores_persisted_live_quotes(self):
        old_cache = bridge.CACHE
        old_cache_file = bridge.CACHE_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "cache_dump.json"
                cache_file.write_text(json.dumps({
                    "live_quotes": {
                        "600726": {"最新价": 9.5},
                        "_updated": "2026-06-01T15:00:00+08:00",
                    },
                    "live_index": {"上证指数涨幅": "-0.27%"},
                }, ensure_ascii=False), encoding="utf-8")

                bridge.CACHE = {}
                bridge.CACHE_FILE = cache_file

                bridge._load_cache()

                self.assertIn("live_quotes", bridge.CACHE)
                self.assertEqual(bridge.CACHE["live_quotes"]["600726"]["最新价"], 9.5)
                self.assertIn("live_index", bridge.CACHE)
        finally:
            bridge.CACHE = old_cache
            bridge.CACHE_FILE = old_cache_file


if __name__ == "__main__":
    unittest.main()
