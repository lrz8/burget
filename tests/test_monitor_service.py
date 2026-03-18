import unittest
from datetime import datetime

import pandas as pd

from src.service.monitor_service import MonitorService


class FakeAnalyzer:
    def __init__(self, config):
        self.config = config

    def generate_review(self, market_data, stock_data, fund_flow):
        return "### 市场补充观察\n指数偏强。\n\n### 持仓补充观察\n优先处理高亏损标的。"


class FakeNotifier:
    def __init__(self, config):
        self.config = config
        self.messages = []

    def notify_all(self, title, content):
        self.messages.append((title, content))


class MonitorServiceTest(unittest.TestCase):
    def test_service_builds_full_report_without_network(self):
        portfolio = pd.DataFrame(
            [
                {"symbol": "600001", "name": "测试股A", "holdings": 100, "buy_price": 10.0},
                {"symbol": "600002", "name": "测试股B", "holdings": 100, "buy_price": 11.0},
            ]
        )

        service = MonitorService(
            config_path="config/cfg.yml",
            market_fetcher=lambda: {
                "上证指数": {"最新价": 3300, "涨跌额": 12, "涨跌幅(%)": 0.36}
            },
            stock_fetcher=lambda _: {
                "600001": {
                    "名称": "测试股A",
                    "类型": "股票",
                    "最新价": 12.0,
                    "持仓成本价": 10.0,
                    "涨跌幅(%)": 1.5,
                    "持仓市值(元)": 1200,
                    "浮动盈亏(元)": 200,
                    "盈亏比例(%)": 20.0,
                },
                "600002": {
                    "名称": "测试股B",
                    "类型": "股票",
                    "最新价": 9.5,
                    "持仓成本价": 11.0,
                    "涨跌幅(%)": -1.2,
                    "持仓市值(元)": 950,
                    "浮动盈亏(元)": -150,
                    "盈亏比例(%)": -13.64,
                },
            },
            flow_fetcher=lambda: {"主力净流入": 30.0},
            analyzer_cls=FakeAnalyzer,
            notifier_cls=FakeNotifier,
            trade_loader=lambda: pd.DataFrame(
                [
                    {
                        "timestamp": "2026-03-18 09:35:00",
                        "symbol": "600002",
                        "name": "测试股B",
                        "side": "buy",
                        "quantity": 100,
                        "price": 9.6,
                        "amount": 960,
                        "note": "补仓",
                    }
                ]
            ),
            snapshot_loader=lambda limit=20: [
                {
                    "timestamp": "2026-03-18 09:00:00",
                    "session_type": "pre_open",
                    "totals": {"total_pnl": 10},
                    "positions": [
                        {"symbol": "600001", "action": "持仓观望"},
                        {"symbol": "600002", "action": "逢低加仓"},
                    ],
                }
            ],
            snapshot_saver=lambda snapshot: None,
        )

        result = service.run(
            portfolio_df=portfolio,
            use_llm=True,
            send_notification=False,
            save_report=False,
            session_type="intraday",
            now=datetime(2026, 3, 18, 10, 0, 0),
        )

        self.assertIn("A股持仓诊断报告", result["report_content"])
        self.assertIn("600001", result["report_content"])
        self.assertIn("清仓止盈", result["report_content"])
        self.assertIn("持仓观望", result["report_content"])
        self.assertIn("### 市场补充观察", result["report_content"])
        self.assertIn("历史与交易记录", result["report_content"])
        self.assertEqual(result["session_type"], "intraday")
        self.assertIsNone(result["report_path"])


if __name__ == "__main__":
    unittest.main()
