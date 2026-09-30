from dataclasses import asdict, replace
import ast
import inspect
import math
import textwrap

import numpy as np
import pytest

from scalar_baseline.config import B0Config, SimulationConfig
from scalar_baseline.functional_validation import ObservedSimulation
from scalar_baseline.simulation import Simulation
from scalar_baseline.stage3b import (OFFSETS, RECOVERY_DURATION, PairedB0Simulation,
    RecoverySimulation, paired_config, shortest_angle, side_schedule, state_digest)
import scalar_baseline.stage3b as stage3b


def small_config(**kwargs):
    base = SimulationConfig(n_ants=1, steps=40, arena_size=10, nest=(2,2),
        food_a=(8,2), food_b=(2,8), contact_radius=0.15, theta_max=0,
        relocation_step=None, navigation=B0Config(noise_amplitude=0))
    return replace(base, **kwargs)


def trigger(sim, side=1, heading=0):
    ant = sim.ants[0]; state = sim.recovery[0]
    ant.role, ant.heading, ant.low_steps = 'follower', heading, 1
    state.last_reliable_heading = heading
    sim._recovery_sides[0, 0] = side
    sim.time = 1
    sim._move(ant)
    return ant, state


def test_b0_default_behavior_stepwise_unchanged():
    config = SimulationConfig(n_ants=4, steps=50)
    old, paired = ObservedSimulation(config), PairedB0Simulation(config)
    for _ in range(50):
        old.step(); paired.step()
        assert [asdict(a) for a in old.ants] == [asdict(a) for a in paired.ants]
        assert asdict(old.ledger) == asdict(paired.ledger)
        np.testing.assert_array_equal(old.field.concentration, paired.field.concentration)


def test_relocation_B0_static_prefix_exact():
    static = PairedB0Simulation(small_config(steps=6))
    relocating = PairedB0Simulation(small_config(steps=6, relocation_step=6))
    for _ in range(5):
        static.step(); relocating.step()
        assert state_digest(static) == state_digest(relocating)
        assert static.observations == relocating.observations


def test_two_low_steps_enter_recovery_with_last_reliable_anchor():
    sim = RecoverySimulation(small_config())
    ant, state = trigger(sim, side=1, heading=0.3)
    assert state.recovery_active and state.recovery_step == 1
    assert state.recovery_anchor_heading == 0.3 and state.recovery_initial_side == 1
    assert ant.role == 'follower' and sim.anchor_fallbacks == 0


def test_explicit_anchor_fallback_never_uses_food_direction():
    sim = RecoverySimulation(small_config())
    ant = sim.ants[0]; ant.role='follower'; ant.heading=1.2; ant.low_steps=1
    sim.time=1; sim._move(ant)
    assert sim.anchor_fallbacks == 1
    assert sim._open_recovery[0]['anchor_heading'] == 1.2


def test_recovery_exactly_24_movements_then_next_step_fcrw():
    sim = RecoverySimulation(small_config())
    ant, state = trigger(sim)
    for t in range(2, 25):
        sim.time=t; sim._move(ant)
    assert not state.recovery_active and ant.role == 'fcrw'
    assert sim.recovery_episodes[0]['duration'] == RECOVERY_DURATION == 24
    heading = ant.heading
    sim.time=25; sim._move(ant)
    assert ant.heading == pytest.approx((heading + sim._turns[0][24]) % (2*math.pi))


def test_four_segment_offsets_and_initial_side_mirror():
    assert tuple(round(math.degrees(x)) for x in OFFSETS) == (15,-30,45,-60)
    left, right = RecoverySimulation(small_config()), RecoverySimulation(small_config())
    a, _ = trigger(left, side=1); b, _ = trigger(right, side=-1)
    assert a.heading == pytest.approx(-b.heading % (2*math.pi))
    assert a.position[0] == pytest.approx(b.position[0])
    assert a.position[1] - 2 == pytest.approx(-(b.position[1] - 2))


@pytest.mark.parametrize(('target','current','expected'), [(0.1,2*math.pi-0.1,0.2),(2*math.pi-0.1,0.1,-0.2)])
def test_shortest_angle_across_wrap(target,current,expected):
    assert shortest_angle(target,current) == pytest.approx(expected)


def test_reacquire_at_on_exits_same_step_with_scalar_steering():
    sim=RecoverySimulation(small_config()); ant,state=trigger(sim)
    sim.field.concentration[:]=1
    sim.time=2; before=ant.position; sim._move(ant)
    assert not state.recovery_active and ant.role=='follower'
    assert sim.recovery_episodes[0]['outcome']=='reacquired'
    assert math.dist(before,ant.position)==pytest.approx(sim.config.step_size)


def test_between_off_and_on_does_not_reacquire():
    sim=RecoverySimulation(small_config()); ant,state=trigger(sim)
    sim.field.concentration[:]=0.3
    sim.time=2; sim._move(ant)
    assert state.recovery_active and state.recovery_step==2


def test_side_schedule_deterministic_independent_and_unused_by_B0():
    a=side_schedule(7,2,50); b=side_schedule(7,2,50); c=side_schedule(7,3,50)
    np.testing.assert_array_equal(a,b); assert not np.array_equal(a,c)
    assert set(a)=={-1,1}
    assert '_recovery_sides' not in inspect.getsource(PairedB0Simulation._move)


def test_pair_initial_random_identity_and_single_shared_config():
    config=paired_config(2026091701); b=PairedB0Simulation(config); c=RecoverySimulation(config)
    assert [asdict(a) for a in b.ants]==[asdict(a) for a in c.ants]
    for name in ('_turns','_noise','_recovery_sides'):
        np.testing.assert_array_equal(getattr(b,name),getattr(c,name))
    assert asdict(b.config)==asdict(c.config)


def test_recovery_move_has_no_food_direction_or_global_field_scan():
    tree=ast.parse(textwrap.dedent(inspect.getsource(RecoverySimulation._move)))
    names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
    assert not names & {'food_a','food_b','food_contact','environment','direction_sum','mean_direction','gradient','argmax'}
    assert 'sense' in names


def test_relocation_preserves_field_and_agent_state():
    sim=RecoverySimulation(small_config(relocation_step=2)); sim.field.deposit((5,5),3)
    before=[asdict(a) for a in sim.ants]; field=sim.field.concentration.copy()
    sim.environment.relocate(2,sim.ledger)
    assert before==[asdict(a) for a in sim.ants]; np.testing.assert_array_equal(field,sim.field.concentration)
    assert sim.environment.active_source=='B'


def test_A_B_delivery_classification_and_carried_A_after_relocation():
    sim=RecoverySimulation(small_config(relocation_step=2)); sim.ledger.pickup(0,'A',1)
    sim.ants[0].role='transporter'; sim.environment.relocate(2,sim.ledger)
    sim.ledger.deliver(0,3)
    assert sim.ledger.deliveries=={'A':1,'B':0} and sim.ledger.carried_a_at_relocation==[0]


def test_observation_mutation_does_not_change_recovery_dynamics():
    a,b=RecoverySimulation(small_config()),RecoverySimulation(small_config())
    for _ in range(40):
        a.step(); b.step(); b.observations.clear()
        assert [asdict(x) for x in a.ants]==[asdict(x) for x in b.ants]
        np.testing.assert_array_equal(a.field.concentration,b.field.concentration)


@pytest.mark.parametrize('kind',['B0','C'])
def test_fixed_seed_reproducibility_population_bounds_finite(kind):
    cls=PairedB0Simulation if kind=='B0' else RecoverySimulation
    a,b=cls(small_config()),cls(small_config())
    for _ in range(40):a.step();b.step()
    assert state_digest(a)==state_digest(b)
    assert len(a.ants)==1 and np.isfinite(a.field.concentration).all()
    assert all(0<=v<=10 for v in a.ants[0].position)


def test_food_contact_can_end_recovery_episode():
    sim=RecoverySimulation(small_config()); ant,state=trigger(sim)
    ant.position=sim.config.food_a; ant.path[-1]=ant.position
    sim._contacts(ant)
    assert sim.recovery_episodes[0]['outcome']=='food_contact'
    assert ant.role=='transporter'


def test_post_recovery_B_window_is_per_ant():
    sim=RecoverySimulation(small_config(n_ants=2, relocation_step=2))
    sim.recovery_episodes.append({'ant_id':0,'end_time':1,'post_window_end':20,
                                  'B_discovery_within_window':False,'B_delivery_within_window':False})
    sim.time=2; sim.environment.relocate(2,sim.ledger)
    ant=sim.ants[1]; ant.position=sim.config.food_b; ant.path[-1]=ant.position; ant.role='follower'
    sim._contacts(ant)
    assert not sim.recovery_episodes[0]['B_discovery_within_window']
