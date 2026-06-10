"""Regression tests for live quote collectors."""
import unittest
from unittest.mock import patch

from scripts.collectors import iwencai_poll, quotes


class QuotesCollectorTests(unittest.TestCase):
    def setUp(self):
        quotes.CACHE.clear()
        iwencai_poll.CACHE.clear()

    def tearDown(self):
        quotes.CACHE.clear()
        iwencai_poll.CACHE.clear()

    def test_collect_index_drops_stale_turnover_compare_when_source_omits_it(self):
        quotes.CACHE["live_index"] = {
            "成交额": "2.89万亿",
            "上证指数成交额": "1.31万亿",
            "深证指数成交额": "1.58万亿",
            "上证昨成交额": "13150.84亿",
            "上证成交额差": "-13150.84亿",
            "上证成交额差百分比": "-100.0%",
            "深证昨成交额": "15788.96亿",
            "深证成交额差": "-15788.96亿",
            "深证成交额差百分比": "-100.0%",
        }
        fresh_index = {
            "成交额": "1.64万亿",
            "上证指数成交额": "7458.48亿",
            "深证指数成交额": "8916.20亿",
        }

        with patch("scripts.collectors.quotes._fetch_market_data", return_value=fresh_index):
            quotes.collect_index(force=True)

        live_index = quotes.CACHE["live_index"]
        self.assertEqual(live_index["成交额"], "1.64万亿")
        self.assertNotIn("上证成交额差", live_index)
        self.assertNotIn("上证成交额差百分比", live_index)
        self.assertNotIn("深证成交额差", live_index)
        self.assertNotIn("深证成交额差百分比", live_index)

    def test_iwencai_limit_counts_fall_back_when_limit_up_query_returns_zero(self):
        def fake_query(query, limit=100):
            if query == "今日跌停 非st":
                return {"datas": [{} for _ in range(12)]}
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={"涨停家数": 43, "跌停家数": 12}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        self.assertEqual(iwencai_poll.CACHE["iwencai"]["涨停家数"], 43)
        self.assertEqual(iwencai_poll.CACHE["iwencai"]["跌停家数"], 12)
        self.assertEqual(iwencai_poll.CACHE["iwencai"]["_limit_source"], "eastmoney_zt_pool")

    def test_collect_limit_counts_writes_independent_cache_and_hot_metadata(self):
        quotes.CACHE["hot_list"] = {"zt_count": 0, "zt_stocks": []}

        with patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={"涨停家数": 43, "跌停家数": 12}):
            quotes.collect_limit_counts(force=True)

        limit_counts = quotes.CACHE["limit_counts"]
        self.assertEqual(limit_counts["涨停家数"], 43)
        self.assertEqual(limit_counts["跌停家数"], 12)
        self.assertEqual(limit_counts["_source"], "eastmoney_zt_pool")
        self.assertIn("_updated", limit_counts)
        self.assertEqual(quotes.CACHE["hot_list"]["zt_count"], 43)
        self.assertEqual(quotes.CACHE["hot_list"]["dt_count"], 12)
        self.assertEqual(quotes.CACHE["hot_list"]["_limit_source"], "eastmoney_zt_pool")

    def test_iwencai_poll_writes_realtime_emotion_from_up_down_counts(self):
        def fake_query(query, limit=100):
            if query == "今日上涨 非st":
                return {"datas": [{} for _ in range(38)]}
            if query == "今日下跌 非st":
                return {"datas": [{} for _ in range(62)]}
            if query == "今日涨停 非st":
                return {"datas": [{} for _ in range(12)]}
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertEqual(iw["情绪值"], 38.0)
        self.assertEqual(iw["_emotion_source"], "iwencai_up_down")

    def test_iwencai_poll_does_not_write_zero_sided_emotion(self):
        def fake_query(query, limit=100):
            if query == "今日上涨 非st":
                return {"datas": []}
            if query == "今日下跌 非st":
                return {"datas": [{} for _ in range(2907)]}
            if query == "今日涨停 非st":
                return {"datas": [{} for _ in range(32)]}
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertNotIn("情绪值", iw)
        self.assertNotIn("_emotion_source", iw)

    def test_iwencai_partial_poll_preserves_same_day_realtime_return_fields(self):
        iwencai_poll.CACHE["iwencai"] = {
            "昨日涨停收益": 2.4,
            "涨停溢价率": 61.5,
            "赚钱效应": "好",
            "连板收益": 3.6,
            "情绪值": 38.0,
            "_emotion_source": "iwencai_up_down",
            "_emotion_counts": {"up": 1900, "down": 3100},
            "_updated": "2026-06-09T14:50:00+08:00",
        }

        def fake_query(query, limit=100):
            if query == "昨日炸板 今日涨跌幅 非st":
                return {"datas": [{"涨跌幅": "-0.18%"}]}
            if query == "今日涨停 非st":
                return {"datas": [{} for _ in range(12)]}
            if query == "今日跌停 非st":
                return {"datas": [{} for _ in range(3)]}
            return {"datas": []}

        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 9, 15, 5, 41)

        from datetime import datetime
        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}), \
             patch("scripts.collectors.iwencai_poll.datetime", FixedDateTime):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertEqual(iw["昨日涨停收益"], 2.4)
        self.assertEqual(iw["涨停溢价率"], 61.5)
        self.assertEqual(iw["赚钱效应"], "好")
        self.assertEqual(iw["连板收益"], 3.6)
        self.assertEqual(iw["情绪值"], 38.0)
        self.assertEqual(iw["炸板收益"], -0.18)
        self.assertIn("昨日涨停收益", iw["_preserved_fields"])
        self.assertIn("连板收益", iw["_preserved_fields"])

    def test_iwencai_lianban_profit_uses_semantic_fallback_when_primary_empty(self):
        def fake_query(query, limit=100):
            if query == "昨日连板 今日涨跌幅 非st":
                return {"datas": [
                    {"涨跌幅": "-3.32%"},
                    {"涨跌幅": "2.52%"},
                    {"涨跌幅": "-0.40%"},
                ]}
            if query == "今日涨停 非st":
                return {"datas": [{} for _ in range(12)]}
            if query == "今日跌停 非st":
                return {"datas": [{} for _ in range(3)]}
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertEqual(iw["连板收益"], -0.4)
        self.assertEqual(iw["_lianban_profit_query"], "昨日连板 今日涨跌幅 非st")

    def test_iwencai_empty_limit_sources_do_not_write_zero_zero(self):
        def fake_query(query, limit=100):
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertNotIn("涨停家数", iw)
        self.assertNotIn("跌停家数", iw)

    def test_iwencai_empty_limit_sources_preserve_previous_valid_counts(self):
        iwencai_poll.CACHE["iwencai"] = {
            "涨停家数": 73,
            "跌停家数": 11,
            "_limit_source": "eastmoney_zt_pool",
        }

        def fake_query(query, limit=100):
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertEqual(iw["涨停家数"], 73)
        self.assertEqual(iw["跌停家数"], 11)
        self.assertEqual(iw["_limit_source"], "eastmoney_zt_pool")

    def test_iwencai_empty_limit_sources_do_not_preserve_previous_zero_zero(self):
        iwencai_poll.CACHE["iwencai"] = {
            "涨停家数": 0,
            "跌停家数": 0,
        }

        def fake_query(query, limit=100):
            return {"datas": []}

        with patch("scripts.collectors.iwencai_poll._iwencai_query", side_effect=fake_query), \
             patch("scripts.collectors.iwencai_poll._eastmoney_limit_counts",
                   return_value={}):
            iwencai_poll.poll_iwencai_sentiment(force=True)

        iw = iwencai_poll.CACHE["iwencai"]
        self.assertNotIn("涨停家数", iw)
        self.assertNotIn("跌停家数", iw)

    def test_collect_yesterday_compare_uses_eastmoney_15m_when_pytdx_disabled(self):
        quotes.CACHE["live_index"] = {
            "上证指数成交额": "7803.40亿",
            "深证指数成交额": "9330.03亿",
        }
        rows = {
            "1.000001": [
                "2026-06-01 09:45,1,1,1,1,1,300000000000.00,0,0,0,0",
                "2026-06-01 10:00,1,1,1,1,1,300000000000.00,0,0,0,0",
                "2026-06-02 09:45,1,1,1,1,1,250000000000.00,0,0,0,0",
            ],
            "0.399001": [
                "2026-06-01 09:45,1,1,1,1,1,400000000000.00,0,0,0,0",
                "2026-06-01 10:00,1,1,1,1,1,450000000000.00,0,0,0,0",
                "2026-06-02 09:45,1,1,1,1,1,300000000000.00,0,0,0,0",
            ],
        }

        with patch("scripts.collectors.quotes._pytdx_disabled", return_value=True), \
             patch("scripts.collectors.quotes._eastmoney_15m_klines",
                   side_effect=lambda secid, now=None: rows[secid]), \
             patch("scripts.collectors.quotes._current_15m_cutoff",
                   return_value="10:00"):
            quotes.collect_yesterday_compare(force=True)

        live_index = quotes.CACHE["live_index"]
        self.assertEqual(live_index["上证昨成交额"], "2500.00亿")
        self.assertEqual(live_index["深证昨成交额"], "3000.00亿")
        self.assertEqual(live_index["上证成交额差"], "+5303.40亿")
        self.assertEqual(live_index["深证成交额差"], "+6330.03亿")

    def test_collect_yesterday_compare_falls_back_to_cached_previous_15m_rows(self):
        quotes.CACHE["live_index"] = {
            "上证指数成交额": "1500.00亿",
            "深证指数成交额": "2300.00亿",
        }
        quotes.CACHE["上证15min"] = [
            {"t": "09:45", "amount": 400 * 1e8},
            {"t": "10:00", "amount": 600 * 1e8},
            {"t": "累计", "amount": 1000 * 1e8, "_cum": True},
        ]
        quotes.CACHE["深证15min"] = [
            {"t": "09:45", "amount": 900 * 1e8},
            {"t": "10:00", "amount": 1100 * 1e8},
            {"t": "累计", "amount": 2000 * 1e8, "_cum": True},
        ]

        with patch("scripts.collectors.quotes._get_tdx_api", return_value=None), \
             patch("scripts.collectors.quotes._current_15m_cutoff", return_value="10:00"):
            quotes.collect_yesterday_compare(force=True)

        live_index = quotes.CACHE["live_index"]
        self.assertEqual(live_index["上证昨成交额"], "1000.00亿")
        self.assertEqual(live_index["深证昨成交额"], "2000.00亿")
        self.assertEqual(live_index["上证成交额差"], "+500.00亿")
        self.assertEqual(live_index["深证成交额差"], "+300.00亿")

    def test_cached_15m_compare_uses_yesterday_amt_when_rows_are_today(self):
        quotes.CACHE["live_index"] = {
            "上证指数成交额": "1500.00亿",
            "深证指数成交额": "2300.00亿",
        }
        quotes.CACHE["上证15min"] = [
            {"t": "09:45", "amount": 400 * 1e8, "yesterdayAmt": 500 * 1e8},
            {"t": "10:00", "amount": 600 * 1e8, "yesterdayAmt": 700 * 1e8},
            {"t": "累计", "amount": 1000 * 1e8, "cumYesterdayAmt": 1200 * 1e8, "_cum": True},
        ]
        quotes.CACHE["深证15min"] = [
            {"t": "09:45", "amount": 900 * 1e8, "yesterdayAmt": 1000 * 1e8},
            {"t": "10:00", "amount": 1100 * 1e8, "yesterdayAmt": 1200 * 1e8},
            {"t": "累计", "amount": 2000 * 1e8, "cumYesterdayAmt": 2200 * 1e8, "_cum": True},
        ]

        with patch("scripts.collectors.quotes._get_tdx_api", return_value=None), \
             patch("scripts.collectors.quotes._current_15m_cutoff", return_value="10:00"):
            quotes.collect_yesterday_compare(force=True)

        live_index = quotes.CACHE["live_index"]
        self.assertEqual(live_index["上证昨成交额"], "1200.00亿")
        self.assertEqual(live_index["深证昨成交额"], "2200.00亿")
        self.assertEqual(live_index["上证成交额差"], "+300.00亿")
        self.assertEqual(live_index["深证成交额差"], "+100.00亿")

    def test_collect_kline_15m_marks_today_date_when_rows_update(self):
        rows = {
            "上证15min": [{"t": "09:45", "chg": 0.1, "volRatio": 1.1}],
            "深证15min": [{"t": "09:45", "chg": -0.1, "volRatio": 0.9}],
            "创业15min": [{"t": "09:45", "chg": 0.2, "volRatio": 1.0}],
        }

        with patch("scripts.collectors.quotes._pipeline_fetch", return_value=rows), \
             patch("scripts.collectors.quotes.datetime") as fake_dt:
            fake_dt.now.return_value.strftime.return_value = "2026-06-03"
            fake_dt.now.return_value.strftime.side_effect = lambda fmt: (
                "2026-06-03" if fmt == "%Y-%m-%d" else "2026-06-03T09:45:00+08:00"
            )
            quotes.collect_kline_15m(force=True)

        self.assertEqual(quotes.CACHE["kline_15m_date"], "2026-06-03")
        self.assertEqual(quotes.CACHE["上证15min"], rows["上证15min"])

    def test_collect_kline_15m_falls_back_to_eastmoney_when_pipeline_empty(self):
        raw = {
            "1.000001": [
                "2026-06-02 09:45,1,1,1,1,1,100000000000.00,0,0.00,0,0",
                "2026-06-03 09:45,1,1,1,1,1,120000000000.00,0,0.33,0,0",
            ],
            "0.399001": [
                "2026-06-02 09:45,1,1,1,1,1,200000000000.00,0,0.00,0,0",
                "2026-06-03 09:45,1,1,1,1,1,180000000000.00,0,-0.12,0,0",
            ],
            "0.399006": [
                "2026-06-02 09:45,1,1,1,1,1,50000000000.00,0,0.00,0,0",
                "2026-06-03 09:45,1,1,1,1,1,55000000000.00,0,0.21,0,0",
            ],
        }

        with patch("scripts.collectors.quotes._pipeline_fetch", return_value={}), \
             patch("scripts.collectors.quotes._eastmoney_15m_klines",
                   side_effect=lambda secid, now=None: raw[secid]), \
             patch("scripts.collectors.quotes.datetime") as fake_dt:
            fake_dt.now.return_value.strftime.side_effect = lambda fmt: (
                "2026-06-03" if fmt == "%Y-%m-%d" else "2026-06-03T09:46:00+08:00"
            )
            quotes.collect_kline_15m(force=True)

        self.assertEqual(quotes.CACHE["kline_15m_date"], "2026-06-03")
        self.assertEqual(quotes.CACHE["上证15min"][0]["t"], "09:45")
        self.assertEqual(quotes.CACHE["上证15min"][0]["amount"], 120000000000.0)
        self.assertEqual(quotes.CACHE["上证15min"][0]["yesterdayAmt"], 100000000000.0)
        self.assertAlmostEqual(quotes.CACHE["上证15min"][0]["volRatio"], 1.2)


if __name__ == "__main__":
    unittest.main()
