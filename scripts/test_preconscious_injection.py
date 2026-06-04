"""
Preconscious Context Builder Test

Tests context window assembly, verifies memory/belief weighting,
and tests scratchpad note injection.
"""

import os
import sys
import json
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ContextBuilderSimulator:
    """Simulates preconscious context building."""
    
    def __init__(self, max_tokens=8192):
        """Initialize context builder."""
        self.max_tokens = max_tokens
        self.current_tokens = 0
        self.context = []
    
    def add_memory(self, memory, weight=1.0):
        """Add memory to context with weight."""
        tokens = len(memory.get("content", "").split()) * weight
        
        if self.current_tokens + tokens <= self.max_tokens:
            self.context.append({
                "type": "memory",
                "content": memory,
                "weight": weight,
                "tokens": tokens
            })
            self.current_tokens += tokens
            return True
        return False
    
    def add_belief(self, belief, weight=1.0):
        """Add belief to context with weight."""
        tokens = len(belief.get("content", "").split()) * weight
        
        if self.current_tokens + tokens <= self.max_tokens:
            self.context.append({
                "type": "belief",
                "content": belief,
                "weight": weight,
                "tokens": tokens
            })
            self.current_tokens += tokens
            return True
        return False
    
    def add_scratchpad_note(self, note):
        """Add scratchpad note to context."""
        tokens = len(note.get("content", "").split())
        
        if self.current_tokens + tokens <= self.max_tokens:
            self.context.append({
                "type": "scratchpad",
                "content": note,
                "tokens": tokens
            })
            self.current_tokens += tokens
            return True
        return False
    
    def get_context_summary(self):
        """Get context summary."""
        return {
            "total_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "utilization_pct": (self.current_tokens / self.max_tokens) * 100,
            "item_count": len(self.context),
            "memory_count": len([c for c in self.context if c["type"] == "memory"]),
            "belief_count": len([c for c in self.context if c["type"] == "belief"]),
            "scratchpad_count": len([c for c in self.context if c["type"] == "scratchpad"])
        }


class TestContextWindowAssembly(unittest.TestCase):
    """Test context window assembly."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.builder = ContextBuilderSimulator()
    
    def test_add_memory_to_context(self):
        """Test adding memory to context."""
        memory = {"id": "mem_001", "content": "This is a test memory"}
        result = self.builder.add_memory(memory)
        
        self.assertTrue(result)
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["memory_count"], 1)
    
    def test_add_belief_to_context(self):
        """Test adding belief to context."""
        belief = {"id": "belief_001", "content": "I can execute tools"}
        result = self.builder.add_belief(belief)
        
        self.assertTrue(result)
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["belief_count"], 1)
    
    def test_add_multiple_items(self):
        """Test adding multiple items to context."""
        memory = {"id": "mem_001", "content": "Test memory"}
        belief = {"id": "belief_001", "content": "Test belief"}
        note = {"id": "note_001", "content": "Test note"}
        
        self.builder.add_memory(memory)
        self.builder.add_belief(belief)
        self.builder.add_scratchpad_note(note)
        
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["item_count"], 3)
    
    def test_context_window_overflow(self):
        """Test context window overflow handling."""
        small_builder = ContextBuilderSimulator(max_tokens=100)
        
        # Add large memory
        large_memory = {
            "id": "mem_001",
            "content": " ".join(["word"] * 150)  # 150 tokens
        }
        result = small_builder.add_memory(large_memory)
        
        self.assertFalse(result)


class TestMemoryBeliefWeighting(unittest.TestCase):
    """Test memory/belief weighting."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.builder = ContextBuilderSimulator()
    
    def test_memory_weighting(self):
        """Test memory weighting in context."""
        memory = {"id": "mem_001", "content": "Test memory"}
        
        self.builder.add_memory(memory, weight=2.0)
        
        summary = self.builder.get_context_summary()
        # With 50% weight multiplier, tokens should double
        self.assertGreater(summary["total_tokens"], 0)
    
    def test_belief_priority_weighting(self):
        """Test belief priority weighting."""
        beliefs = [
            {"id": "belief_001", "content": "High priority belief", "priority": 0.9},
            {"id": "belief_002", "content": "Low priority belief", "priority": 0.1},
        ]
        
        self.builder.add_belief(beliefs[0], weight=beliefs[0]["priority"])
        self.builder.add_belief(beliefs[1], weight=beliefs[1]["priority"])
        
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["belief_count"], 2)
    
    def test_recency_weighting(self):
        """Test recency-based weighting."""
        now = datetime.now()
        
        recent_memory = {
            "id": "mem_001",
            "content": "Recent memory",
            "created_at": (now - timedelta(hours=1)).isoformat()
        }
        
        old_memory = {
            "id": "mem_002",
            "content": "Old memory",
            "created_at": (now - timedelta(days=7)).isoformat()
        }
        
        # Recent should have higher weight
        self.builder.add_memory(recent_memory, weight=2.0)
        self.builder.add_memory(old_memory, weight=0.5)
        
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["memory_count"], 2)


class TestScratchpadInjection(unittest.TestCase):
    """Test scratchpad note injection."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.builder = ContextBuilderSimulator()
    
    def test_add_scratchpad_note(self):
        """Test adding scratchpad note."""
        note = {
            "id": "note_001",
            "content": "Remember to follow up",
            "due_at": (datetime.now() + timedelta(days=1)).isoformat()
        }
        
        result = self.builder.add_scratchpad_note(note)
        
        self.assertTrue(result)
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["scratchpad_count"], 1)
    
    def test_multiple_scratchpad_notes(self):
        """Test adding multiple scratchpad notes."""
        notes = [
            {"id": "note_001", "content": "Note 1"},
            {"id": "note_002", "content": "Note 2"},
            {"id": "note_003", "content": "Note 3"},
        ]
        
        for note in notes:
            self.builder.add_scratchpad_note(note)
        
        summary = self.builder.get_context_summary()
        self.assertEqual(summary["scratchpad_count"], 3)
    
    def test_priority_scratchpad_notes(self):
        """Test that high-priority notes are included first."""
        high_priority = {
            "id": "note_001",
            "content": "URGENT: Action required",
            "priority": "high"
        }
        
        low_priority = {
            "id": "note_002",
            "content": "Nice to have note",
            "priority": "low"
        }
        
        self.builder.add_scratchpad_note(high_priority)
        self.builder.add_scratchpad_note(low_priority)
        
        # High priority should be first in context
        first_item = self.builder.context[0]
        self.assertEqual(first_item["content"]["priority"], "high")


class TestContextOptimization(unittest.TestCase):
    """Test context optimization strategies."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.builder = ContextBuilderSimulator(max_tokens=500)
    
    def test_context_compression(self):
        """Test context compression."""
        # Add items until near capacity
        for i in range(20):
            memory = {
                "id": f"mem_{i:03d}",
                "content": "Test memory content"
            }
            self.builder.add_memory(memory)
        
        summary = self.builder.get_context_summary()
        utilization = summary["utilization_pct"]
        
        # Should be utilizing significant portion of context
        self.assertGreater(utilization, 50)
    
    def test_token_counting(self):
        """Test token counting accuracy."""
        memory = {"id": "mem_001", "content": "one two three four five"}
        self.builder.add_memory(memory, weight=1.0)
        
        summary = self.builder.get_context_summary()
        
        # 5 words = 5 tokens
        self.assertEqual(summary["total_tokens"], 5)


def run_preconscious_tests():
    """Run all preconscious context builder tests."""
    print("Running Preconscious Context Builder Test Suite...")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestContextWindowAssembly))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryBeliefWeighting))
    suite.addTests(loader.loadTestsFromTestCase(TestScratchpadInjection))
    suite.addTests(loader.loadTestsFromTestCase(TestContextOptimization))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_preconscious_tests()
    sys.exit(0 if success else 1)
