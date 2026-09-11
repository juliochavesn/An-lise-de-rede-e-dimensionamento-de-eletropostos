"""
Módulo responsável por gerar arquivos .dat para o AMPL.

O objetivo deste arquivo é converter:
- perfis temporais;
- parâmetros econômicos;
- limites tecnológicos;
- flags dos cenários;

em um arquivo compatível com o modelo matemático AMPL.
"""

# Classe Path facilita manipulação de caminhos de arquivos.
from pathlib import Path
from .service_policy import write_service_parameters


def capital_recovery_factor(rate, years):
    """Calcula o fator de recuperação de capital [1/ano]."""
    rate = float(rate)
    years = float(years)
    if rate < 0.0:
        raise ValueError("A taxa de desconto não pode ser negativa.")
    if years <= 0.0:
        raise ValueError("A vida econômica deve ser positiva.")
    if abs(rate) < 1e-12:
        return 1.0 / years
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


def build_ampl_cost_parameters(costs, horizon_h):
    """
    Converte premissas financeiras em parâmetros usados pelo AMPL.

    CAPEX e O&M permanecem em R$ constantes. O fator
    horizon_weight_years converte custos anuais para o horizonte.
    """
    horizon_h = float(horizon_h)
    if horizon_h <= 0.0:
        raise ValueError("horizon_h deve ser positivo.")

    required = {
        "pv_capex_per_kwp",
        "pv_fixed_om_per_kwp_year",
        "pv_economic_lifetime_years",
        "bess_energy_capex_per_kwh",
        "bess_power_capex_per_kw",
        "bess_fixed_om_per_kw_year",
        "bess_economic_lifetime_years",
        "bess_equivalent_full_cycles",
        "bess_usable_depth_fraction",
        "bess_replacement_cost_fraction",
        "real_discount_rate",
        "curtailment_penalty",
        "final_unserved_penalty",
        "backlog_penalty",
    }
    missing = required - set(costs)
    if missing:
        raise ValueError(
            "Parâmetros econômicos ausentes: "
            f"{sorted(missing)}"
        )

    rate = float(costs["real_discount_rate"])
    cycle_life = float(costs["bess_equivalent_full_cycles"])
    usable_depth = float(costs["bess_usable_depth_fraction"])
    replacement_fraction = float(
        costs["bess_replacement_cost_fraction"]
    )
    if cycle_life <= 0.0:
        raise ValueError("A vida em ciclos do BESS deve ser positiva.")
    if not 0.0 < usable_depth <= 1.0:
        raise ValueError("A profundidade útil deve estar entre 0 e 1.")
    if not 0.0 <= replacement_fraction <= 1.0:
        raise ValueError(
            "A fração de reposição deve estar entre 0 e 1."
        )
    return {
        "pv_capex_per_kwp":
            float(costs["pv_capex_per_kwp"]),
        "pv_fixed_om_per_kwp_year":
            float(costs["pv_fixed_om_per_kwp_year"]),
        "pv_capital_recovery_factor":
            capital_recovery_factor(
                rate,
                costs["pv_economic_lifetime_years"],
            ),
        "bess_energy_capex_per_kwh":
            float(costs["bess_energy_capex_per_kwh"]),
        "bess_power_capex_per_kw":
            float(costs["bess_power_capex_per_kw"]),
        "bess_fixed_om_per_kw_year":
            float(costs["bess_fixed_om_per_kw_year"]),
        "bess_capital_recovery_factor":
            capital_recovery_factor(
                rate,
                costs["bess_economic_lifetime_years"],
            ),
        "bess_degradation_cost_per_kwh_throughput":
            float(costs["bess_energy_capex_per_kwh"])
            * replacement_fraction
            / (2.0 * cycle_life * usable_depth),
        "horizon_weight_years": horizon_h / 8760.0,
        "curtailment_penalty":
            float(costs["curtailment_penalty"]),
        "final_unserved_penalty":
            float(costs["final_unserved_penalty"]),
        "backlog_penalty":
            float(costs["backlog_penalty"]),
    }


def build_tariff_parameters(tariff, horizon_h):
    """
    Converte tarifas reguladas sem tributos em valores finais.

    ICMS, PIS e COFINS são tratados "por dentro". Para um horizonte
    diário representativo, a demanda mensal é ponderada pela fração
    do mês representada pelo horizonte.
    """
    horizon_h = float(horizon_h)
    if horizon_h <= 0.0:
        raise ValueError("horizon_h deve ser positivo.")

    tax_fraction = sum(
        float(tariff[name])
        for name in (
            "icms_fraction",
            "pis_fraction",
            "cofins_fraction",
        )
    )
    if not 0.0 <= tax_fraction < 1.0:
        raise ValueError("A soma dos tributos deve estar entre 0 e 1.")

    tax_gross_up = 1.0 / (1.0 - tax_fraction)
    variable_fee = float(
        tariff["charging_variable_fee_fraction"]
    )
    if not 0.0 <= variable_fee < 1.0:
        raise ValueError(
            "charging_variable_fee_fraction deve estar entre 0 e 1."
        )

    contracted_min = float(tariff["contracted_demand_min_kw"])
    contracted_max = float(tariff["contracted_demand_max_kw"])
    if contracted_min < 0.0 or contracted_max < contracted_min:
        raise ValueError(
            "A demanda contratada deve satisfazer "
            "0 <= mínimo <= máximo."
        )

    average_days_per_month = 365.25 / 12.0
    return {
        "energy_offpeak_brl_per_kwh":
            float(
                tariff[
                    "energy_offpeak_before_tax_brl_per_kwh"
                ]
            ) * tax_gross_up,
        "energy_peak_brl_per_kwh":
            float(
                tariff[
                    "energy_peak_before_tax_brl_per_kwh"
                ]
            ) * tax_gross_up,
        "contracted_demand_min_kw": contracted_min,
        "contracted_demand_max_kw": contracted_max,
        "demand_tariff_brl_per_kw_month":
            float(
                tariff["demand_before_tax_brl_per_kw_month"]
            ) * tax_gross_up,
        "demand_exceedance_tolerance_fraction":
            float(
                tariff[
                    "demand_exceedance_tolerance_fraction"
                ]
            ),
        "demand_exceedance_multiplier":
            float(tariff["demand_exceedance_multiplier"]),
        "demand_month_weight":
            horizon_h / (24.0 * average_days_per_month),
        "charging_price_brl_per_kwh":
            float(tariff["charging_price_brl_per_kwh"]),
        "charging_net_price_brl_per_kwh":
            float(tariff["charging_price_brl_per_kwh"])
            * (1.0 - variable_fee),
        "charging_variable_fee_fraction": variable_fee,
    }


def _write_indexed_param(file, name, values):
    """
    Escreve parâmetros indexados no formato AMPL.

    Exemplo gerado:

    param request_kw :=
    0 10.0
    1 15.0
    2 20.0
    ;

    Parâmetros:
    ----------
    file   : arquivo já aberto para escrita.
    name   : nome do parâmetro no AMPL.
    values : dicionário indexado pelo tempo.
    """

    # Inicia definição do parâmetro.
    file.write(f"param {name} :=\n")

    # Percorre todos os índices temporais.
    for idx, value in values.items():

        # Escreve linha:
        # índice valor
        file.write(f"{idx} {value:.10f}\n")

    # Finaliza parâmetro AMPL.
    file.write(";\n\n")


def write_ampl_dat(
    data,
    costs,
    limits,
    tariff,
    config,
    output_path,
):
    """
    Gera arquivo .dat para um cenário específico.

    Parâmetros:
    ----------
    data        : dicionário com séries temporais.
    costs       : parâmetros econômicos.
    limits      : limites tecnológicos.
    tariff      : tarifa elétrica e premissas comerciais.
    config      : configuração tecnológica.
    output_path : caminho do arquivo .dat.
    """

    # Converte para objeto Path.
    output_path = Path(output_path)

    # Cria diretório pai caso não exista.
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # =========================================================
    # FLAGS TECNOLÓGICAS
    # =========================================================

    # Ativa FV apenas nos cenários correspondentes.
    use_pv = 1 if config in [
        "SMART_PV",
        "SMART_PV_BESS"
    ] else 0

    # Ativa BESS apenas nos cenários correspondentes.
    use_bess = 1 if config in [
        "SMART_BESS",
        "SMART_PV_BESS"
    ] else 0

    # =========================================================
    # MODO DO LIMITE DA REDE
    # =========================================================

    # grid_only  -> 0
    # site_total -> 1
    grid_limit_mode_id = (
        0
        if data["grid_limit_mode"] == "grid_only"
        else 1
    )

    # =========================================================
    # ABERTURA DO ARQUIVO .DAT
    # =========================================================

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        # =====================================================
        # CABEÇALHO
        # =====================================================

        file.write(
            "# Arquivo .dat gerado automaticamente\n"
        )

        file.write(
            f"# Configuração: {config}\n\n"
        )

        # =====================================================
        # CONJUNTO TEMPORAL
        # =====================================================

        # Define conjunto temporal T.
        file.write("set T := ")

        # Escreve todos os índices de tempo.
        file.write(
            " ".join(
                str(t)
                for t in data["time_index"]
            )
        )

        # Fecha conjunto.
        file.write(";\n\n")

        # Períodos mensais de faturamento da demanda. No modo diário
        # existe um único período parcial; no anual, meses 1 a 12.
        file.write("set M := ")
        file.write(
            " ".join(str(month) for month in data["billing_periods"])
        )
        file.write(";\n\n")

        # =====================================================
        # PARÂMETROS ESCALARES
        # =====================================================

        # Passo temporal.
        file.write(
            f"param dt := {data['dt_h']};\n"
        )

        # Horizonte total.
        file.write(
            f"param horizon_h := {data['horizon_h']};\n"
        )

        # Limite de exportação.
        file.write(
            f"param export_limit_kw := "
            f"{data['export_limit_kw']};\n"
        )

        # Modo de operação da rede.
        file.write(
            f"param grid_limit_mode_id := "
            f"{grid_limit_mode_id};\n"
        )

        # Flags tecnológicas.
        file.write(
            f"param use_pv := {use_pv};\n"
        )

        file.write(
            f"param use_bess := {use_bess};\n\n"
        )

        # =====================================================
        # LIMITES TECNOLÓGICOS
        # =====================================================

        ev_max_delay_h = float(limits["ev_max_delay_h"])
        delay_steps = int(round(ev_max_delay_h / data["dt_h"]))
        write_service_parameters(file, data, tariff, delay_steps)
        if delay_steps < 1:
            raise ValueError(
                "ev_max_delay_h deve representar ao menos um intervalo."
            )
        if abs(
            delay_steps * data["dt_h"] - ev_max_delay_h
        ) > 1e-9:
            raise ValueError(
                "ev_max_delay_h deve ser múltiplo de dt_h."
            )

        soc_min = float(limits["bess_soc_min_frac"])
        soc_initial = float(limits["bess_soc_init_frac"])
        soc_max = float(limits["bess_soc_max_frac"])
        if not 0.0 <= soc_min < soc_max <= 1.0:
            raise ValueError(
                "A janela de SOC do BESS deve satisfazer "
                "0 <= mínimo < máximo <= 1."
            )
        if not soc_min <= soc_initial <= soc_max:
            raise ValueError(
                "O SOC inicial deve pertencer à janela operacional."
            )

        duration_min = float(limits["bess_duration_min_h"])
        duration_max = float(limits["bess_duration_max_h"])
        if duration_min <= 0.0 or duration_max < duration_min:
            raise ValueError(
                "A duração do BESS deve satisfazer "
                "0 < mínimo <= máximo."
            )

        for key, value in limits.items():
            if key == "ev_max_delay_h":
                continue

            file.write(
                f"param {key} := {value};\n"
            )

        file.write(
            f"param ev_max_delay_steps := {delay_steps};\n"
        )
        file.write("\n")

        # =====================================================
        # PARÂMETROS ECONÔMICOS
        # =====================================================

        ampl_costs = build_ampl_cost_parameters(
            costs,
            data["horizon_h"],
        )

        for key, value in ampl_costs.items():

            file.write(
                f"param {key} := {value};\n"
            )

        file.write("\n")

        tariff_params = build_tariff_parameters(
            tariff,
            data["horizon_h"],
        )

        # Tarifas de energia são temporais e escritas adiante como
        # price_grid. Os demais parâmetros são escalares do AMPL.
        for key, value in tariff_params.items():
            if key not in {
                "energy_offpeak_brl_per_kwh",
                "energy_peak_brl_per_kwh",
                # Substituído pelo parâmetro indexado month_weight[M].
                "demand_month_weight",
            }:
                file.write(
                    f"param {key} := {value};\n"
                )

        file.write("\n")

        # =====================================================
        # SÉRIES TEMPORAIS
        # =====================================================

        # Demanda EV.
        _write_indexed_param(
            file,
            "month_of_t",
            data["month_of_t"]
        )

        _write_indexed_param(
            file,
            "month_weight",
            data["demand_month_weights"]
        )

        # Demanda EV.
        _write_indexed_param(
            file,
            "request_kw",
            data["request_kw"]
        )

        # Carga local.
        _write_indexed_param(
            file,
            "local_load_kw",
            data["local_load_kw"]
        )

        # Limite da rede.
        _write_indexed_param(
            file,
            "grid_limit_kw",
            data["grid_limit_kw"]
        )

        # Tarifa.
        _write_indexed_param(
            file,
            "price_grid",
            data["price_grid"]
        )

        # Fator FV.
        _write_indexed_param(
            file,
            "pv_cf",
            data["pv_cf"]
        )

    # Retorna caminho do arquivo criado.
    return output_path
