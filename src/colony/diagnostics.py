"""Read-only diagnostics for the frozen Stage 2A colony dynamics.

This module does not sample randomness and does not modify any model rule or
parameter. ``DiagnosticSimulation`` delegates every movement, sensing, field,
and transition decision to ``ColonySimulation`` and only records copies of
state before or after those decisions.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .agents import Ant, Role
from .metrics import compute_order_parameters, fold_headings
from .pheromone import PheromoneField
from .simulation import ColonySimulation, FollowerDirectionDecision, SimulationResult

NOTICE = "Stage 2A diagnostic only — no model rules or parameters changed."
ROLE_SAMPLE_WARNING_THRESHOLD = 5


def axial_angle_error(
    headings: NDArray[np.float64] | Sequence[float], axis_angle: float
) -> NDArray[np.float64]:
    """Smallest absolute angle to an unoriented axis, in ``[0, pi/2]``."""

    angles = np.asarray(headings, dtype=float)
    if not np.isfinite(angles).all() or not np.isfinite(axis_angle):
        raise ValueError("headings and axis_angle must be finite")
    difference = angles - float(axis_angle)
    return np.abs(0.5 * np.arctan2(np.sin(2.0 * difference), np.cos(2.0 * difference)))


def directed_angle_error(angle: float, target_angle: float) -> float:
    """Smallest absolute directed-angle difference, in ``[0, pi]``."""

    if not np.isfinite(angle) or not np.isfinite(target_angle):
        raise ValueError("angles must be finite")
    return float(abs(np.arctan2(np.sin(angle - target_angle), np.cos(angle - target_angle))))


def role_order_rows(
    ants: Sequence[Ant], *, time: int, axis_angle: float, speed: float
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Compute role-specific order and bidirectional axis alignment summaries."""

    order_rows: list[dict[str, object]] = []
    axis_rows: list[dict[str, object]] = []
    axis_unit = np.array([np.cos(axis_angle), np.sin(axis_angle)], dtype=float)
    perpendicular_unit = np.array([-axis_unit[1], axis_unit[0]], dtype=float)

    for role in Role:
        selected = [ant for ant in ants if ant.role is role]
        headings = np.asarray([ant.heading for ant in selected], dtype=float)
        count = len(headings)
        insufficient = count < ROLE_SAMPLE_WARNING_THRESHOLD
        warning = "insufficient sample; do not over-interpret" if insufficient else ""
        if count:
            phi, psi = compute_order_parameters(headings)
            folded = fold_headings(headings)
            vector_x = float(np.mean(np.cos(folded)))
            vector_y = float(np.mean(np.sin(folded)))
            errors = axial_angle_error(headings, axis_angle)
            velocities = speed * np.column_stack((np.cos(headings), np.sin(headings)))
            along = velocities @ axis_unit
            perpendicular = velocities @ perpendicular_unit
            mean_error = float(np.mean(errors))
            median_error = float(np.median(errors))
            p90_error = float(np.quantile(errors, 0.90))
        else:
            phi = psi = vector_x = vector_y = float("nan")
            mean_error = median_error = p90_error = float("nan")
            along = perpendicular = np.empty(0, dtype=float)

        order_rows.append(
            {
                "time": int(time),
                "role": role.value,
                "sample_count": count,
                "orientation_order_phi": phi,
                "nematic_order_psi": psi,
                "folded_vector_x": vector_x,
                "folded_vector_y": vector_y,
                "sample_too_small": insufficient,
                "interpretation_warning": warning,
            }
        )
        axis_rows.append(
            {
                "time": int(time),
                "role": role.value,
                "sample_count": count,
                "axis_angle_rad": float(axis_angle),
                "mean_axial_error_rad": mean_error,
                "median_axial_error_rad": median_error,
                "p90_axial_error_rad": p90_error,
                "mean_axial_error_deg": float(np.degrees(mean_error)),
                "median_axial_error_deg": float(np.degrees(median_error)),
                "p90_axial_error_deg": float(np.degrees(p90_error)),
                "mean_signed_axis_velocity": float(np.mean(along)) if count else float("nan"),
                "mean_abs_axis_velocity": float(np.mean(np.abs(along))) if count else float("nan"),
                "mean_signed_perpendicular_velocity": (
                    float(np.mean(perpendicular)) if count else float("nan")
                ),
                "mean_abs_perpendicular_velocity": (
                    float(np.mean(np.abs(perpendicular))) if count else float("nan")
                ),
                "sample_too_small": insufficient,
                "interpretation_warning": warning,
            }
        )
    return order_rows, axis_rows


def weighted_quantile(values: NDArray[np.float64], weights: NDArray[np.float64], q: float) -> float:
    """Return the left-continuous weighted quantile for positive weights."""

    data = np.asarray(values, dtype=float)
    mass = np.asarray(weights, dtype=float)
    if data.ndim != 1 or mass.shape != data.shape or len(data) < 1:
        raise ValueError("values and weights must be non-empty one-dimensional arrays")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must lie between zero and one")
    if not np.isfinite(data).all() or not np.isfinite(mass).all() or np.any(mass < 0.0):
        raise ValueError("values and weights must be finite and weights non-negative")
    total = float(np.sum(mass))
    if total <= 0.0:
        raise ValueError("weights must have positive total")
    order = np.argsort(data, kind="mergesort")
    ordered_values = data[order]
    cumulative = np.cumsum(mass[order])
    index = int(np.searchsorted(cumulative, q * total, side="left"))
    return float(ordered_values[min(index, len(ordered_values) - 1)])


def top_fraction_intensity_share(values: NDArray[np.float64], fraction: float) -> float:
    """Fraction of total intensity carried by the exact top fraction of cells."""

    strengths = np.asarray(values, dtype=float).ravel()
    if len(strengths) < 1 or not np.isfinite(strengths).all() or np.any(strengths < 0.0):
        raise ValueError("values must be a non-empty finite non-negative array")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must lie in (0, 1]")
    total = float(np.sum(strengths))
    if total <= 0.0:
        return 0.0
    count = max(1, int(np.ceil(fraction * len(strengths))))
    top = np.partition(strengths, len(strengths) - count)[-count:]
    return float(np.sum(top) / total)


def _axis_distances(
    points: NDArray[np.float64], nest: NDArray[np.float64], food: NDArray[np.float64]
) -> NDArray[np.float64]:
    axis = food - nest
    norm = float(np.linalg.norm(axis))
    if norm <= 0.0:
        raise ValueError("nest and food must differ")
    unit = axis / norm
    relative = points - nest
    return np.abs(relative[:, 0] * unit[1] - relative[:, 1] * unit[0])


def _segment_distances(
    points: NDArray[np.float64], nest: NDArray[np.float64], food: NDArray[np.float64]
) -> NDArray[np.float64]:
    segment = food - nest
    squared = float(np.dot(segment, segment))
    if squared <= 0.0:
        raise ValueError("nest and food must differ")
    fractions = np.clip(((points - nest) @ segment) / squared, 0.0, 1.0)
    closest = nest + fractions[:, None] * segment
    return np.linalg.norm(points - closest, axis=1)


def channel_width_90(
    points: NDArray[np.float64],
    weights: NDArray[np.float64],
    nest: NDArray[np.float64],
    food: NDArray[np.float64],
) -> float:
    """Full width containing 90% of intensity by perpendicular axis distance."""

    distances = _axis_distances(np.asarray(points, dtype=float), nest, food)
    return 2.0 * weighted_quantile(distances, np.asarray(weights, dtype=float), 0.90)


def high_concentration_mask(intensity: NDArray[np.float64], fraction: float) -> tuple[NDArray[np.bool_], float]:
    """Tie-inclusive mask for the top fraction of active cells."""

    strengths = np.asarray(intensity, dtype=float)
    active = strengths[strengths > 0.0]
    if len(active) == 0:
        return np.zeros(strengths.shape, dtype=bool), float("nan")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must lie in (0, 1]")
    count = max(1, int(np.ceil(fraction * len(active))))
    threshold = float(np.partition(active, len(active) - count)[-count])
    return (strengths >= threshold) & (strengths > 0.0), threshold


def mask_connects_sites(
    mask: NDArray[np.bool_],
    *,
    cell_size: float,
    nest: Sequence[float],
    food: Sequence[float],
    nest_radius: float = 0.0,
    food_radius: float = 0.0,
) -> bool:
    """Check 8-neighbour grid connectivity between cells touching two sites."""

    selected = np.asarray(mask, dtype=bool)
    if selected.ndim != 2 or cell_size <= 0.0:
        raise ValueError("mask must be two-dimensional and cell_size positive")
    indices = np.argwhere(selected)
    if len(indices) == 0:
        return False
    centres = (indices.astype(float) + 0.5) * cell_size
    cell_half_diagonal = cell_size / np.sqrt(2.0)
    nest_point = np.asarray(nest, dtype=float)
    food_point = np.asarray(food, dtype=float)
    start_indices = indices[
        np.linalg.norm(centres - nest_point, axis=1) <= nest_radius + cell_half_diagonal + 1e-12
    ]
    end_indices = indices[
        np.linalg.norm(centres - food_point, axis=1) <= food_radius + cell_half_diagonal + 1e-12
    ]
    if len(start_indices) == 0 or len(end_indices) == 0:
        return False
    targets = {(int(i), int(j)) for i, j in end_indices}
    queue = deque((int(i), int(j)) for i, j in start_indices)
    visited = set(queue)
    while queue:
        ix, iy = queue.popleft()
        if (ix, iy) in targets:
            return True
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                neighbour = (ix + dx, iy + dy)
                if (
                    0 <= neighbour[0] < selected.shape[0]
                    and 0 <= neighbour[1] < selected.shape[1]
                    and selected[neighbour]
                    and neighbour not in visited
                ):
                    visited.add(neighbour)
                    queue.append(neighbour)
    return False


def pheromone_concentration_rows(
    intensity: NDArray[np.float64],
    *,
    cell_size: float,
    nest: Sequence[float],
    food: Sequence[float],
    nest_radius: float,
    food_radius: float,
    time: int,
) -> list[dict[str, object]]:
    """Summarise all history cells separately from high-concentration masks."""

    field = np.asarray(intensity, dtype=float)
    if field.ndim != 2 or np.any(field < 0.0) or not np.isfinite(field).all():
        raise ValueError("intensity must be a finite non-negative 2D array")
    total_cells = int(field.size)
    active_mask = field > 0.0
    active_values = field[active_mask]
    total_intensity = float(np.sum(field))
    active_count = int(np.count_nonzero(active_mask))
    if active_count == 0:
        return []
    all_values = field.ravel()
    quantiles = {
        f"all_grid_intensity_q{int(q * 100):02d}": float(np.quantile(all_values, q))
        for q in (0.0, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0)
    }
    quantiles.update(
        {
            f"active_intensity_q{int(q * 100):02d}": float(np.quantile(active_values, q))
            for q in (0.0, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0)
        }
    )
    top_shares = {
        f"top_{int(fraction * 100):02d}pct_all_grid_intensity_share": (
            top_fraction_intensity_share(all_values, fraction)
        )
        for fraction in (0.01, 0.05, 0.10)
    }
    scopes: list[tuple[str, str, NDArray[np.bool_], float]] = [
        ("all_active_history", "all historical deposited trajectory cells", active_mask, 0.0)
    ]
    for fraction in (0.01, 0.05, 0.10):
        mask, threshold = high_concentration_mask(field, fraction)
        scopes.append(
            (
                f"top_{int(fraction * 100):02d}pct_active_tie_inclusive",
                "high-concentration main trajectory candidate",
                mask,
                threshold,
            )
        )

    nest_point = np.asarray(nest, dtype=float)
    food_point = np.asarray(food, dtype=float)
    rows: list[dict[str, object]] = []
    for scope, interpretation, mask, threshold in scopes:
        indices = np.argwhere(mask)
        centres = (indices.astype(float) + 0.5) * cell_size
        strengths = field[mask]
        axis_distances = _axis_distances(centres, nest_point, food_point)
        segment_distances = _segment_distances(centres, nest_point, food_point)
        selected_intensity = float(np.sum(strengths))
        row: dict[str, object] = {
            "time": int(time),
            "scope": scope,
            "interpretation": interpretation,
            "total_grid_cells": total_cells,
            "active_cell_count": active_count,
            "active_area_fraction": active_count / total_cells,
            "total_intensity": total_intensity,
            "selection_threshold": threshold,
            "selected_cell_count": int(len(indices)),
            "selected_fraction_of_active": float(len(indices) / active_count),
            "selected_intensity_share": selected_intensity / total_intensity,
            "intensity_weighted_mean_axis_distance": float(
                np.average(axis_distances, weights=strengths)
            ),
            "intensity_weighted_median_axis_distance": weighted_quantile(
                axis_distances, strengths, 0.50
            ),
            "intensity_weighted_p90_axis_distance": weighted_quantile(
                axis_distances, strengths, 0.90
            ),
            "main_channel_width_90": channel_width_90(
                centres, strengths, nest_point, food_point
            ),
            "intensity_weighted_mean_segment_distance": float(
                np.average(segment_distances, weights=strengths)
            ),
            "connects_nest_to_food_8_neighbour": mask_connects_sites(
                mask,
                cell_size=cell_size,
                nest=nest_point,
                food=food_point,
                nest_radius=nest_radius,
                food_radius=food_radius,
            ),
        }
        row.update(quantiles)
        row.update(top_shares)
        rows.append(row)
    return rows


def inspect_sensing_candidates(
    field: PheromoneField, position: NDArray[np.float64], radius: float | None = None
) -> dict[str, object]:
    """Read candidate counts and maximum-strength ties without changing the field."""

    point = np.asarray(position, dtype=float)
    sensing_radius = field.config.sensing_range if radius is None else float(radius)
    lower = np.floor((point - sensing_radius) / field.config.cell_size).astype(int)
    upper = np.floor((point + sensing_radius) / field.config.cell_size).astype(int)
    lower = np.clip(lower, 0, np.array(field.intensity.shape) - 1)
    upper = np.clip(upper, 0, np.array(field.intensity.shape) - 1)
    strengths: list[float] = []
    for ix in range(int(lower[0]), int(upper[0]) + 1):
        for iy in range(int(lower[1]), int(upper[1]) + 1):
            index = (ix, iy)
            strength = float(field.intensity[index])
            if strength <= 0.0:
                continue
            if field._point_to_cell_distance(point, index) > sensing_radius + 1e-12:
                continue
            strengths.append(strength)
    maximum = max(strengths) if strengths else float("nan")
    tie_count = sum(strength == maximum for strength in strengths) if strengths else 0
    return {
        "candidate_cell_count": len(strengths),
        "maximum_intensity": maximum,
        "maximum_intensity_tie_count": tie_count,
    }


def sensing_per_follower_summary(records: pd.DataFrame) -> pd.DataFrame:
    """Aggregate follower sensing hits, misses, ties, and miss streaks by ant."""

    columns = [
        "ant_id",
        "sensing_steps",
        "hit_count",
        "miss_count",
        "miss_rate",
        "max_consecutive_miss_length",
        "mean_candidate_cell_count",
        "tie_step_count",
        "no_signal_continue_count",
        "mean_choice_food_error_deg_on_hits",
    ]
    if records.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for ant_id, group in records.groupby("ant_id", sort=True):
        hits = group["sensing_hit"].astype(bool)
        hit_errors = group.loc[hits, "chosen_direction_food_error_deg"].dropna()
        rows.append(
            {
                "ant_id": int(ant_id),
                "sensing_steps": int(len(group)),
                "hit_count": int(hits.sum()),
                "miss_count": int((~hits).sum()),
                "miss_rate": float((~hits).mean()),
                "max_consecutive_miss_length": int(group["consecutive_miss_length"].max()),
                "mean_candidate_cell_count": float(group["candidate_cell_count"].mean()),
                "tie_step_count": int((group["maximum_intensity_tie_count"] > 1).sum()),
                "no_signal_continue_count": int(group["no_signal_continued_heading"].sum()),
                "mean_choice_food_error_deg_on_hits": (
                    float(hit_errors.mean()) if len(hit_errors) else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def miss_streak_rows(records: pd.DataFrame) -> pd.DataFrame:
    """Return one row per completed or horizon-censored consecutive miss streak."""

    rows: list[dict[str, object]] = []
    if records.empty:
        return pd.DataFrame(columns=["ant_id", "start_time", "end_time", "length", "censored"])
    for ant_id, group in records.sort_values(["ant_id", "time"]).groupby("ant_id", sort=True):
        start: int | None = None
        previous_time: int | None = None
        for record in group.itertuples(index=False):
            current_time = int(record.time)
            miss = not bool(record.sensing_hit)
            contiguous = previous_time is not None and current_time == previous_time + 1
            if miss and (start is None or not contiguous):
                if start is not None and previous_time is not None:
                    rows.append(
                        {"ant_id": int(ant_id), "start_time": start, "end_time": previous_time,
                         "length": previous_time - start + 1, "censored": False}
                    )
                start = current_time
            elif not miss and start is not None and previous_time is not None:
                rows.append(
                    {"ant_id": int(ant_id), "start_time": start, "end_time": previous_time,
                     "length": previous_time - start + 1, "censored": False}
                )
                start = None
            previous_time = current_time
        if start is not None and previous_time is not None:
            rows.append(
                {"ant_id": int(ant_id), "start_time": start, "end_time": previous_time,
                 "length": previous_time - start + 1, "censored": True}
            )
    return pd.DataFrame(rows, columns=["ant_id", "start_time", "end_time", "length", "censored"])


def path_length(points: NDArray[np.float64] | Sequence[Sequence[float]]) -> float:
    """Polyline length."""

    path = np.asarray(points, dtype=float)
    if path.ndim != 2 or path.shape[1] != 2 or len(path) < 1:
        raise ValueError("points must have shape (n, 2) with n >= 1")
    return float(np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1)))


def path_efficiency(direct_distance: float, travelled_distance: float) -> float:
    """Direct endpoint displacement divided by travelled path length."""

    if direct_distance < 0.0 or travelled_distance < 0.0:
        raise ValueError("distances must be non-negative")
    if travelled_distance == 0.0:
        return 1.0 if direct_distance == 0.0 else float("nan")
    return float(direct_distance / travelled_distance)


def metric_validation_rows(axis_angle: float = np.pi / 4) -> list[dict[str, object]]:
    """Validate paper-style phi/psi on aligned, bidirectional, and uniform fields."""

    scenarios = {
        "fully_aligned": np.full(10_000, axis_angle),
        "bidirectionally_aligned": np.tile([axis_angle, axis_angle + np.pi], 5_000),
        "uniform_direction_field": np.linspace(-np.pi, np.pi, 200_000, endpoint=False),
    }
    rows: list[dict[str, object]] = []
    for name, headings in scenarios.items():
        phi, psi = compute_order_parameters(headings)
        rows.append(
            {
                "scenario": name,
                "sample_count": len(headings),
                "orientation_order_phi": phi,
                "nematic_order_psi": psi,
                "mean_axial_error_rad": float(np.mean(axial_angle_error(headings, axis_angle))),
            }
        )
    return rows


class DiagnosticSimulation(ColonySimulation):
    """Frozen Stage 2A simulation with observation-only instrumentation."""

    def __init__(
        self, *args: object, compact_sensing: bool = False, **kwargs: object
    ) -> None:
        self.role_order_records: list[dict[str, object]] = []
        self.axis_alignment_records: list[dict[str, object]] = []
        self.sensing_records: list[dict[str, object]] = []
        self.transport_records: list[dict[str, object]] = []
        self._sense_context: dict[str, object] | None = None
        self._last_sense_time: dict[int, int] = {}
        self._last_sense_was_miss: dict[int, bool] = {}
        self._miss_streak: dict[int, int] = {}
        self._active_transport: dict[int, dict[str, object]] = {}
        self._next_transport_leg_id = 0
        self.compact_sensing = compact_sensing
        super().__init__(*args, **kwargs)
        axis = np.asarray(self.config.food.center) - np.asarray(self.config.nest.center)
        self.axis_angle = float(np.arctan2(axis[1], axis[0]))
        self.nest_food_straight_distance = float(np.linalg.norm(axis))
        self._capture_role_order()

    def _capture_role_order(self) -> None:
        order, alignment = role_order_rows(
            self.ants,
            time=self.time,
            axis_angle=self.axis_angle,
            speed=self.config.movement.speed,
        )
        self.role_order_records.extend(order)
        self.axis_alignment_records.extend(alignment)

    def _follower_direction_decision(self, ant: Ant) -> FollowerDirectionDecision:
        decision = super()._follower_direction_decision(ant)
        if self._sense_context is None:
            return decision
        context_ant = self._sense_context["ant"]
        if not isinstance(context_ant, Ant) or context_ant is not ant:
            raise RuntimeError("invalid sensing diagnostic context")
        position = ant.position
        candidate_info = inspect_sensing_candidates(self.field, position)
        hit = decision.sensing_hit
        last_time = self._last_sense_time.get(ant.ant_id)
        continues = last_time is not None and last_time == self.time - 1
        previous_miss = self._last_sense_was_miss.get(ant.ant_id, False)
        streak = (
            self._miss_streak.get(ant.ant_id, 0) + 1
            if (not hit and continues and previous_miss)
            else (1 if not hit else 0)
        )
        self._last_sense_time[ant.ant_id] = self.time
        self._last_sense_was_miss[ant.ant_id] = not hit
        self._miss_streak[ant.ant_id] = streak
        food_vector = np.asarray(self.config.food.center, dtype=float) - np.asarray(position)
        food_angle = float(np.arctan2(food_vector[1], food_vector[0]))
        chosen_angle = decision.heading if hit else float("nan")
        record: dict[str, object] = {
            "time": self.time,
            "ant_id": ant.ant_id,
            "start_x": float(position[0]),
            "start_y": float(position[1]),
            "heading_before_sensing": float(ant.heading),
            "sensing_hit": hit,
            "sensing_miss": not hit,
            "consecutive_miss_length": streak,
            "candidate_cell_count": int(candidate_info["candidate_cell_count"]),
            "maximum_intensity": candidate_info["maximum_intensity"],
            "maximum_intensity_tie_count": int(
                candidate_info["maximum_intensity_tie_count"]
            ),
            "highest_concentration_tied": int(
                candidate_info["maximum_intensity_tie_count"]
            )
            > 1,
            "no_signal_continued_heading": not hit,
            "selected_cell_x": (
                decision.selected_cell_index[0]
                if decision.selected_cell_index is not None
                else -1
            ),
            "selected_cell_y": (
                decision.selected_cell_index[1]
                if decision.selected_cell_index is not None
                else -1
            ),
            "selected_intensity": (
                decision.selected_intensity
                if decision.selected_intensity is not None
                else float("nan")
            ),
            "chosen_direction_rad": chosen_angle,
            "food_direction_rad": food_angle,
            "chosen_direction_food_error_rad": (
                directed_angle_error(chosen_angle, food_angle) if hit else float("nan")
            ),
            "chosen_direction_food_error_deg": (
                float(np.degrees(directed_angle_error(chosen_angle, food_angle)))
                if hit
                else float("nan")
            ),
        }
        if self.compact_sensing:
            compact_fields = {
                "time",
                "ant_id",
                "heading_before_sensing",
                "sensing_hit",
                "sensing_miss",
                "candidate_cell_count",
                "chosen_direction_rad",
                "chosen_direction_food_error_deg",
            }
            record = {key: value for key, value in record.items() if key in compact_fields}
        self.sensing_records.append(record)
        return decision

    def _move_follower(self, ant: Ant) -> None:
        before = len(self.sensing_records)
        self._sense_context = {"ant": ant}
        try:
            super()._move_follower(ant)
        finally:
            self._sense_context = None
        if len(self.sensing_records) != before + 1:
            raise RuntimeError("each follower movement must produce exactly one sensing record")
        self.sensing_records[-1].update(
            {
                "end_x": float(ant.position[0]),
                "end_y": float(ant.position[1]),
                "heading_after_move": float(ant.heading),
            }
        )

    def _start_transport_leg(self, ant: Ant, source_role: Role, outbound_path: NDArray[np.float64]) -> None:
        self._next_transport_leg_id += 1
        memory_path = ant.return_waypoints.copy()
        departure = ant.position.copy()
        outbound_direct = float(np.linalg.norm(outbound_path[-1] - outbound_path[0]))
        outbound_axis_distances = _axis_distances(
            outbound_path, np.asarray(self.config.nest.center), np.asarray(self.config.food.center)
        )
        start_cell = self.field._cell_index(departure)
        self._active_transport[ant.ant_id] = {
            "leg_id": self._next_transport_leg_id,
            "ant_id": ant.ant_id,
            "source_role": source_role.value,
            "transport_start_time": self.time,
            "departure_x": float(departure[0]),
            "departure_y": float(departure[1]),
            "outbound_sample_count": len(outbound_path),
            "outbound_path_length": path_length(outbound_path),
            "outbound_endpoint_distance": outbound_direct,
            "outbound_path_efficiency": path_efficiency(outbound_direct, path_length(outbound_path)),
            "memory_waypoint_count": len(memory_path),
            "memory_path_length": path_length(memory_path),
            "nest_food_straight_distance": self.nest_food_straight_distance,
            "outbound_max_axis_distance": float(np.max(outbound_axis_distances)),
            "actual_return_distance": 0.0,
            "return_positions": [departure.copy()],
            "return_cells": [start_cell],
            "distance_increasing_steps": 0,
        }

    def _forager_transition(self, ant: Ant) -> None:
        begins_transport = self._at_food(ant)
        outbound = np.asarray(ant.travel_path, dtype=float).copy() if begins_transport else None
        super()._forager_transition(ant)
        if begins_transport and ant.role is Role.TRANSPORTER and outbound is not None:
            self._start_transport_leg(ant, Role.FORAGER, outbound)

    def _follower_transition(self, ant: Ant) -> None:
        begins_transport = self._at_food(ant)
        outbound = np.asarray(ant.travel_path, dtype=float).copy() if begins_transport else None
        super()._follower_transition(ant)
        if begins_transport and ant.role is Role.TRANSPORTER and outbound is not None:
            self._start_transport_leg(ant, Role.FOLLOWER, outbound)

    def _move_transporter(self, ant: Ant) -> None:
        distance_before = float(np.linalg.norm(ant.position - np.asarray(self.config.nest.center)))
        super()._move_transporter(ant)
        leg = self._active_transport.get(ant.ant_id)
        if leg is None:
            raise RuntimeError("transporter movement has no active diagnostic leg")
        leg["actual_return_distance"] = float(leg["actual_return_distance"]) + ant.last_path_distance
        positions = leg["return_positions"]
        cells = leg["return_cells"]
        if not isinstance(positions, list) or not isinstance(cells, list):
            raise RuntimeError("invalid transport diagnostic state")
        positions.append(ant.position.copy())
        cells.append(self.field._cell_index(ant.position))
        distance_after = float(np.linalg.norm(ant.position - np.asarray(self.config.nest.center)))
        if distance_after > distance_before + 1e-9:
            leg["distance_increasing_steps"] = int(leg["distance_increasing_steps"]) + 1

    def _transport_row(self, ant: Ant, *, completed: bool) -> dict[str, object]:
        leg = self._active_transport[ant.ant_id]
        positions = np.asarray(leg["return_positions"], dtype=float)
        cells = leg["return_cells"]
        if not isinstance(cells, list):
            raise RuntimeError("invalid return cell history")
        actual = float(leg["actual_return_distance"])
        endpoint = float(np.linalg.norm(positions[-1] - positions[0]))
        return_axis = _axis_distances(
            positions, np.asarray(self.config.nest.center), np.asarray(self.config.food.center)
        )
        repeated_fraction = 1.0 - len(set(cells)) / len(cells)
        steps = len(positions) - 1
        row = {key: value for key, value in leg.items() if key not in {"return_positions", "return_cells"}}
        row.update(
            {
                "status": "completed_delivery" if completed else "incomplete_at_horizon",
                "delivery_time": self.time if completed else float("nan"),
                "transport_time_steps": self.time - int(leg["transport_start_time"]),
                "actual_return_distance": actual,
                "actual_return_endpoint_distance": endpoint,
                "actual_return_path_efficiency": path_efficiency(endpoint, actual),
                "site_axis_distance_over_actual_return": (
                    self.nest_food_straight_distance / actual if actual > 0.0 else float("nan")
                ),
                "memory_to_outbound_length_ratio": (
                    float(leg["memory_path_length"]) / float(leg["outbound_path_length"])
                    if float(leg["outbound_path_length"]) > 0.0 else float("nan")
                ),
                "memory_shortening_fraction": (
                    1.0 - float(leg["memory_path_length"]) / float(leg["outbound_path_length"])
                    if float(leg["outbound_path_length"]) > 0.0 else float("nan")
                ),
                "actual_to_memory_length_ratio": (
                    actual / float(leg["memory_path_length"])
                    if float(leg["memory_path_length"]) > 0.0 else float("nan")
                ),
                "return_max_axis_distance": float(np.max(return_axis)),
                "return_p90_axis_distance": float(np.quantile(return_axis, 0.90)),
                "distance_increasing_step_fraction": (
                    int(leg["distance_increasing_steps"]) / steps if steps else 0.0
                ),
                "repeated_return_cell_fraction": repeated_fraction,
                "anomalously_long_vs_site_axis": (
                    actual > 1.5 * self.nest_food_straight_distance if completed else False
                ),
                "possible_looping": repeated_fraction > 0.25,
                "far_from_main_axis": float(np.max(return_axis)) > 0.1 * self.nest_food_straight_distance,
            }
        )
        return row

    def _transporter_transition(self, ant: Ant) -> None:
        completes = self._at_nest(ant)
        super()._transporter_transition(ant)
        if completes:
            self.transport_records.append(self._transport_row(ant, completed=True))
            del self._active_transport[ant.ant_id]

    def step(self) -> None:
        super().step()
        self._capture_role_order()

    def run(self) -> SimulationResult:
        result = super().run()
        for ant_id in sorted(self._active_transport):
            ant = self.ants[ant_id]
            self.transport_records.append(self._transport_row(ant, completed=False))
        return result


def read_sha256_baseline(path: Path) -> dict[str, str]:
    """Read the two-column pre-diagnostic SHA-256 manifest."""

    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        entries[relative.strip()] = digest
    return entries
