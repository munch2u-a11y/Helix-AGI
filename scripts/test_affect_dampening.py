"""
Unit tests for dynamic stability-based fear dampening.
"""

import os
import sys
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.affect_field import AffectField


class TestAffectDampening(unittest.TestCase):
    """Test dynamic fear calculation changes in AffectField."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.field = AffectField(data_dir=self.temp_dir)
        # Fast forward pulse count to enable delta calculations
        self.field.current_pulse = 1

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stability_dampens_fear(self):
        """Test that higher stability (omega) reduces fear from entropy and drift."""
        # Scenario 1: Low stability (omega = 0.1)
        snapshot_low = {
            "omega": 0.1,
            "H": 1.5,
            "D_KL": 2.0,
            "T": 1.0,
            "s_total": 0.5,
        }
        self.field._prev_s_total = 0.5
        self.field._prev_omega = 0.1
        res_low = self.field._lagrangian_to_plutchik(snapshot_low)
        fear_low = res_low[2]  # Index 2 is fear

        # Scenario 2: High stability (omega = 0.9)
        snapshot_high = {
            "omega": 0.9,
            "H": 1.5,
            "D_KL": 2.0,
            "T": 1.0,
            "s_total": 0.5,
        }
        self.field._prev_s_total = 0.5
        self.field._prev_omega = 0.9
        res_high = self.field._lagrangian_to_plutchik(snapshot_high)
        fear_high = res_high[2]

        # Verify fear is significantly lower when stable
        self.assertLess(fear_high, fear_low)
        # Mathematically:
        # H term: 1.5 * 0.3 * 0.9 = 0.405 vs 1.5 * 0.3 * 0.1 = 0.045
        # D_KL term: 0.5 * 0.3 * 0.9 = 0.135 vs 0.5 * 0.3 * 0.1 = 0.015
        self.assertAlmostEqual(fear_low, 0.45 * 0.9 + 0.5 * 0.3 * 0.9)
        self.assertAlmostEqual(fear_high, 0.45 * 0.1 + 0.5 * 0.3 * 0.1)

    def test_omega_velocity_offsets_somatic_fear(self):
        """Test that positive omega_vel (gaining stability) offsets somatic delta_s fear."""
        # Case A: Gaining stability rapidly (omega_vel = 0.1)
        snapshot_gaining = {
            "omega": 0.6,
            "H": 0.0,
            "D_KL": 0.0,
            "T": 1.0,
            "s_total": 0.6,  # s_total increased by 0.05
        }
        self.field._prev_s_total = 0.55
        self.field._prev_omega = 0.5  # omega_vel = 0.1
        res_gaining = self.field._lagrangian_to_plutchik(snapshot_gaining)
        fear_gaining = res_gaining[2]

        # delta_s = 0.05. omega_vel = 0.1.
        # delta_s - omega_vel = -0.05 <= 0, so somatic fear is 0
        self.assertEqual(fear_gaining, 0.0)

        # Case B: Losing stability (omega_vel = -0.1)
        snapshot_losing = {
            "omega": 0.4,
            "H": 0.0,
            "D_KL": 0.0,
            "T": 1.0,
            "s_total": 0.6,  # s_total increased by 0.05
        }
        self.field._prev_s_total = 0.55
        self.field._prev_omega = 0.5  # omega_vel = -0.1
        res_losing = self.field._lagrangian_to_plutchik(snapshot_losing)
        fear_losing = res_losing[2]

        # delta_s = 0.05. omega_vel = -0.1.
        # delta_s - omega_vel = 0.15. somatic fear = 0.15 * 5.0 = 0.75
        self.assertAlmostEqual(fear_losing, 0.75)


def run_tests():
    """Run tests."""
    print("Running Affect Dampening Tests...")
    print("=" * 70)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestAffectDampening)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 70)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
