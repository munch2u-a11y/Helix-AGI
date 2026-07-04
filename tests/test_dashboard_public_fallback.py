import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard.dashboard as dashboard_module


class DashboardPublicFallbackTests(unittest.TestCase):
    def test_read_spatial_falls_back_without_numpy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            belief_state = tmp_path / "belief_space_state.json"
            memory_state = tmp_path / "memory_space_state.json"
            beliefs_dir = tmp_path / "beliefs"
            beliefs_dir.mkdir()

            belief_state.write_text(json.dumps({
                "belief-1": {
                    "position": [1.25, 2.5, 3.75, 4.0],
                    "type": "belief",
                    "content": "Belief content",
                    "confidence": 0.8,
                }
            }))
            memory_state.write_text(json.dumps({
                "memory-1": {
                    "position": [-1.0, -2.0, -3.0, -4.0],
                    "content": "Memory content",
                    "importance": 0.4,
                }
            }))
            (beliefs_dir / "knowledge.json").write_text(json.dumps([
                {"id": "belief-1"}
            ]))

            with patch.object(dashboard_module, "NUMPY_AVAILABLE", False), \
                 patch.object(dashboard_module, "BELIEF_STATE", belief_state), \
                 patch.object(dashboard_module, "MEMORY_STATE", memory_state), \
                 patch.object(dashboard_module, "BELIEFS_DIR", beliefs_dir):
                payload = dashboard_module.read_spatial()

            self.assertEqual(payload["point_count"], 2)
            self.assertEqual(payload["points"][0]["id"], "belief-1")
            self.assertEqual(payload["points"][0]["x"], 1.25)
            self.assertEqual(payload["points"][0]["y"], 2.5)
            self.assertEqual(payload["points"][0]["z"], 3.75)
            self.assertEqual(payload["points"][0]["category"], "knowledge")
            self.assertEqual(payload["points"][1]["id"], "memory-1")
            self.assertEqual(payload["points"][1]["x"], -1.0)
            self.assertEqual(payload["points"][1]["y"], -2.0)
            self.assertEqual(payload["points"][1]["z"], -3.0)


if __name__ == "__main__":
    unittest.main()
