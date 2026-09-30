"""Diffusing scalar pheromone field: proposal Eq. (1) with explicit finite differences.

dP/dt = D * laplacian(P) - lambda * P + S, one diffusion sub-step per simulation step,
P = 0 outside the arena (absorbing edge). Stable for D * dt / dx^2 <= 1/4.
diffusion=0 reproduces the validated ScalarField exactly.
"""

from __future__ import annotations

import math

import numpy as np

from scalar_baseline.config import DecayConfig, integer
from scalar_baseline.field import ScalarField


class DiffusingField(ScalarField):
    __slots__ = ("diffusion",)

    def __init__(self, arena_size: float, cell_size: float, decay: DecayConfig, *, diffusion: float):
        if not math.isfinite(diffusion) or diffusion < 0:
            raise ValueError("diffusion must be finite and >= 0")
        if decay.mode != "exponential":
            raise ValueError("diffusing field supports exponential decay only")
        if diffusion / cell_size ** 2 > 0.25:
            raise ValueError("explicit diffusion unstable: need D/dx^2 <= 1/4")
        super().__init__(arena_size, cell_size, decay, diffusion=0)
        self.diffusion = float(diffusion)

    def advance(self, time: int) -> None:
        integer(time, "time", 0)
        if time < self.time:
            raise ValueError("field time cannot go backwards")
        if self.diffusion == 0:
            super().advance(time)
            return
        r = self.diffusion / self.cell_size ** 2
        keep = math.exp(-self.decay.decay_rate)
        c = self.concentration
        for _ in range(time - self.time):
            lap = -4.0 * c
            lap[1:, :] += c[:-1, :]
            lap[:-1, :] += c[1:, :]
            lap[:, 1:] += c[:, :-1]
            lap[:, :-1] += c[:, 1:]
            c += r * lap
            np.maximum(c, 0.0, out=c)
            c *= keep
        self.time = time
