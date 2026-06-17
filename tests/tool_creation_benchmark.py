#!/usr/bin/env python3
"""
Helix — Dynamic Tool Creation & Scaling Benchmark

Benchmarks the latency and scalability of the Tool Factory system:
1. Tool Template Generation
2. Dynamic Compilation and Registration
3. Live Dispatch Execution
4. Scaling Overhead (analyzing latency trends as the number of custom tools increases)
"""

import os
import sys
import time
import json
import shutil
import argparse
import statistics
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_executor import ToolExecutor
from tools.tool_registry import registry


def run_benchmark(num_tools=20):
    print("=" * 70)
    print(f"HELIX DYNAMIC TOOL CREATION BENCHMARK (N={num_tools})")
    print("=" * 70)

    # Setup environment
    custom_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tools",
        "custom"
    )
    os.makedirs(custom_dir, exist_ok=True)

    # Mock PulseLoop to avoid rebuilding actual session
    mock_pulse_loop = MagicMock()
    mock_pulse_loop._active_toolsets = {"core"}
    mock_pulse_loop._pending_toolset_rebuild = False

    executor = ToolExecutor()
    executor.set_pulse_loop(mock_pulse_loop)

    creation_latencies = []
    registration_latencies = []
    execution_latencies = []

    print(f"Generating, registering, and executing {num_tools} tools...")
    for i in range(1, num_tools + 1):
        name = f"benchmark_tool_{i}"
        
        # 1. Benchmark Template Creation
        t0 = time.perf_counter()
        executor.execute_function_call("create_custom_tool_template", {
            "name": name,
            "toolset": "benchmark_group",
            "description": f"Benchmark tool number {i}",
            "parameters": {
                "type": "object",
                "properties": {
                    "val": {"type": "integer"}
                },
                "required": ["val"]
            }
        })
        t1 = time.perf_counter()
        creation_latencies.append((t1 - t0) * 1000)  # ms

        # Inject real handler code into the template file
        filepath = os.path.join(custom_dir, f"{name}.py")
        handler_code = f"""
schema = {{
    "name": "{name}",
    "description": "Returns value squared",
    "parameters": {{
        "type": "object",
        "properties": {{
            "val": {{"type": "integer"}}
        }},
        "required": ["val"]
    }}
}}
toolset = "benchmark_group"

def handler(args):
    import json
    v = int(args.get("val", 0))
    return json.dumps({{"squared": v * v}})
"""
        with open(filepath, "w") as f:
            f.write(handler_code)

        # 2. Benchmark Registration
        t0 = time.perf_counter()
        executor.execute_function_call("register_custom_tool", {"name": name})
        t1 = time.perf_counter()
        registration_latencies.append((t1 - t0) * 1000)  # ms

        # 3. Benchmark Execution
        t0 = time.perf_counter()
        exec_res = executor.execute_function_call(name, {"val": i})
        t1 = time.perf_counter()
        execution_latencies.append((t1 - t0) * 1000)  # ms

        # Verify output correctness
        res_dict = json.loads(exec_res)
        expected_val = i * i
        if res_dict.get("squared") != expected_val:
            print(f"Warning: Tool {name} returned incorrect result: {res_dict}")

    print("\nCleaning up benchmark files and deregistering...")
    # Clean up files & deregister from registry
    for i in range(1, num_tools + 1):
        name = f"benchmark_tool_{i}"
        registry.deregister(name)
        filepath = os.path.join(custom_dir, f"{name}.py")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

    # Statistics reporting
    def get_stats(lst):
        return {
            "avg": statistics.mean(lst),
            "min": min(lst),
            "max": max(lst),
            "p95": sorted(lst)[int(len(lst) * 0.95) - 1] if len(lst) >= 20 else max(lst),
            "stdev": statistics.stdev(lst) if len(lst) > 1 else 0.0
        }

    c_stats = get_stats(creation_latencies)
    r_stats = get_stats(registration_latencies)
    e_stats = get_stats(execution_latencies)

    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS (all metrics in milliseconds)")
    print("=" * 70)
    print(f"{'Operation':<20} | {'Avg':<8} | {'Min':<8} | {'Max':<8} | {'P95':<8} | {'StDev':<8}")
    print("-" * 70)
    print(f"{'Template Creation':<20} | {c_stats['avg']:<8.2f} | {c_stats['min']:<8.2f} | {c_stats['max']:<8.2f} | {c_stats['p95']:<8.2f} | {c_stats['stdev']:<8.2f}")
    print(f"{'Registration':<20} | {r_stats['avg']:<8.2f} | {r_stats['min']:<8.2f} | {r_stats['max']:<8.2f} | {r_stats['p95']:<8.2f} | {r_stats['stdev']:<8.2f}")
    print(f"{'Execution/Dispatch':<20} | {e_stats['avg']:<8.2f} | {e_stats['min']:<8.2f} | {e_stats['max']:<8.2f} | {e_stats['p95']:<8.2f} | {e_stats['stdev']:<8.2f}")
    print("=" * 70)

    # 4. Scaling Overhead Analysis
    # Compare latencies of first 20% vs last 20% of registrations
    split_size = max(1, num_tools // 5)
    first_registrations = registration_latencies[:split_size]
    last_registrations = registration_latencies[-split_size:]
    
    avg_first = statistics.mean(first_registrations)
    avg_last = statistics.mean(last_registrations)
    scaling_overhead = ((avg_last - avg_first) / avg_first) * 100 if avg_first > 0 else 0.0

    print("SCALING ANALYSIS")
    print(f"  First {split_size} tools registration latency avg: {avg_first:.2f} ms")
    print(f"  Last {split_size} tools registration latency avg: {avg_last:.2f} ms")
    print(f"  Scaling overhead (last vs first): {scaling_overhead:+.2f}%")
    
    if scaling_overhead < 20:
        print("  ✓ System scales efficiently with minimal registration overhead.")
    else:
        print("  ⚠ System shows warning-level registration overhead at larger scale.")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Helix Tool Creation Benchmark")
    parser.add_argument("--runs", type=int, default=20, help="Number of dynamic tools to generate (default: 20)")
    args = parser.parse_args()
    
    run_benchmark(num_tools=args.runs)
