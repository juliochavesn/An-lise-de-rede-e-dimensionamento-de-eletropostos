#!/usr/bin/env python3
"""Empacota o resultado por alimentador para armazenamento no Google Drive."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def package(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Destino nao vazio: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("global", "indexes"):
        shutil.copytree(source / name, destination / name)
    bundles = destination / "feeders"
    bundles.mkdir()
    records = []
    for feeder in sorted((source / "feeders").iterdir()):
        if not feeder.is_dir():
            continue
        target = bundles / f"{feeder.name}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for item in sorted(feeder.rglob("*.parquet")):
                archive.write(item, item.relative_to(feeder))
        records.append({"feeder_id": feeder.name, "file": target.name,
                        "bytes": target.stat().st_size})
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        **source_manifest,
        "package_schema": "bdgd-drive-feeder-bundles-v1",
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "feeder_bundle_count": len(records),
        "feeder_bundles": records,
    }
    output = destination / "manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(package(args.source, args.destination))


if __name__ == "__main__":
    main()
