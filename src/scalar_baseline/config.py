"""Validated provisional settings and canonical decay parameterisation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math


def positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def integer(value: int, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def half_life_to_rate(half_life_steps: float) -> float:
    return positive(math.log(2) / positive(half_life_steps, "half life"), "rate")


def rate_to_half_life(decay_rate: float) -> float:
    return positive(math.log(2) / positive(decay_rate, "rate"), "half life")


def matched_cutoff_steps(q: float, threshold: float, decay_rate: float) -> int:
    positive(q, "q")
    positive(threshold, "threshold")
    positive(decay_rate, "rate")
    if q <= threshold:
        raise ValueError("reference deposit must exceed detection threshold")
    time = (math.log(q) - math.log(threshold)) / decay_rate
    positive(time, "detectable time")
    nearest = round(time)
    if nearest >= 1 and abs(time - nearest) <= 1e-12:
        time = float(nearest)
    return max(1, math.ceil(time))


@dataclass(frozen=True)
class DecayConfig:
    mode: str = "exponential"
    half_life_steps: float | None = None
    decay_rate: float | None = None
    cutoff_steps: int | None = None

    def __post_init__(self) -> None:
        if self.mode == "exponential":
            if self.cutoff_steps is not None:
                raise ValueError("exponential does not accept cutoff_steps")
            half, rate = self.half_life_steps, self.decay_rate
            if half is None and rate is None:
                half = 20.0
            if rate is not None:
                positive(rate, "rate")
            if half is not None:
                canonical = half_life_to_rate(half)
                if rate is not None and not math.isclose(canonical, rate, rel_tol=1e-12, abs_tol=0):
                    raise ValueError("inconsistent half_life_steps and decay_rate")
                rate = canonical
            object.__setattr__(self, "decay_rate", rate)
            object.__setattr__(self, "half_life_steps", rate_to_half_life(rate))
        elif self.mode == "hard_cutoff_cell_timer":
            if self.half_life_steps is not None or self.decay_rate is not None:
                raise ValueError("cutoff does not accept exponential parameters")
            integer(self.cutoff_steps, "cutoff_steps")
        else:
            raise ValueError("unknown decay mode")


@dataclass(frozen=True)
class B0Config:
    signal_on: float = 0.5
    signal_off: float = 0.25
    loss_steps: int = 2
    epsilon: float = 1e-12
    max_turn: float = math.pi / 3
    noise_amplitude: float = 0.05
    sensor_distance: float = 1.0
    sensor_angle: float = math.pi / 4

    def __post_init__(self) -> None:
        for name in ("signal_on", "signal_off", "epsilon", "max_turn", "sensor_distance", "sensor_angle"):
            positive(getattr(self, name), name)
        if self.signal_off > self.signal_on:
            raise ValueError("off threshold must not exceed on threshold")
        integer(self.loss_steps, "loss_steps")
        if not math.isfinite(self.noise_amplitude) or not 0 <= self.noise_amplitude <= self.max_turn <= math.pi:
            raise ValueError("require 0 <= noise <= max_turn <= pi")
        if self.sensor_angle > math.pi / 2:
            raise ValueError("sensors must face forward or sideways")


@dataclass(frozen=True)
class SimulationConfig:
    n_ants: int = 10
    steps: int = 100
    seed: int = 20260917
    arena_size: float = 40.0
    cell_size: float = 1.0
    diffusion: float = 0.0
    deposit_q: float = 1.0
    step_size: float = 0.6
    gamma: float = 0.2
    theta_max: float = math.pi / 3
    nest: tuple[float, float] = (20.0, 20.0)
    food_a: tuple[float, float] = (28.0, 20.0)
    food_b: tuple[float, float] = (20.0, 28.0)
    contact_radius: float = 0.75
    relocation_step: int | None = None
    decay: DecayConfig = field(default_factory=DecayConfig)
    navigation: B0Config = field(default_factory=B0Config)

    def __post_init__(self) -> None:
        for name in ("n_ants", "steps"):
            integer(getattr(self, name), name)
        integer(self.seed, "seed", 0)
        for name in ("arena_size", "cell_size", "deposit_q", "step_size", "contact_radius"):
            positive(getattr(self, name), name)
        if self.diffusion != 0:
            raise ValueError("Stage 3A requires diffusion=0")
        if self.cell_size > self.arena_size:
            raise ValueError("cell_size must not exceed arena_size")
        if not math.isfinite(self.gamma) or not 0 <= self.gamma <= 0.5:
            raise ValueError("gamma outside frozen FCRW range")
        if not math.isfinite(self.theta_max) or not 0 <= self.theta_max <= math.pi:
            raise ValueError("theta_max outside [0,pi]")
        for point in (self.nest, self.food_a, self.food_b):
            if len(point) != 2 or any(not math.isfinite(x) or not 0 <= x <= self.arena_size for x in point):
                raise ValueError("contact centres must be finite and inside arena")
        distances = [math.dist(self.nest, p) for p in (self.food_a, self.food_b)]
        if not math.isclose(*distances, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("A and B must be equally distant from nest")
        if min(distances) <= 2 * self.contact_radius or self.food_a == self.food_b:
            raise ValueError("food contacts must be distinct from nest and each other")
        if self.relocation_step is not None:
            integer(self.relocation_step, "relocation_step")
            if self.relocation_step > self.steps:
                raise ValueError("relocation must fall inside horizon")
