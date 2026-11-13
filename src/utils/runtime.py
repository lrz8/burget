import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.utils.trading_time import market_now


def setup_logging(app_name: str = "app") -> Path:
    """初始化日志输出到 logs/YYYY-MM-DD 文件。"""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{app_name}_{market_now():%Y-%m-%d}.log"

    root_logger = logging.getLogger()
    if getattr(root_logger, "_burget_log_initialized", False):
        return log_path

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    root_logger._burget_log_initialized = True
    root_logger.info("日志系统初始化完成: %s", log_path)
    return log_path


def save_markdown_report(content: str, prefix: str = "report", timestamp: datetime | None = None) -> Path:
    """保存 Markdown 报告到 output/YYYY-MM-DD/ 目录。"""
    current = market_now(timestamp)
    report_dir = Path("output") / current.strftime("%Y-%m-%d")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{prefix}_{current:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.md"
    report_path.write_text(content, encoding="utf-8")
    logging.getLogger(__name__).info("报告已保存至: %s", report_path)
    return report_path


def mask_secret(value: str) -> str:
    """用于在日志中展示脱敏后的密钥。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
