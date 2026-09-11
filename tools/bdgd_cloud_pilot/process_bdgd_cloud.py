#!/usr/bin/env python3
"""Converte uma BDGD GDB/ZIP em um conjunto Parquet consultavel por partes.

O pacote gerado preserva a fonte e cria: manifesto auditavel, camadas globais,
particoes por alimentador e um indice espacial leve dos alimentadores. O ZIP
original e somente lido; nunca e alterado.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyogrio

GLOBAL_LAYERS = ("ARAT", "SUB", "UNTRAT", "SEGCON", "EQRE", "CRVCRG", "CTMT")
FEEDER_LAYERS = (
    "SSDMT", "UNTRMT", "UNREMT", "UNSEMT", "UNCRMT",
    "UCMT_tab", "UCBT_tab", "UCAT_tab", "PIP", "UGMT_tab", "UGBT_tab",
)
FEEDER_COLUMNS = ("CTMT", "COD_ID")
CHUNK_ROWS = 100_000


def _source_for_gdal(path: Path) -> str:
    if path.is_dir() and path.suffix.lower() == ".gdb":
        return str(path)
    if path.is_file() and path.name.lower().endswith((".zip", ".gdb.zip")):
        return "/vsizip/" + str(path.resolve())
    raise ValueError("A fonte deve ser um diretorio .gdb ou um arquivo .gdb.zip")


def _safe(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return text[:180] or "SEM_CODIGO"


def _sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_parquet(frame, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(frame, "geometry") and frame.geometry.name in frame.columns:
        frame.to_parquet(target, compression="zstd", index=False)
    else:
        pd.DataFrame(frame).to_parquet(target, compression="zstd", index=False)
    return {"path": str(target), "rows": int(len(frame)), "bytes": target.stat().st_size}


def _feeder_column(columns: list[str]) -> str | None:
    upper = {str(c).upper(): str(c) for c in columns}
    for name in FEEDER_COLUMNS:
        if name in upper:
            return upper[name]
    return None


def process(source: Path, output_root: Path, distributor: str, reference_date: str) -> Path:
    source = source.resolve()
    output = output_root.resolve() / _safe(distributor) / reference_date
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Destino nao vazio: {output}")
    output.mkdir(parents=True, exist_ok=True)
    gdal_source = _source_for_gdal(source)
    available = {str(name) for name, _ in pyogrio.list_layers(gdal_source)}
    manifest = {
        "schema": "bdgd-cloud-pilot-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "distributor": distributor,
        "reference_date": reference_date,
        "source_name": source.name,
        "source_bytes": source.stat().st_size if source.is_file() else None,
        "source_sha256": _sha256(source),
        "crs_output": "EPSG:4674",
        "layers": {},
        "warnings": [],
    }

    # Camadas pequenas/relacionais compartilhadas por varios alimentadores.
    for layer in GLOBAL_LAYERS:
        if layer not in available:
            manifest["warnings"].append(f"Camada ausente: {layer}")
            continue
        frame = pyogrio.read_dataframe(gdal_source, layer=layer)
        if hasattr(frame, "geometry") and frame.geometry.name in frame.columns and frame.crs:
            frame = frame.to_crs(4674)
        manifest["layers"][layer] = {
            "mode": "global",
            **_write_parquet(frame, output / "global" / f"{layer}.parquet"),
        }

    feeder_bounds: dict[str, list[float | int]] = {}
    for layer in FEEDER_LAYERS:
        if layer not in available:
            manifest["warnings"].append(f"Camada ausente: {layer}")
            continue
        info = pyogrio.read_info(gdal_source, layer=layer)
        columns = list(info.get("fields", []))
        feeder_col = _feeder_column(columns)
        if not feeder_col:
            manifest["warnings"].append(f"Camada sem chave de alimentador: {layer}")
            continue
        feature_count = int(info.get("features") or 0)
        layer_rows = layer_bytes = file_count = 0
        feeder_keys: set[str] = set()
        for chunk_no, offset in enumerate(range(0, feature_count, CHUNK_ROWS)):
            frame = pyogrio.read_dataframe(
                gdal_source, layer=layer, skip_features=offset,
                max_features=CHUNK_ROWS,
            )
            if frame.empty:
                continue
            if hasattr(frame, "geometry") and frame.geometry.name in frame.columns and frame.crs:
                frame = frame.to_crs(4674)
            normalized = frame[feeder_col].fillna("").astype(str).str.strip()
            frame = frame.loc[normalized.ne("")].copy()
            frame[feeder_col] = normalized.loc[frame.index]
            for feeder, group in frame.groupby(feeder_col, sort=False):
                feeder = str(feeder)
                feeder_keys.add(feeder)
                record = _write_parquet(
                    group, output / "feeders" / _safe(feeder) /
                    layer / f"part-{chunk_no:05d}.parquet"
                )
                layer_rows += record["rows"]
                layer_bytes += record["bytes"]
                file_count += 1
                if layer == "SSDMT" and hasattr(group, "total_bounds"):
                    minx, miny, maxx, maxy = map(float, group.total_bounds)
                    old = feeder_bounds.get(feeder)
                    if old is None:
                        feeder_bounds[feeder] = [minx, miny, maxx, maxy, len(group)]
                    else:
                        old[0] = min(old[0], minx); old[1] = min(old[1], miny)
                        old[2] = max(old[2], maxx); old[3] = max(old[3], maxy)
                        old[4] += len(group)
        manifest["layers"][layer] = {
            "mode": "by_feeder", "feeders": len(feeder_keys),
            "rows": layer_rows, "bytes": layer_bytes, "files": file_count,
        }

    feeder_index = [
        {"feeder_id": key, "min_lon": val[0], "min_lat": val[1],
         "max_lon": val[2], "max_lat": val[3], "segment_rows": val[4]}
        for key, val in feeder_bounds.items()
    ]
    index_frame = pd.DataFrame(feeder_index)
    if not index_frame.empty:
        index_record = _write_parquet(index_frame, output / "indexes" / "feeders.parquet")
        manifest["feeder_index"] = index_record
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--distributor", required=True)
    parser.add_argument("--reference-date", default="2025-12-31")
    args = parser.parse_args()
    print(process(args.source, args.output, args.distributor, args.reference_date))


if __name__ == "__main__":
    main()
