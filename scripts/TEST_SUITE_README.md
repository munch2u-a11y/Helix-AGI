# Comprehensive Test Suite for Helix-AGI

## Quick Start

Run all tests:
```bash
python scripts/run_all_tests.py
```

Run only quick tests (validation + core):
```bash
python scripts/run_all_tests.py --quick
```

Run a specific test:
```bash
python scripts/run_all_tests.py --script test_tool_executor.py
```

## Test Scripts Overview

### 1. **validate_config.py** - Configuration Validator
Validates system configuration before running:
- Credentials file presence and readability
- Environment variables
- Required data directories
- Tool schema completeness
- Python dependencies

**Run:** `python scripts/validate_config.py`

### 2. **test_integration.py** - Integration Tests
End-to-end integration testing:
- Channel router message flow
- Tool executor integration
- Memory persistence
- Memory retrieval and semantic search
- Tool registration and execution with context

**Run:** `python scripts/test_integration.py`

### 3. **test_tool_executor.py** - Tool Executor Tests
Tests tool execution functionality:
- Tool invocation (single and multiple parameters)
- Parameter validation
- Result parsing and metadata handling
- Error handling (execution failures, timeouts, invalid params)
- Error recovery
- Context injection
- Memory access

**Run:** `python scripts/test_tool_executor.py`

### 4. **test_belief_operations.py** - Belief Operations Tests
Tests belief system functionality:
- Belief creation across categories (identity, people, capabilities, desires, knowledge)
- Belief retrieval (by category, with limits, search)
- Belief mass calculations and normalization
- Belief merging and composition

**Run:** `python scripts/test_belief_operations.py`

### 5. **test_channel_router.py** - Channel Router Tests
Tests communication pipeline:
- Contact management (add, retrieve, list)
- Message queueing and delivery
- Telegram-specific flows
- Message delivery callbacks
- Contact organization by channel

**Run:** `python scripts/test_channel_router.py`

### 6. **test_preconscious_injection.py** - Preconscious Context Builder
Tests context window assembly:
- Adding memories and beliefs to context
- Memory/belief weighting (priority, recency)
- Scratchpad note injection
- Context window overflow handling
- Token counting and compression

**Run:** `python scripts/test_preconscious_injection.py`

### 7. **simulate_memory_operations.py** - Memory Simulator
Simulates memory system operations:
- Memory load/save cycles
- Memory promotion logic (short-term → long-term → core)
- Semantic indexing patterns
- Data persistence and integrity verification

**Run:** `python scripts/simulate_memory_operations.py`

### 8. **simulate_physics.py** - Physics Engine Simulator
Simulates 8D manifold and semantic indexing:
- 8D point representation and distance calculations
- Gravity calculations in 8D space
- Lagrangian energy calculations
- Semantic indexing with FAISS-like nearest neighbor search
- Manifold evolution over multiple pulses
- Attractor dynamics and center of mass calculations

**Run:** `python scripts/simulate_physics.py`

### 9. **stress_test_pulse.py** - Pulse Loop Stress Test
Stress tests pulse loop behavior:
- Basic pulse operations (100 pulses)
- Memory growth monitoring (200 pulses)
- Stability sentinel threshold testing
- Pulse time variability analysis
- Sustained load over 500+ pulses

**Run:** `python scripts/stress_test_pulse.py`

### 10. **load_test.py** - Load Test Suite
Performance and load testing:
- High-volume message handling (1000+ messages)
- Context window saturation under load
- Tool execution latency measurement (per-tool stats)
- Concurrent user simulation (50+ concurrent)
- Sustained load test (30 second duration)

Measures:
- Throughput (messages/second)
- Latency (min, avg, max, p95, p99)
- Error rates
- Resource saturation

**Run:** `python scripts/load_test.py`

### 11. **run_all_tests.py** - Master Test Runner
Orchestrates all test suites with:
- Sequential execution of all tests
- Centralized result aggregation
- Summary reporting
- Exit codes for CI/CD integration

**Run:** `python scripts/run_all_tests.py`

## Test Categories

### Configuration & Setup
- `validate_config.py` - System configuration validation

### Core Unit Tests
- `test_tool_executor.py` - Tool execution
- `test_belief_operations.py` - Belief management
- `test_channel_router.py` - Communication routing
- `test_preconscious_injection.py` - Context building

### Integration Tests
- `test_integration.py` - Full system integration flows

### System Simulations
- `simulate_memory_operations.py` - Memory system behavior
- `simulate_physics.py` - Physics engine and manifold dynamics

### Performance & Load Tests
- `stress_test_pulse.py` - Pulse loop under stress
- `load_test.py` - High-volume load testing

## Expected Test Results

### Validation
- All required credentials and directories detected
- Optional dependencies noted but not required

### Unit Tests
- 100+ test cases across all modules
- 95%+ pass rate expected

### Simulations
- Memory: 50+ memories created and promoted
- Physics: 8D manifold with gravity calculations
- Semantic search with nearest neighbor queries

### Performance Tests
- Pulse throughput: 15-25 pulses/second
- Message throughput: 100+ msg/second
- Latency p99: <200ms for typical operations
- Memory growth: <1MB per 100 pulses
- Context saturation: Proper compression at 90%+

## Continuous Integration

For CI/CD pipelines, use quick mode:
```bash
python scripts/run_all_tests.py --quick
```

This runs only validation and core tests (60-90 seconds total).

## Troubleshooting

If tests fail:

1. **Configuration errors**: Run `python scripts/validate_config.py` first
2. **Import errors**: Ensure all dependencies are installed (`pip install -r requirements.txt`)
3. **Memory issues**: Close other applications before running load tests
4. **Timeout errors**: Increase timeout values in test scripts if running on slow systems

## Adding New Tests

To add a new test:

1. Create `scripts/test_<feature>.py` following the existing pattern
2. Use `unittest.TestCase` for unit tests
3. Include a `run_<feature>_tests()` function
4. Add to `scripts/run_all_tests.py` in the `test_scripts` list

## Performance Baselines

These are typical performance baselines to compare against:

- Single pulse execution: 40-50ms
- Tool invocation: 10-100ms (varies by tool)
- Memory save/load: 5-20ms for 100 memories
- Context assembly: 1-5ms
- Semantic search: 2-10ms for 1000 vectors

If performance degrades significantly, investigate:
- Memory leaks (use stress tests with memory monitoring)
- Inefficient algorithms (profile with cProfile)
- Resource contention (check system resources)

## Support & Debugging

For detailed debug output, modify test scripts:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

For performance profiling:
```python
import cProfile
cProfile.run('run_memory_simulation()')
```
