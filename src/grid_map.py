"""Leitura espacial leve da BDGD para a interface cartográfica local."""

from __future__ import annotations

import json
import math

from .grid_bdgd import resolve_gdb_path
from .grid_data_quality import local_utm_epsg


def load_bdgd_coverage(network_config: dict) -> dict:
    """Retorna o polígono oficial de área de atuação presente na BDGD."""
    import pyogrio

    gdb = resolve_gdb_path(network_config["bdgd_path"])
    coverage = pyogrio.read_dataframe(gdb, layer="ARAT")
    if coverage.empty:
        raise LookupError("A camada ARAT da BDGD está vazia.")
    coverage = coverage.to_crs(4326)
    geometry = coverage.geometry.union_all()
    minx, miny, maxx, maxy = geometry.bounds
    return {
        "geojson": json.loads(coverage.to_json()),
        "bounds": [[float(miny), float(minx)], [float(maxy), float(maxx)]],
        "geometry": geometry,
        "description": str(coverage.iloc[0].get("DESCR", "Área de atuação")),
    }


def point_is_covered(latitude: float, longitude: float, coverage: dict) -> bool:
    """Aceita pontos internos ou exatamente sobre o limite da área BDGD."""
    from shapely.geometry import Point

    return bool(coverage["geometry"].covers(Point(float(longitude), float(latitude))))


def load_network_window(location: dict, network_config: dict, radius_km: float = 1.5) -> dict:
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point

    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    delta_lat = radius_km / 111.0
    delta_lon = radius_km / max(111.0 * math.cos(math.radians(latitude)), 1e-6)
    bbox = (longitude - delta_lon, latitude - delta_lat,
            longitude + delta_lon, latitude + delta_lat)
    gdb = resolve_gdb_path(network_config["bdgd_path"])

    segments = pyogrio.read_dataframe(
        gdb, layer="SSDMT", bbox=bbox,
        columns=["COD_ID", "CTMT", "SUB", "TIP_CND", "SITCONT", "COMP"],
    )
    if "SITCONT" in segments:
        from src.grid_data_quality import operational_rows
        segments = operational_rows(segments, "SITCONT")
    if segments.empty:
        raise LookupError(f"Nenhum segmento MT encontrado em {radius_km:.1f} km.")

    zone = int((longitude + 180.0) // 6.0) + 1
    epsg = local_utm_epsg(latitude, longitude)
    point = gpd.GeoSeries([Point(longitude, latitude)], crs="EPSG:4674").to_crs(epsg).iloc[0]
    projected = segments.to_crs(epsg)
    distances = projected.geometry.distance(point)
    nearest_index = distances.idxmin()
    segments["distance_m"] = distances
    segments["is_nearest"] = segments.index == nearest_index

    transformers = pyogrio.read_dataframe(
        gdb, layer="UNTRMT", bbox=bbox,
        columns=["COD_ID", "CTMT", "POT_NOM", "SIT_ATIV"],
    )
    if "SIT_ATIV" in transformers:
        transformers = transformers.loc[
            transformers["SIT_ATIV"].astype(str).str.startswith("AT")
        ].copy()

    substations = _load_substations_window(
        gdb, bbox, latitude, longitude, radius_km, epsg
    )

    segments = segments.to_crs(4326)
    transformers = transformers.to_crs(4326)
    nearest = segments.loc[nearest_index]
    return {
        "segments_geojson": json.loads(segments.to_json()),
        "transformers_geojson": json.loads(transformers.to_json()),
        "substations_geojson": substations["geojson"],
        "substations": substations["records"],
        "substation_count": len(substations["records"]),
        "excluded_substation_count": substations["excluded_count"],
        "segment_count": int(len(segments)),
        "transformer_count": int(len(transformers)),
        "nearest_segment_id": str(nearest["COD_ID"]),
        "nearest_feeder_id": str(nearest["CTMT"]),
        "nearest_distance_m": float(nearest["distance_m"]),
    }


def _load_substations_window(gdb, bbox, latitude, longitude, radius_km, epsg) -> dict:
    """Carrega subestações padronizadas BDGD e agrega somente dados declarados.

    A camada SUB representa a área da subestação. O marcador usa um ponto
    representativo interno; distância e filtro são calculados contra a geometria
    real. UNTRAT fornece transformadores AT e CTMT os alimentadores associados.
    """
    import geopandas as gpd
    import pandas as pd
    import pyogrio
    from shapely.geometry import Point

    empty = {"type": "FeatureCollection", "features": []}
    try:
        substations = pyogrio.read_dataframe(
            gdb, layer="SUB", bbox=bbox,
            columns=["COD_ID", "NOME", "DESCR", "DIST", "POS"],
        )
    except Exception:
        return {"geojson": empty, "records": [], "excluded_count": 0}
    if substations.empty:
        return {"geojson": empty, "records": [], "excluded_count": 0}

    source_crs = substations.crs
    point = gpd.GeoSeries(
        [Point(longitude, latitude)], crs="EPSG:4674"
    ).to_crs(epsg).iloc[0]
    projected = substations.to_crs(epsg)
    distances = projected.geometry.distance(point)
    substations = substations.loc[distances <= radius_km * 1000.0].copy()
    if substations.empty:
        return {"geojson": empty, "records": [], "excluded_count": 0}
    substations["distance_m"] = distances.loc[substations.index].astype(float)
    ids = substations["COD_ID"].dropna().astype(str).unique().tolist()

    transformer_counts = {}
    transformer_power = {}
    feeder_counts = {}
    try:
        units = pyogrio.read_dataframe(
            gdb, layer="UNTRAT",
            columns=["COD_ID", "SUB", "POT_NOM", "SIT_ATIV"],
            read_geometry=False,
        )
        if "SIT_ATIV" in units:
            units = units.loc[units["SIT_ATIV"].astype(str).str.strip().eq("AT")]
        units = units.loc[units["SUB"].astype(str).isin(ids)].copy()
        units["POT_NOM"] = pd.to_numeric(units["POT_NOM"], errors="coerce")
        transformer_counts = units.groupby(units["SUB"].astype(str))["COD_ID"].nunique().to_dict()
        transformer_power = units.groupby(units["SUB"].astype(str))["POT_NOM"].sum(min_count=1).to_dict()
    except Exception:
        pass
    try:
        feeders = pyogrio.read_dataframe(
            gdb, layer="CTMT", columns=["COD_ID", "SUB"], read_geometry=False
        )
        feeders = feeders.loc[feeders["SUB"].astype(str).isin(ids)]
        feeder_counts = feeders.groupby(feeders["SUB"].astype(str))["COD_ID"].nunique().to_dict()
    except Exception:
        pass

    display = substations.to_crs(4326)
    display.geometry = display.geometry.representative_point()
    records = []
    for idx, row in display.iterrows():
        sid = str(row.get("COD_ID", ""))
        power = transformer_power.get(sid)
        power = float(power) if power is not None and pd.notna(power) else None
        record = {
            "substation_id": sid,
            "name": str(row.get("NOME", "") or "").strip(),
            "description": str(row.get("DESCR", "") or "").strip(),
            "ownership_code": str(row.get("POS", "") or "").strip(),
            "distance_m": float(row["distance_m"]),
            "latitude": float(row.geometry.y),
            "longitude": float(row.geometry.x),
            "transformer_count": int(transformer_counts.get(sid, 0)),
            "installed_power_mva": power,
            "feeder_count": int(feeder_counts.get(sid, 0)),
        }
        # Um vínculo CTMT comprova que a instalação alimenta a rede de
        # distribuição. Apenas nome, proximidade, polígono SUB ou UNTRAT não
        # bastam: consumidores AT e instalações particulares também podem
        # aparecer nessas camadas.
        if record["feeder_count"] > 0:
            records.append(record)
        for key, value in record.items():
            if key not in ("latitude", "longitude"):
                display.at[idx, key] = value
    records.sort(key=lambda item: item["distance_m"])
    included_ids = {item["substation_id"] for item in records}
    filtered_display = display.loc[display["COD_ID"].astype(str).isin(included_ids)].copy()
    excluded_count = int(len(display) - len(filtered_display))
    return {
        "geojson": json.loads(filtered_display.to_json()),
        "records": records,
        "excluded_count": excluded_count,
    }
