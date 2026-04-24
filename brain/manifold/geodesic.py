import numpy as np
import math
import logging

logger = logging.getLogger("helix.brain.manifold.geodesic")

def compute_curvature_field(beliefs: list[dict]) -> dict:
    """
    Computes curvature and masses for a set of beliefs.
    Returns a dict with 'masses', 'curvature', 'heavy_mask', 'heavy_positions', 
    'heavy_curvatures', 'norm_factor'.
    """
    if not beliefs:
        return {}

    # Extract positions
    positions = []
    for b in beliefs:
        pos = b.get("position_8d", [0]*8)
        if pos is None:
            pos = [0]*8
        positions.append(np.array(pos))
    positions = np.array(positions)

    # Compute roughly PageRank-esque masses
    # Using relations out + inbound estimation (assuming symmetric average for inbound)
    total_conns = [len(b.get("relations", [])) for b in beliefs]
    r_mean = max(np.mean(total_conns) * 2, 1.0)
    
    masses = {}
    for b in beliefs:
        v = max(0.1, float(b.get("verifications", 1.0)))
        v_eff = math.log2(v + 2)
        out = len(b.get("relations", []))
        inb = out # fast proxy since inbound loading is expensive
        r_ratio = (out + inb) / r_mean
        s = max(0.1, float(b.get("stability_index", 0.5)))
        t = 1.0 # time factor could be added here if needed
        p = 1.0 + (out + inb) * 0.1
        
        m = max(0.001, v_eff * (1.0 + r_ratio) * s * t * p)
        masses[b["id"]] = m

    mass_array = np.array([masses.get(b["id"], 0.001) for b in beliefs])
    m_mean = np.mean(mass_array)
    G = 1.0 / max(m_mean, 0.001)

    curvature = np.array([
        G * masses.get(b["id"], 0.001) * (1.0 + b.get("encoding_lagrangian", {}).get("D_KL", 0.0))
        for b in beliefs
    ])

    heavy_mask = curvature > 0.01
    heavy_positions = positions[heavy_mask]
    heavy_curvatures = curvature[heavy_mask]
    n_heavy = int(np.sum(heavy_mask))
    norm_factor = 1.0 / max(n_heavy, 1)

    return {
        "masses": masses,
        "curvature": curvature,
        "heavy_mask": heavy_mask,
        "heavy_positions": heavy_positions,
        "heavy_curvatures": heavy_curvatures,
        "norm_factor": norm_factor
    }


def geodesic_distance_vectorized(
    pos: np.ndarray, 
    targets: np.ndarray,
    heavy_positions: np.ndarray,
    heavy_curvatures: np.ndarray,
    norm_factor: float,
    n_samples: int = 8
) -> np.ndarray:
    """
    Vectorized computation of geodesic distances from one position to many targets.
    
    Args:
        pos: Single 8D origin (8,)
        targets: Target positions (N, 8)
        heavy_positions: Significant curvature sources (M, 8)
        heavy_curvatures: Curvature weights (M,)
        norm_factor: 1 / max(M, 1)
        n_samples: Integration steps
        
    Returns:
        1D array of geodesic distances (N,)
    """
    n_targets = len(targets)
    if n_targets == 0:
        return np.array([])
        
    euclidean = np.linalg.norm(targets - pos, axis=1)
    
    if len(heavy_positions) == 0:
        return euclidean

    geo_dists = np.zeros(n_targets)

    for step in range(n_samples):
        t = (step + 0.5) / n_samples
        
        # sample coordinates for all targets at parameter t
        # shape is (n_targets, 8)
        samples = pos + t * (targets - pos)
        
        # for each sample, compute distance to all heavy sources
        for ti in range(n_targets):
            deltas = heavy_positions - samples[ti]
            r_sq = np.sum(deltas ** 2, axis=1)
            r_sq = np.maximum(r_sq, 0.0001)
            
            compression = np.sum(heavy_curvatures / r_sq) * norm_factor
            metric = max(0.10, min(1.0, 1.0 - compression * 0.01))
            
            geo_dists[ti] += (euclidean[ti] / n_samples) * math.sqrt(metric)

    return geo_dists
