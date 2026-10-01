"""H1b movement heterogeneity: per-ant FCRW turning amplitude."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ant_walks.models import generate_trajectory
from scalar_baseline.config import DecayConfig, SimulationConfig
from stage5_navigation.heterogeneity import (HeterogeneousPISimulation, group_assignment, matched_theta,
                                             persistence)
from stage5_navigation.path_integration import NavigationConfig, PathIntegrationSimulation

NAV = NavigationConfig(compass_noise=0.5, landmarks=((25.0, 30.0), (40.0, 35.0)), deposit_during_search=False)


def config(seed: int = 11, steps: int = 2000) -> SimulationConfig:
    return SimulationConfig(n_ants=20, steps=steps, seed=seed, arena_size=60, nest=(30, 30),
                            food_a=(38, 30), food_b=(30, 38), relocation_step=1000,
                            decay=DecayConfig(half_life_steps=200))


def test_homogeneous_setting_reproduces_path_integration_exactly():
    for theta in (None, (math.pi / 3,) * 20):
        a = PathIntegrationSimulation(config(), NAV)
        b = HeterogeneousPISimulation(config(), NAV, theta)
        a.run()
        b.run()
        assert a.ledger.events and a.ledger.events == b.ledger.events
        assert [x.position for x in a.ants] == [x.position for x in b.ants]
        assert np.array_equal(a.field.concentration, b.field.concentration)


def test_heterogeneous_turns_are_rescaled_homogeneous_turns():
    thetas = tuple(math.radians(120) if i < 5 else math.radians(37.43) for i in range(20))
    homo = HeterogeneousPISimulation(config(), NAV)
    het = HeterogeneousPISimulation(config(), NAV, thetas)
    for i, theta in enumerate(thetas):
        assert np.max(np.abs(het._turns[i])) <= theta
        assert np.allclose(het._turns[i], homo._turns[i] * theta / (math.pi / 3))
    het.run()
    homo.run()
    assert [a.position for a in het.ants] != [a.position for a in homo.ants]


def test_persistence_matches_fcrw_generator_and_matched_mean():
    for deg in (37.43, 60, 120):
        theta = math.radians(deg)
        turns = generate_trajectory("fcrw", steps=400_000, theta_max=theta, rng=np.random.default_rng(1)).turn_angles
        assert np.cos(turns).mean() == pytest.approx(persistence(theta), abs=2e-3)
    ref, scout = math.pi / 3, math.radians(120)
    recruit = matched_theta(ref, 0.2, scout)
    assert math.degrees(recruit) == pytest.approx(37.432, abs=1e-3)
    assert 0.2 * persistence(scout) + 0.8 * persistence(recruit) == pytest.approx(persistence(ref), abs=1e-12)
    # The other end of the spread is outside [20, 120] degrees: recruits at 20 need scouts at ~146.5.
    assert math.degrees(matched_theta(ref, 0.8, math.radians(20))) == pytest.approx(146.52, abs=0.01)
    with pytest.raises(ValueError):
        matched_theta(ref, 0.9, 0.0)  # would need the other 10% beyond pi


def test_group_assignment_is_seeded_and_sized():
    g = group_assignment(2026260001, 100, 20)
    assert len(set(g)) == 20 and g == group_assignment(2026260001, 100, 20)
    assert g != group_assignment(2026260002, 100, 20)


def test_rejects_wrong_length():
    with pytest.raises(ValueError):
        HeterogeneousPISimulation(config(), NAV, (1.0,) * 3)
