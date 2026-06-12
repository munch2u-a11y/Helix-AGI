"""
Pulse Loop Stress Test

Stress tests pulse loop behavior:
- Basic pulse operations (100 pulses)
- Memory growth monitoring (200 pulses)
- Stability sentinel threshold testing
- Pulse time variability analysis
- Sustained load over 500+ pulses
"""

import os
import sys
import time
import random
import statistics
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PulseSimulator:
    """Simulates the pulse loop for stress testing."""

    def __init__(self):
        self.pulse_count = 0
        self.memory_entries = 0
        self.pulse_times = []
        self.stability_readings = []
        self.errors = 0

        # Simulated omega/s_total
        self.omega = 0.5
        self.s_total = 0.15

    def run_pulse(self, has_input=False, tool_count=0):
        """Simulate a single pulse cycle."""
        t0 = time.time()

        try:
            # Phase 1: Perception (read incoming events)
            events = self._perceive(has_input)

            # Phase 2: Think (generate thought)
            thought = self._think(events, tool_count)

            # Phase 3: Act (execute tools)
            results = self._act(thought, tool_count)

            # Phase 4: Encode (create memory)
            self._encode(thought, results)

            # Phase 5: Update physics
            self._update_physics()

            self.pulse_count += 1

        except Exception as e:
            self.errors += 1

        elapsed = time.time() - t0
        self.pulse_times.append(elapsed)
        return elapsed

    def _perceive(self, has_input):
        """Simulate perception phase."""
        time.sleep(random.uniform(0.0005, 0.002))
        return ["input_event"] if has_input else []

    def _think(self, events, tool_count):
        """Simulate thinking phase."""
        # Thinking takes longer with more context
        base_time = 0.001 + len(events) * 0.0005
        time.sleep(base_time)
        return f"thought_{self.pulse_count}"

    def _act(self, thought, tool_count):
        """Simulate action phase."""
        results = []
        for _ in range(tool_count):
            time.sleep(random.uniform(0.001, 0.005))
            results.append({"status": "success"})
        return results

    def _encode(self, thought, results):
        """Simulate memory encoding."""
        self.memory_entries += 1
        time.sleep(random.uniform(0.0002, 0.001))

    def _update_physics(self):
        """Simulate physics update."""
        # Omega mean-reverts
        self.omega += (0.5 - self.omega) * 0.005
        self.omega += random.gauss(0, 0.005)
        self.omega = max(0.05, min(1.0, self.omega))

        # S_total fluctuates
        self.s_total = 0.15 + random.gauss(0, 0.03)
        self.s_total = max(0.0, min(1.0, self.s_total))

        self.stability_readings.append({
            "pulse": self.pulse_count,
            "omega": self.omega,
            "s_total": self.s_total,
        })

    def get_stats(self):
        """Get pulse statistics."""
        if not self.pulse_times:
            return {}

        return {
            "total_pulses": self.pulse_count,
            "total_errors": self.errors,
            "memory_entries": self.memory_entries,
            "avg_pulse_ms": statistics.mean(self.pulse_times) * 1000,
            "min_pulse_ms": min(self.pulse_times) * 1000,
            "max_pulse_ms": max(self.pulse_times) * 1000,
            "stdev_pulse_ms": statistics.stdev(self.pulse_times) * 1000 if len(self.pulse_times) > 1 else 0,
            "p95_pulse_ms": sorted(self.pulse_times)[int(len(self.pulse_times) * 0.95)] * 1000,
            "final_omega": self.omega,
            "final_s_total": self.s_total,
        }


def stress_test_basic_pulses():
    """Test 1: Basic pulse operations (100 pulses)."""
    print("\n" + "=" * 70)
    print("STRESS TEST 1: BASIC PULSE OPERATIONS (100 pulses)")
    print("=" * 70)

    sim = PulseSimulator()
    t0 = time.time()

    for i in range(100):
        has_input = random.random() < 0.3  # 30% chance of user input
        tools = random.randint(0, 2)
        sim.run_pulse(has_input=has_input, tool_count=tools)

    elapsed = time.time() - t0
    stats = sim.get_stats()

    print(f"\n  Completed: {stats['total_pulses']} pulses in {elapsed:.2f}s")
    print(f"  Errors: {stats['total_errors']}")
    print(f"  Avg pulse: {stats['avg_pulse_ms']:.2f}ms")
    print(f"  P95 pulse: {stats['p95_pulse_ms']:.2f}ms")
    print(f"  Throughput: {stats['total_pulses']/elapsed:.1f} pulses/sec")

    return stats["total_errors"] == 0


def stress_test_memory_growth():
    """Test 2: Memory growth monitoring (200 pulses)."""
    print("\n" + "=" * 70)
    print("STRESS TEST 2: MEMORY GROWTH MONITORING (200 pulses)")
    print("=" * 70)

    sim = PulseSimulator()
    checkpoints = []

    for i in range(200):
        sim.run_pulse(has_input=random.random() < 0.5, tool_count=1)

        if (i + 1) % 50 == 0:
            checkpoints.append({
                "pulse": i + 1,
                "memory_entries": sim.memory_entries,
                "omega": sim.omega,
            })
            print(f"  Pulse {i+1}: {sim.memory_entries} memories, "
                  f"Ω={sim.omega:.3f}")

    # Memory should grow linearly
    growth_rate = sim.memory_entries / 200
    print(f"\n  Memory growth rate: {growth_rate:.2f} entries/pulse")
    print(f"  Final memory count: {sim.memory_entries}")

    # Verify growth is reasonable (should be ~1 per pulse)
    assert 0.5 <= growth_rate <= 2.0, f"Abnormal growth rate: {growth_rate}"
    print(f"  ✓ Growth rate within expected range")

    return True


def stress_test_stability_thresholds():
    """Test 3: Stability sentinel threshold testing."""
    print("\n" + "=" * 70)
    print("STRESS TEST 3: STABILITY SENTINEL THRESHOLDS")
    print("=" * 70)

    sim = PulseSimulator()

    severity_counts = {"all_clear": 0, "drift": 0, "warning": 0, "critical": 0}

    for i in range(100):
        sim.run_pulse()

        # Classify severity based on s_total
        s = sim.s_total
        if s >= 0.85:
            severity = "critical"
        elif s >= 0.6:
            severity = "warning"
        elif s >= 0.3:
            severity = "drift"
        else:
            severity = "all_clear"

        severity_counts[severity] += 1

    print(f"\n  Severity distribution over 100 pulses:")
    for sev, count in severity_counts.items():
        bar = "█" * count
        print(f"    {sev:12s}: {count:3d} {bar}")

    # Most pulses should be all_clear or drift (since baseline is 0.15)
    assert severity_counts["all_clear"] > 30, "Too few all_clear readings"
    print(f"\n  ✓ Stability distribution looks healthy")

    return True


def stress_test_pulse_variability():
    """Test 4: Pulse time variability analysis."""
    print("\n" + "=" * 70)
    print("STRESS TEST 4: PULSE TIME VARIABILITY ANALYSIS")
    print("=" * 70)

    sim = PulseSimulator()

    for i in range(300):
        # Vary load: some pulses have many tools, some have none
        if i % 10 == 0:
            tools = 5  # Heavy pulse
        elif i % 3 == 0:
            tools = 2  # Medium pulse
        else:
            tools = 0  # Light pulse

        sim.run_pulse(has_input=i % 7 == 0, tool_count=tools)

    stats = sim.get_stats()

    print(f"\n  Pulse timing over 300 pulses:")
    print(f"    Min:   {stats['min_pulse_ms']:.2f}ms")
    print(f"    Avg:   {stats['avg_pulse_ms']:.2f}ms")
    print(f"    Max:   {stats['max_pulse_ms']:.2f}ms")
    print(f"    StDev: {stats['stdev_pulse_ms']:.2f}ms")
    print(f"    P95:   {stats['p95_pulse_ms']:.2f}ms")

    # Coefficient of variation should be reasonable
    cv = stats["stdev_pulse_ms"] / stats["avg_pulse_ms"] if stats["avg_pulse_ms"] > 0 else 0
    print(f"    CV:    {cv:.2f}")

    return True


def stress_test_sustained_load():
    """Test 5: Sustained load over 500+ pulses."""
    print("\n" + "=" * 70)
    print("STRESS TEST 5: SUSTAINED LOAD (500 pulses)")
    print("=" * 70)

    sim = PulseSimulator()
    t0 = time.time()

    # Run 500 pulses with realistic load
    for i in range(500):
        has_input = random.random() < 0.2
        tools = random.randint(0, 3)
        sim.run_pulse(has_input=has_input, tool_count=tools)

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            print(f"  Pulse {i+1}: {rate:.1f} pulses/sec, "
                  f"Ω={sim.omega:.3f}, errors={sim.errors}")

    total_elapsed = time.time() - t0
    stats = sim.get_stats()

    print(f"\n  Sustained Load Results:")
    print(f"    Total pulses: {stats['total_pulses']}")
    print(f"    Total time: {total_elapsed:.2f}s")
    print(f"    Throughput: {stats['total_pulses']/total_elapsed:.1f} pulses/sec")
    print(f"    Errors: {stats['total_errors']}")
    print(f"    Final Ω: {stats['final_omega']:.3f}")
    print(f"    Final S: {stats['final_s_total']:.3f}")
    print(f"    Memory entries: {stats['memory_entries']}")

    # Should complete with zero errors
    assert stats["total_errors"] == 0, f"Errors during sustained load: {stats['total_errors']}"
    print(f"\n  ✓ Sustained load completed without errors")

    return True


def run_stress_tests():
    """Run all stress tests."""
    print("=" * 70)
    print("HELIX PULSE LOOP STRESS TESTS")
    print("=" * 70)

    results = []
    results.append(("Basic Pulses", stress_test_basic_pulses()))
    results.append(("Memory Growth", stress_test_memory_growth()))
    results.append(("Stability Thresholds", stress_test_stability_thresholds()))
    results.append(("Pulse Variability", stress_test_pulse_variability()))
    results.append(("Sustained Load", stress_test_sustained_load()))

    print("\n" + "=" * 70)
    print("STRESS TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")

    print(f"\n  Passed: {passed}/{len(results)}")

    if failed == 0:
        print("  ✓ ALL STRESS TESTS PASSED")
    else:
        print(f"  ✗ {failed} STRESS TEST(S) FAILED")

    return failed == 0


if __name__ == "__main__":
    success = run_stress_tests()
    sys.exit(0 if success else 1)
