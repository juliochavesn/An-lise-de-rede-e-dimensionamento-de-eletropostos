"""Integracao locacional preliminar com a BDGD da distribuidora.

Esta primeira fase identifica o segmento MT mais proximo do ponto configurado
e calcula um teto termico de triagem. O resultado nao substitui estudo de
acesso, fluxo de potencia nem parecer da concessionaria.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
from src.grid_data_quality import operational_rows, local_utm_epsg


# Codigos de tensao encontrados na BDGD da CPFL Paulista. Valores em kV,
# conforme o Dicionario de Dados ANEEL do SIG-R.
TENSION_CODE_KV = {
    "35": 5.0,
    "36": 6.0,
    "37": 6.6,
    "38": 6.93,
    "39": 7.96,
    "40": 8.67,
    "41": 11.4,
    "42": 11.9,
    "43": 12.0,
    "44": 12.6,
    "45": 12.7,
    "46": 13.2,
    "47": 13.337,
    "48": 13.53,
    "49": 13.8,
    "50": 13.86,
    "51": 14.14,
    "52": 14.19,
    "53": 14.4,
    "54": 14.835,
    "55": 15.0,
    "57": 19.053,
    "58": 19.919,
    "59": 21.0,
    "60": 21.5,
    "61": 22.0,
    "62": 23.0,
    "63": 23.1,
    "64": 23.827,
    "65": 24.0,
    "66": 24.2,
    "67": 25.0,
    "68": 25.8,
    "69": 27.0,
    "70": 30.0,
    "71": 33.0,
    "72": 34.5,
}


def bdgd_reference_date(network_config: dict) -> str | None:
    """Obtém a data-base sem confundi-la com o calendário meteorológico."""
    configured = network_config.get("bdgd_reference_date")
    path = Path(network_config["bdgd_path"])
    match = re.search(r"_(20\d{2}-\d{2}-\d{2})_", path.name)
    candidates = [configured, match.group(1) if match else None]
    stem = path.name[:-8] if path.name.lower().endswith(".gdb.zip") else path.stem
    metadata = path.parent / f"{stem}.json"
    if metadata.exists():
        try:
            item = json.loads(metadata.read_text(encoding="utf-8"))
            candidates.extend([item.get("reference_date"), next((tag for tag in item.get("tags", [])
                if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(tag))), None)])
        except (OSError, ValueError, TypeError):
            pass
    for value in candidates:
        if value:
            try:
                return date.fromisoformat(str(value)).isoformat()
            except ValueError:
                continue
    return None


def _safe_extract_gdb(zip_path: Path) -> Path:
    """Extrai o ZIP para cache temporario, bloqueando path traversal."""
    cache_root = Path(tempfile.gettempdir()) / "eletroposto_bdgd_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    fingerprint = f"{zip_path.stem}_{zip_path.stat().st_size}_{zip_path.stat().st_mtime_ns}"
    target = cache_root / fingerprint
    marker = target / ".complete"

    if not marker.exists():
        target.mkdir(parents=True, exist_ok=True)
        target_resolved = target.resolve()
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                destination = (target / member.filename).resolve()
                if target_resolved not in destination.parents and destination != target_resolved:
                    raise ValueError(f"Caminho inseguro no ZIP da BDGD: {member.filename}")
            archive.extractall(target)
        marker.touch()

    candidates = list(target.glob("*.gdb"))
    if len(candidates) != 1:
        raise ValueError(f"Esperado um diretorio .gdb no ZIP; encontrados {len(candidates)}")
    return candidates[0]


def resolve_gdb_path(source: str | Path) -> Path:
    """Resolve GDB/GeoPackage ou descompacta um ZIP para cache temporário."""
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Base BDGD nao encontrada: {path}")
    if path.is_dir() and path.suffix.lower() == ".gdb":
        return path
    if path.is_file() and path.suffix.lower() == ".zip":
        return _safe_extract_gdb(path)
    if path.is_file() and path.suffix.lower() == ".gpkg":
        return path
    raise ValueError("bdgd_path deve apontar para um arquivo .zip, diretório .gdb ou arquivo .gpkg")


def _sql_text(value: object) -> str:
    return str(value).replace("'", "''")


def _nearest_feature(gdb_path: Path, layer: str, columns: list[str], latitude: float,
                     longitude: float, max_radius_km: float):
    try:
        import geopandas as gpd
        import pyogrio
        from shapely.geometry import Point
    except ImportError as exc:
        raise RuntimeError(
            "A leitura da BDGD requer pyogrio, geopandas, shapely e pyproj. "
            "Instale as dependencias de requirements.txt."
        ) from exc

    # Aproximacao apenas para limitar a leitura espacial. A distancia final e
    # calculada em SIRGAS 2000 / UTM da zona correspondente.
    radii_km = [0.25, 0.5, 1.0, 2.0, 5.0, max_radius_km]
    frame = None
    used_radius = None
    if not all(math.isfinite(v) for v in (latitude, longitude, max_radius_km)) or max_radius_km <= 0:
        raise ValueError("Coordenadas e raio devem ser finitos; raio deve ser positivo.")
    zone = int((longitude + 180.0) // 6.0) + 1
    utm_epsg = local_utm_epsg(latitude, longitude)
    point = gpd.GeoSeries([Point(longitude, latitude)], crs="EPSG:4674").to_crs(epsg=utm_epsg).iloc[0]
    for radius_km in sorted(set(r for r in radii_km if r <= max_radius_km)):
        delta_lat = radius_km / 111.0
        delta_lon = radius_km / max(111.0 * math.cos(math.radians(latitude)), 1e-6)
        bbox = (
            longitude - delta_lon,
            latitude - delta_lat,
            longitude + delta_lon,
            latitude + delta_lat,
        )
        candidate = pyogrio.read_dataframe(
            gdb_path, layer=layer, bbox=bbox, columns=columns
        )
        candidate = operational_rows(candidate, "SITCONT")
        if not candidate.empty:
            frame = candidate
            used_radius = radius_km
            # A primeira caixa não garante o vizinho mais próximo se ele
            # estiver num canto. Expanda até o círculo inscrito conter o
            # candidato, com margem para a aproximação geográfica da caixa.
            nearest_distance = candidate.to_crs(epsg=utm_epsg).geometry.distance(point).min()
            if nearest_distance <= radius_km * 980.0:
                break

    if frame is None or frame.empty:
        raise LookupError(
            f"Nenhuma feicao de {layer} encontrada em {max_radius_km:.1f} km"
        )

    zone = int((longitude + 180.0) // 6.0) + 1
    utm_epsg = local_utm_epsg(latitude, longitude)
    point = gpd.GeoSeries(
        [Point(longitude, latitude)], crs="EPSG:4674"
    ).to_crs(epsg=utm_epsg).iloc[0]
    projected = frame.to_crs(epsg=utm_epsg)
    distances = projected.geometry.distance(point)
    index = distances.idxmin()
    if not math.isfinite(float(distances.loc[index])) or distances.loc[index] > max_radius_km * 1000:
        raise LookupError(f"Nenhuma feição operacional de {layer} dentro do raio de {max_radius_km:.1f} km.")
    return frame.loc[index], float(distances.loc[index]), used_radius


def assess_bdgd_connection(location: dict, network_config: dict) -> dict:
    """Calcula o teto termico preliminar do segmento MT mais proximo."""
    if network_config.get("connection_level") != "medium_voltage":
        raise NotImplementedError("A primeira fase implementa apenas conexao em media tensao")

    gdb_path = resolve_gdb_path(network_config["bdgd_path"])
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    segment, distance_m, search_radius_km = _nearest_feature(
        gdb_path,
        "SSDMT",
        ["COD_ID", "CTMT", "SUB", "CONJ", "TIP_CND", "PAC_1", "PAC_2", "SITCONT", "COMP"],
        latitude,
        longitude,
        float(network_config.get("max_search_radius_km", 10.0)),
    )

    import pyogrio

    feeder_id = _sql_text(segment["CTMT"])
    conductor_id = _sql_text(segment["TIP_CND"])
    feeder = pyogrio.read_dataframe(
        gdb_path,
        sql=f"SELECT * FROM CTMT WHERE COD_ID='{feeder_id}'",
        read_geometry=False,
    )
    conductor = pyogrio.read_dataframe(
        gdb_path,
        sql=f"SELECT * FROM SEGCON WHERE COD_ID='{conductor_id}'",
        read_geometry=False,
    )
    if feeder.empty or conductor.empty:
        raise LookupError("Alimentador ou condutor associado ao segmento nao foi encontrado")

    voltage_code = str(feeder.iloc[0]["TEN_NOM"])
    voltage_kv = TENSION_CODE_KV.get(voltage_code)
    if voltage_kv is None:
        raise ValueError(f"Codigo de tensao nao mapeado: {voltage_code}")

    current_a = float(conductor.iloc[0]["CMAX"])
    if not 0.0 < current_a < 900.0:
        raise ValueError(
            f"CMAX={current_a:g} A parece ausente/sentinela; nao sera usado como capacidade"
        )

    power_factor = float(network_config.get("power_factor", 0.95))
    utilization = float(network_config.get("thermal_utilization_factor", 0.80))
    if not 0.0 < power_factor <= 1.0 or not 0.0 < utilization <= 1.0:
        raise ValueError("power_factor e thermal_utilization_factor devem estar em (0, 1]")

    thermal_limit_kw = math.sqrt(3.0) * voltage_kv * current_a * power_factor * utilization
    monthly_energy = [float(feeder.iloc[0][f"ENE_{month:02d}"]) for month in range(1, 13)]

    return {
        "status": "ok",
        "method": "nearest_mt_segment_thermal_screening",
        "warning": (
            "Teto termico de triagem; nao representa hosting capacity oficial nem "
            "substitui estudo de acesso da concessionaria."
        ),
        "location": {"latitude": latitude, "longitude": longitude},
        "gdb_path": str(gdb_path),
        "segment_id": str(segment["COD_ID"]),
        "feeder_id": str(segment["CTMT"]),
        "substation_id": str(segment["SUB"]),
        "conductor_id": str(segment["TIP_CND"]),
        "distance_to_mt_segment_m": distance_m,
        "search_radius_km": search_radius_km,
        "voltage_code": voltage_code,
        "voltage_kv": voltage_kv,
        "conductor_cmax_a": current_a,
        "power_factor": power_factor,
        "thermal_utilization_factor": utilization,
        "estimated_network_limit_kw": thermal_limit_kw,
        "feeder_monthly_energy": monthly_energy,
    }


def combine_grid_limits(network_limit_kw: float | None, manual_limit_kw: float,
                        source: str, interval_count: int) -> np.ndarray:
    """Combina o limite estimado da rede com o limite manual/contratual."""
    manual = np.full(interval_count, float(manual_limit_kw))
    if source == "manual":
        return manual
    if network_limit_kw is None:
        raise ValueError("network_limit_kw e obrigatorio nos modos bdgd e minimum")
    network = np.asarray(network_limit_kw, dtype=float)
    if network.ndim == 0:
        network = np.full(interval_count, float(network))
    if network.shape != (interval_count,):
        raise ValueError(
            "O perfil de limite BDGD deve ter um valor por intervalo."
        )
    if not np.all(np.isfinite(network)) or np.any(network < 0.0):
        raise ValueError("O perfil de limite BDGD contem valores invalidos.")
    if source == "bdgd":
        return network
    if source == "minimum":
        return np.minimum(network, manual)
    raise ValueError("limit_source deve ser 'manual', 'bdgd' ou 'minimum'")


def build_grid_limit_profile(scenario: dict, location: dict, network_config: dict,
                             output_dir: Path,
                             diagnostic_filename: str = "grid_connection_assessment.json",
                             ) -> dict[int, float]:
    """Gera o perfil efetivo e salva o diagnostico da conexao para auditoria."""
    output_dir.mkdir(parents=True, exist_ok=True)
    intervals = int(float(scenario["horizon_h"]) / float(scenario["dt_h"]))
    source = network_config.get("limit_source", "manual")
    assessment = None
    network_limit_kw = None
    residual_metadata = None
    reference_date = bdgd_reference_date(network_config)
    network_scenario = dict(scenario)
    network_profile_config = dict(network_config)
    network_profile_config["bdgd_reference_date"] = reference_date
    if reference_date:
        network_scenario["calendar_start"] = f"{reference_date[:4]}-01-01 00:00:00"

    if source != "manual":
        try:
            assessment = assess_bdgd_connection(location, network_config)
            network_limit_kw = assessment["estimated_network_limit_kw"]
            if network_config.get("capacity_method", "thermal") == "residual":
                connection_detail = None
                connection_path = None
                if network_config.get(
                    "enable_detailed_connection_report", True
                ):
                    from src.grid_connection_detail import (
                        assess_connection_path,
                    )

                    connection_detail, connection_path = assess_connection_path(
                        Path(assessment["gdb_path"]),
                        assessment,
                        network_profile_config,
                    )
                    connection_detail["location"] = assessment["location"]
                    connection_detail["substation_id"] = assessment["substation_id"]
                    assessment["connection_detail"] = connection_detail

                from src.grid_residual_capacity import (
                    estimate_residual_capacity_profile,
                )

                path_capacity_kw = (
                    connection_detail["path_thermal_limit_kw"]
                    if connection_detail is not None
                    else assessment["estimated_network_limit_kw"]
                )
                network_limit_kw, residual_audit, residual_metadata = (
                    estimate_residual_capacity_profile(
                        Path(assessment["gdb_path"]),
                        assessment["feeder_id"],
                        network_scenario,
                        min(
                            assessment["estimated_network_limit_kw"],
                            path_capacity_kw,
                        ),
                        network_profile_config,
                    )
                )
                residual_audit.to_csv(
                    output_dir / "grid_residual_capacity_profile.csv",
                    index=False,
                )
                assessment["residual_capacity"] = residual_metadata
                if network_config.get(
                    "enable_critical_period_analysis", True
                ):
                    from src.grid_capacity_analysis import (
                        run_capacity_critical_analysis,
                    )

                    critical_analysis = run_capacity_critical_analysis(
                        residual_audit,
                        output_dir,
                        network_config,
                    )
                    residual_metadata["critical_period_analysis"] = (
                        critical_analysis
                    )
                    assessment["critical_period_analysis"] = critical_analysis
                if connection_detail is not None:
                    from src.grid_connection_detail import (
                        write_connection_detail_outputs,
                    )

                    write_connection_detail_outputs(
                        connection_detail,
                        connection_path,
                        residual_metadata,
                        output_dir,
                    )
        except Exception as exc:
            if network_config.get("on_error", "raise") != "manual":
                raise
            source = "manual"
            network_limit_kw = None
            residual_metadata = None
            assessment = dict(assessment or {})
            assessment.update(status="fallback_manual", error=str(exc),
                              error_type=type(exc).__name__,
                              capacity_conclusion="inconclusive_not_zero")

    effective = combine_grid_limits(
        network_limit_kw,
        float(scenario["base_grid_limit_kw"]),
        source,
        intervals,
    )
    physical_values = (
        np.asarray(network_limit_kw, dtype=float)
        if network_limit_kw is not None
        else np.array([], dtype=float)
    )
    physical_constant = (
        physical_values.size > 0
        and np.allclose(physical_values, physical_values.flat[0])
    )
    diagnostic = {
        "configured_limit_source": network_config.get("limit_source", "manual"),
        "effective_limit_source": source,
        "manual_or_utility_limit_kw": float(scenario["base_grid_limit_kw"]),
        "manual_limit_applied": source in {"manual", "minimum"},
        "capacity_method": network_config.get("capacity_method", "thermal"),
        "bdgd_reference_date": reference_date,
        "network_profile_calendar_start": network_scenario.get("calendar_start"),
        "network_calendar_is_independent_from_solar": True,
        "physical_network_limit_kw": (
            float(physical_values.flat[0]) if physical_constant else None
        ),
        "physical_network_limit_kw_min": (
            float(physical_values.min()) if physical_values.size else None
        ),
        "physical_network_limit_kw_mean": (
            float(physical_values.mean()) if physical_values.size else None
        ),
        "physical_network_limit_kw_max": (
            float(physical_values.max()) if physical_values.size else None
        ),
        "effective_grid_limit_kw_min": float(effective.min()),
        "effective_grid_limit_kw_max": float(effective.max()),
        "assessment": assessment,
    }
    (output_dir / diagnostic_filename).write_text(
        json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {index: float(value) for index, value in enumerate(effective)}


def build_network_aware_tariff(tariff: dict, grid_limit_profile: dict,
                               network_config: dict) -> dict:
    """Define o teto contratual conforme a semantica do modo de rede.

    Em ``bdgd``, o valor manual de ``contracted_demand_max_kw`` nao limita a
    otimizacao: a demanda contratada pode crescer ate o menor limite fisico do
    perfil da rede. Nos modos ``manual`` e ``minimum``, o teto informado pelo
    usuario permanece inalterado.
    """
    result = dict(tariff)
    if network_config.get("limit_source", "manual") != "bdgd":
        return result

    if not grid_limit_profile:
        raise ValueError(
            "O modo bdgd exige um perfil de limite da rede nao vazio."
        )

    values = [float(value) for value in grid_limit_profile.values()]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("O perfil de limite da rede contem valores invalidos.")

    # O contrato e uma variavel comercial escalar. O perfil grid_limit_kw[t]
    # ja aplica o limite fisico de cada intervalo; portanto, o seu teto deve
    # admitir o maior valor do perfil, sem transformar o pior horario em um
    # limite artificial para todo o ano.
    network_ceiling_kw = max(values)
    contracted_min_kw = float(result.get("contracted_demand_min_kw", 0.0))
    if contracted_min_kw > network_ceiling_kw:
        raise ValueError(
            "A demanda contratada minima excede o limite fisico da rede."
        )

    result["contracted_demand_max_kw"] = network_ceiling_kw
    return result
