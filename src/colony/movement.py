"""Adapter that reuses Stage 1 movement code without copying walk rules."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ant_walks.models import generate_trajectory

from .config import ColonyConfig


def _derived_turn_seed(base_seed: int, ant_id: int) -> int:
    sequence = np.random.SeedSequence([base_seed, 54_306, ant_id])
    return int(sequence.generate_state(1, dtype=np.uint64)[0])


def initial_headings(config: ColonyConfig) -> NDArray[np.float64]:
    sequence = np.random.SeedSequence([config.seed, 4_004, config.n_ants])
    rng = np.random.default_rng(sequence)
    return rng.uniform(0.0, 2.0 * np.pi, size=config.n_ants)


def build_turn_schedules(config: ColonyConfig) -> NDArray[np.float64]:
    """Generate each ant's forager turns through the existing Stage 1 API."""

    schedules = np.empty((config.n_ants, config.steps), dtype=float)
    for ant_id in range(config.n_ants):
        trajectory = generate_trajectory(
            config.movement.model,
            steps=config.steps,
            step_size=config.movement.step_size,
            theta_max=np.deg2rad(config.movement.theta_deg),
            gamma=config.movement.gamma,
            seed=_derived_turn_seed(config.seed, ant_id),
        )
        schedules[ant_id] = trajectory.turn_angles
    return schedules
