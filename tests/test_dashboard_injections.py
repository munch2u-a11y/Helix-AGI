import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard.dashboard as dashboard_module
from core.preconscious import Preconscious


class DashboardInjectionTests(unittest.TestCase):
    def test_preconscious_writes_capped_injection_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                pre = Preconscious.__new__(Preconscious)
                pre.INJECTION_HISTORY_LIMIT = 2
                pre.sentinel = type(
                    "Sentinel",
                    (),
                    {
                        "omega": 0.61,
                        "s_total": 0.12,
                        "get_severity": lambda self: "stable",
                        "get_generation_params": lambda self: {"mode": "tonic"},
                    },
                )()
                pre.physics = type("Physics", (), {"_pulse_count": 0})()

                for pulse in range(1, 4):
                    pre.physics._pulse_count = pulse
                    pre._last_trigger_text = f"trigger {pulse}"
                    pre._last_concepts = [f"concept-{pulse}"]
                    pre._last_neighbors = [
                        {"content": f"memory-{pulse}", "relevance": 2.0 + pulse}
                    ]
                    pre._last_selected_beliefs = [
                        {
                            "content": f"belief-{pulse}",
                            "category": "premises",
                            "gravity": 3.0 + pulse,
                            "mass": 1.5 + pulse,
                        }
                    ]
                    pre._save_injection_state()

                latest_path = Path("data/spatial/spatial_injection.json")
                history_path = Path("data/spatial/spatial_injection_history.json")

                self.assertTrue(latest_path.exists())
                self.assertTrue(history_path.exists())

                latest = json.loads(latest_path.read_text())
                history = json.loads(history_path.read_text())

                self.assertEqual(latest["pulse"], 3)
                self.assertEqual(latest["trigger"], "trigger 3")
                self.assertEqual(len(history), 2)
                self.assertEqual([entry["pulse"] for entry in history], [2, 3])
            finally:
                os.chdir(cwd)

    def test_dashboard_history_endpoint_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "spatial_injection_history.json"
            history_path.write_text(json.dumps([
                {"pulse": 1, "timestamp": "10:00:00", "concepts": [], "memories": [], "beliefs": []},
                {"pulse": 2, "timestamp": "10:00:01", "concepts": [], "memories": [], "beliefs": []},
                {"pulse": 3, "timestamp": "10:00:02", "concepts": [], "memories": [], "beliefs": []},
            ]))

            class _DummyComms:
                def push_inbound(self, *args, **kwargs):
                    return None

                def get_outbound(self, since=0):
                    return []

                def get_outbound_count(self):
                    return 0

            with patch.object(dashboard_module, "SPATIAL_INJECTION_HISTORY_PATH", history_path), \
                 patch("dashboard.dashboard_comms.get_comms", return_value=_DummyComms()):
                app = dashboard_module.create_app()
                client = app.test_client()
                response = client.get("/api/spatial_injection_history?limit=2")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["total"], 3)
            self.assertEqual([entry["pulse"] for entry in data["entries"]], [3, 2])


if __name__ == "__main__":
    unittest.main()
