"""Single-trajectory statistics for Stage 1."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .models import Trajectory


def visited_cell_indices(
    positions: NDArray[np.float64], cell_size: float
) -> NDArray[np.int64]:
    """Map positions to square cells with the origin at a cell centre."""

    if not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError("cell_size must be finite and positive")
    points = np.asarray(positions, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("positions must have shape (n, 2)")
    return np.floor(points / cell_size + 0.5).astype(np.int64)


def cumulative_visited_sites(
    positions: NDArray[np.float64], cell_size: float
) -> NDArray[np.int64]:
    """Count distinct visited cells after every recorded vertex."""

    cells = visited_cell_indices(positions, cell_size)
    visited: set[tuple[int, int]] = set()
    counts = np.empty(len(cells), dtype=np.int64)
    for i, cell in enumerate(cells):
        visited.add((int(cell[0]), int(cell[1])))
        counts[i] = len(visited)
    return counts


def compute_trajectory_metrics(trajectory: Trajectory, cell_size: float) -> dict[str, float]:
    """Compute the Stage 1 metrics for one trajectory."""

    signs = trajectory.turn_signs.astype(float)
    if len(signs) > 1:
        adjacent_products = signs[:-1] * signs[1:]
        same_turn_fraction = float(np.mean(adjacent_products == 1.0))
        lag1_sign_product = float(np.mean(adjacent_products))
    else:
        same_turn_fraction = float("nan")
        lag1_sign_product = float("nan")

    displacement = trajectory.positions[-1] - trajectory.positions[0]
    net_displacement = float(np.linalg.norm(displacement))
    total_path_length = float(len(trajectory.turn_signs) * trajectory.step_size)
    visited_sites = int(cumulative_visited_sites(trajectory.positions, cell_size)[-1])

    return {
        "same_turn_fraction": same_turn_fraction,
        "lag1_sign_product": lag1_sign_product,
        "paper_rho_mean_cos_turn": float(np.mean(np.cos(trajectory.turn_angles))),
        "circular_turn_resultant_length": float(
            np.abs(np.mean(np.exp(1j * trajectory.turn_angles)))
        ),
        "net_displacement": net_displacement,
        "straightness": net_displacement / total_path_length,
        "visited_sites": float(visited_sites),
        "covered_area": float(visited_sites * cell_size**2),
    }

