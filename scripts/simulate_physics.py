"""
Physics Engine Simulator

Simulates 8D manifold and semantic indexing:
- 8D point representation and distance calculations
- Gravity calculations in 8D space
- Lagrangian energy calculations
- Semantic indexing with nearest neighbor search
- Manifold evolution over multiple pulses
- Attractor dynamics and center of mass calculations
"""

import os
import sys
import time
import math
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ── 8D Point Operations ─────────────────────────────────────────────

def random_8d_point(scale=1.0):
    """Generate a random 8D point."""
    if HAS_NUMPY:
        return np.random.randn(8).astype(np.float32) * scale
    return [random.gauss(0, scale) for _ in range(8)]


def distance_8d(a, b):
    """Compute Euclidean distance between two 8D points."""
    if HAS_NUMPY:
        return float(np.linalg.norm(np.array(a) - np.array(b)))
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def gravity(mass, distance, epsilon=1e-4):
    """Compute gravitational pull: mass / (distance² + ε)."""
    return mass / (distance ** 2 + epsilon)


def center_of_mass(points, masses):
    """Compute mass-weighted centroid of a set of 8D points."""
    if HAS_NUMPY:
        pts = np.array(points, dtype=np.float32)
        ms = np.array(masses, dtype=np.float32)
        weights = ms / (ms.sum() + 1e-8)
        return (pts * weights[:, np.newaxis]).sum(axis=0)
    # Fallback
    total_mass = sum(masses)
    if total_mass < 1e-8:
        return points[0]
    centroid = [0.0] * 8
    for pt, m in zip(points, masses):
        for d in range(8):
            centroid[d] += pt[d] * m / total_mass
    return centroid


# ── Lagrangian Computation ───────────────────────────────────────────

def compute_lagrangian(omega, entropy, d_kl):
    """Compute S_total = H + Ω × D_KL."""
    return entropy + omega * d_kl


# ── Simulation ───────────────────────────────────────────────────────

def simulate_manifold():
    """Simulate 8D manifold with gravity dynamics."""
    print("\n" + "=" * 70)
    print("PHYSICS ENGINE SIMULATOR")
    print("=" * 70)

    if not HAS_NUMPY:
        print("\n  ⚠ NumPy not available — using pure Python fallback")
        print("  (performance will be reduced)\n")

    # ── Phase 1: Create 8D belief points ─────────────────────────
    print("\n[1] Creating 8D belief manifold...")

    num_beliefs = 200
    beliefs = []
    for i in range(num_beliefs):
        # Create clusters by adding a category offset
        category = i % 5
        offset = [0] * 8
        offset[category] = 2.0  # Spread categories along different dimensions

        pos = random_8d_point(scale=0.5)
        if HAS_NUMPY:
            pos = pos + np.array(offset, dtype=np.float32)
        else:
            pos = [p + o for p, o in zip(pos, offset)]

        beliefs.append({
            "id": f"b_{i:04d}",
            "position": pos,
            "mass": 0.5 + random.random() * 2.0,
            "category": category,
        })

    print(f"  Created {num_beliefs} beliefs in 8D space")

    # ── Phase 2: Distance and gravity calculations ───────────────
    print("\n[2] Computing pairwise distances and gravity...")
    t0 = time.time()

    # Compute distances between first 50 beliefs
    sample = beliefs[:50]
    distances = []
    gravities = []

    for i, b1 in enumerate(sample):
        for j, b2 in enumerate(sample):
            if i >= j:
                continue
            d = distance_8d(b1["position"], b2["position"])
            g = gravity(b1["mass"] * b2["mass"], d)
            distances.append(d)
            gravities.append(g)

    elapsed = time.time() - t0

    if distances:
        min_d = min(distances)
        max_d = max(distances)
        avg_d = sum(distances) / len(distances)
        avg_g = sum(gravities) / len(gravities)

        print(f"  Computed {len(distances)} pairwise distances in {elapsed*1000:.1f}ms")
        print(f"  Distance range: [{min_d:.4f}, {max_d:.4f}]")
        print(f"  Average distance: {avg_d:.4f}")
        print(f"  Average gravity: {avg_g:.4f}")

    # ── Phase 3: Center of mass per category ─────────────────────
    print("\n[3] Computing category centroids...")

    for cat in range(5):
        cat_beliefs = [b for b in beliefs if b["category"] == cat]
        positions = [b["position"] for b in cat_beliefs]
        masses = [b["mass"] for b in cat_beliefs]

        centroid = center_of_mass(positions, masses)
        if HAS_NUMPY:
            centroid_str = ", ".join(f"{x:.3f}" for x in centroid[:4])
        else:
            centroid_str = ", ".join(f"{x:.3f}" for x in centroid[:4])

        print(f"  Category {cat}: {len(cat_beliefs)} beliefs, "
              f"centroid=[{centroid_str}...]")

    # ── Phase 4: Lagrangian evolution ────────────────────────────
    print("\n[4] Simulating Lagrangian evolution over 100 pulses...")

    omega = 0.5
    entropy = 0.15
    d_kl = 0.05
    s_history = []

    for pulse in range(100):
        # Simulate entropy fluctuation
        entropy += random.gauss(0, 0.02)
        entropy = max(0.01, min(1.0, entropy))

        # Simulate D_KL drift
        d_kl += random.gauss(0, 0.01)
        d_kl = max(0.0, min(1.0, d_kl))

        # Omega mean-reverts toward 0.5
        omega += (0.5 - omega) * 0.005
        omega += random.gauss(0, 0.01)
        omega = max(0.05, min(1.0, omega))

        s_total = compute_lagrangian(omega, entropy, d_kl)
        s_history.append(s_total)

    avg_s = sum(s_history) / len(s_history)
    min_s = min(s_history)
    max_s = max(s_history)
    final_s = s_history[-1]

    print(f"  S_total range: [{min_s:.4f}, {max_s:.4f}]")
    print(f"  S_total average: {avg_s:.4f}")
    print(f"  S_total final: {final_s:.4f}")
    print(f"  Final Ω={omega:.4f}, H={entropy:.4f}, D_KL={d_kl:.4f}")

    # ── Phase 5: Nearest-neighbor search ─────────────────────────
    print("\n[5] Simulating nearest-neighbor search...")
    t0 = time.time()

    query_point = random_8d_point(scale=1.0)
    distances_to_query = []

    for b in beliefs:
        d = distance_8d(query_point, b["position"])
        distances_to_query.append((b["id"], d, b["mass"]))

    distances_to_query.sort(key=lambda x: x[1])
    top_5 = distances_to_query[:5]

    elapsed = time.time() - t0
    print(f"  Searched {num_beliefs} beliefs in {elapsed*1000:.1f}ms")
    print(f"  Top 5 nearest:")
    for bid, d, m in top_5:
        g = gravity(m, d)
        print(f"    {bid}: dist={d:.4f}, mass={m:.2f}, gravity={g:.4f}")

    # ── Phase 6: Attractor dynamics ──────────────────────────────
    print("\n[6] Simulating attractor dynamics (drift toward centroid)...")

    # Pick a cluster and drift beliefs toward its centroid
    cat_beliefs = [b for b in beliefs if b["category"] == 0]
    positions = [b["position"] for b in cat_beliefs]
    masses = [b["mass"] for b in cat_beliefs]
    centroid = center_of_mass(positions, masses)

    # Drift each belief 1% toward the centroid
    drift_rate = 0.01
    total_drift = 0.0

    for b in cat_beliefs:
        if HAS_NUMPY:
            old_pos = np.array(b["position"])
            c = np.array(centroid)
            new_pos = old_pos + drift_rate * (c - old_pos)
            drift = float(np.linalg.norm(new_pos - old_pos))
            b["position"] = new_pos
        else:
            old_pos = b["position"]
            new_pos = [p + drift_rate * (c - p)
                       for p, c in zip(old_pos, centroid)]
            drift = distance_8d(old_pos, new_pos)
            b["position"] = new_pos
        total_drift += drift

    avg_drift = total_drift / len(cat_beliefs) if cat_beliefs else 0
    print(f"  Drifted {len(cat_beliefs)} beliefs toward centroid")
    print(f"  Average drift magnitude: {avg_drift:.6f}")

    print("\n" + "=" * 70)
    print("✓ PHYSICS SIMULATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    simulate_manifold()
