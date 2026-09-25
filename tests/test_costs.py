import pytest

from src.dat_writer import (
    build_ampl_cost_parameters,
    build_tariff_parameters,
    capital_recovery_factor,
)


def test_capital_recovery_factor_at_eight_percent():
    assert capital_recovery_factor(0.08, 25) == pytest.approx(
        0.0936787791
    )
    assert capital_recovery_factor(0.08, 10) == pytest.approx(
        0.1490294887
    )


def test_zero_discount_rate_uses_straight_line_recovery():
    assert capital_recovery_factor(0.0, 20) == pytest.approx(0.05)


def test_cost_parameters_convert_24_hours_to_one_day_of_year():
    costs = {
        "charger_capex_per_kw": 1800.0,
        "charger_fixed_om_per_kw_year": 36.0,
        "charger_economic_lifetime_years": 10.0,
        "pv_capex_per_kwp": 3500.0,
        "pv_fixed_om_per_kwp_year": 60.0,
        "pv_economic_lifetime_years": 25.0,
        "bess_energy_capex_per_kwh": 1225.0,
        "bess_power_capex_per_kw": 600.0,
        "bess_fixed_om_per_kw_year": 140.0,
        "bess_economic_lifetime_years": 10.0,
        "bess_equivalent_full_cycles": 6000.0,
        "bess_usable_depth_fraction": 0.80,
        "bess_replacement_cost_fraction": 0.65,
        "real_discount_rate": 0.08,
        "curtailment_penalty": 0.0,
        "final_unserved_penalty": 5.0,
        "backlog_penalty": 4.0,
    }

    params = build_ampl_cost_parameters(costs, horizon_h=24.0)

    assert params["horizon_weight_years"] == pytest.approx(1.0 / 365.0)
    assert params["charger_capital_recovery_factor"] == pytest.approx(
        capital_recovery_factor(0.08, 10)
    )
    assert params["pv_capital_recovery_factor"] == pytest.approx(
        capital_recovery_factor(0.08, 25)
    )
    assert params["bess_capital_recovery_factor"] == pytest.approx(
        capital_recovery_factor(0.08, 10)
    )
    assert params["bess_degradation_cost_per_kwh_throughput"] == (
        pytest.approx(1225.0 * 0.65 / (2.0 * 6000.0 * 0.80))
    )


def test_tariff_parameters_include_taxes_and_relative_month_weight():
    tariff = {
        "energy_offpeak_before_tax_brl_per_kwh": 0.43698,
        "energy_peak_before_tax_brl_per_kwh": 1.78345,
        "demand_before_tax_brl_per_kw_month": 16.53,
        "icms_fraction": 0.18,
        "pis_fraction": 0.0063,
        "cofins_fraction": 0.0285,
        "contracted_demand_min_kw": 0.0,
        "contracted_demand_max_kw": 200.0,
        "demand_exceedance_tolerance_fraction": 0.05,
        "demand_exceedance_multiplier": 2.0,
        "charging_price_brl_per_kwh": 1.99,
        "charging_variable_fee_fraction": 0.08,
    }

    params = build_tariff_parameters(tariff, 24.0)

    assert params["energy_offpeak_brl_per_kwh"] == pytest.approx(
        0.43698 / 0.7852
    )
    assert params["energy_peak_brl_per_kwh"] == pytest.approx(
        1.78345 / 0.7852
    )
    assert params["charging_net_price_brl_per_kwh"] == pytest.approx(
        1.99 * 0.92
    )
    assert params["demand_month_weight"] == pytest.approx(
        1.0 / (365.25 / 12.0)
    )
