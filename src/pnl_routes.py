"""Consulta espacial sob demanda da rede logística PNL armazenada no Drive."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import pandas as pd

from src.grid_data_quality import local_utm_epsg


PNL_DATASET = {
    "name": "Rede logística consolidada — PNL",
    "folder_url": "https://drive.google.com/drive/folders/1wHZI7XQtxVI0QcB6MwCF4CbQf4mt5Wzh",
    "file_id": "1kl4ij_71nakwIEcuK5DyN_LTukYg8tsP",
    "archive_name": "shapefile_consolidado (3).7z",
    "gpkg_name": "shapefile_consolidado.gpkg",
    "layer": "shapefile_consolidado",
}

_QUARTERS = [f"sat_trimestre_{quarter}" for quarter in range(1, 5)]
_CORRIDORS = [
    "d_corredor_domestico",
    "d_corredor_exportacao",
    "d_corredor_integracao",
]


def _cache_root() -> Path:
    token = hashlib.sha256(PNL_DATASET["file_id"].encode()).hexdigest()[:16]
    root = Path(tempfile.gettempdir()) / "eletroposto_pnl_cloud" / token
    root.mkdir(parents=True, exist_ok=True)
    return root


def prepare_pnl_dataset() -> Path:
    """Baixa e extrai o GeoPackage uma vez por instância da aplicação."""
    root = _cache_root()
    gpkg = root / PNL_DATASET["gpkg_name"]
    if gpkg.exists() and gpkg.stat().st_size:
        return gpkg

    archive = root / PNL_DATASET["archive_name"]
    if not archive.exists() or not archive.stat().st_size:
        import gdown

        partial = archive.with_suffix(archive.suffix + ".part")
        result = gdown.download(
            id=PNL_DATASET["file_id"], output=str(partial),
            quiet=True, use_cookies=False,
        )
        if not result or not partial.exists() or not partial.stat().st_size:
            partial.unlink(missing_ok=True)
            raise ConnectionError("Não foi possível baixar a base PNL do Google Drive.")
        os.replace(partial, archive)

    try:
        import py7zr

        extraction = root / "extracting"
        extraction.mkdir(parents=True, exist_ok=True)
        with py7zr.SevenZipFile(archive, mode="r") as package:
            package.extract(path=extraction, targets=[PNL_DATASET["gpkg_name"]])
        extracted = extraction / PNL_DATASET["gpkg_name"]
        if not extracted.exists() or not extracted.stat().st_size:
            raise FileNotFoundError(PNL_DATASET["gpkg_name"])
        os.replace(extracted, gpkg)
    except Exception as error:
        gpkg.unlink(missing_ok=True)
        raise RuntimeError("O pacote PNL foi baixado, mas o GeoPackage não pôde ser extraído.") from error
    return gpkg


def corridor_label(row) -> str:
    labels = []
    if float(row.get("d_corredor_domestico", 0) or 0) == 1:
        labels.append("Doméstico")
    if float(row.get("d_corredor_exportacao", 0) or 0) == 1:
        labels.append("Exportação")
    if float(row.get("d_corredor_integracao", 0) or 0) == 1:
        labels.append("Integração")
    return " + ".join(labels) if labels else "Não classificado"


def saturation_class(value) -> str:
    if pd.isna(value):
        return "Não informada"
    value = float(value)
    if value >= 1.0:
        return "Crítica (≥100%)"
    if value >= 0.8:
        return "Alta (80–100%)"
    if value >= 0.6:
        return "Moderada (60–80%)"
    return "Baixa (<60%)"


def load_pnl_window(latitude: float, longitude: float, radius_km: float = 15.0,
                    max_map_features: int = 5000) -> dict:
    """Retorna rotas PNL no raio e indicadores do segmento mais próximo."""
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point

    latitude, longitude, radius_km = float(latitude), float(longitude), float(radius_km)
    delta_lat = radius_km / 111.0
    delta_lon = radius_km / max(111.0 * math.cos(math.radians(latitude)), 1e-6)
    bbox = (
        longitude - delta_lon, latitude - delta_lat,
        longitude + delta_lon, latitude + delta_lat,
    )
    columns = [
        "NO", "GTYPE", "LENGTH", "T_TOTAL", "T_TOTAL_SEM_GSM",
        *_QUARTERS, *_CORRIDORS,
    ]
    routes = pyogrio.read_dataframe(
        prepare_pnl_dataset(), layer=PNL_DATASET["layer"],
        bbox=bbox, columns=columns,
    )
    if routes.empty:
        raise LookupError(f"Nenhuma rota PNL encontrada em {radius_km:.0f} km.")
    routes = routes.to_crs(4326)
    epsg = local_utm_epsg(latitude, longitude)
    point = gpd.GeoSeries([Point(longitude, latitude)], crs=4326).to_crs(epsg).iloc[0]
    projected = routes.to_crs(epsg)
    distances = projected.geometry.distance(point)
    routes = routes.loc[distances <= radius_km * 1000].copy()
    if routes.empty:
        raise LookupError(f"Nenhuma rota PNL encontrada em {radius_km:.0f} km.")
    routes["distance_km"] = distances.loc[routes.index].astype(float) / 1000.0
    routes["max_saturation"] = routes[_QUARTERS].apply(pd.to_numeric, errors="coerce").max(axis=1)
    routes["corridor"] = routes.apply(corridor_label, axis=1)
    routes["saturation_label"] = routes["max_saturation"].map(saturation_class)
    routes["total_flow"] = pd.to_numeric(routes["T_TOTAL"], errors="coerce").fillna(0.0)
    nearest_index = routes["distance_km"].idxmin()
    nearest = routes.loc[nearest_index]

    # Prioriza corredores, fluxos e trechos próximos para manter o mapa leve.
    routes["corridor_priority"] = routes[_CORRIDORS].fillna(0).max(axis=1)
    map_routes = routes.sort_values(
        ["corridor_priority", "total_flow", "distance_km"],
        ascending=[False, False, True],
    ).head(int(max_map_features)).copy()
    projected_map = map_routes.to_crs(epsg)
    projected_map.geometry = projected_map.geometry.simplify(8.0, preserve_topology=True)
    map_routes = projected_map.to_crs(4326)
    map_routes["max_saturation_pct"] = (map_routes["max_saturation"] * 100).round(1)
    map_routes["T_TOTAL_display"] = map_routes["total_flow"].map(lambda x: f"{x:,.0f}")

    max_saturation = routes["max_saturation"]
    corridor_mask = routes[_CORRIDORS].fillna(0).max(axis=1).eq(1)
    return {
        "geojson": json.loads(map_routes.to_json()),
        "segment_count": int(len(routes)),
        "displayed_segment_count": int(len(map_routes)),
        "nearest": {
            "segment_id": str(nearest["NO"]),
            "gtype": int(nearest["GTYPE"]),
            "distance_km": float(nearest["distance_km"]),
            "length": str(nearest["LENGTH"]),
            "total_flow": float(nearest["total_flow"]),
            "max_saturation": None if pd.isna(nearest["max_saturation"]) else float(nearest["max_saturation"]),
            "saturation_label": str(nearest["saturation_label"]),
            "corridor": str(nearest["corridor"]),
        },
        "corridor_segment_count": int(corridor_mask.sum()),
        "high_saturation_count": int((max_saturation >= 0.8).sum()),
        "critical_saturation_count": int((max_saturation >= 1.0).sum()),
        "radius_km": radius_km,
        "source": PNL_DATASET,
        "interpretation_warning": (
            "T_TOTAL e GTYPE são mantidos como atributos PNL. Sem o dicionário e as unidades "
            "do estudo, não são convertidos em veículos, energia ou potência de recarga."
        ),
    }


def add_pnl_layer(map_view, data: dict, display_mode: str = "Saturação"):
    """Adiciona ao mapa uma camada leve e interpretável das rotas PNL."""
    import folium

    def style(feature):
        props = feature.get("properties", {})
        saturation = props.get("max_saturation")
        total = float(props.get("total_flow") or 0.0)
        corridor = str(props.get("corridor") or "")
        if display_mode == "Corredores":
            color = (
                "#7c3aed" if "Integração" in corridor else
                "#0f766e" if "Exportação" in corridor else
                "#2563eb" if "Doméstico" in corridor else "#94a3b8"
            )
            weight = 4 if corridor != "Não classificado" else 1.2
        elif display_mode == "Fluxo total":
            color = "#7c3aed"
            weight = min(7.0, 1.0 + math.log10(max(total, 1.0)) * 0.7)
        else:
            if saturation is None:
                color = "#94a3b8"
            elif float(saturation) >= 1.0:
                color = "#dc2626"
            elif float(saturation) >= 0.8:
                color = "#f97316"
            elif float(saturation) >= 0.6:
                color = "#eab308"
            else:
                color = "#16a34a"
            weight = 3.4 if saturation is not None and float(saturation) >= 0.8 else 2.0
        return {"color": color, "weight": weight, "opacity": 0.82}

    fields = ["NO", "GTYPE", "LENGTH", "T_TOTAL_display", "max_saturation_pct", "corridor"]
    aliases = ["Segmento PNL", "Tipo GTYPE", "Comprimento", "Fluxo total PNL", "Saturação máxima (%)", "Corredor"]
    folium.GeoJson(
        data["geojson"], name=f"Rotas PNL — {display_mode}",
        style_function=style,
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, localize=True),
        highlight_function=lambda _: {"weight": 6, "opacity": 1.0},
    ).add_to(map_view)
