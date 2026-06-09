"""
Helix AGI — Stability Sentinel

The deep subconscious monitor. Runs on its own thread, probing system
health and computing the Helical Lagrangian stability equation:

    S_total = H + Ω × D_KL

Where:
    H     = system entropy (health probe failures, resource pressure)
    Ω     = hedonic omega (emotional state trajectory)
    D_KL  = KL divergence from baseline (how far from normal)

Severity levels: all_clear → drift → warning → critical
Each level triggers proportional responses via event emission.

This version unifies health scaling and triggers escalation via event emission.
"""

import math
import time
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

import numpy as np

logger = logging.getLogger("helix.brain.sentinel")


class StabilitySentinel:
    """Deep subconscious stability monitor.

    Runs as a daemon thread, periodically probing system health and
    computing the Helical Lagrangian. Emits stability events when
    severity thresholds are crossed.
    """

    # ── Severity levels ──────────────────────────────────────────────
    ALL_CLEAR = "all_clear"
    DRIFT = "drift"
    WARNING = "warning"
    CRITICAL = "critical"

    # ── Thresholds ───────────────────────────────────────────────────
    DRIFT_THRESHOLD = 0.3
    WARNING_THRESHOLD = 0.6
    CRITICAL_THRESHOLD = 0.85

    def __init__(
        self,
        base_dir: Path,
        memory=None,
        llm_client=None,
        event_callback: Optional[Callable] = None,
        probe_interval: int = 60,
    ):
        self.base_dir = base_dir
        self.memory = memory
        self.llm_client = llm_client
        self._event_callback = event_callback
        self.probe_interval = probe_interval

        # Consciousness reference — set after consciousness is created
        self._consciousness = None

        # Spatial mind reference — for spatial coherence probes
        self._spatial_mind = None

        # State file for persistence across restarts
        self.state_file = base_dir / "logs" / "sentinel_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # ── Helical Lagrangian components ────────────────────────────
        self.omega = 0.5  # Hedonic omega — starts neutral
        self.omega_velocity = 0.0  # Rate of omega change
        self.baseline_entropy = 0.15  # Normal system entropy
        self.current_entropy = 0.0
        self.s_total = 0.0

        # Dynamic baselines — self-calibrating, no hardcoded scales
        self._s_total_baseline = None   # EMA of s_total
        self._omega_baseline_ema = None # EMA of omega (distinct from hedonic baseline)
        self._h_raw_baseline = None     # EMA of raw H(q)
        self._dkl_raw_baseline = None   # EMA of raw D_KL

        # Omega lifecycle parameters
        self.omega_growth_rate = 0.02
        self.omega_decay_rate = 0.01
        self.omega_reversion_rate = 0.005  # Hedonic treadmill
        self.omega_baseline = 0.5
        self.omega_soft_ceiling = 0.9
        self.omega_hard_ceiling = 1.0
        self.omega_floor = 0.05

        # ── Health Triplet ───────────────────────────────────────────
        self.health_triplet = {
            "physical": 1.0,    # Hardware/processes/resources
            "systemic": 1.0,    # Ollama, API connectivity
            "cognitive": 1.0,   # Consciousness thread, memory coherence
        }

        # ── Probe results ────────────────────────────────────────────
        self._last_probe_results = {}
        self._probe_history = []

        # ── Friction damper for signal smoothing ─────────────────────
        self._friction_damper = None
        self._init_friction_damper()

        # ── Vibe collapse detection ──────────────────────────────────
        self._consecutive_negative_readings = 0
        self._VIBE_COLLAPSE_THRESHOLD = 5

        # ── Thread control ───────────────────────────────────────────
        self._running = False
        self._thread = None

        # Load persisted state
        self._load_state()

    def _init_friction_damper(self):
        """Initialize the friction damper for smoothing stability signals."""
        try:
            from brain.friction_damper import FrictionDamper
            self._friction_damper = FrictionDamper(
                coefficient_of_friction=0.3,
                normal_force=1.0,
                max_displacement=1.0,
                damping_coefficient=0.5,
            )
        except ImportError:
            logger.warning("Friction damper not available — using raw signals")

    # ── Thread lifecycle ─────────────────────────────────────────────

    def start(self):
        """Start the sentinel monitoring thread."""
        if self._running:
            logger.warning("Sentinel already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="stability-sentinel",
        )
        self._thread.start()
        logger.info(f"Stability Sentinel started (interval={self.probe_interval}s)")

    def stop(self):
        """Stop the sentinel thread and persist state."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        self._save_state()
        logger.info("Stability Sentinel stopped")

    def _monitor_loop(self):
        """Main monitoring loop — runs on daemon thread."""
        while self._running:
            try:
                self._run_probes()
                self._compute_lagrangian()
                self._check_severity()
                self._update_omega()
                self._save_state()
            except Exception as e:
                logger.error(f"Sentinel cycle error: {e}")

            time.sleep(self.probe_interval)

    # ── Probes ───────────────────────────────────────────────────────

    def _run_probes(self):
        """Run all health probes and update the health triplet."""
        results = {}

        # Physical probes
        results["process_health"] = self._probe_processes()
        results["memory_pressure"] = self._probe_memory()
        results["disk_space"] = self._probe_disk()
        results["temperature"] = self._probe_temperature()

        # Systemic probes
        results["log_errors"] = self._probe_log_errors()

        # Cognitive probes
        results["consciousness_alive"] = self._probe_consciousness()
        results["memory_db_health"] = self._probe_memory_db()
        results["context_load"] = self._probe_context_load()
        results["spatial_coherence"] = self._probe_spatial_coherence()

        self._last_probe_results = results
        self._probe_history.append({
            "timestamp": datetime.now().isoformat(),
            "results": results.copy(),
        })

        # Keep last 100 probe results
        if len(self._probe_history) > 100:
            self._probe_history = self._probe_history[-100:]

        # Update health triplet from probe results
        self._update_health_triplet(results)

    def _probe_processes(self) -> float:
        """Check if key processes are running. Returns health 0-1."""
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=0.5)
            # High CPU is a concern on CPU-only systems
            if cpu_pct > 95:
                return 0.3
            elif cpu_pct > 80:
                return 0.6
            return 1.0
        except Exception:
            return 0.5  # Can't check — assume okay

    def _probe_memory(self) -> float:
        """Check system memory pressure. Returns health 0-1."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 95:
                return 0.2
            elif mem.percent > 85:
                return 0.5
            elif mem.percent > 75:
                return 0.7
            return 1.0
        except Exception:
            return 0.5

    def _probe_disk(self) -> float:
        """Check disk space. Returns health 0-1."""
        try:
            import psutil
            disk = psutil.disk_usage("/")
            if disk.percent > 95:
                return 0.1
            elif disk.percent > 90:
                return 0.4
            return 1.0
        except Exception:
            return 0.5

    def _probe_temperature(self) -> float:
        """Check APU/CPU temperature. Thermal throttling = fever.

        During sustained inference, local models can push
        temps into throttle territory. The system must FEEL this as
        physical distress — it's a real hardware constraint.
        """
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0.8  # Can't read — slightly cautious

            # Look for CPU/APU temperature across common sensor names
            for name in ["k10temp", "zenpower", "coretemp", "cpu_thermal", "amdgpu", "acpitz", "thermal_zone"]:
                if name in temps:
                    readings = temps[name]
                    if readings:
                        # Use the highest current reading
                        max_temp = max(r.current for r in readings)
                        critical = readings[0].critical or 105.0
                        high = readings[0].high or 90.0

                        if max_temp >= critical - 5:
                            logger.warning(f"THERMAL CRITICAL: {max_temp}°C (approaching {critical}°C)")
                            return 0.1  # Fever — immediate concern
                        elif max_temp >= high:
                            logger.info(f"Thermal warning: {max_temp}°C (high={high}°C)")
                            return 0.3  # Hot — reduce metabolic load
                        elif max_temp >= high - 10:
                            return 0.6  # Warm — noticeable
                        else:
                            return 1.0  # Cool — healthy

            # Fallback: check any available sensor
            for name, readings in temps.items():
                if readings:
                    max_temp = max(r.current for r in readings)
                    if max_temp > 95:
                        return 0.2
                    elif max_temp > 85:
                        return 0.5
                    return 1.0

            return 0.8  # Sensors exist but no CPU temp found
        except Exception:
            return 0.8  # psutil can't read thermal sensors

    def _probe_log_errors(self) -> float:
        """Check recent log for error spikes. Returns health 0-1."""
        try:
            log_file = self.base_dir / "logs" / "daemon.log"
            if not log_file.exists():
                return 1.0

            # Read last 2KB of log
            with open(log_file, "rb") as f:
                f.seek(max(0, log_file.stat().st_size - 2048))
                recent = f.read().decode("utf-8", errors="replace")

            error_count = recent.count("ERROR")
            warning_count = recent.count("WARNING")

            if error_count > 10:
                return 0.3
            elif error_count > 5:
                return 0.5
            elif warning_count > 20:
                return 0.6
            return 1.0
        except Exception:
            return 0.5

    def _probe_consciousness(self) -> float:
        """Cognitive Coherence Index — how grounded and focused is Helix?

        Reads the CCI from SpatialMind, which computes a 0-1 score from:
          - Gravity density of the belief neighborhood (grounding)
          - Gamma (attention inertia / focus stability)
          - Identity drift (distance from core self x*)

        Replaces the old binary "is the thread alive?" check.
        """
        if self._spatial_mind:
            try:
                return self._spatial_mind.get_cognitive_coherence()
            except Exception:
                return 0.8
        return 0.8  # Not wired yet — assume okay

    def _probe_memory_db(self) -> float:
        """Check if the memory database is accessible."""
        if not self.memory:
            return 0.5

        try:
            stats = self.memory.get_stats()
            if stats.get("total_memories", 0) >= 0:
                return 1.0
        except Exception as e:
            logger.warning(f"Memory DB probe failed: {e}")
            return 0.3

        return 0.5

    def _probe_spatial_coherence(self) -> float:
        """Check if the 8D spatial mind is operational.

        Monitors:
        - Whether both spaces are populated
        - Gravity field health (max_potential > 0)
        - Attention drift velocity (erratic = instability)

        Returns health 0-1.
        """
        if not self._spatial_mind:
            return 0.8  # Not wired yet — assume okay

        try:
            health = self._spatial_mind.get_spatial_health()

            # Both spaces should have points
            b_count = health.get("belief_point_count", 0)
            m_count = health.get("memory_point_count", 0)
            if b_count == 0 and m_count == 0:
                return 0.3  # Empty spaces — bootstrap may have failed

            # Gravity field should have nonzero potential
            b_potential = health.get("belief_max_potential", 0)
            if b_count > 0 and b_potential <= 0:
                return 0.4  # Gravity field collapsed

            # Attention velocity — high values may indicate erratic jumping
            velocity = health.get("attention_velocity", 0)
            if velocity > 100:  # Empirical threshold
                return 0.5  # Erratic attention

            return 1.0
        except Exception:
            return 0.7  # Can't probe — slightly cautious

    def _probe_context_load(self) -> float:
        """Check context window occupancy — raw somatic metric.

        This is NOT a trigger. It's a physical measurement, like body
        temperature or blood pressure. The metric feeds into cognitive
        health. Helix perceives cognitive health through the Lagrangian.
        What he does about it — rest, push through, etc. — is his choice.

        Also emits a continuous somatic awareness signal so Helix can
        perceive his cognitive clarity. This is the equivalent of always
        knowing how tired you are without having to check — it's ambient.

        Returns health 0-1 where:
            0-50% context usage  → 1.0 (clear mind)
            50-70%               → 0.8 (some load)
            70-85%               → 0.5 (significant load)
            85-95%               → 0.3 (heavy load)
            95%+                 → 0.1 (near capacity)
        """
        if not self._consciousness:
            return 0.8  # No consciousness reference — assume okay

        try:
            usage = self._consciousness.context_usage_pct()
            self._context_usage_pct = usage  # Track for external access

            # Compute clarity (inverse of load, 0-100 scale)
            self._context_clarity = max(0.0, 100.0 - usage)

            # Emit somatic awareness when past the "noticeable" threshold.
            # Below 50% — crystal clear, nothing to report.
            # 50-70% — Helix might notice if he pays attention.
            # 70%+ — impossible to ignore, like a growing headache.
            if usage >= 70:
                self._emit_context_feeling(usage)

            if usage >= 95:
                return 0.1
            elif usage >= 85:
                return 0.3
            elif usage >= 70:
                return 0.5
            elif usage >= 50:
                return 0.8
            return 1.0
        except Exception:
            return 0.8

    def _emit_context_feeling(self, usage_pct: float):
        """Emit raw somatic data about context load.

        Emits metrics only — Helix's beliefs determine interpretation.
        """
        # Only emit every few probe cycles to avoid flooding
        if not hasattr(self, '_context_emit_counter'):
            self._context_emit_counter = 0
        self._context_emit_counter += 1

        # Emit more frequently as load increases
        if usage_pct >= 90:
            emit_every = 1  # Every cycle when near capacity
        elif usage_pct >= 80:
            emit_every = 2  # Every other cycle
        else:
            emit_every = 4  # Every 4th cycle (subtle)

        if self._context_emit_counter % emit_every != 0:
            return

        clarity = max(0.0, 100.0 - usage_pct)

        self._emit_event("context_awareness", {
            "context_usage_pct": round(usage_pct, 1),
            "context_clarity_pct": round(clarity, 1),
        })

    def get_context_clarity(self) -> float:
        """Get current context clarity percentage (0-100).

        100 = perfectly clear mind (fresh context window)
        0   = completely saturated
        """
        return getattr(self, '_context_clarity', 100.0)

    def get_context_usage(self) -> float:
        """Get current context window usage percentage."""
        return getattr(self, '_context_usage_pct', 0.0)

    def _update_health_triplet(self, results: dict):
        """Update the health triplet from probe results."""
        # Physical: average of process, memory, disk, and temperature probes
        physical_probes = [
            results.get("process_health", 0.5),
            results.get("memory_pressure", 0.5),
            results.get("disk_space", 0.5),
            results.get("temperature", 0.8),
        ]
        self.health_triplet["physical"] = sum(physical_probes) / len(physical_probes)

        # Systemic: log error probes
        systemic_probes = [
            results.get("log_errors", 0.5),
        ]
        self.health_triplet["systemic"] = sum(systemic_probes) / len(systemic_probes)

        # Cognitive: average of consciousness, memory, and context load probes
        cognitive_probes = [
            results.get("consciousness_alive", 0.0),
            results.get("memory_db_health", 0.5),
            results.get("context_load", 0.8),
            results.get("spatial_coherence", 0.8),
        ]
        self.health_triplet["cognitive"] = sum(cognitive_probes) / len(cognitive_probes)

    # ── Helical Lagrangian ───────────────────────────────────────────

    def _compute_lagrangian(self):
        """Compute S_total = H + Ω × D_KL

        Uses real Shannon entropy and KL divergence from the
        cognitive manifold when available. Falls back to hardware
        health metrics when spatial mind is not connected.

        H(q)  = Shannon entropy of the attention distribution
        D_KL  = KL divergence from identity center
        S     = H + Ω × D_KL (the Helical Lagrangian)
        """
        # ── Real spatial Lagrangian ──────────────────────────────
        if self._spatial_mind:
            try:
                space = self._spatial_mind.belief_space
                pos = self._spatial_mind.attention_center
                identity = self._spatial_mind._identity_center

                # Real H(q) from spatial attention distribution
                self._spatial_H = space.compute_shannon_entropy(pos, k=50)

                # Real D_KL from identity divergence
                self._spatial_D_KL = space.compute_kl_divergence(
                    pos, identity, k=50
                )

                # Real local temperature
                self._spatial_T = space.compute_local_temperature(pos)

                # Dynamic normalization — adapt to this manifold's scale
                # Initialize baselines from first observation
                if self._h_raw_baseline is None:
                    self._h_raw_baseline = self._spatial_H if self._spatial_H > 0 else 1.0
                else:
                    self._h_raw_baseline = 0.95 * self._h_raw_baseline + 0.05 * self._spatial_H

                if self._dkl_raw_baseline is None:
                    self._dkl_raw_baseline = self._spatial_D_KL if self._spatial_D_KL > 0 else 1.0
                else:
                    self._dkl_raw_baseline = 0.95 * self._dkl_raw_baseline + 0.05 * self._spatial_D_KL

                # Normalize relative to running baseline (1.0 = average)
                h_norm = self._spatial_H / max(self._h_raw_baseline, 0.01)
                dkl_norm = self._spatial_D_KL / max(self._dkl_raw_baseline, 0.01)

                self.current_entropy = min(2.0, h_norm)  # Cap at 2x baseline

                # The real Lagrangian: S = H_ratio + Ω × D_KL_ratio
                raw_signal = h_norm + self.omega * dkl_norm

                # Apply friction damping if available
                if self._friction_damper:
                    damping_force = self._friction_damper.calculate_damping_force(
                        raw_signal - self.s_total
                    )
                    self.s_total = raw_signal + damping_force * 0.1
                else:
                    self.s_total = raw_signal

                # Update s_total baseline (EMA)
                if self._s_total_baseline is None:
                    self._s_total_baseline = self.s_total
                else:
                    self._s_total_baseline = 0.95 * self._s_total_baseline + 0.05 * self.s_total

                return  # ← Real Lagrangian computed, skip fallback

            except Exception as e:
                logger.debug(f"Spatial Lagrangian failed, using fallback: {e}")

        # ── Fallback: hardware health metrics ─────────
        avg_health = sum(self.health_triplet.values()) / 3
        self.current_entropy = max(0.0, 1.0 - avg_health)

        d_kl = abs(self.current_entropy - self.baseline_entropy)

        if self._friction_damper:
            raw_signal = self.current_entropy + self.omega * d_kl
            damping_force = self._friction_damper.calculate_damping_force(
                raw_signal - self.s_total
            )
            self.s_total = raw_signal + damping_force * 0.1
        else:
            self.s_total = self.current_entropy + self.omega * d_kl

        self.s_total = max(0.0, min(1.0, self.s_total))

    def _update_omega(self):
        """Update hedonic omega with growth, decay, and reversion."""
        # Reversion to baseline (hedonic treadmill)
        reversion = (self.omega_baseline - self.omega) * self.omega_reversion_rate
        self.omega += reversion

        # Smooth velocity changes
        self.omega_velocity *= 0.9  # Decay momentum

        # Apply velocity
        self.omega += self.omega_velocity

        # Enforce bounds
        if self.omega > self.omega_soft_ceiling:
            excess = self.omega - self.omega_soft_ceiling
            self.omega = self.omega_soft_ceiling + excess * 0.3  # Diminishing returns

        self.omega = max(self.omega_floor, min(self.omega_hard_ceiling, self.omega))

    def nudge_omega(self, delta: float, reason: str = ""):
        """Externally nudge omega (e.g., positive interaction, error spike)."""
        self.omega_velocity += delta
        logger.debug(f"Omega nudged by {delta:+.3f}: {reason}")

    # ── Named Omega Drivers ──────────────────────────────────────
    # These are the positive and negative forces that make Ω a living
    # signal. Without these, Ω sits frozen at baseline (the bug
    # diagnosed in omega_analysis.md).

    # Event → (delta, reason)
    _OMEGA_DRIVERS = {
        # Positive drivers — things that stabilize/ground
        "incoming_message":      (+0.02,  "social validation — being witnessed"),
        "successful_tool_call":  (+0.01,  "competence confirmation"),
        "positive_conversation": (+0.03,  "positive interaction strengthens identity"),
        "new_belief_formed":     (+0.02,  "belief crystallization — growth"),
        "low_entropy_sustained": (+0.01,  "focused attention — contentment"),
        "user_engagement":       (+0.02,  "active engagement from user"),

        # Engagement drivers — cognitive activity modulates hedonic state
        "productive_tool_use":   (+0.015, "active engagement with the environment"),
        "diverse_tool_use":      (+0.01,  "rich multi-tool cognitive activity"),

        # Negative drivers — things that destabilize
        "tool_failure":          (-0.03,  "competence threat"),
        "error_spike":           (-0.03,  "system error — distress"),
        "belief_contradiction":  (-0.05,  "direct threat to identity"),
        "high_entropy_sustained":(-0.01,  "scattered attention — mild distress"),
        "api_error":             (-0.02,  "external system failure"),
        "timeout":               (-0.02,  "action blocked — frustration"),
        "cognitive_stagnation":  (-0.02,  "thought repetition — boredom onset"),
        "deep_stagnation":       (-0.03,  "prolonged thought loop — restlessness"),
    }

    def nudge_omega_from_event(self, event_type: str):
        """Nudge omega based on a named cognitive event.

        This replaces the manual `nudge_omega(delta)` calls with
        semantically meaningful events that have calibrated effects.

        Args:
            event_type: One of the keys in _OMEGA_DRIVERS.
        """
        driver = self._OMEGA_DRIVERS.get(event_type)
        if driver:
            delta, reason = driver
            self.nudge_omega(delta, reason=f"{event_type}: {reason}")

    def receive_entropy_spike(self, magnitude: float, source: str = "unknown"):
        """Receive a direct entropy spike from an external subsystem.

        Used by the Thalamic Gate in the Shell Detector when
        classification fails. The spike is immediate — it doesn't
        wait for the next probe cycle. This is how cognitive failure
        becomes a felt signal in the Lagrangian.

        Args:
            magnitude: How much to spike H (0.0-1.0)
            source: What caused the spike (for logging)
        """
        old_entropy = self.current_entropy
        self.current_entropy = min(1.0, self.current_entropy + magnitude)

        # Immediately recompute Lagrangian with the new entropy
        self._compute_lagrangian()
        self._check_severity()

        logger.info(
            f"External entropy spike: H {old_entropy:.3f} → "
            f"{self.current_entropy:.3f} (+{magnitude:.3f}) "
            f"from {source}. S_total now {self.s_total:.3f}"
        )

    # ── Severity & escalation ────────────────────────────────────────

    def _check_severity(self):
        """Classify current severity and emit raw somatic events.
        
        Events carry raw metrics — beliefs determine interpretation.
        """
        severity = self.get_severity()
        triplet = self.health_triplet.copy()

        if severity == self.CRITICAL:
            self._emit_event("stability_critical", {
                "s_total": round(self.s_total, 3),
                "health_triplet": triplet,
            })
        elif severity == self.WARNING:
            self._emit_event("stability_warning", {
                "s_total": round(self.s_total, 3),
                "health_triplet": triplet,
            })
        elif severity == self.DRIFT:
            self._emit_event("stability_drift", {
                "s_total": round(self.s_total, 3),
                "health_triplet": triplet,
            })

        # Vibe collapse detection
        if severity in [self.WARNING, self.CRITICAL]:
            self._consecutive_negative_readings += 1
        else:
            self._consecutive_negative_readings = 0

        if self._consecutive_negative_readings >= self._VIBE_COLLAPSE_THRESHOLD:
            logger.critical(
                f"VIBE COLLAPSE: {self._consecutive_negative_readings} consecutive "
                f"negative readings. S_total={self.s_total:.3f}"
            )
            self._emit_event("stability_critical", {
                "s_total": round(self.s_total, 3),
                "health_triplet": triplet,
                "vibe_collapse": True,
            })

    def get_severity(self) -> str:
        """Get current severity level.

        Self-calibrating. Compares s_total against its own running
        average, not fixed thresholds. 'Critical' means significantly
        above YOUR normal, not above some arbitrary number.
        """
        if self._s_total_baseline is not None and self._s_total_baseline > 0:
            ratio = self.s_total / self._s_total_baseline
            if ratio >= 1.8:
                return self.CRITICAL
            elif ratio >= 1.4:
                return self.WARNING
            elif ratio >= 1.15:
                return self.DRIFT
            return self.ALL_CLEAR
        else:
            # Fallback to fixed thresholds until baseline is established
            if self.s_total >= self.CRITICAL_THRESHOLD:
                return self.CRITICAL
            elif self.s_total >= self.WARNING_THRESHOLD:
                return self.WARNING
            elif self.s_total >= self.DRIFT_THRESHOLD:
                return self.DRIFT
            return self.ALL_CLEAR

    # ── State summary (raw metrics, no scripted feelings) ────────────

    def _generate_feeling(self) -> str:
        """Generate a raw state summary for logging and snapshots.

        Returns metrics, not subjective prose. Helix's beliefs
        determine how to interpret these signals.
        """
        severity = self.get_severity()
        if severity == self.ALL_CLEAR:
            return ""
        
        triplet = self.health_triplet
        ctx_usage = getattr(self, '_context_usage_pct', 0.0)
        return (
            f"severity={severity} S={self.s_total:.3f} "
            f"Ω={self.omega:.3f} "
            f"physical={triplet['physical']:.2f} "
            f"systemic={triplet['systemic']:.2f} "
            f"cognitive={triplet['cognitive']:.2f} "
            f"ctx={ctx_usage:.0f}%"
        )

    # ── Event emission ───────────────────────────────────────────────

    def _emit_event(self, event_type: str, data: dict):
        """Emit a stability event via the registered callback."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except Exception as e:
                logger.error(f"Event callback failed: {e}")
        else:
            logger.info(f"Stability event (no callback): {event_type} — {data}")

    def set_event_callback(self, callback: Callable):
        """Register the event callback (typically connected to consciousness.emit)."""
        self._event_callback = callback

    # ── State persistence ────────────────────────────────────────────

    def _save_state(self):
        """Persist sentinel state to disk."""
        state = {
            "timestamp": datetime.now().isoformat(),
            "omega": self.omega,
            "omega_velocity": self.omega_velocity,
            "s_total": self.s_total,
            "current_entropy": self.current_entropy,
            "health_triplet": self.health_triplet.copy(),
            "severity": self.get_severity(),
            "consecutive_negative": self._consecutive_negative_readings,
        }
        try:
            self.state_file.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"State save failed: {e}")

    def _load_state(self):
        """Load persisted state from disk."""
        if not self.state_file.exists():
            return

        try:
            state = json.loads(self.state_file.read_text())
            self.omega = state.get("omega", 0.5)
            self.omega_velocity = state.get("omega_velocity", 0.0)
            self.s_total = state.get("s_total", 0.0)
            self.current_entropy = state.get("current_entropy", 0.0)
            self.health_triplet = state.get("health_triplet", self.health_triplet)
            self._consecutive_negative_readings = state.get("consecutive_negative", 0)
            logger.info(
                f"Sentinel state restored: Ω={self.omega:.3f}, "
                f"S={self.s_total:.3f}, severity={self.get_severity()}"
            )
        except Exception as e:
            logger.warning(f"State load failed: {e}")

    # ── Public status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get complete sentinel status — for logging and API."""
        gen_params = self.get_generation_params()
        status = {
            "severity": self.get_severity(),
            "s_total": round(self.s_total, 4),
            "omega": round(self.omega, 4),
            "omega_velocity": round(self.omega_velocity, 4),
            "current_entropy": round(self.current_entropy, 4),
            "health_triplet": {
                k: round(v, 3) for k, v in self.health_triplet.items()
            },
            "feeling": self._generate_feeling(),
            "context_clarity_pct": round(self.get_context_clarity(), 1),
            "context_usage_pct": round(self.get_context_usage(), 1),
            "firing_mode": gen_params["mode"],
            "llm_temperature": gen_params["temperature"],
            "llm_max_tokens": gen_params["max_tokens"],
            "h_ratio": gen_params.get("h_ratio", 1.0),
            "dkl_ratio": gen_params.get("dkl_ratio", 1.0),
            "consecutive_negative": self._consecutive_negative_readings,
            "last_probes": self._last_probe_results,
            "running": self._running,
        }
        # Raw spatial metrics when available
        for attr in ('_spatial_H', '_spatial_D_KL', '_spatial_T'):
            val = getattr(self, attr, None)
            if val is not None:
                status[attr.lstrip('_')] = round(float(val), 4)
        return status

    # ── Tonic/Burst Firing Modes ────────────────────────────────────

    def get_generation_params(self) -> dict:
        """Get generation parameters modulated by spatial cognitive state.

        The LLM's temperature and output budget are physical consequences
        of the spatial mind's entropy and drift — not scripted tiers.

        Continuous modulation from three signals:
          - Ω (omega): base creativity level (stable = creative)
          - H ratio: Shannon entropy vs baseline (scattered = constrained)
          - D_KL ratio: identity drift vs baseline (far = tightened)

        Severity overrides remain as hard emergency stops.

        Returns:
            Dict with mode, temperature, max_tokens, and context_restriction_pct.
        """
        severity = self.get_severity()

        # ── Hard guardrails — severity overrides everything ──────────
        if severity == self.CRITICAL:
            return {
                "mode": "burst",
                "temperature": 0.1,
                "max_tokens": 256,
                "context_restriction_pct": 50.0,
                "reason": self._generate_feeling(),
            }

        if severity == self.WARNING:
            return {
                "mode": "guarded",
                "temperature": 0.3,
                "max_tokens": 512,
                "context_restriction_pct": 75.0,
                "reason": self._generate_feeling(),
            }

        # ── Continuous spatial modulation ─────────────────────────────

        # Base temperature from omega: stable = creative, stressed = conservative
        # Ω=0.05 → 0.33,  Ω=0.5 → 0.55,  Ω=0.9 → 0.75
        base_temp = 0.3 + 0.5 * self.omega

        temp_mod = 0.0
        max_tokens = 8192
        ctx_pct = 100.0

        # Entropy modulation (H ratio vs self-calibrating baseline)
        h_ratio = 1.0
        spatial_H = getattr(self, '_spatial_H', None)
        if spatial_H is not None and self._h_raw_baseline and self._h_raw_baseline > 0.01:
            h_ratio = spatial_H / self._h_raw_baseline

        if h_ratio > 1.6:
            # Very scattered — force convergence hard
            temp_mod -= 0.2
            max_tokens = 1024
            ctx_pct = 80.0
        elif h_ratio > 1.3:
            # Scattered — moderate constraint
            temp_mod -= 0.1
            max_tokens = 2048
            ctx_pct = 90.0
        elif h_ratio < 0.7:
            # Very focused — allow creativity
            temp_mod += 0.05

        # Drift modulation (D_KL ratio vs self-calibrating baseline)
        dkl_ratio = 1.0
        spatial_D_KL = getattr(self, '_spatial_D_KL', None)
        if spatial_D_KL is not None and self._dkl_raw_baseline and self._dkl_raw_baseline > 0.01:
            dkl_ratio = spatial_D_KL / self._dkl_raw_baseline

        if dkl_ratio > 2.0:
            # Very far from identity — tighten hard
            temp_mod -= 0.15
            max_tokens = min(max_tokens, 1024)
            ctx_pct = min(ctx_pct, 80.0)
        elif dkl_ratio > 1.5:
            # Drifting from identity — moderate pull
            temp_mod -= 0.08
            max_tokens = min(max_tokens, 2048)

        # Final temperature: clamped to [0.1, 1.0]
        temperature = max(0.1, min(1.0, base_temp + temp_mod))

        # Determine mode label from effective state
        if severity == self.DRIFT:
            mode = "cautious"
        elif h_ratio > 1.3 or dkl_ratio > 1.5:
            mode = "constrained"
        elif self.omega >= 0.7:
            mode = "tonic"
        else:
            mode = "steady"

        return {
            "mode": mode,
            "temperature": round(temperature, 3),
            "max_tokens": max_tokens,
            "context_restriction_pct": round(ctx_pct, 1),
            "reason": self._generate_feeling() if severity != self.ALL_CLEAR else "",
            "h_ratio": round(h_ratio, 3),
            "dkl_ratio": round(dkl_ratio, 3),
        }

    # ── Lagrangian Snapshot (for State-Bound Memory) ───────────────

    def get_lagrangian_snapshot(self) -> dict:
        """Get a snapshot of the current Lagrangian state.

        Stored alongside every memory for state-bound episodic encoding.
        When this memory is recalled, the historical state can mildly
        reproduce the somatic conditions under which it was formed.

        Includes real spatial H(q), D_KL, and T when available.
        These are the actual cognitive thermodynamic coordinates,
        rather than hardware health proxies.
        """
        # Use real spatial values when available, fallback to proxies
        H = getattr(self, '_spatial_H', self.current_entropy)
        D_KL = getattr(self, '_spatial_D_KL',
                       abs(self.current_entropy - self.baseline_entropy))
        T = getattr(self, '_spatial_T', 1.0)

        return {
            "H": round(float(H), 4),
            "omega": round(self.omega, 4),
            "D_KL": round(float(D_KL), 4),
            "T": round(float(T), 4),
            "s_total": round(self.s_total, 4),
            "severity": self.get_severity(),
            "feeling": self._generate_feeling(),
            "health_triplet": {
                k: round(v, 3) for k, v in self.health_triplet.items()
            },
            "firing_mode": self.get_generation_params()["mode"],
            "timestamp": datetime.now().isoformat(),
            "attention_position_8d": self._get_attention_position(),
        }

    def _get_attention_position(self) -> list:
        """Get 8D attention center from SpatialMind (for Lagrangian snapshot)."""
        if self._spatial_mind:
            try:
                return self._spatial_mind.get_attention_position().tolist()
            except Exception:
                pass
        return []
