"""Ant state and replaceable positional-memory route operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from numpy.typing import NDArray


class Role(str, Enum):
    FORAGER = "forager"
    TRANSPORTER = "transporter"
    FOLLOWER = "follower"


@dataclass
class Ant:
    """Mutable state for one point ant; no state is shared between instances."""

    ant_id: int
    position: NDArray[np.float64]
    heading: float
    role: Role
    travel_path: list[NDArray[np.float64]] = field(default_factory=list)
    return_waypoints: NDArray[np.float64] = field(
        default_factory=lambda: np.empty((0, 2), dtype=float)
    )
    return_waypoint_index: int = 0
    movement_cursor: int = 0
    last_path_distance: float = 0.0
    last_displacement: float = 0.0

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float).copy()
        if self.position.shape != (2,) or not np.isfinite(self.position).all():
            raise ValueError("ant position must contain two finite coordinates")
        if not np.isfinite(self.heading):
            raise ValueError("ant heading must be finite")
        if not isinstance(self.role, Role):
            self.role = Role(self.role)
        self.travel_path = [np.asarray(point, dtype=float).copy() for point in self.travel_path]
        if not self.travel_path:
            self.travel_path = [self.position.copy()]
        self.return_waypoints = np.asarray(self.return_waypoints, dtype=float).copy()
        if self.return_waypoints.size == 0:
            self.return_waypoints = np.empty((0, 2), dtype=float)
        if self.return_waypoints.ndim != 2 or self.return_waypoints.shape[1] != 2:
            raise ValueError("return_waypoints must have shape (n, 2)")

    def clone(self) -> "Ant":
        return Ant(
            ant_id=self.ant_id,
            position=self.position.copy(),
            heading=float(self.heading),
            role=self.role,
            travel_path=[point.copy() for point in self.travel_path],
            return_waypoints=self.return_waypoints.copy(),
            return_waypoint_index=self.return_waypoint_index,
            movement_cursor=self.movement_cursor,
            last_path_distance=self.last_path_distance,
            last_displacement=self.last_displacement,
        )


def coarse_grain_path(
    path: list[NDArray[np.float64]], stride: int = 3
) -> NDArray[np.float64]:
    """Keep indices 0, stride, ... and append the final vertex if needed."""

    if stride < 1:
        raise ValueError("stride must be positive")
    points = np.asarray(path, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 1:
        raise ValueError("path must contain at least one two-dimensional point")
    retained_indices = list(range(0, len(points), stride))
    if retained_indices[-1] != len(points) - 1:
        retained_indices.append(len(points) - 1)
    return points[retained_indices].copy()


def prepare_transporter_route(ant: Ant, stride: int = 3) -> None:
    """Build the provisional reversed one-third-memory return route."""

    retained = coarse_grain_path(ant.travel_path, stride=stride)
    ant.return_waypoints = retained[::-1].copy()
    if np.linalg.norm(ant.return_waypoints[0] - ant.position) > 1e-9:
        ant.return_waypoints = np.vstack((ant.position.copy(), ant.return_waypoints))
    ant.return_waypoint_index = 1 if len(ant.return_waypoints) > 1 else len(
        ant.return_waypoints
    )


def advance_transporter_route(
    ant: Ant, distance: float
) -> tuple[float, NDArray[np.float64]]:
    """Advance along linearly interpolated return waypoints by path distance."""

    if not np.isfinite(distance) or distance < 0:
        raise ValueError("distance must be finite and non-negative")
    start = ant.position.copy()
    remaining = float(distance)
    travelled = 0.0
    tolerance = 1e-12

    while remaining > tolerance and ant.return_waypoint_index < len(ant.return_waypoints):
        target = ant.return_waypoints[ant.return_waypoint_index]
        vector = target - ant.position
        segment_length = float(np.linalg.norm(vector))
        if segment_length <= tolerance:
            ant.position = target.copy()
            ant.return_waypoint_index += 1
            continue
        direction = vector / segment_length
        ant.heading = float(np.arctan2(direction[1], direction[0]))
        if segment_length <= remaining + tolerance:
            ant.position = target.copy()
            ant.return_waypoint_index += 1
            remaining -= segment_length
            travelled += segment_length
        else:
            ant.position = ant.position + remaining * direction
            travelled += remaining
            remaining = 0.0

    displacement = ant.position - start
    ant.last_path_distance = float(travelled)
    ant.last_displacement = float(np.linalg.norm(displacement))
    return ant.last_path_distance, displacement
