import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_executor import ToolExecutor, ActionTag

class TestEmailReplyAll(unittest.TestCase):
    def setUp(self):
        self.executor = ToolExecutor()

    @patch("tools.google_email.email_reply")
    def test_fc_email_reply_all(self, mock_reply):
        mock_reply.return_value = "Reply sent to all"
        
        # Test function calling interface for email_reply_all
        args = {"message_id": "12345", "body": "Hello all"}
        res = self.executor.execute_function_call("email_reply_all", args)
        
        self.assertEqual(res, "Reply sent to all")
        mock_reply.assert_called_once_with(message_id="12345", body="Hello all", reply_all=True)

    @patch("tools.google_email.email_reply")
    def test_fc_email_reply_with_reply_all_param(self, mock_reply):
        mock_reply.return_value = "Reply sent"
        
        # Test function calling interface for email_reply with reply_all=True
        args = {"message_id": "12345", "body": "Hello all", "reply_all": True}
        res = self.executor.execute_function_call("email_reply", args)
        
        self.assertEqual(res, "Reply sent")
        mock_reply.assert_called_once_with(message_id="12345", body="Hello all", reply_all=True)

    @patch("tools.google_email.email_reply")
    def test_action_tag_email_reply_all(self, mock_reply):
        mock_reply.return_value = "Reply sent to all"
        
        # Test legacy tag parsing / execution
        tag = ActionTag(tag="EMAIL_REPLY_ALL", param="12345", content="Hello all")
        res = self.executor._exec_email(tag)
        
        self.assertEqual(res, "Reply sent to all")
        mock_reply.assert_called_once_with(message_id="12345", body="Hello all", reply_all=True)

if __name__ == "__main__":
    unittest.main()
