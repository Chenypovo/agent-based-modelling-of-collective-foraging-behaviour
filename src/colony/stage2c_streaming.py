"""Observation-only, bounded sensing diagnostics for the frozen colony model.

Every behavioural method delegates to ColonySimulation exactly once. No field
sensing or random-number request is added. Full follower-step tables are never
retained; consecutive-hit history has at most one entry per ant.
"""

from __future__ import annotations

import numpy as np

from .agents import Ant, Role
from .diagnostics import axial_angle_error, channel_width_90, path_efficiency
from .metrics import compute_order_parameters
from .simulation import ColonySimulation, FollowerDirectionDecision
from .transitions import TransitionRecord


def measurement(value, *, count: int, reason: str = "") -> dict:
    if value is not None and not np.isfinite(value):
        raise ValueError("a defined measurement must be finite")
    return {"value": value, "availability": "available" if value is not None else "unavailable",
            "reason": reason if value is None else "", "count": int(count)}


class StreamingSimulation(ColonySimulation):
    """Original trajectories plus sufficient statistics, with no model edits."""

    def __init__(self, config, *, late_window=(9000, 10000), **kwargs):
        if not (0 <= late_window[0] <= late_window[1] <= config.steps):
            raise ValueError("late window must fit inside the configured horizon")
        self.late_window = tuple(late_window)
        axis = np.asarray(config.food.center) - np.asarray(config.nest.center)
        self.axis_angle = float(np.arctan2(axis[1], axis[0]))
        self.sensing_steps = self.hit_count = self.miss_count = 0
        self.hit_axis_sum = self.continuity_sum = 0.0
        self.continuity_count = 0
        self.previous_sensing = {}
        self._observing_ant = None
        self._observed_decision = None
        self.active_transport = {}
        self.completed_transport = []
        self.first_recruitment_time = None
        self.role_rows = []
        self.late_sums = {"phi": 0.0, "psi": 0.0, "follower_phi": 0.0,
                          "follower_psi": 0.0}
        self.late_count = self.follower_late_count = self.follower_sufficient_count = 0
        self.runtime_counters = {"elapsed_seconds": 0.0, "checkpoint_seconds": 0.0,
                                 "checkpoint_count": 0, "peak_storage_bytes": 0}
        # All stochastic work is completed by the unchanged initialisation.
        # There is no live simulation generator after turn schedules are built.
        self.rng_state = {"policy": "frozen_pre_generated_turn_schedules",
                          "seed": int(config.seed), "live_generator_state": None}
        super().__init__(config, **kwargs)
        for ant in self.ants:
            if ant.role is Role.TRANSPORTER:
                self._begin_transport(ant)
        self._capture_observation()

    def _follower_direction_decision(self, ant: Ant) -> FollowerDirectionDecision:
        decision = super()._follower_direction_decision(ant)
        if self._observing_ant == ant.ant_id:
            if self._observed_decision is not None:
                raise RuntimeError("more than one follower decision per movement")
            self._observed_decision = decision
        return decision

    def _move_follower(self, ant: Ant) -> None:
        self._observing_ant = ant.ant_id
        self._observed_decision = None
        try:
            super()._move_follower(ant)
            decision = self._observed_decision
        finally:
            self._observing_ant = None
            self._observed_decision = None
        if decision is None:
            raise RuntimeError("missing observed follower decision")
        self.sensing_steps += 1
        previous = self.previous_sensing.get(ant.ant_id)
        if decision.sensing_hit:
            self.hit_count += 1
            self.hit_axis_sum += float(np.degrees(axial_angle_error([ant.heading], self.axis_angle)[0]))
            if previous is not None and previous[0] == self.time - 1 and previous[1]:
                self.continuity_sum += float(np.degrees(
                    axial_angle_error([decision.heading], previous[2])[0]))
                self.continuity_count += 1
        else:
            self.miss_count += 1
        self.previous_sensing[ant.ant_id] = (self.time, decision.sensing_hit, decision.heading)

    def _begin_transport(self, ant: Ant) -> None:
        self.active_transport[ant.ant_id] = {
            "ant_id": ant.ant_id, "start_time": self.time,
            "departure": ant.position.copy(), "distance": 0.0,
        }

    def _record_transition(self, record: TransitionRecord) -> None:
        super()._record_transition(record)
        ant = next(ant for ant in self.ants if ant.ant_id == record.ant_id)
        if record.reason == "pheromone_sensed" and self.first_recruitment_time is None:
            self.first_recruitment_time = self.time
        if record.to_role == Role.TRANSPORTER.value:
            self._begin_transport(ant)
        elif record.reason == "food_deposited_at_nest":
            leg = self.active_transport.pop(ant.ant_id)
            direct = float(np.linalg.norm(ant.position - leg["departure"]))
            efficiency = path_efficiency(direct, leg["distance"])
            if not np.isfinite(efficiency):
                raise RuntimeError("non-finite completed transporter efficiency")
            self.completed_transport.append({
                "ant_id": ant.ant_id, "start_time": leg["start_time"],
                "delivery_time": self.time, "endpoint_distance": direct,
                "actual_return_distance": leg["distance"], "efficiency": efficiency,
            })

    def _move_transporter(self, ant: Ant) -> None:
        super()._move_transporter(ant)
        self.active_transport[ant.ant_id]["distance"] += ant.last_path_distance

    def _capture_observation(self) -> None:
        row = {"time": self.time}
        for role in Role:
            headings = np.asarray([a.heading for a in self.ants if a.role is role])
            phi, psi = compute_order_parameters(headings) if len(headings) else (None, None)
            row.update({role.value + "_count": len(headings), role.value + "_phi": phi,
                        role.value + "_psi": psi, role.value + "_sufficient": len(headings) >= 5})
        self.role_rows.append(row)
        if self.late_window[0] <= self.time <= self.late_window[1]:
            global_row = self._metric_rows[-1]
            self.late_count += 1
            self.late_sums["phi"] += global_row["orientation_order_phi"]
            self.late_sums["psi"] += global_row["nematic_order_psi"]
            if row["follower_count"]:
                self.follower_late_count += 1
                self.late_sums["follower_phi"] += row["follower_phi"]
                self.late_sums["follower_psi"] += row["follower_psi"]
            self.follower_sufficient_count += int(row["follower_sufficient"])

    def step(self) -> None:
        super().step()
        # The base class already checks population, positions, headings and intensity.
        # Check the remaining field accumulator without changing it.
        if not np.isfinite(self.field.direction_sum).all():
            raise RuntimeError("non-finite pheromone direction accumulator")
        self._capture_observation()

    def endpoint_metrics(self) -> dict:
        if self.time != self.config.steps:
            raise ValueError("endpoint metrics require the complete horizon")
        expected = self.late_window[1] - self.late_window[0] + 1
        if self.late_count != expected:
            raise RuntimeError("missing late-window samples")
        out = {}
        for key in ("phi", "psi"):
            out["late_window_mean_" + key] = measurement(
                self.late_sums[key] / expected, count=expected)
            eligible = self.follower_sufficient_count == expected
            out["follower_late_window_mean_" + key] = measurement(
                self.late_sums["follower_" + key] / expected if eligible else None,
                count=self.follower_sufficient_count, reason="insufficient_follower_samples")
        out["absolute_late_phi_distance"] = measurement(
            abs(out["late_window_mean_phi"]["value"] - np.pi / 4), count=expected)
        for name, total, count, reason in (
            ("follower_hit_step_mean_axis_error_deg", self.hit_axis_sum, self.hit_count, "no_sensing_hits"),
            ("follower_local_continuity_mean_axis_change_deg", self.continuity_sum,
             self.continuity_count, "no_consecutive_hits"),
            ("follower_sensing_miss_rate", self.miss_count, self.sensing_steps, "no_sensing_steps"),
        ):
            out[name] = measurement(float(total / count) if count else None, count=count, reason=reason)
        efficiencies = [r["efficiency"] for r in self.completed_transport]
        for label, reducer in (("mean", np.mean), ("median", np.median)):
            out[f"completed_transporter_{label}_path_efficiency"] = measurement(
                float(reducer(efficiencies)) if efficiencies else None,
                count=len(efficiencies), reason="no_completed_delivery_legs")
        indices = np.argwhere(self.field.intensity > 0.0)
        out["active_pheromone_area_fraction"] = measurement(
            len(indices) / self.field.intensity.size, count=self.field.intensity.size)
        width = None
        if len(indices):
            centres = (indices.astype(float) + 0.5) * self.config.pheromone.cell_size
            width = channel_width_90(centres, self.field.intensity[indices[:, 0], indices[:, 1]],
                                     np.asarray(self.config.nest.center), np.asarray(self.config.food.center))
        out["main_channel_width_90"] = measurement(width, count=len(indices), reason="no_active_pheromone")
        out["cumulative_deliveries"] = measurement(self.cumulative_deliveries, count=1)
        for role, count in self._role_counts().items():
            out["final_" + role.value + "_count"] = measurement(count, count=self.config.n_ants)
        for name, value in (("first_food_discovery_time", self.first_food_discovery_time),
                            ("first_successful_delivery_time", self.first_delivery_time),
                            ("first_pheromone_recruitment_time", self.first_recruitment_time)):
            item = measurement(value, count=int(value is not None), reason="right_censored_at_horizon")
            item.update(observed=value is not None, censoring_horizon=self.config.steps)
            out[name] = item
        return out

    def diagnostic_evidence(self) -> dict:
        return {"sensing_steps": self.sensing_steps, "hit_count": self.hit_count,
                "miss_count": self.miss_count, "hit_axis_sum": self.hit_axis_sum,
                "continuity_sum": self.continuity_sum, "continuity_count": self.continuity_count,
                "late_sums": self.late_sums, "late_count": self.late_count,
                "follower_late_count": self.follower_late_count,
                "follower_sufficient_count": self.follower_sufficient_count,
                "completed_leg_count": len(self.completed_transport),
                "incomplete_leg_count": len(self.active_transport),
                "transition_counts": self.transition_counts, "rng_state": self.rng_state}
