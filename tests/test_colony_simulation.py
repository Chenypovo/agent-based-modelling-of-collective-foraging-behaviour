from __future__ import annotations

from dataclasses import replace

import numpy as np

from colony.agents import Ant, Role, prepare_transporter_route
from colony.config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from colony.simulation import ColonySimulation


def deterministic_config(*, steps: int = 10, n_ants: int = 1) -> ColonyConfig:
    return ColonyConfig(
        n_ants=n_ants,
        arena_size=10.0,
        steps=steps,
        seed=123,
        movement=MovementConfig(model="zw", step_size=0.6, theta_deg=0.0, gamma=0.1),
        pheromone=PheromoneConfig(cell_size=0.2, sensing_range=0.25),
        nest=SiteConfig((1.0, 5.0), 0.25),
        food=SiteConfig((3.4, 5.0), 0.1),
        snapshot_steps=(),
        agent_state_interval=1,
        output_dir="results/stage2_provisional/test-only",
    )


def test_forager_finds_food_in_deterministic_scene() -> None:
    config = deterministic_config(steps=1)
    ant = Ant(
        ant_id=0,
        position=np.array([2.8, 5.0]),
        heading=0.0,
        role=Role.FORAGER,
        travel_path=[np.array([1.0, 5.0]), np.array([2.8, 5.0])],
    )
    simulation = ColonySimulation(
        config,
        initial_agents=[ant],
        turn_schedules=np.zeros((1, config.steps)),
    )
    simulation.step()

    assert simulation.ants[0].role is Role.TRANSPORTER
    assert simulation.first_food_discovery_time == 1
    assert simulation.transition_counts["forager_to_transporter"] == 1


def test_transporter_returns_to_nest_and_becomes_follower() -> None:
    config = deterministic_config(steps=8)
    path = [np.array([1.0 + 0.4 * i, 5.0]) for i in range(7)]
    ant = Ant(
        ant_id=0,
        position=path[-1].copy(),
        heading=0.0,
        role=Role.TRANSPORTER,
        travel_path=[point.copy() for point in path],
    )
    prepare_transporter_route(ant, stride=config.memory_stride)
    simulation = ColonySimulation(
        config,
        initial_agents=[ant],
        turn_schedules=np.zeros((1, config.steps)),
    )
    simulation.run()

    assert simulation.first_delivery_time is not None
    assert simulation.cumulative_deliveries >= 1
    assert simulation.transition_counts["transporter_to_follower"] >= 1
    assert simulation.field.total_intensity > 0


def test_follower_reaches_food_on_deterministic_trail() -> None:
    config = deterministic_config(steps=5)
    ant = Ant(
        ant_id=0,
        position=np.array(config.nest.center),
        heading=0.0,
        role=Role.FOLLOWER,
        travel_path=[np.array(config.nest.center)],
    )
    simulation = ColonySimulation(
        config,
        initial_agents=[ant],
        turn_schedules=np.zeros((1, config.steps)),
    )
    for x in np.arange(1.0, 3.41, 0.2):
        simulation.field.deposit(np.array([x, 5.0]), np.array([1.0, 0.0]))

    simulation.run()

    assert simulation.transition_counts["follower_to_transporter"] == 1
    assert simulation.ants[0].role is Role.TRANSPORTER


def test_seed_reproducibility() -> None:
    base = ColonyConfig.pilot(output_dir="results/stage2_provisional/test-only")
    config = replace(base, n_ants=4, steps=120, snapshot_steps=(), agent_state_interval=20)
    first = ColonySimulation(config).run()
    second = ColonySimulation(config).run()

    np.testing.assert_array_equal(
        first.metrics.to_numpy(), second.metrics.to_numpy()
    )
    np.testing.assert_array_equal(
        first.final_agents.to_numpy(), second.final_agents.to_numpy()
    )


def test_small_long_run_preserves_population_bounds_and_finite_state() -> None:
    base = ColonyConfig.pilot(output_dir="results/stage2_provisional/test-only")
    config = replace(base, steps=1_500, snapshot_steps=(), agent_state_interval=100)
    simulation = ColonySimulation(config)
    result = simulation.run()

    counts = result.metrics[["foragers", "transporters", "followers"]].sum(axis=1)
    assert np.all(counts.to_numpy() == config.n_ants)
    positions = result.final_agents[["x", "y"]].to_numpy(dtype=float)
    assert np.isfinite(positions).all()
    assert np.all(positions >= 0.0)
    assert np.all(positions <= config.arena_size)
    assert np.isfinite(result.metrics.select_dtypes(include=[float, int]).to_numpy()).all()


def test_simulations_do_not_share_internal_state() -> None:
    base = ColonyConfig.pilot(output_dir="results/stage2_provisional/test-only")
    config = replace(base, n_ants=2, steps=5, snapshot_steps=())
    first = ColonySimulation(config)
    second = ColonySimulation(config)

    first.field.deposit(np.array(config.nest.center), np.array([1.0, 0.0]))
    first.ants[0].travel_path.append(np.array([9.0, 9.0]))

    assert second.field.total_intensity == 0.0
    assert len(second.ants[0].travel_path) == 1
    assert not np.shares_memory(first.ants[0].position, second.ants[0].position)


def test_population_count_is_conserved_across_role_changes() -> None:
    config = deterministic_config(steps=8, n_ants=2)
    agents = [
        Ant(
            ant_id=0,
            position=np.array([2.8, 5.0]),
            heading=0.0,
            role=Role.FORAGER,
            travel_path=[np.array([1.0, 5.0]), np.array([2.8, 5.0])],
        ),
        Ant(
            ant_id=1,
            position=np.array([1.0, 6.0]),
            heading=np.pi / 2,
            role=Role.FORAGER,
            travel_path=[np.array([1.0, 5.0]), np.array([1.0, 6.0])],
        ),
    ]
    simulation = ColonySimulation(
        config,
        initial_agents=agents,
        turn_schedules=np.zeros((2, config.steps)),
    )
    result = simulation.run()
    assert np.all(
        result.metrics[["foragers", "transporters", "followers"]].sum(axis=1)
        == 2
    )
