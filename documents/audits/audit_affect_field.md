# Affect Field Audit

**File:** `core/affect_field.py`

---

### Overview
The `AffectField` module implements an 8‑dimensional Plutchik emotion field that overlays the main cognitive spatial manifold. It models emotional traces as *wave packets* that diffuse, decay, and interfere, providing a dynamic steering force and memory‑reactivation signals for the Helix system.

---

### Key Constants (lines 42‑66)
```python
42-66: AFFECT_DIMS = 8
# Primary Plutchik emotions
PLUTCHIK_PRIMARIES = ["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"]
# Neutral baselines for each dimension
NEUTRAL_BASELINES = {"joy":0.5, "trust":0.5, "fear":0.0, "surprise":0.0, "sadness":0.0, "disgust":0.0, "anger":0.0, "anticipation":0.5}
# Diffusion rates – higher = faster fade
DIFFUSION_RATES = {"joy":0.008, "trust":0.005, "fear":0.06, "surprise":0.08, "sadness":0.008, "disgust":0.03, "anger":0.05, "anticipation":0.01}
# Phase frequencies for interference
BASE_FREQUENCIES = {"joy":0.04, "trust":0.02, "fear":0.10, "surprise":0.12, "sadness":0.03, "disgust":0.05, "anger":0.08, "anticipation":0.04}
COMPOSITE_FREQUENCY = sum(BASE_FREQUENCIES.values()) / len(BASE_FREQUENCIES)
```
**What:** Sets dimensionality, emotion names, neutral baselines, per‑dimension diffusion, and interference frequencies.
**Why:** Encodes psychological intuition (e.g., trust persists longer than fear) directly into simulation parameters, allowing the field to exhibit realistic emotional dynamics.

---

### WavePacket Dataclass (lines 100‑126)
```python
100-126: @dataclass
class WavePacket:
    """A single emotional trace in 8D Plutchik affect‑space.
    Attributes include position (8‑D vector), initial_amplitude, deposit_pulse,
    anchor_memories, blended_memories, sigma (per‑dim spread), and a cached _amplitude.
    """
    position: List[float]
    initial_amplitude: float
    deposit_pulse: int
    anchor_memories: Set[str] = field(default_factory=set)
    blended_memories: Dict[str, float] = field(default_factory=dict)
    sigma: List[float] = field(default_factory=lambda: [INITIAL_SIGMA] * AFFECT_DIMS)
    _amplitude: Optional[float] = field(default=None, repr=False)
```
**What:** Stores all state needed for diffusion, decay, and interference.
**Why:** Separates *raw emotion* (position) from *temporal uncertainty* (sigma) and *semantic linkage* (memories) to support later memory‑reactivation logic.

---

### WavePacket Helper Methods (lines 130‑210)
- `__post_init__` pads missing dimensions.
- `intensity` computes deviation from neutral baselines (scaled by 2).
- `importance` caps anchor‑memory count at `IMPORTANCE_MATURITY`.
- `current_phase` returns `(pulse - deposit_pulse) * COMPOSITE_FREQUENCY` modulo `2π`.
- `evolve` diffuses sigma per `DIFFUSION_RATES` and applies SDFT‑style decay where halflife is boosted by intensity and importance.
- `spatial_contribution` evaluates anisotropic Gaussian contribution at a sample position.
- `is_alive` checks amplitude against `PRUNE_THRESHOLD`.
- Serialization via `to_dict` / `from_dict`.

**Why:** Mirrors physical diffusion‑decay processes, letting emotions fade naturally while still being *reinforced* by anchored memories (SDFT bonus).

---

### InterferenceResult Dataclass (lines 232‑252)
Collects the outcome of sampling the field: intensity, packet count, steering vector, surfaced memories, reactivation strength, dominant affect, and a cognitive‑diversity signal.

---

### AffectField Core (lines 258‑335)
```python
258-335: class AffectField:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.packets: List[WavePacket] = []
        self.current_pulse: int = 0
        self._prev_s_total = 0.0
        self._prev_omega = 0.5
        self._stagnation_counter = 0
        self._summary_cache = None
        self._summary_cache_pulse = -1
        self._load_state()
```
**What:** Initializes state, loads persisted packets, and sets up caches.
**Why:** Provides deterministic behaviour across restarts and enables cheap summary recomputation.

---

### Deposit Logic (lines 295‑354)
- Stores stagnation counter.
- Maps Lagrangian snapshot → Plutchik vector via `_lagrangian_to_plutchik`.
- Calculates intensity from deviation; amplitude = `max(0.1, intensity)`.
- Creates a `WavePacket` (anchor memories optional).
- Enforces hard cap `MAX_PACKETS` by pruning lowest‑amplitude packets.

**Why:** Guarantees only *meaningful* emotional events generate packets and prevents unbounded memory growth.

---

### Lagrangian → Plutchik Mapping (lines 355‑386)
```python
367-385: omega = snapshot.get("omega",0.5)
H = snapshot.get("H",0.0)
D_KL = snapshot.get("D_KL",0.0)
s_total = snapshot.get("s_total",0.0)
# Deltas from previous pulse
delta_s = s_total - self._prev_s_total
omega_vel = omega - self._prev_omega
return [
    _clamp(omega),                      # joy
    _clamp(1.0 - D_KL),                 # trust
    _clamp(max(0.0, delta_s) * 5.0),    # fear
    _clamp(abs(delta_s) * 5.0),         # surprise
    _clamp(max(0.0, -omega_vel) *10.0), # sadness
    _clamp(self._stagnation_counter/10.0),
    _clamp(H * (1.0 - omega) * 2.0),    # anger
    _clamp(max(0.0, omega_vel) *10.0),  # anticipation
]
```
**What:** Deterministically translates system‑level Lagrangian metrics into the 8‑D emotional space.
**Why:** Provides a *single source of truth* for affect; all downstream modules (steering, memory reactivation) rely on this mapping.

---

### Evolution Step (lines 389‑410)
- Increment pulse, clear summary cache.
- For each packet, call `evolve` (diffuse + decay).
- Blend accessed memories into packets whose amplitude exceeds `BLEND_AMPLITUDE_THRESHOLD`.
- Prune dead packets.

**Why:** Simulates continuous emotional diffusion and ties recent memory accesses to emotional reinforcement.

---

### Sampling / Interference (lines 414‑485)
- If no packets, return empty result.
- Determine sample position (default: current affect summary via `_compute_affect_summary`).
- For each packet compute `spatial_contribution` and phase factor `cos(phase)` → contribution.
- Aggregate field intensity, positive‑contributing packets, steering vector (weighted blend), and optionally surface memories when intensity & overlap exceed thresholds.
- Compute dominant affect and cognitive‑diversity signal.

**Why:** Generates a *steering vector* that other subsystems (e.g., `SpatialMind`) use to bias attention, and surfaces memories when emotional intensity aligns with retrieval cues.

---

### Helper Methods (lines 486‑608)
- `_compute_steering_vector` – weighted average of positions by absolute spatial contribution.
- `_compute_semantic_overlap` – simple co‑retrieval overlap metric for memory surfacing.
- `_collect_surfaced_memories` – dedupes memory IDs.
- `_compute_affect_summary` – caches weighted averages; returns dominant affect and total amplitude.
- `_cognitive_diversity_signal` – boredom/novelty estimate based on disgust & anticipation.

**Why:** These utilities keep the main sampling loop clean and expose high‑level signals for downstream decision‑making.

---

### Persistence (lines 631‑674)
- `save_state` writes JSON with schema version, pulse, previous Lagrangian values, stagnation counter, and serialized packets.
- `_load_state` restores these values, handling missing files gracefully.

**Why:** Guarantees that affect dynamics survive restarts, essential for long‑running cognitive agents.

---

### Mermaid Diagram – Affect Field Workflow
```mermaid
flowchart TD
    Init[Init AffectField] --> Deposit
    Deposit -->|New Lagrangian| CreatePacket[WavePacket]
    CreatePacket --> Append[Add to packets]
    Append --> Evolve[Pulse Evolution]
    Evolve --> Diffuse[Diffusion per dimension]
    Evolve --> Decay[Decay via SDFT]
    Evolve --> Prune[Prune dead packets]
    Evolve --> Sample[Sampling]
    Sample --> Steering[Compute steering vector]
    Sample --> React[Memory reactivation (if intensity high)]
    Steering -->|Feedback| SpatialMind[SpatialMind integration]
    React -->|Surface| Preconscious[Pre‑conscious injection]
```
The diagram shows the full lifecycle from deposit to sampling, highlighting where the field influences other subsystems.

---

### Prompt‑Injection Example
When `sample` returns a non‑empty `surfaced_memories` list, the pre‑conscious module injects each memory as a raw context line:
```
MEMORY: "I once felt a surge of joy after solving a puzzle" (ID: mem_042)
```
These lines become part of the LLM prompt for the next pulse, allowing emotions to directly bias language generation.

---

### Open Questions / Clarifications
- **Configurable Parameters:** Diffusion rates, decay baselines, and thresholds are hard‑coded. Should they be exposed via a config file or environment variables for easy experimentation?
- **Scalability:** The current O(P) per‑pulse complexity may become costly at `MAX_PACKETS=500`. Would a spatial index (e.g., KD‑tree) improve sampling performance?
- **Persistence Format:** JSON is convenient but lacks schema validation. Would using a versioned binary format (e.g., protobuf) be beneficial for future extensions?

---

*End of Affect Field audit.*

---

*This file now contains the full line‑by‑line audit for `core/affect_field.py`.*
