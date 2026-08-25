"""Colony-level order parameters from Zhang & Yong Eqs. (15)--(17)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def fold_headings(headings: NDArray[np.float64]) -> NDArray[np.float64]:
    """Map directed headings to the unoriented interval [-pi/2, pi/2)."""

    angles = np.asarray(headings, dtype=float)
    if angles.ndim != 1 or len(angles) < 1:
        raise ValueError("headings must be a non-empty one-dimensional array")
    if not np.isfinite(angles).all():
        raise ValueError("headings must be finite")
    return (angles + np.pi / 2) % np.pi - np.pi / 2


def compute_order_parameters(headings: NDArray[np.float64]) -> tuple[float, float]:
    """Return paper-style arithmetic orientation order and nematic magnitude."""

    folded = fold_headings(headings)
    phi = float(np.mean(folded))
    director = np.array([np.mean(np.cos(folded)), np.mean(np.sin(folded))])
    psi = float(np.linalg.norm(director))
    return phi, psi
