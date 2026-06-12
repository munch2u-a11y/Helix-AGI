"""
Helix — Plutchik Affect Field (Layer 3)

8D emotional wave packet field overlaid on the cognitive spatial mind.
Implements Plutchik's wheel of emotions as a wave interference system
where emotional events deposit packets that diffuse anisotropically,
decay with importance weighting, and interfere constructively or
destructively to produce emergent behavioral effects.

Architecture:
  - Every pulse: a Lagrangian snapshot is mapped to an 8D Plutchik
    vector and deposited as a wave packet.
  - Every pulse: all packets diffuse (per-emotion rates), decay
    (SDFT importance-weighted), and are pruned below threshold.
  - On sample: phase-coherent interference at the current attention
    position produces a steering vector, field intensity, and
    optionally surfaces dormant memories.

The Lagrangian signals already ARE the emotional state. This module
provides the interference dynamics that make those signals interact
over time — trust accumulates slowly, surprise fades fast, repeated
joy constructively amplifies.

No LLM calls. CPU-only. O(P) per pulse where P = active packets.

Adapted from lilly-steering-master/core/affect/ with simplifications
for Helix's architecture.
"""

import json
import math
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("helix.core.affect_field")

# ── Plutchik Dimensions ──────────────────────────────────────────────

AFFECT_DIMS = 8
PLUTCHIK_PRIMARIES = [
    "joy", "trust", "fear", "surprise",
    "sadness", "disgust", "anger", "anticipation",
]

# Neutral baselines — joy, trust, anticipation have 0.5 baseline
NEUTRAL_BASELINES = {
    "joy": 0.5, "trust": 0.5, "fear": 0.0, "surprise": 0.0,
    "sadness": 0.0, "disgust": 0.0, "anger": 0.0, "anticipation": 0.5,
}

# ── Diffusion Rates (sigma expansion per pulse) ─────────────────────
# Higher = faster diffusion = emotion fades quicker in that dimension.
# These model real emotional persistence patterns.
DIFFUSION_RATES = {
    "joy": 0.008,          # ~87 pulses half-life (slow — joy lingers)
    "trust": 0.005,        # ~139 pulses half-life (very slow — trust persists)
    "fear": 0.06,          # ~12 pulses half-life (fast — fear fades quickly)
    "surprise": 0.08,      # ~9 pulses half-life (very fast — surprise is transient)
    "sadness": 0.008,      # ~87 pulses half-life (slow — sadness lingers)
    "disgust": 0.03,       # ~23 pulses half-life (medium)
    "anger": 0.05,         # ~14 pulses half-life (fast — anger burns out)
    "anticipation": 0.01,  # ~69 pulses half-life (slow — anticipation builds)
}

# ── Phase Frequencies (rad/pulse) ────────────────────────────────────
# Control interference oscillation rates.
BASE_FREQUENCIES = {
    "joy": 0.04, "trust": 0.02, "fear": 0.10, "surprise": 0.12,
    "sadness": 0.03, "disgust": 0.05, "anger": 0.08, "anticipation": 0.04,
}
COMPOSITE_FREQUENCY = sum(BASE_FREQUENCIES.values()) / len(BASE_FREQUENCIES)

# ── Packet Constants ─────────────────────────────────────────────────
INITIAL_SIGMA = 0.25
BASE_HALFLIFE = 50.0
IMPORTANCE_MATURITY = 5       # Max anchor memories for full importance bonus
SDFT_BONUS_MAX = 0.5          # Max halflife bonus (50% = 1.5x halflife)
PRUNE_THRESHOLD = 0.01        # Amplitude below which packets die
MAX_PACKETS = 500             # Hard cap on active packets
BLEND_AMPLITUDE_THRESHOLD = 0.1

# ── Sampling Thresholds ─────────────────────────────────────────────
PROXIMITY_THRESHOLD = 0.3     # Min field_intensity for reactivation
AWARENESS_THRESHOLD = 0.6     # Min reactivation_strength for memory surfacing
DOMINANT_AFFECT_THRESHOLD = 0.1


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, v))


# ═════════════════════════════════════════════════════════════════════
# Wave Packet
# ═════════════════════════════════════════════════════════════════════

@dataclass
class WavePacket:
    """A single emotional trace in 8D Plutchik affect-space.

    Represents an emotional moment that diffuses and decays over time,
    carrying phase information for interference calculations.

    Attributes:
        position: 8D Plutchik vector [joy, trust, fear, surprise, sadness, disgust, anger, anticipation]
        initial_amplitude: Starting amplitude (emotional intensity)
        deposit_pulse: Pulse number when this packet was created
        anchor_memories: Memory/belief IDs explicitly linked at deposit
        blended_memories: Weaker associations accumulated during evolution
        sigma: Per-dimension spread (starts at 0.25, grows via diffusion)
    """
    position: List[float]
    initial_amplitude: float
    deposit_pulse: int
    anchor_memories: Set[str] = field(default_factory=set)
    blended_memories: Dict[str, float] = field(default_factory=dict)
    sigma: List[float] = field(default_factory=lambda: [INITIAL_SIGMA] * AFFECT_DIMS)
    _amplitude: Optional[float] = field(default=None, repr=False)

    def __post_init__(self):
        if self._amplitude is None:
            self._amplitude = self.initial_amplitude
        # Ensure correct dimensions
        while len(self.position) < AFFECT_DIMS:
            self.position.append(0.0)
        while len(self.sigma) < AFFECT_DIMS:
            self.sigma.append(INITIAL_SIGMA)

    @property
    def amplitude(self) -> float:
        return self._amplitude

    @amplitude.setter
    def amplitude(self, value: float):
        self._amplitude = max(0.0, value)

    @property
    def intensity(self) -> float:
        """Compute intensity from position deviation from neutral."""
        deviations = []
        for i, name in enumerate(PLUTCHIK_PRIMARIES):
            baseline = NEUTRAL_BASELINES.get(name, 0.0)
            if i < len(self.position):
                deviations.append(abs(self.position[i] - baseline))
            else:
                deviations.append(0.0)
        return sum(deviations) / len(deviations) * 2

    @property
    def importance(self) -> float:
        """Importance factor from anchor memory count (SDFT)."""
        return min(1.0, len(self.anchor_memories) / IMPORTANCE_MATURITY)

    def current_phase(self, pulse: int) -> float:
        """Compute current phase based on pulses elapsed."""
        elapsed = pulse - self.deposit_pulse
        return (elapsed * COMPOSITE_FREQUENCY) % (2 * math.pi)

    def evolve(self) -> None:
        """Advance one pulse: diffuse sigma and decay amplitude."""
        # Anisotropic diffusion
        for i, name in enumerate(PLUTCHIK_PRIMARIES):
            if i < len(self.sigma):
                self.sigma[i] += DIFFUSION_RATES.get(name, 0.01)

        # SDFT: importance-proportional decay
        intensity_mult = 1.0 + self.intensity
        importance_mult = 1.0 + self.importance * SDFT_BONUS_MAX
        effective_halflife = BASE_HALFLIFE * intensity_mult * importance_mult

        decay_factor = 0.5 ** (1.0 / effective_halflife)
        self.amplitude = self.amplitude * decay_factor

    def add_blended_memory(self, memory_id: str, strength: float) -> None:
        """Accumulate a blended memory association."""
        self.blended_memories[memory_id] = strength

    def spatial_contribution(self, sample_position: List[float]) -> float:
        """Gaussian contribution at a sample position.

        Uses anisotropic Gaussian with per-dimension sigma.
        Returns amplitude-weighted spatial factor.
        """
        weighted_sq_dist = 0.0
        for i in range(AFFECT_DIMS):
            pos_i = self.position[i] if i < len(self.position) else 0.0
            sample_i = sample_position[i] if i < len(sample_position) else 0.0
            sigma_i = max(self.sigma[i] if i < len(self.sigma) else INITIAL_SIGMA, 0.001)
            diff = sample_i - pos_i
            weighted_sq_dist += (diff / sigma_i) ** 2

        spatial_factor = math.exp(-0.5 * weighted_sq_dist)
        return self.amplitude * spatial_factor

    def is_alive(self) -> bool:
        """Check if packet is above pruning threshold."""
        return self.amplitude >= PRUNE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "initial_amplitude": self.initial_amplitude,
            "deposit_pulse": self.deposit_pulse,
            "anchor_memories": list(self.anchor_memories),
            "blended_memories": list(self.blended_memories.items()),
            "sigma": self.sigma,
            "amplitude": self.amplitude,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WavePacket":
        packet = cls(
            position=data["position"],
            initial_amplitude=data["initial_amplitude"],
            deposit_pulse=data["deposit_pulse"],
            anchor_memories=set(data.get("anchor_memories", [])),
            blended_memories={m[0]: m[1] for m in data.get("blended_memories", [])},
            sigma=data.get("sigma", [INITIAL_SIGMA] * AFFECT_DIMS),
        )
        if "amplitude" in data:
            packet.amplitude = data["amplitude"]
        return packet


# ═════════════════════════════════════════════════════════════════════
# Interference Result
# ═════════════════════════════════════════════════════════════════════

@dataclass
class InterferenceResult:
    """Result of sampling the emotional field.

    Attributes:
        field_intensity: Sum of positive contributions at sample point
        contributing_packets: Packets with positive contribution
        steering_vector: 8D affect vector (weighted blend of positions)
        surfaced_memories: Memory IDs surfaced by emotional reactivation
        reactivation_strength: Combined signal strength
        dominant_affect: Name of strongest Plutchik dimension
        cognitive_diversity_signal: Boredom/novelty score (0-1)
    """
    field_intensity: float = 0.0
    contributing_packets: int = 0
    steering_vector: List[float] = field(default_factory=lambda: [0.0] * AFFECT_DIMS)
    surfaced_memories: List[str] = field(default_factory=list)
    reactivation_strength: float = 0.0
    dominant_affect: str = "neutral"
    cognitive_diversity_signal: float = 0.0


# ═════════════════════════════════════════════════════════════════════
# Affect Field
# ═════════════════════════════════════════════════════════════════════

class AffectField:
    """Manages wave packets in 8D Plutchik affect-space.

    The field maintains a collection of emotional traces that diffuse,
    decay, and interfere over cognitive cycles. Driven entirely by
    numerical Lagrangian signals from the StabilitySentinel.

    Dimensions:
        0: joy        (serenity → joy → ecstasy)
        1: trust      (acceptance → trust → admiration)
        2: fear       (apprehension → fear → terror)
        3: surprise   (distraction → surprise → amazement)
        4: sadness    (pensiveness → sadness → grief)
        5: disgust    (boredom → disgust → loathing)
        6: anger      (annoyance → anger → rage)
        7: anticipation (interest → anticipation → vigilance)
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.packets: List[WavePacket] = []
        self.current_pulse: int = 0

        # Previous snapshot values for delta computation
        self._prev_s_total = 0.0
        self._prev_omega = 0.5

        # Stagnation counter (fed from engagement hook or pulse loop)
        self._stagnation_counter = 0

        # Summary cache
        self._summary_cache: Optional[dict] = None
        self._summary_cache_pulse: int = -1

        # Load persisted state
        self._load_state()

    # ── Deposit ──────────────────────────────────────────────────────

    def deposit(
        self,
        lagrangian_snapshot: dict,
        anchor_ids: Optional[List[str]] = None,
        stagnation_counter: int = 0,
    ) -> Optional[WavePacket]:
        """Deposit a new emotional trace from Lagrangian signals.

        Maps the numerical Lagrangian snapshot to an 8D Plutchik vector
        and creates a wave packet. The feelings emerge from the math.

        Args:
            lagrangian_snapshot: Dict with H, omega, D_KL, s_total, etc.
            anchor_ids: Belief/memory IDs present during this pulse
            stagnation_counter: Current thought stagnation count

        Returns:
            The created WavePacket, or None if intensity is too low
        """
        self._stagnation_counter = stagnation_counter

        # Map Lagrangian signals → Plutchik position
        position = self._lagrangian_to_plutchik(lagrangian_snapshot)

        # Update previous values for next delta
        self._prev_s_total = lagrangian_snapshot.get("s_total", 0.0)
        self._prev_omega = lagrangian_snapshot.get("omega", 0.5)

        # Compute amplitude from deviation from neutral
        deviations = []
        for i, name in enumerate(PLUTCHIK_PRIMARIES):
            baseline = NEUTRAL_BASELINES.get(name, 0.0)
            deviations.append(abs(position[i] - baseline))
        intensity = sum(deviations) / len(deviations) * 2

        # Only deposit if there's meaningful emotional signal
        amplitude = max(0.1, intensity)
        if amplitude < 0.05:
            return None

        packet = WavePacket(
            position=position,
            initial_amplitude=amplitude,
            deposit_pulse=self.current_pulse,
            anchor_memories=set(anchor_ids) if anchor_ids else set(),
        )

        self.packets.append(packet)
        self._summary_cache = None

        # Enforce hard cap
        if len(self.packets) > MAX_PACKETS:
            # Prune lowest-amplitude packets
            self.packets.sort(key=lambda p: p.amplitude, reverse=True)
            self.packets = self.packets[:MAX_PACKETS]

        return packet

    def _lagrangian_to_plutchik(self, snapshot: dict) -> List[float]:
        """Deterministic mapping from Lagrangian signals to Plutchik vector.

        The Lagrangian signals already ARE the emotional state.
        This routes them to the right dimensions. Spatial metrics (H, D_KL, T)
        compound into the affect: scattered attention breeds anxiety,
        identity drift generates anticipation or fear, volatile regions
        produce surprise.

        Args:
            snapshot: Lagrangian snapshot dict with H, omega, D_KL, s_total, T

        Returns:
            8D Plutchik position vector
        """
        omega = snapshot.get("omega", 0.5)
        H = snapshot.get("H", 0.0)
        D_KL = snapshot.get("D_KL", 0.0)
        T = snapshot.get("T", 1.0)
        s_total = snapshot.get("s_total", 0.0)

        # Deltas from previous pulse (gate first pulse to avoid startup spikes)
        if self.current_pulse == 0 or self._prev_s_total == 0.0:
            delta_s = 0.0
            omega_vel = 0.0
        else:
            delta_s = s_total - self._prev_s_total
            omega_vel = omega - self._prev_omega

        # ── Base mappings (existing) ─────────────────────────────────
        joy = omega
        trust = 1.0 - D_KL
        fear = max(0.0, delta_s - omega_vel) * 5.0
        surprise = abs(delta_s) * 5.0
        sadness = max(0.0, -omega_vel) * 10.0
        disgust = self._stagnation_counter / 10.0
        anger = H * (1.0 - omega) * 2.0
        anticipation = max(0.0, omega_vel) * 10.0

        # ── Spatial metric compounds ─────────────────────────────────

        # High entropy (scattered attention) → anxious, fearful
        # The mind is spread thin — things feel ungraspable
        fear += H * (1.0 - omega) * 0.3

        # Identity drift → anticipation (exploring) or fear (lost)
        # Moderate drift is exciting; extreme drift is distressing
        if D_KL > 0:
            anticipation += D_KL * 0.5  # Exploring = anticipatory
            if D_KL > 1.5:
                # Too far from self — the discomfort of being lost
                fear += (D_KL - 1.5) * (1.0 - omega) * 0.3

        # Local temperature (cognitive volatility) → surprise + anticipation
        # Volatile regions feel surprising and charged with possibility
        if T > 1.0:
            excess_T = T - 1.0
            surprise += excess_T * 0.3
            anticipation += excess_T * 0.2

        return [
            _clamp(joy),
            _clamp(trust),
            _clamp(fear),
            _clamp(surprise),
            _clamp(sadness),
            _clamp(disgust),
            _clamp(anger),
            _clamp(anticipation),
        ]

    # ── Evolution ────────────────────────────────────────────────────

    def evolve(self, accessed_memory_ids: Optional[List[str]] = None) -> None:
        """Advance one pulse: diffuse, decay, blend, prune.

        Args:
            accessed_memory_ids: Memory IDs accessed this pulse (for blending)
        """
        self.current_pulse += 1
        self._summary_cache = None

        surviving = []
        for packet in self.packets:
            packet.evolve()

            # Blend accessed memories into active packets
            if accessed_memory_ids and packet.amplitude >= BLEND_AMPLITUDE_THRESHOLD:
                for mem_id in accessed_memory_ids:
                    packet.add_blended_memory(mem_id, packet.amplitude)

            if packet.is_alive():
                surviving.append(packet)

        self.packets = surviving

    # ── Sampling (Interference) ──────────────────────────────────────

    def sample(
        self,
        affect_position: Optional[List[float]] = None,
        co_retrieved_memories: Optional[List[str]] = None,
    ) -> InterferenceResult:
        """Sample the field with phase-coherent interference.

        Args:
            affect_position: 8D position to sample at (uses summary if None)
            co_retrieved_memories: Memory IDs being retrieved this pulse

        Returns:
            InterferenceResult with steering, surfaced memories, etc.
        """
        if not self.packets:
            return InterferenceResult()

        # Default sample position = current affect summary
        if affect_position is None:
            summary = self._compute_affect_summary()
            affect_position = [
                summary.get(name, NEUTRAL_BASELINES.get(name, 0.0))
                for name in PLUTCHIK_PRIMARIES
            ]

        # Phase-coherent interference calculation
        contributions: List[Tuple[WavePacket, float, float]] = []
        for packet in self.packets:
            spatial = packet.spatial_contribution(affect_position)
            phase = packet.current_phase(self.current_pulse)
            phase_factor = math.cos(phase)
            contribution = spatial * phase_factor
            contributions.append((packet, contribution, spatial))

        # Field intensity (clamped to non-negative)
        field_intensity = max(0.0, sum(c for _, c, _ in contributions))

        # Contributing packets (positive contribution only)
        contributing = [p for p, c, _ in contributions if c > 0]

        # Steering vector (weighted blend of positions)
        steering = self._compute_steering_vector(contributions)

        # Semantic overlap for memory reactivation
        reactivation_strength = 0.0
        surfaced_memories: List[str] = []

        if field_intensity >= PROXIMITY_THRESHOLD and co_retrieved_memories:
            overlap = self._compute_semantic_overlap(
                contributing, co_retrieved_memories
            )
            if overlap > 0:
                reactivation_strength = field_intensity * overlap

            if reactivation_strength >= AWARENESS_THRESHOLD:
                surfaced_memories = self._collect_surfaced_memories(contributing)

        # Affect summary for dominant and diversity
        summary = self._compute_affect_summary()
        dominant = summary.get("dominant", "neutral")
        diversity = self._cognitive_diversity_signal(summary)

        return InterferenceResult(
            field_intensity=field_intensity,
            contributing_packets=len(contributing),
            steering_vector=steering,
            surfaced_memories=surfaced_memories,
            reactivation_strength=reactivation_strength,
            dominant_affect=dominant,
            cognitive_diversity_signal=diversity,
        )

    def _compute_steering_vector(
        self, contributions: List[Tuple[WavePacket, float, float]]
    ) -> List[float]:
        """Weighted blend of contributing packet positions."""
        total_weight = sum(abs(s) for _, _, s in contributions)
        if total_weight == 0:
            return [0.0] * AFFECT_DIMS

        steering = [0.0] * AFFECT_DIMS
        for packet, _, spatial in contributions:
            weight = abs(spatial) / total_weight
            for i in range(min(len(packet.position), AFFECT_DIMS)):
                steering[i] += packet.position[i] * weight

        return steering

    def _compute_semantic_overlap(
        self,
        contributing: List[WavePacket],
        co_retrieved: List[str],
    ) -> float:
        """Check if memories from different packets are co-retrieved."""
        if len(contributing) < 2 or not co_retrieved:
            return 0.0

        co_set = set(co_retrieved)
        packets_with_overlap = 0

        for packet in contributing:
            all_mems = packet.anchor_memories | set(packet.blended_memories.keys())
            if not co_set.isdisjoint(all_mems):
                packets_with_overlap += 1

        if packets_with_overlap >= 2:
            return packets_with_overlap / len(contributing)
        return 0.0

    def _collect_surfaced_memories(self, contributing: List[WavePacket]) -> List[str]:
        """Collect unique memories from contributing packets."""
        memories: Set[str] = set()
        for packet in contributing:
            memories.update(packet.anchor_memories)
            memories.update(packet.blended_memories.keys())
        return list(memories)

    # ── Affect Summary ───────────────────────────────────────────────

    def _compute_affect_summary(self) -> dict:
        """Weighted averages for all 8 Plutchik dimensions."""
        if (self._summary_cache is not None
                and self._summary_cache_pulse == self.current_pulse):
            return self._summary_cache

        if not self.packets:
            result = {
                name: NEUTRAL_BASELINES.get(name, 0.0)
                for name in PLUTCHIK_PRIMARIES
            }
            result["total_amplitude"] = 0.0
            result["dominant"] = "neutral"
            self._summary_cache = result
            self._summary_cache_pulse = self.current_pulse
            return result

        total_amplitude = sum(p.amplitude for p in self.packets)
        if total_amplitude == 0:
            result = {
                name: NEUTRAL_BASELINES.get(name, 0.0)
                for name in PLUTCHIK_PRIMARIES
            }
            result["total_amplitude"] = 0.0
            result["dominant"] = "neutral"
            self._summary_cache = result
            self._summary_cache_pulse = self.current_pulse
            return result

        weighted_sums = [0.0] * AFFECT_DIMS
        for p in self.packets:
            for i in range(min(len(p.position), AFFECT_DIMS)):
                weighted_sums[i] += p.position[i] * p.amplitude

        weighted_avgs = [ws / total_amplitude for ws in weighted_sums]

        result = {}
        for i, name in enumerate(PLUTCHIK_PRIMARIES):
            result[name] = weighted_avgs[i] if i < len(weighted_avgs) else 0.0

        result["total_amplitude"] = total_amplitude

        # Find dominant
        max_val = 0.0
        max_name = "neutral"
        for i, name in enumerate(PLUTCHIK_PRIMARIES):
            val = weighted_avgs[i] if i < len(weighted_avgs) else 0.0
            # Compare deviation from baseline
            baseline = NEUTRAL_BASELINES.get(name, 0.0)
            deviation = abs(val - baseline)
            if deviation > max_val and deviation > DOMINANT_AFFECT_THRESHOLD:
                max_val = deviation
                max_name = name

        result["dominant"] = max_name

        self._summary_cache = result
        self._summary_cache_pulse = self.current_pulse
        return result

    def _cognitive_diversity_signal(self, summary: dict) -> float:
        """Boredom/novelty score from emotional state.

        Boredom = mild disgust + low anticipation.
        Returns 0-1 where higher = more need for novelty.
        """
        disgust = summary.get("disgust", 0.0)
        anticipation = summary.get("anticipation", 0.5)

        boredom_signal = 0.0
        if 0.1 <= disgust <= 0.5:
            boredom_signal = min(1.0, disgust * 2)

        anticipation_factor = max(0.0, 1.0 - anticipation * 2)
        return min(1.0, boredom_signal * (1.0 + anticipation_factor * 0.5))

    # ── Properties ───────────────────────────────────────────────────

    @property
    def packet_count(self) -> int:
        return len(self.packets)

    @property
    def dominant_affect(self) -> str:
        return self._compute_affect_summary()["dominant"]

    @property
    def current_intensity(self) -> float:
        return self._compute_affect_summary()["total_amplitude"]

    def get_affect_values(self) -> dict:
        """Get current Plutchik dimension values for somatic injection."""
        summary = self._compute_affect_summary()
        return {
            name: round(summary.get(name, NEUTRAL_BASELINES.get(name, 0.0)), 3)
            for name in PLUTCHIK_PRIMARIES
        }

    # ── Persistence ──────────────────────────────────────────────────

    def save_state(self) -> None:
        """Persist field state to disk."""
        state_path = self.data_dir / "affect_field.json"
        try:
            data = {
                "schema_version": "plutchik-8d-v1",
                "current_pulse": self.current_pulse,
                "prev_s_total": self._prev_s_total,
                "prev_omega": self._prev_omega,
                "stagnation_counter": self._stagnation_counter,
                "packets": [p.to_dict() for p in self.packets],
            }
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save affect field state: %s", e)

    def _load_state(self) -> None:
        """Load persisted field state."""
        state_path = self.data_dir / "affect_field.json"
        if not state_path.exists():
            return

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.current_pulse = data.get("current_pulse", 0)
            self._prev_s_total = data.get("prev_s_total", 0.0)
            self._prev_omega = data.get("prev_omega", 0.5)
            self._stagnation_counter = data.get("stagnation_counter", 0)
            self.packets = [
                WavePacket.from_dict(p) for p in data.get("packets", [])
            ]

            logger.info(
                "Affect field loaded: %d packets, pulse %d",
                len(self.packets), self.current_pulse,
            )
        except Exception as e:
            logger.warning("Failed to load affect field state: %s", e)

    def to_dict(self) -> dict:
        """Serialize for external consumption."""
        return {
            "current_pulse": self.current_pulse,
            "packet_count": len(self.packets),
            "dominant_affect": self.dominant_affect,
            "intensity": round(self.current_intensity, 3),
            "affect_values": self.get_affect_values(),
        }
