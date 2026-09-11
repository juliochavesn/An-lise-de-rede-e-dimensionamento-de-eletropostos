"""Gráficos auditáveis do despacho resolvido. Não reotimiza ou altera limites."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

REQUIRED = ["hour", "request_kw", "served_kw", "local_load_kw", "grid_limit_kw", "grid_import_kw", "grid_export_kw",
            "pv_avail_kw", "pv_used_kw", "pv_curt_kw", "bess_ch_kw", "bess_dis_kw", "soc_kwh", "backlog_kwh", "expired_unserved_kwh"]


def finite(value):
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def prepare_dispatch(frame, summary):
    if str(summary.get("solve_status", "")) != "solved":
        raise ValueError("Sem solução resolvida: gráficos de despacho não disponíveis.")
    missing = set(REQUIRED) - set(frame)
    if missing or frame.empty:
        raise ValueError("Série técnica ausente/incompleta: " + ", ".join(sorted(missing)))
    df = frame.copy().reset_index(drop=True)
    for col in REQUIRED:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if not np.isfinite(df[REQUIRED].to_numpy(dtype=float)).all():
        raise ValueError("Série técnica contém valores ausentes ou não finitos; não foram convertidos em zero.")
    step = finite(summary.get("dt_h"))
    differences = np.diff(df["hour"].to_numpy())
    if step is None and len(differences):
        step = float(differences[0])
    if step is None or step <= 0 or (len(differences) and not np.allclose(differences, step, rtol=1e-8, atol=1e-8)):
        raise ValueError("Passo temporal inválido, irregular ou não informado.")
    start = df["hour"] - step / 2
    if (start < -1e-8).any():
        raise ValueError("Horas incompatíveis com centros dos intervalos.")
    df["dt_h"] = step
    df["interval_start_h"] = start
    df["interval_end_h"] = start + step
    df["day_index"] = np.floor((start + 1e-8) / 24).astype(int)
    if "timestamp" in df:
        stamps = pd.to_datetime(df["timestamp"], errors="coerce")
        if stamps.isna().any() or not stamps.is_monotonic_increasing or stamps.duplicated().any():
            raise ValueError("Datas da série inválidas ou duplicadas.")
        if len(stamps) > 1 and not np.allclose(stamps.diff().dropna().dt.total_seconds() / 3600, step):
            raise ValueError("Datas incompatíveis com o passo temporal da série.")
        df["timestamp"] = stamps
        df["day_label"] = stamps.dt.strftime("%Y-%m-%d")
    else:
        df["day_label"] = df["day_index"].map(lambda d: f"Dia {d + 1}")
    df["total_served_load_kw"] = df["local_load_kw"] + df["served_kw"]
    df["power_balance_residual_kw"] = (df["grid_import_kw"] + df["pv_used_kw"] + df["bess_dis_kw"]
        - df["local_load_kw"] - df["served_kw"] - df["bess_ch_kw"] - df["grid_export_kw"])
    df["pv_balance_residual_kw"] = df["pv_avail_kw"] - df["pv_used_kw"] - df["pv_curt_kw"]
    df["grid_margin_kw"] = df["grid_limit_kw"] - df["grid_import_kw"]
    df["grid_utilization_pct"] = df["grid_import_kw"].div(df["grid_limit_kw"].where(df["grid_limit_kw"] > 1e-9)) * 100
    capacity = finite(summary.get("bess_e_kwh"))
    df["soc_pct"] = df["soc_kwh"] / capacity * 100 if capacity is not None and capacity > 1e-6 else np.nan
    df["soc_start_kwh"] = df["soc_kwh"].shift(1)
    init = finite(summary.get("bess_soc_init_frac"))
    if init is not None and capacity is not None:
        df.loc[df.index[0], "soc_start_kwh"] = init * capacity
    df["soc_start_pct"] = df["soc_start_kwh"] / capacity * 100 if capacity is not None and capacity > 1e-6 else np.nan
    return df


def metrics(df):
    energy = lambda col: float((df[col] * df["dt_h"]).sum())
    peak_row = df.loc[df["grid_import_kw"].idxmax()]
    return {"horizon_h": float(df["dt_h"].sum()), "local_energy_kwh": energy("local_load_kw"),
            "ev_requested_kwh": energy("request_kw"), "ev_served_kwh": energy("served_kw"),
            "grid_import_kwh": energy("grid_import_kw"), "grid_export_kwh": energy("grid_export_kw"),
            "pv_available_kwh": energy("pv_avail_kw"), "pv_used_kwh": energy("pv_used_kw"), "pv_curtailed_kwh": energy("pv_curt_kw"),
            "bess_charge_kwh": energy("bess_ch_kw"), "bess_discharge_kwh": energy("bess_dis_kw"),
            # These are energy/state columns: do not integrate them a second time.
            "expired_unserved_kwh": float(df["expired_unserved_kwh"].sum()),
            "maximum_backlog_kwh": float(df["backlog_kwh"].max()),
            "grid_peak_kw": float(peak_row["grid_import_kw"]), "grid_peak_day": str(peak_row["day_label"]),
            "minimum_grid_margin_kw": float(df["grid_margin_kw"].min()),
            "grid_limit_exceedance_intervals": int((df["grid_margin_kw"] < -1e-5).sum()),
            "maximum_power_balance_error_kw": float(df["power_balance_residual_kw"].abs().max()),
            "maximum_pv_balance_error_kw": float(df["pv_balance_residual_kw"].abs().max()),
            "soc_min_pct": finite(df["soc_pct"].min()), "soc_max_pct": finite(df["soc_pct"].max())}


def dispatch_figure(df, summary, day_label):
    selected = df[df["day_label"] == day_label].copy()
    if selected.empty:
        raise ValueError("Dia não encontrado na série.")
    fig = Figure(figsize=(15, 16), layout="constrained")
    axes = fig.subplots(4, 2).ravel()
    base = float(selected["day_index"].iloc[0]) * 24
    x = selected["interval_start_h"].to_numpy() - base
    end = float(selected["interval_end_h"].iloc[-1]) - base
    end_x = selected["interval_end_h"].to_numpy() - base

    def power(ax, column, label, color, style="-"):
        y = selected[column].to_numpy()
        ax.step(np.r_[x, end], np.r_[y, y[-1]], where="post", label=label, color=color, linestyle=style, linewidth=1.5)

    for col, label, color in (("local_load_kw", "Carga local", "#475569"), ("served_kw", "Recarga atendida", "#2563eb"),
                              ("request_kw", "Recarga solicitada", "#f97316"), ("total_served_load_kw", "Local + recarga atendida", "#0f766e")):
        power(axes[0], col, label, color, "--" if col == "request_kw" else "-")
    axes[0].set_title("Carga local e atendimento de veículos")
    for col, label, color in (("grid_import_kw", "Importação", "#16a34a"), ("grid_export_kw", "Exportação", "#9333ea")):
        power(axes[1], col, label, color)
    contracted = finite(summary.get("contracted_demand_kw"))
    if contracted is not None:
        axes[1].axhline(contracted, color="#dc2626", linestyle="--", label="Demanda contratada otimizada")
    axes[1].set_title("Trocas com a rede (limite técnico no painel de utilização)")
    for col, label, color in (("pv_used_kw", "FV utilizado", "#16a34a"), ("pv_avail_kw", "FV disponível", "#f59e0b"), ("pv_curt_kw", "FV cortado", "#dc2626")):
        power(axes[2], col, label, color, "--" if col == "pv_avail_kw" else "-")
    axes[2].set_title("Geração fotovoltaica — PV/FV")
    for col, label, color in (("bess_ch_kw", "Carga do BESS", "#2563eb"), ("bess_dis_kw", "Descarga do BESS", "#9333ea")):
        power(axes[3], col, label, color)
    axes[3].set_title("Potência da bateria (ambos os sentidos positivos)")
    if selected["soc_pct"].notna().any():
        state_x, state_y = end_x, selected["soc_pct"].to_numpy()
        if pd.notna(selected["soc_start_pct"].iloc[0]):
            state_x = np.r_[x[0], state_x]
            state_y = np.r_[selected["soc_start_pct"].iloc[0], state_y]
        axes[4].plot(state_x, state_y, color="#0f766e", label="SOC / capacidade nominal")
        for key, label in (("bess_soc_min_frac", "SOC mínimo"), ("bess_soc_max_frac", "SOC máximo")):
            val = finite(summary.get(key))
            if val is not None: axes[4].axhline(val * 100, color="#94a3b8", linestyle="--", label=label)
        axes[4].set_ylim(min(0, float(selected["soc_pct"].min())), max(100, float(selected["soc_pct"].max())))
    else:
        axes[4].text(.5, .5, "BESS não dimensionado ou capacidade nominal ausente\nSOC percentual não definido", ha="center", va="center", transform=axes[4].transAxes)
    axes[4].set_title("Estado de carga — valores ao fim dos intervalos")
    axes[4].set_ylabel("SOC (%)")
    axes[5].plot(end_x, selected["backlog_kwh"], color="#2563eb", label="Energia em espera (estado)")
    axes[5].bar(x, selected["expired_unserved_kwh"], width=selected["dt_h"], align="edge", alpha=.5, color="#ef4444", label="Energia expirada no intervalo")
    axes[5].set_title("Qualidade do atendimento de recarga")
    axes[5].set_ylabel("Energia (kWh)")
    axes[5].set_ylim(0, max(1, selected[["backlog_kwh", "expired_unserved_kwh"]].max().max() * 1.1))
    power(axes[6], "grid_utilization_pct", "Importação / limite técnico", "#2563eb")
    axes[6].axhline(100, color="#ef4444", linestyle="--", label="100% do limite técnico")
    axes[6].set_ylabel("Utilização (%)")
    axes[6].set_title(f"Limite técnico aplicado: {selected['grid_limit_kw'].min():.1f}–{selected['grid_limit_kw'].max():.1f} kW")
    power(axes[7], "power_balance_residual_kw", "Resíduo do balanço do barramento", "#0f766e")
    power(axes[7], "pv_balance_residual_kw", "Resíduo FV", "#f59e0b")
    axes[7].set_title("Verificação do balanço de potência (ideal: zero)")
    amplitude = max(1.2e-4, selected[["power_balance_residual_kw", "pv_balance_residual_kw"]].abs().max().max() * 1.2)
    axes[7].set_ylim(-amplitude, amplitude)
    axes[7].axhline(1e-4, color="#94a3b8", linestyle=":", label="Referência de tolerância ±0,0001 kW")
    axes[7].axhline(-1e-4, color="#94a3b8", linestyle=":")
    for i, ax in enumerate(axes):
        if i in (0, 1, 2, 3, 7): ax.set_ylabel("Potência (kW)")
        ax.set_xlabel("Hora do dia")
        ax.set_xlim(0, 24)
        ax.set_xticks(np.arange(0, 25, 3))
        ax.grid(True, alpha=.2)
        if ax.get_legend_handles_labels()[0]: ax.legend(fontsize=8, loc="best")
    size = lambda key: f"{finite(summary.get(key)):.1f}" if finite(summary.get(key)) is not None else "—"
    fig.suptitle(f"{summary.get('config', 'Configuração')} · operação otimizada · {day_label}\nFV {size('pv_size_kw')} kW | BESS {size('bess_e_kwh')} kWh", fontsize=13)
    return fig


def overview_figure(df, summary):
    fig = Figure(figsize=(14, 9), layout="constrained")
    axes = fig.subplots(2, 2).ravel()
    if "timestamp" in df:
        groups = df["timestamp"].dt.strftime("%Y-%m")
    else:
        groups = df["day_label"]
    energies = df[["local_load_kw", "served_kw", "grid_import_kw", "pv_used_kw"]].mul(df["dt_h"], axis=0).groupby(groups, sort=False).sum()
    positions = np.arange(len(energies))
    for i, (col, label) in enumerate((("local_load_kw", "Carga local"), ("served_kw", "Recarga atendida"), ("grid_import_kw", "Importação"), ("pv_used_kw", "FV utilizado"))):
        axes[0].bar(positions + (i - 1.5) * .2, energies[col], width=.2, label=label)
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(energies.index, rotation=45, ha="right")
    axes[0].set_ylabel("Energia (kWh)")
    axes[0].set_title("Energias por período — barras independentes, não somar fontes e cargas")
    descending = np.sort(df["grid_import_kw"].to_numpy())[::-1]
    axes[1].step(np.arange(len(df)) * float(df["dt_h"].iloc[0]), descending, where="post", label="Importação ordenada")
    axes[1].set_xlabel("Horas acumuladas por ordem de potência (não cronológico)")
    axes[1].set_ylabel("Potência (kW)")
    axes[1].set_title("Curva de duração da demanda da rede")
    daily = df.groupby("day_index").agg(soc_min=("soc_pct", "min"), soc_mean=("soc_pct", "mean"), soc_max=("soc_pct", "max"), backlog=("backlog_kwh", "max"), expired=("expired_unserved_kwh", "sum"))
    if daily["soc_mean"].notna().any():
        axes[2].fill_between(daily.index.to_numpy() + 1, daily["soc_min"].to_numpy(), daily["soc_max"].to_numpy(), alpha=.2, label="Faixa min–max diária")
        axes[2].plot(daily.index + 1, daily["soc_mean"], label="Média diária (não capta extremos)")
    else:
        axes[2].text(.5, .5, "SOC percentual não definido", transform=axes[2].transAxes, ha="center")
    axes[2].set_title("SOC ao longo do horizonte")
    axes[2].set_ylabel("SOC (%)")
    axes[2].set_xlabel("Dia da simulação")
    axes[3].plot(daily.index + 1, daily["backlog"], label="Maior espera diária (kWh)")
    axes[3].plot(daily.index + 1, daily["expired"], label="Energia expirada no dia (kWh)")
    axes[3].set_title("Atendimento ao longo do horizonte")
    axes[3].set_ylabel("Energia (kWh)")
    axes[3].set_xlabel("Dia da simulação")
    for ax in axes:
        ax.grid(True, alpha=.2)
        if ax.get_legend_handles_labels()[0]: ax.legend(fontsize=8)
    fig.suptitle(f"{summary.get('config', 'Configuração')} · visão geral do horizonte resolvido")
    return fig


def export_technical_results(frame, summary, output_dir):
    df = prepare_dispatch(frame, summary)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    config = str(summary["config"])
    if config not in ("SMART", "SMART_PV", "SMART_BESS", "SMART_PV_BESS"):
        raise ValueError("Configuração não reconhecida para exportação.")
    values = metrics(df)
    df.to_csv(target / f"technical_dispatch_{config}.csv", index=False)
    (target / f"technical_metrics_{config}.json").write_text(json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    figure = dispatch_figure(df, summary, values["grid_peak_day"])
    figure.savefig(target / f"technical_peak_day_{config}.png", dpi=150)
    figure.clear()
    figure = overview_figure(df, summary)
    figure.savefig(target / f"technical_overview_{config}.png", dpi=150)
    figure.clear()
    from .technical_dashboard import chronological_figure, quality_table
    figure = chronological_figure(df)
    figure.savefig(target / f"technical_chronological_{config}.png", dpi=150)
    figure.clear()
    for period in ("monthly", "daily"):
        quality_table(df, period).to_csv(target / f"service_quality_{period}_{config}.csv")
    return values
