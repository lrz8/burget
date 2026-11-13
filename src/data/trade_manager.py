import logging
import os
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from src.utils.trading_time import market_now


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

    required = {"timestamp", "symbol", "side", "quantity", "price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"交易记录缺少字段: {', '.join(sorted(missing))}")
    normalized = df.copy()
    for column in TRADE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[TRADE_COLUMNS]
    raw_symbols = normalized["symbol"].fillna("").astype(str).str.strip()
    normalized["symbol"] = raw_symbols.str.zfill(6)
    normalized["side"] = normalized["side"].fillna("").astype(str).str.strip().str.lower()
    timestamps = pd.to_datetime(normalized["timestamp"], errors="coerce", format="mixed")
    quantities = pd.to_numeric(normalized["quantity"], errors="coerce")
    prices = pd.to_numeric(normalized["price"], errors="coerce")
    valid = (
        raw_symbols.str.fullmatch(r"\d{1,6}")
        & normalized["side"].isin(["buy", "sell"])
        & timestamps.notna()
        & quantities.map(lambda value: math.isfinite(value) and value > 0 and value == int(value))
        & prices.map(lambda value: math.isfinite(value) and value > 0)
    )
    if not valid.all():
        raise ValueError(f"交易记录包含无效代码、时间、方向、数量或价格，行号: {list(normalized.index[~valid])}")
    normalized["timestamp"] = timestamps.map(
        lambda value: market_now(value.to_pydatetime()).strftime("%Y-%m-%d %H:%M:%S")
    )
    normalized["quantity"] = quantities.astype(int)
    normalized["price"] = prices.astype(float)
    normalized["amount"] = normalized["quantity"] * normalized["price"]
    for column in ("name", "note"):
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    return normalized.sort_values("timestamp", kind="stable").reset_index(drop=True)


def load_trade_log(path: str = TRADE_FILE) -> pd.DataFrame:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        df = pd.DataFrame(columns=TRADE_COLUMNS)
        df.to_csv(path, index=False)
        return df

    try:
        return normalize_trade_log(pd.read_csv(path, dtype={"symbol": str}))
    except Exception as exc:
        logger.error("读取交易记录失败: %s", exc, exc_info=True)
        raise


def save_trade_log(df: pd.DataFrame, path: str = TRADE_FILE) -> None:
    normalized = normalize_trade_log(df)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", dir=target.parent, encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            normalized.to_csv(handle, index=False)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    logger.info("交易记录已保存，共 %s 条。", len(normalized))


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
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("成交数量必须为正整数。")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("成交价格必须为有限正数。")
    raw_symbol = str(symbol).strip()
    if not raw_symbol.isascii() or not raw_symbol.isdigit() or len(raw_symbol) > 6:
        raise ValueError("交易代码必须为不超过六位的数字。")
    trade_log = load_trade_log(path)
    trade_time = market_now(timestamp)
    new_row = pd.DataFrame(
        [
            {
                "timestamp": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": raw_symbol.zfill(6),
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

    current_time = market_now(now)
    cutoff = current_time - timedelta(days=lookback_days)
    timestamps = pd.to_datetime(normalized["timestamp"], errors="coerce")
    mask = (timestamps >= cutoff) & (timestamps <= current_time)
    recent = normalized.loc[mask].copy()
    return recent.sort_values("timestamp", ascending=False).reset_index(drop=True)


def summarize_recent_trades(trade_log: pd.DataFrame, limit: Optional[int] = 5) -> List[Dict[str, str]]:
    recent = normalize_trade_log(trade_log)
    if recent.empty:
        return []

    summary: List[Dict[str, str]] = []
    ordered = recent.sort_values("timestamp", ascending=False, kind="stable")
    if limit is not None:
        ordered = ordered.head(limit)
    for _, row in ordered.iterrows():
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


def derive_position_book(
    trade_log: pd.DataFrame,
    opening_positions: Optional[pd.DataFrame] = None,
    as_of: Optional[datetime] = None,
) -> pd.DataFrame:
    """从完整交易历史或明确的期初持仓推导仓位；不静默忽略超额卖出。"""
    normalized = normalize_trade_log(trade_log)
    if as_of is not None:
        normalized = normalized[pd.to_datetime(normalized["timestamp"]) <= market_now(as_of)]
    positions: Dict[str, Dict[str, float | str]] = {}
    if opening_positions is not None:
        from src.data.portfolio_manager import normalize_portfolio

        for row in normalize_portfolio(opening_positions).to_dict("records"):
            quantity = int(row["holdings"])
            price = float(row["buy_price"])
            if quantity < 0 or not math.isfinite(price) or price < 0 or (quantity > 0 and price <= 0):
                raise ValueError(f"{row['symbol']} 的期初持仓或成本无效。")
            positions[row["symbol"]] = {
                **row, "cost_amount": quantity * price,
            }
    for _, row in normalized.iterrows():
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

        if quantity > current_holdings:
            raise ValueError(
                f"{symbol} 卖出 {quantity} 股超过可记账持仓 {current_holdings} 股；"
                "请补齐期初持仓或完整交易记录。"
            )
        sell_quantity = quantity
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
