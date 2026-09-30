"""Egocentric path integration with optional geocentric landmark correction.

Each ant keeps an estimate of its own absolute position (its home vector). Every
movement step is integrated with Gaussian compass noise, so the estimate drifts
with distance travelled. A transporter walks toward its *estimated* nest; once it
believes it is home but cannot perceive the nest, it runs an Archimedean spiral
search. The nest is perceivable only within ``nest_cue_radius``.

Landmarks are fixed points visible within ``view_radius``. Each ant remembers,
per landmark, the landmark position implied by its own estimate at the least
uncertain sighting (uncertainty = path length since the last anchor). A later,
more uncertain sighting resets the estimate to that memory. No food, pheromone
or nest coordinates are given to outbound ants.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from scalar_baseline.config import SimulationConfig
from scalar_baseline.simulation import Simulation


@dataclass(frozen=True)
class NavigationConfig:
    compass_noise: float = 0.0          # SD (radians) of heading error per integrated step
    nest_cue_radius: float = 3.0        # distance at which the nest itself is perceived
    spiral_spacing: float = 4.0         # distance between successive spiral search loops
    landmarks: tuple = ()               # fixed landmark positions
    view_radius: float = 8.0            # landmark visibility

    def __post_init__(self) -> None:
        if not math.isfinite(self.compass_noise) or self.compass_noise < 0:
            raise ValueError("compass_noise must be finite and >= 0")
        for name in ("nest_cue_radius", "spiral_spacing", "view_radius"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


class LandmarkMemory:
    """Per-ant landmark memories: landmark -> (estimated landmark position, uncertainty)."""

    def __init__(self) -> None:
        self.store: dict[tuple[int, tuple[float, float]], tuple[tuple[float, float], float]] = {}

    def observe(self, ant_id: int, *, landmark, estimate, true_position, uncertainty):
        """Return (reset estimate, reset uncertainty) or None after storing a better memory."""
        key = (ant_id, tuple(landmark))
        offset = (true_position[0] - landmark[0], true_position[1] - landmark[1])
        stored = self.store.get(key)
        if stored is not None and stored[1] < uncertainty:
            (lx, ly), unc = stored
            return (lx + offset[0], ly + offset[1]), unc
        self.store[key] = ((estimate[0] - offset[0], estimate[1] - offset[1]), uncertainty)
        return None


class PathIntegrationSimulation(Simulation):
    def __init__(self, config: SimulationConfig, navigation: NavigationConfig):
        self.navigation = navigation
        super().__init__(config)
        n = config.n_ants
        self._noise_rng = [np.random.default_rng(np.random.SeedSequence([config.seed, i, 5])) for i in range(n)]
        self.estimate = [tuple(config.nest) for _ in range(n)]
        self.uncertainty = [0.0] * n
        self.mode: dict[int, str] = {}           # transporter mode: "home" or "search"
        self.search: dict[int, list] = {}         # ant -> [centre, arc length]
        self._arrival_recorded: set[int] = set()
        self.memory = LandmarkMemory()
        self.arrival_errors: list[float] = []
        self.search_starts = 0
        self.landmark_resets = 0
        self._grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for mark in navigation.landmarks:
            self._grid.setdefault(self._cell(mark), []).append(tuple(map(float, mark)))

    # ----- helpers -------------------------------------------------------
    def _cell(self, point) -> tuple[int, int]:
        r = self.navigation.view_radius
        return math.floor(point[0] / r), math.floor(point[1] / r)

    def estimate_error(self, ant_id: int) -> float:
        return math.dist(self.estimate[ant_id], self.ants[ant_id].position)

    def _visible_landmark(self, position):
        cx, cy = self._cell(position)
        best, best_d = None, self.navigation.view_radius
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for mark in self._grid.get((cx + dx, cy + dy), ()):
                    d = math.dist(mark, position)
                    if d <= best_d:
                        best, best_d = mark, d
        return best

    def _integrate(self, ant, old) -> None:
        dx, dy = ant.position[0] - old[0], ant.position[1] - old[1]
        if dx or dy:
            if self.navigation.compass_noise > 0:
                a = float(self._noise_rng[ant.ant_id].normal(0.0, self.navigation.compass_noise))
                c, s = math.cos(a), math.sin(a)
                dx, dy = c * dx - s * dy, s * dx + c * dy
            ex, ey = self.estimate[ant.ant_id]
            self.estimate[ant.ant_id] = (ex + dx, ey + dy)
            self.uncertainty[ant.ant_id] += math.hypot(dx, dy)
        # A committed local search ignores landmarks; otherwise a biased landmark memory
        # keeps sending the ant back to the same wrong spot (observed restart loop).
        if self._grid and self.mode.get(ant.ant_id) != "search":
            mark = self._visible_landmark(ant.position)
            if mark is not None:
                reset = self.memory.observe(ant.ant_id, landmark=mark, estimate=self.estimate[ant.ant_id],
                                            true_position=ant.position,
                                            uncertainty=self.uncertainty[ant.ant_id])
                if reset is not None:
                    self.estimate[ant.ant_id], self.uncertainty[ant.ant_id] = reset
                    self.landmark_resets += 1

    def _step_toward(self, ant, target, max_length: float) -> None:
        dx, dy = target[0] - ant.position[0], target[1] - ant.position[1]
        d = math.hypot(dx, dy)
        if d == 0:
            return
        ant.heading = math.atan2(dy, dx) % (2 * math.pi)
        if d <= max_length:
            ant.position = (float(target[0]), float(target[1]))
        else:
            size = self.config.arena_size
            ant.position = tuple(max(0.0, min(size, p + max_length * u))
                                 for p, u in zip(ant.position, (dx / d, dy / d)))

    def _record_arrival(self, ant) -> None:
        if ant.ant_id not in self._arrival_recorded:
            self._arrival_recorded.add(ant.ant_id)
            self.arrival_errors.append(self.estimate_error(ant.ant_id))

    # ----- movement --------------------------------------------------------
    def _move(self, ant) -> None:
        old = ant.position
        if ant.role != "transporter":
            super()._move(ant)
            self._integrate(ant, old)
            return
        nest, step = self.config.nest, self.config.step_size
        if math.dist(ant.position, nest) <= self.navigation.nest_cue_radius:
            self._record_arrival(ant)
            self._step_toward(ant, nest, step)
        else:
            if self.mode.get(ant.ant_id) == "home":
                est = self.estimate[ant.ant_id]
                if math.dist(est, nest) <= step:
                    # Believes it is home but cannot perceive the nest: start local search.
                    self._record_arrival(ant)
                    self.mode[ant.ant_id] = "search"
                    self.search[ant.ant_id] = [ant.position, 0.0]
                    self.search_starts += 1
                else:
                    home = (ant.position[0] + nest[0] - est[0], ant.position[1] + nest[1] - est[1])
                    self._step_toward(ant, home, step)
            if self.mode.get(ant.ant_id) == "search":
                state = self.search[ant.ant_id]
                state[1] += step
                a = self.navigation.spiral_spacing / (2 * math.pi)
                phi = math.sqrt(2 * state[1] / a)
                c = state[0]
                self._step_toward(ant, (c[0] + a * phi * math.cos(phi), c[1] + a * phi * math.sin(phi)), step)
        ant.path.append(ant.position)
        self._integrate(ant, old)

    def _contacts(self, ant) -> None:
        was_transporter = ant.role == "transporter"
        super()._contacts(ant)
        if not was_transporter and ant.role == "transporter":
            self.mode[ant.ant_id] = "home"
            self._arrival_recorded.discard(ant.ant_id)
        elif was_transporter and ant.role != "transporter":
            # Delivered: the visible nest re-anchors the home vector exactly.
            self.estimate[ant.ant_id] = tuple(ant.position)
            self.uncertainty[ant.ant_id] = 0.0
            self.mode.pop(ant.ant_id, None)
            self.search.pop(ant.ant_id, None)
