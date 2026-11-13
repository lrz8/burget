import os
import sys
from datetime import datetime
from unittest.mock import patch

import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.service.monitor_service import MonitorService


class FakeAnalyzer:
    def __init__(self, config):
        self.config = config

    def generate_review(self, market_data, stock_data, fund_flow):
        return (
            "### 市场补充观察\n"
            "指数整体偏强，但仍需关注资金分化。\n\n"
            "### 持仓补充观察\n"
            "优先锁定高盈利仓位，深亏标的先控制回撤。"
        )


class FakeNotifier:
    def __init__(self, config):
        self.config = config

    def notify_all(self, title, content):
        print(f"NOTIFY: {title}")


def main():
    portfolio = pd.DataFrame(
        [
            {"symbol": "600001", "name": "测试股A", "holdings": 100, "buy_price": 10.0},
            {"symbol": "600002", "name": "测试股B", "holdings": 200, "buy_price": 11.0},
            {"symbol": "159001", "name": "测试ETF", "holdings": 300, "buy_price": 1.05},
        ]
    )

    service = MonitorService(
        config_path="config/cfg.yml",
        market_fetcher=lambda: {
            "上证指数": {"最新价": 3312.5, "涨跌额": 15.2, "涨跌幅(%)": 0.46},
            "创业板指": {"最新价": 2108.4, "涨跌额": 21.6, "涨跌幅(%)": 1.03},
        },
        stock_fetcher=lambda _: {
            "600001": {
                "名称": "测试股A",
                "类型": "股票",
                "最新价": 12.3,
                "持仓成本价": 10.0,
                "涨跌幅(%)": 1.8,
                "持仓市值(元)": 1230.0,
                "浮动盈亏(元)": 230.0,
                "盈亏比例(%)": 23.0,
            },
            "600002": {
                "名称": "测试股B",
                "类型": "股票",
                "最新价": 9.2,
                "持仓成本价": 11.0,
                "涨跌幅(%)": -2.4,
                "持仓市值(元)": 1840.0,
                "浮动盈亏(元)": -360.0,
                "盈亏比例(%)": -16.36,
            },
            "159001": {
                "名称": "测试ETF",
                "类型": "ETF",
                "最新价": 1.01,
                "持仓成本价": 1.05,
                "涨跌幅(%)": -1.9,
                "持仓市值(元)": 303.0,
                "浮动盈亏(元)": -12.0,
                "盈亏比例(%)": -3.81,
            },
        },
        flow_fetcher=lambda: {"主力净流入": 28.6, "超大单净流入": 12.3},
        analyzer_cls=FakeAnalyzer,
        notifier_cls=FakeNotifier,
        trade_loader=lambda: pd.DataFrame(
            [
                {
                    "timestamp": "2026-03-18 10:00:00",
                    "symbol": "159001",
                    "name": "测试ETF",
                    "side": "buy",
                    "quantity": 300,
                    "price": 1.02,
                    "amount": 306.0,
                    "note": "盘中补仓",
                }
            ]
        ),
        snapshot_loader=lambda limit=20: [
            {
                "timestamp": "2026-03-18 14:30:00",
                "session_type": "intraday",
                "totals": {"total_pnl": -200.0},
                "positions": [
                    {"symbol": "600001", "name": "测试股A", "action": "持仓观望"},
                    {"symbol": "600002", "name": "测试股B", "action": "割肉止损"},
                    {"symbol": "159001", "name": "测试ETF", "action": "持仓观望"},
                ],
            }
        ],
        snapshot_saver=lambda snapshot: None,
    )

    original_stocks = service.stock_fetcher
    original_market = service.market_fetcher
    service.stock_fetcher = lambda portfolio: {
        symbol: {**info, "行情日期": "2026-03-18", "数据周期": "daily"}
        for symbol, info in original_stocks(portfolio).items()
    }
    service.market_fetcher = lambda: {
        name: {**info, "行情日期": "2026-03-18", "数据周期": "daily"}
        for name, info in original_market().items()
    }
    service.flow_fetcher = lambda: {"日期": "2026-03-18", "主力净流入-净额": 28.6}
    with patch("src.service.monitor_service.load_config", return_value={
        "llm": {"api_key": "test-placeholder"}, "monitor": {"position_source": "manual"}, "notifier": {},
    }):
        result = service.run(
            portfolio_df=portfolio, use_llm=True, send_notification=False,
            save_report=True, session_type="post_close", now=datetime(2026, 3, 18, 15, 10),
        )
    assert result["analysis"]["totals"]["valuation_complete"]
    assert "清仓止盈" in result["report_content"]
    assert "割肉止损" in result["report_content"]
    assert "指数整体偏强" in result["llm_commentary"]
    assert result["report_path"].read_text(encoding="utf-8") == result["report_content"]
    assert result["daily_summary_path"].exists()
    print(f"REPORT_PATH={result['report_path']}")
    print(f"DAILY_SUMMARY_PATH={result['daily_summary_path']}")
    print(result["report_content"])


if __name__ == "__main__":
    main()
