import json
import math
import os
from pathlib import Path

import pandas as pd

from src.config import (
    AMPL_MODEL_FILE,
    SOLVER_NAME,
    OUTPUT_DIR,
    CONFIGS,
    COSTS,
    TARIFF,
    LIMITS,
    SCENARIO_BASE,
    SCENARIO_ANNUAL,
    SIMULATION_MODE,
    RUN_SENSITIVITIES_IN_ANNUAL_MODE,
    ANNUAL_RELAX_BESS_BINARY,
    GRID_SENSITIVITY,
    CHARGING_PRICE_SENSITIVITY,
    USE_REALISTIC_PV_PROFILE,
    PV_PROFILE_MODE,
    PV_PROFILE_START_TIME,
    PV_LOCATION,
    PV_SYSTEM,
    SYSTEM_OPTIONS, 
    GRID_NETWORK,
)
from src.solar_pv import (
    PVLocationConfig,
    PVSystemConfig,
    simulate_normalized_pv_profile,
    build_pv_cf_for_optimizer,
    save_pv_profile,
    summarize_pv_resource, save_pv_summary, save_pv_metadata,
    build_annual_average_pv_cf_for_optimizer,
)

from src.profiles import (
    generate_profiles,
    save_homer_load_profiles,
    save_homer_served_profile,
)
from src.grid_bdgd import (
    build_grid_limit_profile,
    build_network_aware_tariff,
)
from src.dat_writer import (
    build_tariff_parameters,
    write_ampl_dat,
)
from src.run_ampl import AmplSolveError, solve_ampl_case
from src.postprocess import extract_results
from src.plots import (
    plot_results,
    plot_annual_results,
    plot_annual_financial_comparison,
    plot_scenario_comparison,
    plot_sensitivity,
)
from src.technical_results import export_technical_results
from src.expansion_diagnostics import analyze_expansion_need


EV_REQUEST_PROFILE_24H = None


def apply_runtime_overrides(env=None):
    """Aplica parâmetros enviados pela interface sem alterar src/config.py."""
    global OUTPUT_DIR, SIMULATION_MODE, CONFIGS, PV_LOCATION
    global SCENARIO_BASE, SCENARIO_ANNUAL, GRID_NETWORK, TARIFF
    global EV_REQUEST_PROFILE_24H
    env = os.environ if env is None else env
    if env.get("EV_SERVICE_POLICY"):
        from src.service_policy import normalize_policy
        TARIFF = dict(TARIFF, service_policy=normalize_policy(json.loads(env["EV_SERVICE_POLICY"])))
    if env.get("EV_GRID_LIMIT_SOURCE"):
        source = env["EV_GRID_LIMIT_SOURCE"]
        if source not in {"bdgd", "minimum"}:
            raise ValueError("A interface aceita somente bdgd ou minimum.")
        GRID_NETWORK = dict(GRID_NETWORK, limit_source=source, on_error="raise")
        if source == "minimum":
            cap = float(env.get("EV_CONTRACTED_DEMAND_MAX_KW", "nan"))
            if not math.isfinite(cap) or cap <= 0:
                raise ValueError("O teto de demanda contratada deve ser finito e maior que zero.")
            if cap < float(TARIFF.get("contracted_demand_min_kw", 0)):
                raise ValueError("O teto informado é menor que a demanda contratada mínima.")
            TARIFF = dict(TARIFF, contracted_demand_max_kw=cap)
    if env.get("EV_BDGD_PATH"):
        GRID_NETWORK = dict(GRID_NETWORK, bdgd_path=Path(env["EV_BDGD_PATH"]).expanduser().resolve())

    if env.get("EV_REQUEST_PROFILE_24H"):
        profile = json.loads(env["EV_REQUEST_PROFILE_24H"])
        if not isinstance(profile, list) or len(profile) != 24:
            raise ValueError("EV_REQUEST_PROFILE_24H deve conter 24 potências horárias.")
        profile = [float(value) for value in profile]
        if any(not math.isfinite(value) or value < 0 for value in profile):
            raise ValueError("O perfil logístico deve conter potências finitas e não negativas.")
        EV_REQUEST_PROFILE_24H = profile

    if env.get("EV_OUTPUT_DIR"):
        OUTPUT_DIR = Path(env["EV_OUTPUT_DIR"]).expanduser().resolve()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if env.get("EV_SITE_LATITUDE") and env.get("EV_SITE_LONGITUDE"):
        PV_LOCATION = dict(PV_LOCATION)
        PV_LOCATION["latitude"] = float(env["EV_SITE_LATITUDE"])
        PV_LOCATION["longitude"] = float(env["EV_SITE_LONGITUDE"])
    if env.get("EV_SIMULATION_MODE"):
        mode = env["EV_SIMULATION_MODE"].strip().lower()
        if mode not in {"daily", "annual"}:
            raise ValueError("EV_SIMULATION_MODE deve ser 'daily' ou 'annual'.")
        SIMULATION_MODE = mode
    if env.get("EV_CONFIGS"):
        allowed = {"SMART", "SMART_PV", "SMART_BESS", "SMART_PV_BESS"}
        selected = [item.strip() for item in env["EV_CONFIGS"].split(",") if item.strip()]
        invalid = set(selected) - allowed
        if invalid or not selected:
            raise ValueError(f"Configurações inválidas em EV_CONFIGS: {sorted(invalid)}")
        CONFIGS = selected

    demand_scale = float(env.get("EV_DEMAND_SCALE", "1"))
    local_scale = float(env.get("EV_LOCAL_LOAD_SCALE", "1"))
    if demand_scale <= 0 or local_scale < 0:
        raise ValueError("Os fatores de carga devem ser positivos (carga local pode ser zero).")
    ev_keys = ("ev_base_kw", "ev_morning_peak_kw", "ev_evening_peak_kw")
    local_keys = ("local_base_kw", "local_midday_peak_kw", "local_evening_peak_kw")
    SCENARIO_BASE = dict(SCENARIO_BASE)
    SCENARIO_ANNUAL = dict(SCENARIO_ANNUAL)
    for scenario in (SCENARIO_BASE, SCENARIO_ANNUAL):
        for key in ev_keys:
            scenario[key] = float(scenario[key]) * demand_scale
        for key in local_keys:
            scenario[key] = float(scenario[key]) * local_scale

    if env.get("EV_CRITICAL_CAPACITY_KW"):
        GRID_NETWORK = dict(GRID_NETWORK)
        GRID_NETWORK["critical_capacity_threshold_kw"] = float(
            env["EV_CRITICAL_CAPACITY_KW"]
        )


def apply_tariff_to_scenario(scenario, tariff):
    """Aplica ao perfil as tarifas finais, já incluindo tributos."""
    scenario = dict(scenario)
    tariff_params = build_tariff_parameters(
        tariff,
        scenario["horizon_h"],
    )
    scenario.update({
        "price_offpeak":
            tariff_params["energy_offpeak_brl_per_kwh"],
        "price_peak":
            tariff_params["energy_peak_brl_per_kwh"],
        "peak_start_hour": tariff["peak_start_hour"],
        "peak_end_hour": tariff["peak_end_hour"],
    })
    return scenario


def get_active_scenario():
    """Retorna uma cópia do cenário diário ou anual selecionado."""
    if SIMULATION_MODE == "daily":
        return dict(SCENARIO_BASE)
    if SIMULATION_MODE == "annual":
        return dict(SCENARIO_ANNUAL)
    raise ValueError("SIMULATION_MODE deve ser 'daily' ou 'annual'.")


def build_realistic_pv_cf(scenario=None):
    """
    Gera perfil FV realista e normalizado usando pvlib.

    Retorna:
    --------
    Dicionário pv_cf_external no formato exigido por generate_profiles().
    """

    scenario = dict(scenario or get_active_scenario())

    # Cria objeto de localização.
    location = PVLocationConfig(**PV_LOCATION)

    # Cria objeto de configuração solarimétrica.
    system = PVSystemConfig(**PV_SYSTEM)
    # Simula perfil FV normalizado anual.
    pv_result = simulate_normalized_pv_profile(
        location_config=location,
        system_config=system,
    )
    pv_summary = summarize_pv_resource(pv_result)

    save_pv_summary(
    pv_summary,
    OUTPUT_DIR,
)
    # Salva perfil anual para auditoria.
    save_pv_profile(
        pv_result,
        OUTPUT_DIR / "pv_profile_realistic.csv",
    )
    save_pv_metadata(
        pv_result,
        OUTPUT_DIR / "pv_profile_metadata.json",
    )
     # Converte perfil anual para o horizonte de otimização.
    if SIMULATION_MODE == "annual":
        pv_cf_external = build_pv_cf_for_optimizer(
            pv_result=pv_result,
            dt_h=scenario["dt_h"],
            horizon_h=scenario["horizon_h"],
            start_time=scenario["calendar_start"],
        )
    elif PV_PROFILE_MODE == "annual_average":
        pv_cf_external = build_annual_average_pv_cf_for_optimizer(
            pv_result=pv_result,
            dt_h=scenario["dt_h"],
            horizon_h=scenario["horizon_h"],
        )
    elif PV_PROFILE_MODE == "specific_period":
        pv_cf_external = build_pv_cf_for_optimizer(
            pv_result=pv_result,
            dt_h=scenario["dt_h"],
            horizon_h=scenario["horizon_h"],
            start_time=PV_PROFILE_START_TIME,
        )
    else:
        raise ValueError(
            "PV_PROFILE_MODE deve ser 'annual_average' "
            "ou 'specific_period'."
        )

    return pv_cf_external

def run_base_scenarios():
    """Executa os cenários tecnológicos principais."""

    scenario = apply_tariff_to_scenario(
        get_active_scenario(),
        TARIFF,
    )

    # O teto contínuo da demanda contratada é também a capacidade
    # máxima disponível da rede para o caso estudado. O nome legado
    # base_grid_limit_kw permanece apenas como argumento interno do
    # gerador de perfis e não é mais uma entrada do usuário.
    scenario["base_grid_limit_kw"] = (
        float(TARIFF["contracted_demand_max_kw"])
        if SYSTEM_OPTIONS["enable_grid"]
        else 0.0
    )

    if not SYSTEM_OPTIONS["enable_local_load"]:
        scenario["local_base_kw"] = 0.0
        scenario["local_midday_peak_kw"] = 0.0
        scenario["local_evening_peak_kw"] = 0.0

    grid_limit_external = None
    if SYSTEM_OPTIONS["enable_grid"]:
        grid_limit_external = build_grid_limit_profile(
            scenario,
            PV_LOCATION,
            GRID_NETWORK,
            OUTPUT_DIR,
        )

    tariff_for_optimization = dict(TARIFF)
    if SYSTEM_OPTIONS["enable_grid"]:
        tariff_for_optimization = build_network_aware_tariff(
            TARIFF,
            grid_limit_external,
            GRID_NETWORK,
        )
    else:
        tariff_for_optimization["contracted_demand_max_kw"] = 0.0

    if (
        SYSTEM_OPTIONS["enable_grid"]
        and GRID_NETWORK.get("limit_source") == "bdgd"
    ):
        grid_values = [float(value) for value in grid_limit_external.values()]
        print(
            "\nModo BDGD: sem teto manual de demanda; "
            "capacidade disponivel min/media/max = "
            f"{min(grid_values):.3f} / "
            f"{sum(grid_values) / len(grid_values):.3f} / "
            f"{max(grid_values):.3f} kW."
        )
        if GRID_NETWORK.get("enable_detailed_connection_report", True):
            print("Analise detalhada do ponto de conexao salva em:")
            print(f"  {OUTPUT_DIR / 'grid_connection_detailed_report.md'}")
            print(f"  {OUTPUT_DIR / 'grid_connection_detailed.json'}")
            print(f"  {OUTPUT_DIR / 'grid_connection_path.csv'}")
        if GRID_NETWORK.get("enable_critical_period_analysis", True):
            critical_path = OUTPUT_DIR / "grid_capacity_critical_analysis.json"
            critical_analysis = json.loads(
                critical_path.read_text(encoding="utf-8")
            )
            preferred_hours = ", ".join(
                f"{int(hour):02d}h"
                for hour in critical_analysis["preferred_charging_hours"]
            )
            print(
                "Analise dos periodos criticos: "
                f"pior dia = {critical_analysis['worst_date']} | "
                "intervalos abaixo do limiar = "
                f"{int(critical_analysis['critical_interval_count'])} | "
                f"horas preferenciais = {preferred_hours}."
            )
            print(f"  {OUTPUT_DIR / 'grid_capacity_24h_analysis.png'}")

    if USE_REALISTIC_PV_PROFILE:
        pv_cf_external = build_realistic_pv_cf(scenario)
    else:
        pv_cf_external = None

    data = generate_profiles(
        **scenario,
        pv_cf_external=pv_cf_external,
        grid_limit_external=grid_limit_external,
        ev_request_external=EV_REQUEST_PROFILE_24H,
    )

    expansion_diagnostic = analyze_expansion_need(data, LIMITS)
    (OUTPUT_DIR / "grid_expansion_diagnostic.json").write_text(
        json.dumps(expansion_diagnostic, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    homer_files = save_homer_load_profiles(data, OUTPUT_DIR)
    print("\nSéries de carga para o HOMER Pro salvas em:")
    for path in homer_files.values():
        print(f"  {path}")

    results = {}
    summaries = []

    for config in CONFIGS:
        print(f"\nExecutando cenário: {config}")

        mode_suffix = "" if SIMULATION_MODE == "daily" else "_annual"
        dat_path = OUTPUT_DIR / f"scenario_base{mode_suffix}_{config}.dat"

        write_ampl_dat(
            data,
            COSTS,
            LIMITS,
            tariff_for_optimization,
            config,
            dat_path,
        )

        try:
            ampl = solve_ampl_case(
                AMPL_MODEL_FILE,
                dat_path,
                SOLVER_NAME,
                relax_integrality=(
                    SIMULATION_MODE == "annual"
                    and ANNUAL_RELAX_BESS_BINARY
                ),
            )
        except AmplSolveError as error:
            # Somente inviabilidade matemática pode ser apresentada como
            # inviabilidade da solução. Estados como "?", "failure" ou
            # "limit" normalmente indicam licença, solver ou ambiente.
            if error.solve_result not in {
                "infeasible", "infeasible_or_unbounded", "unbounded"
            }:
                detail = f" ({error.solve_message})" if error.solve_message else ""
                raise RuntimeError(
                    "Falha técnica do motor AMPL/HiGHS; o caso não foi "
                    f"classificado como inviável. Estado: {error.solve_result}{detail}"
                ) from error
            summary = _infeasible_summary(
                config,
                error.solve_result,
                diagnose_local_grid_adequacy(data),
            )
            summary.update({
                "indicative_firm_reinforcement_kw": expansion_diagnostic[
                    "local_load_case"
                ]["reinforcement_to_eliminate_deficit_kw"],
                "indicative_full_demand_reinforcement_kw": expansion_diagnostic[
                    "full_instantaneous_demand_case"
                ]["reinforcement_to_eliminate_deficit_kw"],
                "indicative_nominal_bess_required_kwh": expansion_diagnostic[
                    "storage_screening"
                ]["indicative_nominal_bess_required_kwh"],
            })
            summaries.append(summary)
            pd.DataFrame([{
                "config": config,
                "solve_status": error.solve_result,
            }]).to_csv(
                OUTPUT_DIR / f"timeseries{mode_suffix}_{config}.csv",
                index=False,
            )
            print(
                "  Cenário não atende aos requisitos mínimos "
                "de serviço e espera."
            )
            continue

        try:
            df, summary = extract_results(config, ampl)
        finally:
            ampl.close()

        summary["solve_status"] = "solved"
        summary["is_feasible"] = True
        summary["simulation_mode"] = SIMULATION_MODE
        summary["horizon_h"] = float(data["horizon_h"])
        if data.get("timestamps") and data["timestamps"][0] is not None:
            df["timestamp"] = pd.to_datetime(data["timestamps"])

        if SIMULATION_MODE == "annual" and config == "SMART_PV_BESS":
            homer_served_path = save_homer_served_profile(
                df,
                OUTPUT_DIR,
                config,
            )
            print(
                "  Série EV atendida para o HOMER Pro: "
                f"{homer_served_path}"
            )
        results[config] = {
            "df": df,
            "summary": summary,
        }
        summaries.append(summary)

        df.to_csv(
            OUTPUT_DIR / f"timeseries{mode_suffix}_{config}.csv",
            index=False,
        )
        # Persist technical diagnostics for both CLI and graphical executions.
        try:
            export_technical_results(df, summary, OUTPUT_DIR)
        except Exception as error:
            print(f"Aviso: gráficos técnicos não gerados para {config}: {error}")

    summary_df = pd.DataFrame(summaries)

    economic = TARIFF.get("service_policy", {}).get("mode") == "economic"
    summary_df = summary_df.sort_values(
        by=["objective_value"] if economic else ["served_ratio", "objective_value"],
        ascending=[True] if economic else [False, True],
    )

    summary_df.to_csv(
        OUTPUT_DIR / (
            "summary_base.csv"
            if SIMULATION_MODE == "daily"
            else "summary_annual.csv"
        ),
        index=False,
    )

    return results, summary_df

def build_grid_sensitivity_limits(base_limit_kw, settings):
    """Constrói limites ancorados na demanda contratada."""
    if base_limit_kw < 0.0:
        raise ValueError("base_grid_limit_kw não pode ser negativo.")

    mode = settings.get("mode", "relative")

    if mode == "relative":
        factors = settings.get("factors")
        if not factors:
            raise ValueError("A lista de fatores não pode ser vazia.")
        if any(float(factor) < 0.0 for factor in factors):
            raise ValueError("Os fatores não podem ser negativos.")
        values = [
            base_limit_kw * float(factor)
            for factor in factors
        ]
        rounding_kw = settings.get("rounding_kw")
        if rounding_kw:
            rounding_kw = float(rounding_kw)
            if rounding_kw <= 0.0:
                raise ValueError("rounding_kw deve ser positivo.")
            values = [
                round(value / rounding_kw) * rounding_kw
                for value in values
            ]

    elif mode == "range":
        minimum_kw = settings.get("minimum_kw")
        maximum_kw = settings.get("maximum_kw")
        step_kw = settings.get("step_kw")
        if minimum_kw is None or maximum_kw is None or step_kw is None:
            raise ValueError(
                "O modo range exige minimum_kw, maximum_kw e step_kw."
            )
        minimum_kw = float(minimum_kw)
        maximum_kw = float(maximum_kw)
        step_kw = float(step_kw)
        if minimum_kw < 0.0 or maximum_kw < minimum_kw:
            raise ValueError("Intervalo de sensibilidade inválido.")
        if step_kw <= 0.0:
            raise ValueError("step_kw deve ser positivo.")
        count = int(
            math.floor((maximum_kw - minimum_kw) / step_kw + 1e-9)
        )
        values = [
            minimum_kw + index * step_kw
            for index in range(count + 1)
        ]
        if values[-1] < maximum_kw - 1e-9:
            values.append(maximum_kw)

    elif mode == "manual":
        values_kw = settings.get("values_kw")
        if not values_kw:
            raise ValueError("A lista values_kw não pode ser vazia.")
        values = [float(value) for value in values_kw]
        if any(value < 0.0 for value in values):
            raise ValueError("Os limites não podem ser negativos.")

    else:
        raise ValueError(
            "O modo deve ser 'relative', 'range' ou 'manual'."
        )

    if settings.get("include_base_limit", True):
        values.append(float(base_limit_kw))

    return sorted({
        round(float(value), 10)
        for value in values
    })


def diagnose_local_grid_adequacy(data):
    """Quantifica a insuficiência da rede para a carga local."""
    dt = float(data["dt_h"])
    local_values = [
        float(data["local_load_kw"][t])
        for t in data["time_index"]
    ]
    gaps = [
        max(
            0.0,
            float(data["local_load_kw"][t])
            - float(data["grid_limit_kw"][t]),
        )
        for t in data["time_index"]
    ]

    return {
        "local_peak_kw": max(local_values, default=0.0),
        "grid_alone_serves_local_load": not any(
            gap > 1e-9 for gap in gaps
        ),
        "local_grid_gap_peak_kw": max(gaps, default=0.0),
        "local_grid_gap_energy_kwh": sum(gaps) * dt,
        "local_grid_gap_intervals": sum(
            gap > 1e-9 for gap in gaps
        ),
    }


def _infeasible_summary(config, solve_status, diagnostics):
    """Cria uma linha de resultado para uma configuração inviável."""
    return {
        "config": config,
        "solve_status": solve_status,
        "is_feasible": False,
        "objective_value": float("nan"),
        "pv_size_kw": float("nan"),
        "bess_e_kwh": float("nan"),
        "bess_p_kw": float("nan"),
        "requested_energy_kwh": float("nan"),
        "served_energy_kwh": float("nan"),
        "served_ratio": float("nan"),
        "final_backlog_kwh": float("nan"),
        **diagnostics,
    }


def run_sensitivity():
    """Executa teste de sensibilidade para diferentes limites da rede."""

    if GRID_NETWORK.get("limit_source") == "bdgd":
        print(
            "\nSensibilidade de limites manuais ignorada no modo BDGD: "
            "a capacidade fisica vem exclusivamente da rede."
        )
        return pd.DataFrame()

    sensitivity = []

    if USE_REALISTIC_PV_PROFILE:
        pv_cf_external = build_realistic_pv_cf()
    else:
        pv_cf_external = None

    base_limit_kw = float(TARIFF["contracted_demand_max_kw"])
    sensitivity_limits = build_grid_sensitivity_limits(
        base_limit_kw,
        GRID_SENSITIVITY,
    )

    print(
        "\nLimites da sensibilidade da rede [kW]: "
        f"{sensitivity_limits}"
    )

    for limit_kw in sensitivity_limits:

        print(f"\nTeste de sensibilidade: limite da rede = {limit_kw} kW")

        scenario = apply_tariff_to_scenario(
            SCENARIO_BASE,
            TARIFF,
        )

        # ==========================================
        # REDE
        # ==========================================

        if SYSTEM_OPTIONS["enable_grid"]:
            scenario["base_grid_limit_kw"] = limit_kw
        else:
            scenario["base_grid_limit_kw"] = 0.0

        tariff_case = dict(TARIFF)
        tariff_case["contracted_demand_max_kw"] = (
            limit_kw if SYSTEM_OPTIONS["enable_grid"] else 0.0
        )

        # ==========================================
        # CARGA LOCAL
        # ==========================================

        if not SYSTEM_OPTIONS["enable_local_load"]:
            scenario["local_base_kw"] = 0.0
            scenario["local_midday_peak_kw"] = 0.0
            scenario["local_evening_peak_kw"] = 0.0

        # ==========================================
        # GERA PERFIS
        # ==========================================

        grid_limit_external = None
        if SYSTEM_OPTIONS["enable_grid"]:
            grid_limit_external = build_grid_limit_profile(
                scenario,
                PV_LOCATION,
                GRID_NETWORK,
                OUTPUT_DIR,
                diagnostic_filename=(
                    f"grid_connection_assessment_sensitivity_{limit_kw:g}_kw.json"
                ),
            )

        data_test = generate_profiles(
            **scenario,
            pv_cf_external=pv_cf_external,
            grid_limit_external=grid_limit_external,
        )
        diagnostics = diagnose_local_grid_adequacy(data_test)

        if diagnostics["grid_alone_serves_local_load"]:
            print(
                "  Diagnóstico local: a rede sozinha pode atender "
                "integralmente a carga local."
            )
        else:
            print(
                "  Diagnóstico local: a rede sozinha NÃO garante "
                "o atendimento integral da carga local."
            )
            print(
                "    Pico local = "
                f"{diagnostics['local_peak_kw']:.2f} kW | "
                "déficit máximo = "
                f"{diagnostics['local_grid_gap_peak_kw']:.2f} kW | "
                "déficit energético = "
                f"{diagnostics['local_grid_gap_energy_kwh']:.2f} kWh"
            )

        for config in CONFIGS:

            print(f"  Configuração: {config}")

            dat_path = (
                OUTPUT_DIR
                / f"sensitivity_grid_{limit_kw}_{config}.dat"
            )

            write_ampl_dat(
                data_test,
                COSTS,
                LIMITS,
                tariff_case,
                config,
                dat_path,
            )

            try:
                ampl = solve_ampl_case(
                    AMPL_MODEL_FILE,
                    dat_path,
                    SOLVER_NAME,
                )
            except AmplSolveError as error:
                summary = _infeasible_summary(
                    config,
                    error.solve_result,
                    diagnostics,
                )
                print(
                    "    Resultado: inviável para atendimento "
                    "integral das cargas obrigatórias."
                )
            else:
                try:
                    _, summary = extract_results(config, ampl)
                finally:
                    ampl.close()
                summary["solve_status"] = "solved"
                summary["is_feasible"] = True
                summary.update(diagnostics)
                print("    Resultado: solução ótima.")

            summary["grid_limit_test_kw"] = limit_kw
            summary["base_grid_limit_kw"] = base_limit_kw
            summary["grid_limit_factor"] = (
                limit_kw / base_limit_kw
                if base_limit_kw > 1e-9
                else float("nan")
            )
            sensitivity.append(summary)

    sens_df = pd.DataFrame(sensitivity)

    sens_df.to_csv(
        OUTPUT_DIR / "summary_sensitivity_grid_limit.csv",
        index=False,
    )

    return sens_df


def build_relative_values(base_value, settings):
    """Constrói valores de sensibilidade relativos à referência."""
    base_value = float(base_value)
    factors = [
        float(factor)
        for factor in settings.get("factors", [])
    ]
    if base_value < 0.0:
        raise ValueError("O valor-base não pode ser negativo.")
    if not factors or any(factor < 0.0 for factor in factors):
        raise ValueError("Fatores de sensibilidade inválidos.")
    if settings.get("include_base", True):
        factors.append(1.0)
    factors = sorted(set(factors))
    return [
        (factor, base_value * factor)
        for factor in factors
    ]


def run_charging_price_sensitivity():
    """Avalia preços de recarga definidos por fatores da referência."""
    sensitivity = []
    base_price = float(TARIFF["charging_price_brl_per_kwh"])
    cases = build_relative_values(
        base_price,
        CHARGING_PRICE_SENSITIVITY,
    )

    if USE_REALISTIC_PV_PROFILE:
        pv_cf_external = build_realistic_pv_cf()
    else:
        pv_cf_external = None

    scenario = apply_tariff_to_scenario(
        SCENARIO_BASE,
        TARIFF,
    )
    scenario["base_grid_limit_kw"] = (
        float(TARIFF["contracted_demand_max_kw"])
        if SYSTEM_OPTIONS["enable_grid"]
        else 0.0
    )
    grid_limit_external = None
    if SYSTEM_OPTIONS["enable_grid"]:
        grid_limit_external = build_grid_limit_profile(
            scenario,
            PV_LOCATION,
            GRID_NETWORK,
            OUTPUT_DIR,
            diagnostic_filename="grid_connection_assessment_charging_price.json",
        )
    data = generate_profiles(
        **scenario,
        pv_cf_external=pv_cf_external,
        grid_limit_external=grid_limit_external,
    )

    print("\nSensibilidade do preço de recarga [R$/kWh]:")
    for factor, price in cases:
        print(f"  fator={factor:.2f} | preço={price:.4f}")
        tariff_case = dict(TARIFF)
        tariff_case["charging_price_brl_per_kwh"] = price
        if SYSTEM_OPTIONS["enable_grid"]:
            tariff_case = build_network_aware_tariff(
                tariff_case,
                grid_limit_external,
                GRID_NETWORK,
            )
        else:
            tariff_case["contracted_demand_max_kw"] = 0.0

        for config in CONFIGS:
            dat_path = (
                OUTPUT_DIR
                / (
                    "sensitivity_charging_price_"
                    f"{factor:.2f}_{config}.dat"
                )
            )
            write_ampl_dat(
                data,
                COSTS,
                LIMITS,
                tariff_case,
                config,
                dat_path,
            )
            try:
                ampl = solve_ampl_case(
                    AMPL_MODEL_FILE,
                    dat_path,
                    SOLVER_NAME,
                )
            except AmplSolveError as error:
                summary = _infeasible_summary(
                    config,
                    error.solve_result,
                    {},
                )
            else:
                try:
                    _, summary = extract_results(config, ampl)
                finally:
                    ampl.close()
                summary["solve_status"] = "solved"
                summary["is_feasible"] = True

            summary["charging_price_factor"] = factor
            summary["charging_price_brl_per_kwh"] = price
            sensitivity.append(summary)

    sensitivity_df = pd.DataFrame(sensitivity)
    sensitivity_df.to_csv(
        OUTPUT_DIR / "summary_sensitivity_charging_price.csv",
        index=False,
    )
    return sensitivity_df


if __name__ == "__main__":
    apply_runtime_overrides()
    active_scenario = get_active_scenario()
    print(
        "\nModo de simulação selecionado: "
        f"{SIMULATION_MODE.upper()} | "
        f"horizonte = {active_scenario['horizon_h']:.0f} h | "
        f"passo = {active_scenario['dt_h']:.2f} h | "
        "intervalos = "
        f"{int(active_scenario['horizon_h'] / active_scenario['dt_h'])}"
    )
    results, summary_df = run_base_scenarios()

    print("\nResumo dos cenários principais:")
    print(summary_df)

    if SIMULATION_MODE == "annual":
        plot_annual_results(results)
        plot_annual_financial_comparison(summary_df)
    else:
        plot_results(results)

    if (
        SYSTEM_OPTIONS["enable_grid"]
        and GRID_SENSITIVITY.get("enabled", True)
        and GRID_NETWORK.get("limit_source") != "bdgd"
        and (
            SIMULATION_MODE == "daily"
            or RUN_SENSITIVITIES_IN_ANNUAL_MODE
        )
    ):

       sens_df = run_sensitivity()

       print("\nResumo da sensibilidade:")
       print(sens_df)

       plot_sensitivity(sens_df)

    elif not SYSTEM_OPTIONS["enable_grid"]:
        print(
            "\nSensibilidade da rede ignorada "
            "(enable_grid = False)."
        )
    elif GRID_NETWORK.get("limit_source") == "bdgd":
        print(
            "\nSensibilidade de limites manuais ignorada no modo BDGD: "
            "a capacidade fisica vem exclusivamente da rede."
        )
    else:
        print(
            "\nSensibilidade da rede desabilitada em "
            "GRID_SENSITIVITY."
        )

    if (
        CHARGING_PRICE_SENSITIVITY.get("enabled", True)
        and (
            SIMULATION_MODE == "daily"
            or RUN_SENSITIVITIES_IN_ANNUAL_MODE
        )
    ):
        charging_sens_df = run_charging_price_sensitivity()
        print("\nResumo da sensibilidade do preço de recarga:")
        print(charging_sens_df)

    comparison = plot_scenario_comparison(summary_df)
    if comparison is not None:
        print(
            "\nMelhor configuração segundo a política de atendimento selecionada: "
            f"{comparison['best_config']} | "
            f"atendimento = "
            f"{100 * comparison['served_ratio']:.2f}% | "
            f"custo líquido = "
            f"R$ {comparison['objective_value']:.2f}"
        )
