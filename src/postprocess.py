"""
Pós-processamento dos resultados do AMPL.

Este módulo:
- extrai variáveis do modelo;
- converte resultados em DataFrame;
- calcula indicadores energéticos;
- gera métricas de qualidade do atendimento.
"""

import pandas as pd


def _get_scalar(ampl, name):
    """
    Obtém valor escalar do AMPL.
    """

    return ampl.get_value(name)


def _get_param_dict(ampl, name):
    """
    Obtém parâmetro indexado AMPL como dicionário Python.
    """

    return ampl.get_parameter(name).to_dict()


def _get_var_dict(ampl, name):
    """
    Obtém variável indexada AMPL como dicionário Python.
    """

    return ampl.get_variable(name).get_values().to_dict()


def extract_results(config, ampl):
    """
    Extrai resultados do cenário resolvido.
    """

    # =========================================================
    # CONJUNTO TEMPORAL
    # =========================================================

    T = list(ampl.get_set("T").to_list())
    M = list(ampl.get_set("M").to_list())

    # =========================================================
    # PARÂMETROS ESCALARES
    # =========================================================

    dt = float(_get_scalar(ampl, "dt"))

    # =========================================================
    # PARÂMETROS TEMPORAIS
    # =========================================================

    request_kw = _get_param_dict(ampl, "request_kw")

    local_load_kw = _get_param_dict(
        ampl,
        "local_load_kw"
    )

    grid_limit_kw = _get_param_dict(
        ampl,
        "grid_limit_kw"
    )

    price_grid = _get_param_dict(
        ampl,
        "price_grid"
    )

    pv_cf = _get_param_dict(
        ampl,
        "pv_cf"
    )
    month_of_t = _get_param_dict(ampl, "month_of_t")
    month_weight = _get_param_dict(ampl, "month_weight")

    # =========================================================
    # VARIÁVEIS TEMPORAIS
    # =========================================================

    p_served_kw = _get_var_dict(
        ampl,
        "p_served_kw"
    )

    backlog_kwh = _get_var_dict(
        ampl,
        "backlog_kwh"
    )

    expired_unserved_kwh = _get_var_dict(
        ampl,
        "expired_unserved_kwh"
    )

    p_grid_import_kw = _get_var_dict(
        ampl,
        "p_grid_import_kw"
    )

    p_grid_export_kw = _get_var_dict(
        ampl,
        "p_grid_export_kw"
    )

    p_pv_used_kw = _get_var_dict(
        ampl,
        "p_pv_used_kw"
    )

    p_pv_curt_kw = _get_var_dict(
        ampl,
        "p_pv_curt_kw"
    )

    p_bess_ch_kw = _get_var_dict(
        ampl,
        "p_bess_ch_kw"
    )

    p_bess_dis_kw = _get_var_dict(
        ampl,
        "p_bess_dis_kw"
    )

    bess_charge_mode = _get_var_dict(
        ampl,
        "bess_charge_mode"
    )

    soc_kwh = _get_var_dict(
        ampl,
        "soc_kwh"
    )

    # =========================================================
    # VARIÁVEIS DE DIMENSIONAMENTO
    # =========================================================

    charger_power_installed_kw = float(
        _get_scalar(ampl, "charger_power_installed_kw")
    )

    pv_size_kw = float(
        _get_scalar(ampl, "pv_size_kw")
    )

    bess_e_kwh = float(
        _get_scalar(ampl, "bess_e_kwh")
    )

    bess_p_kw = float(
        _get_scalar(ampl, "bess_p_kw")
    )

    # =========================================================
    # PARÂMETROS E INDICADORES ECONÔMICOS
    # =========================================================

    pv_capex_per_kwp = float(
        _get_scalar(ampl, "pv_capex_per_kwp")
    )
    charger_capex_per_kw = float(
        _get_scalar(ampl, "charger_capex_per_kw")
    )
    charger_fixed_om_per_kw_year = float(
        _get_scalar(ampl, "charger_fixed_om_per_kw_year")
    )
    charger_capital_recovery_factor = float(
        _get_scalar(ampl, "charger_capital_recovery_factor")
    )
    pv_fixed_om_per_kwp_year = float(
        _get_scalar(ampl, "pv_fixed_om_per_kwp_year")
    )
    pv_capital_recovery_factor = float(
        _get_scalar(ampl, "pv_capital_recovery_factor")
    )
    bess_energy_capex_per_kwh = float(
        _get_scalar(ampl, "bess_energy_capex_per_kwh")
    )
    bess_power_capex_per_kw = float(
        _get_scalar(ampl, "bess_power_capex_per_kw")
    )
    bess_fixed_om_per_kw_year = float(
        _get_scalar(ampl, "bess_fixed_om_per_kw_year")
    )
    bess_capital_recovery_factor = float(
        _get_scalar(ampl, "bess_capital_recovery_factor")
    )
    bess_degradation_cost_per_kwh_throughput = float(
        _get_scalar(
            ampl,
            "bess_degradation_cost_per_kwh_throughput",
        )
    )
    horizon_weight_years = float(
        _get_scalar(ampl, "horizon_weight_years")
    )
    contracted_demand_kw = float(
        _get_scalar(ampl, "contracted_demand_kw")
    )
    demand_tariff_brl_per_kw_month = float(
        _get_scalar(ampl, "demand_tariff_brl_per_kw_month")
    )
    demand_exceedance_multiplier = float(
        _get_scalar(ampl, "demand_exceedance_multiplier")
    )
    charging_price_brl_per_kwh = float(
        _get_scalar(ampl, "charging_price_brl_per_kwh")
    )
    charging_net_price_brl_per_kwh = float(
        _get_scalar(ampl, "charging_net_price_brl_per_kwh")
    )
    maximum_pv_curtailment_fraction = float(
        _get_scalar(ampl, "maximum_pv_curtailment_fraction")
    )
    demand_above_contract_by_month = _get_var_dict(
        ampl, "demand_above_contract_kw"
    )
    demand_exceedance_by_month = _get_var_dict(
        ampl, "demand_exceedance_kw"
    )

    charger_capex_brl = charger_power_installed_kw * charger_capex_per_kw
    charger_annualized_cost_brl_year = charger_power_installed_kw * (
        charger_capex_per_kw * charger_capital_recovery_factor
        + charger_fixed_om_per_kw_year
    )
    pv_capex_brl = pv_size_kw * pv_capex_per_kwp
    pv_annualized_cost_brl_year = pv_size_kw * (
        pv_capex_per_kwp * pv_capital_recovery_factor
        + pv_fixed_om_per_kwp_year
    )

    bess_capex_brl = (
        bess_e_kwh * bess_energy_capex_per_kwh
        + bess_p_kw * bess_power_capex_per_kw
    )
    bess_annualized_cost_brl_year = (
        bess_capex_brl * bess_capital_recovery_factor
        + bess_p_kw * bess_fixed_om_per_kw_year
    )

    investment_cost_in_horizon_brl = (
        horizon_weight_years
        * (
            charger_annualized_cost_brl_year
            + pv_annualized_cost_brl_year
            + bess_annualized_cost_brl_year
        )
    )

    bess_duration_h = (
        bess_e_kwh / bess_p_kw
        if bess_p_kw > 1e-9
        else 0.0
    )

    # =========================================================
    # CONSTRUÇÃO DO DATAFRAME
    # =========================================================

    rows = []

    prev_backlog = 0.0

    for t in T:

        req = float(request_kw[t])

        served = float(p_served_kw[t])

        backlog = float(backlog_kwh[t])

        admissible_served_kw = (
            req + prev_backlog / dt
        )

        pv_avail_kw = (
            float(pv_cf[t]) * pv_size_kw
        )

        rows.append({

            "config": config,

            "t": int(t),

            "hour": (int(t) + 0.5) * dt,

            "month": int(round(float(month_of_t[t]))),

            "request_kw": req,

            "served_kw": served,

            "admissible_served_kw":
                admissible_served_kw,

            "local_load_kw":
                float(local_load_kw[t]),

            "grid_limit_kw":
                float(grid_limit_kw[t]),

            "price_grid":
                float(price_grid[t]),

            "grid_import_kw":
                float(p_grid_import_kw[t]),

            "grid_export_kw":
                float(p_grid_export_kw[t]),

            "pv_avail_kw":
                pv_avail_kw,

            "pv_used_kw":
                float(p_pv_used_kw[t]),

            "pv_curt_kw":
                float(p_pv_curt_kw[t]),

            "pv_allocation_residual_kw":
                pv_avail_kw
                - float(p_pv_used_kw[t])
                - float(p_pv_curt_kw[t]),

            "bess_ch_kw":
                float(p_bess_ch_kw[t]),

            "bess_dis_kw":
                float(p_bess_dis_kw[t]),

            "bess_charge_mode":
                int(round(float(bess_charge_mode[t]))),

            "soc_kwh":
                float(soc_kwh[t]),

            "backlog_kwh":
                backlog,

            "expired_unserved_kwh":
                float(expired_unserved_kwh[t]),

        })

        prev_backlog = backlog

    # =========================================================
    # DATAFRAME FINAL
    # =========================================================

    df = pd.DataFrame(rows)

    # =========================================================
    # INDICADORES
    # =========================================================

    requested_energy = (
        df["request_kw"] * dt
    ).sum()

    served_energy = (
        df["served_kw"] * dt
    ).sum()

    final_backlog = float(
        df["backlog_kwh"].iloc[-1]
    )

    expired_unserved_energy = float(
        df["expired_unserved_kwh"].sum()
    )

    ev_max_delay_h = (
        float(_get_scalar(ampl, "ev_max_delay_steps"))
        * dt
    )

    served_ratio = (
        served_energy / requested_energy
        if requested_energy > 1e-9
        else 1.0
    )

    maximum_served_energy = float(
        _get_scalar(ampl, "served_energy_quality_floor_kwh")
    )
    maximum_service_ratio = (
        maximum_served_energy / requested_energy
        if requested_energy > 1e-9
        else 1.0
    )
    economic_mode = int(_get_scalar(ampl, "economic_service_mode")) == 1
    if economic_mode:
        allocation = ampl.get_variable("cohort_served").get_values().to_dict()
        origin_served = {t: 0.0 for t in T}
        for (arrival, dispatch), energy in allocation.items():
            origin_served[arrival] += float(energy)
        # Mesma ordem temporal usada para construir df; serviço atribuído à chegada.
        df["cohort_served_kwh"] = [origin_served[t] for t in T]
        df["cohort_unserved_kwh"] = df["request_kw"] * dt - df["cohort_served_kwh"]
        maximum_service_ratio = None

    # Usa a série efetivamente importada para reportar o pico. A
    # variável auxiliar do AMPL pode ficar no valor contratado quando
    # o pico real é inferior, pois isso não altera o faturamento.
    monthly_peaks = (
        df.groupby("month")["grid_import_kw"].max().to_dict()
    )
    monthly_peak_grid_kw = float(max(monthly_peaks.values(), default=0.0))

    grid_energy_cost_brl = (
        df["grid_import_kw"]
        * df["price_grid"]
        * dt
    ).sum()

    demand_cost_in_horizon_brl = demand_tariff_brl_per_kw_month * sum(
        float(month_weight[m])
        * (
            contracted_demand_kw
            + float(demand_above_contract_by_month[m])
            + demand_exceedance_multiplier
            * float(demand_exceedance_by_month[m])
        )
        for m in M
    )
    demand_above_contract_kw = float(max(
        demand_above_contract_by_month.values(), default=0.0
    ))
    demand_exceedance_kw = float(max(
        demand_exceedance_by_month.values(), default=0.0
    ))

    charging_gross_revenue_brl = (
        served_energy * charging_price_brl_per_kwh
    )
    charging_net_revenue_brl = (
        served_energy * charging_net_price_brl_per_kwh
    )
    operating_margin_before_investment_brl = (
        charging_net_revenue_brl
        - grid_energy_cost_brl
        - demand_cost_in_horizon_brl
    )

    bess_throughput_kwh = float(
        (
            df["bess_ch_kw"]
            + df["bess_dis_kw"]
        ).sum() * dt
    )
    bess_simultaneous_intervals = int(
        (
            (df["bess_ch_kw"] > 1e-7)
            & (df["bess_dis_kw"] > 1e-7)
        ).sum()
    )
    bess_degradation_cost_brl = (
        bess_throughput_kwh
        * bess_degradation_cost_per_kwh_throughput
    )

    pv_available_energy = (
        df["pv_avail_kw"] * dt
    ).sum()

    pv_used_energy = (
        df["pv_used_kw"] * dt
    ).sum()

    pv_curtailed_energy = (
        df["pv_curt_kw"] * dt
    ).sum()

    pv_utilization_ratio = (
        pv_used_energy / pv_available_energy
        if pv_available_energy > 1e-9
        else 0.0
    )

    pv_curtailment_ratio = (
        pv_curtailed_energy / pv_available_energy
        if pv_available_energy > 1e-9
        else 0.0
    )

    pv_full_load_hours = (
        pv_available_energy / pv_size_kw
        if pv_size_kw > 1e-9
        else 0.0
    )

    # =========================================================
    # RESUMO FINAL
    # =========================================================

    summary = {
        "service_mode": "economic" if economic_mode else "maximum",
        "service_target": float(_get_scalar(ampl, "service_target")) if economic_mode else None,
        "period_service_target": float(_get_scalar(ampl, "period_service_target")) if economic_mode else None,
        "strict_service_targets": bool(round(float(_get_scalar(ampl, "strict_service_targets")))) if economic_mode else None,
        "global_target_shortfall_kwh": float(_get_scalar(ampl, "global_target_shortfall_kwh")) if economic_mode else 0.0,
        "service_target_met": (served_energy + 1e-6 >= float(_get_scalar(ampl, "service_target")) * requested_energy) if economic_mode else None,
        "unserved_energy_kwh": max(0.0, requested_energy - served_energy),
        "charging_curtailment_ratio": (max(0.0, requested_energy - served_energy) / requested_energy if requested_energy > 1e-9 else 0.0),
        "waiting_energy_hours": float(df["backlog_kwh"].sum() * dt),
        "ev_waiting_penalty_brl": float(_get_scalar(ampl, "ev_waiting_cost")) * float(df["backlog_kwh"].sum() * dt) if economic_mode else 0.0,
        "ev_unserved_penalty_brl": float(_get_scalar(ampl, "ev_unserved_cost")) * (expired_unserved_energy + final_backlog) if economic_mode else 0.0,
        # Metadados da execução, para gráficos sem depender do config atual.
        "dt_h": dt,
        "bess_soc_init_frac": float(_get_scalar(ampl, "bess_soc_init_frac")),
        "bess_soc_min_frac": float(_get_scalar(ampl, "bess_soc_min_frac")),
        "bess_soc_max_frac": float(_get_scalar(ampl, "bess_soc_max_frac")),

        "config": config,

        "charger_power_installed_kw":
            charger_power_installed_kw,

        "charger_capex_brl":
            charger_capex_brl,

        "charger_annualized_cost_brl_year":
            charger_annualized_cost_brl_year,

        "objective_value":
            float(_get_scalar(ampl, "Total_Cost")),

        "pv_size_kw":
            pv_size_kw,

        "bess_e_kwh":
            bess_e_kwh,

        "bess_p_kw":
            bess_p_kw,

        "bess_duration_h":
            bess_duration_h,

        "pv_capex_brl":
            pv_capex_brl,

        "pv_annualized_cost_brl_year":
            pv_annualized_cost_brl_year,

        "bess_capex_brl":
            bess_capex_brl,

        "bess_annualized_cost_brl_year":
            bess_annualized_cost_brl_year,

        "investment_cost_in_horizon_brl":
            investment_cost_in_horizon_brl,

        "contracted_demand_kw":
            contracted_demand_kw,

        "monthly_peak_grid_kw":
            monthly_peak_grid_kw,

        "demand_above_contract_kw":
            demand_above_contract_kw,

        "demand_exceedance_kw":
            demand_exceedance_kw,

        "grid_energy_cost_brl":
            grid_energy_cost_brl,

        "demand_cost_in_horizon_brl":
            demand_cost_in_horizon_brl,

        "charging_price_brl_per_kwh":
            charging_price_brl_per_kwh,

        "charging_gross_revenue_brl":
            charging_gross_revenue_brl,

        "charging_net_revenue_brl":
            charging_net_revenue_brl,

        "operating_margin_before_investment_brl":
            operating_margin_before_investment_brl,

        "requested_energy_kwh":
            requested_energy,

        "served_energy_kwh":
            served_energy,

        "served_ratio":
            served_ratio,

        "maximum_service_ratio":
            maximum_service_ratio,

        "service_optimality_gap_kwh":
            None if economic_mode else max(0.0, maximum_served_energy - served_energy),

        "final_backlog_kwh":
            final_backlog,

        "expired_unserved_energy_kwh":
            expired_unserved_energy,

        "ev_max_delay_h":
            ev_max_delay_h,

        "bess_throughput_kwh":
            bess_throughput_kwh,

        "bess_simultaneous_intervals":
            bess_simultaneous_intervals,

        "bess_degradation_cost_brl":
            bess_degradation_cost_brl,

        "pv_available_energy_kwh":
            pv_available_energy,

        "pv_used_energy_kwh":
            pv_used_energy,

        "pv_curtailed_energy_kwh":
            pv_curtailed_energy,

        "pv_utilization_ratio":
            pv_utilization_ratio,

        "pv_curtailment_ratio":
            pv_curtailment_ratio,

        "maximum_pv_curtailment_fraction":
            maximum_pv_curtailment_fraction,

        "pv_full_load_hours":
            pv_full_load_hours,

        "pv_allocation_max_error_kw":
            float(
                df["pv_allocation_residual_kw"]
                .abs()
                .max()
            ),
    }

    return df, summary
