import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger("helix.brain.manifold.projector")

class ManifoldProjector:
    """
    Projector for reducing 384D ChromaDB embeddings to 8D cognitive manifold space.
    Uses numpy-based PCA (SVD) since sklearn isn't installed system-wide.
    """

    def __init__(self, save_dir: Path):
        self.save_dir = save_dir
        self.matrix_path = save_dir / "projection.npz"
        self.mean = None
        self.components = None
        self.n_components = 8
        self._load_if_exists()

    def _load_if_exists(self):
        """Load projection matrix if it exists."""
        if self.matrix_path.exists():
            try:
                data = np.load(self.matrix_path)
                self.mean = data['mean']
                self.components = data['components']
                logger.info(f"Loaded projection matrix from {self.matrix_path}")
            except Exception as e:
                logger.warning(f"Failed to load projection matrix: {e}")
                self.mean = None
                self.components = None

    def save(self):
        """Save the projection matrix."""
        if self.mean is not None and self.components is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            np.savez(self.matrix_path, mean=self.mean, components=self.components)
            logger.info(f"Saved projection matrix to {self.matrix_path}")

    def fit(self, X: np.ndarray):
        """
        Fit the PCA using all given embeddings.
        X should be shape (N, 384).
        """
        if len(X) < self.n_components:
            raise ValueError(f"Need at least {self.n_components} vectors to fit PCA.")

        logger.info(f"Fitting PCA on {len(X)} vectors...")
        self.mean = np.mean(X, axis=0)
        X_centered = X - self.mean
        
        # SVD: X = U * S * Vt
        # Using full_matrices=False is critical for efficient computation
        U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
        
        self.components = Vt[:self.n_components]
        self.save()
        logger.info("PCA fit complete.")

    def project(self, X: np.ndarray) -> np.ndarray:
        """
        Project embeddings to 8D.
        X can be a single vector (384,) or dataset (N, 384).
        """
        if self.mean is None or self.components is None:
            raise RuntimeError("Projector is not fitted yet.")

        is_1d = X.ndim == 1
        if is_1d:
            X = X.reshape(1, -1)

        projected = (X - self.mean) @ self.components.T
        
        if is_1d:
            return projected[0]
        return projected

    @property
    def is_fitted(self) -> bool:
        return self.mean is not None and self.components is not None
