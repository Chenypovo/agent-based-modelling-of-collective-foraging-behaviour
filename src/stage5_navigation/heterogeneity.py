"""Movement heterogeneity (H1b): per-ant FCRW turning amplitude on the path-integration model.

Only the FCRW turn amplitude ``theta_max`` differs between ants; sensing, pheromone response and
homing are unchanged. Each ant's turn sequence is regenerated from the same random stream the parent
uses (``SeedSequence([seed, ant_id, 2])``), so a turn of ant i is ``theta_i / theta_ref`` times the
turn it would make in the homogeneous colony (common random numbers). ``theta_max_per_ant=None`` or
all values equal to ``config.theta_max`` reproduces ``PathIntegrationSimulation`` exactly.

Per-step persistence of an FCRW step with magnitude ~ U(0, theta) and random sign is
c(theta) = E[cos(turn)] = sin(theta) / theta.
"""

from __future__ import annotations

import math

import numpy as np

from ant_walks.models import generate_trajectory
from scalar_baseline.config import SimulationConfig
from .path_integration import NavigationConfig, PathIntegrationSimulation


def persistence(theta: float) -> float:
    """E[cos(turn)] for turn magnitudes uniform on [0, theta]."""
    return 1.0 if theta == 0 else math.sin(theta) / theta


def matched_theta(theta_ref: float, fraction: float, theta_other: float) -> float:
    """theta for the remaining (1 - fraction) of ants so the colony-mean persistence equals c(theta_ref)."""
    if not 0 < fraction < 1:
        raise ValueError("fraction must be in (0, 1)")
    target = (persistence(theta_ref) - fraction * persistence(theta_other)) / (1 - fraction)
    if not persistence(math.pi) <= target <= 1:
        raise ValueError("no matching theta in [0, pi]")
    lo, hi = 0.0, math.pi  # persistence is strictly decreasing on [0, pi]
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if persistence(mid) > target else (lo, mid)
    return (lo + hi) / 2


def group_assignment(seed: int, n_ants: int, n_group: int) -> tuple[int, ...]:
    """Ant ids of the first group, drawn per seed independently of all simulation streams."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, 77]))
    return tuple(sorted(int(i) for i in rng.choice(n_ants, size=n_group, replace=False)))


class HeterogeneousPISimulation(PathIntegrationSimulation):
    def __init__(self, config: SimulationConfig, navigation: NavigationConfig,
                 theta_max_per_ant: tuple[float, ...] | None = None):
        if theta_max_per_ant is not None:
            if len(theta_max_per_ant) != config.n_ants:
                raise ValueError("need one theta_max per ant")
            if any(not math.isfinite(t) or not 0 <= t <= math.pi for t in theta_max_per_ant):
                raise ValueError("theta_max outside [0, pi]")
        self.theta_max_per_ant = (tuple(float(t) for t in theta_max_per_ant) if theta_max_per_ant is not None
                                  else (config.theta_max,) * config.n_ants)
        super().__init__(config, navigation)
        for i, theta in enumerate(self.theta_max_per_ant):
            if theta != config.theta_max:
                walk_rng = np.random.default_rng(np.random.SeedSequence([config.seed, i, 2]))
                self._turns[i] = generate_trajectory("fcrw", steps=config.steps, step_size=config.step_size,
                                                     theta_max=theta, gamma=config.gamma,
                                                     rng=walk_rng).turn_angles
