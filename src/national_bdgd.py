"""Catálogo nacional oficial ArcGIS/ANEEL e instalação sob demanda da BDGD.

Não é um serviço nacional de capacidade disponível: cada distribuidora/data
é uma base independente, sujeita às validações e limitações do modelo local.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://www.arcgis.com/sharing/rest"
ANEEL_ORG = "J5unWNi0P2dwjI3y"
TITLE = re.compile(r"^(.+)_(\d+)_(\d{4}-\d{2}-\d{2})_([^_]+)_(\d{8}-\d{4})$")


def api_json(path, params=None):
    response = requests.get(API + path, params={"f": "json", **(params or {})},
                            headers={"User-Agent": "EletropostoResearch/1.0"}, timeout=(10, 40))
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError("ANEEL/ArcGIS: " + str(data["error"].get("message", "erro de consulta")))
    return data


def latest_by_distributor(items):
    latest = {}
    for item in items:
        match = TITLE.fullmatch(item.get("title", ""))
        if not match or item.get("type") != "File Geodatabase":
            continue
        name, distributor, date, version, revision = match.groups()
        record = dict(item, distributor_id=distributor, distributor_name=name.replace("_", " "),
                      reference_date=date, schema_version=version, revision=revision)
        rank = (date, revision, int(item.get("modified", 0)))
        old = latest.get(distributor)
        if old is None or rank > (old["reference_date"], old["revision"], int(old.get("modified", 0))):
            latest[distributor] = record
    return sorted(latest.values(), key=lambda item: item["distributor_name"].casefold())


def fetch_catalog():
    items, start, seen = [], 1, set()
    while start != -1:
        if start in seen or len(seen) >= 100:
            raise RuntimeError("Paginação inconsistente no catálogo ANEEL; catálogo não atualizado.")
        seen.add(start)
        data = api_json("/search", {"q": f'orgid:{ANEEL_ORG} type:"File Geodatabase" tags:distribuicao',
                                    "num": 100, "start": start, "sortField": "title", "sortOrder": "asc"})
        items.extend(data.get("results", []))
        start = int(data.get("nextStart", -1))
    if len(items) != int(data.get("total", len(items))):
        raise RuntimeError("O catálogo mudou durante a paginação; tente atualizar novamente.")
    latest = latest_by_distributor(items)
    if not latest:
        raise RuntimeError("Nenhuma BDGD reconhecida no catálogo oficial.")
    return {"retrieved_at": datetime.now(timezone.utc).isoformat(), "source": API,
            "item_count": len(items), "distributor_count": len(latest), "items": latest}


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


def validate_item_id(item_id):
    if not re.fullmatch(r"[a-f0-9]{32}", str(item_id)):
        raise ValueError("Identificador ArcGIS inválido.")


def install_dataset(item_id, directory, progress=None, max_bytes=6_000_000_000):
    """Baixa somente após ação explícita. Nunca sobrescreve a base CPFL original."""
    validate_item_id(item_id)
    item = api_json(f"/content/items/{item_id}")
    if item.get("orgId") != ANEEL_ORG or item.get("type") != "File Geodatabase":
        raise ValueError("O item não é uma geodatabase da organização oficial ANEEL.")
    size = int(item.get("size", 0))
    if not 0 < size <= max_bytes:
        raise ValueError("Tamanho ausente ou acima do limite de segurança de 6 GB por arquivo.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{item_id}.gdb.zip"
    metadata_path = directory / f"{item_id}.json"
    if target.exists() and metadata_path.exists():
        old = json.loads(metadata_path.read_text(encoding="utf-8"))
        if old.get("modified") == item.get("modified") and target.stat().st_size == old.get("downloaded_bytes"):
            return target, old
        raise ValueError("Item já instalado mudou no portal. Preserve a versão local e instale a atualização em outra pasta.")
    if shutil.disk_usage(directory).free < size * 4 + 1_000_000_000:
        raise OSError("Espaço livre insuficiente para download e extração com margem de segurança.")
    digest, count = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
        temporary = Path(output.name)
        try:
            with requests.get(API + f"/content/items/{item_id}/data", stream=True,
                              headers={"User-Agent": "EletropostoResearch/1.0"}, timeout=(15, 60)) as response:
                response.raise_for_status()
                for block in response.iter_content(1024 * 1024):
                    count += len(block)
                    if count > max_bytes:
                        raise ValueError("Download excedeu o limite permitido.")
                    output.write(block)
                    digest.update(block)
                    if progress:
                        progress(min(count / size, 0.99))
            output.flush()
            if count != size:
                raise ValueError("Download incompleto ou tamanho diferente do catálogo; arquivo não instalado.")
            with zipfile.ZipFile(temporary) as archive:
                entries = archive.infolist()
                if not any(".gdb/" in member.filename.lower() for member in entries):
                    raise ValueError("O arquivo recebido não contém uma geodatabase.")
                for member in entries:
                    if member.filename.startswith(("/", "\\")) or ".." in Path(member.filename.replace("\\", "/")).parts:
                        raise ValueError("Caminho inseguro no arquivo ZIP.")
                if sum(member.file_size for member in entries) > shutil.disk_usage(directory).free - 500_000_000:
                    raise OSError("Não há espaço para extrair a base baixada.")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
    metadata = dict(item, sha256=digest.hexdigest(), downloaded_bytes=count,
                    downloaded_at=datetime.now(timezone.utc).isoformat(), local_path=str(target))
    atomic_json(metadata_path, metadata)
    if progress:
        progress(1.0)
    return target, metadata


def installed_datasets(directory):
    result = []
    for path in sorted(Path(directory).glob("*.json")):
        if not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            zip_path = Path(directory) / f"{path.stem}.gdb.zip"
            if zip_path.exists():
                result.append((str(zip_path), item.get("title", path.stem)))
        except (ValueError, OSError):
            continue
    return result
