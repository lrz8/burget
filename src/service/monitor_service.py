import logging
from typing import Any, Callable, Dict, Optional

import pandas as pd

from src.analyzer.llm_report import LLMAnalyzer
from src.analyzer.report_builder import build_markdown_report
from src.analyzer.strategy_engine import build_analysis_result
from src.config.loader import load_config
from src.data.portfolio_manager import load_portfolio, normalize_portfolio
from src.fetcher.market_data import (
    get_market_money_flow,
    get_market_summary,
    get_stock_data,
)
from src.notifier.dispatcher import NotifierDispatcher
from src.utils.runtime import save_markdown_report


logger = logging.getLogger(__name__)


class MonitorService:
    """统一承载抓取、分析、报告、通知主流程。"""

    def __init__(
        self,
        config_path: str = "config/cfg.yml",
        market_fetcher: Callable[[], Dict[str, Any]] = get_market_summary,
        stock_fetcher: Callable[[pd.DataFrame], Dict[str, Any]] = get_stock_data,
        flow_fetcher: Callable[[], Dict[str, Any]] = get_market_money_flow,
        analyzer_cls: type[LLMAnalyzer] = LLMAnalyzer,
        notifier_cls: type[NotifierDispatcher] = NotifierDispatcher,
    ):
        self.config_path = config_path
        self.market_fetcher = market_fetcher
        self.stock_fetcher = stock_fetcher
        self.flow_fetcher = flow_fetcher
        self.analyzer_cls = analyzer_cls
        self.notifier_cls = notifier_cls

    def run(
        self,
        portfolio_df: Optional[pd.DataFrame] = None,
        use_llm: bool = True,
        send_notification: bool = False,
        save_report: bool = True,
    ) -> Dict[str, Any]:
        config = load_config(self.config_path)
        portfolio = normalize_portfolio(portfolio_df) if portfolio_df is not None else load_portfolio()

        logger.info("开始执行主流程，持仓数=%s", len(portfolio))
        market_data = self.market_fetcher()
        stock_data = self.stock_fetcher(portfolio) if not portfolio.empty else {}
        fund_flow = self.flow_fetcher()

        analysis = build_analysis_result(market_data, stock_data, fund_flow)
        llm_commentary = self._generate_llm_commentary(
            config, market_data, stock_data, fund_flow, analysis, use_llm
        )
        report_content = build_markdown_report(
            market_data=market_data,
            stock_data=stock_data,
            fund_flow=fund_flow,
            analysis=analysis,
            llm_commentary=llm_commentary,
        )

        report_path = save_markdown_report(report_content) if save_report else None
        if send_notification and report_content:
            notifier = self.notifier_cls(config)
            notifier.notify_all("AI 盯盘助手策略诊断", report_content)

        result = {
            "config": config,
            "portfolio": portfolio,
            "market_data": market_data,
            "stock_data": stock_data,
            "fund_flow": fund_flow,
            "analysis": analysis,
            "llm_commentary": llm_commentary,
            "report_content": report_content,
            "report_path": report_path,
        }
        logger.info(
            "主流程完成: stocks=%s, report_saved=%s",
            len(stock_data),
            bool(report_path),
        )
        return result

    def _generate_llm_commentary(
        self,
        config: Dict[str, Any],
        market_data: Dict[str, Any],
        stock_data: Dict[str, Any],
        fund_flow: Dict[str, Any],
        analysis: Dict[str, Any],
        use_llm: bool,
    ) -> str:
        if not use_llm:
            logger.info("本次执行未启用 LLM。")
            return ""

        if not stock_data:
            logger.info("没有持仓行情数据，跳过 LLM。")
            return ""

        analyzer = self.analyzer_cls(config)
        llm_text = analyzer.generate_review(market_data, stock_data, fund_flow)
        if not llm_text or "失败" in llm_text or "缺失" in llm_text:
            logger.warning("LLM 输出不可用，降级为纯规则报告。")
            return ""

        action_lines = []
        for item in analysis["positions"]:
            action_lines.append(f"- {item['symbol']} {item['name']}：{item['action']}")

        return "\n".join(
            [
                "以下为基于同一份输入数据生成的补充解读：",
                llm_text.strip(),
                "",
                "规则引擎动作摘要：",
                *action_lines,
            ]
        ).strip()
