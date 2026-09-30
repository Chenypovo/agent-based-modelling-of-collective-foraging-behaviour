"""Stage 5 path integration (egocentric) and landmark correction (geocentric)."""

from __future__ import annotations

import math

import pytest

from scalar_baseline.config import DecayConfig, SimulationConfig
from stage5_navigation.path_integration import LandmarkMemory, NavigationConfig, PathIntegrationSimulation


def config(seed: int = 7, steps: int = 3000) -> SimulationConfig:
    return SimulationConfig(n_ants=20, steps=steps, seed=seed, arena_size=60,
                            nest=(30, 30), food_a=(38, 30), food_b=(30, 38),
                            decay=DecayConfig(half_life_steps=200))


def run_tracking(sim):
    """Record every transporter trip: positions from pickup to delivery."""
    trips, open_trips = [], {}
    while sim.time < sim.config.steps:
        before = {a.ant_id: a.role for a in sim.ants}
        sim.step()
        for a in sim.ants:
            if before[a.ant_id] != "transporter" and a.role == "transporter":
                open_trips[a.ant_id] = [a.position]
            elif before[a.ant_id] == "transporter":
                open_trips[a.ant_id].append(a.position)
                if a.role != "transporter":
                    trips.append(open_trips.pop(a.ant_id))
    return trips


def test_noise_free_integration_homes_in_a_straight_line_without_search():
    sim = PathIntegrationSimulation(config(), NavigationConfig(compass_noise=0.0))
    trips = run_tracking(sim)
    assert trips and sim.search_starts == 0
    nest = sim.config.nest
    for trip in trips:
        start = trip[0]
        steps = len(trip) - 1
        assert steps <= math.ceil(math.dist(start, nest) / sim.config.step_size) + 1
    for a in sim.ants:
        err = sim.estimate_error(a.ant_id)
        assert err < 1e-6


def test_noisy_integration_accumulates_error_but_still_delivers():
    sim = PathIntegrationSimulation(config(seed=3, steps=4000), NavigationConfig(compass_noise=0.6))
    trips = run_tracking(sim)
    assert trips, "noisy ants must still find the nest by local search"
    assert max(sim.estimate_error(a.ant_id) for a in sim.ants) > 0.1


def test_reproducible_for_same_seed():
    a = PathIntegrationSimulation(config(seed=5), NavigationConfig(compass_noise=0.3))
    b = PathIntegrationSimulation(config(seed=5), NavigationConfig(compass_noise=0.3))
    a.run()
    b.run()
    assert a.ledger.events == b.ledger.events


def test_landmark_memory_keeps_the_least_uncertain_estimate_and_resets():
    memory = LandmarkMemory()
    # First sighting: store estimated landmark position with uncertainty 50.
    assert memory.observe(0, landmark=(10.0, 0.0), estimate=(12.0, 1.0), true_position=(11.0, 0.0),
                          uncertainty=50.0) is None
    # Later, more uncertain ant sees it again: reset to the stored estimate.
    reset = memory.observe(0, landmark=(10.0, 0.0), estimate=(30.0, 30.0), true_position=(9.0, 0.0),
                           uncertainty=80.0)
    assert reset == ((10.0, 1.0), 50.0)
    # A less uncertain sighting overwrites the memory and does not reset.
    assert memory.observe(0, landmark=(10.0, 0.0), estimate=(10.5, 0.0), true_position=(10.5, 0.0),
                          uncertainty=5.0) is None
    assert memory.observe(0, landmark=(10.0, 0.0), estimate=(0.0, 0.0), true_position=(10.0, 0.0),
                          uncertainty=9.0) == ((10.0, 0.0), 5.0)


def test_landmarks_reduce_homing_error():
    noisy = NavigationConfig(compass_noise=0.8)
    plain = PathIntegrationSimulation(config(seed=9, steps=4000), noisy)
    marks = [(x, y) for x in range(5, 60, 6) for y in range(5, 60, 6)]
    guided = PathIntegrationSimulation(config(seed=9, steps=4000),
                                       NavigationConfig(compass_noise=0.8, landmarks=tuple(marks), view_radius=4.0))
    plain.run()
    guided.run()
    assert guided.landmark_resets > 0
    assert sum(guided.arrival_errors) / len(guided.arrival_errors) < sum(plain.arrival_errors) / len(plain.arrival_errors)


def test_at_most_one_local_search_per_trip_with_dense_landmarks():
    import numpy as np
    full = SimulationConfig(n_ants=100, steps=4000, seed=2026093001, arena_size=300, nest=(150, 150),
                            food_a=(240, 150), food_b=(150, 240), decay=DecayConfig(half_life_steps=1000))
    # Same terrain as the exploratory run where the restart loop was observed (ant 64 near t=2500).
    rng = np.random.default_rng(np.random.SeedSequence([2026093001, 99]))
    marks = tuple(map(tuple, rng.uniform(0, 300, size=(300, 2)).round(6).tolist()))
    sim = PathIntegrationSimulation(full, NavigationConfig(compass_noise=0.6, landmarks=marks))
    sim.run()
    pickups = sum(e["event"] == "pickup" for e in sim.ledger.events)
    assert pickups > 0 and sim.search_starts <= pickups


def test_invalid_navigation_config():
    with pytest.raises(ValueError):
        NavigationConfig(compass_noise=-1)
    with pytest.raises(ValueError):
        NavigationConfig(nest_cue_radius=0)
