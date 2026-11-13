import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import pandas as pd

from src.analyzer.llm_report import LLMAnalyzer
from src.analyzer.report_builder import build_daily_summary_report, build_markdown_report
from src.analyzer.strategy_engine import build_analysis_result
from src.config.loader import load_config
from src.data.portfolio_manager import (
    load_portfolio,
    normalize_portfolio,
)
from src.data.snapshot_manager import (
    append_snapshot,
    build_snapshot_payload,
    load_snapshots,
    summarize_daily_snapshots,
    summarize_snapshot_history,
)
from src.data.trade_manager import (
    build_trade_context,
    derive_position_book,
    get_recent_trades,
    load_trade_log,
    normalize_trade_log,
    summarize_recent_trades,
)
from src.fetcher.market_data import (
    get_market_money_flow,
    get_market_summary,
    get_stock_data,
)
from src.notifier.dispatcher import NotifierDispatcher
from src.service.session_planner import resolve_session_type
from src.utils.runtime import save_markdown_report
from src.utils.trading_time import market_now


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
        trade_loader: Callable[[], pd.DataFrame] = load_trade_log,
        snapshot_loader: Callable[..., list[Dict[str, Any]]] = load_snapshots,
        snapshot_saver: Callable[..., None] = append_snapshot,
    ):
        self.config_path = config_path
        self.market_fetcher = market_fetcher
        self.stock_fetcher = stock_fetcher
        self.flow_fetcher = flow_fetcher
        self.analyzer_cls = analyzer_cls
        self.notifier_cls = notifier_cls
        self.trade_loader = trade_loader
        self.snapshot_loader = snapshot_loader
        self.snapshot_saver = snapshot_saver

    def run(
        self,
        portfolio_df: Optional[pd.DataFrame] = None,
        use_llm: bool = True,
        send_notification: bool = False,
        save_report: bool = True,
        save_snapshot: bool = True,
        session_type: str = "auto",
        now: Optional[datetime] = None,
        trade_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        current_time = market_now(now)
        resolved_session = resolve_session_type(current_time) if session_type == "auto" else session_type
        config = load_config(self.config_path)
        monitor_config = config.get("monitor", {})
        cooldown = monitor_config.get("buy_cooldown_minutes", 30)
        if isinstance(cooldown, bool) or not isinstance(cooldown, int) or not 0 < cooldown <= 1440:
            raise ValueError("monitor.buy_cooldown_minutes 必须为 1 到 1440 的整数。")
        trade_log = normalize_trade_log(trade_df if trade_df is not None else self.trade_loader())
        if not trade_log.empty:
            trade_log = trade_log[pd.to_datetime(trade_log["timestamp"]) <= current_time].copy()
        manual_portfolio = normalize_portfolio(portfolio_df) if portfolio_df is not None else load_portfolio()
        position_source = monitor_config.get("position_source", "manual")
        trade_book = pd.DataFrame(columns=["symbol", "name", "holdings", "buy_price"])
        if position_source == "manual":
            portfolio = manual_portfolio.copy()
        elif position_source == "trades":
            opening_positions = None
            ledger = trade_log
            opening_path = monitor_config.get("opening_positions_path", "")
            if opening_path:
                raw_start = monitor_config.get("opening_as_of", "")
                if not raw_start:
                    raise ValueError("使用期初持仓时必须配置 monitor.opening_as_of。")
                start_time = market_now(datetime.fromisoformat(str(raw_start)))
                if start_time > current_time:
                    raise ValueError("期初持仓时点不能晚于本次诊断时间。")
                opening_positions = normalize_portfolio(pd.read_csv(opening_path, dtype={"symbol": str}))
                ledger = trade_log[pd.to_datetime(trade_log["timestamp"]) > start_time]
            trade_book = derive_position_book(ledger, opening_positions=opening_positions, as_of=current_time)
            portfolio = normalize_portfolio(trade_book)
        else:
            raise ValueError("monitor.position_source 必须为 manual 或 trades。")
        recent_trade_df = get_recent_trades(trade_log, now=current_time)
        recent_trades = summarize_recent_trades(recent_trade_df)
        trade_context = build_trade_context(recent_trade_df)
        snapshots = [
            item for item in self.snapshot_loader(limit=None)
            if item.get("timestamp", "") <= current_time.strftime("%Y-%m-%d %H:%M:%S")
        ]

        logger.info("开始执行主流程，session=%s, 持仓数=%s", resolved_session, len(portfolio))
        market_data = self.market_fetcher()
        stock_data = self.stock_fetcher(portfolio) if not portfolio.empty else {}
        fund_flow = self.flow_fetcher()

        # 保留缺失标的，避免将抓取失败误报为仓位消失或总市值减少。
        analysis_stock_data = {
            row["symbol"]: stock_data.get(row["symbol"], {
                "名称": row["name"] or row["symbol"],
                "持仓数量": row["holdings"], "持仓成本价": row["buy_price"],
            })
            for row in portfolio.to_dict("records")
        }
        current_date = current_time.date().isoformat()
        fresh_market = {
            name: info for name, info in market_data.items()
            if str(info.get("行情日期", ""))[:10] == current_date
        }
        fresh_flow = fund_flow if str(fund_flow.get("日期", ""))[:10] == current_date else {}
        analysis = build_analysis_result(
            fresh_market,
            analysis_stock_data,
            fresh_flow,
            session_type=resolved_session,
            trade_context=trade_context,
            snapshots=snapshots,
            now=current_time,
            buy_cooldown_minutes=cooldown,
        )
        history_summary = summarize_snapshot_history(snapshots, analysis)
        llm_commentary = self._generate_llm_commentary(
            config, fresh_market, stock_data, fresh_flow, analysis,
            use_llm and analysis["totals"]["valuation_complete"]
        )
        report_content = build_markdown_report(
            market_data=market_data,
            stock_data=stock_data,
            fund_flow=fund_flow,
            analysis=analysis,
            llm_commentary=llm_commentary,
            session_type=resolved_session,
            history_summary=history_summary,
            recent_trades=recent_trades,
            generated_at=current_time,
        )

        snapshot = build_snapshot_payload(
            session_type=resolved_session,
            market_data=market_data,
            stock_data=stock_data,
            analysis=analysis,
            recent_trades=recent_trades,
            timestamp=current_time,
        )
        report_path = save_markdown_report(report_content, prefix=resolved_session, timestamp=current_time) if save_report else None
        if save_snapshot:
            self.snapshot_saver(snapshot)

        daily_summary = {}
        daily_summary_content = ""
        daily_summary_path = None
        if resolved_session == "post_close":
            daily_summary = summarize_daily_snapshots([*snapshots, snapshot], current_time.date())
            daily_trades = trade_log[
                pd.to_datetime(trade_log["timestamp"]).dt.date == current_time.date()
            ] if not trade_log.empty else trade_log
            daily_summary_content = build_daily_summary_report(
                daily_summary, recent_trades=summarize_recent_trades(daily_trades, limit=None)
            )
            if save_report:
                daily_summary_path = save_markdown_report(daily_summary_content, prefix="daily_summary", timestamp=current_time)

        if send_notification and report_content:
            notifier = self.notifier_cls(config)
            notifier.notify_all(f"AI 盯盘助手 {resolved_session} 诊断", report_content)

        result = {
            "config": config,
            "portfolio": portfolio,
            "manual_portfolio": manual_portfolio,
            "trade_book": trade_book,
            "position_source": position_source,
            "session_type": resolved_session,
            "market_data": market_data,
            "stock_data": stock_data,
            "fund_flow": fund_flow,
            "recent_trades": recent_trades,
            "history_summary": history_summary,
            "daily_summary": daily_summary,
            "daily_summary_content": daily_summary_content,
            "daily_summary_path": daily_summary_path,
            "analysis": analysis,
            "llm_commentary": llm_commentary,
            "report_content": report_content,
            "report_path": report_path,
        }
        logger.info(
            "主流程完成: session=%s, stocks=%s, report_saved=%s",
            resolved_session,
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

        if not config.get("llm", {}).get("api_key"):
            logger.info("未配置 LLM API Key，跳过补充解读。")
            return ""
        analyzer = self.analyzer_cls(config)
        llm_text = analyzer.generate_review(market_data, stock_data, fund_flow)
        if not llm_text:
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
