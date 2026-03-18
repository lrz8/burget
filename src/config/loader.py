import logging
import os
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

from src.utils.runtime import mask_secret

logger = logging.getLogger(__name__)

def load_config(config_path: str = "config/cfg.yml") -> Dict[str, Any]:
    """读取并解析配置文件，支持格式自适应与容错"""
    load_dotenv()
    if not os.path.exists(config_path):
        logger.warning(f"未找到配置文件 {config_path}，将使用默认配置或环境变量。")
        config_data: Dict[str, Any] = {}
        _apply_env_overrides(config_data)
        _normalize_config(config_data)
        return config_data

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
            
        if not isinstance(config_data, dict):
            # 如果解析结果不是字典，可能是纯粹的 key=value 没被正确解析，尝试退化为读取 env 格式
            logger.warning(f"文件 {config_path} 似乎不是标准 YAML 格式，尝试退化解析。")
            config_data = _fallback_env_parse(config_path)
            
        # 针对 symbols 参数进行专门处理（处理中文逗号等不规范输入）
        if "monitor" in config_data:
            monitor_cfg = config_data["monitor"]
            if "symbols" in monitor_cfg:
                raw_symbols = monitor_cfg["symbols"]
                if isinstance(raw_symbols, str):
                    normalized = raw_symbols.replace("，", ",").replace("；", ",").replace(";", ",")
                    symbol_list = [s.strip() for s in normalized.split(",") if s.strip()]
                    monitor_cfg["symbols"] = symbol_list
            
            # 处理持仓数据 (如果有)
            if "holdings" in monitor_cfg and "symbols" in monitor_cfg:
                raw_holdings = monitor_cfg["holdings"]
                if isinstance(raw_holdings, str):
                    normalized_holdings = raw_holdings.replace("，", ",").replace("；", ",").replace(";", ",")
                    holding_list = [h.strip() for h in normalized_holdings.split(",") if h.strip()]
                    
                    # 组装成 symbol -> holding 的映射字典
                    symbol_holdings = {}
                    symbols = monitor_cfg["symbols"]
                    for idx, sym in enumerate(symbols):
                        if idx < len(holding_list):
                            try:
                                symbol_holdings[sym] = float(holding_list[idx])
                            except ValueError:
                                symbol_holdings[sym] = 0.0
                        else:
                            symbol_holdings[sym] = 0.0
                    monitor_cfg["holdings_dict"] = symbol_holdings
                
        _apply_env_overrides(config_data)
        _normalize_config(config_data)
        return config_data
        
    except Exception as e:
        logger.error(f"解析配置文件 {config_path} 失败: {e}", exc_info=True)
        config_data = {}
        _apply_env_overrides(config_data)
        _normalize_config(config_data)
        return config_data

def _fallback_env_parse(config_path: str) -> Dict[str, Any]:
    """当 YAML 解析失败，尝试把文件当成类似 .env 的键值对解析（向下兼容旧的输入习惯）"""
    fallback_config = {"llm": {}, "monitor": {}, "notifier": {}}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'").strip('"')
                    
                    if "API_KEY" in key:
                        fallback_config["llm"]["api_key"] = val
                    elif "BASE_URL" in key:
                        fallback_config["llm"]["base_url"] = val
                    elif "SYMBOLS" in key:
                        fallback_config["monitor"]["symbols"] = val
        return fallback_config
    except Exception as inner_e:
        logger.error(f"降级解析配置文件同样失败: {inner_e}")
        return {}


def _apply_env_overrides(config_data: Dict[str, Any]) -> None:
    """允许用环境变量覆盖敏感配置。"""
    config_data.setdefault("llm", {})
    config_data.setdefault("monitor", {})
    config_data.setdefault("notifier", {})

    llm_config = config_data["llm"]
    monitor_config = config_data["monitor"]
    notifier_config = config_data["notifier"]

    llm_config["api_key"] = os.getenv("LLM_API_KEY", llm_config.get("api_key", ""))
    llm_config["base_url"] = os.getenv("LLM_BASE_URL", llm_config.get("base_url", "https://api.openai.com/v1"))
    llm_config["model"] = os.getenv("LLM_MODEL", llm_config.get("model", "gpt-4o-mini"))

    monitor_symbols = os.getenv("MONITOR_SYMBOLS")
    if monitor_symbols:
        monitor_config["symbols"] = monitor_symbols
    monitor_holdings = os.getenv("MONITOR_HOLDINGS")
    if monitor_holdings:
        monitor_config["holdings"] = monitor_holdings

    notifier_config["serverchan_sendkey"] = os.getenv(
        "SERVERCHAN_SENDKEY", notifier_config.get("serverchan_sendkey", "")
    )
    notifier_config["feishu_webhook_url"] = os.getenv(
        "FEISHU_WEBHOOK_URL", notifier_config.get("feishu_webhook_url", "")
    )

    logger.info(
        "配置加载完成: llm.model=%s, llm.base_url=%s, llm.api_key=%s",
        llm_config["model"],
        llm_config["base_url"],
        mask_secret(llm_config["api_key"]),
    )


def _normalize_config(config_data: Dict[str, Any]) -> None:
    """统一配置结构，避免调用方反复兜底。"""
    config_data.setdefault("llm", {})
    config_data.setdefault("monitor", {})
    config_data.setdefault("notifier", {})
