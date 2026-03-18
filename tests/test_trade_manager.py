import unittest
from datetime import datetime

import pandas as pd

from src.data.trade_manager import (
    build_trade_context,
    derive_position_book,
    get_recent_trades,
    list_traded_symbols,
    summarize_recent_trades,
)


class TradeManagerTest(unittest.TestCase):
    def test_recent_trade_summary_and_context(self):
        trade_log = pd.DataFrame(
            [
                {
                    "timestamp": "2026-03-18 09:35:00",
                    "symbol": "600001",
                    "name": "测试股A",
                    "side": "buy",
                    "quantity": 100,
                    "price": 10.2,
                    "amount": 1020,
                    "note": "开盘加仓",
                },
                {
                    "timestamp": "2026-03-15 14:20:00",
                    "symbol": "600002",
                    "name": "测试股B",
                    "side": "sell",
                    "quantity": 200,
                    "price": 9.8,
                    "amount": 1960,
                    "note": "减仓",
                },
            ]
        )

        recent = get_recent_trades(trade_log, now=datetime(2026, 3, 18, 10, 0, 0), lookback_days=5)
        summary = summarize_recent_trades(recent)
        context = build_trade_context(recent)

        self.assertEqual(len(summary), 2)
        self.assertEqual(context["600001"]["last_side"], "buy")
        self.assertEqual(context["600002"]["last_side"], "sell")

    def test_derive_position_book_rebuilds_holdings_and_cost(self):
        trade_log = pd.DataFrame(
            [
                {
                    "timestamp": "2026-03-18 09:35:00",
                    "symbol": "600001",
                    "name": "测试股A",
                    "side": "buy",
                    "quantity": 100,
                    "price": 10.0,
                    "amount": 1000,
                    "note": "",
                },
                {
                    "timestamp": "2026-03-18 10:35:00",
                    "symbol": "600001",
                    "name": "测试股A",
                    "side": "buy",
                    "quantity": 100,
                    "price": 12.0,
                    "amount": 1200,
                    "note": "",
                },
                {
                    "timestamp": "2026-03-18 14:35:00",
                    "symbol": "600001",
                    "name": "测试股A",
                    "side": "sell",
                    "quantity": 50,
                    "price": 13.0,
                    "amount": 650,
                    "note": "",
                },
            ]
        )

        book = derive_position_book(trade_log)
        row = book.iloc[0].to_dict()
        self.assertEqual(row["symbol"], "600001")
        self.assertEqual(int(row["holdings"]), 150)
        self.assertAlmostEqual(float(row["buy_price"]), 11.0, places=2)
        self.assertEqual(list_traded_symbols(trade_log), ["600001"])


if __name__ == "__main__":
    unittest.main()
