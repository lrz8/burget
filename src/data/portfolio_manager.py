import pandas as pd
import os
import logging

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = "data/portfolio.csv"
REQUIRED_COLUMNS = ["symbol", "name", "holdings", "buy_price"]


def normalize_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    """统一持仓表结构并清理无效行。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    normalized = df.copy()
    for column in REQUIRED_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""

    normalized = normalized[REQUIRED_COLUMNS]
    normalized["symbol"] = normalized["symbol"].fillna("").astype(str).str.strip()
    normalized["name"] = normalized["name"].fillna("").astype(str).str.strip()
    normalized["holdings"] = pd.to_numeric(normalized["holdings"], errors="coerce").fillna(0).astype(int)
    normalized["buy_price"] = pd.to_numeric(normalized["buy_price"], errors="coerce").fillna(0.0)

    normalized = normalized[normalized["symbol"] != ""].copy()
    normalized["symbol"] = normalized["symbol"].str.zfill(6)
    normalized = normalized.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)
    return normalized

def load_portfolio(path: str = PORTFOLIO_FILE) -> pd.DataFrame:
    """从 CSV 加载持仓和买入价信息"""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        # 初始化一个空 DataFrame
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        df.to_csv(path, index=False)
        return df
    
    try:
        df = pd.read_csv(path, dtype={"symbol": str})
        return normalize_portfolio(df)
    except Exception as e:
        logger.error(f"读取持仓文件失败: {e}", exc_info=True)
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

def save_portfolio(df: pd.DataFrame):
    """保存修改后的持仓信息到 CSV"""
    try:
        os.makedirs(os.path.dirname(PORTFOLIO_FILE), exist_ok=True)
        normalized = normalize_portfolio(df)
        normalized.to_csv(PORTFOLIO_FILE, index=False)
        logger.info("持仓配置已更新保存。")
    except Exception as e:
        logger.error(f"保存持仓文件失败: {e}", exc_info=True)


def merge_portfolio_with_trade_book(
    portfolio_df: pd.DataFrame,
    trade_book_df: pd.DataFrame,
    traded_symbols: list[str] | None = None,
) -> pd.DataFrame:
    """以交易推导出的持仓覆盖同代码的手工持仓，并补入仅存在于交易账本中的标的。"""
    base = normalize_portfolio(portfolio_df)
    if trade_book_df is None or trade_book_df.empty:
        if traded_symbols:
            base = base[~base["symbol"].isin(traded_symbols)].reset_index(drop=True)
        return base

    trade_book = normalize_portfolio(trade_book_df)
    base_map = {row["symbol"]: row.to_dict() for _, row in base.iterrows()}

    if traded_symbols:
        for symbol in traded_symbols:
            base_map.pop(symbol, None)

    for _, row in trade_book.iterrows():
        base_map[row["symbol"]] = {
            "symbol": row["symbol"],
            "name": row["name"] or base_map.get(row["symbol"], {}).get("name", ""),
            "holdings": int(row["holdings"]),
            "buy_price": float(row["buy_price"]),
        }

    merged = pd.DataFrame(base_map.values(), columns=REQUIRED_COLUMNS)
    return normalize_portfolio(merged)
