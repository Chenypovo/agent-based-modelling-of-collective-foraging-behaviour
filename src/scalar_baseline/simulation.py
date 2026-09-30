"""Bounded scalar B0 simulation with isolated contact resolution."""

from dataclasses import dataclass, field
import math
import numpy as np

from ant_walks.models import generate_trajectory
from .config import SimulationConfig
from .environment import ContactEnvironment, Ledger
from .field import ScalarField
from .navigation import navigate
from .sensing import sense


@dataclass
class Ant:
    ant_id: int
    position: tuple[float, float]
    heading: float
    role: str = "fcrw"
    low_steps: int = 0
    path: list = field(default_factory=list)


class Simulation:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.field = ScalarField(config.arena_size, config.cell_size, config.decay, diffusion=config.diffusion)
        self.environment = ContactEnvironment(config)
        self.ledger = Ledger()
        self.time = 0
        self.ants = []
        self._turns, self._noise = [], []
        for i in range(config.n_ants):
            heading_rng = np.random.default_rng(np.random.SeedSequence([config.seed, i, 1]))
            walk_rng = np.random.default_rng(np.random.SeedSequence([config.seed, i, 2]))
            noise_rng = np.random.default_rng(np.random.SeedSequence([config.seed, i, 3]))
            self.ants.append(Ant(i, config.nest, float(heading_rng.uniform(0, 2 * math.pi)), path=[config.nest]))
            trajectory = generate_trajectory("fcrw", steps=config.steps, step_size=config.step_size,
                                             theta_max=config.theta_max, gamma=config.gamma, rng=walk_rng)
            self._turns.append(trajectory.turn_angles)
            self._noise.append(noise_rng.uniform(-config.navigation.noise_amplitude,
                                                 config.navigation.noise_amplitude, config.steps))

    def _move(self, ant: Ant) -> None:
        if ant.role == "transporter":
            if len(ant.path) > 1:
                ant.path.pop()
                target = ant.path[-1]
                dx, dy = target[0] - ant.position[0], target[1] - ant.position[1]
                if dx or dy:
                    ant.heading = math.atan2(dy, dx) % (2 * math.pi)
                ant.position = target
            return
        left, right = sense(self.field, ant.position, ant.heading, self.config.navigation)
        decision = navigate(heading=ant.heading, left=left, right=right, role=ant.role,
                            low_steps=ant.low_steps, fcrw_turn=float(self._turns[ant.ant_id][self.time - 1]),
                            noise=float(self._noise[ant.ant_id][self.time - 1]), config=self.config.navigation)
        ant.heading, ant.role, ant.low_steps = decision.heading, decision.role, decision.low_steps
        ant.position = tuple(max(0.0, min(self.config.arena_size, p + self.config.step_size * d))
                             for p, d in zip(ant.position, (math.cos(ant.heading), math.sin(ant.heading))))
        ant.path.append(ant.position)

    def _contacts(self, ant: Ant) -> None:
        if ant.role == "transporter":
            if self.environment.nest_contact(ant.position):
                self.ledger.deliver(ant.ant_id, self.time)
                ant.role, ant.low_steps, ant.path = "fcrw", 0, [ant.position]
        else:
            source = self.environment.food_contact(ant.position)
            if source is not None:
                self.ledger.pickup(ant.ant_id, source, self.time)
                ant.role, ant.low_steps = "transporter", 0

    def step(self) -> None:
        if self.time >= self.config.steps:
            raise ValueError("declared horizon exhausted")
        self.time += 1
        self.field.advance(self.time)
        self.environment.relocate(self.time, self.ledger)
        transporting = [ant.role == "transporter" for ant in self.ants]
        for ant in self.ants:
            self._move(ant)
        for ant in self.ants:
            self._contacts(ant)
        for ant, was_transporting in zip(self.ants, transporting):
            if was_transporting:
                self.field.deposit(ant.position, self.config.deposit_q)
        self.validate()

    def validate(self) -> None:
        if len(self.ants) != self.config.n_ants or {a.ant_id for a in self.ants} != set(range(self.config.n_ants)):
            raise AssertionError("population changed")
        if not np.all(np.isfinite(self.field.concentration)) or np.any(self.field.concentration < 0):
            raise AssertionError("invalid concentration")
        for ant in self.ants:
            if ant.role not in {"follower", "fcrw", "transporter"}:
                raise AssertionError("invalid role")
            if not all(math.isfinite(v) and 0 <= v <= self.config.arena_size for v in ant.position):
                raise AssertionError("invalid position")
            if not math.isfinite(ant.heading) or not 0 <= ant.heading < 2 * math.pi:
                raise AssertionError("invalid heading")
            if not 1 <= len(ant.path) <= self.config.steps + 1 or ant.path[-1] != ant.position:
                raise AssertionError("invalid own-path memory")
            if (ant.role == "transporter") != (ant.ant_id in self.ledger.cargo):
                raise AssertionError("cargo/role mismatch")
        for source in ("A", "B"):
            carried = sum(value == source for value in self.ledger.cargo.values())
            if self.ledger.discoveries[source] != self.ledger.deliveries[source] + carried:
                raise AssertionError("cargo conservation failed")

    def run(self) -> None:
        while self.time < self.config.steps:
            self.step()
