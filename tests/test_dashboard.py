import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest


class DashboardTest(unittest.TestCase):
    @staticmethod
    def empty_portfolio():
        return pd.DataFrame(columns=["symbol", "name", "holdings", "buy_price"])

    def test_trade_driven_positions_render_when_manual_table_is_empty(self):
        portfolio = pd.DataFrame([{"symbol": "600001", "name": "测试股", "holdings": 100, "buy_price": 10}])
        position = {
            "symbol": "600001", "name": "测试股", "action": "持仓观望",
            "confidence": "low", "reasons": ["日线观察"],
        }
        result = {
            "portfolio": portfolio, "position_source": "trades", "session_type": "intraday",
            "market_data": {}, "stock_data": {"600001": {
                "名称": "测试股", "最新价": 10, "持仓成本价": 10,
                "涨跌幅(%)": 0, "持仓市值(元)": 1000, "浮动盈亏(元)": 0, "盈亏比例(%)": 0,
            }},
            "analysis": {"positions": [position], "totals": {"valuation_complete": True}},
            "recent_trades": [], "history_summary": {},
        }
        with TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("src.utils.runtime.setup_logging", return_value=Path(directory) / "dashboard.log"))
            stack.enter_context(patch("src.data.portfolio_manager.load_portfolio", return_value=self.empty_portfolio()))
            stack.enter_context(patch("src.data.trade_manager.load_trade_log", return_value=pd.DataFrame(columns=["timestamp"])))
            stack.enter_context(patch("src.fetcher.market_data.get_stock_history_kline", return_value=pd.DataFrame()))
            run = stack.enter_context(patch("src.service.monitor_service.MonitorService.run", return_value=result))
            app = AppTest.from_file("src/dashboard/app.py", default_timeout=15).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.dataframe), 2)
            self.assertFalse(run.call_args.kwargs["save_snapshot"])
            self.assertFalse(run.call_args.kwargs["save_report"])

    def test_invalid_trade_file_shows_an_error_without_uncaught_exception(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("src.utils.runtime.setup_logging", return_value=Path(directory) / "dashboard.log"))
            stack.enter_context(patch("src.data.portfolio_manager.load_portfolio", return_value=self.empty_portfolio()))
            stack.enter_context(patch("src.data.trade_manager.load_trade_log", side_effect=ValueError("记录无效")))
            run = stack.enter_context(patch("src.service.monitor_service.MonitorService.run"))
            app = AppTest.from_file("src/dashboard/app.py", default_timeout=15).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("无法读取交易记录" in item.value for item in app.error))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
