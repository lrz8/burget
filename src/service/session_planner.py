import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from typing import Dict, List, Optional, Set


logger = logging.getLogger(__name__)


def resolve_session_type(now: Optional[datetime] = None) -> str:
    current = now or datetime.now()
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


def build_schedule_plan(target_date: Optional[date] = None) -> List[Dict[str, str]]:
    run_date = target_date or datetime.now().date()
    slots = [
        ("pre_open", dt_time(9, 0)),
        ("intraday", dt_time(9, 30)),
        ("intraday", dt_time(10, 0)),
        ("intraday", dt_time(10, 30)),
        ("intraday", dt_time(11, 0)),
        ("intraday", dt_time(13, 0)),
        ("intraday", dt_time(13, 30)),
        ("intraday", dt_time(14, 0)),
        ("intraday", dt_time(14, 30)),
        ("post_close", dt_time(15, 5)),
    ]
    plan: List[Dict[str, str]] = []
    for session_type, slot_time in slots:
        plan.append(
            {
                "session_type": session_type,
                "run_at": datetime.combine(run_date, slot_time).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return plan


@dataclass(frozen=True)
class SchedulerSlot:
    session_type: str
    run_at: datetime

    @property
    def key(self) -> str:
        return f"{self.session_type}@{self.run_at.strftime('%Y-%m-%d %H:%M')}"


class MonitorScheduler:
    """基于 A 股交易时段执行预设轮询。"""

    def __init__(self, service):
        self.service = service
        self.executed_slots: Set[str] = set()

    def planned_slots(self, target_date: Optional[date] = None) -> List[SchedulerSlot]:
        slots: List[SchedulerSlot] = []
        for item in build_schedule_plan(target_date):
            slots.append(
                SchedulerSlot(
                    session_type=item["session_type"],
                    run_at=datetime.strptime(item["run_at"], "%Y-%m-%d %H:%M:%S"),
                )
            )
        return slots

    def run_due_slots(
        self,
        now: Optional[datetime] = None,
        use_llm: bool = True,
        send_notification: bool = True,
        portfolio_df=None,
    ) -> List[Dict[str, object]]:
        current = now or datetime.now()
        due_results: List[Dict[str, object]] = []
        for slot in self.planned_slots(current.date()):
            if slot.key in self.executed_slots:
                continue
            if current >= slot.run_at:
                logger.info("触发计划任务: %s", slot.key)
                result = self.service.run(
                    portfolio_df=portfolio_df,
                    use_llm=use_llm,
                    send_notification=send_notification,
                    save_report=True,
                    session_type=slot.session_type,
                    now=current,
                )
                self.executed_slots.add(slot.key)
                due_results.append(result)
        return due_results

    def run_loop(
        self,
        check_interval_seconds: int = 60,
        max_cycles: Optional[int] = None,
        use_llm: bool = True,
        send_notification: bool = True,
        portfolio_df=None,
    ) -> None:
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            now = datetime.now()
            self.run_due_slots(
                now=now,
                use_llm=use_llm,
                send_notification=send_notification,
                portfolio_df=portfolio_df,
            )
            cycles += 1
            time.sleep(check_interval_seconds)
