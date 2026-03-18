import unittest
from datetime import datetime

from src.service.session_planner import MonitorScheduler, build_schedule_plan, resolve_session_type


class DummyService:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {"session_type": kwargs["session_type"], "report_path": None}


class SessionPlannerTest(unittest.TestCase):
    def test_resolve_session_type(self):
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 9, 0, 0)), "pre_open")
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 10, 0, 0)), "intraday")
        self.assertEqual(resolve_session_type(datetime(2026, 3, 18, 15, 10, 0)), "post_close")

    def test_scheduler_runs_due_slots_once(self):
        service = DummyService()
        scheduler = MonitorScheduler(service)
        results = scheduler.run_due_slots(
            now=datetime(2026, 3, 18, 10, 5, 0),
            use_llm=False,
            send_notification=False,
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(service.calls[0]["session_type"], "pre_open")
        self.assertEqual(service.calls[-1]["session_type"], "intraday")
        self.assertEqual(len(build_schedule_plan()), 10)


if __name__ == "__main__":
    unittest.main()
