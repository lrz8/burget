import akshare as ak
import logging
import time
from datetime import timedelta
from functools import lru_cache
from inspect import signature

from src.utils.trading_time import market_now
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def retry_akshare_call(func, *args, retries=3, delay=2, **kwargs):
    """带重试机制的 akshare 调用封装"""
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"调用 {func.__name__} 失败: {e}，将在 {delay} 秒后进行第 {attempt + 2} 次重试...")
                time.sleep(delay)
            else:
                logger.error(f"调用 {func.__name__} 最终失败: {e}")
                raise e

def _get_tx_symbol(symbol: str) -> str:
    """自动给代码加上 sh/sz 等前缀，适配腾讯接口"""
    if symbol.startswith(("92", "8", "4")):
        return f"bj{symbol}"
    if symbol.startswith(("6", "5", "9")):
        return f"sh{symbol}"
    elif symbol.startswith(("0", "3", "1")):
        return f"sz{symbol}"
    elif symbol.startswith(("8", "4")):
        return f"bj{symbol}"
    return symbol

def is_etf(symbol: str) -> bool:
    """根据代码判断是否是ETF基金"""
    return symbol.startswith(("159", "51", "56", "58"))

# 增加全局的 Name 缓存，避免每次循环都请求网络
_STOCK_NAME_CACHE = {}
_ETF_NAME_CACHE = {}

def get_symbol_name(symbol: str) -> str:
    """获取股票或 ETF 的名称"""
    global _STOCK_NAME_CACHE, _ETF_NAME_CACHE
    try:
        if is_etf(symbol):
            if not _ETF_NAME_CACHE:
                df = retry_akshare_call(ak.fund_name_em)
                _ETF_NAME_CACHE = dict(zip(df['基金代码'], df['基金简称']))
            return _ETF_NAME_CACHE.get(symbol, f"ETF_{symbol}")
        else:
            if not _STOCK_NAME_CACHE:
                df = retry_akshare_call(ak.stock_info_a_code_name)
                _STOCK_NAME_CACHE = dict(zip(df['code'], df['name']))
            return _STOCK_NAME_CACHE.get(symbol, f"代码_{symbol}")
    except Exception as e:
        logger.warning(f"获取名称缓存失败: {e}")
        return symbol

def _volume_fields(latest) -> Dict[str, Any]:
    # 旧版腾讯接口的 amount 实为成交量（手）；新版提供独立的 volume（股）和 amount（元）。
    if "volume" in latest:
        return {"成交量(股)": latest["volume"], "成交额(元)": latest.get("amount", "N/A")}
    return {"成交量(手)": latest.get("amount", "N/A")}


@lru_cache(maxsize=2)
def _get_market_summary(bucket: int) -> Dict[str, Any]:
    """获取 A 股主要指数行情（使用无反爬限制的 Tencent 接口）"""
    logger.info("开始获取大盘指数数据...")
    target_indices = {
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "创业板指": "sz399006",
        "科创50": "sh000688",
        "沪深300": "sh000300"
    }
    
    summary = {}
    for name, code in target_indices.items():
        try:
            df = retry_akshare_call(ak.stock_zh_index_daily_tx, symbol=code)
            if len(df) >= 2:
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                close = latest['close']
                prev_close = prev['close']
                change = close - prev_close
                pct_change = (change / prev_close) * 100
                
                summary[name] = {
                    "行情日期": str(latest["date"])[:10],
                    "数据周期": "daily",
                    "数据来源": "Tencent",
                    "最新价": round(close, 2),
                    "涨跌额": round(change, 2),
                    "涨跌幅(%)": round(pct_change, 2),
                    **_volume_fields(latest)
                }
        except Exception as e:
            logger.error(f"获取指数 {name} 数据失败: {e}")
            
    logger.info(f"成功获取 {len(summary)} 个主要指数行情。")
    return summary

def get_market_summary() -> Dict[str, Any]:
    return {
        name: info.copy()
        for name, info in _get_market_summary(int(time.monotonic() // 60)).items()
    }


import pandas as pd

@lru_cache(maxsize=128)
def _cached_stock_history(symbol: str, start_date: str, end_date: str, bucket: int) -> pd.DataFrame:
    kwargs = {"symbol": _get_tx_symbol(symbol), "start_date": start_date, "end_date": end_date}
    if "timeout" in signature(ak.stock_zh_a_hist_tx).parameters:
        kwargs["timeout"] = 10
    return retry_akshare_call(ak.stock_zh_a_hist_tx, **kwargs)


def _load_stock_history(symbol: str, days: int = 30) -> pd.DataFrame:
    current = market_now()
    return _cached_stock_history(
        symbol,
        (current.date() - timedelta(days=max(90, days * 2))).strftime("%Y%m%d"),
        current.strftime("%Y%m%d"),
        int(time.monotonic() // 60),
    ).copy()


def get_stock_data(portfolio_df: pd.DataFrame) -> Dict[str, Any]:
    """获取指定个股或ETF的最新行情，并结合持仓和买入价计算盈亏"""
    symbols = portfolio_df["symbol"].tolist()
    logger.info(f"开始获取个股/ETF行情，列表: {symbols}")
    stock_data = {}
    
    for _, row in portfolio_df.iterrows():
        symbol = row["symbol"]
        holding_count = row.get("holdings", 0)
        buy_price = row.get("buy_price", 0.0)
        
        try:
            df = _load_stock_history(symbol)
            if len(df) >= 2:
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                close = latest['close']
                prev_close = prev['close']
                change = close - prev_close
                pct_change = (change / prev_close) * 100
                
                # 计算持仓信息与盈亏
                holding_value = close * holding_count
                cost_value = buy_price * holding_count
                floating_pnl = holding_value - cost_value
                floating_pnl_pct = ((close - buy_price) / buy_price * 100) if buy_price > 0 else 0.0
                
                stock_data[symbol] = {
                    "名称": get_symbol_name(symbol),
                    "类型": "ETF" if is_etf(symbol) else "股票",
                    "行情日期": str(latest["date"])[:10],
                    "数据周期": "daily",
                    "数据来源": "Tencent",
                    "最新价": round(close, 3),
                    "涨跌幅(%)": round(pct_change, 2),
                    **_volume_fields(latest),
                    "持仓数量": holding_count,
                    "持仓成本价": buy_price,
                    "持仓市值(元)": round(holding_value, 2),
                    "浮动盈亏(元)": round(floating_pnl, 2),
                    "盈亏比例(%)": round(floating_pnl_pct, 2)
                }
        except Exception as e:
            logger.error(f"获取 {symbol} 行情失败: {e}")
            
    logger.info(f"成功获取 {len(stock_data)} 个标的数据。")
    return stock_data

def get_stock_history_kline(symbol: str, days: int = 30) -> pd.DataFrame:
    """获取用于绘制曲线的历史 K 线数据"""
    try:
        df = _load_stock_history(symbol, days)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            return df.tail(days).reset_index(drop=True)
    except Exception as e:
        logger.error(f"获取 {symbol} K线数据失败: {e}")
    return pd.DataFrame()

@lru_cache(maxsize=2)
def _get_market_money_flow(bucket: int) -> Dict[str, Any]:
    """获取大盘资金流向数据"""
    logger.info("开始获取市场资金流向数据...")
    try:
        flow_df = retry_akshare_call(ak.stock_market_fund_flow)
        if not flow_df.empty:
            latest_flow = flow_df.iloc[-1].to_dict()
            logger.info("成功获取市场资金流向数据。")
            return latest_flow
        else:
            return {}
    except Exception as e:
        logger.error(f"获取资金流向数据失败: {e}")
        return {}


def get_market_money_flow() -> Dict[str, Any]:
    return _get_market_money_flow(int(time.monotonic() // 60)).copy()
