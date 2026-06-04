"""test_market_data_collector.py — market data collector behavior tests."""
import unittest
from unittest.mock import patch

from scripts.collectors import market_data


class MarketDataCollectorTests(unittest.TestCase):
    def setUp(self):
        market_data.CACHE.clear()

    def test_poll_sector_inflow_force_bypasses_trading_time_gate(self):
        payload = {
            "top": [
                {"name": "电力", "change_pct": 3.09, "net_inflow_yi": 76.35},
            ]
        }
        with patch("scripts.collectors.market_data.is_trading_time", return_value=False), \
             patch("scripts.collectors.market_data._pipeline_fetch", return_value=payload) as fetch:
            market_data.poll_sector_inflow(force=True)

        fetch.assert_called_once_with("sector_inflow", top_n=20)
        self.assertEqual(market_data.CACHE["sector_inflow"]["data"][0]["name"], "电力")
        self.assertIn("_updated", market_data.CACHE["sector_inflow"])

    def test_poll_sector_inflow_respects_trading_time_gate_without_force(self):
        with patch("scripts.collectors.market_data.is_trading_time", return_value=False), \
             patch("scripts.collectors.market_data._pipeline_fetch") as fetch:
            market_data.poll_sector_inflow()

        fetch.assert_not_called()
        self.assertNotIn("sector_inflow", market_data.CACHE)


if __name__ == "__main__":
    unittest.main()
