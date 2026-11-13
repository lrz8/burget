import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.data.trade_manager import (
    build_trade_context,
    derive_position_book,
    get_recent_trades,
    list_traded_symbols,
    record_trade,
    load_trade_log,
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

    def test_sell_from_opening_position_keeps_remaining_shares(self):
        opening = pd.DataFrame([{"symbol": "600001", "name": "测试股", "holdings": 1000, "buy_price": 10}])
        trades = pd.DataFrame([{
            "timestamp": "2026-03-18 10:00:00", "symbol": "600001",
            "side": "sell", "quantity": 100, "price": 11,
        }])
        book = derive_position_book(trades, opening_positions=opening)
        self.assertEqual(book.iloc[0]["holdings"], 900)
        self.assertEqual(book.iloc[0]["buy_price"], 10)

    def test_incomplete_ledger_rejects_a_sell_instead_of_silently_closing(self):
        trades = pd.DataFrame([{
            "timestamp": "2026-03-18 10:00:00", "symbol": "600001",
            "side": "sell", "quantity": 100, "price": 11,
        }])
        with self.assertRaisesRegex(ValueError, "期初持仓"):
            derive_position_book(trades)

    def test_future_trade_is_excluded_from_positions_and_recent_context(self):
        trades = pd.DataFrame([
            {"timestamp": "2026-03-18 09:35:00", "symbol": "600001", "side": "buy", "quantity": 100, "price": 10},
            {"timestamp": "2026-03-19 09:35:00", "symbol": "600001", "side": "buy", "quantity": 100, "price": 12},
        ])
        now = datetime(2026, 3, 18, 10)
        self.assertEqual(derive_position_book(trades, as_of=now).iloc[0]["holdings"], 100)
        self.assertEqual(len(get_recent_trades(trades, now=now)), 1)

    def test_record_validation_and_leading_zero_csv_round_trip(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "trades.csv")
            record_trade("000001", "buy", 100, 10, path=path)
            self.assertEqual(load_trade_log(path).iloc[0]["symbol"], "000001")
            for quantity, price in [(0, 10), (1.5, 10), (100, 0), (100, float("nan"))]:
                with self.subTest(quantity=quantity, price=price), self.assertRaises(ValueError):
                    record_trade("000001", "buy", quantity, price, path=path)
            self.assertEqual(len(load_trade_log(path)), 1)


if __name__ == "__main__":
    unittest.main()
