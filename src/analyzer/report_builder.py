from datetime import datetime
from typing import Any, Dict, List, Optional


def build_markdown_report(
    market_data: Dict[str, Any],
    stock_data: Dict[str, Any],
    fund_flow: Dict[str, Any],
    analysis: Dict[str, Any],
    llm_commentary: str = "",
    session_type: str = "intraday",
    history_summary: Optional[Dict[str, Any]] = None,
    recent_trades: Optional[List[Dict[str, str]]] = None,
) -> str:
    """组合结构化诊断结果，生成稳定可读的 Markdown 报告。"""
    market_section = _render_market_section(market_data, fund_flow, analysis["market"], session_type)
    positions_section = _render_positions_section(analysis["positions"], analysis["totals"])
    history_section = _render_history_section(history_summary or {}, recent_trades or [])
    llm_section = _render_llm_section(llm_commentary)
    risk_section = _render_risk_section(stock_data)

    sections = [
        f"# A股持仓诊断报告",
        f"**生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}**",
        f"**运行阶段：{_session_label(session_type)}**",
        "",
        market_section,
        "",
        positions_section,
        "",
        history_section,
        "",
        llm_section,
        "",
        risk_section,
    ]
    return "\n".join(section for section in sections if section is not None).strip() + "\n"


def _render_market_section(
    market_data: Dict[str, Any],
    fund_flow: Dict[str, Any],
    market_analysis: Dict[str, Any],
    session_type: str,
) -> str:
    lines = [
        "## 市场概览",
        f"- 阶段说明：{_session_hint(session_type)}",
        f"- 市场判断：**{market_analysis.get('bias', '数据不足')}**",
        f"- 核心结论：{market_analysis.get('summary', '暂无结论')}",
    ]

    if market_data:
        lines.append("- 主要指数：")
        for name, info in market_data.items():
            lines.append(
                f"  - {name}：{info.get('最新价', 'N/A')}，"
                f"涨跌 {info.get('涨跌额', 'N/A')}，涨跌幅 {info.get('涨跌幅(%)', 'N/A')}%"
            )
    else:
        lines.append("- 主要指数：未获取到指数数据。")

    if fund_flow:
        flow_fragments = []
        for key, value in fund_flow.items():
            flow_fragments.append(f"{key}={value}")
            if len(flow_fragments) >= 5:
                break
        lines.append(f"- 资金流摘要：{'；'.join(flow_fragments)}")
    else:
        lines.append("- 资金流摘要：未获取到资金流数据。")
    return "\n".join(lines)


def _render_positions_section(position_analysis: List[Dict[str, Any]], totals: Dict[str, Any]) -> str:
    lines = [
        "## 持仓诊断",
        f"- 持仓数量：{totals.get('count', 0)}",
        f"- 持仓总市值：{totals.get('total_value', 0)} 元",
        f"- 总浮动盈亏：{totals.get('total_pnl', 0)} 元",
        f"- 盈利标的 / 亏损标的：{totals.get('gain_count', 0)} / {totals.get('loss_count', 0)}",
        "",
        "| 代码 | 名称 | 最新价 | 成本价 | 当日涨跌幅 | 浮盈亏比例 | 建议动作 | 原因 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    if not position_analysis:
        lines.append("| - | - | - | - | - | - | - | 暂无持仓或行情数据 |")
        return "\n".join(lines)

    for item in position_analysis:
        reason_text = " ".join(item["reasons"])
        lines.append(
            f"| {item['symbol']} | {item['name']} | {item['latest_price']} | {item['buy_price']} | "
            f"{item['day_pct']}% | {item['pnl_pct']}% | {item['action']} | {reason_text} |"
        )
    return "\n".join(lines)


def _render_llm_section(llm_commentary: str) -> str:
    lines = ["## LLM 辅助结论"]
    if llm_commentary:
        lines.append(llm_commentary.strip())
    else:
        lines.append("本次未启用 LLM 润色，以上结论完全基于规则引擎与结构化数据。")
    return "\n".join(lines)


def _render_history_section(history_summary: Dict[str, Any], recent_trades: List[Dict[str, str]]) -> str:
    lines = ["## 历史与交易记录"]
    if history_summary:
        lines.append(f"- 历史快照对比：{history_summary.get('summary', '暂无历史快照结论。')}")
    else:
        lines.append("- 历史快照对比：暂无。")

    if recent_trades:
        lines.append("- 最近交易：")
        for item in recent_trades[:5]:
            side_label = "买入" if item.get("side") == "buy" else "卖出"
            lines.append(
                f"  - {item.get('timestamp', '')} {item.get('symbol', '')} {item.get('name', '')} "
                f"{side_label} {item.get('quantity', '')} 股，价格 {item.get('price', '')}。"
            )
    else:
        lines.append("- 最近交易：暂无。")
    return "\n".join(lines)


def _render_risk_section(stock_data: Dict[str, Any]) -> str:
    lines = [
        "## 风险提示",
        "- 当前结论主要依据持仓成本、最新价、日线级涨跌幅和资金流摘要，不包含分时、盘口、新闻事件和公告影响。",
        "- 这份报告用于辅助梳理仓位状态，不构成自动交易指令。",
    ]
    if not stock_data:
        lines.append("- 本次未抓到有效持仓行情，结论可信度有限。")
    return "\n".join(lines)


def _session_label(session_type: str) -> str:
    return {
        "pre_open": "盘前预判",
        "intraday": "盘中跟踪",
        "post_close": "盘后总结",
        "midday_break": "午间观察",
        "off_hours": "非交易时段",
    }.get(session_type, session_type)


def _session_hint(session_type: str) -> str:
    return {
        "pre_open": "基于开盘前可获得的上一交易日与最新资金数据，生成盘前预判。",
        "intraday": "基于当前轮次抓取结果，生成盘中跟踪建议。",
        "post_close": "基于收盘后数据和交易记录，生成盘后总结与次日预案。",
        "midday_break": "当前属于午间休市阶段，可用于回顾上午走势。",
        "off_hours": "当前处于非交易时段，结果更适合作为观察记录。",
    }.get(session_type, "按当前数据生成诊断。")
