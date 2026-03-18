import unittest

from src.analyzer.report_builder import build_markdown_report


class ReportBuilderTest(unittest.TestCase):
    def test_report_contains_core_sections(self):
        report = build_markdown_report(
            market_data={"上证指数": {"最新价": 3300, "涨跌额": 10, "涨跌幅(%)": 0.3}},
            stock_data={"600001": {"名称": "测试股"}},
            fund_flow={"主力净流入": 20},
            analysis={
                "market": {"bias": "震荡", "summary": "测试市场结论"},
                "positions": [
                    {
                        "symbol": "600001",
                        "name": "测试股",
                        "latest_price": 10.2,
                        "buy_price": 10.0,
                        "day_pct": 0.5,
                        "pnl_pct": 2.0,
                        "action": "持仓观望",
                        "reasons": ["当前总盈亏 2.00%。", "现有数据不足以支撑更激进动作。"],
                    }
                ],
                "totals": {
                    "count": 1,
                    "total_value": 1020,
                    "total_pnl": 20,
                    "gain_count": 1,
                    "loss_count": 0,
                },
            },
            llm_commentary="### 市场补充观察\n测试文本",
        )

        self.assertIn("## 市场概览", report)
        self.assertIn("## 持仓诊断", report)
        self.assertIn("## LLM 辅助结论", report)
        self.assertIn("测试股", report)


if __name__ == "__main__":
    unittest.main()
