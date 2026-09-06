"""Follower direction inference kept separate from field storage and movement."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def _wrapped_heading(heading: float) -> float:
    if not np.isfinite(heading):
        raise ValueError("current_heading must be finite")
    return float(np.arctan2(np.sin(heading), np.cos(heading)))


def local_weighted_pca_tangent(
    cell_centers: NDArray[np.float64],
    concentrations: NDArray[np.float64],
    current_heading: float,
) -> float:
    """Infer an oriented local tangent from grid-centre geometry and weights."""

    fallback = _wrapped_heading(current_heading)
    centers = np.asarray(cell_centers, dtype=float)
    weights = np.asarray(concentrations, dtype=float)
    if centers.ndim != 2 or centers.shape[1:] != (2,):
        raise ValueError("cell_centers must have shape (n, 2)")
    if weights.shape != (len(centers),):
        raise ValueError("concentrations must have shape (n,)")
    if not np.isfinite(centers).all() or not np.isfinite(weights).all():
        raise ValueError("cell centers and concentrations must be finite")
    if np.any(weights <= 0.0):
        raise ValueError("active-cell concentrations must be positive")
    if len(np.unique(centers, axis=0)) < 2:
        return fallback

    weighted_mean = np.average(centers, axis=0, weights=weights)
    centered = centers - weighted_mean
    covariance = (centered * weights[:, None]).T @ centered / float(np.sum(weights))
    if not np.isfinite(covariance).all() or np.array_equal(covariance, np.zeros((2, 2))):
        return fallback

    try:
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    except np.linalg.LinAlgError:
        return fallback
    if not np.isfinite(eigenvalues).all() or not np.isfinite(eigenvectors).all():
        return fallback
    if eigenvalues[-1] <= 0.0 or eigenvalues[-1] == eigenvalues[-2]:
        return fallback

    tangent = eigenvectors[:, -1]
    norm = float(np.linalg.norm(tangent))
    if not np.isfinite(norm) or norm == 0.0:
        return fallback
    tangent = tangent / norm
    heading_vector = np.array([np.cos(fallback), np.sin(fallback)], dtype=float)
    alignment = float(np.dot(tangent, heading_vector))
    if alignment == 0.0:
        return fallback
    if alignment < 0.0:
        tangent = -tangent
    return float(np.arctan2(tangent[1], tangent[0]))
