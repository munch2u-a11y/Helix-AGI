"""
Load Test Script

Simulates high-volume message handling, tests context window saturation,
and measures tool execution latency.
"""

import os
import sys
import time
import random
import threading
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LoadTestSimulator:
    """Simulates high-volume message handling."""
    
    def __init__(self, max_concurrent=10, context_window_size=8192):
        """Initialize load test simulator."""
        self.max_concurrent = max_concurrent
        self.context_window_size = context_window_size
        self.active_contexts = 0
        self.completed_messages = 0
        self.failed_messages = 0
        self.latencies = []
        self.context_saturations = []
        self.start_time = time.time()
    
    def process_message(self, message, simulated_delay=0.01):
        """Process a message with simulated delay."""
        process_start = time.time()
        
        # Simulate concurrent limit
        while self.active_contexts >= self.max_concurrent:
            time.sleep(0.001)
        
        self.active_contexts += 1
        
        try:
            # Simulate processing
            time.sleep(simulated_delay + random.uniform(-0.005, 0.005))
            
            latency = time.time() - process_start
            self.latencies.append(latency)
            self.completed_messages += 1
            
            return {
                "status": "success",
                "latency_ms": latency * 1000,
                "message_id": message.get("id")
            }
        except Exception as e:
            self.failed_messages += 1
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            self.active_contexts -= 1
    
    def get_stats(self):
        """Get load test statistics."""
        if not self.latencies:
            return {}
        
        elapsed = time.time() - self.start_time
        
        sorted_latencies = sorted(self.latencies)
        
        return {
            "elapsed_seconds": elapsed,
            "completed_messages": self.completed_messages,
            "failed_messages": self.failed_messages,
            "messages_per_second": self.completed_messages / elapsed if elapsed > 0 else 0,
            "avg_latency_ms": (sum(self.latencies) / len(self.latencies)) * 1000,
            "min_latency_ms": min(self.latencies) * 1000,
            "max_latency_ms": max(self.latencies) * 1000,
            "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2] * 1000,
            "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)] * 1000,
            "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)] * 1000,
            "total_errors": self.failed_messages,
            "error_rate_pct": (self.failed_messages / (self.completed_messages + self.failed_messages)) * 100
        }


class ContextSaturationSimulator:
    """Simulates context window saturation."""
    
    def __init__(self, max_tokens=8192):
        """Initialize context saturation simulator."""
        self.max_tokens = max_tokens
        self.current_tokens = 0
        self.saturation_events = []
    
    def add_to_context(self, item_tokens):
        """Add item to context, tracking saturation."""
        if self.current_tokens + item_tokens > self.max_tokens:
            # Need to compress or drop content
            saturation_pct = (self.current_tokens / self.max_tokens) * 100
            self.saturation_events.append({
                "timestamp": datetime.now().isoformat(),
                "saturation_pct": saturation_pct,
                "tokens_needed": item_tokens,
                "tokens_available": self.max_tokens - self.current_tokens
            })
            
            # Simulate compression (reduce by 30%)
            self.current_tokens = int(self.current_tokens * 0.7)
        
        self.current_tokens += item_tokens
        
        return {
            "added": True,
            "current_saturation_pct": (self.current_tokens / self.max_tokens) * 100
        }
    
    def get_saturation_stats(self):
        """Get saturation statistics."""
        if not self.saturation_events:
            return {"total_saturations": 0}
        
        return {
            "total_saturations": len(self.saturation_events),
            "avg_saturation_pct": sum(e["saturation_pct"] for e in self.saturation_events) / len(self.saturation_events),
            "max_saturation_pct": max(e["saturation_pct"] for e in self.saturation_events)
        }


class ToolLatencySimulator:
    """Simulates tool execution latency measurement."""
    
    def __init__(self):
        """Initialize tool latency simulator."""
        self.tool_executions = defaultdict(list)
        self.start_time = time.time()
    
    def execute_tool(self, tool_name, params=None):
        """Execute tool and measure latency."""
        execution_start = time.time()
        
        # Simulate tool execution with variable latency
        base_latency = {
            "browser": 0.05,
            "calculator": 0.01,
            "memory_search": 0.02,
            "api_call": 0.1,
            "file_io": 0.03
        }
        
        latency = base_latency.get(tool_name, 0.02)
        jitter = random.uniform(-0.01, 0.02)
        
        time.sleep(latency + jitter)
        
        execution_time = time.time() - execution_start
        self.tool_executions[tool_name].append(execution_time)
        
        return {
            "tool": tool_name,
            "status": "success",
            "latency_ms": execution_time * 1000
        }
    
    def get_tool_stats(self):
        """Get tool execution statistics."""
        stats = {}
        
        for tool_name, latencies in self.tool_executions.items():
            sorted_latencies = sorted(latencies)
            
            stats[tool_name] = {
                "calls": len(latencies),
                "avg_latency_ms": (sum(latencies) / len(latencies)) * 1000,
                "min_latency_ms": min(latencies) * 1000,
                "max_latency_ms": max(latencies) * 1000,
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)] * 1000
            }
        
        return stats


def load_test_message_handling():
    """Load test message handling."""
    print("\n" + "=" * 70)
    print("LOAD TEST: MESSAGE HANDLING")
    print("=" * 70)
    
    simulator = LoadTestSimulator(max_concurrent=5)
    
    print("\n[1] Processing 1000 messages with 5 concurrent limit...")
    
    for i in range(1000):
        message = {
            "id": f"msg_{i:04d}",
            "content": "Test message"
        }
        result = simulator.process_message(message, simulated_delay=0.01)
        
        if (i + 1) % 250 == 0:
            print(f"  Processed {i + 1} messages")
    
    stats = simulator.get_stats()
    
    print("\n[2] Message Handling Statistics:")
    print(f"  Completed: {stats['completed_messages']}")
    print(f"  Failed: {stats['failed_messages']}")
    print(f"  Throughput: {stats['messages_per_second']:.1f} msg/sec")
    print(f"  Avg latency: {stats['avg_latency_ms']:.2f}ms")
    print(f"  Min latency: {stats['min_latency_ms']:.2f}ms")
    print(f"  Max latency: {stats['max_latency_ms']:.2f}ms")
    print(f"  P95 latency: {stats['p95_latency_ms']:.2f}ms")
    print(f"  P99 latency: {stats['p99_latency_ms']:.2f}ms")
    print(f"  Error rate: {stats['error_rate_pct']:.2f}%")


def load_test_context_saturation():
    """Load test context window saturation."""
    print("\n" + "=" * 70)
    print("LOAD TEST: CONTEXT WINDOW SATURATION")
    print("=" * 70)
    
    simulator = ContextSaturationSimulator(max_tokens=8192)
    
    print("\n[1] Adding items until saturation...")
    
    items_added = 0
    for i in range(500):
        item_tokens = random.randint(50, 200)
        result = simulator.add_to_context(item_tokens)
        items_added += 1
        
        if (i + 1) % 100 == 0:
            saturation = (simulator.current_tokens / simulator.max_tokens) * 100
            print(f"  Items {i + 1}: Saturation {saturation:.1f}%")
    
    stats = simulator.get_saturation_stats()
    
    print("\n[2] Saturation Statistics:")
    print(f"  Total saturation events: {stats['total_saturations']}")
    if stats['total_saturations'] > 0:
        print(f"  Avg saturation level: {stats['avg_saturation_pct']:.1f}%")
        print(f"  Max saturation level: {stats['max_saturation_pct']:.1f}%")
    print(f"  Items processed: {items_added}")


def load_test_tool_latency():
    """Load test tool execution latency."""
    print("\n" + "=" * 70)
    print("LOAD TEST: TOOL EXECUTION LATENCY")
    print("=" * 70)
    
    simulator = ToolLatencySimulator()
    
    print("\n[1] Executing tools under load...")
    
    tools = ["browser", "calculator", "memory_search", "api_call", "file_io"]
    
    # Execute each tool multiple times
    for _ in range(10):
        for tool in tools:
            simulator.execute_tool(tool)
    
    print(f"  Completed {sum(len(v) for v in simulator.tool_executions.values())} total tool executions")
    
    stats = simulator.get_tool_stats()
    
    print("\n[2] Tool Execution Statistics:")
    for tool_name, tool_stats in sorted(stats.items()):
        print(f"\n  {tool_name}:")
        print(f"    Calls: {tool_stats['calls']}")
        print(f"    Avg latency: {tool_stats['avg_latency_ms']:.2f}ms")
        print(f"    Min latency: {tool_stats['min_latency_ms']:.2f}ms")
        print(f"    Max latency: {tool_stats['max_latency_ms']:.2f}ms")
        print(f"    P95 latency: {tool_stats['p95_latency_ms']:.2f}ms")


def load_test_concurrent_users():
    """Load test concurrent user simulation."""
    print("\n" + "=" * 70)
    print("LOAD TEST: CONCURRENT USERS")
    print("=" * 70)
    
    print("\n[1] Simulating 50 concurrent users sending messages...")
    
    simulator = LoadTestSimulator(max_concurrent=50)
    
    # Simulate 50 concurrent users each sending 20 messages
    for user_id in range(50):
        for msg_num in range(20):
            message = {
                "id": f"user_{user_id:02d}_msg_{msg_num:02d}",
                "user": user_id,
                "content": "Concurrent user message"
            }
            simulator.process_message(message, simulated_delay=0.005)
    
    stats = simulator.get_stats()
    
    print("\n[2] Concurrent User Load Statistics:")
    print(f"  Total messages: {stats['completed_messages']}")
    print(f"  Failures: {stats['failed_messages']}")
    print(f"  Throughput: {stats['messages_per_second']:.1f} msg/sec")
    print(f"  Avg latency: {stats['avg_latency_ms']:.2f}ms")
    print(f"  Max latency: {stats['max_latency_ms']:.2f}ms")
    print(f"  Error rate: {stats['error_rate_pct']:.2f}%")


def load_test_sustained_load():
    """Load test sustained load over time."""
    print("\n" + "=" * 70)
    print("LOAD TEST: SUSTAINED LOAD (30 seconds)")
    print("=" * 70)
    
    simulator = LoadTestSimulator(max_concurrent=10)
    
    print("\n[1] Running sustained load test for 30 seconds...")
    
    duration = 30
    start_time = time.time()
    msg_id = 0
    
    while time.time() - start_time < duration:
        message = {
            "id": f"msg_{msg_id:06d}",
            "content": "Sustained load test message"
        }
        simulator.process_message(message, simulated_delay=0.01)
        msg_id += 1
    
    stats = simulator.get_stats()
    
    print("\n[2] Sustained Load Statistics:")
    print(f"  Duration: {stats['elapsed_seconds']:.1f} seconds")
    print(f"  Total messages: {stats['completed_messages']}")
    print(f"  Throughput: {stats['messages_per_second']:.1f} msg/sec")
    print(f"  Avg latency: {stats['avg_latency_ms']:.2f}ms")
    print(f"  Error rate: {stats['error_rate_pct']:.2f}%")


def run_load_tests():
    """Run all load tests."""
    load_test_message_handling()
    load_test_context_saturation()
    load_test_tool_latency()
    load_test_concurrent_users()
    load_test_sustained_load()
    
    print("\n" + "=" * 70)
    print("LOAD TESTS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    run_load_tests()
