"""Probe-based recovery and independent operational fault severity."""
import math

LEVELS = ("all_clear", "drift", "warning", "critical")


class SeverityRecovery:
    def __init__(self, recovery_cycles=3):
        self.level = "all_clear"
        self.healthy_cycles = 0
        self.recovery_cycles = recovery_cycles

    def observe(self, level):
        if LEVELS.index(level) >= LEVELS.index(self.level):
            self.level = level
            self.healthy_cycles = 0
        else:
            self.healthy_cycles += 1
            if self.healthy_cycles >= self.recovery_cycles:
                self.level = level
                self.healthy_cycles = 0
        return self.level


def operational_faults(probes):
    """Resource/store failures cannot be normalized away by a spatial baseline.

    CPU utilization is deliberately excluded: native inference may use a CPU
    fully while functioning correctly. These values are existing probe scores,
    not calibrated probabilities or authorization signals.
    """
    faults = {}
    for key in ("memory_pressure", "disk_space", "memory_db_health", "consciousness_alive"):
        value = probes.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            faults[key] = "warning"
        elif value <= 0.3:
            faults[key] = "critical"
        elif value <= 0.5:
            faults[key] = "warning"
    return faults


def maximum_severity(*levels):
    return max(levels, key=LEVELS.index)
