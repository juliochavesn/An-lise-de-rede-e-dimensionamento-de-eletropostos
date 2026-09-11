import pytest
import pandas as pd

from src.config import SCENARIO_ANNUAL, SCENARIO_BASE
from src.profiles import generate_profiles


def test_daily_mode_preserves_15_minute_24_hour_structure():
    data = generate_profiles(**SCENARIO_BASE)
    assert len(data["time_index"]) == 96
    assert data["billing_periods"] == [1]
    assert data["demand_month_weights"][1] == pytest.approx(
        1.0 / (365.25 / 12.0)
    )


def test_annual_mode_builds_complete_non_leap_year():
    data = generate_profiles(**SCENARIO_ANNUAL)
    assert len(data["time_index"]) == 8760
    assert data["billing_periods"] == list(range(1, 13))
    assert all(
        weight == pytest.approx(1.0)
        for weight in data["demand_month_weights"].values()
    )


def test_annual_peak_tariff_is_not_applied_on_weekends():
    scenario = dict(SCENARIO_ANNUAL)
    scenario.update({"price_offpeak": 1.0, "price_peak": 2.0})
    data = generate_profiles(**scenario)

    # Verifica todos os dias do calendário configurado, sem supor o ano 2021.
    start = pd.Timestamp(scenario["calendar_start"])
    for day in range(int(scenario["horizon_h"] / 24)):
        timestamp = start + pd.Timedelta(days=day, hours=18)
        expected = 2.0 if timestamp.dayofweek < 5 else 1.0
        assert data["price_grid"][day * 24 + 18] == pytest.approx(expected)
