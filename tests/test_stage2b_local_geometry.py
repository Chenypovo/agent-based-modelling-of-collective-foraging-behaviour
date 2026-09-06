from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from colony.agents import Ant, Role
from colony.config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from colony.simulation import ColonySimulation
from colony.stage2b_audit import protected_sha256_manifest, single_change_audit
from colony.trail_direction import local_weighted_pca_tangent

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _axial_difference(left: float, right: float) -> float:
    difference = left - right
    return float(abs(0.5 * np.arctan2(np.sin(2.0 * difference), np.cos(2.0 * difference))))


def _local_config(*, steps: int = 2, n_ants: int = 1) -> ColonyConfig:
    return ColonyConfig(
        n_ants=n_ants,
        arena_size=10.0,
        steps=steps,
        seed=123,
        movement=MovementConfig(model="zw", step_size=0.6, theta_deg=0.0, gamma=0.1),
        pheromone=PheromoneConfig(cell_size=0.6, sensing_range=0.6),
        nest=SiteConfig((1.0, 1.0), 0.25),
        food=SiteConfig((8.0, 8.0), 0.25),
        follower_direction_rule="local_weighted_pca_tangent",
        snapshot_steps=(),
        agent_state_interval=1,
        output_dir="results/stage2b_local_geometry/test-only",
    )


def test_horizontal_cells_produce_horizontal_tangent() -> None:
    heading = local_weighted_pca_tangent(
        np.array([[0.0, 2.0], [1.0, 2.0], [2.0, 2.0]]),
        np.ones(3),
        0.1,
    )
    assert _axial_difference(heading, 0.0) == pytest.approx(0.0, abs=1e-12)


def test_diagonal_cells_produce_pi_over_four_tangent() -> None:
    heading = local_weighted_pca_tangent(
        np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]),
        np.ones(3),
        np.pi / 4,
    )
    assert _axial_difference(heading, np.pi / 4) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize(
    ("current_heading", "expected"),
    [(0.2, 0.0), (np.pi - 0.2, np.pi)],
)
def test_tangent_sign_follows_current_heading(current_heading: float, expected: float) -> None:
    inferred = local_weighted_pca_tangent(
        np.array([[-1.0, 0.0], [0.0, 0.0], [1.0, 0.0]]),
        np.ones(3),
        current_heading,
    )
    assert abs(np.arctan2(np.sin(inferred - expected), np.cos(inferred - expected))) < 1e-12


def test_opposite_tangent_directions_are_one_axis() -> None:
    centers = np.array([[-1.0, 0.0], [0.0, 0.0], [1.0, 0.0]])
    forward = local_weighted_pca_tangent(centers, np.ones(3), 0.1)
    reverse = local_weighted_pca_tangent(centers, np.ones(3), np.pi - 0.1)
    assert _axial_difference(forward, reverse) == pytest.approx(0.0, abs=1e-12)


def test_concentration_weights_change_the_principal_axis() -> None:
    centers = np.array([[-2.0, 0.0], [2.0, 0.0], [0.0, -1.0], [0.0, 1.0]])
    horizontal = local_weighted_pca_tangent(centers, np.ones(4), 0.1)
    vertical = local_weighted_pca_tangent(centers, np.array([1.0, 1.0, 10.0, 10.0]), 1.4)
    assert _axial_difference(horizontal, 0.0) == pytest.approx(0.0, abs=1e-12)
    assert _axial_difference(vertical, np.pi / 2) == pytest.approx(0.0, abs=1e-12)


def test_single_cell_preserves_current_heading() -> None:
    current = -0.73
    inferred = local_weighted_pca_tangent(np.array([[2.0, 3.0]]), np.array([4.0]), current)
    assert inferred == pytest.approx(current)


def test_non_unique_covariance_preserves_current_heading() -> None:
    current = 0.37
    inferred = local_weighted_pca_tangent(
        np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, -1.0], [0.0, 1.0]]),
        np.ones(4),
        current,
    )
    assert inferred == pytest.approx(current)


def test_pca_inference_has_no_food_or_nest_input() -> None:
    signature = inspect.signature(local_weighted_pca_tangent)
    assert tuple(signature.parameters) == ("cell_centers", "concentrations", "current_heading")
    source = inspect.getsource(local_weighted_pca_tangent)
    assert "food" not in source
    assert "nest" not in source


def test_local_rule_does_not_read_stored_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _local_config()
    ant = Ant(0, np.array([5.1, 5.1]), 0.0, Role.FOLLOWER, travel_path=[np.array([5.1, 5.1])])
    simulation = ColonySimulation(
        config,
        initial_agents=[ant],
        turn_schedules=np.zeros((1, config.steps)),
    )
    simulation.field.intensity[8, 8] = 1.0
    simulation.field.intensity[9, 8] = 2.0

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("stored pheromone direction was read")

    monkeypatch.setattr(simulation.field, "sense", fail)
    monkeypatch.setattr(simulation.field, "_direction", fail)
    simulation._move_follower(simulation.ants[0])
    assert simulation.ants[0].position[0] > 5.1


def test_pca_inference_does_not_call_random_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("PCA inference requested a random number")

    monkeypatch.setattr(np.random, "default_rng", fail)
    monkeypatch.setattr(np.random, "random", fail)
    inferred = local_weighted_pca_tangent(
        np.array([[0.0, 0.0], [1.0, 0.0]]), np.array([1.0, 2.0]), 0.1
    )
    assert np.isfinite(inferred)


def test_default_baseline_rule_behavior_is_unchanged() -> None:
    config = replace(
        _local_config(steps=1),
        follower_direction_rule="stored_cell_direction",
    )
    assert ColonyConfig().follower_direction_rule == "stored_cell_direction"
    ant = Ant(0, np.array([5.1, 5.1]), 0.0, Role.FOLLOWER, travel_path=[np.array([5.1, 5.1])])
    simulation = ColonySimulation(
        config,
        initial_agents=[ant],
        turn_schedules=np.zeros((1, config.steps)),
    )
    simulation.field.deposit(np.array([5.1, 5.1]), np.array([0.0, 1.0]))
    simulation._move_follower(simulation.ants[0])
    np.testing.assert_allclose(simulation.ants[0].position, [5.1, 5.7], atol=1e-12)


def test_local_rule_fixed_seed_is_reproducible() -> None:
    base = ColonyConfig.pilot(output_dir="results/stage2b_local_geometry/test-only")
    config = replace(
        base,
        n_ants=4,
        steps=200,
        snapshot_steps=(),
        agent_state_interval=20,
        follower_direction_rule="local_weighted_pca_tangent",
    )
    first = ColonySimulation(config).run()
    second = ColonySimulation(config).run()
    np.testing.assert_array_equal(first.metrics.to_numpy(), second.metrics.to_numpy())
    np.testing.assert_array_equal(first.final_agents.to_numpy(), second.final_agents.to_numpy())


def test_local_rule_preserves_population_bounds_and_finite_state() -> None:
    base = ColonyConfig.pilot(output_dir="results/stage2b_local_geometry/test-only")
    config = replace(
        base,
        steps=1_500,
        snapshot_steps=(),
        agent_state_interval=100,
        follower_direction_rule="local_weighted_pca_tangent",
    )
    simulation = ColonySimulation(config)
    result = simulation.run()
    assert np.all(result.metrics[["foragers", "transporters", "followers"]].sum(axis=1) == 10)
    positions = result.final_agents[["x", "y"]].to_numpy(dtype=float)
    assert np.isfinite(positions).all()
    assert np.all(positions >= 0.0)
    assert np.all(positions <= config.arena_size)
    assert np.isfinite(result.metrics.select_dtypes(include=[float, int]).to_numpy()).all()


def test_protected_hash_manifest_covers_frozen_scope() -> None:
    manifest = protected_sha256_manifest(PROJECT_ROOT)
    files = manifest["files"]
    assert isinstance(files, dict)
    assert "results/stage1/REPORT.md" in files
    assert "results/stage2_provisional/metrics.csv" in files
    assert "results/stage2_diagnostic/sensing_diagnostics.csv" in files
    assert "docs/STAGE1_SPEC.md" in files
    assert "docs/STAGE2_SPEC.md" in files
    assert "Project Proposal.pdf" in files
    assert "_PH6780 Templates.docx" in files
    assert "_AY2627_T1_Briefing_updated.pdf" in files
    assert "references.bib" in files


def test_only_follower_direction_rule_differs_from_baseline_config() -> None:
    baseline = json.loads(
        (PROJECT_ROOT / "results/stage2_provisional/config.json").read_text(encoding="utf-8")
    )
    stage2b = ColonyConfig.paper_scale(
        output_dir="results/stage2b_local_geometry"
    ).to_dict()
    stage2b["follower_direction_rule"] = "local_weighted_pca_tangent"
    audit = single_change_audit(baseline, stage2b)
    assert audit["only_follower_direction_rule_changed"] is True
    assert audit["difference_count"] == 1
