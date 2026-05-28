import unittest

from scripts.ops.refresh_close_baseline import apply_close_baseline


class RefreshCloseBaselineTests(unittest.TestCase):

    def test_apply_close_baseline_overwrites_stale_market_and_sentiment(self):
        data = {
            "meta": {"date": "2026-05-28", "updated": "2026-05-28T13:35:53+08:00"},
            "market": {"上证指数": 4093.73, "上证涨幅": -1.25, "市场量能": 3.24},
            "sentiment": {"情绪值": 17.1, "情绪区间": "冰点"},
        }
        index_data = {
            "上证指数": 4098.64,
            "上证指数涨幅": "+0.12%",
            "上证指数振幅": "1.34%",
            "深证指数": 15861.89,
            "深证指数涨幅": "+0.80%",
            "深证指数振幅": "2.45%",
            "创业指数": 4125.07,
            "创业指数涨幅": "+1.96%",
            "创业指数振幅": "4.05%",
            "成交额": "2.97万亿",
            "上涨家数": 2800,
            "下跌家数": 2335,
        }
        sentiment_data = {
            "涨停家数": 100,
            "跌停家数": 8,
            "封板率": 1.0,
            "炸板率": 0.0,
            "昨日涨停收益": 0.84,
            "连板收益": 4.01,
            "炸板收益": 2.26,
            "晋级率": 0.1915,
            "最高板": 4,
        }

        out = apply_close_baseline(data, index_data, sentiment_data, "2026-05-28T18:00:00+08:00")

        self.assertEqual(out["market"]["上证指数"], 4098.64)
        self.assertEqual(out["market"]["上证涨幅"], 0.12)
        self.assertEqual(out["market"]["上证振幅"], 1.34)
        self.assertEqual(out["market"]["深证指数"], 15861.89)
        self.assertEqual(out["market"]["深证涨幅"], 0.8)
        self.assertEqual(out["market"]["深证振幅"], 2.45)
        self.assertEqual(out["market"]["创业指数"], 4125.07)
        self.assertEqual(out["market"]["创业涨幅"], 1.96)
        self.assertEqual(out["market"]["创业振幅"], 4.05)
        self.assertEqual(out["market"]["市场量能"], 2.97)
        self.assertEqual(out["market"]["涨跌比"], "2800/2335")
        self.assertEqual(out["market"]["涨停家数"], 100)
        self.assertEqual(out["market"]["跌停家数"], 8)
        self.assertEqual(out["market"]["封板率"], 100.0)
        self.assertEqual(out["market"]["炸板率"], 0.0)
        self.assertEqual(out["sentiment"]["情绪值"], 54.5)
        self.assertEqual(out["sentiment"]["情绪区间"], "主升")
        self.assertEqual(out["sentiment"]["晋级率"], 19.15)
        self.assertEqual(out["meta"]["close_source"], "scripts/ops/refresh_close_baseline.py")


if __name__ == "__main__":
    unittest.main()
