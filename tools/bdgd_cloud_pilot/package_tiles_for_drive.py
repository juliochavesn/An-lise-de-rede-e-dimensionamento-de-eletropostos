#!/usr/bin/env python3
"""Agrupa pacotes de alimentadores em blocos geograficos adequados ao Drive."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def safe_name(value: object) -> str:
    import re
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return text[:180] or "SEM_CODIGO"


def tile_name(lat: float, lon: float, resolution: float) -> str:
    y = math.floor(lat / resolution) * resolution
    x = math.floor(lon / resolution) * resolution
    return f"tile_{y:+06.2f}_{x:+07.2f}.zip".replace("+", "P").replace("-", "M")


def package(source: Path, destination: Path, resolution: float = 1.0) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Destino nao vazio: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("global", "indexes"):
        shutil.copytree(source / name, destination / name)
    index = pd.read_parquet(source / "indexes" / "feeders.parquet")
    index["center_lat"] = (index.min_lat + index.max_lat) / 2
    index["center_lon"] = (index.min_lon + index.max_lon) / 2
    index["tile"] = [tile_name(a, b, resolution) for a, b in zip(index.center_lat, index.center_lon)]
    tiles = destination / "tiles"
    tiles.mkdir()
    feeder_to_tile = {}
    for tile, group in index.groupby("tile"):
        target = tiles / tile
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for feeder in group.feeder_id.astype(str):
                safe = safe_name(feeder)
                bundle = source / "feeders" / f"{safe}.zip"
                if bundle.exists():
                    archive.write(bundle, f"feeders/{safe}.zip")
                    feeder_to_tile[feeder] = tile
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "package_schema": "bdgd-drive-geographic-tiles-v1",
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "tile_resolution_degrees": resolution,
        "tile_count": len(list(tiles.glob("*.zip"))),
        "feeder_to_tile": feeder_to_tile,
    })
    output = destination / "manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--resolution", type=float, default=1.0)
    args = parser.parse_args()
    print(package(args.source, args.destination, args.resolution))


if __name__ == "__main__":
    main()
