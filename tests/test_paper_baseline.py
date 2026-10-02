import math

import numpy as np
import pytest

from colony.environment import SquareEnvironment
from scalar_baseline.config import B0Config, DecayConfig, SimulationConfig
from scalar_baseline.simulation import Simulation
from paper_baseline import checks
from paper_baseline.model import (NoDecayField, PaperOptions, PaperSimulation, baseline_options,
                                  order_parameters, reflect, walk_route)


def config(**kw):
    base = dict(n_ants=12, steps=400, seed=7, arena_size=40.0, nest=(20.0, 20.0), food_a=(26.0, 26.0),
                food_b=(14.0, 26.0), gamma=0.1, theta_max=math.radians(50),
                decay=DecayConfig(half_life_steps=200), navigation=B0Config(signal_on=0.25, signal_off=0.125))
    base.update(kw)
    return SimulationConfig(**base)


def snapshot(sim):
    return ([(a.position, a.heading, a.role) for a in sim.ants], sim.field.concentration.copy(),
            list(sim.ledger.events))


def test_all_off_reproduces_validated_simulation():
    cfg = config(n_ants=30, steps=1500, food_a=(23.0, 23.0), food_b=(17.0, 23.0))
    old, new = Simulation(cfg), PaperSimulation(cfg, record=True)
    for _ in range(cfg.steps):
        old.step()
        new.step()
    a, b = snapshot(old), snapshot(new)
    assert a[0] == b[0] and a[2] == b[2] and np.array_equal(a[1], b[1])
    assert old.ledger.deliveries["A"] > 0  # the comparison exercised transport


def test_reflect_matches_colony_rule():
    env = SquareEnvironment(10.0)
    rng = np.random.default_rng(1)
    for _ in range(500):
        p = tuple(rng.uniform(0, 10, 2))
        h, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, 3)
        (x, y), heading = reflect(p, h, d, 10.0)
        ref, ref_h = env.reflect_move(np.array(p), heading=h, distance=d)
        assert np.allclose((x, y), ref) and math.isclose(math.cos(heading), math.cos(ref_h), abs_tol=1e-12)
        assert math.isclose(math.sin(heading), math.sin(ref_h), abs_tol=1e-12)
        assert 0 <= x <= 10 and 0 <= y <= 10 and 0 <= heading < 2 * math.pi


def test_reflect_mirrors_heading_at_wall():
    (x, y), h = reflect((9.8, 5.0), 0.0, 0.6, 10.0)
    assert math.isclose(x, 9.6) and y == 5.0 and math.isclose(h, math.pi)


def test_reflective_run_stays_inside():
    cfg = config(arena_size=12.0, nest=(6.0, 6.0), food_a=(9.0, 9.0), food_b=(3.0, 9.0), steps=600)
    sim = PaperSimulation(cfg, PaperOptions(boundary="reflect"))
    sim.run()  # validate() checks every position each step
    assert all(0 <= v <= 12 for a in sim.ants for v in a.position)


def test_walk_route_moves_fixed_length_through_corners():
    route = [(1.0, 0.0), (1.0, 1.0), (1.0, 5.0)]
    pos, h = walk_route((0.0, 0.0), route, 0.6)
    assert pos == (0.6, 0.0) and h == 0.0
    pos, h = walk_route(pos, route, 0.6)  # 0.4 to the corner, then 0.2 up
    assert np.allclose(pos, (1.0, 0.2)) and math.isclose(h, math.pi / 2)
    assert route == [(1.0, 1.0), (1.0, 5.0)]


def test_stride3_route_keeps_every_third_vertex_and_ends_at_nest():
    cfg = config()
    sim = PaperSimulation(cfg, PaperOptions(return_stride=3))
    ant = sim.ants[0]
    ant.path = [(20.0 + 0.5 * i, 20.0) for i in range(11)]  # vertices 0..10
    ant.position = ant.path[-1]
    sim.environment._sources["A"] = ant.position
    sim._contacts(ant)
    assert ant.role == "transporter"
    expected = [ant.path[i] for i in (9, 6, 3, 0)]  # kept 0,3,6,9,10; reversed, minus current
    assert sim.routes[0] == expected
    assert sim.pickup_roles == [(0, "fcrw")]
    steps = 0
    while ant.role == "transporter":
        sim.time += 1
        sim._move(ant)
        sim._contacts(ant)
        steps += 1
    assert steps == math.ceil((5.0 - 0.75) / 0.6)  # straight route, delivered on entering the nest radius
    assert sim.ledger.deliveries["A"] == 1


def test_coarse_route_is_shorter_than_wiggly_path():
    cfg = config()
    sim = PaperSimulation(cfg, PaperOptions(return_stride=3))
    ant = sim.ants[0]
    ant.path = [(20.0 + 0.5 * i, 20.0 + (0.4 if i % 2 else 0.0)) for i in range(31)]
    ant.position = ant.path[-1]
    sim.environment._sources["A"] = ant.position
    sim._contacts(ant)
    route = [ant.position] + sim.routes[0]
    length = sum(math.dist(p, q) for p, q in zip(route, route[1:]))
    raw = sum(math.dist(p, q) for p, q in zip(ant.path, ant.path[1:]))
    assert length < raw


def test_delivery_turns_transporter_into_follower_facing_away():
    cfg = config()
    sim = PaperSimulation(cfg, PaperOptions(return_stride=3, after_delivery="follower"))
    ant = sim.ants[0]
    sim.ledger.pickup(0, "A", 0)
    ant.role, ant.position, ant.heading = "transporter", (20.3, 20.0), math.pi
    ant.path = [(21.0, 20.0), (20.3, 20.0)]
    sim.routes[0] = []
    sim._contacts(ant)
    assert ant.role == "follower" and ant.low_steps == 0
    assert math.isclose(ant.heading, 0.0, abs_tol=1e-12)
    assert ant.path == [(20.3, 20.0)] and 0 not in sim.routes


def test_default_delivery_still_reverts_to_forager():
    sim = PaperSimulation(config(), PaperOptions(return_stride=3))
    ant = sim.ants[0]
    sim.ledger.pickup(0, "A", 0)
    ant.role, ant.position, ant.heading = "transporter", (20.3, 20.0), math.pi
    ant.path = [(20.3, 20.0)]
    sim._contacts(ant)
    assert ant.role == "fcrw" and ant.heading == math.pi


def test_pheromone_off_keeps_field_zero_but_transports():
    cfg = config(steps=1500)
    sim = PaperSimulation(cfg, baseline_options(0.01, deposit=False))
    sim.run()
    assert sim.field.concentration.sum() == 0
    assert sim.ledger.discoveries["A"] > 0
    assert all(role == "fcrw" for _, role in sim.pickup_roles)


def test_no_decay_field_keeps_mass():
    f = NoDecayField(10.0, 1.0, DecayConfig(half_life_steps=5))
    f.deposit((2.5, 2.5), 1.0)
    f.advance(1000)
    assert f.concentration.sum() == 1.0


def test_diffusing_option_conserves_mass_away_from_edge():
    sim = PaperSimulation(config(), baseline_options(0.02))
    sim.field.deposit((20.5, 20.5), 1.0)
    sim.field.advance(10)
    keep = math.exp(-math.log(2) / 200 * 10)
    assert math.isclose(sim.field.concentration.sum(), keep, rel_tol=1e-9)
    assert sim.field.concentration[20, 20] < keep


def test_zw_option_changes_only_the_search_turns():
    cfg = config()
    fc, zw = PaperSimulation(cfg, baseline_options(0.01)), PaperSimulation(cfg, baseline_options(0.01, walk="zw"))
    assert not np.array_equal(fc._turns[0], zw._turns[0])
    assert np.all(np.abs(zw._turns[0]) <= cfg.theta_max)
    assert [a.heading for a in fc.ants] == [a.heading for a in zw.ants]


def test_baseline_run_is_valid_and_records():
    cfg = config(steps=1500)
    sim = PaperSimulation(cfg, baseline_options(0.01), record=True)
    sim.run()
    assert sim.counts.sum(axis=1).tolist() == [cfg.n_ants] * cfg.steps
    assert np.all((sim.psi >= 0) & (sim.psi <= 1 + 1e-12))
    assert sim.ledger.deliveries["A"] > 0
    assert any(role == "follower" for _, role in sim.pickup_roles)


def test_order_parameters_aligned_and_uniform():
    phi, psi = order_parameters(np.full(50, math.pi / 4))
    assert math.isclose(psi, 1.0) and math.isclose(phi, math.pi / 4)
    phi, psi = order_parameters(np.array([math.pi / 4, math.pi / 4 + math.pi]))  # opposite = same axis
    assert math.isclose(psi, 1.0) and math.isclose(phi, math.pi / 4)
    rng = np.random.default_rng(0)
    phi, psi = order_parameters(rng.uniform(0, 2 * math.pi, 200_000))
    assert abs(psi - 2 / math.pi) < 0.01 and abs(phi) < 0.01


def test_trail_share():
    c = np.zeros((30, 30))
    c[10, 10] = 3.0      # on the segment (10,10)-(20,20)
    c[25, 2] = 1.0       # far away
    assert math.isclose(checks.trail_share(c, 1.0, (10, 10), (20, 20)), 0.75)
    assert checks.trail_share(np.zeros((5, 5)), 1.0, (1, 1), (3, 3)) == 0.0


def test_recruitment_and_discovery():
    roles = [(3000, "follower"), (5000, "follower"), (6000, "fcrw"), (7000, "follower"), (12000, "fcrw")]
    assert math.isclose(checks.recruitment_share(roles), 2 / 3)
    assert checks.recruitment_share([]) == 0.0
    assert checks.first_pickup([900, 400], 12000) == 400 and checks.first_pickup([], 12000) == 12000


def test_transport_linear_and_none():
    times = list(range(6000, 12000, 30))
    count, r2 = checks.transport(times)
    assert count == 200 and r2 > 0.999
    assert checks.transport([]) == (0, 0.0)
    count, r2 = checks.transport([11990] * 150)  # all at the end: far from linear
    assert count == 150 and r2 < 0.95


def run_metrics(seed, **kw):
    m = dict(seed=seed, first_pickup=1000, recruitment=0.8, trail_share=0.7, deliveries_window=300,
             r2=0.99, psi=0.95, phi=math.pi / 4, foragers=5)
    m.update(kw)
    return m


def test_condition_rules_full_basic_and_seed_share():
    runs = [run_metrics(s) for s in range(10)]
    off = {s: 0.64 for s in range(10)}
    out = checks.condition_checks(runs, off)
    assert out["full_pass"] and out["basic_pass"]
    runs = [run_metrics(s, psi=0.85, foragers=20) for s in range(10)]
    out = checks.condition_checks(runs, off)
    assert not out["full_pass"] and out["basic_pass"]
    out = checks.condition_checks(runs, {s: 0.8 for s in range(10)})  # gain only 0.05
    assert not out["basic_pass"]
    runs = [run_metrics(s, first_pickup=5000 if s < 3 else 1000) for s in range(10)]  # 7/10 seeds
    assert not checks.condition_checks(runs, off)["c1"]
    runs = [run_metrics(s, first_pickup=5000 if s < 2 else 1000) for s in range(10)]  # 8/10 seeds
    assert checks.condition_checks(runs, off)["c1"]
