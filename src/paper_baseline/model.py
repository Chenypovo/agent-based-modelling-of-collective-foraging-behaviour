"""Zhang & Yong (2023) rules on the Eq. (1) scalar field, as options on the validated Simulation.

All options at their defaults reproduce ``scalar_baseline.simulation.Simulation`` exactly.
Paper baseline: ``PaperOptions(boundary="reflect", return_stride=3, after_delivery="follower",
field="diffusing", diffusion=D)``.
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


def baseline_options(diffusion: float, *, walk: str = "fcrw", deposit: bool = True) -> PaperOptions:
    return PaperOptions(walk=walk, boundary="reflect", return_stride=3, after_delivery="follower",
                        deposit=deposit, field="diffusing", diffusion=diffusion)


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
        if record:
            n = config.steps
            self.phi, self.psi = np.zeros(n), np.zeros(n)
            self.counts = np.zeros((n, 3), dtype=np.int32)  # foragers, transporters, followers

    def _move(self, ant: Ant) -> None:
        opts = self.options
        if ant.role == "transporter":
            if opts.return_stride == 1:
                super()._move(ant)
                return
            route = self.routes.get(ant.ant_id)
            if route:
                ant.position, heading = walk_route(ant.position, route, self.config.step_size)
                if heading is not None:
                    ant.heading = heading
                ant.path.append(ant.position)
            return
        if opts.boundary == "clamp":
            super()._move(ant)
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

    def _contacts(self, ant: Ant) -> None:
        before = ant.role
        super()._contacts(ant)
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
        for ant in self.ants:
            self._move(ant)
        for ant in self.ants:
            self._contacts(ant)
        if self.options.deposit:
            for ant, was_transporting in zip(self.ants, transporting):
                if was_transporting:
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
