import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.utils.trading_time import market_now

logger = logging.getLogger(__name__)


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def analyze_market(market_data: Dict[str, Any], fund_flow: Dict[str, Any]) -> Dict[str, Any]:
    """金额与占比分开处理，不重复叠加资金分类。"""
    changes = [
        value for item in market_data.values()
        if (value := _number(item.get("涨跌幅(%)"))) is not None
    ]
    if not changes:
        return {"bias": "数据不足", "summary": "未获取到有效指数数据，无法判断市场强弱。", "score": 0}

    avg_change = sum(changes) / len(changes)
    net_flow = _number(fund_flow.get("主力净流入-净额", fund_flow.get("主力净流入")))
    score = avg_change
    if net_flow is not None:
        score += 0.5 if net_flow > 0 else -0.5 if net_flow < 0 else 0
    bias = "偏强" if score >= 1 else "偏弱" if score <= -1 else "震荡"
    flow_hint = "结合主力净流入金额" if net_flow is not None else "资金流数据不足，仅参考指数"
    return {
        "bias": bias,
        "summary": f"{len(changes)} 个有效指数平均涨跌幅约为 {avg_change:.2f}%，{flow_hint}，当前判断为{bias}。",
        "score": round(score, 2),
        "fund_flow_available": net_flow is not None,
    }


def analyze_positions(
    stock_data: Dict[str, Any],
    market_analysis: Dict[str, Any],
    session_type: str = "intraday",
    trade_context: Optional[Dict[str, Dict[str, str]]] = None,
    previous_snapshot: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    buy_cooldown_minutes: int = 30,
) -> List[Dict[str, Any]]:
    analyses: List[Dict[str, Any]] = []
    previous_actions = {
        item.get("symbol"): item.get("action")
        for item in (previous_snapshot or {}).get("positions", [])
    }
    current = market_now(now) if now is not None else None
    for symbol, info in stock_data.items():
        price = _number(info.get("最新价"))
        cost = _number(info.get("持仓成本价"))
        pnl = _number(info.get("盈亏比例(%)"))
        day = _number(info.get("涨跌幅(%)"))
        value = _number(info.get("持仓市值(元)"))
        floating = _number(info.get("浮动盈亏(元)"))
        available = (
            price is not None and price > 0 and cost is not None and cost > 0
            and pnl is not None and day is not None and value is not None and value >= 0
            and floating is not None
        )
        reasons: List[str] = []
        quote_date = None
        try:
            quote_date = date.fromisoformat(str(info.get("行情日期", ""))[:10])
        except ValueError:
            pass
        fresh = current is None or quote_date == current.date()
        if not available:
            action, confidence = "持仓观望", "low"
            reasons.append("数据不足，建议观察：行情缺失、数值无效或持仓成本未配置。")
        elif not fresh:
            action, confidence = "持仓观望", "low"
            reasons.append(
                f"数据不足，建议观察：行情日期为 {quote_date or '未知'}，"
                f"与本次日期 {current.date()} 不一致。"
            )
        elif current is not None and (
            info.get("数据周期") != "daily" or session_type != "post_close"
        ):
            action, confidence = "持仓观望", "low"
            reasons.append("当前仅支持日线诊断；盘前、盘中及非交易时段不生成可执行买卖建议，等待盘后确认。")
        else:
            action, reasons, confidence = _decide_action(
                pnl_pct=pnl, day_pct=day,
                market_bias=market_analysis.get("bias", "数据不足"),
                holding_value=value, session_type=session_type,
                trade_context=(trade_context or {}).get(symbol, {}),
                now=current, buy_cooldown_minutes=buy_cooldown_minutes,
            )
        previous_action = previous_actions.get(symbol)
        if previous_action:
            if previous_action != action:
                reasons.append(f"上一条快照建议为“{previous_action}”，当前切换为“{action}”。")
            else:
                reasons.append(f"与上一条快照相比，建议维持“{action}”。")
        analyses.append({
            "symbol": symbol, "name": info.get("名称", symbol), "type": info.get("类型", ""),
            "latest_price": round(price, 3) if price is not None else None,
            "buy_price": round(cost, 4) if cost is not None else None,
            "day_pct": round(day, 2) if day is not None else None,
            "pnl_pct": round(pnl, 2) if pnl is not None else None,
            "floating_pnl": round(floating, 2) if floating is not None else None,
            "holding_value": round(value, 2) if value is not None else None,
            "action": action, "reasons": reasons, "confidence": confidence,
            "data_available": available, "data_fresh": fresh,
            "quote_date": quote_date.isoformat() if quote_date else "",
        })
    analyses.sort(key=lambda item: (
        item["pnl_pct"] is None, item["pnl_pct"] if item["pnl_pct"] is not None else 0
    ))
    return analyses


def build_analysis_result(
    market_data: Dict[str, Any],
    stock_data: Dict[str, Any],
    fund_flow: Dict[str, Any],
    session_type: str = "intraday",
    trade_context: Optional[Dict[str, Dict[str, str]]] = None,
    snapshots: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    buy_cooldown_minutes: int = 30,
) -> Dict[str, Any]:
    market = analyze_market(market_data, fund_flow)
    positions = analyze_positions(
        stock_data, market, session_type=session_type, trade_context=trade_context,
        previous_snapshot=snapshots[-1] if snapshots else None,
        now=now, buy_cooldown_minutes=buy_cooldown_minutes,
    )
    return {"market": market, "positions": positions, "totals": _summarize_positions(positions)}


def _decide_action(
    pnl_pct: float, day_pct: float, market_bias: str, holding_value: float,
    session_type: str, trade_context: Optional[Dict[str, str]],
    now: Optional[datetime] = None, buy_cooldown_minutes: int = 30,
) -> tuple[str, List[str], str]:
    """先生成候选动作，再统一应用交易冷却和阶段说明。"""
    context = trade_context or {}
    if holding_value <= 0:
        action, reasons, confidence = "持仓观望", ["当前无实际仓位需要处理。"], "low"
    elif pnl_pct >= 12:
        action, confidence = "清仓止盈", "high"
        reasons = [f"累计浮盈 {pnl_pct:.2f}%，触及现有 12% 止盈规则。"]
    elif pnl_pct <= -8:
        action, confidence = "割肉止损", "high"
        reasons = [f"累计亏损 {pnl_pct:.2f}%，触及现有 -8% 止损规则。"]
    elif -5 <= pnl_pct <= 5 and market_bias == "偏强" and day_pct <= -1.5:
        action, confidence = "逢低加仓", "medium"
        reasons = [f"累计盈亏 {pnl_pct:.2f}%，当日回撤 {day_pct:.2f}%，市场偏强；仅作为条件预案。"]
    else:
        action, confidence = "持仓观望", "low"
        reasons = [f"累计盈亏 {pnl_pct:.2f}%，当日涨跌 {day_pct:.2f}%。"]
        if (pnl_pct >= 5 and day_pct < 0) or (pnl_pct < 0 and day_pct > 1.5):
            reasons.append("日线信息不足以识别日内买卖点，不据此建议做 T。")
        else:
            reasons.append("现有数据不足以支持进一步操作。")

    if context.get("last_side") == "buy" and action == "逢低加仓":
        try:
            last_time = datetime.fromisoformat(context.get("last_timestamp", ""))
            elapsed = market_now(now) - market_now(last_time)
            cooling_down = timedelta(0) <= elapsed < timedelta(minutes=buy_cooldown_minutes)
        except (TypeError, ValueError):
            cooling_down = True
        if cooling_down:
            action, confidence = "持仓观望", "medium"
            reasons.append(f"最近买入仍处于 {buy_cooldown_minutes} 分钟冷却期，暂停连续加仓。")
    if session_type == "pre_open":
        reasons.append("盘前仅作预案，等待开盘后重新确认数据。")
    elif session_type == "post_close":
        reasons.append("盘后动作仅作为下一交易日预案，执行前应重新确认行情和可用仓位。")
    return action, reasons, confidence


def _summarize_positions(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "count": len(positions),
        "total_value": round(sum(item["holding_value"] or 0 for item in positions), 2),
        "total_pnl": round(sum(item["floating_pnl"] or 0 for item in positions), 2),
        "gain_count": sum(1 for item in positions if (item["pnl_pct"] or 0) > 0),
        "loss_count": sum(1 for item in positions if (item["pnl_pct"] or 0) < 0),
        "valuation_complete": all(item["data_available"] and item["data_fresh"] for item in positions),
        "missing_symbols": [item["symbol"] for item in positions if not item["data_available"]],
        "stale_symbols": [item["symbol"] for item in positions if not item["data_fresh"]],
    }
