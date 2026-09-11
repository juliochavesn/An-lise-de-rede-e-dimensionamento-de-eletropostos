"""Consulta sob demanda das bases BDGD previamente tratadas no Google Drive."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.grid_data_quality import local_utm_epsg, operational_rows


CLOUD_DATASETS = {
    "CPFL Paulista — BDGD 2025 em nuvem": {
        "folder_url": "https://drive.google.com/drive/folders/1lqjA_v-pFWYtms8Bscp8TnWEH2-dXqJs",
        "distributor": "CPFL Paulista",
        "reference_date": "2025-12-31",
    },
    "Enel SP — BDGD 2025 em nuvem": {
        "folder_url": "https://drive.google.com/drive/folders/1Mnq1pob0y8UKH2UkMIrlvCzAPHNKqdzT",
        "distributor": "Enel SP",
        "reference_date": "2025-12-31",
    },
}

_ENERGY_COLUMNS = [f"ENE_{month:02d}" for month in range(1, 13)]
_EMPTY_LAYER_COLUMNS = {
    "UNREMT": ["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV", "FAS_CON", "TIP_REGU"],
    "UNTRMT": ["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV", "POT_NOM"],
    "UNSEMT": ["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV", "P_N_OPE", "TIP_UNID", "COR_NOM"],
    "UNCRMT": ["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV"],
    "UCBT_tab": ["CTMT", "TIP_CC", "SIT_ATIV", *_ENERGY_COLUMNS],
    "UCMT_tab": ["CTMT", "TIP_CC", "SIT_ATIV", *_ENERGY_COLUMNS],
    "UGBT_tab": ["CTMT", "SIT_ATIV", *_ENERGY_COLUMNS],
    "UGMT_tab": ["CTMT", "SIT_ATIV", *_ENERGY_COLUMNS],
    "UCAT_tab": ["CTMT", "SIT_ATIV", *_ENERGY_COLUMNS],
    "PIP": ["COD_ID", "CTMT", "SIT_ATIV"],
}


def _cache_root(dataset: dict) -> Path:
    token = hashlib.sha256(dataset["folder_url"].encode()).hexdigest()[:16]
    root = Path(tempfile.gettempdir()) / "eletroposto_bdgd_cloud" / token
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remote_files(dataset: dict) -> dict[str, str]:
    """Lista o pacote compacto no Drive sem baixar seu conteúdo."""
    import gdown

    root = _cache_root(dataset)
    cached = root / "drive_files.json"
    if cached.exists() and (pd.Timestamp.now().timestamp() - cached.stat().st_mtime) < 3600:
        mapping = json.loads(cached.read_text(encoding="utf-8"))
        if "global/ARAT.parquet" in mapping and "indexes/feeders.parquet" in mapping:
            return mapping
    files = gdown.download_folder(
        url=dataset["folder_url"], output=str(root / "listing"), quiet=True,
        use_cookies=False, remaining_ok=True, skip_download=True,
    )
    if not files:
        raise ConnectionError("O Google Drive não retornou os arquivos do pacote BDGD.")
    mapping = {}
    for item in files:
        remote_path = str(item.path).replace("\\", "/")
        marker = "2025-12-31/"
        relative = remote_path.split(marker, 1)[-1] if marker in remote_path else remote_path
        mapping[relative] = item.id
    cached.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapping


def _download(dataset: dict, relative: str) -> Path:
    import gdown

    root = _cache_root(dataset)
    target = root / "files" / relative
    if target.exists() and target.stat().st_size:
        return target
    file_id = _remote_files(dataset).get(relative)
    if not file_id:
        raise FileNotFoundError(f"Arquivo {relative} não localizado no pacote em nuvem.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    result = gdown.download(id=file_id, output=str(temporary), quiet=True, use_cookies=False)
    if not result or not temporary.exists() or not temporary.stat().st_size:
        temporary.unlink(missing_ok=True)
        raise ConnectionError(f"Falha ao baixar {relative} do Google Drive.")
    os.replace(temporary, target)
    return target


def _read_parquet_bytes(data: bytes):
    stream = io.BytesIO(data)
    try:
        return gpd.read_parquet(stream)
    except (ValueError, TypeError):
        stream.seek(0)
        return pd.read_parquet(stream)


def load_cloud_coverage(dataset: dict) -> dict:
    frame = gpd.read_parquet(_download(dataset, "global/ARAT.parquet"))
    if frame.crs is None:
        frame = frame.set_crs(4674)
    else:
        frame = frame.to_crs(4674)
    geometry = frame.geometry.union_all() if hasattr(frame.geometry, "union_all") else frame.geometry.unary_union
    minx, miny, maxx, maxy = geometry.bounds
    return {
        "geometry": geometry,
        "bounds": [[miny, minx], [maxy, maxx]],
        "geojson": json.loads(gpd.GeoSeries([geometry], crs=4674).to_json()),
        "layer": "ARAT",
    }


def _candidate_feeders(index: pd.DataFrame, latitude: float, longitude: float, radius_km: float) -> list[str]:
    dlat = radius_km / 111.0
    dlon = radius_km / max(111.0 * abs(__import__("math").cos(__import__("math").radians(latitude))), 1e-6)
    hit = index[
        (index.max_lon >= longitude - dlon) & (index.min_lon <= longitude + dlon)
        & (index.max_lat >= latitude - dlat) & (index.min_lat <= latitude + dlat)
    ]
    return hit.sort_values("segment_rows", ascending=False).feeder_id.astype(str).tolist()


def _inner_bundle(tile_path: Path, feeder_id: str) -> bytes | None:
    wanted = f"feeders/{feeder_id}.zip"
    with zipfile.ZipFile(tile_path) as archive:
        try:
            return archive.read(wanted)
        except KeyError:
            return None


def _bundle_layers(bundle: bytes, only: set[str] | None = None) -> dict[str, pd.DataFrame]:
    groups: dict[str, list[pd.DataFrame]] = {}
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        for name in archive.namelist():
            if not name.endswith(".parquet") or "/" not in name:
                continue
            layer = name.split("/", 1)[0]
            if only is not None and layer not in only:
                continue
            groups.setdefault(layer, []).append(_read_parquet_bytes(archive.read(name)))
    result = {}
    for layer, parts in groups.items():
        combined = pd.concat(parts, ignore_index=True)
        if parts and isinstance(parts[0], gpd.GeoDataFrame):
            combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=parts[0].crs)
        result[layer] = combined
    return result


def _combine_frames(frames: list[pd.DataFrame]):
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    if isinstance(frames[0], gpd.GeoDataFrame):
        combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=frames[0].crs)
    return combined


def prepare_cloud_point(dataset: dict, latitude: float, longitude: float,
                        max_radius_km: float = 10.0, context_radius_km: float = 1.5) -> dict:
    """Monta recorte: alimentador completo para cálculo e ativos vizinhos para o mapa."""
    manifest = json.loads(_download(dataset, "manifest.json").read_text(encoding="utf-8"))
    index = pd.read_parquet(_download(dataset, "indexes/feeders.parquet"))
    candidates = _candidate_feeders(index, latitude, longitude, max_radius_km)
    context_candidates = set(_candidate_feeders(index, latitude, longitude, context_radius_km))
    if not candidates:
        raise LookupError(f"Nenhum alimentador indexado em até {max_radius_km:.1f} km do ponto.")

    point = gpd.GeoSeries.from_xy([longitude], [latitude], crs=4674).to_crs(local_utm_epsg(latitude, longitude)).iloc[0]
    nearest = None
    tile_cache = {}
    bundle_cache = {}
    context_layers: dict[str, list[pd.DataFrame]] = {"SSDMT": [], "UNTRMT": []}
    for feeder_id in candidates:
        tile_name = manifest["feeder_to_tile"].get(feeder_id)
        if not tile_name:
            continue
        tile_path = tile_cache.setdefault(tile_name, _download(dataset, f"tiles/{tile_name}"))
        bundle = _inner_bundle(tile_path, feeder_id)
        if not bundle:
            continue
        bundle_cache[feeder_id] = bundle
        layers = _bundle_layers(bundle, {"SSDMT", "UNTRMT"})
        segments = layers.get("SSDMT")
        if segments is None or segments.empty:
            continue
        operational_segments = operational_rows(segments, "SITCONT")
        if operational_segments.empty:
            continue
        if operational_segments.crs is None:
            operational_segments = operational_segments.set_crs(4674)
        distance = float(operational_segments.to_crs(
            local_utm_epsg(latitude, longitude)
        ).geometry.distance(point).min())
        if nearest is None or distance < nearest[0]:
            nearest = (distance, feeder_id, tile_name)
        if feeder_id in context_candidates:
            for layer in context_layers:
                frame = layers.get(layer)
                if frame is not None and not frame.empty:
                    context_layers[layer].append(frame)
    if nearest is None or nearest[0] > max_radius_km * 1000:
        raise LookupError(f"Nenhum trecho operacional encontrado em até {max_radius_km:.1f} km do ponto.")

    distance_m, feeder_id, tile_name = nearest
    feeder_layers = _bundle_layers(bundle_cache[feeder_id])
    # As camadas pesadas de consumidores e geração permanecem apenas para o
    # alimentador calculado. O mapa recebe trechos e transformadores de todos
    # os alimentadores cujo envelope cruza o raio solicitado.
    for layer, frames in context_layers.items():
        combined = _combine_frames(frames)
        if combined is not None:
            feeder_layers[layer] = combined
    root = _cache_root(dataset)
    key_source = (
        f"v3|{latitude:.7f}|{longitude:.7f}|{context_radius_km:.2f}|"
        f"{feeder_id}|{manifest.get('source_sha256')}"
    )
    key = hashlib.sha256(key_source.encode()).hexdigest()[:16]
    gpkg = root / "points" / f"{feeder_id}_{key}.gpkg"
    if not gpkg.exists():
        import pyogrio

        gpkg.parent.mkdir(parents=True, exist_ok=True)
        temporary = gpkg.with_suffix(".building.gpkg")
        temporary.unlink(missing_ok=True)
        layers = {}
        for name, info in manifest.get("layers", {}).items():
            if info.get("mode") == "global":
                path = _download(dataset, f"global/{name}.parquet")
                try:
                    layers[name] = gpd.read_parquet(path)
                except (ValueError, TypeError):
                    layers[name] = pd.read_parquet(path)
        layers.update(feeder_layers)
        for layer, columns in _EMPTY_LAYER_COLUMNS.items():
            layers.setdefault(layer, pd.DataFrame(columns=columns))
        for layer, frame in layers.items():
            if frame is None:
                continue
            pyogrio.write_dataframe(frame, temporary, layer=layer, driver="GPKG", append=temporary.exists())
        os.replace(temporary, gpkg)
    return {
        "bdgd_path": str(gpkg), "feeder_id": feeder_id, "distance_m": distance_m,
        "tile": tile_name, "distributor": dataset["distributor"],
        "reference_date": manifest.get("reference_date", dataset["reference_date"]),
        "context_radius_km": context_radius_km,
        "context_feeder_count": len(context_candidates),
    }
