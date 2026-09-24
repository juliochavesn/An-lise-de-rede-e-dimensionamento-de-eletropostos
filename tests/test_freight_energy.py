import math

from src.freight_energy import (
    FreightAssumptions,
    estimate_freight_charging,
    normalized_freight_profile,
)


def test_hourly_profile_is_normalized():
    profile = normalized_freight_profile()
    assert len(profile) == 24
    assert all(value >= 0 for value in profile)
    assert math.isclose(sum(profile), 1.0, rel_tol=1e-12)


def test_conversion_keeps_physical_trips_separate_from_traffic_equivalence():
    assumptions = FreightAssumptions(
        payload_t=25,
        empty_returns_per_loaded_trip=0.5,
        electric_share=0.2,
        station_capture_share=0.25,
        energy_per_stop_kwh=200,
        operating_days_per_year=100,
    )
    result = estimate_freight_charging(100_000, assumptions)["scenarios"]["P50"]
    assert result["loaded_trips_per_year"] == 4_000
    assert result["physical_trips_per_day"] == 60
    assert result["electric_trucks_per_day"] == 12
    assert result["charging_events_per_day"] == 3
    assert result["daily_energy_kwh"] == 600
    assert math.isclose(sum(result["hourly_profile_kw"]), 600, rel_tol=1e-12)


def test_uncertainty_scenarios_are_ordered():
    scenarios = estimate_freight_charging(1_000_000)["scenarios"]
    assert scenarios["P10"]["daily_energy_kwh"] < scenarios["P50"]["daily_energy_kwh"]
    assert scenarios["P50"]["daily_energy_kwh"] < scenarios["P90"]["daily_energy_kwh"]


def test_zero_flow_produces_zero_demand():
    scenarios = estimate_freight_charging(0)["scenarios"]
    assert all(value["daily_energy_kwh"] == 0 for value in scenarios.values())
