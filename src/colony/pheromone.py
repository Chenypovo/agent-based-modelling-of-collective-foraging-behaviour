"""Replaceable discrete, additive, non-decaying pheromone field."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .config import PheromoneConfig


@dataclass(frozen=True)
class PheromoneSignal:
    cell_index: tuple[int, int]
    intensity: float
    direction: NDArray[np.float64]
    cell_center: NDArray[np.float64]


class PheromoneField:
    """Grid cells store additive strength and weighted direction toward food."""

    def __init__(
        self,
        side_length: float,
        config: PheromoneConfig,
        food_position: NDArray[np.float64],
    ) -> None:
        if not np.isfinite(side_length) or side_length <= 0:
            raise ValueError("side_length must be finite and positive")
        self.side_length = float(side_length)
        self.config = config
        self.food_position = np.asarray(food_position, dtype=float).copy()
        if self.food_position.shape != (2,) or not np.isfinite(self.food_position).all():
            raise ValueError("food_position must contain two finite coordinates")
        cells = int(np.ceil(self.side_length / config.cell_size))
        self.intensity = np.zeros((cells, cells), dtype=np.float64)
        self.direction_sum = np.zeros((cells, cells, 2), dtype=np.float64)

    def _cell_index(self, position: NDArray[np.float64]) -> tuple[int, int]:
        point = np.asarray(position, dtype=float)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError("position must contain two finite coordinates")
        if np.any(point < 0.0) or np.any(point > self.side_length):
            raise ValueError("pheromone position must lie inside the arena")
        raw = np.floor(point / self.config.cell_size).astype(int)
        clipped = np.clip(raw, 0, np.array(self.intensity.shape) - 1)
        return int(clipped[0]), int(clipped[1])

    def _cell_center(self, index: tuple[int, int]) -> NDArray[np.float64]:
        centre = (np.asarray(index, dtype=float) + 0.5) * self.config.cell_size
        return np.minimum(centre, self.side_length)

    def deposit(
        self,
        position: NDArray[np.float64],
        direction_to_food: NDArray[np.float64],
        amount: float | None = None,
    ) -> None:
        deposit_amount = self.config.deposit_amount if amount is None else float(amount)
        if not np.isfinite(deposit_amount) or deposit_amount <= 0:
            raise ValueError("deposit amount must be finite and positive")
        direction = np.asarray(direction_to_food, dtype=float)
        if direction.shape != (2,) or not np.isfinite(direction).all():
            raise ValueError("direction_to_food must contain two finite coordinates")
        norm = float(np.linalg.norm(direction))
        if norm <= 1e-15:
            direction = self.food_position - np.asarray(position, dtype=float)
            norm = float(np.linalg.norm(direction))
        if norm <= 1e-15:
            direction = np.array([1.0, 0.0])
        else:
            direction = direction / norm
        index = self._cell_index(position)
        self.intensity[index] += deposit_amount
        self.direction_sum[index] += deposit_amount * direction

    def _point_to_cell_distance(
        self, point: NDArray[np.float64], index: tuple[int, int]
    ) -> float:
        lower = np.asarray(index, dtype=float) * self.config.cell_size
        upper = np.minimum(lower + self.config.cell_size, self.side_length)
        delta = np.maximum(np.maximum(lower - point, point - upper), 0.0)
        return float(np.linalg.norm(delta))

    def _direction(self, index: tuple[int, int]) -> NDArray[np.float64]:
        vector = self.direction_sum[index]
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-15:
            vector = self.food_position - self._cell_center(index)
            norm = float(np.linalg.norm(vector))
        if norm <= 1e-15:
            return np.array([1.0, 0.0])
        return vector / norm

    def sense(
        self, position: NDArray[np.float64], radius: float | None = None
    ) -> PheromoneSignal | None:
        """Select local maximum concentration with deterministic tie-breaking."""

        point = np.asarray(position, dtype=float)
        sensing_radius = self.config.sensing_range if radius is None else float(radius)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError("position must contain two finite coordinates")
        if not np.isfinite(sensing_radius) or sensing_radius <= 0:
            raise ValueError("sensing radius must be finite and positive")

        lower = np.floor((point - sensing_radius) / self.config.cell_size).astype(int)
        upper = np.floor((point + sensing_radius) / self.config.cell_size).astype(int)
        lower = np.clip(lower, 0, np.array(self.intensity.shape) - 1)
        upper = np.clip(upper, 0, np.array(self.intensity.shape) - 1)

        candidates: list[tuple[float, float, int, int, NDArray[np.float64]]] = []
        for ix in range(int(lower[0]), int(upper[0]) + 1):
            for iy in range(int(lower[1]), int(upper[1]) + 1):
                index = (ix, iy)
                strength = float(self.intensity[index])
                if strength <= 0.0:
                    continue
                if self._point_to_cell_distance(point, index) > sensing_radius + 1e-12:
                    continue
                direction = self._direction(index)
                food_vector = self.food_position - self._cell_center(index)
                food_norm = float(np.linalg.norm(food_vector))
                projection = (
                    float(np.dot(direction, food_vector / food_norm)) if food_norm > 1e-15 else 1.0
                )
                candidates.append((strength, projection, ix, iy, direction))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
        strength, _, ix, iy, direction = candidates[0]
        return PheromoneSignal(
            cell_index=(ix, iy),
            intensity=strength,
            direction=direction.copy(),
            cell_center=self._cell_center((ix, iy)),
        )

    def active_cells_near(
        self, position: NDArray[np.float64], radius: float | None = None
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return only centres and strengths of active cells in sensing range."""

        point = np.asarray(position, dtype=float)
        sensing_radius = self.config.sensing_range if radius is None else float(radius)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError("position must contain two finite coordinates")
        if not np.isfinite(sensing_radius) or sensing_radius <= 0:
            raise ValueError("sensing radius must be finite and positive")

        lower = np.floor((point - sensing_radius) / self.config.cell_size).astype(int)
        upper = np.floor((point + sensing_radius) / self.config.cell_size).astype(int)
        lower = np.clip(lower, 0, np.array(self.intensity.shape) - 1)
        upper = np.clip(upper, 0, np.array(self.intensity.shape) - 1)

        centers: list[NDArray[np.float64]] = []
        strengths: list[float] = []
        for ix in range(int(lower[0]), int(upper[0]) + 1):
            for iy in range(int(lower[1]), int(upper[1]) + 1):
                index = (ix, iy)
                strength = float(self.intensity[index])
                if strength <= 0.0:
                    continue
                if self._point_to_cell_distance(point, index) > sensing_radius + 1e-12:
                    continue
                centers.append(self._cell_center(index))
                strengths.append(strength)
        if not centers:
            return np.empty((0, 2), dtype=float), np.empty(0, dtype=float)
        return np.vstack(centers), np.asarray(strengths, dtype=float)

    @property
    def total_intensity(self) -> float:
        return float(np.sum(self.intensity))

    @property
    def active_cell_count(self) -> int:
        return int(np.count_nonzero(self.intensity > 0.0))

    def active_cells(
        self,
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        indices = np.argwhere(self.intensity > 0.0)
        if len(indices) == 0:
            return (
                np.empty((0, 2), dtype=float),
                np.empty(0, dtype=float),
                np.empty((0, 2), dtype=float),
            )
        centres = np.vstack([self._cell_center((int(i), int(j))) for i, j in indices])
        strengths = self.intensity[indices[:, 0], indices[:, 1]].astype(float)
        directions = np.vstack([self._direction((int(i), int(j))) for i, j in indices])
        return centres, strengths, directions

    def advance_time(self) -> None:
        """No-op by design: Stage 2A has no diffusion and no decay."""

        if self.config.decay_rate != 0.0 or self.config.diffusion_rate != 0.0:
            raise RuntimeError("Stage 2A pheromone field must remain non-decaying and non-diffusing")
