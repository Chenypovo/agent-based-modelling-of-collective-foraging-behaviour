"""Zhang & Yong (2023) rules on the Eq. (1) scalar field, as options on the validated Simulation.

All options at their defaults reproduce ``scalar_baseline.simulation.Simulation`` exactly.
Step 3 (paper rule): ``PaperOptions(boundary="reflect", return_stride=3, after_delivery="follower",
field="diffusing", diffusion=D)``. Step 3b (user decision after Step 3 failed): ``homing="vector"``,
transporters walk home along a path-integration home vector with Gaussian compass noise (no
landmarks), as in ``stage5_navigation.path_integration`` with nest cue radius 3, spiral search
spacing 4 and no deposit while spiral-searching.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from ant_walks.models import generate_trajectory
from colony.agents import coarse_grain_path
from scalar_baseline.config import SimulationConfig
from scalar_baseline.field import ScalarField
from scalar_baseline.navigation import navigate
from scalar_baseline.sensing import sense
from scalar_baseline.simulation import Ant, Simulation
from stage5_navigation.diffusion import DiffusingField

TWO_PI = 2 * math.pi
ROLES = ("fcrw", "transporter", "follower")


def wrap(angle: float) -> float:
    angle %= TWO_PI
    return 0.0 if angle >= TWO_PI else angle


@dataclass(frozen=True)
class PaperOptions:
    walk: str = "fcrw"
    boundary: str = "clamp"
    return_stride: int = 1
    after_delivery: str = "forager"
    deposit: bool = True
    field: str = "scalar"
    diffusion: float = 0.0
    homing: str = "route"
    compass_noise: float = 0.0

    def __post_init__(self) -> None:
        if self.walk not in {"fcrw", "zw"}:
            raise ValueError("walk must be fcrw or zw")
        if self.boundary not in {"clamp", "reflect"}:
            raise ValueError("boundary must be clamp or reflect")
        if isinstance(self.return_stride, bool) or not isinstance(self.return_stride, int) or self.return_stride < 1:
            raise ValueError("return_stride must be a positive integer")
        if self.after_delivery not in {"forager", "follower"}:
            raise ValueError("after_delivery must be forager or follower")
        if self.field not in {"scalar", "diffusing", "no_decay"}:
            raise ValueError("field must be scalar, diffusing or no_decay")
        if self.field != "diffusing" and self.diffusion != 0:
            raise ValueError("diffusion needs field='diffusing'")
        if self.homing not in {"route", "vector"}:
            raise ValueError("homing must be route or vector")
        if not math.isfinite(self.compass_noise) or self.compass_noise < 0:
            raise ValueError("compass_noise must be finite and >= 0")
        if self.homing == "route" and self.compass_noise != 0:
            raise ValueError("compass_noise needs homing='vector'")


NEST_CUE_RADIUS, SPIRAL_SPACING = 3.0, 4.0  # Stage 5 / H1a values


def baseline_options(diffusion: float, *, walk: str = "fcrw", deposit: bool = True,
                     homing: str = "route", compass_noise: float = 0.0) -> PaperOptions:
    return PaperOptions(walk=walk, boundary="reflect", return_stride=3 if homing == "route" else 1,
                        after_delivery="follower", deposit=deposit, field="diffusing", diffusion=diffusion,
                        homing=homing, compass_noise=compass_noise)


class NoDecayField(ScalarField):
    """Paper-faithful field: deposits accumulate, no evaporation, no diffusion."""

    __slots__ = ()

    def advance(self, time: int) -> None:
        if time < self.time:
            raise ValueError("field time cannot go backwards")
        self.time = time


def reflect(position: tuple[float, float], heading: float, distance: float,
            side: float) -> tuple[tuple[float, float], float]:
    """Specular reflection of overshoot (same rule as colony SquareEnvironment.reflect_move)."""
    vx, vy = math.cos(heading), math.sin(heading)
    x, y = position[0] + distance * vx, position[1] + distance * vy
    while x < 0 or x > side:
        x, vx = (-x, -vx) if x < 0 else (2 * side - x, -vx)
    while y < 0 or y > side:
        y, vy = (-y, -vy) if y < 0 else (2 * side - y, -vy)
    x, y = min(max(x, 0.0), side), min(max(y, 0.0), side)
    return (x, y), wrap(math.atan2(vy, vx))


def walk_route(position: tuple[float, float], route: list, distance: float):
    """Move ``distance`` along the polyline ``route`` (consumed in place); return (position, heading|None)."""
    heading = None
    remaining = distance
    while remaining > 1e-12 and route:
        tx, ty = route[0]
        dx, dy = tx - position[0], ty - position[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            position = route.pop(0)
            continue
        heading = wrap(math.atan2(dy, dx))
        if length <= remaining + 1e-12:
            position = route.pop(0)
            remaining -= length
        else:
            position = (position[0] + dx / length * remaining, position[1] + dy / length * remaining)
            remaining = 0.0
    return position, heading


def order_parameters(directions: np.ndarray) -> tuple[float, float]:
    """Eqs. (16)-(17): mean folded angle phi and nematic magnitude psi."""
    folded = (np.asarray(directions, dtype=float) + math.pi / 2) % math.pi - math.pi / 2
    return float(folded.mean()), float(math.hypot(np.cos(folded).mean(), np.sin(folded).mean()))


class PaperSimulation(Simulation):
    def __init__(self, config: SimulationConfig, options: PaperOptions = PaperOptions(), *,
                 record: bool = False):
        self.options = options
        self.routes: dict[int, list] = {}
        self.pickup_roles: list[tuple[int, str]] = []
        super().__init__(config)
        if options.walk == "zw":
            for i in range(config.n_ants):
                rng = np.random.default_rng(np.random.SeedSequence([config.seed, i, 2]))
                self._turns[i] = generate_trajectory("zw", steps=config.steps, step_size=config.step_size,
                                                     theta_max=config.theta_max, gamma=config.gamma,
                                                     rng=rng).turn_angles
        if options.field == "diffusing":
            self.field = DiffusingField(config.arena_size, config.cell_size, config.decay,
                                        diffusion=options.diffusion)
        elif options.field == "no_decay":
            self.field = NoDecayField(config.arena_size, config.cell_size, config.decay)
        self.record = record
        if options.homing == "vector":
            self.estimate = [tuple(config.nest) for _ in range(config.n_ants)]
            self.mode: dict[int, str] = {}      # transporter: "home" or "search"
            self.search: dict[int, list] = {}   # ant -> [centre, arc length]
            self.search_starts = 0
            self._searched: set[int] = set()
            self._compass = [np.random.default_rng(np.random.SeedSequence([config.seed, i, 5]))
                             .normal(0.0, options.compass_noise, config.steps) if options.compass_noise > 0
                             else None for i in range(config.n_ants)]
        if record:
            n = config.steps
            self.phi, self.psi = np.zeros(n), np.zeros(n)
            self.counts = np.zeros((n, 3), dtype=np.int32)  # foragers, transporters, followers

    def _move(self, ant: Ant) -> None:
        if self.options.homing == "vector":
            old = ant.position
            if ant.role == "transporter":
                self._home_move(ant)
            else:
                self._search_move(ant)
            self._integrate(ant, old)
            return
        if ant.role == "transporter":
            if self.options.return_stride == 1:
                super()._move(ant)
                return
            route = self.routes.get(ant.ant_id)
            if route:
                ant.position, heading = walk_route(ant.position, route, self.config.step_size)
                if heading is not None:
                    ant.heading = heading
                ant.path.append(ant.position)
            return
        self._search_move(ant)

    def _search_move(self, ant: Ant) -> None:
        """Forager / follower step (sensing, B0 navigation, boundary rule)."""
        if self.options.boundary == "clamp":
            Simulation._move(self, ant)
            return
        nav = self.config.navigation
        left, right = sense(self.field, ant.position, ant.heading, nav)
        decision = navigate(heading=ant.heading, left=left, right=right, role=ant.role,
                            low_steps=ant.low_steps, fcrw_turn=float(self._turns[ant.ant_id][self.time - 1]),
                            noise=float(self._noise[ant.ant_id][self.time - 1]), config=nav)
        ant.role, ant.low_steps = decision.role, decision.low_steps
        ant.position, ant.heading = reflect(ant.position, decision.heading, self.config.step_size,
                                            self.config.arena_size)
        ant.path.append(ant.position)

    def _integrate(self, ant: Ant, old) -> None:
        dx, dy = ant.position[0] - old[0], ant.position[1] - old[1]
        if dx or dy:
            noise = self._compass[ant.ant_id]
            if noise is not None:
                a = float(noise[self.time - 1])
                c, s = math.cos(a), math.sin(a)
                dx, dy = c * dx - s * dy, s * dx + c * dy
            ex, ey = self.estimate[ant.ant_id]
            self.estimate[ant.ant_id] = (ex + dx, ey + dy)

    def _step_toward(self, ant: Ant, target, length: float) -> None:
        dx, dy = target[0] - ant.position[0], target[1] - ant.position[1]
        d = math.hypot(dx, dy)
        if d == 0:
            return
        ant.heading = wrap(math.atan2(dy, dx))
        if d <= length:
            x, y = target
        else:
            x, y = ant.position[0] + length * dx / d, ant.position[1] + length * dy / d
        size = self.config.arena_size
        ant.position = (min(max(float(x), 0.0), size), min(max(float(y), 0.0), size))

    def _home_move(self, ant: Ant) -> None:
        """Walk the home vector; if the estimate says 'home' but the nest is not seen, spiral-search."""
        nest, step, i = self.config.nest, self.config.step_size, ant.ant_id
        if math.dist(ant.position, nest) <= NEST_CUE_RADIUS:
            self._step_toward(ant, nest, step)
        else:
            if self.mode.get(i) == "home":
                est = self.estimate[i]
                if math.dist(est, nest) <= step:
                    self.mode[i] = "search"
                    self.search[i] = [ant.position, 0.0]
                    self.search_starts += 1
                else:
                    self._step_toward(ant, (ant.position[0] + nest[0] - est[0],
                                            ant.position[1] + nest[1] - est[1]), step)
            if self.mode.get(i) == "search":
                state = self.search[i]
                state[1] += step
                a = SPIRAL_SPACING / (2 * math.pi)
                phi = math.sqrt(2 * state[1] / a)
                c = state[0]
                self._step_toward(ant, (c[0] + a * phi * math.cos(phi), c[1] + a * phi * math.sin(phi)), step)
                self._searched.add(i)
        ant.path.append(ant.position)

    def _contacts(self, ant: Ant) -> None:
        before = ant.role
        super()._contacts(ant)
        if self.options.homing == "vector":
            if before != "transporter" and ant.role == "transporter":
                self.mode[ant.ant_id] = "home"
            elif before == "transporter" and ant.role != "transporter":
                self.estimate[ant.ant_id] = tuple(ant.position)  # the seen nest re-anchors the estimate
                self.mode.pop(ant.ant_id, None)
                self.search.pop(ant.ant_id, None)
        if before != "transporter" and ant.role == "transporter":
            self.pickup_roles.append((self.time, before))
            if self.options.return_stride > 1:
                coarse = coarse_grain_path(ant.path, stride=self.options.return_stride)[::-1]
                self.routes[ant.ant_id] = [(float(x), float(y)) for x, y in coarse[1:]]
        elif before == "transporter" and ant.role != "transporter":
            self.routes.pop(ant.ant_id, None)
            if self.options.after_delivery == "follower":
                ant.role, ant.low_steps = "follower", 0
                ant.heading = wrap(ant.heading + math.pi)

    def step(self) -> None:
        if self.time >= self.config.steps:
            raise ValueError("declared horizon exhausted")
        self.time += 1
        self.field.advance(self.time)
        self.environment.relocate(self.time, self.ledger)
        previous = [ant.position for ant in self.ants]
        transporting = [ant.role == "transporter" for ant in self.ants]
        if self.options.homing == "vector":
            self._searched.clear()
        for ant in self.ants:
            self._move(ant)
        for ant in self.ants:
            self._contacts(ant)
        if self.options.deposit:
            for ant, was_transporting in zip(self.ants, transporting):
                if was_transporting and not (self.options.homing == "vector" and ant.ant_id in self._searched):
                    self.field.deposit(ant.position, self.config.deposit_q)
        if self.record:
            self._record(previous)
        self.validate()

    def _record(self, previous: list) -> None:
        directions = np.empty(len(self.ants))
        counts = [0, 0, 0]
        for k, (ant, old) in enumerate(zip(self.ants, previous)):
            dx, dy = ant.position[0] - old[0], ant.position[1] - old[1]
            directions[k] = math.atan2(dy, dx) if (dx or dy) else ant.heading
            counts[ROLES.index(ant.role)] += 1
        i = self.time - 1
        self.phi[i], self.psi[i] = order_parameters(directions)
        self.counts[i] = counts
