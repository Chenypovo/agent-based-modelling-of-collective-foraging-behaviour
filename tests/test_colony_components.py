from __future__ import annotations

import numpy as np
import pytest

from colony.agents import Ant, Role, coarse_grain_path
from colony.config import ColonyConfig, MovementConfig, PheromoneConfig, SiteConfig
from colony.environment import SquareEnvironment
from colony.metrics import compute_order_parameters
from colony.pheromone import PheromoneField
from colony.transitions import ALLOWED_TRANSITIONS, transition_role


def test_reflection_keeps_position_inside_and_flips_heading() -> None:
    environment = SquareEnvironment(side_length=10.0)
    position, heading = environment.reflect_move(
        np.array([9.8, 5.0]), heading=0.0, distance=0.6
    )

    np.testing.assert_allclose(position, [9.6, 5.0], atol=1e-12)
    assert np.cos(heading) == pytest.approx(-1.0)
    assert environment.contains(position)


def test_unobstructed_move_uses_the_configured_step_length() -> None:
    environment = SquareEnvironment(side_length=10.0)
    start = np.array([5.0, 5.0])
    end, _ = environment.reflect_move(start, heading=0.37, distance=0.6)
    assert np.linalg.norm(end - start) == pytest.approx(0.6)


def test_provisional_memory_rule_keeps_every_third_vertex_and_final_vertex() -> None:
    path = [np.array([float(i), 0.0]) for i in range(8)]
    retained = coarse_grain_path(path, stride=3)
    np.testing.assert_array_equal(retained[:, 0], [0.0, 3.0, 6.0, 7.0])


@pytest.mark.parametrize(
    ("headings", "expected_phi"),
    [
        (np.array([0.0, np.pi]), 0.0),
        (np.array([np.pi / 4, 5 * np.pi / 4]), np.pi / 4),
    ],
)
def test_order_parameters_equal_one_for_known_nematic_alignment(
    headings: np.ndarray, expected_phi: float
) -> None:
    phi, psi = compute_order_parameters(headings)
    assert phi == pytest.approx(expected_phi)
    assert psi == pytest.approx(1.0)


def test_uniform_folded_orientations_have_paper_disordered_limit() -> None:
    headings = np.linspace(-np.pi / 2, np.pi / 2, 200_000, endpoint=False)
    phi, psi = compute_order_parameters(headings)
    assert phi == pytest.approx(0.0, abs=1e-5)
    assert psi == pytest.approx(2 / np.pi, abs=1e-5)


def test_pheromone_does_not_spontaneously_decrease_without_decay() -> None:
    field = PheromoneField(
        side_length=10.0,
        config=PheromoneConfig(cell_size=0.5, sensing_range=0.6),
        food_position=np.array([8.0, 8.0]),
    )
    field.deposit(np.array([2.0, 2.0]), np.array([1.0, 0.0]))
    field.deposit(np.array([2.0, 2.0]), np.array([1.0, 0.0]))
    before = field.total_intensity
    field.advance_time()
    assert before == pytest.approx(2.0)
    assert field.total_intensity == pytest.approx(before)


def test_pheromone_tie_break_is_deterministic() -> None:
    config = PheromoneConfig(cell_size=0.5, sensing_range=1.0)
    field = PheromoneField(10.0, config, food_position=np.array([8.0, 5.0]))
    field.deposit(np.array([4.25, 4.75]), np.array([1.0, 0.0]))
    field.deposit(np.array([4.25, 5.25]), np.array([0.0, 1.0]))
    signal = field.sense(np.array([4.25, 5.0]))
    assert signal is not None
    np.testing.assert_allclose(signal.direction, [1.0, 0.0])


def test_only_paper_role_transitions_are_allowed() -> None:
    expected = {
        (Role.FORAGER, Role.TRANSPORTER),
        (Role.FORAGER, Role.FOLLOWER),
        (Role.TRANSPORTER, Role.FOLLOWER),
        (Role.FOLLOWER, Role.TRANSPORTER),
    }
    assert ALLOWED_TRANSITIONS == expected

    ant = Ant(0, np.array([1.0, 1.0]), 0.0, Role.TRANSPORTER)
    with pytest.raises(ValueError, match="not allowed"):
        transition_role(ant, Role.FORAGER, reason="invalid", time=1)


def test_decay_and_diffusion_are_rejected_in_stage2a_config() -> None:
    with pytest.raises(ValueError, match="decay"):
        PheromoneConfig(decay_rate=0.01)
    with pytest.raises(ValueError, match="diffusion"):
        PheromoneConfig(diffusion_rate=0.01)


def test_config_rejects_sites_outside_the_arena() -> None:
    with pytest.raises(ValueError, match="food"):
        ColonyConfig(
            n_ants=1,
            arena_size=10.0,
            steps=10,
            movement=MovementConfig(),
            pheromone=PheromoneConfig(),
            nest=SiteConfig((2.0, 2.0), 0.5),
            food=SiteConfig((12.0, 2.0), 0.5),
        )
