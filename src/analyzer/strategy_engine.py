import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


def analyze_market(market_data: Dict[str, Any], fund_flow: Dict[str, Any]) -> Dict[str, Any]:
    """基于已抓取数据生成市场强弱判断。"""
    if not market_data:
        return {
            "bias": "数据不足",
            "summary": "未获取到指数数据，无法判断市场强弱。",
            "score": 0,
        }

    pct_changes = [float(item.get("涨跌幅(%)", 0.0)) for item in market_data.values()]
    avg_change = sum(pct_changes) / len(pct_changes) if pct_changes else 0.0

    net_flow = 0.0
    flow_keywords = ("净流入", "净额", "净买入", "主力净")
    for key, value in fund_flow.items():
        if any(keyword in str(key) for keyword in flow_keywords):
            try:
                net_flow += float(value)
            except (TypeError, ValueError):
                continue

    score = avg_change
    if net_flow > 0:
        score += 0.5
    elif net_flow < 0:
        score -= 0.5

    if score >= 1.0:
        bias = "偏强"
    elif score <= -1.0:
        bias = "偏弱"
    else:
        bias = "震荡"

    summary = (
        f"主要指数平均涨跌幅约为 {avg_change:.2f}%，"
        f"结合资金流向信号，当前市场判断为{bias}。"
    )
    logger.info("市场分析完成: bias=%s, score=%.2f", bias, score)
    return {"bias": bias, "summary": summary, "score": round(score, 2)}


def analyze_positions(
    stock_data: Dict[str, Any], market_analysis: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """根据持仓盈亏与当日涨跌幅生成结构化建议。"""
    analyses: List[Dict[str, Any]] = []
    market_bias = market_analysis.get("bias", "震荡")

    for symbol, info in stock_data.items():
        pnl_pct = float(info.get("盈亏比例(%)", 0.0))
        day_pct = float(info.get("涨跌幅(%)", 0.0))
        floating_pnl = float(info.get("浮动盈亏(元)", 0.0))
        holding_value = float(info.get("持仓市值(元)", 0.0))
        latest_price = float(info.get("最新价", 0.0))
        buy_price = float(info.get("持仓成本价", 0.0))

        action, reasons, confidence = _decide_action(
            pnl_pct=pnl_pct,
            day_pct=day_pct,
            market_bias=market_bias,
            holding_value=holding_value,
        )

        analyses.append(
            {
                "symbol": symbol,
                "name": info.get("名称", symbol),
                "type": info.get("类型", ""),
                "latest_price": round(latest_price, 2),
                "buy_price": round(buy_price, 3),
                "day_pct": round(day_pct, 2),
                "pnl_pct": round(pnl_pct, 2),
                "floating_pnl": round(floating_pnl, 2),
                "holding_value": round(holding_value, 2),
                "action": action,
                "reasons": reasons,
                "confidence": confidence,
            }
        )

    analyses.sort(key=lambda item: item["pnl_pct"])
    logger.info("持仓诊断完成，共 %s 个标的。", len(analyses))
    return analyses


def build_analysis_result(
    market_data: Dict[str, Any], stock_data: Dict[str, Any], fund_flow: Dict[str, Any]
) -> Dict[str, Any]:
    market_analysis = analyze_market(market_data, fund_flow)
    position_analysis = analyze_positions(stock_data, market_analysis)
    totals = _summarize_positions(position_analysis)
    return {
        "market": market_analysis,
        "positions": position_analysis,
        "totals": totals,
    }


def _decide_action(
    pnl_pct: float, day_pct: float, market_bias: str, holding_value: float
) -> tuple[str, List[str], str]:
    reasons: List[str] = []

    if holding_value <= 0:
        return "持仓观望", ["当前持仓市值为 0，暂无实际仓位需要处理。"], "low"

    if pnl_pct >= 12:
        action = "清仓止盈"
        reasons.append(f"当前累计浮盈 {pnl_pct:.2f}%，已达到较高收益区间。")
        reasons.append(f"当日涨跌幅为 {day_pct:.2f}%，优先考虑兑现收益而不是继续放大波动。")
        return action, reasons, "high"

    if pnl_pct <= -8:
        action = "割肉止损"
        reasons.append(f"当前累计亏损 {pnl_pct:.2f}%，已超过预设风险容忍区间。")
        reasons.append("在没有更多分时与事件信息前，先控制回撤更稳妥。")
        return action, reasons, "high"

    if pnl_pct >= 5 and day_pct < 0:
        action = "做T（低吸高抛）"
        reasons.append(f"当前仍有 {pnl_pct:.2f}% 的浮盈，但当日回落 {day_pct:.2f}%。")
        reasons.append("已有利润垫时优先通过仓位微调降低波动。")
        return action, reasons, "medium"

    if -5 <= pnl_pct <= 5 and market_bias == "偏强" and day_pct <= -1.5:
        action = "逢低加仓"
        reasons.append(f"当前总盈亏 {pnl_pct:.2f}% 接近成本区，价格回撤 {day_pct:.2f}%。")
        reasons.append("市场整体偏强时，成本附近的回撤更适合分批低吸。")
        return action, reasons, "medium"

    if pnl_pct < 0 and day_pct > 1.5:
        action = "做T（低吸高抛）"
        reasons.append(f"当前仍亏损 {pnl_pct:.2f}%，但当日反弹 {day_pct:.2f}%。")
        reasons.append("先利用反弹降低持仓成本，比直接追价加仓更稳。")
        return action, reasons, "medium"

    action = "持仓观望"
    reasons.append(f"当前总盈亏 {pnl_pct:.2f}%，当日涨跌幅 {day_pct:.2f}%。")
    reasons.append("现有数据不足以支撑更激进动作，先观察更合适。")
    return action, reasons, "low"


def _summarize_positions(position_analysis: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_value = sum(item["holding_value"] for item in position_analysis)
    total_pnl = sum(item["floating_pnl"] for item in position_analysis)
    gain_count = sum(1 for item in position_analysis if item["pnl_pct"] > 0)
    loss_count = sum(1 for item in position_analysis if item["pnl_pct"] < 0)
    return {
        "count": len(position_analysis),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "gain_count": gain_count,
        "loss_count": loss_count,
    }
