"""Engineering fixtures, not scientific confirmation experiments."""

from dataclasses import asdict, replace
import ast
import inspect
import math

import numpy as np
import pytest

from ant_walks.models import generate_trajectory
from scalar_baseline.config import (B0Config, DecayConfig, SimulationConfig,
                                    half_life_to_rate, rate_to_half_life, matched_cutoff_steps)
from scalar_baseline.environment import ContactEnvironment, Ledger
from scalar_baseline.field import ScalarField
from scalar_baseline.navigation import navigate
from scalar_baseline.sensing import sense
from scalar_baseline.simulation import Simulation
import scalar_baseline.navigation as navigation_module
import scalar_baseline.sensing as sensing_module


@pytest.mark.parametrize("half", [0.1, 1.0, 20.0, 1000.0])
def test_half_life_rate_roundtrip(half):
    rate = half_life_to_rate(half)
    assert rate == math.log(2) / half
    assert rate_to_half_life(rate) == pytest.approx(half)


def test_equivalent_parameterisations_step_by_step():
    half = 20.0
    rate = half_life_to_rate(half)
    fields = [ScalarField(4, 1, c) for c in (
        DecayConfig(half_life_steps=half), DecayConfig(decay_rate=rate),
        DecayConfig(half_life_steps=half, decay_rate=rate))]
    for f in fields:
        f.deposit((1, 1), 3)
    for t in range(30):
        deposits = [((1, 1), 0.7), ((2, 2), 0.1)] if t % 3 == 0 else []
        for f in fields:
            f.step(deposits)
        for f in fields[1:]:
            np.testing.assert_array_equal(f.concentration, fields[0].concentration)


@pytest.mark.parametrize("kwargs", [
    {"half_life_steps": 20, "decay_rate": 0.4}, {"half_life_steps": 0},
    {"decay_rate": -1}, {"decay_rate": float("nan")}, {"half_life_steps": float("inf")},
    {"mode": "hard_cutoff"}, {"cutoff_steps": 3},
    {"mode": "hard_cutoff_cell_timer", "cutoff_steps": 2, "half_life_steps": 20},
    {"mode": "hard_cutoff_cell_timer", "cutoff_steps": 0},
    {"mode": "hard_cutoff_cell_timer", "cutoff_steps": 2.5},
    {"mode": "hard_cutoff_cell_timer", "cutoff_steps": True},
])
def test_invalid_decay_rejected(kwargs):
    with pytest.raises(ValueError):
        DecayConfig(**kwargs)


def test_exponential_analytic_and_multiple_deposits():
    f = ScalarField(3, 1, DecayConfig(half_life_steps=2))
    f.deposit((1, 1), 8)
    f.advance(2)
    assert f.sample((1, 1)) == pytest.approx(4)
    f.deposit((1, 1), 2)
    f.advance(4)
    assert f.sample((1, 1)) == pytest.approx(8 * 0.25 + 2 * 0.5)
    f.step([((1, 1), 7)])
    assert f.sample((1, 1)) == pytest.approx(3 * 2 ** (-0.5) + 7)


def test_cutoff_hold_expire_refresh_and_zero_deposit():
    f = ScalarField(3, 1, DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=3))
    f.deposit((1, 1), 4)
    f.advance(2)
    assert f.sample((1, 1)) == 4
    f.deposit((1, 1), 2)
    f.advance(4)
    assert f.sample((1, 1)) == 6
    f.deposit((1, 1), 0)
    f.advance(5)
    assert f.sample((1, 1)) == 0


@pytest.mark.parametrize("decay", [DecayConfig(half_life_steps=1), DecayConfig(mode="hard_cutoff_cell_timer", cutoff_steps=1)])
def test_common_decay_then_deposit_order_and_no_diffusion(decay):
    f = ScalarField(5, 1, decay)
    f.deposit((2.2, 2.2), 4)
    f.step([((2.3, 2.3), 3)])
    assert f.sample((2, 2)) == (5 if decay.mode == "exponential" else 3)
    occupied = np.zeros((5, 5), bool)
    occupied[2, 2] = True
    for _ in range(5):
        assert np.all(f.concentration[~occupied] == 0)
        f.step()
    assert set(ScalarField.__slots__) == {"concentration", "last_deposit", "time", "arena_size", "cell_size", "decay"}
    assert f.last_deposit is None if decay.mode == "exponential" else f.last_deposit.dtype == np.int64


def test_matching_rule_fixed_before_foraging():
    assert matched_cutoff_steps(1, 0.5, half_life_to_rate(20)) == 20
    assert matched_cutoff_steps(1, 0.5, half_life_to_rate(20.1)) == 21
    assert matched_cutoff_steps(1, 0.25, half_life_to_rate(20)) == 40
    with pytest.raises(ValueError):
        matched_cutoff_steps(0.1, 0.5, 1)


def decision(left, right, **kwargs):
    args = dict(heading=math.pi, left=left, right=right, role="follower", low_steps=0,
                fcrw_turn=0.2, noise=0.0, config=B0Config())
    args.update(kwargs)
    return navigate(**args)


def test_left_right_and_tie():
    assert decision(2, 1).heading > math.pi
    assert decision(1, 2).heading < math.pi
    assert decision(1, 1).heading == math.pi
    assert decision(0, 0).deterministic_turn == 0
    assert decision(1e308, 1e308).heading == math.pi
    assert decision(1e308, 0).deterministic_turn == pytest.approx(math.pi / 3)


def test_loss_switch_is_immediate_frozen_fcrw_no_recovery():
    first = decision(0, 0)
    assert (first.role, first.low_steps) == ("follower", 1)
    second = decision(0, 0, low_steps=first.low_steps)
    assert second.role == "fcrw"
    assert second.heading == math.pi + 0.2
    assert "recovery_duration" not in asdict(B0Config())
    for role in ("recovery", "casting"):
        with pytest.raises(ValueError):
            decision(1, 1, role=role)


def test_threshold_equality_hysteresis_and_streak_reset():
    assert decision(0.25, 0, low_steps=1).low_steps == 0
    assert decision(0.49, 0, role="fcrw").role == "fcrw"
    assert decision(0.5, 0, role="fcrw").role == "follower"
    assert decision(0.3, 0).role == "follower"


def test_navigation_structural_food_isolation():
    assert set(inspect.signature(navigate).parameters) == {"heading", "left", "right", "role", "low_steps", "fcrw_turn", "noise", "config"}
    for module in (navigation_module, sensing_module):
        tree = ast.parse(inspect.getsource(module))
        identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not identifiers & {"food_a", "food_b", "food_contact", "environment", "ledger", "cargo", "argmax", "gradient", "direction_sum"}


def test_sensor_only_two_queries_and_left_geometry():
    class Probe:
        def __init__(self):
            self.points = []
        def sample(self, point):
            self.points.append(point)
            return point[1]
    probe = Probe()
    left, right = sense(probe, (10, 10), 0, B0Config())
    assert len(probe.points) == 2
    assert left > right
    assert all(math.dist(p, (10, 10)) == pytest.approx(1) for p in probe.points)


def test_own_fcrw_schedule_reuses_legacy_exactly():
    config = SimulationConfig(n_ants=1, steps=10)
    sim = Simulation(config)
    expected = generate_trajectory("fcrw", steps=10, step_size=config.step_size,
                                   theta_max=config.theta_max, gamma=config.gamma,
                                   rng=np.random.default_rng(np.random.SeedSequence([config.seed, 0, 2])))
    np.testing.assert_array_equal(sim._turns[0], expected.turn_angles)


def test_changing_food_positions_cannot_change_noncontact_navigation():
    a = Simulation(SimulationConfig(n_ants=1, steps=8, food_a=(39, 20), food_b=(20, 39)))
    b = Simulation(replace(a.config, food_a=(1, 20), food_b=(20, 1)))
    for sim in (a, b):
        sim.ants[0].role = "follower"
        sim.field.deposit((20, 20), 2)
    for _ in range(8):
        a.step(); b.step()
        assert asdict(a.ants[0]) == asdict(b.ants[0])
    assert a.ledger.events == b.ledger.events == []


def test_move_has_no_contact_environment_dependency():
    sim = Simulation(SimulationConfig(n_ants=1, steps=1))
    class Poison:
        def __getattribute__(self, name):
            raise AssertionError("movement tried to access environment")
    sim.environment = Poison()
    sim.ants[0].role = "follower"
    sim.time = 1
    sim._move(sim.ants[0])


def test_relocation_preserves_field_all_agent_state_and_classifies_cargo():
    sim = Simulation(SimulationConfig(n_ants=2, steps=5, relocation_step=2))
    sim.ants[0].role = "transporter"
    sim.ledger.pickup(0, "A", 1)
    sim.field.deposit((8, 8), 3)
    before = [asdict(a) for a in sim.ants]
    field = sim.field.concentration.copy()
    sim.environment.relocate(2, sim.ledger)
    assert before == [asdict(a) for a in sim.ants]
    np.testing.assert_array_equal(field, sim.field.concentration)
    assert sim.environment.food_contact(sim.config.food_a) is None
    assert sim.environment.food_contact(sim.config.food_b) == "B"
    assert sim.ledger.carried_a_at_relocation == [0]
    sim.ledger.pickup(1, "B", 2)
    sim.ledger.deliver(0, 3)
    assert sim.ledger.deliveries == {"A": 1, "B": 0}
    sim.ledger.deliver(1, 4)
    assert sim.ledger.deliveries == {"A": 1, "B": 1}
    sim.environment.relocate(2, sim.ledger)
    assert sum(e["event"] == "relocation" for e in sim.ledger.events) == 1


@pytest.mark.parametrize("mode", ["exponential", "hard_cutoff_cell_timer"])
def test_small_population_reproducibility_bounds_finite(mode):
    decay = DecayConfig() if mode == "exponential" else DecayConfig(mode=mode, cutoff_steps=20)
    config = SimulationConfig(steps=30, relocation_step=15, decay=decay)
    a, b = Simulation(config), Simulation(config)
    for _ in range(config.steps):
        a.step(); b.step()
        assert [asdict(x) for x in a.ants] == [asdict(x) for x in b.ants]
        np.testing.assert_array_equal(a.field.concentration, b.field.concentration)
    assert asdict(a.ledger) == asdict(b.ledger)
    with pytest.raises(ValueError):
        a.step()


def test_boundary_and_deposit_numeric_validation():
    f = ScalarField(4, 1, DecayConfig())
    f.deposit((4, 4), 1)
    assert f.sample((100, 100)) == 1
    assert f.sample((-1, -1)) == 0
    for amount in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            f.deposit((0, 0), amount)
    f.deposit((0, 0), 1e308)
    with pytest.raises(ValueError):
        f.deposit((0, 0), 1e308)
    assert np.all(np.isfinite(f.concentration))
    with pytest.raises(ValueError):
        f.sample((float("nan"), 0))
    with pytest.raises(ValueError):
        f.advance(-1)
    sim = Simulation(SimulationConfig(n_ants=1, steps=1))
    sim.ants[0].position = (40, 40)
    sim.ants[0].path = [(40, 40)]
    sim.time = 1
    sim._move(sim.ants[0])
    sim.validate()


@pytest.mark.parametrize("kwargs", [{"diffusion": 0.1}, {"steps": 0}, {"n_ants": True},
    {"deposit_q": float("inf")}, {"food_b": (21, 21)}, {"relocation_step": 101},
    {"gamma": float("nan")}, {"cell_size": 0}, {"step_size": -1}])
def test_invalid_simulation_config_rejected(kwargs):
    with pytest.raises(ValueError):
        SimulationConfig(**kwargs)


def test_end_to_end_relocation_delivery_and_trail_gap_fixtures():
    from scalar_baseline.pilot import relocation_fixture, trail_fixture
    relocation = relocation_fixture()
    deliveries = [e for e in relocation["ledger"]["events"] if e["event"] == "delivery"]
    assert deliveries == [{"time": 8, "event": "delivery", "ant_id": 0, "source": "A"},
                          {"time": 10, "event": "delivery", "ant_id": 1, "source": "B"}]
    gap = trail_fixture(True)
    assert any(r["role"] == "fcrw" for r in gap["rows"])


def test_all_movement_observes_predeposition_field():
    config = SimulationConfig(n_ants=2, steps=1, theta_max=0,
                              navigation=B0Config(sensor_distance=0.1, noise_amplitude=0))
    sim = Simulation(config)
    # Returner deposits into the follower sensor cell during this step.
    sim.ants[0].position = (22.6, 20)
    sim.ants[0].path = [(20, 20), (22, 20), (22.6, 20)]
    sim.ants[0].role = "transporter"
    sim.ledger.pickup(0, "A", 0)
    sim.ants[1].position = (22.2, 20.2)
    sim.ants[1].path = [(22.2, 20.2)]
    sim.ants[1].heading = 0
    sim.step()
    assert sim.ants[1].role == "fcrw"
    assert sim.field.sample((22.2, 20.2)) == 1


def test_noise_symmetric_tie_and_max_turn():
    left = decision(1, 1, noise=0.05)
    right = decision(1, 1, noise=-0.05)
    assert (left.heading + right.heading) / 2 == pytest.approx(math.pi)
    saturated = decision(1e308, 0, noise=0.05)
    assert saturated.heading - math.pi == pytest.approx(B0Config().max_turn)


def test_field_rejects_nonzero_diffusion_directly():
    with pytest.raises(ValueError):
        ScalarField(4, 1, DecayConfig(), diffusion=0.1)
