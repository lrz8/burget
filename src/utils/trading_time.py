"""All naive timestamps in persisted files represent Asia/Shanghai local time."""

from datetime import datetime
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def market_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(MARKET_TIMEZONE)
    if current.tzinfo is not None:
        current = current.astimezone(MARKET_TIMEZONE)
    return current.replace(tzinfo=None)
