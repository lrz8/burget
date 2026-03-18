import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd


logger = logging.getLogger(__name__)

TRADE_FILE = "data/trades.csv"
TRADE_COLUMNS = [
    "timestamp",
    "symbol",
    "name",
    "side",
    "quantity",
    "price",
    "amount",
    "note",
]


def normalize_trade_log(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    normalized = df.copy()
    for column in TRADE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""

    normalized = normalized[TRADE_COLUMNS]
    normalized["timestamp"] = normalized["timestamp"].fillna("").astype(str).str.strip()
    normalized["symbol"] = normalized["symbol"].fillna("").astype(str).str.strip().str.zfill(6)
    normalized["name"] = normalized["name"].fillna("").astype(str).str.strip()
    normalized["side"] = normalized["side"].fillna("").astype(str).str.strip().str.lower()
    normalized["quantity"] = pd.to_numeric(normalized["quantity"], errors="coerce").fillna(0).astype(int)
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce").fillna(0.0)
    normalized["amount"] = pd.to_numeric(normalized["amount"], errors="coerce")
    normalized["amount"] = normalized["amount"].fillna(normalized["quantity"] * normalized["price"])
    normalized["note"] = normalized["note"].fillna("").astype(str).str.strip()

    normalized = normalized[
        (normalized["timestamp"] != "")
        & (normalized["symbol"] != "")
        & (normalized["side"].isin(["buy", "sell"]))
        & (normalized["quantity"] > 0)
    ].copy()
    normalized = normalized.sort_values("timestamp").reset_index(drop=True)
    return normalized


def load_trade_log(path: str = TRADE_FILE) -> pd.DataFrame:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = pd.DataFrame(columns=TRADE_COLUMNS)
        df.to_csv(path, index=False)
        return df

    try:
        return normalize_trade_log(pd.read_csv(path))
    except Exception as exc:
        logger.error("读取交易记录失败: %s", exc, exc_info=True)
        return pd.DataFrame(columns=TRADE_COLUMNS)


def save_trade_log(df: pd.DataFrame, path: str = TRADE_FILE) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        normalized = normalize_trade_log(df)
        normalized.to_csv(path, index=False)
        logger.info("交易记录已保存，共 %s 条。", len(normalized))
    except Exception as exc:
        logger.error("保存交易记录失败: %s", exc, exc_info=True)


def record_trade(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    name: str = "",
    note: str = "",
    timestamp: Optional[datetime] = None,
    path: str = TRADE_FILE,
) -> pd.DataFrame:
    trade_log = load_trade_log(path)
    trade_time = timestamp or datetime.now()
    new_row = pd.DataFrame(
        [
            {
                "timestamp": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": str(symbol).zfill(6),
                "name": name,
                "side": side.lower(),
                "quantity": int(quantity),
                "price": float(price),
                "amount": round(int(quantity) * float(price), 2),
                "note": note,
            }
        ]
    )
    updated = pd.concat([trade_log, new_row], ignore_index=True)
    save_trade_log(updated, path)
    return normalize_trade_log(updated)


def get_recent_trades(
    trade_log: pd.DataFrame,
    now: Optional[datetime] = None,
    lookback_days: int = 5,
) -> pd.DataFrame:
    normalized = normalize_trade_log(trade_log)
    if normalized.empty:
        return normalized

    current_time = now or datetime.now()
    cutoff = current_time - timedelta(days=lookback_days)
    timestamps = pd.to_datetime(normalized["timestamp"], errors="coerce")
    mask = timestamps >= cutoff
    recent = normalized.loc[mask].copy()
    return recent.sort_values("timestamp", ascending=False).reset_index(drop=True)


def summarize_recent_trades(trade_log: pd.DataFrame, limit: int = 5) -> List[Dict[str, str]]:
    recent = normalize_trade_log(trade_log)
    if recent.empty:
        return []

    summary: List[Dict[str, str]] = []
    for _, row in recent.sort_values("timestamp", ascending=False).head(limit).iterrows():
        summary.append(
            {
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "name": row["name"],
                "side": row["side"],
                "quantity": str(row["quantity"]),
                "price": f"{float(row['price']):.3f}",
                "note": row["note"],
            }
        )
    return summary


def build_trade_context(trade_log: pd.DataFrame) -> Dict[str, Dict[str, str]]:
    recent = normalize_trade_log(trade_log)
    context: Dict[str, Dict[str, str]] = {}
    if recent.empty:
        return context

    for _, row in recent.sort_values("timestamp", ascending=False).iterrows():
        symbol = row["symbol"]
        if symbol in context:
            continue
        context[symbol] = {
            "last_side": row["side"],
            "last_timestamp": row["timestamp"],
            "last_price": f"{float(row['price']):.3f}",
        }
    return context


def derive_position_book(trade_log: pd.DataFrame) -> pd.DataFrame:
    """根据交易记录推导当前持仓数量与均价，使用移动平均成本法。"""
    normalized = normalize_trade_log(trade_log)
    if normalized.empty:
        return pd.DataFrame(columns=["symbol", "name", "holdings", "buy_price"])

    positions: Dict[str, Dict[str, float | str]] = {}
    for _, row in normalized.sort_values("timestamp").iterrows():
        symbol = row["symbol"]
        side = row["side"]
        quantity = int(row["quantity"])
        price = float(row["price"])
        name = row["name"]

        position = positions.setdefault(
            symbol,
            {"symbol": symbol, "name": name, "holdings": 0, "buy_price": 0.0, "cost_amount": 0.0},
        )
        if name:
            position["name"] = name

        current_holdings = int(position["holdings"])
        current_cost = float(position["cost_amount"])

        if side == "buy":
            new_holdings = current_holdings + quantity
            new_cost = current_cost + quantity * price
            avg_cost = new_cost / new_holdings if new_holdings > 0 else 0.0
            position["holdings"] = new_holdings
            position["cost_amount"] = new_cost
            position["buy_price"] = round(avg_cost, 4)
            continue

        sell_quantity = min(quantity, current_holdings)
        avg_cost = current_cost / current_holdings if current_holdings > 0 else 0.0
        new_holdings = current_holdings - sell_quantity
        new_cost = max(current_cost - sell_quantity * avg_cost, 0.0)
        position["holdings"] = new_holdings
        position["cost_amount"] = new_cost
        position["buy_price"] = round(new_cost / new_holdings, 4) if new_holdings > 0 else 0.0

    rows = []
    for item in positions.values():
        if int(item["holdings"]) <= 0:
            continue
        rows.append(
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "holdings": int(item["holdings"]),
                "buy_price": float(item["buy_price"]),
            }
        )
    return pd.DataFrame(rows, columns=["symbol", "name", "holdings", "buy_price"])


def list_traded_symbols(trade_log: pd.DataFrame) -> List[str]:
    normalized = normalize_trade_log(trade_log)
    if normalized.empty:
        return []
    return sorted(normalized["symbol"].dropna().astype(str).str.zfill(6).unique().tolist())
