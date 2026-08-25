from __future__ import annotations

import numpy as np
import pytest

from ant_walks.models import generate_trajectory, zigzag_repeat_probability


@pytest.mark.parametrize("model", ["srw", "fcrw", "zw"])
def test_random_seed_is_reproducible(model: str) -> None:
    first = generate_trajectory(model, steps=500, seed=12345)
    second = generate_trajectory(model, steps=500, seed=12345)

    np.testing.assert_array_equal(first.turn_signs, second.turn_signs)
    np.testing.assert_array_equal(first.turn_angles, second.turn_angles)
    np.testing.assert_array_equal(first.positions, second.positions)
    np.testing.assert_array_equal(first.selected_probabilities, second.selected_probabilities)


@pytest.mark.parametrize("model", ["srw", "fcrw", "zw"])
def test_every_step_has_fixed_length(model: str) -> None:
    step_size = 0.37
    trajectory = generate_trajectory(model, steps=1_000, step_size=step_size, seed=72)
    measured = np.linalg.norm(np.diff(trajectory.positions, axis=0), axis=1)
    np.testing.assert_allclose(measured, step_size, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("model", ["srw", "fcrw", "zw"])
def test_turn_angles_do_not_exceed_theta(model: str) -> None:
    theta_max = np.deg2rad(47.0)
    trajectory = generate_trajectory(model, steps=10_000, theta_max=theta_max, seed=9)
    assert np.all(np.abs(trajectory.turn_angles) <= theta_max)
    assert np.all(np.abs(trajectory.turn_angles) >= 0.0)


def test_srw_left_right_balance_is_close_to_one_half() -> None:
    trajectory = generate_trajectory("srw", steps=200_000, seed=2023)
    positive_fraction = np.mean(trajectory.turn_signs == 1)
    assert positive_fraction == pytest.approx(0.5, abs=0.005)


def test_fcrw_same_direction_fraction_is_close_to_gamma() -> None:
    gamma = 0.2
    trajectory = generate_trajectory("fcrw", steps=200_000, gamma=gamma, seed=108)
    same_fraction = np.mean(trajectory.turn_signs[1:] == trajectory.turn_signs[:-1])
    assert same_fraction == pytest.approx(gamma, abs=0.005)


def test_zw_probability_update_matches_selected_paper_interpretation() -> None:
    gamma = 0.2
    assert zigzag_repeat_probability(0.5, gamma) == pytest.approx(gamma)
    assert zigzag_repeat_probability(0.8, gamma) == pytest.approx(gamma)
    assert zigzag_repeat_probability(0.2, gamma) == pytest.approx(gamma * 0.2)

    trajectory = generate_trajectory("zw", steps=5_000, gamma=gamma, seed=54_306)
    for i in range(1, len(trajectory.turn_signs)):
        expected_repeat = zigzag_repeat_probability(
            trajectory.selected_probabilities[i - 1], gamma
        )
        assert trajectory.repeat_probabilities[i] == pytest.approx(expected_repeat)
        repeated = trajectory.turn_signs[i] == trajectory.turn_signs[i - 1]
        expected_selected = expected_repeat if repeated else 1.0 - expected_repeat
        assert trajectory.selected_probabilities[i] == pytest.approx(expected_selected)


def test_models_do_not_share_internal_state() -> None:
    baseline = generate_trajectory("fcrw", steps=2_000, gamma=0.2, seed=481)
    zw = generate_trajectory("zw", steps=2_000, gamma=0.2, seed=481)
    after_other_model = generate_trajectory("fcrw", steps=2_000, gamma=0.2, seed=481)

    np.testing.assert_array_equal(baseline.turn_signs, after_other_model.turn_signs)
    np.testing.assert_array_equal(baseline.positions, after_other_model.positions)
    assert not np.shares_memory(baseline.turn_signs, after_other_model.turn_signs)
    assert not np.shares_memory(baseline.turn_signs, zw.turn_signs)

