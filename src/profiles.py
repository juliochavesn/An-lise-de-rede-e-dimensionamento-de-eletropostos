"""
Geração dos perfis sintéticos de entrada.

Este módulo preserva a lógica original:
- demanda de recarga EV com picos de manhã e fim da tarde;
- carga local com pico ao meio-dia e à noite;
- tarifa por período horário;
- fator de capacidade FV normalizado.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd


def gaussian(x, mu, sigma, amp):
    """
    Calcula uma curva gaussiana.

    Parâmetros:
    x     : vetor de tempo ou variável independente;
    mu    : centro do pico;
    sigma : largura do pico;
    amp   : amplitude do pico.
    """
    return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _resample_hourly_daily_profile(profile, dt_h):
    """Converte 24 potências horárias para a resolução do modelo.

    A interpolação é periódica entre 23h e 0h. Para passos que dividem
    exatamente o dia, conserva a energia diária representada pelo perfil
    original (soma das 24 potências horárias em kWh).
    """
    profile = np.asarray(profile, dtype=float)
    intervals_per_day = int(round(24.0 / dt_h))
    if not math.isclose(intervals_per_day * dt_h, 24.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("O passo temporal deve dividir exatamente um dia de 24 horas.")
    if intervals_per_day == 24:
        return profile.copy()
    source_hours = np.arange(25, dtype=float)
    periodic_profile = np.concatenate([profile, profile[:1]])
    target_hours = np.arange(intervals_per_day, dtype=float) * dt_h
    return np.interp(target_hours, source_hours, periodic_profile)


def generate_profiles(
    horizon_h=24.0,
    dt_h=0.25,
    seed=42,
    grid_limit_mode="grid_only",
    base_grid_limit_kw=120.0,
    export_limit_kw=0.0,
    local_base_kw=20.0,
    local_midday_peak_kw=60.0,
    local_evening_peak_kw=40.0,
    ev_base_kw=10.0,
    ev_morning_peak_kw=80.0,
    ev_evening_peak_kw=140.0,
    price_offpeak=0.45,
    price_peak=1.20,
    peak_start_hour=18.0,
    peak_end_hour=21.0,
    pv_cf_external=None,
    calendar_start=None,
    weekday_load_factor=1.0,
    saturday_load_factor=1.0,
    sunday_load_factor=1.0,
    monthly_load_factors=None,
    holiday_dates=None,
    grid_limit_external=None,
    ev_request_external=None,
):
     # Gerador aleatório para reprodutibilidade.
    rng = np.random.default_rng(seed)
    """
    Gera todos os perfis necessários para o modelo de otimização.

    Retorna um dicionário com séries temporais indexadas por t.
    """

    # Inicializa gerador aleatório com semente fixa para reprodutibilidade.

    # Número de intervalos de tempo do horizonte.
    n = int(horizon_h / dt_h)

    # Índices inteiros dos intervalos.
    t = np.arange(n)

    # Vetor de horas correspondente a cada intervalo. hour_of_day é
    # usado nas curvas recorrentes e evita que os picos desapareçam
    # depois do primeiro dia em horizontes maiores que 24 h.
    hours = t * dt_h
    hour_of_day = np.mod(hours, 24.0)

    calendar_index = None
    if calendar_start is not None:
        calendar_index = pd.date_range(
            start=pd.Timestamp(calendar_start),
            periods=n,
            freq=pd.to_timedelta(dt_h, unit="h"),
        )

    # Demanda nova de recarga EV [kW].
    ev_request = (
        ev_base_kw
        + gaussian(hour_of_day, 8.0, 1.4, ev_morning_peak_kw)
        + gaussian(hour_of_day, 18.5, 2.0, ev_evening_peak_kw)
    )

    # Adiciona ruído para representar variabilidade operacional.
    ev_request += rng.normal(0.0, 3.0, size=n)

    # Evita valores negativos de demanda.
    ev_request = np.clip(ev_request, 0.0, None)

    # Um perfil logístico externo pode substituir a curva sintética. Aceita
    # uma série para todo o horizonte, um dia na resolução do modelo ou as
    # 24 potências horárias produzidas pela conversão PNL. Neste último caso,
    # reamostra automaticamente e depois repete o dia pelo horizonte.
    if ev_request_external is not None:
        external = np.asarray(ev_request_external, dtype=float)
        intervals_per_day = int(round(24.0 / dt_h))
        if len(external) == 24:
            external = _resample_hourly_daily_profile(external, dt_h)
        if len(external) == intervals_per_day:
            external = np.tile(external, int(np.ceil(n / len(external))))[:n]
        if len(external) != n:
            raise ValueError(
                "O perfil externo de recarga deve conter 24 potências horárias, "
                "um dia completo na resolução do modelo ou exatamente todos "
                "os intervalos da simulação."
            )
        if not np.isfinite(external).all() or (external < 0).any():
            raise ValueError("O perfil externo de recarga deve ser finito e não negativo.")
        ev_request = external.copy()

    # Carga local do estabelecimento [kW].
    
    if (
        abs(local_base_kw) < 1e-9
        and abs(local_midday_peak_kw) < 1e-9
        and abs(local_evening_peak_kw) < 1e-9
    ):
        local_load = np.zeros(n)

    else:
        local_load = (
            local_base_kw
            + gaussian(hour_of_day, 12.5, 2.8, local_midday_peak_kw)
            + gaussian(hour_of_day, 19.0, 2.2, local_evening_peak_kw)
        )

        local_load += rng.normal(0.0, 1.5, size=n)
        local_load = np.clip(local_load, 0.0, None)

    # Calendário opcional do modo anual. Os fatores ficam explícitos
    # na configuração e são aplicados igualmente às cargas local e EV.
    if calendar_index is not None:
        monthly_load_factors = (
            [1.0] * 12
            if monthly_load_factors is None
            else list(monthly_load_factors)
        )
        if len(monthly_load_factors) != 12:
            raise ValueError("monthly_load_factors deve ter 12 valores.")
        if any(float(value) < 0.0 for value in monthly_load_factors):
            raise ValueError("Multiplicadores mensais não podem ser negativos.")

        weekday = calendar_index.dayofweek.to_numpy()
        day_factor = np.where(
            weekday == 5,
            float(saturday_load_factor),
            np.where(
                weekday == 6,
                float(sunday_load_factor),
                float(weekday_load_factor),
            ),
        )
        month_factor = np.array([
            float(monthly_load_factors[month - 1])
            for month in calendar_index.month
        ])
        load_factor = day_factor * month_factor
        ev_request *= load_factor
        local_load *= load_factor

    # Limite efetivo de importacao [kW]. Sem perfil externo, preserva
    # exatamente o comportamento anterior com limite constante.
    if grid_limit_external is None:
        grid_limit = np.full(n, base_grid_limit_kw, dtype=float)
    elif isinstance(grid_limit_external, dict):
        grid_limit = np.array(
            [grid_limit_external[index] for index in range(n)], dtype=float
        )
    else:
        grid_limit = np.asarray(grid_limit_external, dtype=float)

    if grid_limit.shape != (n,):
        raise ValueError(
            f"grid_limit_external deve possuir {n} intervalos; "
            f"recebidos {grid_limit.size}"
        )
    if not np.all(np.isfinite(grid_limit)) or np.any(grid_limit < 0.0):
        raise ValueError(
            "grid_limit_external deve conter valores finitos e nao negativos"
        )

    # Grupo A4 Verde: apenas ponta e fora de ponta.
    price = np.full(n, price_offpeak)
    peak_mask = (
        (hour_of_day >= peak_start_hour)
        & (hour_of_day < peak_end_hour)
    )
    if calendar_index is not None:
        holiday_dates = set(holiday_dates or [])
        date_strings = calendar_index.strftime("%Y-%m-%d")
        business_day = (
            (calendar_index.dayofweek < 5)
            & ~date_strings.isin(holiday_dates)
        )
        peak_mask &= np.asarray(business_day)
    price[peak_mask] = price_peak

  # ========================================================
    # FATOR DE CAPACIDADE FV
    # ========================================================

    if pv_cf_external is None:
        # Caso não exista perfil FV externo, usa curva sintética simplificada.
        pv_cf = np.zeros(n)

        sunrise = 6.0
        sunset = 18.0

        for i, h in enumerate(hour_of_day):
            if sunrise <= h <= sunset:
                x = (h - sunrise) / (sunset - sunrise)
                pv_cf[i] = math.sin(math.pi * x) ** 1.6

        pv_cf = np.clip(pv_cf, 0.0, 1.0)

    else:
        # Caso exista perfil externo, usa pvlib/PVGIS.
        # O dicionário deve estar no formato {0: valor, 1: valor, ...}.
        pv_cf = np.array([
            pv_cf_external.get(i, 0.0)
            for i in range(n)
        ])

        pv_cf = np.clip(pv_cf, 0.0, 1.0)

    # Garante que o fator FV fique entre 0 e 1.
    pv_cf = np.clip(pv_cf, 0.0, 1.0)

    if calendar_index is None:
        month_of_t = np.ones(n, dtype=int)
        billing_periods = [1]
        demand_month_weights = {
            1: float(horizon_h) / (24.0 * (365.25 / 12.0))
        }
        timestamps = [None] * n
    else:
        month_of_t = calendar_index.month.to_numpy(dtype=int)
        billing_periods = sorted(set(month_of_t.tolist()))
        demand_month_weights = {}
        for month in billing_periods:
            represented_hours = float(np.sum(month_of_t == month)) * dt_h
            days_in_month = int(
                calendar_index[month_of_t == month][0].days_in_month
            )
            demand_month_weights[month] = (
                represented_hours / (24.0 * days_in_month)
            )
        timestamps = [value.isoformat() for value in calendar_index]

    # Retorna dados no formato usado pelo escritor .dat.
    return {
        "dt_h": float(dt_h),
        "horizon_h": float(horizon_h),
        "time_index": list(range(n)),
        "request_kw": {i: float(ev_request[i]) for i in range(n)},
        "local_load_kw": {i: float(local_load[i]) for i in range(n)},
        "grid_limit_kw": {i: float(grid_limit[i]) for i in range(n)},
        "price_grid": {i: float(price[i]) for i in range(n)},
        "pv_cf": {i: float(pv_cf[i]) for i in range(n)},
        "month_of_t": {i: int(month_of_t[i]) for i in range(n)},
        "billing_periods": billing_periods,
        "demand_month_weights": demand_month_weights,
        "timestamps": timestamps,
        "is_peak": {i: int(bool(peak_mask[i])) for i in range(n)},
        "grid_limit_mode": grid_limit_mode,
        "export_limit_kw": float(export_limit_kw),
    }


def save_homer_load_profiles(data, output_dir):
    """Exporta para o HOMER as cargas exatas usadas na simulação.

    Os arquivos ``*_kw.csv`` possuem uma única coluna, sem cabeçalho e
    sem índice, no formato de importação direta do HOMER Pro. Cada linha
    contém a potência média [kW] do respectivo passo temporal. Um arquivo
    adicional com timestamp e as três séries facilita a auditoria.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    time_index = list(data["time_index"])
    local_load = [float(data["local_load_kw"][t]) for t in time_index]
    ev_request = [float(data["request_kw"][t]) for t in time_index]
    total_load = [
        local_kw + ev_kw
        for local_kw, ev_kw in zip(local_load, ev_request)
    ]

    series = {
        "homer_local_load_kw.csv": local_load,
        "homer_ev_request_kw.csv": ev_request,
        "homer_total_load_kw.csv": total_load,
    }
    for filename, values in series.items():
        pd.Series(values).to_csv(
            output_dir / filename,
            index=False,
            header=False,
            float_format="%.10f",
        )

    timestamps = data.get("timestamps") or [None] * len(time_index)
    audit = pd.DataFrame({
        "timestamp": timestamps,
        "local_load_kw": local_load,
        "ev_request_kw": ev_request,
        "total_load_kw": total_load,
    })
    audit.to_csv(
        output_dir / "homer_load_profiles_audit.csv",
        index=False,
        float_format="%.10f",
    )

    return {
        name: output_dir / name
        for name in (*series, "homer_load_profiles_audit.csv")
    }


def save_homer_served_profile(results_df, output_dir, config):
    """Exporta a potência EV atendida pelo AMPL para o HOMER Pro.

    A série é escrita com uma coluna sem cabeçalho ou índice, de modo
    que cada linha seja a potência média [kW] do passo temporal. Diferente
    de ``homer_ev_request_kw.csv``, este arquivo contém o despacho EV
    otimizado, incluindo os deslocamentos permitidos pela janela de espera.
    """
    if "served_kw" not in results_df.columns:
        raise ValueError("A coluna served_kw não existe nos resultados.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"homer_ev_served_{config}_kw.csv"
    results_df["served_kw"].astype(float).to_csv(
        output_path,
        index=False,
        header=False,
        float_format="%.10f",
    )
    return output_path
