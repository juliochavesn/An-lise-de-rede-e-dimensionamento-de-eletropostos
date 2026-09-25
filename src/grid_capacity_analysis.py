"""Analise permanente dos periodos criticos da capacidade residual."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def _longest_run_hours(mask: pd.Series, interval_hours: float) -> float:
    """Retorna a maior duração consecutiva verdadeira, em horas."""
    values = mask.fillna(False).astype(bool).to_numpy()
    longest = current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return float(longest * interval_hours)


def analyze_capacity_profile(audit: pd.DataFrame, threshold_kw: float,
                             preferred_hour_count: int = 6,
                             zero_tolerance_kw: float = 1e-6):
    """Resume piores dias, horarios recorrentes e janelas robustas."""
    required = {"timestamp", "residual_capacity_kw"}
    missing = required.difference(audit.columns)
    if missing:
        raise ValueError(f"Colunas ausentes na capacidade residual: {sorted(missing)}")
    frame = audit.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["residual_capacity_kw"] = pd.to_numeric(
        frame["residual_capacity_kw"], errors="raise"
    )
    if frame.empty or frame["timestamp"].isna().any():
        raise ValueError("O perfil residual deve possuir timestamps validos.")
    if (frame["residual_capacity_kw"] < 0.0).any():
        raise ValueError("A capacidade residual nao pode ser negativa.")
    threshold_kw = float(threshold_kw)
    preferred_hour_count = int(preferred_hour_count)
    if threshold_kw < 0.0 or not 1 <= preferred_hour_count <= 24:
        raise ValueError("Limiar e numero de horas preferidas invalidos.")

    frame["date"] = frame["timestamp"].dt.date
    frame["month"] = frame["timestamp"].dt.month
    frame["hour"] = frame["timestamp"].dt.hour
    frame["hour_of_day"] = (
        frame["timestamp"].dt.hour
        + frame["timestamp"].dt.minute / 60.0
    )
    frame["is_zero"] = frame["residual_capacity_kw"] <= zero_tolerance_kw
    frame["is_critical"] = frame["residual_capacity_kw"] < threshold_kw
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    deltas = ordered["timestamp"].diff().dt.total_seconds().div(3600.0)
    positive_deltas = deltas[deltas > 0]
    interval_hours = float(positive_deltas.median()) if not positive_deltas.empty else 1.0
    residual = frame["residual_capacity_kw"]

    daily = frame.groupby("date")["residual_capacity_kw"].agg(
        minimum_kw="min", mean_kw="mean", maximum_kw="max"
    )
    daily["zero_intervals"] = frame.groupby("date")["is_zero"].sum()
    daily["critical_intervals"] = frame.groupby("date")["is_critical"].sum()
    daily = daily.sort_values(
        ["minimum_kw", "mean_kw", "critical_intervals"],
        ascending=[True, True, False],
    )

    slot = frame.groupby("hour_of_day")["residual_capacity_kw"].agg(
        minimum_kw="min", mean_kw="mean", maximum_kw="max"
    )
    slot["p10_kw"] = frame.groupby("hour_of_day")[
        "residual_capacity_kw"
    ].quantile(0.10)
    slot["median_kw"] = frame.groupby("hour_of_day")[
        "residual_capacity_kw"
    ].quantile(0.50)
    slot["p90_kw"] = frame.groupby("hour_of_day")[
        "residual_capacity_kw"
    ].quantile(0.90)
    slot["zero_intervals"] = frame.groupby("hour_of_day")["is_zero"].sum()
    slot["critical_intervals"] = frame.groupby("hour_of_day")[
        "is_critical"
    ].sum()

    hourly = frame.groupby("hour")["residual_capacity_kw"].agg(
        minimum_kw="min", mean_kw="mean", maximum_kw="max"
    )
    hourly["p10_kw"] = frame.groupby("hour")["residual_capacity_kw"].quantile(0.10)
    hourly["median_kw"] = frame.groupby("hour")["residual_capacity_kw"].quantile(0.50)
    hourly["zero_intervals"] = frame.groupby("hour")["is_zero"].sum()
    hourly["critical_intervals"] = frame.groupby("hour")["is_critical"].sum()
    preferred_hours = (
        hourly.sort_values(["p10_kw", "median_kw"], ascending=False)
        .head(preferred_hour_count)
        .index.astype(int).tolist()
    )
    constrained_hours = hourly.loc[
        hourly["p10_kw"] < threshold_kw
    ].index.astype(int).tolist()

    critical = frame.loc[frame["is_critical"]].copy()
    critical_by_month_hour = (
        critical.groupby(["month", "hour"]).size().rename("interval_count")
        .reset_index()
    )
    worst_date = daily.index[0]
    worst_day = frame.loc[frame["date"] == worst_date].copy()
    summary = {
        "status": "ok",
        "threshold_kw": threshold_kw,
        "zero_tolerance_kw": float(zero_tolerance_kw),
        "profile_interval_count": int(len(frame)),
        "zero_capacity_interval_count": int(frame["is_zero"].sum()),
        "critical_interval_count": int(frame["is_critical"].sum()),
        "profile_interval_hours": interval_hours,
        "residual_capacity_kw_min": float(residual.min()),
        "residual_capacity_kw_p01": float(residual.quantile(0.01)),
        "residual_capacity_kw_p05": float(residual.quantile(0.05)),
        "residual_capacity_kw_p10": float(residual.quantile(0.10)),
        "residual_capacity_kw_median": float(residual.quantile(0.50)),
        "residual_capacity_kw_mean": float(residual.mean()),
        "residual_capacity_kw_p90": float(residual.quantile(0.90)),
        "residual_capacity_kw_max": float(residual.max()),
        "robust_screening_reference_kw": float(residual.quantile(0.05)),
        "robust_screening_reference_percentile": 5,
        "longest_zero_capacity_run_hours": _longest_run_hours(
            ordered["is_zero"], interval_hours
        ),
        "longest_critical_run_hours": _longest_run_hours(
            ordered["is_critical"], interval_hours
        ),
        "worst_date": str(worst_date),
        "worst_day_minimum_kw": float(daily.iloc[0]["minimum_kw"]),
        "worst_day_mean_kw": float(daily.iloc[0]["mean_kw"]),
        "preferred_charging_hours": sorted(preferred_hours),
        "preferred_charging_hours_ranked": preferred_hours,
        "constrained_hours_p10_below_threshold": constrained_hours,
        "critical_occurrences_by_month_hour": [
            {
                "month": int(row["month"]),
                "hour": int(row["hour"]),
                "interval_count": int(row["interval_count"]),
            }
            for _, row in critical_by_month_hour.iterrows()
        ],
    }
    return frame, daily, slot, hourly, critical, worst_day, summary


def plot_capacity_24h(worst_day: pd.DataFrame,
                      slot_statistics: pd.DataFrame,
                      summary: dict, output_path: Path):
    """Gera grafico do pior dia e envelope anual por horario."""
    import matplotlib

    # A rotina e executada em lote pelo main.py e nao deve depender do backend
    # grafico do macOS nem de uma sessao com interface aberta.
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    threshold = float(summary["threshold_kw"])
    worst_x = worst_day["hour_of_day"].to_numpy(float)
    worst_y = worst_day["residual_capacity_kw"].to_numpy(float)
    slot_x = slot_statistics.index.to_numpy(float)
    p10 = slot_statistics["p10_kw"].to_numpy(float)
    median = slot_statistics["median_kw"].to_numpy(float)
    p90 = slot_statistics["p90_kw"].to_numpy(float)

    figure, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    figure.suptitle("Capacidade residual da rede em 24 horas")

    axes[0].plot(worst_x, worst_y, color="#2166ac", linewidth=2.2,
                 marker="o", markersize=3, label="Capacidade residual")
    axes[0].fill_between(
        worst_x, 0.0, worst_y, where=worst_y < threshold,
        color="#b2182b", alpha=0.25, label="Abaixo do limiar",
    )
    axes[0].axhline(threshold, color="#666666", linestyle="--",
                    linewidth=1.2, label=f"Limiar {threshold:g} kW")
    axes[0].set_title(f"Pior dia identificado: {summary['worst_date']}")
    axes[0].set_ylabel("Capacidade residual [kW]")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].fill_between(
        slot_x, p10, p90, color="#92c5de", alpha=0.45,
        label="Faixa P10-P90",
    )
    axes[1].plot(slot_x, median, color="#762a83", linewidth=2.2,
                 label="Mediana anual")
    axes[1].plot(slot_x, p10, color="#2166ac", linewidth=1.2,
                 linestyle="--", label="P10")
    axes[1].axhline(threshold, color="#666666", linestyle=":",
                    linewidth=1.2, label=f"Limiar {threshold:g} kW")
    axes[1].set_title("Distribuicao anual da capacidade por horario")
    axes[1].set_xlabel("Hora do dia")
    axes[1].set_ylabel("Capacidade residual [kW]")
    axes[1].set_xlim(0.0, 23.75)
    axes[1].set_xticks(np.arange(0, 24, 1))
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best", ncol=2)

    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def run_capacity_critical_analysis(audit: pd.DataFrame, output_dir: Path,
                                   network_config: dict) -> dict:
    """Executa analise, salva tabelas, JSON e grafico de 24 horas."""
    threshold = float(network_config.get(
        "critical_capacity_threshold_kw",
        network_config.get("connection_reference_power_kw", 250.0),
    ))
    outputs = analyze_capacity_profile(
        audit,
        threshold_kw=threshold,
        preferred_hour_count=int(
            network_config.get("preferred_charging_hour_count", 6)
        ),
        zero_tolerance_kw=float(
            network_config.get("zero_capacity_tolerance_kw", 1e-6)
        ),
    )
    frame, daily, slot, hourly, critical, worst_day, summary = outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "analysis_json": output_dir / "grid_capacity_critical_analysis.json",
        "critical_intervals_csv": output_dir / "grid_capacity_critical_intervals.csv",
        "daily_statistics_csv": output_dir / "grid_capacity_daily_statistics.csv",
        "time_of_day_statistics_csv": output_dir / "grid_capacity_time_of_day_statistics.csv",
        "hourly_statistics_csv": output_dir / "grid_capacity_hourly_statistics.csv",
        "plot_24h_png": output_dir / "grid_capacity_24h_analysis.png",
    }
    critical.drop(columns=["date"], errors="ignore").to_csv(
        paths["critical_intervals_csv"], index=False
    )
    daily.to_csv(paths["daily_statistics_csv"], index_label="date")
    slot.to_csv(paths["time_of_day_statistics_csv"], index_label="hour_of_day")
    hourly.to_csv(paths["hourly_statistics_csv"], index_label="hour")
    plot_capacity_24h(worst_day, slot, summary, paths["plot_24h_png"])
    summary["output_files"] = {key: str(path) for key, path in paths.items()}
    paths["analysis_json"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary
