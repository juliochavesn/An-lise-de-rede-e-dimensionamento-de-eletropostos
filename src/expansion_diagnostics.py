"""Triagem quantitativa de reforços quando a rede residual é insuficiente."""

from __future__ import annotations

import numpy as np


def _series(data: dict, key: str) -> np.ndarray:
    return np.asarray([float(data[key][t]) for t in data["time_index"]], dtype=float)


def _deficit_metrics(required: np.ndarray, available: np.ndarray, dt: float) -> dict:
    deficit = np.maximum(required - available, 0.0)
    positive = deficit[deficit > 1e-9]
    return {
        "reinforcement_to_eliminate_deficit_kw": float(deficit.max(initial=0.0)),
        "deficit_energy_kwh": float(deficit.sum() * dt),
        "deficit_intervals": int(positive.size),
        "deficit_p90_kw": float(np.quantile(positive, 0.90)) if positive.size else 0.0,
        "deficit_p95_kw": float(np.quantile(positive, 0.95)) if positive.size else 0.0,
        "deficit_p99_kw": float(np.quantile(positive, 0.99)) if positive.size else 0.0,
    }


def _longest_zero_window(grid: np.ndarray, local: np.ndarray, dt: float) -> dict:
    best_start = best_end = None
    best_length = run_length = 0
    run_start = 0
    for index, value in enumerate(grid):
        if value <= 1e-9:
            if run_length == 0:
                run_start = index
            run_length += 1
            if run_length > best_length:
                best_length = run_length
                best_start, best_end = run_start, index
        else:
            run_length = 0
    energy = 0.0 if best_start is None else float(local[best_start:best_end + 1].sum() * dt)
    return {
        "longest_zero_residual_hours": float(best_length * dt),
        "longest_zero_start_index": best_start,
        "longest_zero_end_index": best_end,
        "local_energy_during_longest_zero_kwh": energy,
    }


def analyze_expansion_need(data: dict, limits: dict) -> dict:
    """Calcula reforços indicativos; não substitui estudo de acesso."""
    dt = float(data["dt_h"])
    grid = _series(data, "grid_limit_kw")
    local = _series(data, "local_load_kw")
    ev = _series(data, "request_kw")
    local_case = _deficit_metrics(local, grid, dt)
    full_case = _deficit_metrics(local + ev, grid, dt)
    zero = _longest_zero_window(grid, local, dt)
    eta_dis = float(limits.get("bess_eta_dis", 1.0))
    soc_window = max(float(limits.get("bess_soc_max_frac", 1.0)) - float(limits.get("bess_soc_min_frac", 0.0)), 1e-9)
    stored_required = zero["local_energy_during_longest_zero_kwh"] / eta_dis
    nominal_required = stored_required / soc_window
    bess_max = float(limits.get("bess_e_max_kwh", 0.0))
    local_reinforcement = local_case["reinforcement_to_eliminate_deficit_kw"]
    improved_grid = grid + local_reinforcement
    ev_headroom = np.maximum(improved_grid - local, 0.0)
    return {
        "status": "reinforcement_required" if local_reinforcement > 1e-9 else "local_load_supported",
        "method": "constant_firm_increment_to_bdgd_residual_profile",
        "local_load_case": local_case,
        "full_instantaneous_demand_case": full_case,
        "storage_screening": {
            **zero,
            "stored_energy_required_kwh": float(stored_required),
            "indicative_nominal_bess_required_kwh": float(nominal_required),
            "configured_bess_max_kwh": bess_max,
            "configured_usable_bess_energy_kwh": float(bess_max * soc_window),
            "storage_limit_shortfall_kwh": float(max(nominal_required - bess_max, 0.0)),
            "note": "Estimativa necessária, mas não suficiente: recarga, potência, recarregamento e perdas também devem ser otimizados.",
        },
        "improved_local_support_case": {
            "firm_reinforcement_kw": float(local_reinforcement),
            "remaining_local_deficit_intervals": int(np.sum(improved_grid + 1e-9 < local)),
            "ev_headroom_energy_kwh": float(ev_headroom.sum() * dt),
            "ev_headroom_peak_kw": float(ev_headroom.max(initial=0.0)),
        },
        "interpretation": "Triagem de planejamento baseada no perfil residual BDGD. Os reforços são hipóteses escalares e não definem obra, custo ou parecer de acesso.",
    }
