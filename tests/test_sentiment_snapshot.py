import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts import bridge
from scripts.collectors import sentiment_snapshot


class SentimentSnapshotTests(unittest.TestCase):
    def setUp(self):
        sentiment_snapshot.CACHE.clear()

    def tearDown(self):
        sentiment_snapshot.CACHE.clear()

    def test_snapshot_prefers_pytdx_core_counts_over_iwencai_counts(self):
        sentiment_snapshot.CACHE.update({
            "iwencai": {
                "涨停家数": 999,
                "跌停家数": 888,
                "封板率": 0.8,
            },
            "breadth": {
                "涨停": 51,
                "跌停": 3,
                "_total": 5200,
                "_source": "pytdx",
            },
            "live_index": {
                "上涨家数": 3100,
                "下跌家数": 1900,
            },
        })

        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 26, 10, 0, 5)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sentiment_auto.json"
            with patch.object(sentiment_snapshot, "OUTPUT", output), \
                 patch.object(sentiment_snapshot, "datetime", FixedDateTime):
                sentiment_snapshot.take_sentiment_snapshot(force=True)

            rows = json.loads(output.read_text(encoding="utf-8"))["2026-06-26"]

        self.assertEqual(51, rows[-1]["涨停家数"])
        self.assertEqual(3, rows[-1]["跌停家数"])
        self.assertEqual("pytdx_breadth", rows[-1]["核心行情源"])

    def test_auction_snapshot_uses_auction_node_name(self):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 26, 9, 25, 30)

        with patch.object(sentiment_snapshot, "datetime", FixedDateTime):
            self.assertEqual("竞价", sentiment_snapshot._current_node())

    def test_history_payload_returns_only_requested_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "sentiment_auto.json").write_text(
                json.dumps({
                    "2026-06-25": [{"time": "2026-06-25T15:00:00+08:00"}],
                    "2026-06-26": [{"time": "2026-06-26T10:00:00+08:00"}],
                }),
                encoding="utf-8",
            )

            with patch.object(bridge, "ROOT", root):
                payload = bridge._sentiment_history_payload("2026-06-26")

        self.assertEqual("2026-06-26", payload["date"])
        self.assertEqual(1, len(payload["rows"]))
        self.assertEqual("sentiment_auto", payload["source"])


if __name__ == "__main__":
    unittest.main()
