"""Coarse-grained return: transporters home through every k-th vertex of their own outbound path.

Spacing 1 is the validated exact retrace; ``None`` walks straight to the path start
(an idealised, noise-free path-integration home vector). Only the transporter's own
remembered path is used; no food, nest or field information is added.
"""

from __future__ import annotations

import math

from scalar_baseline.config import SimulationConfig
from scalar_baseline.simulation import Simulation

# Tolerance for landing on a waypoint exactly one step away despite float rounding.
_LAND = 1 + 1e-9


class CoarseReturnSimulation(Simulation):
    def __init__(self, config: SimulationConfig, waypoint_spacing: int | None = 1):
        if waypoint_spacing is not None and (isinstance(waypoint_spacing, bool)
                                             or not isinstance(waypoint_spacing, int)
                                             or waypoint_spacing < 1):
            raise ValueError("waypoint_spacing must be a positive integer or None")
        self.waypoint_spacing = waypoint_spacing
        self.return_routes: dict[int, list[tuple[float, float]]] = {}
        super().__init__(config)

    def route_from_path(self, path: list) -> list:
        """Waypoints to visit in order, ending at the path start; path[-1] is the current position."""
        last = len(path) - 1
        if self.waypoint_spacing is None:
            return [path[0]]
        k = self.waypoint_spacing
        return [path[i] for i in range(last - k, 0, -k)] + [path[0]]

    def _move(self, ant) -> None:
        if ant.role != "transporter":
            super()._move(ant)
            return
        route = self.return_routes.get(ant.ant_id)
        if not route:
            return
        target = route[0]
        dx, dy = target[0] - ant.position[0], target[1] - ant.position[1]
        distance = math.hypot(dx, dy)
        if dx or dy:
            ant.heading = math.atan2(dy, dx) % (2 * math.pi)
        if distance <= self.config.step_size * _LAND:
            ant.position = target
            route.pop(0)
        else:
            s = self.config.step_size / distance
            ant.position = (ant.position[0] + dx * s, ant.position[1] + dy * s)
        # Keep the parent invariant path[-1] == position without reusing return vertices as memory.
        if self.waypoint_spacing == 1:
            ant.path.pop()
        else:
            ant.path.append(ant.position)

    def _contacts(self, ant) -> None:
        was_transporter = ant.role == "transporter"
        super()._contacts(ant)
        if not was_transporter and ant.role == "transporter":
            self.return_routes[ant.ant_id] = self.route_from_path(ant.path)
        elif was_transporter and ant.role != "transporter":
            self.return_routes.pop(ant.ant_id, None)
