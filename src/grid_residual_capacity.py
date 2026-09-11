"""Estimativa conservadora da capacidade residual de um alimentador BDGD.

A BDGD nao contem medicoes SCADA horarias. Este modulo combina energia mensal,
curvas tipicas de carga e limites nominais para produzir um perfil horario de
triagem. O resultado e mais informativo que a ampacidade isolada, mas ainda nao
substitui fluxo de potencia nem parecer de acesso da distribuidora.
"""

from __future__ import annotations

import calendar
import math
from pathlib import Path

import numpy as np
import pandas as pd
from src.grid_data_quality import operational_rows


ENERGY_COLUMNS = [f"ENE_{month:02d}" for month in range(1, 13)]
CURVE_COLUMNS = [f"POT_{index:02d}" for index in range(1, 97)]


def scale_profile_to_energy(raw_profile, target_energy_kwh: float,
                            dt_h: float) -> np.ndarray:
    """Escala uma forma nao negativa para reproduzir energia conhecida."""
    raw = np.asarray(raw_profile, dtype=float)
    target = float(target_energy_kwh)
    dt_h = float(dt_h)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError("raw_profile deve ser um vetor nao vazio.")
    if not np.all(np.isfinite(raw)) or np.any(raw < 0.0):
        raise ValueError("raw_profile deve conter valores finitos e nao negativos.")
    if not math.isfinite(target) or target < 0.0 or not math.isfinite(dt_h) or dt_h <= 0.0:
        raise ValueError("Energia-alvo e passo temporal devem ser validos.")
    if target == 0.0:
        return np.zeros_like(raw)
    raw_energy = float(raw.sum()) * dt_h
    if raw_energy <= 0.0:
        return np.full(raw.size, target / (raw.size * dt_h))
    return raw * (target / raw_energy)


def calculate_residual_capacity(capacity_ceiling_kw, feeder_load_kw,
                                generation_kw, load_safety_factor: float,
                                generation_credit_fraction: float) -> np.ndarray:
    """Calcula capacidade firme restante, truncada em zero."""
    capacity = np.asarray(capacity_ceiling_kw, dtype=float)
    load = np.asarray(feeder_load_kw, dtype=float)
    generation = np.asarray(generation_kw, dtype=float)
    if capacity.ndim == 0:
        capacity = np.full(load.size, float(capacity))
    if capacity.shape != load.shape or generation.shape != load.shape:
        raise ValueError("Capacidade, carga e geracao devem ter a mesma dimensao.")
    if any(not np.all(np.isfinite(values)) for values in (capacity, load, generation)):
        raise ValueError("As series de capacidade residual devem ser finitas.")
    if np.any(capacity < 0.0) or np.any(load < 0.0) or np.any(generation < 0.0):
        raise ValueError("Capacidade, carga e geracao nao podem ser negativas.")
    safety = float(load_safety_factor)
    credit = float(generation_credit_fraction)
    if not math.isfinite(safety) or safety < 1.0 or not 0.0 <= credit <= 1.0:
        raise ValueError("Fator de seguranca >= 1 e credito de geracao em [0, 1].")
    return np.maximum(capacity - safety * load + credit * generation, 0.0)


def _active_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return operational_rows(frame, "SIT_ATIV")


def _monthly_sums(frame: pd.DataFrame) -> np.ndarray:
    return np.array([
        pd.to_numeric(frame.get(column), errors="coerce").fillna(0.0).clip(lower=0.0).sum()
        if column in frame else 0.0
        for column in ENERGY_COLUMNS
    ], dtype=float)


def _calendar_index(scenario: dict) -> pd.DatetimeIndex:
    interval_count = int(float(scenario["horizon_h"]) / float(scenario["dt_h"]))
    start = scenario.get("calendar_start") or "2021-01-04 00:00:00"
    return pd.date_range(
        start=pd.Timestamp(start),
        periods=interval_count,
        freq=pd.to_timedelta(float(scenario["dt_h"]), unit="h"),
    )


def _day_type(timestamp: pd.Timestamp) -> str:
    if timestamp.dayofweek == 5:
        return "SA"
    if timestamp.dayofweek == 6:
        return "DO"
    return "DU"


def _curve_library(curves: pd.DataFrame) -> dict[tuple[str, str], np.ndarray]:
    library = {}
    for _, row in curves.iterrows():
        values = pd.to_numeric(row[CURVE_COLUMNS], errors="coerce").to_numpy(float)
        if np.all(np.isfinite(values)) and np.any(values > 0.0):
            library[(str(row["COD_ID"]), str(row["TIP_DIA"]))] = np.clip(
                values, 0.0, None
            )
    return library


def _curve_value(curve: np.ndarray, timestamp: pd.Timestamp,
                 dt_h: float) -> float:
    steps = max(1, int(round(dt_h / 0.25)))
    if not math.isclose(steps * 0.25, dt_h, abs_tol=1e-9):
        raise ValueError("O perfil BDGD requer dt_h multiplo de 0,25 h.")
    start = timestamp.hour * 4 + timestamp.minute // 15
    indices = [(start + offset) % 96 for offset in range(steps)]
    return float(np.mean(curve[indices]))


def _customer_curve_shape(customers: pd.DataFrame, curves: pd.DataFrame,
                          timestamps: pd.DatetimeIndex, dt_h: float,
                          month: int) -> tuple[np.ndarray, int]:
    library = _curve_library(curves)
    energy_column = f"ENE_{month:02d}"
    energies = pd.to_numeric(customers[energy_column], errors="coerce").fillna(0.0)
    grouped = (
        customers.assign(_energy=energies.clip(lower=0.0))
        .groupby(customers["TIP_CC"].astype(str))["_energy"]
        .sum()
    )
    shape = np.zeros(len(timestamps), dtype=float)
    missing = 0
    for code, energy in grouped.items():
        if energy <= 0.0:
            continue
        class_shape = np.zeros(len(timestamps), dtype=float)
        incomplete = False
        for index, timestamp in enumerate(timestamps):
            curve = library.get((code, _day_type(timestamp)))
            if curve is None:
                incomplete = True
                class_shape[index] = 1.0
            else:
                class_shape[index] = _curve_value(curve, timestamp, dt_h)
        # Cada classe deve reproduzir SUA energia, independentemente da escala
        # arbitrária da curva típica, antes de compor o alimentador.
        shape += scale_profile_to_energy(class_shape, float(energy), dt_h)
        if incomplete:
            missing += 1
    return shape, missing


def _build_existing_load_profile(feeder_energy: np.ndarray,
                                 customers: pd.DataFrame,
                                 curves: pd.DataFrame,
                                 timestamps: pd.DatetimeIndex,
                                 dt_h: float) -> tuple[np.ndarray, int]:
    profile = np.zeros(len(timestamps), dtype=float)
    missing_curve_classes = 0
    for year, month in sorted(set(zip(timestamps.year, timestamps.month))):
        mask = (timestamps.month == month) & (timestamps.year == year)
        month_timestamps = timestamps[mask]
        full_month = pd.date_range(
            pd.Timestamp(year=year, month=month, day=1),
            periods=int(calendar.monthrange(year, month)[1] * 24 / dt_h),
            freq=pd.to_timedelta(dt_h, unit="h"),
        )
        shape, missing = _customer_curve_shape(
            customers, curves, full_month, dt_h, month
        )
        full_profile = scale_profile_to_energy(shape, feeder_energy[month - 1], dt_h)
        positions = full_month.get_indexer(month_timestamps)
        if np.any(positions < 0):
            raise ValueError("Calendário BDGD deve estar alinhado ao passo temporal desde meia-noite.")
        profile[mask] = full_profile[positions]
        missing_curve_classes += missing
    return profile, missing_curve_classes


def _build_generation_profile(monthly_energy: np.ndarray,
                              timestamps: pd.DatetimeIndex,
                              dt_h: float) -> np.ndarray:
    profile = np.zeros(len(timestamps), dtype=float)
    hour = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
    solar_base = np.clip(np.sin(np.pi * (hour - 6.0) / 12.0), 0.0, None)
    solar_shape = np.where(
        (hour >= 6.0) & (hour <= 18.0),
        solar_base ** 1.5,
        0.0,
    )
    solar_shape = np.nan_to_num(solar_shape, nan=0.0)
    for month in sorted(set(timestamps.month)):
        mask = timestamps.month == month
        represented_hours = float(mask.sum()) * dt_h
        hours_in_month = 24.0 * calendar.monthrange(
            int(timestamps[mask][0].year), month
        )[1]
        target_energy = monthly_energy[month - 1] * represented_hours / hours_in_month
        profile[mask] = scale_profile_to_energy(solar_shape[mask], target_energy, dt_h)
    return profile


def _transformer_capacity_kw(transformer: pd.DataFrame, power_factor: float,
                             utilization: float) -> tuple[float | None, str | None]:
    if transformer.empty:
        return None, None
    rating = float(transformer.iloc[0]["POT_NOM"])
    if not math.isfinite(rating) or rating <= 0.0:
        return None, str(transformer.iloc[0]["COD_ID"])
    # Na UNTRAT da BDGD da CPFL, POT_NOM e informado em MVA.
    return rating * 1000.0 * power_factor * utilization, str(
        transformer.iloc[0]["COD_ID"]
    )


def estimate_residual_capacity_profile(gdb_path: Path, feeder_id: str,
                                       scenario: dict,
                                       conductor_capacity_kw: float,
                                       network_config: dict):
    """Le a BDGD e retorna perfil, tabela de auditoria e metadados."""
    import pyogrio

    escaped = str(feeder_id).replace("'", "''")
    feeder = pyogrio.read_dataframe(
        gdb_path, layer="CTMT", where=f"COD_ID='{escaped}'", read_geometry=False
    )
    if feeder.empty:
        raise LookupError(f"Alimentador {feeder_id} nao encontrado na CTMT.")

    feeder_row = feeder.iloc[0]
    # O driver OpenFileGDB precisa manter a coluna usada no filtro entre as
    # colunas solicitadas; caso contrario pode retornar um conjunto vazio.
    consumer_columns = ["CTMT", "TIP_CC", "SIT_ATIV", *ENERGY_COLUMNS]
    consumer_frames = []
    consumer_counts = {}
    for layer in ("UCBT_tab", "UCMT_tab"):
        frame = pyogrio.read_dataframe(
            gdb_path,
            layer=layer,
            where=f"CTMT='{escaped}'",
            columns=consumer_columns,
            read_geometry=False,
        )
        frame = _active_rows(frame)
        consumer_counts[layer] = int(len(frame))
        consumer_frames.append(frame)
    customers = pd.concat(consumer_frames, ignore_index=True)

    curves = pyogrio.read_dataframe(
        gdb_path,
        layer="CRVCRG",
        columns=["COD_ID", "TIP_DIA", *CURVE_COLUMNS],
        read_geometry=False,
    )

    generation_frames = []
    generation_counts = {}
    for layer in ("UGBT_tab", "UGMT_tab"):
        frame = pyogrio.read_dataframe(
            gdb_path,
            layer=layer,
            where=f"CTMT='{escaped}'",
            columns=["CTMT", "SIT_ATIV", *ENERGY_COLUMNS],
            read_geometry=False,
        )
        frame = _active_rows(frame)
        generation_counts[layer] = int(len(frame))
        generation_frames.append(frame)
    generators = pd.concat(generation_frames, ignore_index=True)

    transformer_id = str(feeder_row.get("UNI_TR_AT", ""))
    transformer = pyogrio.read_dataframe(
        gdb_path,
        layer="UNTRAT",
        where=f"COD_ID='{transformer_id.replace(chr(39), chr(39) * 2)}'",
        columns=["COD_ID", "POT_NOM", "SIT_ATIV"],
        read_geometry=False,
    )
    transformer = _active_rows(transformer)

    feeder_energy = np.array([
        max(float(feeder_row[column]), 0.0) for column in ENERGY_COLUMNS
    ])
    customer_energy = _monthly_sums(customers)
    generation_energy = _monthly_sums(generators)
    dt_h = float(scenario["dt_h"])
    timestamps = _calendar_index(scenario)
    if any(not np.isfinite(feeder_energy[m - 1]) or feeder_energy[m - 1] <= 0
           for m in set(timestamps.month)):
        raise ValueError("Energia mensal CTMT ausente, inválida ou zero: carga existente não validada.")
    load_profile, missing_curves = _build_existing_load_profile(
        feeder_energy, customers, curves, timestamps, dt_h
    )
    generation_profile = _build_generation_profile(
        generation_energy, timestamps, dt_h
    )

    power_factor = float(network_config.get("power_factor", 0.95))
    transformer_capacity, transformer_id = _transformer_capacity_kw(
        transformer,
        power_factor,
        float(network_config.get("transformer_utilization_factor", 0.80)),
    )
    candidates = {"path_conductor": float(conductor_capacity_kw)}
    if transformer_capacity is not None:
        candidates["substation_transformer"] = transformer_capacity
    limiting_element = min(candidates, key=candidates.get)
    capacity_ceiling = float(candidates[limiting_element])

    safety = float(network_config.get("existing_load_safety_factor", 1.10))
    generation_credit = float(
        network_config.get("distributed_generation_credit_fraction", 0.0)
    )
    residual = calculate_residual_capacity(
        float(conductor_capacity_kw),
        load_profile,
        generation_profile,
        safety,
        generation_credit,
    )
    # Um transformador AT/MT pode alimentar vários CTMT. A carga de apenas
    # um deles não representa sua disponibilidade. Mesma forma horária é uma
    # aproximação explicitada, não uma medição de simultaneidade.
    shared_feeders = pyogrio.read_dataframe(
        gdb_path, layer="CTMT", read_geometry=False,
        where=f"UNI_TR_AT='{str(feeder_row.get('UNI_TR_AT', '')).replace(chr(39), chr(39)*2)}'",
        columns=["COD_ID", "UNI_TR_AT", *ENERGY_COLUMNS],
    )
    shared_energy = _monthly_sums(shared_feeders)
    shared_load = np.array([
        load * shared_energy[t.month - 1] / feeder_energy[t.month - 1]
        for load, t in zip(load_profile, timestamps)
    ])
    if transformer_capacity is not None:
        residual = np.minimum(residual, calculate_residual_capacity(
            transformer_capacity, shared_load, np.zeros_like(shared_load), safety, 0.0
        ))
    audit = pd.DataFrame({
        "timestamp": timestamps,
        "feeder_existing_load_estimated_kw": load_profile,
        "load_with_safety_factor_kw": load_profile * safety,
        "distributed_generation_estimated_kw": generation_profile,
        "credited_generation_kw": generation_profile * generation_credit,
        "network_capacity_ceiling_kw": capacity_ceiling,
        "shared_transformer_load_estimated_kw": shared_load,
        "residual_capacity_kw": residual,
    })
    monthly = audit.assign(month=audit["timestamp"].dt.month).groupby("month")[
        "residual_capacity_kw"
    ].agg(["min", "mean", "max"])

    metadata = {
        "method": "feeder_aggregate_residual_screening",
        "bdgd_reference_date": network_config.get("bdgd_reference_date"),
        "profile_calendar_start": timestamps[0].isoformat(),
        "profile_calendar_end": timestamps[-1].isoformat(),
        "warning": (
            "Estimativa por energia mensal e curvas tipicas; nao usa SCADA, "
            "fluxo de potencia ou reservas de acesso. Desconta toda a carga do "
            "alimentador no gargalo do caminho: conservadora em ramais; zero "
            "não prova falta de capacidade real. Transformador compartilhado "
            "usa energia de todos os CTMT associados e forma horária do CTMT local."
        ),
        "shared_transformer_feeder_ids": shared_feeders["COD_ID"].astype(str).tolist(),
        "shared_transformer_load_method": "aggregate_monthly_energy_local_feeder_shape_proxy",
        "downstream_load_allocation": "not_implemented_full_feeder_conservative_bound",
        "feeder_id": str(feeder_id),
        "consumer_counts": consumer_counts,
        "generation_counts": generation_counts,
        "feeder_monthly_energy_kwh": feeder_energy.tolist(),
        "customer_monthly_energy_kwh": customer_energy.tolist(),
        "distributed_generation_monthly_energy_kwh": generation_energy.tolist(),
        "missing_curve_classes": int(missing_curves),
        "conductor_capacity_kw": float(conductor_capacity_kw),
        "substation_transformer_id": transformer_id,
        "substation_transformer_capacity_kw": transformer_capacity,
        "limiting_element": limiting_element,
        "network_capacity_ceiling_kw": capacity_ceiling,
        "existing_load_safety_factor": safety,
        "distributed_generation_credit_fraction": generation_credit,
        "residual_capacity_kw_min": float(residual.min()),
        "residual_capacity_kw_mean": float(residual.mean()),
        "residual_capacity_kw_max": float(residual.max()),
        "zero_capacity_intervals": int(np.count_nonzero(residual <= 1e-9)),
        "monthly_residual_capacity_kw": {
            str(int(month)): {
                "min": float(row["min"]),
                "mean": float(row["mean"]),
                "max": float(row["max"]),
            }
            for month, row in monthly.iterrows()
        },
    }
    return residual, audit, metadata
