import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Dict, List, Optional, Set

from src.utils.trading_time import market_now

logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _trading_dates(year: int) -> frozenset[date]:
    import akshare as ak

    frame = ak.tool_trade_date_hist_sina()
    dates = frozenset(date.fromisoformat(str(value)[:10]) for value in frame["trade_date"])
    if not dates or year > max(dates).year:
        raise ValueError("交易日历尚未覆盖目标年份，请更新数据源后重试。")
    return dates


def is_a_share_trading_day(target: date) -> bool:
    if target.weekday() >= 5:
        return False
    dates = _trading_dates(target.year)
    if target < min(dates) or target > max(dates):
        raise ValueError("交易日历未覆盖目标日期，暂停自动任务。")
    return target in dates


def resolve_session_type(
    now: Optional[datetime] = None,
    is_trading_day: Optional[Callable[[date], bool]] = None,
) -> str:
    current = market_now(now)
    if current.weekday() >= 5 or (is_trading_day is not None and not is_trading_day(current.date())):
        return "off_hours"
    current_time = current.time()
    if dt_time(8, 30) <= current_time < dt_time(9, 30):
        return "pre_open"
    if dt_time(9, 30) <= current_time < dt_time(11, 30):
        return "intraday"
    if dt_time(11, 30) <= current_time < dt_time(13, 0):
        return "midday_break"
    if dt_time(13, 0) <= current_time < dt_time(15, 0):
        return "intraday"
    if dt_time(15, 0) <= current_time < dt_time(17, 0):
        return "post_close"
    return "off_hours"


def build_schedule_plan(
    target_date: Optional[date] = None,
    is_trading_day: Optional[Callable[[date], bool]] = None,
) -> List[Dict[str, str]]:
    run_date = target_date or market_now().date()
    try:
        trading = (is_trading_day or is_a_share_trading_day)(run_date)
    except Exception:
        logger.exception("交易日历不可用，暂停自动任务；可手动生成观察报告。")
        return []
    if not trading:
        return []
    slots = [
        ("pre_open", dt_time(9, 0)),
        ("intraday", dt_time(9, 30)), ("intraday", dt_time(10, 0)),
        ("intraday", dt_time(10, 30)), ("intraday", dt_time(11, 0)),
        ("intraday", dt_time(13, 0)), ("intraday", dt_time(13, 30)),
        ("intraday", dt_time(14, 0)), ("intraday", dt_time(14, 30)),
        ("post_close", dt_time(15, 5)),
    ]
    return [
        {"session_type": session, "run_at": datetime.combine(run_date, at).strftime("%Y-%m-%d %H:%M:%S")}
        for session, at in slots
    ]


@dataclass(frozen=True)
class SchedulerSlot:
    session_type: str
    run_at: datetime

    @property
    def key(self) -> str:
        return f"{self.session_type}@{self.run_at:%Y-%m-%d %H:%M}"


class MonitorScheduler:
    """仅执行有效期内的最新任务，执行记录跨进程重启保留。"""

    def __init__(
        self, service, state_path: Optional[str] = "data/scheduler_state.json",
        is_trading_day: Optional[Callable[[date], bool]] = None,
        grace_period_seconds: int = 120,
    ):
        if grace_period_seconds <= 0:
            raise ValueError("任务有效期必须为正数。")
        self.service = service
        self.state_path = Path(state_path) if state_path is not None else None
        self.is_trading_day = is_trading_day or is_a_share_trading_day
        self.grace_period = timedelta(seconds=grace_period_seconds)
        self.executed_slots: Set[str] = set()
        if self.state_path is not None and self.state_path.exists():
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.executed_slots = set(data["executed_slots"])

    def planned_slots(self, target_date: Optional[date] = None) -> List[SchedulerSlot]:
        return [
            SchedulerSlot(item["session_type"], datetime.strptime(item["run_at"], "%Y-%m-%d %H:%M:%S"))
            for item in build_schedule_plan(target_date, self.is_trading_day)
        ]

    def _save_state(self, current: datetime) -> None:
        cutoff = (current.date() - timedelta(days=7)).isoformat()
        self.executed_slots = {key for key in self.executed_slots if key.split("@")[-1][:10] >= cutoff}
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", dir=self.state_path.parent, encoding="utf-8", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"executed_slots": sorted(self.executed_slots)}, handle, ensure_ascii=False)
            os.replace(temporary, self.state_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def run_due_slots(
        self, now: Optional[datetime] = None, use_llm: bool = True,
        send_notification: bool = True, portfolio_df=None,
    ) -> List[Dict[str, object]]:
        current = market_now(now)
        eligible = [
            slot for slot in self.planned_slots(current.date())
            if slot.key not in self.executed_slots
            and timedelta(0) <= current - slot.run_at <= self.grace_period
        ]
        if not eligible:
            return []
        slot = max(eligible, key=lambda item: item.run_at)
        logger.info("触发计划任务: %s", slot.key)
        result = self.service.run(
            portfolio_df=portfolio_df, use_llm=use_llm,
            send_notification=send_notification, save_report=True,
            session_type=slot.session_type, now=current,
        )
        self.executed_slots.add(slot.key)
        self._save_state(current)
        return [result]

    def run_loop(
        self, check_interval_seconds: int = 60, max_cycles: Optional[int] = None,
        use_llm: bool = True, send_notification: bool = True, portfolio_df=None,
    ) -> None:
        if check_interval_seconds <= 0:
            raise ValueError("轮询间隔必须为正数。")
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            self.run_due_slots(
                use_llm=use_llm, send_notification=send_notification, portfolio_df=portfolio_df,
            )
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(check_interval_seconds)
