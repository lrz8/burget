import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from src.fetcher.market_data import _cached_stock_history, _get_tx_symbol, get_stock_data, get_stock_history_kline


class MarketDataTest(unittest.TestCase):
    def test_quote_and_chart_share_bounded_history_request(self):
        frame = pd.DataFrame([
            {"date": "2026-03-17", "open": 1.01, "close": 1.01, "high": 1.02, "low": 1, "amount": 100},
            {"date": "2026-03-18", "open": 1.01, "close": 1.015, "high": 1.02, "low": 1, "amount": 200},
        ])
        portfolio = pd.DataFrame([{"symbol": "159915", "holdings": 100, "buy_price": 1}])
        _cached_stock_history.cache_clear()
        self.addCleanup(_cached_stock_history.cache_clear)
        with patch("src.fetcher.market_data.market_now", return_value=datetime(2026, 3, 18, 15, 10)), \
             patch("src.fetcher.market_data.time.monotonic", return_value=600), \
             patch("src.fetcher.market_data.retry_akshare_call", return_value=frame) as fetch, \
             patch("src.fetcher.market_data.get_symbol_name", return_value="测试ETF"):
            quote = get_stock_data(portfolio)["159915"]
            chart = get_stock_history_kline("159915")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.kwargs["start_date"], "20251218")
        self.assertEqual(fetch.call_args.kwargs["timeout"], 10)
        self.assertEqual(quote["行情日期"], "2026-03-18")
        self.assertEqual(quote["最新价"], 1.015)
        self.assertIn("成交量(手)", quote)
        self.assertNotIn("成交额(元)", quote)
        self.assertEqual(len(chart), 2)

    def test_new_beijing_code_is_not_routed_to_shanghai(self):
        self.assertEqual(_get_tx_symbol("920001"), "bj920001")


if __name__ == "__main__":
    unittest.main()
