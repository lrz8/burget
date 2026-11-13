import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.utils.runtime import save_markdown_report


class RuntimeTest(unittest.TestCase):
    def test_reports_use_shanghai_date_without_overwriting_same_time(self):
        previous_directory = Path.cwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                timestamp = datetime(2026, 3, 18, 18, tzinfo=timezone.utc)
                first = save_markdown_report("first", timestamp=timestamp)
                second = save_markdown_report("second", timestamp=timestamp)
                self.assertEqual(first.parent, Path("output/2026-03-19"))
                self.assertNotEqual(first, second)
                self.assertEqual(first.read_text(encoding="utf-8"), "first")
                self.assertEqual(second.read_text(encoding="utf-8"), "second")
            finally:
                os.chdir(previous_directory)


if __name__ == "__main__":
    unittest.main()
