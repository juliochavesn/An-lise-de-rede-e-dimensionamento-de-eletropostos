import unittest

from main import (
    build_grid_sensitivity_limits,
    diagnose_local_grid_adequacy,
)


class TestGridSensitivity(unittest.TestCase):
    def test_relative_limits_are_anchored_on_base(self):
        limits = build_grid_sensitivity_limits(
            100.0,
            {
                "mode": "relative",
                "factors": [0.5, 0.8, 1.2, 2.0],
                "rounding_kw": 10.0,
                "include_base_limit": True,
            },
        )
        self.assertEqual(limits, [50.0, 80.0, 100.0, 120.0, 200.0])

    def test_manual_mode_always_includes_base(self):
        limits = build_grid_sensitivity_limits(
            500.0,
            {
                "mode": "manual",
                "values_kw": [300.0, 700.0],
                "include_base_limit": True,
            },
        )
        self.assertEqual(limits, [300.0, 500.0, 700.0])

    def test_range_mode_includes_upper_bound_and_base(self):
        limits = build_grid_sensitivity_limits(
            500.0,
            {
                "mode": "range",
                "minimum_kw": 300.0,
                "maximum_kw": 750.0,
                "step_kw": 200.0,
                "include_base_limit": True,
            },
        )
        self.assertEqual(limits, [300.0, 500.0, 700.0, 750.0])

    def test_local_grid_diagnostic(self):
        diagnostic = diagnose_local_grid_adequacy(
            {
                "dt_h": 0.25,
                "time_index": [0, 1, 2],
                "local_load_kw": {0: 70.0, 1: 90.0, 2: 100.0},
                "grid_limit_kw": {0: 80.0, 1: 80.0, 2: 80.0},
            }
        )
        self.assertFalse(diagnostic["grid_alone_serves_local_load"])
        self.assertEqual(diagnostic["local_peak_kw"], 100.0)
        self.assertEqual(diagnostic["local_grid_gap_peak_kw"], 20.0)
        self.assertEqual(diagnostic["local_grid_gap_energy_kwh"], 7.5)
        self.assertEqual(diagnostic["local_grid_gap_intervals"], 2)


if __name__ == "__main__":
    unittest.main()
