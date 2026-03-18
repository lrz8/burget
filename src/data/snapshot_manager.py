import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

SNAPSHOT_FILE = "data/snapshots.jsonl"


def append_snapshot(snapshot: Dict[str, Any], path: str = SNAPSHOT_FILE) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False, default=str) + "\n")
        logger.info("已追加历史快照: %s", snapshot.get("timestamp", "unknown"))
    except Exception as exc:
        logger.error("保存历史快照失败: %s", exc, exc_info=True)


def load_snapshots(path: str = SNAPSHOT_FILE, limit: Optional[int] = 20) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []

    snapshots: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    snapshots.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("跳过无法解析的历史快照行。")
                    continue
    except Exception as exc:
        logger.error("读取历史快照失败: %s", exc, exc_info=True)
        return []

    snapshots.sort(key=lambda item: item.get("timestamp", ""))
    if limit is not None:
        return snapshots[-limit:]
    return snapshots


def build_snapshot_payload(
    session_type: str,
    market_data: Dict[str, Any],
    stock_data: Dict[str, Any],
    analysis: Dict[str, Any],
    recent_trades: List[Dict[str, str]],
    timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    current_time = timestamp or datetime.now()
    return {
        "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_type": session_type,
        "market_bias": analysis.get("market", {}).get("bias", ""),
        "market_summary": analysis.get("market", {}).get("summary", ""),
        "totals": analysis.get("totals", {}),
        "positions": [
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "action": item["action"],
                "latest_price": item["latest_price"],
                "pnl_pct": item["pnl_pct"],
            }
            for item in analysis.get("positions", [])
        ],
        "recent_trades": recent_trades,
        "market_data": market_data,
        "stock_data": stock_data,
    }


def summarize_snapshot_history(
    snapshots: List[Dict[str, Any]], current_analysis: Dict[str, Any]
) -> Dict[str, Any]:
    if not snapshots:
        return {
            "summary": "这是第一条历史快照，后续运行后才会形成趋势比较。",
            "action_changes": 0,
            "pnl_delta": 0.0,
            "previous_session": "",
        }

    previous = snapshots[-1]
    previous_totals = previous.get("totals", {})
    current_totals = current_analysis.get("totals", {})
    pnl_delta = round(
        float(current_totals.get("total_pnl", 0.0)) - float(previous_totals.get("total_pnl", 0.0)),
        2,
    )

    previous_actions = {
        item.get("symbol"): item.get("action")
        for item in previous.get("positions", [])
    }
    action_changes = 0
    for item in current_analysis.get("positions", []):
        symbol = item.get("symbol")
        if previous_actions.get(symbol) and previous_actions.get(symbol) != item.get("action"):
            action_changes += 1

    previous_session = previous.get("session_type", "")
    summary = (
        f"相较上一条 {previous_session or '历史'} 快照，组合浮盈亏变化 {pnl_delta} 元，"
        f"动作发生变化的标的数为 {action_changes}。"
    )
    return {
        "summary": summary,
        "action_changes": action_changes,
        "pnl_delta": pnl_delta,
        "previous_session": previous_session,
    }


def summarize_daily_snapshots(
    snapshots: List[Dict[str, Any]],
    target_date: Optional[date] = None,
) -> Dict[str, Any]:
    current_date = target_date or datetime.now().date()
    daily = []
    for item in snapshots:
        ts = item.get("timestamp", "")
        try:
            snapshot_time = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if snapshot_time.date() == current_date:
            daily.append(item)

    if not daily:
        return {
            "report_date": current_date.strftime("%Y-%m-%d"),
            "snapshot_count": 0,
            "sessions": [],
            "pnl_change": 0.0,
            "summary": "当日还没有历史快照，无法形成盘中节奏总结。",
            "latest_actions": [],
        }

    daily.sort(key=lambda item: item.get("timestamp", ""))
    first = daily[0]
    last = daily[-1]
    first_pnl = float(first.get("totals", {}).get("total_pnl", 0.0))
    last_pnl = float(last.get("totals", {}).get("total_pnl", 0.0))
    sessions = [item.get("session_type", "") for item in daily]
    latest_actions = [
        {
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "action": item.get("action", ""),
            "pnl_pct": item.get("pnl_pct", 0.0),
        }
        for item in last.get("positions", [])
    ]
    summary = (
        f"当日共记录 {len(daily)} 条快照，阶段覆盖 {', '.join(sessions)}，"
        f"组合浮盈亏从 {first_pnl} 元变为 {last_pnl} 元，变化 {round(last_pnl - first_pnl, 2)} 元。"
    )
    return {
        "report_date": current_date.strftime("%Y-%m-%d"),
        "snapshot_count": len(daily),
        "sessions": sessions,
        "pnl_change": round(last_pnl - first_pnl, 2),
        "summary": summary,
        "latest_actions": latest_actions,
        "open_snapshot": first,
        "close_snapshot": last,
    }
