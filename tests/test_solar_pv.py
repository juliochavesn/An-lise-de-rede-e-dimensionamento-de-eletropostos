import unittest
from unittest.mock import patch

import pandas as pd

from src.solar_pv import (
    PVSystemConfig,
    PVLocationConfig,
    get_weather_pvgis,
    build_annual_average_pv_cf_for_optimizer,
    build_pv_cf_for_optimizer,
    simulate_normalized_pv_profile,
)


def synthetic_weather():
    index = pd.date_range(
        "2021-01-01 00:00:00",
        periods=48,
        freq="1h",
        tz="America/Sao_Paulo",
    )
    hours = index.hour
    poa = pd.Series(0.0, index=index)
    daylight = (hours >= 6) & (hours <= 18)
    poa.loc[daylight] = 800.0

    return pd.DataFrame(
        {
            "poa_global": poa,
            "temp_air": 25.0,
            "wind_speed": 1.0,
        },
        index=index,
    )


class TestSolarPV(unittest.TestCase):
    def setUp(self):
        self.location = PVLocationConfig(-22.817, -47.069, 650.0, "America/Sao_Paulo")

    def test_config_calendar_matches_solar_reference(self):
        from src.config import PV_SYSTEM, SCENARIO_ANNUAL, PV_PROFILE_START_TIME
        self.assertEqual(PV_SYSTEM["year"], 2023)
        self.assertEqual(pd.Timestamp(SCENARIO_ANNUAL["calendar_start"]).year, PV_SYSTEM["year"])
        self.assertEqual(pd.Timestamp(PV_PROFILE_START_TIME).year, PV_SYSTEM["year"])
        self.assertEqual(SCENARIO_ANNUAL["horizon_h"], 8760)

    def annual_weather(self):
        return pd.DataFrame(
            {"poa_global": 0.0, "temp_air": 25.0, "wind_speed": 1.0},
            index=pd.date_range("2023-01-01 00:30", periods=8760, freq="h", tz="UTC"),
        )

    @patch("src.solar_pv.pvlib.iotools.get_pvgis_hourly")
    def test_pvgis_pins_version_year_and_records_provenance(self, query):
        query.return_value = (self.annual_weather(), {"inputs": {}})
        result = get_weather_pvgis(self.location, PVSystemConfig())
        self.assertEqual(query.call_args.kwargs["url"], "https://re.jrc.ec.europa.eu/api/v5_3/")
        self.assertEqual(query.call_args.kwargs["start"], 2023)
        self.assertEqual(query.call_args.kwargs["end"], 2023)
        self.assertEqual(query.call_args.kwargs["raddatabase"], "PVGIS-ERA5")
        self.assertTrue(result.attrs["solar_provenance"]["complete_hourly_year"])

    @patch("src.solar_pv.pvlib.iotools.get_pvgis_hourly")
    def test_pvgis_rejects_missing_or_wrong_hours(self, query):
        for weather in [self.annual_weather().iloc[:-1], self.annual_weather().set_axis(
                pd.date_range("2022-01-01", periods=8760, freq="h", tz="UTC"))]:
            query.return_value = (weather, {})
            with self.assertRaisesRegex(ValueError, "ano incompleto"):
                get_weather_pvgis(self.location, PVSystemConfig())

    @patch("src.solar_pv.pvlib.iotools.get_pvgis_hourly")
    def test_pvgis_rejects_missing_and_infinite_irradiance(self, query):
        for value in [float("nan"), float("inf")]:
            weather = self.annual_weather()
            weather.iloc[12, 0] = value
            query.return_value = (weather, {})
            with self.assertRaises(ValueError):
                get_weather_pvgis(self.location, PVSystemConfig())

    @patch("src.solar_pv.pvlib.iotools.get_pvgis_hourly")
    def test_pvgis_does_not_silently_fallback_year(self, query):
        with self.assertRaisesRegex(ValueError, "2005 a 2023"):
            get_weather_pvgis(self.location, PVSystemConfig(year=2024))
        query.assert_not_called()

    def test_ac_output_accounts_for_inverter_and_losses(self):
        config = PVSystemConfig(
            losses_percent=10.0,
            dc_ac_ratio=1.2,
            inverter_nominal_efficiency=0.96,
        )
        result = simulate_normalized_pv_profile(
            location_config=None,
            system_config=config,
            weather=synthetic_weather(),
        )

        daylight = result["pv_reference_dc_kw"] > 0.0
        self.assertTrue(
            (
                result.loc[daylight, "pv_reference_ac_kw"]
                < result.loc[daylight, "pv_reference_dc_kw"]
            ).all()
        )
        self.assertLessEqual(result["pv_cf"].max(), 1.0 / 1.2 + 1e-12)
        self.assertTrue((result["pv_cf"] >= 0.0).all())

    def test_specific_period_has_expected_resolution(self):
        result = simulate_normalized_pv_profile(
            location_config=None,
            system_config=PVSystemConfig(),
            weather=synthetic_weather(),
        )
        profile = build_pv_cf_for_optimizer(
            result,
            dt_h=0.25,
            horizon_h=24.0,
            start_time="2021-01-01 00:00:00",
        )

        self.assertEqual(len(profile), 96)
        self.assertEqual(profile[0], 0.0)
        self.assertGreater(profile[48], 0.0)

    def test_annual_average_has_expected_resolution(self):
        result = simulate_normalized_pv_profile(
            location_config=None,
            system_config=PVSystemConfig(),
            weather=synthetic_weather(),
        )
        profile = build_annual_average_pv_cf_for_optimizer(
            result,
            dt_h=0.25,
            horizon_h=24.0,
        )

        self.assertEqual(len(profile), 96)
        self.assertEqual(profile[0], 0.0)
        self.assertGreater(profile[48], 0.0)

    def test_invalid_horizon_is_rejected(self):
        result = simulate_normalized_pv_profile(
            location_config=None,
            system_config=PVSystemConfig(),
            weather=synthetic_weather(),
        )
        with self.assertRaises(ValueError):
            build_pv_cf_for_optimizer(
                result,
                dt_h=0.3,
                horizon_h=1.0,
            )


if __name__ == "__main__":
    unittest.main()
