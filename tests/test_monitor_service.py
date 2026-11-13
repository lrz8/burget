import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from src.service.monitor_service import MonitorService


class FakeAnalyzer:
    calls = 0

    def __init__(self, config):
        pass

    def generate_review(self, market_data, stock_data, fund_flow):
        FakeAnalyzer.calls += 1
        return "### 市场补充观察\n仅根据日线数据观察。\n\n### 持仓补充观察\n盘后条件预案。"


class MonitorServiceTest(unittest.TestCase):
    def setUp(self):
        self.config = {"monitor": {"position_source": "manual"}, "llm": {"api_key": "test-placeholder"}, "notifier": {}}
        self.config_patch = patch("src.service.monitor_service.load_config", return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.now = datetime(2026, 3, 18, 15, 10)
        self.portfolio = pd.DataFrame([
            {"symbol": "600001", "name": "测试股A", "holdings": 1000, "buy_price": 10},
            {"symbol": "600002", "name": "测试股B", "holdings": 200, "buy_price": 10},
        ])
        self.saved = []
        self.snapshots = []
        self.missing = set()
        self.quote_date = "2026-03-18"
        FakeAnalyzer.calls = 0
        self.loaded_limit = "unset"

    def quotes(self, portfolio):
        result = {}
        for row in portfolio.to_dict("records"):
            if row["symbol"] in self.missing:
                continue
            price = 12.5 if row["symbol"] == "600001" else 9.0
            result[row["symbol"]] = {
                "名称": row["name"], "类型": "股票", "最新价": price,
                "持仓成本价": row["buy_price"], "涨跌幅(%)": 1,
                "持仓市值(元)": price * row["holdings"],
                "浮动盈亏(元)": (price - row["buy_price"]) * row["holdings"],
                "盈亏比例(%)": (price / row["buy_price"] - 1) * 100,
                "行情日期": self.quote_date, "数据周期": "daily",
            }
        return result

    def load_snapshots(self, limit=None):
        self.loaded_limit = limit
        return self.snapshots if limit is None else self.snapshots[-limit:]

    def service(self):
        return MonitorService(
            market_fetcher=lambda: {"测试指数": {
                "最新价": 3300, "涨跌额": 10, "涨跌幅(%)": 1, "行情日期": "2026-03-18",
            }},
            stock_fetcher=self.quotes,
            flow_fetcher=lambda: {"日期": "2026-03-18", "主力净流入-净额": 10},
            analyzer_cls=FakeAnalyzer, trade_loader=lambda: pd.DataFrame(),
            snapshot_loader=self.load_snapshots, snapshot_saver=self.saved.append,
        )

    def run_service(self, **kwargs):
        options = dict(portfolio_df=self.portfolio, use_llm=True, save_report=False,
                       send_notification=False, session_type="post_close", now=self.now)
        options.update(kwargs)
        return self.service().run(**options)

    @staticmethod
    def trade(timestamp="2026-03-18 10:00:00", side="sell", quantity=100):
        return {"timestamp": timestamp, "symbol": "600001", "side": side,
                "quantity": quantity, "price": 11}

    def test_manual_positions_are_not_overwritten_by_partial_trade_log(self):
        result = self.run_service(trade_df=pd.DataFrame([self.trade()]))
        self.assertEqual(result["position_source"], "manual")
        self.assertEqual(result["portfolio"].iloc[0]["holdings"], 1000)
        self.assertIn("清仓止盈", result["report_content"])
        self.assertIn("### 市场补充观察", result["report_content"])
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(FakeAnalyzer.calls, 1)

    def test_complete_trade_ledger_is_an_explicit_mode(self):
        self.config["monitor"]["position_source"] = "trades"
        trades = pd.DataFrame([
            self.trade("2026-03-17 10:00:00", "buy", 1000),
            self.trade(),
        ])
        result = self.run_service(trade_df=trades)
        self.assertEqual(result["portfolio"].iloc[0]["holdings"], 900)
        self.assertEqual(len(result["portfolio"]), 1)

    def test_opening_balance_is_not_double_counted_and_future_trades_are_excluded(self):
        with TemporaryDirectory() as directory:
            opening = Path(directory) / "opening.csv"
            self.portfolio.iloc[:1].to_csv(opening, index=False)
            self.config["monitor"].update(
                position_source="trades", opening_positions_path=str(opening),
                opening_as_of="2026-03-17 15:00:00",
            )
            result = self.run_service(trade_df=pd.DataFrame([
                self.trade("2026-03-17 10:00:00", "buy", 1000),
                self.trade(),
                self.trade("2026-03-19 10:00:00", "sell", 100),
            ]))
            self.assertEqual(result["portfolio"].iloc[0]["holdings"], 900)
            self.assertEqual(len(result["recent_trades"]), 2)

    def test_incomplete_trade_mode_fails_with_actionable_error(self):
        self.config["monitor"]["position_source"] = "trades"
        with self.assertRaisesRegex(ValueError, "期初持仓"):
            self.run_service(trade_df=pd.DataFrame([self.trade()]))

    def test_missing_quote_is_retained_and_partial_valuation_is_marked(self):
        self.missing.add("600002")
        result = self.run_service()
        totals = result["analysis"]["totals"]
        self.assertEqual(totals["count"], 2)
        self.assertEqual(totals["missing_symbols"], ["600002"])
        self.assertFalse(totals["valuation_complete"])
        self.assertIn("估值不完整", result["report_content"])
        self.assertEqual(FakeAnalyzer.calls, 0)

    def test_stale_quotes_suppress_actions_and_llm(self):
        self.quote_date = "2026-03-17"
        result = self.run_service()
        self.assertTrue(all(item["action"] == "持仓观望" for item in result["analysis"]["positions"]))
        self.assertFalse(result["analysis"]["totals"]["valuation_complete"])
        self.assertEqual(FakeAnalyzer.calls, 0)

    def test_intraday_is_daily_observation(self):
        result = self.run_service(session_type="intraday", now=datetime(2026, 3, 18, 10))
        self.assertTrue(all(item["action"] == "持仓观望" for item in result["analysis"]["positions"]))

    def test_dashboard_refresh_can_skip_snapshot_writes(self):
        self.run_service(save_snapshot=False)
        self.assertEqual(self.saved, [])

    def test_missing_llm_key_still_builds_report(self):
        self.config["llm"]["api_key"] = ""
        result = self.run_service()
        self.assertIn("A股持仓诊断报告", result["report_content"])
        self.assertEqual(FakeAnalyzer.calls, 0)

    def test_daily_summary_loads_full_day_and_filters_trades_to_report_date(self):
        self.snapshots = [{
            "timestamp": f"2026-03-18 10:{minute:02d}:00", "session_type": "intraday",
            "totals": {"total_pnl": minute, "valuation_complete": True}, "positions": [],
        } for minute in range(25)]
        trades = [self.trade(f"2026-03-18 10:{minute:02d}:00") for minute in range(7)]
        trades.append(self.trade("2026-03-17 10:00:00"))
        result = self.run_service(trade_df=pd.DataFrame(trades))
        self.assertIsNone(self.loaded_limit)
        self.assertEqual(result["daily_summary"]["snapshot_count"], 26)
        self.assertIn("2026-03-18 10:00:00", result["daily_summary_content"])
        self.assertNotIn("2026-03-17 10:00:00", result["daily_summary_content"])
        self.assertIn("不代表账户当日收益", result["daily_summary_content"])

    def test_utc_input_is_rendered_in_shanghai_time(self):
        result = self.run_service(now=datetime(2026, 3, 18, 7, 10, tzinfo=timezone.utc))
        self.assertIn("2026-03-18 15:10:00", result["report_content"])


if __name__ == "__main__":
    unittest.main()
