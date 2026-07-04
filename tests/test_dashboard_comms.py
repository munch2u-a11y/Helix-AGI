import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.dashboard import _coerce_int
from dashboard.dashboard_comms import DashboardComms, _DEFAULT_PATH


class DashboardCommsTests(unittest.TestCase):
    def test_default_message_bus_path_is_absolute(self):
        self.assertTrue(_DEFAULT_PATH.is_absolute())
        self.assertEqual(_DEFAULT_PATH.name, "dashboard_messages.json")
        self.assertEqual(_DEFAULT_PATH.parent.name, "data")

    def test_outbound_cursor_survives_retention_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            comms = DashboardComms(path=Path(tmp) / "dashboard_messages.json")
            for idx in range(205):
                comms.push_outbound("browser", f"message-{idx}")

            messages = comms.get_outbound(200)

            self.assertEqual(comms.get_outbound_count(), 205)
            self.assertEqual(len(messages), 5)
            self.assertEqual(messages[0]["content"], "message-200")
            self.assertEqual(messages[-1]["content"], "message-204")

    def test_coerce_int_uses_default_and_bounds(self):
        self.assertEqual(_coerce_int("abc", default=7), 7)
        self.assertEqual(_coerce_int("-5", default=0, minimum=0), 0)
        self.assertEqual(_coerce_int("999", default=0, maximum=50), 50)


if __name__ == "__main__":
    unittest.main()
