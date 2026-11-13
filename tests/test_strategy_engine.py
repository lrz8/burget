import math
import unittest
from datetime import datetime

from src.analyzer.strategy_engine import _decide_action, analyze_market, analyze_positions


class StrategyEngineTest(unittest.TestCase):
    def quote(self, **overrides):
        return {
            "名称": "测试股", "类型": "股票", "最新价": 12.5, "持仓成本价": 10,
            "涨跌幅(%)": 1, "持仓市值(元)": 1250, "浮动盈亏(元)": 250,
            "盈亏比例(%)": 25, "行情日期": "2026-03-18", "数据周期": "daily", **overrides,
        }

    def test_market_flow_uses_only_main_net_amount(self):
        result = analyze_market(
            {"测试指数": {"涨跌幅(%)": 0.6}},
            {"主力净流入-净额": -10, "主力净流入-净占比": 1000, "超大单净流入-净额": 1000},
        )
        self.assertEqual(result["bias"], "震荡")
        self.assertAlmostEqual(result["score"], 0.1)

    def test_missing_flow_is_not_reported_as_neutral_flow(self):
        result = analyze_market({"测试指数": {"涨跌幅(%)": 0.6}}, {})
        self.assertFalse(result["fund_flow_available"])
        self.assertIn("资金流数据不足", result["summary"])

    def test_post_close_retains_existing_profit_and_loss_thresholds(self):
        result = analyze_positions(
            {"600001": self.quote(), "600002": self.quote(**{"盈亏比例(%)": -9})},
            {"bias": "震荡"}, session_type="post_close", now=datetime(2026, 3, 18, 15, 10),
        )
        self.assertEqual({item["symbol"]: item["action"] for item in result},
                         {"600001": "清仓止盈", "600002": "割肉止损"})
        self.assertTrue(all("下一交易日预案" in " ".join(item["reasons"]) for item in result))

    def test_recent_buy_blocks_addition_but_expired_cooldown_does_not(self):
        for timestamp, expected in [
            ("2026-03-18 15:00:00", "持仓观望"),
            ("2026-03-18 14:00:00", "逢低加仓"),
        ]:
            with self.subTest(timestamp=timestamp):
                action, _, _ = _decide_action(
                    0, -2, "偏强", 1000, "post_close",
                    {"last_side": "buy", "last_timestamp": timestamp},
                    now=datetime(2026, 3, 18, 15, 10),
                )
                self.assertEqual(action, expected)

    def test_daily_quotes_do_not_generate_intraday_trade_actions(self):
        result = analyze_positions(
            {"600001": self.quote()}, {"bias": "偏强"},
            session_type="intraday", now=datetime(2026, 3, 18, 10),
        )[0]
        self.assertEqual(result["action"], "持仓观望")
        self.assertIn("日线", " ".join(result["reasons"]))

    def test_stale_future_and_undated_quotes_are_observation_only(self):
        for quote_date in ["2026-03-17", "2026-03-19", ""]:
            with self.subTest(quote_date=quote_date):
                result = analyze_positions(
                    {"600001": self.quote(**{"行情日期": quote_date})}, {"bias": "偏强"},
                    session_type="post_close", now=datetime(2026, 3, 18, 15, 10),
                )[0]
                self.assertEqual(result["action"], "持仓观望")
                self.assertFalse(result["data_fresh"])

    def test_non_finite_quote_does_not_produce_a_trade_action(self):
        result = analyze_positions(
            {"600001": self.quote(**{"最新价": math.nan})}, {"bias": "偏强"},
        )[0]
        self.assertEqual(result["action"], "持仓观望")
        self.assertFalse(result["data_available"])

    def test_daily_rebound_is_not_a_timing_signal(self):
        action, reasons, _ = _decide_action(-3, 2, "偏强", 1000, "post_close", {})
        self.assertEqual(action, "持仓观望")
        self.assertIn("不据此建议做 T", " ".join(reasons))


if __name__ == "__main__":
    unittest.main()
