"""Stage 5 coarse-grained return: equivalence with B0 at spacing 1 and straight homing."""

from __future__ import annotations

import math

import numpy as np
import pytest

from scalar_baseline.config import DecayConfig, SimulationConfig
from scalar_baseline.simulation import Simulation
from stage5_navigation.model import CoarseReturnSimulation


def small_config(seed: int = 7, steps: int = 3000) -> SimulationConfig:
    return SimulationConfig(n_ants=20, steps=steps, seed=seed, arena_size=60,
                            nest=(30, 30), food_a=(38, 30), food_b=(30, 38),
                            decay=DecayConfig(half_life_steps=200))


def test_spacing_one_reproduces_exact_retrace():
    config = small_config()
    base, coarse = Simulation(config), CoarseReturnSimulation(config, waypoint_spacing=1)
    base.run()
    coarse.run()
    assert base.ledger.events == coarse.ledger.events
    assert np.array_equal(base.field.concentration, coarse.field.concentration)
    assert [a.position for a in base.ants] == [a.position for a in coarse.ants]
    assert base.ledger.deliveries["A"] > 0


def test_straight_return_moves_on_a_line_to_path_start():
    config = small_config(seed=11)
    sim = CoarseReturnSimulation(config, waypoint_spacing=None)
    tracked = {}
    while sim.time < config.steps:
        before = {a.ant_id: a.role for a in sim.ants}
        sim.step()
        for ant in sim.ants:
            if before[ant.ant_id] != "transporter" and ant.role == "transporter" and ant.ant_id not in tracked:
                tracked[ant.ant_id] = [ant.position, sim.return_routes[ant.ant_id][-1]]
            elif ant.ant_id in tracked and len(tracked[ant.ant_id]) < 40 and ant.role == "transporter":
                tracked[ant.ant_id].append(ant.position)
        if len(tracked) >= 2:
            break
    assert tracked, "fixture should produce at least one pickup"
    for points in tracked.values():
        start, goal, *moves = points
        for p in moves:
            # Every return position lies on the segment from the food contact to the path start.
            cross = (goal[0] - start[0]) * (p[1] - start[1]) - (goal[1] - start[1]) * (p[0] - start[0])
            assert abs(cross) < 1e-6 * max(1.0, math.dist(start, goal))
        for a, b in zip([start, *moves], moves):
            assert math.dist(a, b) <= config.step_size + 1e-9


def test_coarse_route_keeps_start_and_every_kth_vertex():
    sim = CoarseReturnSimulation(small_config(), waypoint_spacing=3)
    path = [(float(i), 0.0) for i in range(10)]
    assert sim.route_from_path(path) == [(6.0, 0.0), (3.0, 0.0), (0.0, 0.0)]
    straight = CoarseReturnSimulation(small_config(), waypoint_spacing=None)
    assert straight.route_from_path(path) == [(0.0, 0.0)]


def test_invalid_spacing_rejected():
    with pytest.raises(ValueError):
        CoarseReturnSimulation(small_config(), waypoint_spacing=0)
