"""Ground scalar concentration, with no directional or source data."""

import math
import numpy as np

from .config import DecayConfig, integer, positive


class ScalarField:
    __slots__ = ("concentration", "last_deposit", "time", "arena_size", "cell_size", "decay")

    def __init__(self, arena_size: float, cell_size: float, decay: DecayConfig, *, diffusion: float = 0):
        positive(arena_size, "arena_size")
        positive(cell_size, "cell_size")
        if diffusion != 0 or cell_size > arena_size:
            raise ValueError("requires diffusion=0 and cell_size<=arena_size")
        self.arena_size, self.cell_size, self.decay = arena_size, cell_size, decay
        n = math.ceil(arena_size / cell_size)
        self.concentration = np.zeros((n, n), dtype=np.float64)
        self.last_deposit = np.full((n, n), -1, dtype=np.int64) if decay.mode == "hard_cutoff_cell_timer" else None
        self.time = 0

    def _index(self, point: tuple[float, float]) -> tuple[int, int]:
        if len(point) != 2 or not all(math.isfinite(x) for x in point):
            raise ValueError("point must contain two finite coordinates")
        n = self.concentration.shape[0]
        return tuple(min(n - 1, max(0, math.floor(x / self.cell_size))) for x in point)

    def sample(self, point: tuple[float, float]) -> float:
        return float(self.concentration[self._index(point)])

    def advance(self, time: int) -> None:
        integer(time, "time", 0)
        if time < self.time:
            raise ValueError("field time cannot go backwards")
        if self.decay.mode == "exponential":
            self.concentration *= math.exp(-self.decay.decay_rate * (time - self.time))
        else:
            expired = (self.last_deposit >= 0) & (time - self.last_deposit >= self.decay.cutoff_steps)
            self.concentration[expired] = 0
            self.last_deposit[expired] = -1
        self.time = time

    def deposit(self, point: tuple[float, float], amount: float) -> None:
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("deposit must be finite and nonnegative")
        index = self._index(point)
        value = float(self.concentration[index]) + float(amount)
        if not math.isfinite(value):
            raise ValueError("deposit would overflow")
        if amount > 0:
            self.concentration[index] = value
            if self.last_deposit is not None:
                self.last_deposit[index] = self.time

    def step(self, deposits=()) -> None:
        self.advance(self.time + 1)
        for point, amount in deposits:
            self.deposit(point, amount)
