"""Discrete SRW, FCRW, and provisional ZW trajectory generators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

ModelName = Literal["srw", "fcrw", "zw"]


@dataclass(frozen=True)
class Trajectory:
    """One simulated single-ant trajectory.

    ``positions`` contains the initial vertex followed by one vertex per
    movement step. The remaining arrays contain one entry per movement step.
    ``selected_probabilities`` stores the probability of the sign that was
    actually selected on each realised branch. ``repeat_probabilities[i]`` is
    the probability used to decide whether sign ``i`` repeats sign ``i-1``;
    its first value is NaN because there is no previous sign.
    """

    model: ModelName
    positions: NDArray[np.float64]
    headings: NDArray[np.float64]
    turn_angles: NDArray[np.float64]
    turn_signs: NDArray[np.int8]
    selected_probabilities: NDArray[np.float64]
    repeat_probabilities: NDArray[np.float64]
    step_size: float
    theta_max: float
    gamma: float


def _validate_inputs(
    model: str,
    steps: int,
    step_size: float,
    theta_max: float,
    gamma: float,
) -> ModelName:
    normalised_model = model.lower()
    if normalised_model not in {"srw", "fcrw", "zw"}:
        raise ValueError(f"Unknown model {model!r}; choose srw, fcrw, or zw")
    if isinstance(steps, bool) or not isinstance(steps, (int, np.integer)) or steps < 1:
        raise ValueError("steps must be a positive integer")
    if not np.isfinite(step_size) or step_size <= 0:
        raise ValueError("step_size must be finite and positive")
    if not np.isfinite(theta_max) or not 0 <= theta_max <= np.pi:
        raise ValueError("theta_max must be between 0 and pi radians")
    if not np.isfinite(gamma) or not 0 <= gamma <= 0.5:
        raise ValueError("gamma must be between 0 and 0.5")
    return normalised_model  # type: ignore[return-value]


def zigzag_repeat_probability(selected_probability: float, gamma: float) -> float:
    """Return the ZW probability of repeating the current realised sign.

    This is the provisional branch-conditional reading of Zhang & Yong (2023),
    equations (5)--(7), supported by the probability tree in Fig. 1(d).
    """

    if not np.isfinite(selected_probability) or not 0 <= selected_probability <= 1:
        raise ValueError("selected_probability must be between 0 and 1")
    if not np.isfinite(gamma) or not 0 <= gamma <= 0.5:
        raise ValueError("gamma must be between 0 and 0.5")
    if selected_probability >= 0.5:
        return float(gamma)
    return float(gamma * selected_probability)


def _srw_signs(
    steps: int, rng: np.random.Generator
) -> tuple[NDArray[np.int8], NDArray[np.float64], NDArray[np.float64]]:
    signs = np.where(rng.random(steps) < 0.5, 1, -1).astype(np.int8)
    selected = np.full(steps, 0.5, dtype=float)
    repeats = np.full(steps, 0.5, dtype=float)
    repeats[0] = np.nan
    return signs, selected, repeats


def _fcrw_signs(
    steps: int, gamma: float, rng: np.random.Generator
) -> tuple[NDArray[np.int8], NDArray[np.float64], NDArray[np.float64]]:
    signs = np.empty(steps, dtype=np.int8)
    selected = np.empty(steps, dtype=float)
    repeats = np.full(steps, gamma, dtype=float)

    signs[0] = 1 if rng.random() < 0.5 else -1
    selected[0] = 0.5
    repeats[0] = np.nan
    for i in range(1, steps):
        if rng.random() < gamma:
            signs[i] = signs[i - 1]
            selected[i] = gamma
        else:
            signs[i] = -signs[i - 1]
            selected[i] = 1.0 - gamma
    return signs, selected, repeats


def _zw_signs(
    steps: int, gamma: float, rng: np.random.Generator
) -> tuple[NDArray[np.int8], NDArray[np.float64], NDArray[np.float64]]:
    signs = np.empty(steps, dtype=np.int8)
    selected = np.empty(steps, dtype=float)
    repeats = np.empty(steps, dtype=float)

    signs[0] = 1 if rng.random() < 0.5 else -1
    selected[0] = 0.5
    repeats[0] = np.nan

    for i in range(1, steps):
        p_same = zigzag_repeat_probability(selected[i - 1], gamma)
        repeats[i] = p_same
        if rng.random() < p_same:
            signs[i] = signs[i - 1]
            selected[i] = p_same
        else:
            signs[i] = -signs[i - 1]
            selected[i] = 1.0 - p_same
    return signs, selected, repeats


def generate_trajectory(
    model: ModelName | str,
    *,
    steps: int,
    step_size: float = 0.6,
    theta_max: float = np.pi / 3,
    gamma: float = 0.2,
    seed: int | None = None,
    rng: np.random.Generator | None = None,
) -> Trajectory:
    """Generate one fixed-step 2D trajectory.

    Angles use radians. Supply either ``seed`` or an explicit NumPy generator,
    not both. No random generator or model state is stored globally.
    """

    normalised_model = _validate_inputs(model, steps, step_size, theta_max, gamma)
    if seed is not None and rng is not None:
        raise ValueError("provide either seed or rng, not both")
    local_rng = np.random.default_rng(seed) if rng is None else rng

    if normalised_model == "srw":
        signs, selected, repeats = _srw_signs(steps, local_rng)
    elif normalised_model == "fcrw":
        signs, selected, repeats = _fcrw_signs(steps, gamma, local_rng)
    else:
        signs, selected, repeats = _zw_signs(steps, gamma, local_rng)

    magnitudes = local_rng.uniform(0.0, theta_max, size=steps)
    turn_angles = signs.astype(float) * magnitudes
    headings = np.cumsum(turn_angles)
    increments = step_size * np.column_stack((np.cos(headings), np.sin(headings)))
    positions = np.vstack((np.zeros((1, 2), dtype=float), np.cumsum(increments, axis=0)))

    return Trajectory(
        model=normalised_model,
        positions=positions,
        headings=headings,
        turn_angles=turn_angles,
        turn_signs=signs,
        selected_probabilities=selected,
        repeat_probabilities=repeats,
        step_size=float(step_size),
        theta_max=float(theta_max),
        gamma=float(gamma),
    )

