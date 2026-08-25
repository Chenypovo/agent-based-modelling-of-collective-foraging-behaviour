"""Finite square environment and provisional reflective boundary handling."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class SquareEnvironment:
    """Continuous square arena with specular reflection of overshoot."""

    def __init__(self, side_length: float) -> None:
        if not np.isfinite(side_length) or side_length <= 0:
            raise ValueError("side_length must be finite and positive")
        self.side_length = float(side_length)

    def contains(self, position: NDArray[np.float64], tolerance: float = 1e-12) -> bool:
        point = np.asarray(position, dtype=float)
        return bool(
            point.shape == (2,)
            and np.isfinite(point).all()
            and np.all(point >= -tolerance)
            and np.all(point <= self.side_length + tolerance)
        )

    def reflect_move(
        self,
        position: NDArray[np.float64],
        *,
        heading: float,
        distance: float,
    ) -> tuple[NDArray[np.float64], float]:
        """Move along a ray, reflecting overshoot and its velocity component."""

        start = np.asarray(position, dtype=float)
        if not self.contains(start):
            raise ValueError("start position must lie inside the arena")
        if not np.isfinite(heading):
            raise ValueError("heading must be finite")
        if not np.isfinite(distance) or distance < 0:
            raise ValueError("distance must be finite and non-negative")

        velocity = np.array([np.cos(heading), np.sin(heading)], dtype=float)
        candidate = start + distance * velocity
        for axis in range(2):
            reflections = 0
            while candidate[axis] < 0.0 or candidate[axis] > self.side_length:
                if candidate[axis] < 0.0:
                    candidate[axis] = -candidate[axis]
                    velocity[axis] *= -1.0
                elif candidate[axis] > self.side_length:
                    candidate[axis] = 2.0 * self.side_length - candidate[axis]
                    velocity[axis] *= -1.0
                reflections += 1
                if reflections > 1_000:
                    raise RuntimeError("too many boundary reflections in one move")

        candidate = np.clip(candidate, 0.0, self.side_length)
        reflected_heading = float(np.arctan2(velocity[1], velocity[0]))
        return candidate.astype(float), reflected_heading


def distance_to_site(position: NDArray[np.float64], centre: tuple[float, float]) -> float:
    """Euclidean distance from an ant centre to a configured site centre."""

    return float(np.linalg.norm(np.asarray(position, dtype=float) - np.asarray(centre)))
