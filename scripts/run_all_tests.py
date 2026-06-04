"""Master Test Runner

Orchestrates and runs all test suites in the comprehensive test framework.
Provides centralized coordination, reporting, and result aggregation.
"""

import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSuiteRunner:
    """Orchestrates test suite execution."""
    
    def __init__(self):
        """Initialize test runner."""
        self.scripts_dir = os.path.dirname(os.path.abspath(__file__))
        self.results = []
        self.start_time = datetime.now()
    
    def run_test_script(self, script_name, description):
        """Run a single test script."""
        script_path = os.path.join(self.scripts_dir, script_name)
        
        print(f"\n{'=' * 70}")
        print(f"Running: {description}")
        print(f"Script: {script_name}")
        print(f"{'=' * 70}")
        
        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=False,
                timeout=300  # 5 minute timeout
            )
            
            success = result.returncode == 0
            
            self.results.append({
                "script": script_name,
                "description": description,
                "success": success,
                "returncode": result.returncode,
                "timestamp": datetime.now().isoformat()
            })
            
            return success
        
        except subprocess.TimeoutExpired:
            print(f"\n✗ TIMEOUT: {script_name} exceeded 5 minute limit")
            self.results.append({
                "script": script_name,
                "description": description,
                "success": False,
                "error": "Timeout",
                "timestamp": datetime.now().isoformat()
            })
            return False
        
        except Exception as e:
            print(f"\n✗ ERROR running {script_name}: {e}")
            self.results.append({
                "script": script_name,
                "description": description,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return False
    
    def run_all_tests(self, quick_mode=False):
        """Run all test suites."""
        print("\n" + "=" * 70)
        print("HELIX COMPREHENSIVE TEST SUITE")
        print("=" * 70)
        print(f"Started: {self.start_time.isoformat()}")
        print(f"Mode: {'QUICK' if quick_mode else 'FULL'}")
        
        test_scripts = [
            # Validation
            ("validate_config.py", "Configuration Validator"),
            
            # Core Systems
            ("test_integration.py", "Integration Test Suite"),
            ("test_tool_executor.py", "Tool Executor Tests"),
            ("test_belief_operations.py", "Belief Operations Tests"),
            ("test_channel_router.py", "Channel Router Tests"),
            ("test_preconscious_injection.py", "Preconscious Context Builder Tests"),
            
            # Simulations
            ("simulate_memory_operations.py", "Memory Operations Simulator"),
            ("simulate_physics.py", "Physics Engine Simulator"),
            
            # Performance Tests
            ("stress_test_pulse.py", "Pulse Loop Stress Test"),
            ("load_test.py", "Load Test Suite"),
        ]
        
        if quick_mode:
            # Run only validation and core tests
            test_scripts = test_scripts[:6]
        
        passed = 0
        failed = 0
        
        for script_name, description in test_scripts:
            success = self.run_test_script(script_name, description)
            
            if success:
                passed += 1
                print(f"✓ PASSED: {description}")
            else:
                failed += 1
                print(f"✗ FAILED: {description}")
        
        self.print_summary(passed, failed)
        
        return failed == 0
    
    def print_summary(self, passed, failed):
        """Print test summary."""
        elapsed = datetime.now() - self.start_time
        
        print("\n" + "=" * 70)
        print("TEST SUITE SUMMARY")
        print("=" * 70)
        
        print(f"\nTotal Tests: {passed + failed}")
        print(f"Passed: {passed} ✓")
        print(f"Failed: {failed} ✗")
        print(f"Success Rate: {(passed / (passed + failed) * 100) if (passed + failed) > 0 else 0:.1f}%")
        print(f"Elapsed Time: {elapsed}")
        
        print("\nDetailed Results:")
        print("-" * 70)
        for result in self.results:
            status = "✓" if result["success"] else "✗"
            print(f"{status} {result['description']}")
            if not result["success"] and "error" in result:
                print(f"  Error: {result['error']}")
        
        print("\n" + "=" * 70)
        
        if failed == 0:
            print("✓ ALL TESTS PASSED")
        else:
            print(f"✗ {failed} TEST(S) FAILED")
        
        print("=" * 70)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Helix Comprehensive Test Suite Runner"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only validation and core tests (skip simulations and load tests)"
    )
    parser.add_argument(
        "--script",
        type=str,
        help="Run a specific test script"
    )
    
    args = parser.parse_args()
    
    runner = TestSuiteRunner()
    
    if args.script:
        # Run specific script
        success = runner.run_test_script(args.script, f"Running {args.script}")
        sys.exit(0 if success else 1)
    else:
        # Run all tests
        success = runner.run_all_tests(quick_mode=args.quick)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
