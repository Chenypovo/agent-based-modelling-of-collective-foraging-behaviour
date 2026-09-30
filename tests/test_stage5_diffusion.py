"""Stage 5 diffusing scalar field (proposal Eq. 1, explicit finite differences)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from scalar_baseline.config import DecayConfig
from scalar_baseline.field import ScalarField
from stage5_navigation.diffusion import DiffusingField


def test_zero_diffusion_matches_validated_field():
    decay = DecayConfig(half_life_steps=100)
    a, b = ScalarField(20, 1, decay), DiffusingField(20, 1, decay, diffusion=0.0)
    for t in range(1, 30):
        a.advance(t)
        b.advance(t)
        a.deposit((10.2, 10.7), 1.0)
        b.deposit((10.2, 10.7), 1.0)
    assert np.allclose(a.concentration, b.concentration, rtol=0, atol=1e-15)


def test_diffusion_spreads_symmetrically_and_conserves_mass_without_decay_or_edges():
    decay = DecayConfig(half_life_steps=1e12)
    field = DiffusingField(81, 1, decay, diffusion=0.2)
    field.deposit((40.5, 40.5), 1.0)
    for t in range(1, 51):
        field.advance(t)
    c = field.concentration
    assert math.isclose(c.sum(), 1.0, rel_tol=1e-6)
    assert np.allclose(c, c.T) and np.allclose(c, c[::-1, :])
    # Variance per axis grows as 2 D t for a random-walk kernel.
    x = np.arange(81) - 40
    var = float((c.sum(axis=1) * x ** 2).sum())
    assert var == pytest.approx(2 * 0.2 * 50, rel=0.02)


def test_decay_applies_on_top_of_diffusion():
    decay = DecayConfig(half_life_steps=10)
    field = DiffusingField(41, 1, decay, diffusion=0.1)
    field.deposit((20.5, 20.5), 1.0)
    for t in range(1, 11):
        field.advance(t)
    assert field.concentration.sum() == pytest.approx(0.5, rel=1e-6)


def test_unstable_or_negative_diffusion_rejected():
    decay = DecayConfig(half_life_steps=10)
    with pytest.raises(ValueError):
        DiffusingField(10, 1, decay, diffusion=0.3)
    with pytest.raises(ValueError):
        DiffusingField(10, 1, decay, diffusion=-0.1)
