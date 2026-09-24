"""Conversão auditável de fluxos logísticos PNL em cenários de recarga.

Somente o carregamento anualizado e a geometria provêm do PNL. As hipóteses de
frota, eletrificação, captura e recarga são entradas explícitas do usuário; os
resultados não devem ser confundidos com previsões oficiais do PNL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import exp


@dataclass(frozen=True)
class FreightAssumptions:
    """Hipóteses centrais usadas para converter toneladas em energia."""

    payload_t: float = 30.0
    empty_returns_per_loaded_trip: float = 0.35
    electric_share: float = 0.15
    station_capture_share: float = 0.20
    energy_per_stop_kwh: float = 250.0
    operating_days_per_year: int = 365

    def validate(self) -> None:
        if self.payload_t <= 0 or self.energy_per_stop_kwh <= 0:
            raise ValueError("Carga útil e energia por parada devem ser positivas.")
        if self.operating_days_per_year <= 0:
            raise ValueError("Dias operacionais devem ser positivos.")
        if self.empty_returns_per_loaded_trip < 0:
            raise ValueError("A razão de retornos vazios não pode ser negativa.")
        for name in ("electric_share", "station_capture_share"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} deve estar entre zero e um.")


SCENARIO_FACTORS = {
    "P10": {
        "payload_t": 1.15,
        "empty_returns_per_loaded_trip": 0.70,
        "electric_share": 0.60,
        "station_capture_share": 0.70,
        "energy_per_stop_kwh": 0.85,
    },
    "P50": {},
    "P90": {
        "payload_t": 0.85,
        "empty_returns_per_loaded_trip": 1.30,
        "electric_share": 1.40,
        "station_capture_share": 1.30,
        "energy_per_stop_kwh": 1.15,
    },
}


def _scenario_assumptions(base: FreightAssumptions, label: str) -> FreightAssumptions:
    factors = SCENARIO_FACTORS[label]
    values = asdict(base)
    for field, factor in factors.items():
        values[field] *= factor
    values["electric_share"] = min(1.0, values["electric_share"])
    values["station_capture_share"] = min(1.0, values["station_capture_share"])
    return replace(base, **values)


def normalized_freight_profile() -> list[float]:
    """Perfil horário representativo, normalizado para uma unidade de energia.

    Os três pulsos apenas distribuem a energia diária; não constituem medição
    de tráfego. O usuário pode substituir o perfil em evoluções posteriores.
    """
    weights = []
    for hour in range(24):
        value = (
            0.25
            + 0.85 * exp(-0.5 * ((hour - 7.0) / 2.2) ** 2)
            + 1.00 * exp(-0.5 * ((hour - 13.0) / 2.8) ** 2)
            + 0.75 * exp(-0.5 * ((hour - 20.0) / 2.5) ** 2)
        )
        weights.append(value)
    total = sum(weights)
    return [value / total for value in weights]


def estimate_freight_charging(
    annual_tonnes: float,
    assumptions: FreightAssumptions | None = None,
) -> dict:
    """Calcula cenários P10/P50/P90 e perfis médios de 24 horas."""
    annual_tonnes = float(annual_tonnes)
    if annual_tonnes < 0:
        raise ValueError("O carregamento anual não pode ser negativo.")
    assumptions = assumptions or FreightAssumptions()
    assumptions.validate()
    shares = normalized_freight_profile()
    scenarios = {}
    for label in ("P10", "P50", "P90"):
        values = _scenario_assumptions(assumptions, label)
        values.validate()
        loaded_trips_year = annual_tonnes / values.payload_t
        physical_trips_year = loaded_trips_year * (
            1.0 + values.empty_returns_per_loaded_trip
        )
        trucks_day = physical_trips_year / values.operating_days_per_year
        electric_trucks_day = trucks_day * values.electric_share
        charging_events_day = electric_trucks_day * values.station_capture_share
        daily_energy_kwh = charging_events_day * values.energy_per_stop_kwh
        hourly_profile = [daily_energy_kwh * share for share in shares]
        scenarios[label] = {
            "annual_tonnes": annual_tonnes,
            "loaded_trips_per_year": loaded_trips_year,
            "physical_trips_per_day": trucks_day,
            "electric_trucks_per_day": electric_trucks_day,
            "charging_events_per_day": charging_events_day,
            "daily_energy_kwh": daily_energy_kwh,
            "annual_energy_mwh": daily_energy_kwh * values.operating_days_per_year / 1000.0,
            "mean_power_kw": daily_energy_kwh / 24.0,
            "profile_peak_kw": max(hourly_profile),
            "hourly_profile_kw": hourly_profile,
            "assumptions": asdict(values),
        }
    return {
        "scenarios": scenarios,
        "central_assumptions": asdict(assumptions),
        "method": "TU anualizado → viagens físicas → frota elétrica → capturas → energia",
        "scope_warning": (
            "Estimativa por cenários, não previsão oficial. O fator de veículo "
            "equivalente da engenharia de tráfego não entra no cálculo elétrico."
        ),
    }


def scenario_table(result: dict):
    """Retorna linhas simples para apresentação ou exportação."""
    return [
        {
            "Cenário": label,
            "Caminhões físicos/dia": values["physical_trips_per_day"],
            "Caminhões elétricos/dia": values["electric_trucks_per_day"],
            "Recargas/dia": values["charging_events_per_day"],
            "Energia/dia (kWh)": values["daily_energy_kwh"],
            "Potência média (kW)": values["mean_power_kw"],
            "Pico do perfil (kW)": values["profile_peak_kw"],
        }
        for label, values in result["scenarios"].items()
    ]
