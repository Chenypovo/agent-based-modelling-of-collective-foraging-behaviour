"""Centralised configuration for the provisional Stage 2A colony model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

MovementModel = Literal["srw", "fcrw", "zw"]


@dataclass(frozen=True)
class SiteConfig:
    """A circular site used for provisional nest/food event detection."""

    center: tuple[float, float]
    radius: float

    def __post_init__(self) -> None:
        centre = np.asarray(self.center, dtype=float)
        if centre.shape != (2,) or not np.isfinite(centre).all():
            raise ValueError("site center must contain two finite coordinates")
        if not np.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("site radius must be finite and positive")


@dataclass(frozen=True)
class MovementConfig:
    """Movement parameters shared with the existing Stage 1 implementation."""

    model: MovementModel = "zw"
    step_size: float = 0.6
    time_step: float = 1.0
    theta_deg: float = 50.0
    gamma: float = 0.1

    def __post_init__(self) -> None:
        if self.model not in {"srw", "fcrw", "zw"}:
            raise ValueError("movement model must be srw, fcrw, or zw")
        if not np.isfinite(self.step_size) or self.step_size <= 0:
            raise ValueError("step_size must be finite and positive")
        if not np.isfinite(self.time_step) or self.time_step <= 0:
            raise ValueError("time_step must be finite and positive")
        if not np.isfinite(self.theta_deg) or not 0 <= self.theta_deg <= 180:
            raise ValueError("theta_deg must be between 0 and 180")
        if not np.isfinite(self.gamma) or not 0 <= self.gamma <= 0.5:
            raise ValueError("gamma must be between 0 and 0.5")

    @property
    def speed(self) -> float:
        return self.step_size / self.time_step


@dataclass(frozen=True)
class PheromoneConfig:
    """Replaceable discrete pheromone-field parameters."""

    cell_size: float = 0.6
    sensing_range: float = 0.6
    deposit_amount: float = 1.0
    decay_rate: float = 0.0
    diffusion_rate: float = 0.0
    tie_break_rule: str = "food_projection_then_lexicographic"
    follower_no_signal_policy: str = "continue_heading"

    def __post_init__(self) -> None:
        for name, value in (
            ("cell_size", self.cell_size),
            ("sensing_range", self.sensing_range),
            ("deposit_amount", self.deposit_amount),
        ):
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.decay_rate != 0.0:
            raise ValueError("pheromone decay is outside the Stage 2A scope")
        if self.diffusion_rate != 0.0:
            raise ValueError("pheromone diffusion is outside the Stage 2A scope")
        if self.tie_break_rule != "food_projection_then_lexicographic":
            raise ValueError("unsupported pheromone tie-break rule")
        if self.follower_no_signal_policy != "continue_heading":
            raise ValueError("unsupported follower no-signal policy")


@dataclass(frozen=True)
class ColonyConfig:
    """Complete Stage 2A configuration; provisional rules live here."""

    n_ants: int = 100
    arena_size: float = 300.0
    steps: int = 10_000
    seed: int = 20_260_824
    movement: MovementConfig = field(default_factory=MovementConfig)
    pheromone: PheromoneConfig = field(default_factory=PheromoneConfig)
    nest: SiteConfig = field(default_factory=lambda: SiteConfig((90.0, 90.0), 3.0))
    food: SiteConfig = field(default_factory=lambda: SiteConfig((240.0, 240.0), 3.0))
    food_is_inexhaustible: bool = True
    initial_position_rule: str = "nest_centre"
    initial_heading_rule: str = "iid_uniform_0_2pi"
    initial_role_rule: str = "all_forager"
    food_detection_rule: str = "site_radius_plus_sensing_range"
    nest_arrival_rule: str = "site_radius"
    memory_stride: int = 3
    memory_final_vertex_rule: str = "append_if_not_retained"
    transporter_motion_rule: str = "reverse_interpolated_coarse_path"
    transporter_post_nest_role: str = "follower"
    boundary_rule: str = "reflect_overshoot_and_velocity_component"
    event_order_rule: str = "move_deposit_then_transition_food_before_pheromone"
    snapshot_steps: tuple[int, ...] = (1_000, 4_000, 10_000)
    agent_state_interval: int = 100
    output_dir: str = "results/stage2_provisional"

    def __post_init__(self) -> None:
        if isinstance(self.n_ants, bool) or not isinstance(self.n_ants, (int, np.integer)):
            raise ValueError("n_ants must be an integer")
        if self.n_ants < 1:
            raise ValueError("n_ants must be positive")
        if not np.isfinite(self.arena_size) or self.arena_size <= 0:
            raise ValueError("arena_size must be finite and positive")
        if isinstance(self.steps, bool) or not isinstance(self.steps, (int, np.integer)):
            raise ValueError("steps must be an integer")
        if self.steps < 1:
            raise ValueError("steps must be positive")
        if self.movement.step_size > self.arena_size:
            raise ValueError("step_size must not exceed arena_size")
        for label, site in (("nest", self.nest), ("food", self.food)):
            centre = np.asarray(site.center, dtype=float)
            if np.any(centre < 0.0) or np.any(centre > self.arena_size):
                raise ValueError(f"{label} center must lie inside the arena")
        if self.memory_stride < 1:
            raise ValueError("memory_stride must be positive")
        if self.agent_state_interval < 1:
            raise ValueError("agent_state_interval must be positive")
        if any(step < 0 or step > self.steps for step in self.snapshot_steps):
            raise ValueError("snapshot steps must lie between zero and steps")
        if tuple(sorted(set(self.snapshot_steps))) != self.snapshot_steps:
            raise ValueError("snapshot_steps must be unique and sorted")
        if not self.food_is_inexhaustible:
            raise ValueError("food depletion is outside the Stage 2A scope")
        expected_rules = {
            "initial_position_rule": (self.initial_position_rule, "nest_centre"),
            "initial_heading_rule": (self.initial_heading_rule, "iid_uniform_0_2pi"),
            "initial_role_rule": (self.initial_role_rule, "all_forager"),
            "food_detection_rule": (
                self.food_detection_rule,
                "site_radius_plus_sensing_range",
            ),
            "nest_arrival_rule": (self.nest_arrival_rule, "site_radius"),
            "memory_final_vertex_rule": (
                self.memory_final_vertex_rule,
                "append_if_not_retained",
            ),
            "transporter_motion_rule": (
                self.transporter_motion_rule,
                "reverse_interpolated_coarse_path",
            ),
            "transporter_post_nest_role": (
                self.transporter_post_nest_role,
                "follower",
            ),
            "boundary_rule": (
                self.boundary_rule,
                "reflect_overshoot_and_velocity_component",
            ),
            "event_order_rule": (
                self.event_order_rule,
                "move_deposit_then_transition_food_before_pheromone",
            ),
        }
        for name, (actual, expected) in expected_rules.items():
            if actual != expected:
                raise ValueError(f"unsupported {name}: {actual!r}")

    @property
    def food_detection_distance(self) -> float:
        return self.food.radius + self.pheromone.sensing_range

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def paper_scale(cls, output_dir: str | Path = "results/stage2_provisional") -> "ColonyConfig":
        return cls(output_dir=str(output_dir))

    @classmethod
    def pilot(cls, output_dir: str | Path = "results/stage2_provisional/pilot") -> "ColonyConfig":
        return cls(
            n_ants=10,
            arena_size=45.0,
            steps=1_000,
            nest=SiteConfig((12.0, 12.0), 3.0),
            food=SiteConfig((27.0, 27.0), 3.0),
            snapshot_steps=(250, 500, 1_000),
            agent_state_interval=25,
            output_dir=str(output_dir),
        )
