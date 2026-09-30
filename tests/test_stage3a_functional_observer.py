from dataclasses import asdict

import numpy as np
import pytest

from scalar_baseline.config import SimulationConfig, B0Config
from scalar_baseline.functional_validation import ObservedSimulation, connected, route_detectability, research_config, SEEDS
from scalar_baseline.simulation import Simulation


def test_observer_does_not_change_dynamics():
    config = SimulationConfig(n_ants=4, steps=50)
    plain, observed = Simulation(config), ObservedSimulation(config)
    for sim in (plain, observed):
        sim.field.deposit((20, 20), 2)
    for _ in range(config.steps):
        plain.step()
        observed.step()
        assert [asdict(a) for a in plain.ants] == [asdict(a) for a in observed.ants]
        assert asdict(plain.ledger) == asdict(observed.ledger)
        np.testing.assert_array_equal(plain.field.concentration, observed.field.concentration)


def test_connectivity_and_gap_metrics():
    mask = np.eye(4, dtype=bool)
    assert connected(mask, (0, 0), (3, 3))
    mask[2, 2] = False
    assert not connected(mask, (0, 0), (3, 3))
    result = route_detectability([1, 0, 0, 1, 0], 0.5)
    assert result['detectable_fraction'] == 0.4
    assert result['longest_undetectable_run_points'] == 2


def test_frozen_research_config():
    config = research_config(SEEDS[0])
    assert (config.n_ants, config.steps, config.arena_size) == (100, 12000, 300)
    assert config.decay.half_life_steps == pytest.approx(1000)
    assert config.relocation_step is None
    assert config.food_a == (240, 150)
    assert config.diffusion == 0


def test_observer_records_actual_follower_contact_and_delivery():
    config = SimulationConfig(n_ants=1, steps=8, arena_size=10, nest=(2, 2),
                              food_a=(4.4, 2), food_b=(2, 4.4), contact_radius=0.15,
                              theta_max=0, navigation=B0Config(noise_amplitude=0))
    plain, observed = Simulation(config), ObservedSimulation(config)
    for sim in (plain, observed):
        sim.ants[0].heading = 0
        for x in range(2, 6):
            for y in (1, 2):
                sim.field.deposit((x + 0.5, y + 0.5), 2)
    for _ in range(8):
        plain.step(); observed.step()
        assert asdict(plain.ants[0]) == asdict(observed.ants[0])
        np.testing.assert_array_equal(plain.field.concentration, observed.field.concentration)
    pickup = next(e for e in observed.observations if e['event'] == 'pickup')
    assert pickup['time'] == 4 and pickup['role_before_contact'] == 'follower'
    assert pickup['follower_episode']['duration_steps'] == 4
    assert observed.ledger.deliveries == {'A': 1, 'B': 0}
    assert observed.first_delivery_pending
    assert 0 in observed.ever_deposited
