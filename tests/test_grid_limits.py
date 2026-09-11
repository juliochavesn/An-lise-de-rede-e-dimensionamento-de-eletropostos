import unittest

import numpy as np

from src.config import GRID_NETWORK
from src.grid_bdgd import combine_grid_limits, build_network_aware_tariff, bdgd_reference_date
from src.profiles import generate_profiles


class GridLimitTests(unittest.TestCase):
    def test_bdgd_reference_date_is_not_the_solar_year(self):
        self.assertEqual(bdgd_reference_date({
            "bdgd_path": "/tmp/CPFL_63_2025-12-31_V11_x.gdb.zip",
            "bdgd_reference_date": "2025-12-31",
        }), "2025-12-31")

    def test_bdgd_is_default_and_manual_fallback_is_preserved(self):
        self.assertEqual(GRID_NETWORK["limit_source"], "bdgd")
        self.assertEqual(GRID_NETWORK["capacity_method"], "residual")
        self.assertEqual(GRID_NETWORK["on_error"], "manual")

    def test_manual_mode_preserves_legacy_limit(self):
        result = combine_grid_limits(250.0, 100.0, "manual", 4)
        np.testing.assert_allclose(result, [100.0] * 4)

    def test_bdgd_mode_uses_network_limit(self):
        result = combine_grid_limits(250.0, 100.0, "bdgd", 4)
        np.testing.assert_allclose(result, [250.0] * 4)

    def test_minimum_mode_honors_customer_or_utility_cap(self):
        result = combine_grid_limits(250.0, 100.0, "minimum", 4)
        np.testing.assert_allclose(result, [100.0] * 4)

    def test_minimum_mode_honors_network_when_more_restrictive(self):
        result = combine_grid_limits(80.0, 100.0, "minimum", 4)
        np.testing.assert_allclose(result, [80.0] * 4)

    def test_external_profile_reaches_optimizer_input(self):
        values = {index: 50.0 + index for index in range(4)}
        data = generate_profiles(
            horizon_h=1.0,
            dt_h=0.25,
            grid_limit_external=values,
            pv_cf_external={index: 0.0 for index in range(4)},
        )
        self.assertEqual(data["grid_limit_kw"], values)

    def test_bdgd_removes_manual_contracted_demand_ceiling(self):
        tariff = {
            "contracted_demand_min_kw": 0.0,
            "contracted_demand_max_kw": 100.0,
        }
        result = build_network_aware_tariff(
            tariff,
            {0: 250.0, 1: 230.0},
            {"limit_source": "bdgd"},
        )
        self.assertEqual(result["contracted_demand_max_kw"], 250.0)
        self.assertEqual(tariff["contracted_demand_max_kw"], 100.0)

    def test_manual_keeps_user_contracted_demand_ceiling(self):
        tariff = {
            "contracted_demand_min_kw": 0.0,
            "contracted_demand_max_kw": 100.0,
        }
        result = build_network_aware_tariff(
            tariff,
            {0: 250.0},
            {"limit_source": "manual"},
        )
        self.assertEqual(result["contracted_demand_max_kw"], 100.0)

    def test_minimum_keeps_user_contracted_demand_ceiling(self):
        tariff = {
            "contracted_demand_min_kw": 0.0,
            "contracted_demand_max_kw": 100.0,
        }
        result = build_network_aware_tariff(
            tariff,
            {0: 80.0},
            {"limit_source": "minimum"},
        )
        self.assertEqual(result["contracted_demand_max_kw"], 100.0)

    def test_bdgd_profile_can_vary_by_interval(self):
        result = combine_grid_limits(
            np.array([250.0, 180.0, 220.0]), 100.0, "bdgd", 3
        )
        np.testing.assert_allclose(result, [250.0, 180.0, 220.0])


if __name__ == "__main__":
    unittest.main()
