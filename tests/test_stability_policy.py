"""Deterministic stability/recovery controls; no running threads or hardware probes."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from brain.friction_damper import FrictionDamper
from brain.stability_sentinel import StabilitySentinel
from core.robustness import options, defer_idle
from core.pulse_context import retrieval_events


class StabilityPolicyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.events = []
        self.sentinel = StabilitySentinel(Path(temp.name), event_callback=lambda *args: self.events.append(args))
        self.sentinel._s_total_baseline = 1.0
        self.sentinel.s_total = 1.0

    def test_damping_opposes_motion_at_small_and_large_scales(self):
        damper = FrictionDamper(0.3, 1, 1, 0.5)
        for velocity in (-100, -1, -0.1, 0, 0.1, 1, 100):
            with self.subTest(velocity=velocity):
                self.assertLessEqual(damper.calculate_damping_force(velocity) * velocity, 0)
        for previous, target in ((0, 0.001), (0, 100), (100, 0), (0.1, 0.099), (1, 1)):
            value = damper.dampen_signal(previous, target)
            self.assertGreaterEqual(value, min(previous, target))
            self.assertLessEqual(value, max(previous, target))

    def test_spatial_and_fallback_paths_use_bounded_damping(self):
        sentinel = self.sentinel
        sentinel.s_total = 0
        sentinel._spatial_mind = SimpleNamespace(
            belief_space=SimpleNamespace(compute_shannon_entropy=lambda *a, **k: 1,
                compute_kl_divergence=lambda *a, **k: 1,
                compute_local_temperature=lambda *a, **k: 1),
            attention_center=None, _identity_center=None)
        sentinel._compute_lagrangian()
        self.assertGreaterEqual(sentinel.s_total, 0)
        self.assertLessEqual(sentinel.s_total, 1.5)
        sentinel._spatial_mind = None
        sentinel._compute_lagrangian()
        self.assertGreaterEqual(sentinel.s_total, 0)
        self.assertLessEqual(sentinel.s_total, 1)

    def test_raw_disk_failure_survives_baseline_normalization(self):
        self.sentinel._last_probe_results = {"disk_space": 0.2}
        for _ in range(20):
            self.sentinel._compute_lagrangian()
            self.sentinel._check_severity()
            self.assertEqual(self.sentinel.get_severity(), "critical")

    def test_recovery_requires_probe_cycles_and_snapshot_reads_do_not_advance_it(self):
        sentinel = self.sentinel
        sentinel._last_probe_results = {"memory_pressure": 0.2}
        sentinel._check_severity()
        sentinel._last_probe_results = {"memory_pressure": 1.0}
        for _ in range(20):
            self.assertEqual(sentinel.get_severity(), "critical")
        sentinel._check_severity()
        sentinel._check_severity()
        self.assertEqual(sentinel.get_severity(), "critical")
        sentinel._check_severity()
        self.assertEqual(sentinel.get_severity(), "all_clear")
        self.assertEqual([event[0] for event in self.events].count("stability_recovered"), 1)

    def test_cpu_use_alone_does_not_block_native_inference(self):
        self.sentinel._last_probe_results = {"process_health": 0.3}
        self.assertEqual(self.sentinel.get_severity(), "all_clear")

    def test_cognitive_warning_does_not_park_native_thinking(self):
        self.sentinel.s_total = 3.0
        self.sentinel._last_probe_results = {"consciousness_alive": 0.2, "memory_pressure": 1.0}
        self.assertEqual(self.sentinel.get_severity(), "critical")
        self.assertEqual(self.sentinel.get_resource_severity(), "all_clear")
        self.sentinel._last_probe_results["memory_pressure"] = 0.2
        self.assertEqual(self.sentinel.get_resource_severity(), "critical")

    def test_backpressure_yields_to_messages_and_unfinished_work(self):
        for severity in ("warning", "critical"):
            self.assertTrue(defer_idle(enabled=True, severity=severity, queued_events=False, pending_interaction=False))
            self.assertFalse(defer_idle(enabled=True, severity=severity, queued_events=True, pending_interaction=False))
            self.assertFalse(defer_idle(enabled=True, severity=severity, queued_events=False, pending_interaction=True))
        self.assertFalse(defer_idle(enabled=False, severity="critical", queued_events=False, pending_interaction=False))

    def test_telemetry_cannot_become_a_fresh_retrieval_query(self):
        for severity in ("critical", "warning", "drift", "recovered"):
            self.assertEqual(retrieval_events([f"[stability_{severity}] raw telemetry"]), [])

    def test_master_switch_and_bad_options(self):
        self.assertFalse(any(options({"mindscape": {"robustness": {"enabled": False}}}).values()))
        for value in ({"unknown": True}, {"procedure_learning": "yes"}, []):
            with self.assertRaises(ValueError):
                options({"mindscape": {"robustness": value}})
