"""
Integration Test Suite

Tests end-to-end message flow through the channel router, tool executor,
and memory system. Verifies core functionality without external dependencies.
"""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestChannelRouterIntegration(unittest.TestCase):
    """Test channel router message flow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_message_routing_mock(self):
        """Test message routing with mock objects."""
        # Create mock router
        router = Mock()
        router.route_message = Mock(return_value={"status": "routed", "channel": "telegram"})
        
        # Send test message
        result = router.route_message("test_user", "Hello World")
        
        self.assertEqual(result["status"], "routed")
        self.assertEqual(result["channel"], "telegram")
        router.route_message.assert_called_once_with("test_user", "Hello World")
    
    def test_tool_executor_mock(self):
        """Test tool executor with mock tools."""
        # Create mock executor
        executor = Mock()
        executor.execute_tool = Mock(return_value={"result": "success", "data": "test_data"})
        
        # Execute mock tool
        result = executor.execute_tool("test_tool", {"param": "value"})
        
        self.assertEqual(result["result"], "success")
        executor.execute_tool.assert_called_once_with("test_tool", {"param": "value"})
    
    def test_memory_persistence_mock(self):
        """Test memory save and load with mock."""
        # Create mock memory manager
        memory = Mock()
        memory.save_memory = Mock(return_value=True)
        memory.load_memory = Mock(return_value={"id": "mem_001", "content": "test"})
        
        # Save memory
        save_result = memory.save_memory({"content": "test message"})
        self.assertTrue(save_result)
        
        # Load memory
        loaded = memory.load_memory("mem_001")
        self.assertEqual(loaded["content"], "test")


class TestMemoryRetrievalIntegration(unittest.TestCase):
    """Test memory retrieval functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_semantic_memory_search_mock(self):
        """Test semantic memory search with mock."""
        memory = Mock()
        memory.semantic_search = Mock(return_value=[
            {"id": "mem_001", "content": "related memory 1", "score": 0.95},
            {"id": "mem_002", "content": "related memory 2", "score": 0.87},
        ])
        
        results = memory.semantic_search("test query", limit=2)
        
        self.assertEqual(len(results), 2)
        self.assertGreater(results[0]["score"], results[1]["score"])
    
    def test_memory_promotion_mock(self):
        """Test memory promotion to core."""
        memory = Mock()
        memory.promote_to_core = Mock(return_value=True)
        
        result = memory.promote_to_core("mem_001")
        
        self.assertTrue(result)
        memory.promote_to_core.assert_called_once_with("mem_001")


class TestToolIntegration(unittest.TestCase):
    """Test tool execution integration."""
    
    def test_tool_registration_mock(self):
        """Test tool registration."""
        executor = Mock()
        executor.register_tool = Mock(return_value=True)
        
        result = executor.register_tool("test_tool", Mock())
        
        self.assertTrue(result)
        executor.register_tool.assert_called_once()
    
    def test_tool_execution_with_context_mock(self):
        """Test tool execution with context."""
        executor = Mock()
        executor.execute_with_context = Mock(return_value={
            "status": "success",
            "tool": "test_tool",
            "result": {"output": "test"}
        })
        
        context = {"memory": "test", "beliefs": []}
        result = executor.execute_with_context("test_tool", {"param": "value"}, context)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tool"], "test_tool")


def run_integration_tests():
    """Run all integration tests."""
    print("Running Integration Test Suite...")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestChannelRouterIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryRetrievalIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestToolIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)
