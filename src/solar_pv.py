"""
Módulo de simulação solar fotovoltaica para integração
com o sistema de otimização AMPL.

Objetivo:
---------
Gerar um perfil solarimétrico realista do local utilizando:
- coordenadas geográficas;
- irradiância solar do PVGIS;
- inclinação dos módulos;
- azimute dos módulos;
- temperatura ambiente;
- perdas globais do sistema FV.

Importante:
-----------
Este módulo NÃO dimensiona a usina FV.

O dimensionamento ótimo continua sendo realizado pelo
modelo de otimização AMPL através da variável:

    pv_size_kw

O módulo solar apenas fornece:

    pv_cf[t]

que representa o fator de capacidade solar horário
do local analisado.

O modelo AMPL utiliza:

    pv_avail_kw[t] = pv_cf[t] * pv_size_kw

Portanto:

    pv_cf[t]
        -> comportamento solar realista

    pv_size_kw
        -> decisão ótima do modelo
"""

from dataclasses import asdict, dataclass
import json
import logging
import calendar
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pvlib

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURAÇÃO GEOGRÁFICA
# ============================================================

@dataclass
class PVLocationConfig:
    """
    Configuração geográfica do ponto de instalação FV.
    """

    # Latitude do local [graus decimais].
    latitude: float

    # Longitude do local [graus decimais].
    longitude: float

    # Altitude do local [m].
    altitude_m: float

    # Fuso horário.
    #
    # Exemplo:
    # "America/Sao_Paulo"
    timezone: str

    # Nome identificador do local.
    name: str = "local_pv"

    def __post_init__(self):
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude deve estar entre -90 e 90 graus.")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude deve estar entre -180 e 180 graus.")
        if not self.timezone:
            raise ValueError("timezone não pode ser vazio.")


# ============================================================
# CONFIGURAÇÃO SOLARIMÉTRICA DO SISTEMA FV
# ============================================================

@dataclass
class PVSystemConfig:
    """
    Configuração solarimétrica utilizada para gerar
    o perfil FV normalizado.

    IMPORTANTE:
    -----------
    Este módulo NÃO dimensiona o sistema FV.

    O objetivo é apenas calcular:
    - irradiância no plano dos módulos;
    - temperatura da célula;
    - perdas;
    - potência FV normalizada;
    - fator de capacidade pv_cf.
    """

    # ========================================================
    # ANO METEOROLÓGICO
    # ========================================================

    # Ano da base meteorológica do PVGIS.
    year: int = 2023
    api_url: str = "https://re.jrc.ec.europa.eu/api/v5_3/"
    radiation_database: str = "PVGIS-ERA5"

    # ========================================================
    # GEOMETRIA DOS MÓDULOS
    # ========================================================

    # Inclinação dos módulos [graus].
    #
    # Exemplos:
    # 0°  -> horizontal
    # 20° -> típico no Brasil
    # 30° -> inclinação elevada
    surface_tilt_deg: float = 20.0

    # Azimute dos módulos [graus].
    #
    # Convenção pvlib:
    #
    # 0°   -> norte
    # 90°  -> leste
    # 180° -> sul
    # 270° -> oeste
    #
    # Para sistemas fixos no Brasil normalmente:
    #
    # 0° -> orientação norte
    surface_azimuth_deg: float = 0.0

    # ========================================================
    # POTÊNCIA DE REFERÊNCIA
    # ========================================================

    # Potência DC de referência [kW].
    #
    # Utilizada apenas para normalização.
    #
    # NÃO representa a potência ótima do sistema.
    #
    # Recomenda-se manter:
    #
    # 1.0 kW
    reference_capacity_kw: float = 1.0

    # Relação potência DC dos módulos / potência AC do inversor.
    dc_ac_ratio: float = 1.20

    # Eficiência nominal do inversor.
    inverter_nominal_efficiency: float = 0.96

    # Coeficiente térmico de potência [1/°C].
    gamma_pdc_per_c: float = -0.0035

    # ========================================================
    # PERDAS GLOBAIS
    # ========================================================

    # Perdas globais do sistema FV [%].
    #
    # Inclui:
    # - sujeira;
    # - mismatch;
    # - cabeamento;
    # - disponibilidade;
    # - perdas elétricas.
    losses_percent: float = 14.0

    # ========================================================
    # MODELO TÉRMICO
    # ========================================================

    # Modelo de temperatura da célula.
    #
    # Opções:
    #
    # "faiman"
    # "sapm"
    temperature_model: str = "faiman"

    # Coeficientes térmicos configuráveis.
    faiman_u0: float = 25.0
    faiman_u1: float = 6.84
    sapm_a: float = -3.47
    sapm_b: float = -0.0594
    sapm_delta_t: float = 3.0

    def __post_init__(self):
        if not 0.0 <= self.surface_tilt_deg <= 90.0:
            raise ValueError(
                "surface_tilt_deg deve estar entre 0 e 90 graus."
            )
        if not 0.0 <= self.surface_azimuth_deg < 360.0:
            raise ValueError(
                "surface_azimuth_deg deve estar entre 0 (inclusive) "
                "e 360 (exclusive)."
            )
        if self.reference_capacity_kw <= 0.0:
            raise ValueError("reference_capacity_kw deve ser positivo.")
        if self.dc_ac_ratio <= 0.0:
            raise ValueError("dc_ac_ratio deve ser positivo.")
        if not 0.0 < self.inverter_nominal_efficiency <= 1.0:
            raise ValueError(
                "inverter_nominal_efficiency deve estar em (0, 1]."
            )
        if not 0.0 <= self.losses_percent < 100.0:
            raise ValueError(
                "losses_percent deve estar entre 0 (inclusive) "
                "e 100 (exclusive)."
            )
        if self.temperature_model.lower() not in {"faiman", "sapm"}:
            raise ValueError(
                "temperature_model deve ser 'faiman' ou 'sapm'."
            )


# ============================================================
# DOWNLOAD DE DADOS PVGIS
# ============================================================

def get_weather_pvgis(
    location_config: PVLocationConfig,
    system_config: PVSystemConfig,
) -> pd.DataFrame:
    """
    Obtém dados meteorológicos do PVGIS.

    O PVGIS já fornece irradiância no plano inclinado
    quando surface_tilt e surface_azimuth são definidos.
    """

    # ========================================================
    # CONSULTA AO PVGIS
    # ========================================================

    if system_config.api_url != "https://re.jrc.ec.europa.eu/api/v5_3/":
        raise ValueError("Este conector exige a API PVGIS 5.3 validada; PVGIS 6 usa outro esquema.")
    if not 2005 <= system_config.year <= 2023:
        raise ValueError("PVGIS 5.3 disponibiliza anos de 2005 a 2023; não há fallback silencioso de ano.")
    weather, metadata = pvlib.iotools.get_pvgis_hourly(
        latitude=location_config.latitude,
        longitude=location_config.longitude,
        start=system_config.year,
        end=system_config.year,
        raddatabase=system_config.radiation_database,
        url=system_config.api_url,
        components=True,
        surface_tilt=system_config.surface_tilt_deg,
        surface_azimuth=system_config.surface_azimuth_deg,
        outputformat="json",
        usehorizon=True,
        pvcalculation=False,
        map_variables=True,
        timeout=60,
    )

    # ========================================================
    # AJUSTE DE TIMEZONE
    # ========================================================

    # Caso o índice temporal venha sem timezone,
    # assume UTC.
    if weather.index.tz is None:
        weather.index = weather.index.tz_localize("UTC")

    # Um ano pedido não pode ser aceito como completo apenas porque a API respondeu 200.
    utc_index = weather.index.tz_convert("UTC")
    expected_hours = (366 if calendar.isleap(system_config.year) else 365) * 24
    if (len(weather) != expected_hours or utc_index.has_duplicates
            or not utc_index.is_monotonic_increasing
            or not (utc_index.year == system_config.year).all()
            or not (utc_index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()):
        raise ValueError("PVGIS retornou um ano incompleto, incorreto ou com lacunas horárias.")

    # Converte para o fuso horário local.
    weather = weather.tz_convert(
        location_config.timezone
    )

    # ========================================================
    # ORGANIZAÇÃO DAS COLUNAS
    # ========================================================

    # Algumas versões do pvlib/PVGIS retornam apenas as componentes
    # quando components=True. Nesse caso, reconstrói a irradiância
    # global no plano inclinado de forma fisicamente consistente.
    if "poa_global" not in weather.columns:
        poa_components = {
            "poa_direct",
            "poa_sky_diffuse",
            "poa_ground_diffuse",
        }
        missing_components = poa_components - set(weather.columns)
        if missing_components:
            raise ValueError(
                "PVGIS não retornou poa_global nem todas as componentes "
                "necessárias para reconstruí-la. Componentes ausentes: "
                f"{sorted(missing_components)}"
            )
        weather["poa_global"] = (
            weather["poa_direct"]
            + weather["poa_sky_diffuse"]
            + weather["poa_ground_diffuse"]
        )

    required_columns = {"poa_global", "temp_air", "wind_speed"}
    missing_columns = required_columns - set(weather.columns)
    if missing_columns:
        raise ValueError(
            "PVGIS não retornou as colunas obrigatórias: "
            f"{sorted(missing_columns)}"
        )

    if not weather.index.is_monotonic_increasing:
        weather = weather.sort_index()
    if weather.index.has_duplicates:
        raise ValueError("A série meteorológica contém timestamps duplicados.")
    if weather[list(required_columns)].isna().any().any():
        raise ValueError(
            "A série meteorológica contém valores ausentes nas "
            "variáveis obrigatórias."
        )
    if not np.isfinite(weather[list(required_columns)].to_numpy(dtype=float)).all():
        raise ValueError("PVGIS retornou valores meteorológicos não finitos.")

    # Remove valores negativos fisicamente inválidos.
    weather["poa_global"] = (
        weather["poa_global"]
        .clip(lower=0.0)
    )

    # ========================================================
    # DEBUG OPCIONAL
    # ========================================================

    logger.debug("Colunas retornadas pelo PVGIS: %s", weather.columns.tolist())
    logger.debug(
        "Resumo estatístico POA:\n%s",
        weather["poa_global"].describe(),
    )

    # ========================================================
    # RETORNO FINAL
    # ========================================================

    selected_columns = [
        column
        for column in [
            "poa_global",
            "poa_direct",
            "poa_sky_diffuse",
            "poa_ground_diffuse",
            "temp_air",
            "wind_speed",
        ]
        if column in weather.columns
    ]
    result = weather[selected_columns].copy()
    result.attrs["pvgis_metadata"] = metadata
    result.attrs["solar_provenance"] = {
        "api_url": system_config.api_url,
        "radiation_database": system_config.radiation_database,
        "meteorological_year": system_config.year,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_hours": expected_hours,
        "received_hours": len(weather),
        "complete_hourly_year": True,
        "period_basis": "ano UTC da fonte; timestamps convertidos ao fuso local",
        "reference_selection": "último ano completo validado; não atualização automática por data atual",
    }
    result.attrs["location_config"] = asdict(location_config)
    result.attrs["system_config"] = asdict(system_config)
    result.attrs["altitude_note"] = (
        "altitude_m é mantida como metadado; a consulta horária do "
        "PVGIS utiliza a elevação de sua própria base geográfica."
    )
    return result


# ============================================================
# SIMULAÇÃO FV NORMALIZADA
# ============================================================

def simulate_normalized_pv_profile(
    location_config: PVLocationConfig,
    system_config: PVSystemConfig,
    weather: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Calcula perfil FV normalizado do local.

    A saída principal é:

        pv_cf

    que será utilizada pelo modelo AMPL.
    """

    # ========================================================
    # DADOS METEOROLÓGICOS
    # ========================================================

    # Caso o usuário não forneça dados meteorológicos,
    # busca automaticamente no PVGIS.
    if weather is None:

        weather = get_weather_pvgis(
            location_config,
            system_config,
        )

    # ========================================================
    # IRRADIÂNCIA NO PLANO DO ARRANJO
    # ========================================================

    required_columns = {"poa_global", "temp_air", "wind_speed"}
    missing_columns = required_columns - set(weather.columns)
    if missing_columns:
        raise ValueError(
            "Dados meteorológicos sem colunas obrigatórias: "
            f"{sorted(missing_columns)}"
        )
    if len(weather) < 2:
        raise ValueError(
            "São necessários ao menos dois registros meteorológicos."
        )
    if not isinstance(weather.index, pd.DatetimeIndex):
        raise TypeError("O índice meteorológico deve ser DatetimeIndex.")
    if not weather.index.is_monotonic_increasing:
        weather = weather.sort_index()
    if weather.index.has_duplicates:
        raise ValueError("O índice meteorológico contém duplicatas.")
    if weather[list(required_columns)].isna().any().any():
        raise ValueError(
            "Os dados meteorológicos contêm valores ausentes."
        )

    # O PVGIS já forneceu irradiância no plano inclinado.
    poa_global = weather["poa_global"].clip(lower=0.0)

    # ========================================================
    # TEMPERATURA DA CÉLULA FV
    # ========================================================

    # Modelo térmico de Faiman.
    if system_config.temperature_model.lower() == "faiman":

        temp_cell = pvlib.temperature.faiman(
            poa_global=poa_global,
            temp_air=weather["temp_air"],
            wind_speed=weather["wind_speed"],
            u0=system_config.faiman_u0,
            u1=system_config.faiman_u1,
        )

    # Modelo SAPM.
    elif system_config.temperature_model.lower() == "sapm":

        temp_cell = pvlib.temperature.sapm_cell(
            poa_global=poa_global,
            temp_air=weather["temp_air"],
            wind_speed=weather["wind_speed"],
            a=system_config.sapm_a,
            b=system_config.sapm_b,
            deltaT=system_config.sapm_delta_t,
        )

    # Modelo inválido.
    else:

        raise ValueError(
            "temperature_model deve ser "
            "'faiman' ou 'sapm'."
        )

    # ========================================================
    # MODELO PVWATTS
    # ========================================================

    # Potência DC de referência [W].
    pdc0_w = (
        system_config.reference_capacity_kw
        * 1000.0
    )

    # Potência DC de referência.
    pv_reference_dc_raw_w = pvlib.pvsystem.pvwatts_dc(
        effective_irradiance=poa_global,
        temp_cell=temp_cell,
        pdc0=pdc0_w,
        gamma_pdc=system_config.gamma_pdc_per_c,
        temp_ref=25.0,
    ).clip(lower=0.0)

    # ========================================================
    # PERDAS GLOBAIS
    # ========================================================

    # Calcula fator de perdas.
    loss_factor = (
        100.0 - system_config.losses_percent
    ) / 100.0

    # Aplica perdas globais.
    pv_reference_dc_net_w = (
        pv_reference_dc_raw_w * loss_factor
    )

    # ========================================================
    # LIMITAÇÃO DO INVERSOR
    # ========================================================

    # A potência AC nominal é derivada da capacidade DC de referência
    # e da relação DC/AC, evitando bases de normalização conflitantes.
    pac_nominal_w = pdc0_w / system_config.dc_ac_ratio

    # No modelo PVWatts do inversor, pdc0 é o limite de entrada DC
    # correspondente à potência AC nominal e à eficiência nominal.
    inverter_pdc0_w = (
        pac_nominal_w
        / system_config.inverter_nominal_efficiency
    )

    pv_reference_ac_w = pvlib.inverter.pvwatts(
        pdc=pv_reference_dc_net_w,
        pdc0=inverter_pdc0_w,
        eta_inv_nom=system_config.inverter_nominal_efficiency,
    )
    pv_reference_ac_w = pd.Series(
        pv_reference_ac_w,
        index=weather.index,
    ).clip(
        lower=0.0,
        upper=pac_nominal_w,
    )

    # ========================================================
    # FATOR DE CAPACIDADE FV
    # ========================================================

    # Perfil normalizado utilizado pelo AMPL.
    pv_cf = (
        pv_reference_ac_w / pdc0_w
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    # ========================================================
    # DATAFRAME FINAL
    # ========================================================

    result = pd.DataFrame(index=weather.index)

    result["poa_global_wm2"] = poa_global
    result["temp_air_c"] = weather["temp_air"]
    result["wind_speed_ms"] = weather["wind_speed"]
    result["temp_cell_c"] = temp_cell
    result["pv_reference_dc_raw_kw"] = (
        pv_reference_dc_raw_w / 1000.0
    )
    result["pv_reference_dc_kw"] = (
        pv_reference_dc_net_w / 1000.0
    )
    result["pv_reference_ac_kw"] = (
        pv_reference_ac_w / 1000.0
    )
    result["pv_cf"] = pv_cf
    result["pv_system_losses_kw"] = (
        (pv_reference_dc_raw_w - pv_reference_dc_net_w)
        / 1000.0
    )
    result["pv_inverter_losses_kw"] = (
        (pv_reference_dc_net_w - pv_reference_ac_w)
        .clip(lower=0.0)
        / 1000.0
    )
    result["pv_clipping_kw"] = (
        (
            pv_reference_dc_net_w
            * system_config.inverter_nominal_efficiency
            - pac_nominal_w
        )
        .clip(lower=0.0)
        / 1000.0
    )

    result.attrs.update(weather.attrs)
    result.attrs["system_config"] = asdict(system_config)
    result.attrs["pv_size_basis"] = "DC kWp"
    result.attrs["pv_cf_definition"] = "AC kW delivered per DC kWp"

    return result


# ============================================================
# CONVERSÃO PARA O OTIMIZADOR
# ============================================================

def build_pv_cf_for_optimizer(
    pv_result: pd.DataFrame,
    dt_h: float,
    horizon_h: float,
    start_time: Optional[str] = None,
) -> dict:
    """
    Converte o perfil anual FV para o horizonte
    do problema de otimização.
    """

    # ========================================================
    # INSTANTE INICIAL
    # ========================================================

    if start_time is None:

        start = pv_result.index[0]

    else:

        start = pd.Timestamp(start_time)

        # Ajusta timezone.
        if start.tzinfo is None:

            start = start.tz_localize(
                pv_result.index.tz
            )

        else:

            start = start.tz_convert(
                pv_result.index.tz
            )

    # ========================================================
    # DEFINIÇÃO DO HORIZONTE
    # ========================================================

    n, frequency = _validate_optimizer_horizon(dt_h, horizon_h)

    # Índice temporal alvo.
    target_index = pd.date_range(
        start=start,
        periods=n,
        freq=frequency,
        tz=pv_result.index.tz,
    )

    # ========================================================
    # INTERPOLAÇÃO TEMPORAL
    # ========================================================

    source = pv_result["pv_cf"].sort_index()
    if source.index.has_duplicates:
        raise ValueError("O perfil FV contém timestamps duplicados.")

    pv_cf_series = (
        source
        .reindex(
            pv_result.index.union(target_index)
        )
        .interpolate(method="time")
        .reindex(target_index)
        .clip(lower=0.0, upper=1.0)
    )

    if pv_cf_series.isna().any():
        missing = pv_cf_series[pv_cf_series.isna()].index
        raise ValueError(
            "O horizonte solicitado não está integralmente coberto "
            f"pelo perfil FV. Primeiro timestamp ausente: {missing[0]}"
        )

    # ========================================================
    # CONVERSÃO PARA DICIONÁRIO
    # ========================================================

    return {
        i: float(value)
        for i, value in enumerate(
            pv_cf_series.values
        )
    }


# ============================================================
# EXPORTAÇÃO CSV
# ============================================================

def save_pv_profile(
    pv_result: pd.DataFrame,
    output_path,
) -> None:
    """
    Salva perfil FV em CSV.

    Útil para:
    - auditoria;
    - validação;
    - dissertação;
    - integração com outros modelos.
    """

    pv_result.to_csv(
        output_path,
        index=True,
    )


def _json_default(value):
    """Converte objetos comuns do pandas/PVGIS para JSON."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def save_pv_metadata(
    pv_result: pd.DataFrame,
    output_path,
) -> None:
    """Salva metadados de entrada e convenções do perfil FV."""
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            dict(pv_result.attrs),
            file,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )

def summarize_pv_resource(pv_result: pd.DataFrame) -> dict:
    """
    Calcula indicadores anuais e mensais do recurso FV.
    """

    dt_h = (
        pv_result.index[1] - pv_result.index[0]
    ).total_seconds() / 3600

    pv_result = pv_result.copy()

    pv_result["energy_kwh_per_kwp"] = (
        pv_result["pv_cf"] * dt_h
    )

    monthly = pv_result.resample("ME").agg(
        pv_cf_mean=("pv_cf", "mean"),
        energy_kwh_per_kwp=("energy_kwh_per_kwp", "sum"),
        poa_mean_wm2=("poa_global_wm2", "mean"),
    )

    annual = {
        "pv_cf_mean_annual": float(pv_result["pv_cf"].mean()),
        "energy_kwh_per_kwp_annual": float(
            pv_result["energy_kwh_per_kwp"].sum()
        ),
        "poa_mean_annual_wm2": float(
            pv_result["poa_global_wm2"].mean()
        ),
    }

    return {
        "annual": annual,
        "monthly": monthly,
    }



def save_pv_summary(pv_summary: dict, output_dir) -> None:
    """
    Salva resumo solar anual e mensal em CSV.
    """

    monthly = pv_summary["monthly"]
    monthly.to_csv(output_dir / "pv_monthly_summary.csv")

    annual = pd.DataFrame([pv_summary["annual"]])
    annual.to_csv(
        output_dir / "pv_annual_summary.csv",
        index=False,
    )
def build_annual_average_pv_cf_for_optimizer(
    pv_result: pd.DataFrame,
    dt_h: float,
    horizon_h: float,
) -> dict:
    """
    Constrói um perfil FV médio anual para o otimizador.

    Calcula a média anual de pv_cf para cada horário do dia.
    """

    n, frequency = _validate_optimizer_horizon(dt_h, horizon_h)

    df = pv_result.copy()

    df = df.resample(frequency).interpolate(
        method="time"
    )

    df["time_of_day"] = df.index.strftime("%H:%M")

    annual_average = (
        df.groupby("time_of_day")["pv_cf"]
        .mean()
        .sort_index()
    )

    target_times = pd.date_range(
        start="2000-01-01 00:00:00",
        periods=n,
        freq=frequency,
    ).strftime("%H:%M")

    pv_cf_values = [
        float(annual_average.get(t, 0.0))
        for t in target_times
    ]

    return {
        i: pv_cf_values[i]
        for i in range(n)
    }


def _validate_optimizer_horizon(
    dt_h: float,
    horizon_h: float,
) -> tuple[int, pd.Timedelta]:
    """Valida e converte o horizonte do otimizador."""
    if dt_h <= 0.0:
        raise ValueError("dt_h deve ser positivo.")
    if horizon_h <= 0.0:
        raise ValueError("horizon_h deve ser positivo.")

    intervals = horizon_h / dt_h
    rounded_intervals = round(intervals)
    if abs(intervals - rounded_intervals) > 1e-9:
        raise ValueError(
            "horizon_h deve ser múltiplo inteiro de dt_h."
        )

    frequency = pd.to_timedelta(dt_h, unit="h")
    if frequency <= pd.Timedelta(0):
        raise ValueError("dt_h gerou uma frequência temporal inválida.")

    return int(rounded_intervals), frequency
