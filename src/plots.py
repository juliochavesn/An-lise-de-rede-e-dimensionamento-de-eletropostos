"""
Gráficos dos cenários otimizados.

Mostra:
- demanda EV;
- atendimento EV;
- importação da rede;
- geração FV utilizada;
- carga/descarga do BESS;
- backlog;
- dimensionamento ótimo de FV e BESS.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.config import OUTPUT_DIR, TARIFF


def _shade_tariff_periods(ax, include_labels=False):
    """Destaca, no fundo do gráfico, ponta e fora de ponta."""
    peak_start = float(TARIFF["peak_start_hour"])
    peak_end = float(TARIFF["peak_end_hour"])

    offpeak_label = None
    peak_label = None
    if include_labels:
        offpeak_label = (
            "Fora de ponta "
            f"(00h-{peak_start:02.0f}h e {peak_end:02.0f}h-24h)"
        )
        peak_label = (
            f"Horário de ponta ({peak_start:02.0f}h-{peak_end:02.0f}h)"
        )

    # O fundo azul representa todo o dia fora de ponta. A faixa laranja
    # sobreposta substitui visualmente apenas o intervalo de ponta.
    ax.axvspan(
        0.0,
        24.0,
        color="lightskyblue",
        alpha=0.07,
        zorder=-20,
        label=offpeak_label,
    )
    ax.axvspan(
        peak_start,
        peak_end,
        color="darkorange",
        alpha=0.13,
        zorder=-19,
        label=peak_label,
    )
    ax.axvline(
        peak_start, color="darkorange", alpha=0.45,
        linewidth=1.0, linestyle="--", zorder=-18,
    )
    ax.axvline(
        peak_end, color="darkorange", alpha=0.45,
        linewidth=1.0, linestyle="--", zorder=-18,
    )


def plot_results(results):
    """
    Gera uma figura didática por cenário.

    O painel superior apresenta o despacho de potência.
    O painel inferior separa backlog e SOC das curvas de potência.
    """
    for config, result in results.items():
        df = result["df"]
        summary = result["summary"]

        fig, (ax_power, ax_state) = plt.subplots(
            2,
            1,
            figsize=(14, 9),
            sharex=True,
            gridspec_kw={"height_ratios": [3.2, 1.2]},
        )

        _shade_tariff_periods(ax_power, include_labels=True)
        _shade_tariff_periods(ax_state)

        ax_power.plot(
            df["hour"], df["request_kw"],
            color="black", linewidth=1.5, linestyle=":",
            label="Demanda EV solicitada",
        )
        ax_power.plot(
            df["hour"], df["served_kw"],
            color="tab:blue", linewidth=2.2,
            label="Demanda EV atendida",
        )
        ax_power.plot(
            df["hour"], df["local_load_kw"],
            color="tab:brown", linewidth=1.6, linestyle="-.",
            label="Carga local",
        )
        ax_power.plot(
            df["hour"], df["grid_import_kw"],
            color="tab:green", linewidth=2.0,
            label="Importação da rede",
        )
        ax_power.plot(
            df["hour"], df["grid_limit_kw"],
            color="tab:red", linewidth=1.5, linestyle="--",
            label="Limite físico da rede",
        )
        ax_power.axhline(
            summary.get("contracted_demand_kw", 0.0),
            color="firebrick",
            linewidth=1.5,
            linestyle=":",
            label="Demanda contratada ótima",
        )

        if df["pv_avail_kw"].sum() > 1e-6:
            ax_power.plot(
                df["hour"], df["pv_avail_kw"],
                color="goldenrod", linewidth=2.0, linestyle="--",
                label="FV potencial - perfil representativo",
            )
            ax_power.plot(
                df["hour"], df["pv_used_kw"],
                color="darkorange", linewidth=2.5,
                label="FV aproveitado",
            )
            ax_power.fill_between(
                df["hour"],
                df["pv_used_kw"],
                df["pv_avail_kw"],
                where=(df["pv_avail_kw"] > df["pv_used_kw"]),
                color="gold",
                alpha=0.25,
                label="Curtailment FV",
            )

        if df["bess_ch_kw"].sum() > 1e-6:
            ax_power.plot(
                df["hour"], df["bess_ch_kw"],
                color="tab:pink", linewidth=1.8,
                label="Carga BESS",
            )
        if df["bess_dis_kw"].sum() > 1e-6:
            ax_power.plot(
                df["hour"], df["bess_dis_kw"],
                color="tab:purple", linewidth=2.0,
                label="Descarga BESS",
            )

        ax_power.fill_between(
            df["hour"],
            df["served_kw"],
            df["request_kw"],
            where=(df["request_kw"] > df["served_kw"]),
            color="red",
            alpha=0.10,
            label="Demanda EV postergada",
        )

        pv_available = summary.get("pv_available_energy_kwh", 0.0)
        pv_used = summary.get("pv_used_energy_kwh", 0.0)
        pv_curtailed = summary.get("pv_curtailed_energy_kwh", 0.0)
        pv_curtailment_ratio = summary.get(
            "pv_curtailment_ratio", 0.0
        )
        title = (
            f"{config} | FV = {summary.get('pv_size_kw', 0.0):.1f} "
            "kWp DC | "
            f"BESS = {summary.get('bess_e_kwh', 0.0):.1f} kWh / "
            f"{summary.get('bess_p_kw', 0.0):.1f} kW | "
            f"Atendimento EV = "
            f"{100 * summary.get('served_ratio', 0.0):.1f}%"
        )
        if pv_available > 1e-6:
            title += (
                "\nFV potencial = "
                f"{pv_available:.1f} kWh | "
                f"Aproveitado = {pv_used:.1f} kWh | "
                f"Curtailment = {pv_curtailed:.1f} kWh "
                f"({100 * pv_curtailment_ratio:.1f}%)"
            )

        ax_power.set_title(title, fontsize=12)
        ax_power.set_ylabel("Potência [kW]")
        ax_power.grid(True, alpha=0.25)
        ax_power.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.10),
            fontsize=8,
            ncol=4,
        )

        ax_state.plot(
            df["hour"], df["backlog_kwh"],
            color="darkviolet", linewidth=2.2,
            label="Backlog EV",
        )
        if "expired_unserved_kwh" in df:
            ax_state.step(
                df["hour"],
                df["expired_unserved_kwh"].cumsum(),
                where="mid",
                color="firebrick",
                linewidth=1.8,
                label="Não atendida após 2 h",
            )
        ax_state.set_ylabel("Backlog EV [kWh]", color="darkviolet")
        ax_state.tick_params(axis="y", labelcolor="darkviolet")
        ax_state.grid(True, alpha=0.25)

        state_handles, state_labels = ax_state.get_legend_handles_labels()
        if df["soc_kwh"].max() > 1e-6:
            ax_soc = ax_state.twinx()
            ax_soc.plot(
                df["hour"], df["soc_kwh"],
                color="teal", linewidth=2.0,
                label="SOC do BESS",
            )
            ax_soc.set_ylabel("SOC BESS [kWh]", color="teal")
            ax_soc.tick_params(axis="y", labelcolor="teal")
            soc_handles, soc_labels = ax_soc.get_legend_handles_labels()
            state_handles += soc_handles
            state_labels += soc_labels

        ax_state.legend(
            state_handles,
            state_labels,
            loc="upper left",
            fontsize=8,
        )
        ax_state.set_xlabel("Hora")
        ax_state.set_xlim(0.0, 24.0)
        hour_ticks = np.arange(0.0, 25.0, 1.0)
        ax_state.set_xticks(hour_ticks)
        ax_state.set_xticklabels(
            [f"{int(hour):02d}h" for hour in hour_ticks],
            rotation=45,
            ha="right",
            fontsize=8,
        )

        fig.subplots_adjust(
            top=0.90,
            bottom=0.09,
            left=0.08,
            right=0.92,
            hspace=0.42,
        )
        fig.savefig(
            OUTPUT_DIR / f"scenario_{config}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.show()
        plt.close(fig)


def plot_annual_results(results):
    """Gera painéis técnicos, energéticos e financeiros anuais."""
    month_labels = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    ]

    for config, result in results.items():
        df = result["df"].copy()
        summary = result["summary"]
        if "timestamp" not in df:
            raise ValueError(
                "O gráfico anual exige timestamps no resultado."
            )

        dt_h = float(summary["horizon_h"]) / len(df)
        df["month"] = df["timestamp"].dt.month
        energy_columns = [
            "request_kw", "served_kw", "grid_import_kw",
            "pv_used_kw", "pv_curt_kw",
        ]
        monthly_energy = (
            df.groupby("month")[energy_columns].sum() * dt_h / 1000.0
        )
        monthly_peak = df.groupby("month")["grid_import_kw"].max()
        monthly_service = (
            monthly_energy["served_kw"]
            / monthly_energy["request_kw"].replace(0.0, np.nan)
            * 100.0
        ).fillna(100.0)
        monthly_hours = df.groupby("month").size() * dt_h
        horizon_hours = float(monthly_hours.sum())
        sizing_text = (
            f"FV = {summary.get('pv_size_kw', 0.0):.1f} kWp DC | "
            f"BESS = {summary.get('bess_e_kwh', 0.0):.1f} kWh / "
            f"{summary.get('bess_p_kw', 0.0):.1f} kW | "
            f"Duração = {summary.get('bess_duration_h', 0.0):.2f} h | "
            "Demanda contratada = "
            f"{summary.get('contracted_demand_kw', 0.0):.1f} kW"
        )

        fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
        x = np.arange(1, 13)

        axes[0].plot(
            x, monthly_energy["request_kw"], marker="o",
            color="black", linestyle=":", label="EV solicitada",
        )
        axes[0].plot(
            x, monthly_energy["served_kw"], marker="o",
            color="tab:blue", linewidth=2.2, label="EV atendida",
        )
        axes[0].plot(
            x, monthly_energy["grid_import_kw"], marker="s",
            color="tab:green", label="Importação da rede",
        )
        if monthly_energy["pv_used_kw"].sum() > 1e-6:
            axes[0].plot(
                x, monthly_energy["pv_used_kw"], marker="^",
                color="darkorange", label="FV aproveitado",
            )
        axes[0].set_ylabel("Energia [MWh/mês]")
        axes[0].set_title(
            f"{config} — resumo anual | Atendimento EV = "
            f"{100 * summary.get('served_ratio', 0.0):.2f}%\n"
            f"{sizing_text}"
        )
        axes[0].grid(True, alpha=0.25)
        axes[0].legend(ncol=4, fontsize=8)

        axes[1].plot(
            x, monthly_peak.reindex(x).values,
            marker="o", color="tab:green", linewidth=2.0,
            label="Pico mensal importado",
        )
        axes[1].axhline(
            summary.get("contracted_demand_kw", 0.0),
            color="firebrick", linestyle="--",
            label="Demanda contratada ótima",
        )
        axes[1].set_ylabel("Potência [kW]")
        axes[1].grid(True, alpha=0.25)
        axes[1].legend(fontsize=8)

        axes[2].bar(
            x, monthly_service.reindex(x).values,
            color="tab:blue", alpha=0.75,
            label="Atendimento EV",
        )
        axes[2].set_ylabel("Atendimento [%]")
        axes[2].set_ylim(0.0, 105.0)
        axes[2].set_xlabel("Mês")
        axes[2].grid(True, axis="y", alpha=0.25)
        axes[2].set_xticks(x)
        axes[2].set_xticklabels(month_labels)

        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / f"scenario_annual_{config}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)

        # ====================================================
        # RECURSOS FV E BESS
        # ====================================================
        resource_columns = [
            "pv_avail_kw", "pv_used_kw", "pv_curt_kw",
            "bess_ch_kw", "bess_dis_kw",
        ]
        monthly_resources = (
            df.groupby("month")[resource_columns].sum() * dt_h / 1000.0
        )
        fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

        axes[0].plot(
            x, monthly_resources["pv_avail_kw"], marker="o",
            color="goldenrod", linestyle="--", label="FV potencial",
        )
        axes[0].plot(
            x, monthly_resources["pv_used_kw"], marker="o",
            color="darkorange", linewidth=2.2, label="FV aproveitado",
        )
        axes[0].bar(
            x, monthly_resources["pv_curt_kw"], alpha=0.35,
            color="gold", label="Curtailment FV",
        )
        axes[0].set_ylabel("Energia FV [MWh/mês]")
        axes[0].set_title(
            f"{config} — recursos FV e BESS\n{sizing_text}"
        )
        axes[0].grid(True, alpha=0.25)
        axes[0].legend(ncol=3, fontsize=8)

        axes[1].plot(
            x, monthly_resources["bess_ch_kw"], marker="o",
            color="tab:pink", label="Carga BESS",
        )
        axes[1].plot(
            x, monthly_resources["bess_dis_kw"], marker="o",
            color="tab:purple", label="Descarga BESS",
        )
        axes[1].set_ylabel("Energia BESS [MWh/mês]")
        axes[1].set_xlabel("Mês")
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(month_labels)
        axes[1].grid(True, alpha=0.25)
        axes[1].legend(fontsize=8)

        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / f"annual_resources_{config}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)

        # ====================================================
        # CUSTOS E RECEITAS MENSAIS
        # ====================================================
        df["grid_energy_cost_brl"] = (
            df["grid_import_kw"] * df["price_grid"] * dt_h
        )
        net_price = (
            summary.get("charging_net_revenue_brl", 0.0)
            / summary.get("served_energy_kwh", 1.0)
            if summary.get("served_energy_kwh", 0.0) > 1e-9
            else 0.0
        )
        df["charging_net_revenue_brl"] = (
            df["served_kw"] * dt_h * net_price
        )
        df["bess_throughput_kwh"] = (
            df["bess_ch_kw"] + df["bess_dis_kw"]
        ) * dt_h

        monthly_financial = df.groupby("month")[[
            "grid_energy_cost_brl",
            "charging_net_revenue_brl",
            "bess_throughput_kwh",
        ]].sum()
        month_fraction = monthly_hours / horizon_hours
        monthly_financial["demand_cost_brl"] = (
            summary.get("demand_cost_in_horizon_brl", 0.0)
            * month_fraction
        )
        monthly_financial["fixed_investment_om_brl"] = (
            summary.get("investment_cost_in_horizon_brl", 0.0)
            * month_fraction
        )
        annual_throughput = monthly_financial["bess_throughput_kwh"].sum()
        monthly_financial["degradation_cost_brl"] = (
            summary.get("bess_degradation_cost_brl", 0.0)
            * monthly_financial["bess_throughput_kwh"]
            / annual_throughput
            if annual_throughput > 1e-9
            else 0.0
        )
        cost_columns = [
            "grid_energy_cost_brl", "demand_cost_brl",
            "fixed_investment_om_brl", "degradation_cost_brl",
        ]
        monthly_financial["net_cost_brl"] = (
            monthly_financial[cost_columns].sum(axis=1)
            - monthly_financial["charging_net_revenue_brl"]
        )
        monthly_financial.to_csv(
            OUTPUT_DIR / f"annual_financial_{config}.csv",
            index_label="month",
        )

        fig, (ax_components, ax_net) = plt.subplots(
            2, 1, figsize=(14, 9), sharex=True,
        )
        bottom = np.zeros(12)
        component_style = [
            ("grid_energy_cost_brl", "Energia da rede", "tab:green"),
            ("demand_cost_brl", "Demanda contratada", "firebrick"),
            ("fixed_investment_om_brl", "CAPEX anualizado + O&M", "steelblue"),
            ("degradation_cost_brl", "Degradação BESS", "tab:purple"),
        ]
        for column, label, color in component_style:
            values = monthly_financial[column].reindex(x).fillna(0.0).values
            ax_components.bar(x, values, bottom=bottom, label=label, color=color)
            bottom += values
        revenue = monthly_financial[
            "charging_net_revenue_brl"
        ].reindex(x).fillna(0.0).values
        ax_components.plot(
            x, revenue, color="black", marker="o", linewidth=2.0,
            label="Receita líquida das recargas",
        )
        ax_components.set_ylabel("Valor [R$/mês]")
        ax_components.set_title(
            f"{config} — composição financeira mensal\n{sizing_text}"
        )
        ax_components.grid(True, axis="y", alpha=0.25)
        ax_components.legend(ncol=3, fontsize=8)

        net_values = monthly_financial[
            "net_cost_brl"
        ].reindex(x).fillna(0.0).values
        net_colors = ["seagreen" if value < 0.0 else "indianred" for value in net_values]
        ax_net.bar(x, net_values, color=net_colors)
        ax_net.axhline(0.0, color="black", linewidth=0.9)
        ax_net.set_ylabel("Custo líquido [R$/mês]")
        ax_net.set_xlabel("Mês")
        ax_net.set_xticks(x)
        ax_net.set_xticklabels(month_labels)
        ax_net.grid(True, axis="y", alpha=0.25)

        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / f"annual_financial_{config}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)

        # ====================================================
        # OPERAÇÃO ANUAL E SEMANA CRÍTICA
        # ====================================================
        daily = df.set_index("timestamp").resample("D").agg({
            "request_kw": "sum",
            "served_kw": "sum",
            "grid_import_kw": "sum",
            "soc_kwh": ["min", "mean", "max"],
        })
        daily.columns = ["_".join(column) for column in daily.columns]
        daily_energy_request = daily["request_kw_sum"] * dt_h
        critical_day = daily_energy_request.idxmax()
        critical_start = critical_day - pd.Timedelta(days=3)
        critical_end = critical_start + pd.Timedelta(days=7)
        week = df[
            (df["timestamp"] >= critical_start)
            & (df["timestamp"] < critical_end)
        ].copy()
        week_hour = np.arange(len(week)) * dt_h

        fig, (ax_year, ax_week) = plt.subplots(2, 1, figsize=(15, 9))
        day_axis = daily.index
        ax_year.fill_between(
            day_axis,
            daily["soc_kwh_min"],
            daily["soc_kwh_max"],
            color="teal", alpha=0.18, label="Faixa diária do SOC",
        )
        ax_year.plot(
            day_axis, daily["soc_kwh_mean"],
            color="teal", linewidth=1.2, label="SOC médio diário",
        )
        ax_year.set_ylabel("SOC BESS [kWh]")
        ax_year.set_title(
            f"{config} — operação anual e semana crítica\n{sizing_text}"
        )
        ax_year.grid(True, alpha=0.25)
        ax_year.legend(fontsize=8)

        ax_week.plot(week_hour, week["request_kw"], color="black", linestyle=":", label="EV solicitada")
        ax_week.plot(week_hour, week["served_kw"], color="tab:blue", label="EV atendida")
        ax_week.plot(week_hour, week["grid_import_kw"], color="tab:green", label="Rede")
        ax_week.plot(week_hour, week["pv_used_kw"], color="darkorange", label="FV aproveitado")
        ax_week.plot(week_hour, week["bess_ch_kw"], color="tab:pink", label="Carga BESS")
        ax_week.plot(week_hour, week["bess_dis_kw"], color="tab:purple", label="Descarga BESS")
        ax_week.set_xlabel(
            "Horas da semana crítica iniciada em "
            f"{critical_start.strftime('%d/%m/%Y')}"
        )
        ax_week.set_ylabel("Potência [kW]")
        ax_week.grid(True, alpha=0.25)
        ax_week.legend(ncol=3, fontsize=8)

        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / f"annual_operation_{config}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)


def plot_sensitivity(sens_df):
    """
    Plota sensibilidade do atendimento ao limite da rede.
    """

    plt.figure(figsize=(10, 5))

    for config in sens_df["config"].unique():

        sub = sens_df[
            sens_df["config"] == config
        ].sort_values("grid_limit_test_kw")

        if "is_feasible" in sub.columns:
            feasible = sub[sub["is_feasible"].astype(bool)]
        else:
            feasible = sub

        if not feasible.empty:
            plt.plot(
                feasible["grid_limit_test_kw"],
                feasible["served_ratio"],
                marker="o",
                label=config,
            )

        if "is_feasible" in sub.columns:
            infeasible = sub[~sub["is_feasible"].astype(bool)]
            if not infeasible.empty:
                plt.scatter(
                    infeasible["grid_limit_test_kw"],
                    [-0.04] * len(infeasible),
                    marker="x",
                    s=55,
                    label=f"{config} (inviável)",
                )

    plt.xlabel("Limite da rede [kW]")
    plt.ylabel("Fração de energia EV atendida")
    plt.title("Sensibilidade do atendimento ao limite da rede")
    plt.ylim(-0.08, 1.05)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(
        OUTPUT_DIR / "sensitivity_grid_limit.png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.show()


def plot_scenario_comparison(summary_df):
    """
    Compara custo líquido e atendimento dos cenários-base.

    A recomendação segue a política selecionada: no modo econômico,
    menor custo entre soluções que cumprem as metas; no modo legado,
    maior atendimento EV e, em empate técnico, menor custo líquido.
    O custo líquido corresponde à função objetivo econômica, isto é,
    custos no horizonte menos a receita líquida das recargas.
    """
    comparison = summary_df.copy()
    if "is_feasible" in comparison:
        comparison = comparison[
            comparison["is_feasible"].astype(bool)
        ].copy()

    if comparison.empty:
        return None

    comparison = comparison.sort_values("config").reset_index(drop=True)
    maximum_service = comparison["served_ratio"].max()
    service_tolerance = 1e-6
    finalists = comparison[
        comparison["served_ratio"]
        >= maximum_service - service_tolerance
    ]
    if "service_mode" in comparison and comparison["service_mode"].eq("economic").all():
        finalists = comparison
    best_index = finalists["objective_value"].idxmin()
    best = comparison.loc[best_index]

    display_names = {
        "SMART": "SMART",
        "SMART_PV": "SMART + FV",
        "SMART_BESS": "SMART + BESS",
        "SMART_PV_BESS": "SMART + FV + BESS",
    }
    labels = [
        display_names.get(config, config)
        for config in comparison["config"]
    ]
    positions = np.arange(len(labels))
    colors = [
        "seagreen" if index == best_index else "steelblue"
        for index in comparison.index
    ]

    fig, (ax_cost, ax_service) = plt.subplots(
        1,
        2,
        figsize=(14, 7),
        gridspec_kw={"width_ratios": [1.0, 1.0]},
    )

    costs = comparison["objective_value"].to_numpy()
    cost_bars = ax_cost.bar(positions, costs, color=colors)
    ax_cost.axhline(0.0, color="black", linewidth=0.9)
    ax_cost.set_title(
        "Custo líquido no horizonte\n"
        "(valor negativo = benefício líquido)"
    )
    ax_cost.set_ylabel("Custo líquido [R$]")
    ax_cost.set_xticks(positions, labels, rotation=20)
    ax_cost.grid(axis="y", alpha=0.25)
    ax_cost.bar_label(
        cost_bars,
        labels=[f"R$ {value:,.0f}" for value in costs],
        padding=4,
        fontsize=9,
    )

    service_percent = 100.0 * comparison["served_ratio"].to_numpy()
    service_bars = ax_service.bar(
        positions,
        service_percent,
        color=colors,
    )
    ax_service.set_title("Atendimento da demanda EV")
    ax_service.set_ylabel("Energia solicitada atendida [%]")
    ax_service.set_xticks(positions, labels, rotation=20)
    ax_service.set_ylim(
        0.0,
        max(105.0, service_percent.max() * 1.12),
    )
    ax_service.grid(axis="y", alpha=0.25)
    ax_service.bar_label(
        service_bars,
        labels=[f"{value:.1f}%" for value in service_percent],
        padding=4,
        fontsize=9,
    )

    reason = (
        f"Recomendação: "
        f"{display_names.get(best['config'], best['config'])}\n"
        f"Atendimento = {100 * best['served_ratio']:.1f}% "
        f"({best['served_energy_kwh']:.1f} kWh de "
        f"{best['requested_energy_kwh']:.1f} kWh)\n"
        f"Custo líquido = R$ {best['objective_value']:,.2f}\n"
        + ("Critério: menor custo respeitando as metas de atendimento."
           if best.get("service_mode") == "economic"
           else "Critério: maior atendimento; menor custo em empate técnico.")
    )
    fig.text(
        0.5,
        0.02,
        reason,
        ha="center",
        va="bottom",
        fontsize=10,
        bbox={
            "boxstyle": "round,pad=0.6",
            "facecolor": "honeydew",
            "edgecolor": "seagreen",
        },
    )
    fig.suptitle(
        "Comparação técnico-econômica dos modos de operação",
        fontsize=14,
    )
    fig.subplots_adjust(
        top=0.86,
        bottom=0.28,
        left=0.08,
        right=0.97,
        wspace=0.25,
    )
    is_annual = (
        "simulation_mode" in comparison
        and comparison["simulation_mode"].eq("annual").all()
    )
    suffix = "annual" if is_annual else "daily"
    output_path = OUTPUT_DIR / f"comparison_scenarios_{suffix}.png"
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return {
        "best_config": str(best["config"]),
        "served_ratio": float(best["served_ratio"]),
        "objective_value": float(best["objective_value"]),
        "output_path": output_path,
    }


def plot_annual_financial_comparison(summary_df):
    """Compara componentes anuais de custo, receita e resultado líquido."""
    comparison = summary_df.copy()
    if "is_feasible" in comparison:
        comparison = comparison[comparison["is_feasible"].astype(bool)]
    if comparison.empty:
        return None

    comparison = comparison.sort_values("config").reset_index(drop=True)
    labels = comparison["config"].str.replace("_", " + ", regex=False)
    x = np.arange(len(comparison))
    width = 0.62
    components = [
        ("grid_energy_cost_brl", "Energia da rede", "tab:green"),
        ("demand_cost_in_horizon_brl", "Demanda", "firebrick"),
        ("investment_cost_in_horizon_brl", "CAPEX anualizado + O&M", "steelblue"),
        ("bess_degradation_cost_brl", "Degradação BESS", "tab:purple"),
    ]

    fig, ax = plt.subplots(figsize=(14, 7))
    bottom = np.zeros(len(comparison))
    for column, label, color in components:
        values = comparison[column].fillna(0.0).to_numpy()
        ax.bar(x, values, width, bottom=bottom, label=label, color=color)
        bottom += values

    revenue = comparison["charging_net_revenue_brl"].fillna(0.0).to_numpy()
    ax.bar(
        x, -revenue, width, color="goldenrod", alpha=0.75,
        label="Receita líquida das recargas",
    )
    net = comparison["objective_value"].to_numpy()
    ax.scatter(
        x, net, color="black", marker="D", s=55, zorder=5,
        label="Custo líquido anual",
    )
    for position, value in zip(x, net):
        ax.annotate(
            f"R$ {value:,.0f}", (position, value),
            xytext=(0, 8 if value >= 0 else -16),
            textcoords="offset points", ha="center", fontsize=8,
        )

    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15)
    ax.set_ylabel("Valor anual [R$]")
    ax.set_title("Comparação financeira anual dos modos")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    output_path = OUTPUT_DIR / "comparison_financial_annual.png"
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path
