import numpy as np
import pytest

from src.grid_residual_capacity import (
    calculate_residual_capacity,
    scale_profile_to_energy,
)


def test_profile_scaling_reproduces_target_energy():
    result = scale_profile_to_energy([1.0, 2.0, 1.0, 0.0], 20.0, 0.5)
    assert result.sum() * 0.5 == pytest.approx(20.0)


def test_flat_fallback_reproduces_energy_when_shape_is_zero():
    result = scale_profile_to_energy([0.0, 0.0], 10.0, 1.0)
    np.testing.assert_allclose(result, [5.0, 5.0])


def test_residual_capacity_applies_safety_and_generation_credit():
    result = calculate_residual_capacity(
        100.0,
        np.array([50.0, 90.0]),
        np.array([20.0, 20.0]),
        load_safety_factor=1.10,
        generation_credit_fraction=0.50,
    )
    np.testing.assert_allclose(result, [55.0, 11.0])


def test_residual_capacity_is_never_negative():
    result = calculate_residual_capacity(
        100.0,
        np.array([120.0]),
        np.array([0.0]),
        load_safety_factor=1.10,
        generation_credit_fraction=0.0,
    )
    np.testing.assert_allclose(result, [0.0])
