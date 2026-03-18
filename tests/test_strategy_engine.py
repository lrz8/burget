import unittest

from src.analyzer.strategy_engine import analyze_market, analyze_positions


class StrategyEngineTest(unittest.TestCase):
    def test_market_bias_prefers_positive_indices_and_flow(self):
        market_data = {
            "上证指数": {"涨跌幅(%)": 0.8},
            "创业板指": {"涨跌幅(%)": 1.6},
        }
        fund_flow = {"主力净流入": 12.5}

        result = analyze_market(market_data, fund_flow)

        self.assertEqual(result["bias"], "偏强")
        self.assertGreater(result["score"], 1.0)

    def test_position_rules_cover_profit_and_loss_paths(self):
        stock_data = {
            "600001": {
                "名称": "测试盈利股",
                "类型": "股票",
                "最新价": 12.5,
                "持仓成本价": 10.0,
                "涨跌幅(%)": 1.2,
                "持仓市值(元)": 1250,
                "浮动盈亏(元)": 250,
                "盈亏比例(%)": 25.0,
            },
            "600002": {
                "名称": "测试亏损股",
                "类型": "股票",
                "最新价": 9.0,
                "持仓成本价": 10.5,
                "涨跌幅(%)": -2.0,
                "持仓市值(元)": 900,
                "浮动盈亏(元)": -150,
                "盈亏比例(%)": -14.29,
            },
        }

        results = analyze_positions(stock_data, {"bias": "震荡"})
        action_map = {item["symbol"]: item["action"] for item in results}

        self.assertEqual(action_map["600001"], "清仓止盈")
        self.assertEqual(action_map["600002"], "割肉止损")


if __name__ == "__main__":
    unittest.main()
