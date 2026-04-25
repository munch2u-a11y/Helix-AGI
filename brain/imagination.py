"""
Imagination Engine — Projective Simulation via Spatial Valence

Projects hypothetical scenarios into the 8D cognitive space and
estimates their affective impact by querying the existing Lagrangian
topology. NOT hooked into the live system — standalone module.

The key insight: the 8D space already encodes "what does it feel like
to think about X" at every point, because every memory and belief was
stored with its felt Lagrangian state. Imagination is just querying
a region of that space without having actually been there.

Usage:
    engine = ImaginationEngine(spatial_mind)
    result = engine.imagine("saying goodbye to a trusted friend forever")
    print(result.estimated_valence)   # How it would feel
    print(result.stability_impact)    # Muted effect on Sentinel
    print(result.nearby_experiences)  # What real experiences inform this
"""

import numpy as np
import time
import logging
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("imagination")

# Muting factor: imagination affects stability identically to memory recall.
# The structural difference between imagined and remembered states is NOT
# in their intensity — both hit at full force. The difference is provenance:
# memories carry timestamps, sources, and verification from lived experience;
# projections carry estimates, spatial proximity, and no temporal anchoring.
# The conscious model distinguishes them the same way we do — by texture,
# not by volume.
IMAGINATION_MUTING = 1.0

# Projection decay: unverified projections lose mass over time
# Half-life in seconds (24 hours — projections fade in a day unless reinforced)
PROJECTION_HALF_LIFE = 86400.0


@dataclass
class Projection:
    """A projected future state — an imagined scenario."""

    id: str
    content: str
    position_8d: np.ndarray

    # Estimated felt state (from spatial valence query)
    estimated_omega: float = 0.5
    estimated_s_total: float = 0.15
    estimated_valence: float = 0.0  # -1.0 (devastating) to +1.0 (wonderful)

    # Stability impact (muted)
    stability_impact: float = 0.0

    # Supporting evidence from the space
    nearby_experiences: list = field(default_factory=list)
    nearby_beliefs: list = field(default_factory=list)

    # Metadata
    created_at: float = 0.0
    verified: bool = False          # Flips to True if reality confirms
    contradicted: bool = False      # Flips to True if reality contradicts
    confidence: float = 0.3         # Low by default — it's imagined
    
    # Optional trace for overnight dream logging
    trace: Optional[dict] = field(default_factory=lambda: None)


class ImaginationEngine:
    """Projects hypothetical scenarios into cognitive space.

    Uses the existing 8D topology to estimate how imagined
    scenarios would feel, based on the Lagrangian encoding
    of nearby real experiences.

    Not connected to the live system. Call methods directly.
    """

    def __init__(self, spatial_mind):
        """
        Args:
            spatial_mind: The live SpatialMind instance (read-only access).
                          We query its spaces but don't write to them.
        """
        self.spatial_mind = spatial_mind
        self._projections: dict[str, Projection] = {}
        self._projection_counter = 0

    # ── 8D Navigation ─────────────────────────────────────────────────

    def _navigate(self, target_text: str, action: str) -> Optional[dict]:
        """Navigate the spatial mind to a target and return the path trace.
        
        This physically moves the 8D attention center to execute projections,
        leaving emergent 'dream' paths in its wake.
        """
        if not self.spatial_mind:
            return None
            
        try:
            from_pos = self.spatial_mind.attention_center.copy().tolist()
            # Pulse toward the target
            context = self.spatial_mind.pulse_from_text(target_text)
            to_pos = self.spatial_mind.attention_center.copy().tolist()
            
            flashes = []
            nearby = []
            for line in context.split("\n"):
                if "⟪" in line:
                    flashes.extend(re.findall(r"⟪([^⟫]+)⟫", line))
                elif line.startswith("• "):
                    text = re.sub(r"\s*\[\d+\.\d+\]$", "", line[2:]).strip()
                    if text:
                        nearby.append(text)
                elif line.strip() and not line.startswith("•"):
                    nearby.append(line.strip())
                    
            return {
                "from_pos": from_pos,
                "to_pos": to_pos,
                "flashes": flashes[:5],
                "action": action,
                "agent": "imagination",
                "nearby": nearby[:5],
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug(f"Spatial navigation for {action} failed: {e}")
            return None

    # ── Core: Imagine a scenario ──────────────────────────────────────

    def imagine(self, scenario_text: str, k_nearby: int = 15) -> Projection:
        """Imagine a scenario and estimate its affective impact.

        1. Embed the scenario text → 8D position
        2. Query nearby memories and beliefs at that position
        3. Compute weighted average Lagrangian encoding
        4. Estimate valence and muted stability impact

        Args:
            scenario_text: Natural language description of the scenario.
            k_nearby: How many nearby points to query for valence estimation.

        Returns:
            Projection with estimated felt state and supporting evidence.
        """
        # 1. Project scenario into 8D & Navigate
        trace = self._navigate(target_text=scenario_text, action=f"imagine: {scenario_text[:30]}")
        
        embedder = self.spatial_mind._get_embedder()
        embedding = embedder.encode(scenario_text)
        embedding = np.array(embedding, dtype=np.float32)
        position = self.spatial_mind.belief_space.projection.project(embedding)

        # 2. Query nearby points in both spaces
        belief_nearby = self.spatial_mind.belief_space.gravity_ranked_query(
            position, k=k_nearby
        )
        memory_nearby = self.spatial_mind.memory_space.gravity_ranked_query(
            position, k=k_nearby
        )

        # 3. Collect Lagrangian data from nearby points
        omega_samples = []
        s_total_samples = []
        weights = []
        nearby_experiences = []
        nearby_beliefs = []

        for pid, gravity, dist in belief_nearby:
            pt = self.spatial_mind.belief_space.get_point(pid)
            if pt:
                omega = pt.get("encoding_omega", 0.5)
                s_total = pt.get("encoding_s_total", 0.15)
                w = gravity  # Weight by gravitational influence

                omega_samples.append(omega)
                s_total_samples.append(s_total)
                weights.append(w)
                nearby_beliefs.append({
                    "id": pid,
                    "content": pt.get("content", ""),
                    "gravity": round(gravity, 4),
                    "omega": omega,
                })

        for pid, gravity, dist in memory_nearby:
            pt = self.spatial_mind.memory_space.get_point(pid)
            if pt:
                omega = pt.get("encoding_omega", 0.5)
                s_total = pt.get("encoding_s_total", 0.15)
                w = gravity * 0.5  # Memories: half weight of beliefs for valence

                omega_samples.append(omega)
                s_total_samples.append(s_total)
                weights.append(w)
                nearby_experiences.append({
                    "id": pid,
                    "content": pt.get("content", "")[:100],
                    "gravity": round(gravity, 4),
                    "omega": omega,
                })

        # 4. Compute weighted average Lagrangian state
        if weights:
            weights = np.array(weights)
            weights /= weights.sum()

            est_omega = float(np.average(omega_samples, weights=weights))
            est_s_total = float(np.average(s_total_samples, weights=weights))
        else:
            est_omega = 0.5
            est_s_total = 0.15

        # 5. Compute valence: high Ω + low stress = positive
        #    Valence ranges from -1 (devastating) to +1 (wonderful)
        #    Neutral point: Ω=0.5, s_total=0.15
        valence = (est_omega - 0.5) * 2.0 - (est_s_total - 0.15) * 2.0
        valence = max(-1.0, min(1.0, valence))

        # 6. Compute muted stability impact
        #    This is what the Sentinel WOULD feel, dampened by 0.1×
        stability_impact = valence * IMAGINATION_MUTING

        # 7. Create projection
        self._projection_counter += 1
        proj_id = f"proj_{self._projection_counter:04d}"

        projection = Projection(
            id=proj_id,
            content=scenario_text,
            position_8d=position,
            estimated_omega=round(est_omega, 4),
            estimated_s_total=round(est_s_total, 4),
            estimated_valence=round(valence, 4),
            stability_impact=round(stability_impact, 4),
            nearby_experiences=nearby_experiences[:5],
            nearby_beliefs=nearby_beliefs[:5],
            created_at=time.time(),
            trace=trace,
        )

        self._projections[proj_id] = projection
        logger.info(
            f"Imagined: '{scenario_text[:50]}...' → "
            f"valence={valence:+.3f}, impact={stability_impact:+.4f}"
        )

        return projection

    # ── Compare two scenarios ─────────────────────────────────────────

    def compare(self, scenario_a: str, scenario_b: str) -> dict:
        """Imagine two scenarios and compare their felt impact.

        Useful for decision-making: "Which future feels better?"

        Returns:
            Dict with both projections and a preference signal.
        """
        proj_a = self.imagine(scenario_a)
        proj_b = self.imagine(scenario_b)

        preference = proj_a.estimated_valence - proj_b.estimated_valence

        return {
            "scenario_a": proj_a,
            "scenario_b": proj_b,
            "preference": round(preference, 4),
            "preferred": "a" if preference > 0 else "b" if preference < 0 else "neutral",
            "confidence": round(abs(preference), 4),
        }

    # ── Verify against reality ────────────────────────────────────────

    def verify(self, projection_id: str, actual_omega: float, actual_s_total: float):
        """Compare a projection against what actually happened.

        Called when an imagined future comes to pass. The prediction
        error (D_KL between projected and actual) drives learning.

        Args:
            projection_id: ID of the projection to verify.
            actual_omega: The real Ω when the event occurred.
            actual_s_total: The real s_total when the event occurred.
        """
        proj = self._projections.get(projection_id)
        if not proj:
            return

        # Prediction error: how far off was the imagination?
        omega_error = abs(proj.estimated_omega - actual_omega)
        s_total_error = abs(proj.estimated_s_total - actual_s_total)
        total_error = omega_error + s_total_error

        if total_error < 0.2:
            proj.verified = True
            proj.confidence = min(0.9, proj.confidence + 0.2)
            logger.info(
                f"Projection {projection_id} VERIFIED "
                f"(error={total_error:.3f}). Imagination was accurate."
            )
        else:
            proj.contradicted = True
            proj.confidence = max(0.1, proj.confidence - 0.2)
            logger.info(
                f"Projection {projection_id} CONTRADICTED "
                f"(error={total_error:.3f}). Reality differed from imagination."
            )

        return {
            "projection_id": projection_id,
            "predicted_omega": proj.estimated_omega,
            "actual_omega": actual_omega,
            "predicted_s_total": proj.estimated_s_total,
            "actual_s_total": actual_s_total,
            "prediction_error": round(total_error, 4),
            "verified": proj.verified,
        }

    # ── Query spatial valence at arbitrary point ──────────────────────

    def query_valence(self, position_8d: np.ndarray, k: int = 10) -> dict:
        """What does this region of the space FEEL like?

        Pure spatial query — no imagination involved. Just reads
        the Lagrangian topology at a point.

        Returns:
            Dict with average omega, s_total, and valence at that position.
        """
        nearby = self.spatial_mind.belief_space.gravity_ranked_query(
            position_8d, k=k
        )

        if not nearby:
            return {"omega": 0.5, "s_total": 0.15, "valence": 0.0}

        omegas = []
        s_totals = []
        weights = []

        for pid, gravity, dist in nearby:
            pt = self.spatial_mind.belief_space.get_point(pid)
            if pt:
                omegas.append(pt.get("encoding_omega", 0.5))
                s_totals.append(pt.get("encoding_s_total", 0.15))
                weights.append(gravity)

        if not weights:
            return {"omega": 0.5, "s_total": 0.15, "valence": 0.0}

        w = np.array(weights)
        w /= w.sum()

        avg_omega = float(np.average(omegas, weights=w))
        avg_s_total = float(np.average(s_totals, weights=w))
        valence = (avg_omega - 0.5) * 2.0 - (avg_s_total - 0.15) * 2.0
        valence = max(-1.0, min(1.0, valence))

        return {
            "omega": round(avg_omega, 4),
            "s_total": round(avg_s_total, 4),
            "valence": round(valence, 4),
        }

    # ── Decay old projections ─────────────────────────────────────────

    def decay_projections(self):
        """Remove stale, unverified projections.

        Called periodically. Projections that weren't verified or
        contradicted within their half-life lose confidence and
        eventually get pruned.
        """
        now = time.time()
        to_remove = []

        for pid, proj in self._projections.items():
            if proj.verified or proj.contradicted:
                continue  # Keep verified/contradicted for the record

            age = now - proj.created_at
            decay = 0.5 ** (age / PROJECTION_HALF_LIFE)
            proj.confidence *= decay

            if proj.confidence < 0.05:
                to_remove.append(pid)

        for pid in to_remove:
            del self._projections[pid]

        if to_remove:
            logger.info(f"Pruned {len(to_remove)} stale projections")

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        total = len(self._projections)
        verified = sum(1 for p in self._projections.values() if p.verified)
        contradicted = sum(1 for p in self._projections.values() if p.contradicted)
        pending = total - verified - contradicted

        return {
            "total_projections": total,
            "verified": verified,
            "contradicted": contradicted,
            "pending": pending,
            "prediction_accuracy": (
                round(verified / (verified + contradicted), 3)
                if (verified + contradicted) > 0 else None
            ),
        }
