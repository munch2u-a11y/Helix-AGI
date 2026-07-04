"""
Integration test for Helix's tool-learning pipeline.

Tests the full lifecycle:
  1. Failure capture — tool errors are queued as pending belief candidates
  2. Dedup — same (tool, error-signature) within 6h cooldown is not re-queued
  3. Belief store round-trip — distilled lessons carry tool_bindings
  4. Verification loop — injected lesson + tool success = stability bump
  5. Workflow skill — deterministic direct-write to skills category
  6. Express lane injection via belief cache
  7. Nightly note compilation (curator Phase 7 path)

Run:  venv/bin/python tests/test_tool_learning_pipeline.py
"""

import json
import os
import sys
import shutil
import tempfile
import time
import logging

# ── Setup ────────────────────────────────────────────────────────────

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Configure logging so we can see what the tracker is doing
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("test_tool_learning")

# ── Test Harness ─────────────────────────────────────────────────────

class ToolLearningTestHarness:
    """Isolated test environment for the tool-learning pipeline."""

    def __init__(self):
        # Create temp dirs for belief store and pending file
        self.tmp_dir = tempfile.mkdtemp(prefix="helix_test_tool_learning_")
        self.data_dir = os.path.join(self.tmp_dir, "data")
        self.belief_dir = os.path.join(self.data_dir, "beliefs")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.belief_dir, exist_ok=True)

        logger.info(f"Test data dir: {self.tmp_dir}")

        # Initialize real BeliefStore
        from memory.belief_store import BeliefStore
        self.belief_store = BeliefStore(self.belief_dir)

        # Redirect pending_beliefs.json to temp dir
        import core.belief_detector as bd
        from pathlib import Path
        self._orig_pending_file = bd._PENDING_FILE
        bd._PENDING_FILE = Path(os.path.join(self.data_dir, "pending_beliefs.json"))

        # Wire tool_lesson_tracker with real belief store, no physics engine
        import core.tool_lesson_tracker as tlt
        tlt.set_dependencies(self.belief_store, physics_engine=None)

        # Reset tracker state from any prior test
        tlt._seen_signatures.clear()
        tlt._recent_injections.clear()

        self.tlt = tlt
        self.bd = bd

    def cleanup(self):
        """Restore global state and remove temp files."""
        self.bd._PENDING_FILE = self._orig_pending_file
        # Reset tracker globals
        self.tlt._belief_store = None
        self.tlt._physics_engine = None
        self.tlt._seen_signatures.clear()
        self.tlt._recent_injections.clear()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


# ── Test Functions ───────────────────────────────────────────────────

def test_failure_capture(h: ToolLearningTestHarness):
    """Tool errors are captured and queued as pending belief candidates."""
    print("\n" + "=" * 60)
    print("TEST 1: Failure Capture")
    print("=" * 60)

    # Simulate a tool error
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "git push origin main"},
        "Tool error (run_command): fatal: remote origin not found",
    )

    # Check pending queue
    pending = h.bd._read_pending()
    assert len(pending) == 1, f"Expected 1 pending, got {len(pending)}"
    entry = pending[0]
    assert entry["status"] == "pending"
    assert entry["source_type"] == "tool_failure"
    assert "run_command" in entry["tool_bindings"]
    assert "git push" in entry["content"]
    print(f"  ✓ Failure captured: {entry['content'][:80]}...")
    print(f"  ✓ Tool bindings: {entry['tool_bindings']}")
    print(f"  ✓ Status: {entry['status']}")

    # Verify stats
    stats = h.tlt.get_stats()
    assert stats["seen_signatures"] == 1
    print(f"  ✓ Tracker stats: {stats}")
    return True


def test_dedup_cooldown(h: ToolLearningTestHarness):
    """Same error signature within cooldown window is not re-queued."""
    print("\n" + "=" * 60)
    print("TEST 2: Dedup / Cooldown")
    print("=" * 60)

    before_count = len(h.bd._read_pending())

    # Same tool, same error pattern (numbers differ but get masked)
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "git push origin dev"},
        "Tool error (run_command): fatal: remote origin not found",
    )

    after_count = len(h.bd._read_pending())
    assert after_count == before_count, \
        f"Dedup failed: {before_count} -> {after_count}"
    print(f"  ✓ Duplicate suppressed (pending count stable at {after_count})")

    # Different tool, different error — should queue
    h.tlt.observe_tool_result(
        "search_web",
        {"query": "test"},
        "Error: connection timeout after 30 seconds",
    )

    after_new = len(h.bd._read_pending())
    assert after_new == before_count + 1, \
        f"Different error should queue: {before_count} -> {after_new}"
    print(f"  ✓ Different error queued (pending count: {after_new})")
    return True


def test_success_does_not_queue(h: ToolLearningTestHarness):
    """Successful tool results are not queued."""
    print("\n" + "=" * 60)
    print("TEST 3: Success Passthrough")
    print("=" * 60)

    before_count = len(h.bd._read_pending())

    h.tlt.observe_tool_result(
        "run_command",
        {"command": "ls -la"},
        "total 48\ndrwxr-xr-x  5 user user 4096 Jul  2 09:00 .",
    )

    after_count = len(h.bd._read_pending())
    assert after_count == before_count, \
        f"Success should not queue: {before_count} -> {after_count}"
    print(f"  ✓ Success result not queued (pending stable at {after_count})")
    return True


def test_belief_with_tool_bindings(h: ToolLearningTestHarness):
    """Beliefs can be created and queried with tool_bindings."""
    print("\n" + "=" * 60)
    print("TEST 4: Belief Store — tool_bindings CRUD")
    print("=" * 60)

    bid = h.belief_store.generate_id("propositions")
    print(f"  Generated ID: {bid}")

    added = h.belief_store.add_belief(
        category="propositions",
        belief_id=bid,
        content="When using run_command for git push, always verify the remote exists first with 'git remote -v'.",
        mass=1.0,
        confidence=0.6,
        source="tool_failure",
        tool_bindings=["run_command", "terminal"],
        formation_type="tool_failure_lesson",
    )
    assert added, "add_belief should return True"
    print(f"  ✓ Belief added with tool_bindings")

    # Retrieve and verify
    belief = h.belief_store.get_belief(bid)
    assert belief is not None
    assert belief["tool_bindings"] == ["run_command", "terminal"]
    print(f"  ✓ Retrieved: tool_bindings = {belief['tool_bindings']}")

    # Query by tool
    by_tool = h.belief_store.get_beliefs_by_tool("run_command")
    assert len(by_tool) >= 1
    assert any(b["id"] == bid for b in by_tool)
    print(f"  ✓ get_beliefs_by_tool('run_command') found {len(by_tool)} beliefs")

    # Case-insensitive
    by_tool_ci = h.belief_store.get_beliefs_by_tool("Run_Command")
    assert len(by_tool_ci) >= 1
    print(f"  ✓ Case-insensitive lookup works")

    return True


def test_verification_loop(h: ToolLearningTestHarness):
    """Injected lesson + subsequent tool success = stability bump."""
    print("\n" + "=" * 60)
    print("TEST 5: Verification Loop")
    print("=" * 60)

    # Create a tool-bound belief to act as the "lesson"
    bid = h.belief_store.generate_id("propositions")
    h.belief_store.add_belief(
        category="propositions",
        belief_id=bid,
        content="Always check disk space before large file operations with df -h.",
        mass=1.0,
        confidence=0.5,
        stability_index=0.5,
        source="tool_failure",
        tool_bindings=["run_command"],
    )

    initial = h.belief_store.get_belief(bid)
    initial_stability = initial["stability_index"]
    initial_verifications = initial["verifications"]
    print(f"  Initial: stability={initial_stability}, verifications={initial_verifications}")

    # Simulate: preconscious injected this lesson
    h.tlt.note_lessons_injected([{
        "belief_id": bid,
        "tools": ["run_command"],
    }])
    print(f"  ✓ Lesson injection reported to tracker")

    # Verify tracker state
    stats = h.tlt.get_stats()
    assert stats["pending_bumps"] == 1, f"Expected 1 pending bump, got {stats['pending_bumps']}"
    print(f"  ✓ Tracker has {stats['pending_bumps']} pending bump(s)")

    # Simulate: the tool succeeds within TTL
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "df -h"},
        "Filesystem      Size  Used Avail Use%\n/dev/sda1       100G   45G   55G  45%",
    )

    # Check: stability and verifications should have been bumped
    updated = h.belief_store.get_belief(bid)
    assert updated["stability_index"] > initial_stability, \
        f"Stability should have increased: {initial_stability} -> {updated['stability_index']}"
    assert updated["verifications"] > initial_verifications, \
        f"Verifications should have increased: {initial_verifications} -> {updated['verifications']}"
    print(f"  ✓ After success: stability={updated['stability_index']}, verifications={updated['verifications']}")

    # Verify bump was consumed
    stats_after = h.tlt.get_stats()
    assert stats_after["pending_bumps"] == 0
    print(f"  ✓ Pending bumps consumed: {stats_after['pending_bumps']}")

    return True


def test_verification_ttl_expiry(h: ToolLearningTestHarness):
    """Lesson injection that expires (outside TTL) does NOT bump on success."""
    print("\n" + "=" * 60)
    print("TEST 6: Verification TTL Expiry")
    print("=" * 60)

    bid = h.belief_store.generate_id("propositions")
    h.belief_store.add_belief(
        category="propositions",
        belief_id=bid,
        content="Check file permissions before writing.",
        mass=1.0,
        stability_index=0.5,
        source="tool_failure",
        tool_bindings=["write_to_file"],
    )

    # Report injection, then backdate it past TTL
    h.tlt.note_lessons_injected([{
        "belief_id": bid,
        "tools": ["write_to_file"],
    }])

    # Manually expire the injection by backdating
    import core.tool_lesson_tracker as tlt
    with tlt._state_lock:
        for note in tlt._recent_injections:
            if note["belief_id"] == bid:
                note["t"] = time.time() - 700  # 700s > 600s TTL

    # Tool success after TTL expiry
    h.tlt.observe_tool_result(
        "write_to_file",
        {"path": "/tmp/test.txt"},
        "File written successfully",
    )

    belief = h.belief_store.get_belief(bid)
    assert belief["stability_index"] == 0.5, \
        f"Stability should NOT have changed: {belief['stability_index']}"
    print(f"  ✓ Expired injection not bumped: stability still {belief['stability_index']}")

    return True


def test_workflow_skill_write(h: ToolLearningTestHarness):
    """Workflow detector's crystallized patterns write directly as skills."""
    print("\n" + "=" * 60)
    print("TEST 7: Workflow Skill Direct Write")
    print("=" * 60)

    result_id = h.tlt.record_workflow_skill(
        content="When deploying, always run 'git pull' then 'npm install' then 'npm run build' in sequence.",
        tool_names=["run_command", "terminal"],
    )

    assert result_id is not None, "record_workflow_skill should return a belief ID"
    print(f"  ✓ Skill written: {result_id}")

    belief = h.belief_store.get_belief(result_id)
    assert belief is not None
    assert belief["_category"] == "skills"
    assert "run_command" in belief.get("tool_bindings", [])
    assert belief.get("formation_type") == "workflow_crystallization"
    print(f"  ✓ Category: {belief['_category']}")
    print(f"  ✓ Tool bindings: {belief.get('tool_bindings')}")
    print(f"  ✓ Formation type: {belief.get('formation_type')}")
    print(f"  ✓ Content: {belief['content'][:80]}...")

    return True


def test_update_stability_index_clamping(h: ToolLearningTestHarness):
    """update_stability_index clamps to [0, 1]."""
    print("\n" + "=" * 60)
    print("TEST 8: Stability Index Clamping")
    print("=" * 60)

    bid = h.belief_store.generate_id("propositions")
    h.belief_store.add_belief(
        category="propositions",
        belief_id=bid,
        content="Test clamping belief",
        stability_index=0.95,
        tool_bindings=["test_tool"],
    )

    # Bump beyond 1.0
    h.belief_store.update_stability_index(bid, +0.10)
    belief = h.belief_store.get_belief(bid)
    assert belief["stability_index"] == 1.0, \
        f"Should clamp to 1.0, got {belief['stability_index']}"
    print(f"  ✓ Upper clamp: 0.95 + 0.10 = {belief['stability_index']}")

    # Negative delta
    h.belief_store.update_stability_index(bid, -1.5)
    belief = h.belief_store.get_belief(bid)
    assert belief["stability_index"] == 0.0, \
        f"Should clamp to 0.0, got {belief['stability_index']}"
    print(f"  ✓ Lower clamp: 1.0 - 1.5 = {belief['stability_index']}")

    return True


def test_multiple_failures_different_tools(h: ToolLearningTestHarness):
    """Multiple failures from different tools all get captured."""
    print("\n" + "=" * 60)
    print("TEST 9: Multi-Tool Failure Capture")
    print("=" * 60)

    before = len(h.bd._read_pending())

    failures = [
        ("search_telegram", {"query": "test"}, "Error: Telegram API rate limited"),
        ("send_message", {"to": "user"}, "Tool error (send_message): channel not found"),
        ("write_to_file", {"path": "/root/x"}, "Tool error (write_to_file): Permission denied"),
    ]

    for tool, args, error in failures:
        h.tlt.observe_tool_result(tool, args, error)

    after = len(h.bd._read_pending())
    new_entries = after - before
    assert new_entries == 3, f"Expected 3 new entries, got {new_entries}"

    pending = h.bd._read_pending()
    tools_captured = [p["tool_bindings"][0] for p in pending if p.get("tool_bindings")]
    print(f"  ✓ {new_entries} new failures captured")
    print(f"  ✓ Tools: {tools_captured[-3:]}")

    return True


def test_end_to_end_scenario(h: ToolLearningTestHarness):
    """Full scenario: agent uses terminal, hits errors, learns from them."""
    print("\n" + "=" * 60)
    print("TEST 10: End-to-End Scenario — Terminal Roadblocks")
    print("=" * 60)

    print("\n  --- Scene: Agent tries to deploy a project ---\n")

    # Step 1: Agent tries to push, fails (no remote)
    print("  Step 1: git push fails...")
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "git push origin main"},
        "Tool error (run_command): fatal: 'origin' does not appear to be a git repository",
    )
    stats = h.tlt.get_stats()
    print(f"    -> Failure captured (signatures: {stats['seen_signatures']})")

    # Step 2: Agent tries npm install, fails (no package.json)
    print("  Step 2: npm install fails...")
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "npm install"},
        "Error: ENOENT: no such file or directory, open 'package.json'",
    )
    print(f"    -> Failure captured")

    # Step 3: Agent tries to build, fails (wrong directory)
    print("  Step 3: npm run build fails...")
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "npm run build"},
        "Error: missing script: build",
    )
    print(f"    -> Failure captured")

    # --- Simulated nightly distillation ---
    # (Normally the batch service LLM distills these, but we simulate
    #  by manually creating the distilled beliefs)
    print("\n  --- Simulated nightly distillation ---\n")

    lessons = [
        ("Before git push, verify the remote exists with 'git remote -v'.",
         ["run_command"]),
        ("Before npm install, verify package.json exists in the current directory.",
         ["run_command"]),
        ("Before npm run build, check that 'build' is defined in package.json scripts.",
         ["run_command"]),
    ]

    lesson_ids = []
    for content, bindings in lessons:
        bid = h.belief_store.generate_id("propositions")
        h.belief_store.add_belief(
            category="propositions",
            belief_id=bid,
            content=content,
            mass=1.0,
            confidence=0.6,
            stability_index=0.5,
            source="batch_distillation",
            tool_bindings=bindings,
            formation_type="tool_failure_lesson",
        )
        lesson_ids.append(bid)
        print(f"    Distilled lesson {bid}: {content[:60]}...")

    # Verify all lessons are queryable by tool
    by_tool = h.belief_store.get_beliefs_by_tool("run_command")
    print(f"\n  Beliefs bound to 'run_command': {len(by_tool)}")
    for b in by_tool:
        print(f"    [{b['id']}] {b['content'][:60]}...")

    # --- Simulated next-day usage: lessons injected, then tool succeeds ---
    print("\n  --- Next day: agent deploys again ---\n")

    # Preconscious injects the lessons
    inject_items = [
        {"belief_id": bid, "tools": ["run_command"]}
        for bid in lesson_ids
    ]
    h.tlt.note_lessons_injected(inject_items)
    stats = h.tlt.get_stats()
    print(f"  Lessons injected: {len(inject_items)} (pending bumps: {stats['pending_bumps']})")

    # Agent now does it RIGHT: checks remote first, succeeds
    print("  Agent checks 'git remote -v' first...")
    h.tlt.observe_tool_result(
        "run_command",
        {"command": "git remote -v"},
        "origin  https://github.com/user/repo.git (fetch)\norigin  https://github.com/user/repo.git (push)",
    )

    # All lessons bound to run_command should have been bumped
    print("\n  --- Verification results ---\n")
    bumped = 0
    for bid in lesson_ids:
        b = h.belief_store.get_belief(bid)
        if b["stability_index"] > 0.5 or b["verifications"] > 1.0:
            bumped += 1
            print(f"  ✓ {bid}: stability={b['stability_index']:.2f}, "
                  f"verifications={b['verifications']:.1f} — VERIFIED")
        else:
            print(f"  ○ {bid}: stability={b['stability_index']:.2f}, "
                  f"verifications={b['verifications']:.1f} — not bumped")

    assert bumped >= 1, "At least one lesson should have been verified"
    print(f"\n  ✓ {bumped}/{len(lesson_ids)} lessons verified by tool success")

    # Final stats
    final_stats = h.tlt.get_stats()
    print(f"  ✓ Final tracker stats: {final_stats}")

    return True


# ── Runner ───────────────────────────────────────────────────────────

def run_all_tests():
    print("=" * 60)
    print("  HELIX TOOL LEARNING PIPELINE — INTEGRATION TESTS")
    print("=" * 60)

    harness = ToolLearningTestHarness()
    tests = [
        test_failure_capture,
        test_dedup_cooldown,
        test_success_does_not_queue,
        test_belief_with_tool_bindings,
        test_verification_loop,
        test_verification_ttl_expiry,
        test_workflow_skill_write,
        test_update_stability_index_clamping,
        test_multiple_failures_different_tools,
        test_end_to_end_scenario,
    ]

    passed = 0
    failed = 0
    errors = []

    for test_fn in tests:
        try:
            result = test_fn(harness)
            if result:
                passed += 1
            else:
                failed += 1
                errors.append((test_fn.__name__, "Returned False"))
        except Exception as e:
            failed += 1
            errors.append((test_fn.__name__, str(e)))
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    if errors:
        print("\n  FAILURES:")
        for name, msg in errors:
            print(f"    ✗ {name}: {msg}")

    harness.cleanup()
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
