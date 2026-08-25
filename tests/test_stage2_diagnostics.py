from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from colony.agents import Ant, Role
from colony.config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from colony.diagnostics import (
    DiagnosticSimulation,
    axial_angle_error,
    channel_width_90,
    mask_connects_sites,
    metric_validation_rows,
    path_efficiency,
    role_order_rows,
    sensing_per_follower_summary,
    top_fraction_intensity_share,
)
from colony.simulation import ColonySimulation


def diagnostic_config(*, steps: int = 4, n_ants: int = 2) -> ColonyConfig:
    return ColonyConfig(
        n_ants=n_ants,
        arena_size=10.0,
        steps=steps,
        seed=123,
        movement=MovementConfig(model="zw", step_size=0.6, theta_deg=0.0, gamma=0.1),
        pheromone=PheromoneConfig(cell_size=0.5, sensing_range=0.6),
        nest=SiteConfig((1.0, 5.0), 0.25),
        food=SiteConfig((8.0, 5.0), 0.25),
        snapshot_steps=(),
        agent_state_interval=1,
        output_dir="results/stage2_diagnostic/test-only",
    )


def initial_foragers(n_ants: int) -> list[Ant]:
    return [
        Ant(
            ant_id=ant_id,
            position=np.array([1.0, 4.0 + ant_id]),
            heading=0.0,
            role=Role.FORAGER,
        )
        for ant_id in range(n_ants)
    ]


def test_role_classification_statistics_are_separate_and_counted() -> None:
    ants = [
        Ant(0, np.array([0.0, 0.0]), 0.0, Role.FORAGER),
        Ant(1, np.array([0.0, 0.0]), np.pi, Role.FORAGER),
        Ant(2, np.array([0.0, 0.0]), np.pi / 4, Role.TRANSPORTER),
        Ant(3, np.array([0.0, 0.0]), -np.pi / 4, Role.FOLLOWER),
    ]
    order, _ = role_order_rows(ants, time=7, axis_angle=np.pi / 4, speed=0.6)
    by_role = {row["role"]: row for row in order}
    assert by_role["forager"]["sample_count"] == 2
    assert by_role["transporter"]["sample_count"] == 1
    assert by_role["follower"]["sample_count"] == 1
    assert float(by_role["forager"]["nematic_order_psi"]) == pytest.approx(1.0)


def test_bidirectional_alignment_is_not_misclassified_as_disorder() -> None:
    rows = {row["scenario"]: row for row in metric_validation_rows(np.pi / 4)}
    assert float(rows["fully_aligned"]["nematic_order_psi"]) == pytest.approx(1.0)
    assert float(rows["bidirectionally_aligned"]["nematic_order_psi"]) == pytest.approx(1.0)
    assert float(rows["uniform_direction_field"]["nematic_order_psi"]) == pytest.approx(
        2 / np.pi, abs=1e-8
    )


def test_axial_error_handles_plus_minus_pi_boundary() -> None:
    headings = np.array([-np.pi + 0.01, np.pi - 0.01, 0.01, np.pi + 0.01])
    errors = axial_angle_error(headings, axis_angle=0.0)
    np.testing.assert_allclose(errors, 0.01, atol=1e-12)


def test_top_fraction_concentration_share_is_exact() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    assert top_fraction_intensity_share(values, 0.25) == pytest.approx(0.4)
    assert top_fraction_intensity_share(values, 0.50) == pytest.approx(0.7)


def test_channel_width_uses_weighted_90_percent_full_width() -> None:
    points = np.array([[0.0, -1.0], [1.0, 1.0], [2.0, -1.0], [3.0, 1.0]])
    weights = np.ones(4)
    width = channel_width_90(points, weights, np.array([0.0, 0.0]), np.array([3.0, 0.0]))
    assert width == pytest.approx(2.0)


def test_artificial_continuous_channel_connects_sites() -> None:
    mask = np.eye(5, dtype=bool)
    assert mask_connects_sites(
        mask,
        cell_size=1.0,
        nest=(0.5, 0.5),
        food=(4.5, 4.5),
    )


def test_artificial_broken_channel_fails_connectivity() -> None:
    mask = np.eye(5, dtype=bool)
    mask[2, 2] = False
    assert not mask_connects_sites(
        mask,
        cell_size=1.0,
        nest=(0.5, 0.5),
        food=(4.5, 4.5),
    )


def test_sensing_hit_miss_and_consecutive_loss_summary() -> None:
    records = pd.DataFrame(
        {
            "ant_id": [0, 0, 0, 0, 1],
            "sensing_hit": [True, False, False, True, False],
            "consecutive_miss_length": [0, 1, 2, 0, 1],
            "candidate_cell_count": [2, 0, 0, 3, 0],
            "maximum_intensity_tie_count": [1, 0, 0, 2, 0],
            "no_signal_continued_heading": [False, True, True, False, True],
            "chosen_direction_food_error_deg": [5.0, np.nan, np.nan, 15.0, np.nan],
        }
    )
    summary = sensing_per_follower_summary(records).set_index("ant_id")
    assert int(summary.loc[0, "miss_count"]) == 2
    assert float(summary.loc[0, "miss_rate"]) == pytest.approx(0.5)
    assert int(summary.loc[0, "max_consecutive_miss_length"]) == 2
    assert int(summary.loc[0, "tie_step_count"]) == 1
    assert int(summary.loc[0, "no_signal_continue_count"]) == 2


def test_path_efficiency_is_direct_distance_over_travelled_distance() -> None:
    assert path_efficiency(3.0, 5.0) == pytest.approx(0.6)
    assert path_efficiency(0.0, 0.0) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        path_efficiency(-1.0, 2.0)


def test_diagnostic_instrumentation_does_not_request_random_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    config = diagnostic_config(steps=2, n_ants=1)
    agents = initial_foragers(1)
    schedules = np.zeros((1, config.steps))

    def fail_random(*args: object, **kwargs: object) -> object:
        raise AssertionError("diagnostic instrumentation requested a random number")

    monkeypatch.setattr(np.random, "default_rng", fail_random)
    monkeypatch.setattr(np.random, "SeedSequence", fail_random)
    simulation = DiagnosticSimulation(
        config,
        initial_agents=agents,
        turn_schedules=schedules,
    )
    simulation.run()


def test_fixed_dynamics_match_uninstrumented_stage2a_exactly() -> None:
    config = replace(diagnostic_config(steps=8, n_ants=2), agent_state_interval=1)
    agents = initial_foragers(2)
    schedules = np.zeros((2, config.steps))
    baseline = ColonySimulation(
        config,
        initial_agents=agents,
        turn_schedules=schedules,
    )
    observed = DiagnosticSimulation(
        config,
        initial_agents=agents,
        turn_schedules=schedules,
    )
    baseline_result = baseline.run()
    observed_result = observed.run()

    pd.testing.assert_frame_equal(baseline_result.metrics, observed_result.metrics, check_exact=True)
    pd.testing.assert_frame_equal(baseline_result.events, observed_result.events, check_exact=True)
    pd.testing.assert_frame_equal(
        baseline_result.final_agents, observed_result.final_agents, check_exact=True
    )
    np.testing.assert_array_equal(baseline.field.intensity, observed.field.intensity)
    np.testing.assert_array_equal(baseline.field.direction_sum, observed.field.direction_sum)
    assert baseline.transition_counts == observed.transition_counts
