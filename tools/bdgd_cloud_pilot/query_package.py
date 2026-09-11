#!/usr/bin/env python3
"""Consulta local de um pacote BDGD tratado; base para o adaptador remoto."""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def candidate_feeders(root: Path, latitude: float, longitude: float) -> list[str]:
    frame = pd.read_parquet(root / "indexes" / "feeders.parquet")
    rows = frame.loc[
        frame["min_lon"].le(longitude) & frame["max_lon"].ge(longitude)
        & frame["min_lat"].le(latitude) & frame["max_lat"].ge(latitude)
    ]
    return rows["feeder_id"].astype(str).tolist()


def read_feeder_layer(root: Path, feeder_id: str, layer: str) -> gpd.GeoDataFrame:
    bundle = root / "feeders" / f"{feeder_id}.zip"
    frames = []
    with zipfile.ZipFile(bundle) as archive:
        members = [n for n in archive.namelist() if n.startswith(layer + "/") and n.endswith(".parquet")]
        for member in members:
            frames.append(gpd.read_parquet(io.BytesIO(archive.read(member))))
    if not frames:
        return gpd.GeoDataFrame()
    return pd.concat(frames, ignore_index=True)


def nearest_feeder(root: Path, latitude: float, longitude: float) -> dict:
    candidates = candidate_feeders(root, latitude, longitude)
    if not candidates:
        raise LookupError("Nenhum alimentador candidato cobre a coordenada pelo indice espacial.")
    epsg = (31978 if longitude < -48 else 31983)  # substituido abaixo pela zona UTM real
    zone = int((longitude + 180.0) // 6.0) + 1
    epsg = (31960 + zone) if latitude < 0 else (31954 + zone)
    point = gpd.GeoSeries([Point(longitude, latitude)], crs=4674).to_crs(epsg).iloc[0]
    best = None
    for feeder in candidates:
        segments = read_feeder_layer(root, feeder, "SSDMT")
        if segments.empty:
            continue
        distance = float(segments.to_crs(epsg).geometry.distance(point).min())
        if best is None or distance < best["distance_m"]:
            best = {"feeder_id": feeder, "distance_m": distance,
                    "candidate_count": len(candidates), "bundle": f"feeders/{feeder}.zip"}
    if best is None:
        raise LookupError("Pacotes candidatos nao continham segmentos SSDMT.")
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("latitude", type=float)
    parser.add_argument("longitude", type=float)
    args = parser.parse_args()
    print(json.dumps(nearest_feeder(args.root, args.latitude, args.longitude), indent=2))


if __name__ == "__main__":
    main()
