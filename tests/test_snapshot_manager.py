import unittest
from datetime import date

from src.data.snapshot_manager import summarize_daily_snapshots, summarize_snapshot_history


class SnapshotManagerTest(unittest.TestCase):
    @staticmethod
    def snapshot(timestamp, pnl, complete=True):
        return {"timestamp": timestamp, "session_type": "post_close",
                "totals": {"total_pnl": pnl, "valuation_complete": complete}, "positions": []}

    def test_closing_position_is_not_reported_as_account_loss(self):
        snapshots = [
            self.snapshot("2026-03-18 10:00:00", 1000),
            self.snapshot("2026-03-18 15:10:00", 0),
        ]
        result = summarize_daily_snapshots(snapshots, date(2026, 3, 18))
        self.assertEqual(result["pnl_change"], -1000)
        self.assertIn("浮动盈亏", result["summary"])
        self.assertIn("不代表当日账户收益", result["summary"])

    def test_incomplete_or_legacy_valuation_has_no_pnl_delta(self):
        previous = self.snapshot("2026-03-18 10:00:00", 1000)
        current = self.snapshot("2026-03-18 15:10:00", 0, complete=False)
        daily = summarize_daily_snapshots([previous, current], date(2026, 3, 18))
        self.assertIsNone(daily["pnl_change"])
        history = summarize_snapshot_history([previous], {"totals": current["totals"], "positions": []})
        self.assertIsNone(history["pnl_delta"])
        self.assertIn("暂停计算", history["summary"])


if __name__ == "__main__":
    unittest.main()
