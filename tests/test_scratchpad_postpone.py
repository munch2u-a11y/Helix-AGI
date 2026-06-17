"""
Unit tests for scratchpad note postponement (timed lock blockers)
"""

import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scratchpad import Scratchpad


class TestScratchpadPostpone(unittest.TestCase):
    """Test suite for scratchpad note postponement and reactivation logic."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.scratchpad = Scratchpad(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_postponed_note(self):
        """Verify adding a note with postpone_until sets [P] status and ignores it in queries."""
        future_time = (datetime.now() + timedelta(hours=1)).astimezone().isoformat(timespec="seconds")
        
        # Add a postponed note
        note_id = self.scratchpad.add_note(
            content="Water the plants",
            postpone_until=future_time
        )
        self.assertTrue(note_id.startswith("n"))
        
        # Read raw file and check formatting
        with open(self.scratchpad.filepath, "r") as f:
            content = f.read()
            
        self.assertIn(f"- [P] ({note_id}) Water the plants [postponed_until: {future_time}]", content)
        
        # Verify it is ignored by get_active_notes()
        active = self.scratchpad.get_active_notes()
        self.assertEqual(len(active), 0)
        
        # Verify it is not cleared by clear_completed or clear_all
        self.scratchpad.clear_completed()
        self.scratchpad.clear_all()
        
        with open(self.scratchpad.filepath, "r") as f:
            self.assertIn(note_id, f.read())

    def test_auto_reactivation_on_read(self):
        """Verify that expired postponed notes automatically activate back to [ ] status on read."""
        past_time = (datetime.now() - timedelta(minutes=5)).astimezone().isoformat(timespec="seconds")
        
        # Add a note postponed to a past timestamp
        note_id = self.scratchpad.add_note(
            content="Expired postponed task",
            postpone_until=past_time
        )
        
        # Calling get_active_notes() invokes _read() which internally runs _check_postponed
        active = self.scratchpad.get_active_notes()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], note_id)
        self.assertEqual(active[0]["content"], "Expired postponed task")
        
        # Verify the file on disk was rewritten to standard active format '- [ ]' without the postponed metadata
        with open(self.scratchpad.filepath, "r") as f:
            disk_content = f.read()
            
        self.assertIn(f"- [ ] ({note_id}) Expired postponed task", disk_content)
        self.assertNotIn("postponed_until", disk_content)

    def test_update_note_postpone_status(self):
        """Verify updating content, adding postpone lock, and clearing lock on an existing note."""
        # 1. Create a normal note
        note_id = self.scratchpad.add_note(content="Original note content")
        
        # 2. Add a postpone lock
        future_time = (datetime.now() + timedelta(hours=2)).astimezone().isoformat(timespec="seconds")
        updated = self.scratchpad.update_note(
            note_id=note_id,
            new_content="Updated note content",
            postpone_until=future_time
        )
        self.assertTrue(updated)
        
        # Verify it's locked on disk
        with open(self.scratchpad.filepath, "r") as f:
            disk_content = f.read()
        self.assertIn(f"- [P] ({note_id}) Updated note content [postponed_until: {future_time}]", disk_content)
        self.assertEqual(len(self.scratchpad.get_active_notes()), 0)
        
        # 3. Clear postpone lock
        cleared = self.scratchpad.update_note(
            note_id=note_id,
            new_content="Final clean content",
            postpone_until="clear"
        )
        self.assertTrue(cleared)
        
        # Verify it is active again
        active = self.scratchpad.get_active_notes()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["content"], "Final clean content")
        
        with open(self.scratchpad.filepath, "r") as f:
            disk_content = f.read()
        self.assertNotIn("postponed_until", disk_content)
        self.assertIn(f"- [ ] ({note_id}) Final clean content", disk_content)

    def test_remove_postponed_note(self):
        """Verify removing a postponed note by ID deletes it from disk."""
        future_time = (datetime.now() + timedelta(hours=1)).astimezone().isoformat(timespec="seconds")
        note_id = self.scratchpad.add_note(
            content="Temporary postponed task",
            postpone_until=future_time
        )
        
        # Remove it
        removed = self.scratchpad.remove_note(note_id)
        self.assertTrue(removed)
        
        # Verify it is gone from file
        with open(self.scratchpad.filepath, "r") as f:
            self.assertNotIn(note_id, f.read())


if __name__ == "__main__":
    unittest.main()
