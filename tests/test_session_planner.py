import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.service.session_planner import MonitorScheduler, build_schedule_plan, resolve_session_type


class DummyService:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {"session_type": kwargs["session_type"]}


class SessionPlannerTest(unittest.TestCase):
    @staticmethod
    def weekday(target):
        return target.weekday() < 5

    def scheduler(self, service, **kwargs):
        return MonitorScheduler(service, is_trading_day=self.weekday, state_path=None, **kwargs)

    def test_session_resolves_using_shanghai_time_and_skips_weekends(self):
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 1, tzinfo=timezone.utc)), "pre_open")
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 10)), "intraday")
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 12)), "midday_break")
        self.assertEqual(resolve_session_type(datetime(2026, 3, 21, 10)), "off_hours")

    def test_late_start_does_not_replay_missed_slots(self):
        service = DummyService()
        scheduler = self.scheduler(service)
        self.assertEqual(scheduler.run_due_slots(now=datetime(2026, 3, 18, 15, 10)), [])
        self.assertEqual(service.calls, [])

    def test_only_current_slot_runs_once(self):
        service = DummyService()
        scheduler = self.scheduler(service)
        now = datetime(2026, 3, 18, 10, 1)
        self.assertEqual(len(scheduler.run_due_slots(now=now)), 1)
        self.assertEqual(service.calls[0]["session_type"], "intraday")
        self.assertEqual(scheduler.run_due_slots(now=now), [])

    def test_lunch_weekends_and_exchange_holidays_have_no_tasks(self):
        service = DummyService()
        self.assertEqual(self.scheduler(service).run_due_slots(now=datetime(2026, 3, 18, 12)), [])
        self.assertEqual(build_schedule_plan(date(2026, 3, 21), self.weekday), [])
        self.assertEqual(build_schedule_plan(date(2026, 10, 1), lambda _: False), [])
        self.assertEqual(len(build_schedule_plan(date(2026, 3, 18), self.weekday)), 10)

    def test_calendar_failure_does_not_fall_back_to_weekdays(self):
        with patch("src.service.session_planner.is_a_share_trading_day", side_effect=RuntimeError("offline")):
            self.assertEqual(build_schedule_plan(date(2026, 3, 18)), [])

    def test_executed_slot_survives_scheduler_restart(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.json")
            now = datetime(2026, 3, 18, 15, 5, 30)
            service = DummyService()
            first = MonitorScheduler(service, state_path=path, is_trading_day=self.weekday)
            self.assertEqual(len(first.run_due_slots(now=now)), 1)
            restarted = MonitorScheduler(service, state_path=path, is_trading_day=self.weekday)
            self.assertEqual(restarted.run_due_slots(now=now), [])
            self.assertEqual(len(service.calls), 1)


if __name__ == "__main__":
    unittest.main()
