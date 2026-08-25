"""Deterministic orchestration of the provisional Stage 2A colony model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .agents import Ant, Role, advance_transporter_route, prepare_transporter_route
from .config import ColonyConfig
from .environment import SquareEnvironment, distance_to_site
from .metrics import compute_order_parameters, fold_headings
from .movement import build_turn_schedules, initial_headings
from .pheromone import PheromoneField
from .transitions import TransitionRecord, transition_role

TRANSITION_KEYS = (
    "forager_to_transporter",
    "forager_to_follower",
    "transporter_to_follower",
    "follower_to_transporter",
)


@dataclass(frozen=True)
class SimulationResult:
    metrics: pd.DataFrame
    agent_states: pd.DataFrame
    final_agents: pd.DataFrame
    events: pd.DataFrame
    snapshots: dict[int, pd.DataFrame]
    pheromone_snapshots: dict[
        int, tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]
    ]


class ColonySimulation:
    """One isolated, repeatable Stage 2A simulation instance."""

    def __init__(
        self,
        config: ColonyConfig,
        *,
        initial_agents: Sequence[Ant] | None = None,
        turn_schedules: NDArray[np.float64] | None = None,
    ) -> None:
        self.config = config
        self.environment = SquareEnvironment(config.arena_size)
        self.field = PheromoneField(
            config.arena_size,
            config.pheromone,
            food_position=np.asarray(config.food.center, dtype=float),
        )
        if initial_agents is None:
            headings = initial_headings(config)
            nest = np.asarray(config.nest.center, dtype=float)
            self.ants = [
                Ant(
                    ant_id=ant_id,
                    position=nest.copy(),
                    heading=float(headings[ant_id]),
                    role=Role.FORAGER,
                    travel_path=[nest.copy()],
                )
                for ant_id in range(config.n_ants)
            ]
        else:
            if len(initial_agents) != config.n_ants:
                raise ValueError("initial_agents length must equal config.n_ants")
            self.ants = [ant.clone() for ant in initial_agents]
        if sorted(ant.ant_id for ant in self.ants) != list(range(config.n_ants)):
            raise ValueError("ant ids must be exactly 0 through n_ants - 1")

        if turn_schedules is None:
            self.turn_schedules = build_turn_schedules(config)
        else:
            schedules = np.asarray(turn_schedules, dtype=float)
            if schedules.shape != (config.n_ants, config.steps):
                raise ValueError("turn_schedules must have shape (n_ants, steps)")
            if not np.isfinite(schedules).all():
                raise ValueError("turn_schedules must be finite")
            self.turn_schedules = schedules.copy()

        for ant in self.ants:
            if ant.role is Role.TRANSPORTER and len(ant.return_waypoints) == 0:
                prepare_transporter_route(ant, stride=config.memory_stride)

        self.time = 0
        self.cumulative_deliveries = 0
        self.first_food_discovery_time: int | None = None
        self.first_delivery_time: int | None = None
        self.transition_counts = {key: 0 for key in TRANSITION_KEYS}
        self._metric_rows: list[dict[str, int | float | bool]] = []
        self._agent_state_rows: list[dict[str, int | float | str]] = []
        self._event_records: list[TransitionRecord] = []
        self._snapshots: dict[int, pd.DataFrame] = {}
        self._pheromone_snapshots: dict[
            int, tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]
        ] = {}
        self._record_state()
        self._assert_invariants()

    def _move_forager(self, ant: Ant) -> None:
        if ant.movement_cursor >= self.config.steps:
            raise RuntimeError("forager turn schedule exhausted")
        turn = self.turn_schedules[ant.ant_id, ant.movement_cursor]
        ant.movement_cursor += 1
        ant.heading = float(np.arctan2(np.sin(ant.heading + turn), np.cos(ant.heading + turn)))
        start = ant.position.copy()
        ant.position, ant.heading = self.environment.reflect_move(
            ant.position,
            heading=ant.heading,
            distance=self.config.movement.step_size,
        )
        ant.travel_path.append(ant.position.copy())
        ant.last_path_distance = self.config.movement.step_size
        ant.last_displacement = float(np.linalg.norm(ant.position - start))

    def _move_follower(self, ant: Ant) -> None:
        signal = self.field.sense(ant.position)
        if signal is not None:
            ant.heading = float(np.arctan2(signal.direction[1], signal.direction[0]))
        start = ant.position.copy()
        ant.position, ant.heading = self.environment.reflect_move(
            ant.position,
            heading=ant.heading,
            distance=self.config.movement.step_size,
        )
        ant.travel_path.append(ant.position.copy())
        ant.last_path_distance = self.config.movement.step_size
        ant.last_displacement = float(np.linalg.norm(ant.position - start))

    def _move_transporter(self, ant: Ant) -> None:
        start = ant.position.copy()
        _, displacement = advance_transporter_route(ant, self.config.movement.step_size)
        if not self.environment.contains(ant.position):
            raise RuntimeError("transporter waypoint left the arena")
        direction_to_food = -displacement
        if np.linalg.norm(direction_to_food) <= 1e-15:
            direction_to_food = np.asarray(self.config.food.center, dtype=float) - ant.position
        self.field.deposit(ant.position, direction_to_food)
        ant.last_displacement = float(np.linalg.norm(ant.position - start))

    def _record_transition(self, record: TransitionRecord) -> None:
        key = f"{record.from_role}_to_{record.to_role}"
        if key not in self.transition_counts:
            raise RuntimeError(f"unexpected transition key {key}")
        self.transition_counts[key] += 1
        self._event_records.append(record)

    def _at_food(self, ant: Ant) -> bool:
        return (
            distance_to_site(ant.position, self.config.food.center)
            <= self.config.food_detection_distance + 1e-12
        )

    def _at_nest(self, ant: Ant) -> bool:
        return (
            distance_to_site(ant.position, self.config.nest.center)
            <= self.config.nest.radius + 1e-12
        )

    def _forager_transition(self, ant: Ant) -> None:
        if self._at_food(ant):
            record = transition_role(
                ant,
                Role.TRANSPORTER,
                reason="food_detected",
                time=self.time,
            )
            prepare_transporter_route(ant, stride=self.config.memory_stride)
            if self.first_food_discovery_time is None:
                self.first_food_discovery_time = self.time
            self._record_transition(record)
            return
        signal = self.field.sense(ant.position)
        if signal is not None:
            ant.heading = float(np.arctan2(signal.direction[1], signal.direction[0]))
            record = transition_role(
                ant,
                Role.FOLLOWER,
                reason="pheromone_sensed",
                time=self.time,
            )
            self._record_transition(record)

    def _follower_transition(self, ant: Ant) -> None:
        if not self._at_food(ant):
            return
        record = transition_role(
            ant,
            Role.TRANSPORTER,
            reason="food_reached_from_trail",
            time=self.time,
        )
        prepare_transporter_route(ant, stride=self.config.memory_stride)
        self._record_transition(record)

    def _transporter_transition(self, ant: Ant) -> None:
        if not self._at_nest(ant):
            return
        self.cumulative_deliveries += 1
        if self.first_delivery_time is None:
            self.first_delivery_time = self.time
        record = transition_role(
            ant,
            Role.FOLLOWER,
            reason="food_deposited_at_nest",
            time=self.time,
        )
        ant.travel_path = [ant.position.copy()]
        ant.return_waypoints = np.empty((0, 2), dtype=float)
        ant.return_waypoint_index = 0
        signal = self.field.sense(ant.position)
        if signal is not None:
            ant.heading = float(np.arctan2(signal.direction[1], signal.direction[0]))
        self._record_transition(record)

    def _role_counts(self) -> dict[Role, int]:
        return {role: sum(ant.role is role for ant in self.ants) for role in Role}

    def _metrics_row(self) -> dict[str, int | float | bool]:
        counts = self._role_counts()
        headings = np.asarray([ant.heading for ant in self.ants], dtype=float)
        phi, psi = compute_order_parameters(headings)
        row: dict[str, int | float | bool] = {
            "time": self.time,
            "foragers": counts[Role.FORAGER],
            "transporters": counts[Role.TRANSPORTER],
            "followers": counts[Role.FOLLOWER],
            "population_total": sum(counts.values()),
            "population_conserved": sum(counts.values()) == self.config.n_ants,
            "cumulative_deliveries": self.cumulative_deliveries,
            "orientation_order_phi": phi,
            "nematic_order_psi": psi,
            "pheromone_active_cells": self.field.active_cell_count,
            "pheromone_total_intensity": self.field.total_intensity,
        }
        row.update(self.transition_counts)
        return row

    def _agent_rows(self) -> list[dict[str, int | float | str]]:
        headings = np.asarray([ant.heading for ant in self.ants], dtype=float)
        folded = fold_headings(headings)
        return [
            {
                "time": self.time,
                "ant_id": ant.ant_id,
                "x": float(ant.position[0]),
                "y": float(ant.position[1]),
                "heading": float(ant.heading),
                "orientation_angle": float(folded[index]),
                "role": ant.role.value,
                "movement_cursor": ant.movement_cursor,
                "last_path_distance": ant.last_path_distance,
                "last_displacement": ant.last_displacement,
            }
            for index, ant in enumerate(self.ants)
        ]

    def _record_state(self) -> None:
        self._metric_rows.append(self._metrics_row())
        should_record_agents = (
            self.time == 0
            or self.time == self.config.steps
            or self.time % self.config.agent_state_interval == 0
            or self.time in self.config.snapshot_steps
        )
        rows = self._agent_rows() if should_record_agents else []
        if rows:
            self._agent_state_rows.extend(rows)
        if self.time in self.config.snapshot_steps:
            self._snapshots[self.time] = pd.DataFrame(rows).copy(deep=True)
            centres, strengths, directions = self.field.active_cells()
            self._pheromone_snapshots[self.time] = (
                centres.copy(),
                strengths.copy(),
                directions.copy(),
            )

    def _assert_invariants(self) -> None:
        if len(self.ants) != self.config.n_ants:
            raise RuntimeError("ant population changed")
        if sum(self._role_counts().values()) != self.config.n_ants:
            raise RuntimeError("role population is not conserved")
        for ant in self.ants:
            if not self.environment.contains(ant.position):
                raise RuntimeError(f"ant {ant.ant_id} left the arena")
            if not np.isfinite(ant.heading):
                raise RuntimeError(f"ant {ant.ant_id} has a non-finite heading")
            if not np.isfinite(ant.last_path_distance) or ant.last_path_distance < 0:
                raise RuntimeError(f"ant {ant.ant_id} has an invalid path distance")
            if ant.last_path_distance > self.config.movement.step_size + 1e-9:
                raise RuntimeError(f"ant {ant.ant_id} exceeded the configured step length")
        if not np.isfinite(self.field.intensity).all() or np.any(self.field.intensity < 0.0):
            raise RuntimeError("pheromone field contains invalid values")

    def step(self) -> None:
        if self.time >= self.config.steps:
            raise RuntimeError("simulation has already reached its configured horizon")
        roles_at_start = [ant.role for ant in self.ants]
        self.time += 1

        for ant, role in zip(self.ants, roles_at_start):
            if role is Role.FORAGER:
                self._move_forager(ant)
        for ant, role in zip(self.ants, roles_at_start):
            if role is Role.FOLLOWER:
                self._move_follower(ant)
        for ant, role in zip(self.ants, roles_at_start):
            if role is Role.TRANSPORTER:
                self._move_transporter(ant)

        for ant, role in zip(self.ants, roles_at_start):
            if role is Role.FORAGER:
                self._forager_transition(ant)
            elif role is Role.FOLLOWER:
                self._follower_transition(ant)
            else:
                self._transporter_transition(ant)

        self.field.advance_time()
        self._assert_invariants()
        self._record_state()

    def _events_dataframe(self) -> pd.DataFrame:
        columns = ["time", "ant_id", "from_role", "to_role", "reason", "x", "y"]
        return pd.DataFrame([record.to_dict() for record in self._event_records], columns=columns)

    def run(self) -> SimulationResult:
        while self.time < self.config.steps:
            self.step()
        agent_states = pd.DataFrame(self._agent_state_rows)
        final_agents = agent_states.loc[agent_states["time"] == self.config.steps].reset_index(
            drop=True
        )
        return SimulationResult(
            metrics=pd.DataFrame(self._metric_rows),
            agent_states=agent_states,
            final_agents=final_agents,
            events=self._events_dataframe(),
            snapshots={time: frame.copy(deep=True) for time, frame in self._snapshots.items()},
            pheromone_snapshots={
                time: tuple(array.copy() for array in arrays)
                for time, arrays in self._pheromone_snapshots.items()
            },
        )
