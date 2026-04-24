"""
Helix V5 — Cognitive Manifold

This package implements the 8D non-Euclidean cognitive manifold, projecting 
high-dimensional semantic embeddings (384D) down to an 8D space where 
beliefs provide gravitational curvature and memories orbit as matter.
"""

from .projector import ManifoldProjector
from .manifold import CognitiveManifold
from .geodesic import compute_curvature_field, geodesic_distance_vectorized
