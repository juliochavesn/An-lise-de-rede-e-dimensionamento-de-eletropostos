"""Triagem online independente da BDGD local; nunca estima capacidade a partir de UCs.

O DataStore ANEEL não habilita SQL. Usamos busca textual por células decimais
de coordenadas, paginação limitada e recorte geodésico final. O universo é PJ,
não todos os consumidores nem a topologia nacional da rede.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Geod

from .national_bdgd import atomic_json
from .online_characterization import enrich, reference_date

CKAN = "https://dadosabertos.aneel.gov.br/api/3/action/"
PACKAGE = "base-de-dados-geografica-da-distribuidora-bdgd"
PACKAGE_URL = "https://dadosabertos.aneel.gov.br/dataset/" + PACKAGE
SIGEL = "https://sigel.aneel.gov.br/server/rest/services/Dados_Abertos/AME_2023/FeatureServer"
GEOD = Geod(ellps="WGS84")
VERSION = 2
FIELDS = ["DIST", "SUB", "CONJ", "MUN", "POINT_X", "POINT_Y", "SIT_ATIV",
          "GRU_TAR", "TEN_FORN", "DEM_CONT", "DATA_BASE", "CTMT", "CTAT", "CAR_INST", "FAS_CON"]
FIELDS += [f"{prefix}_{month:02d}" for prefix in ("ENE", "DEM", "ENE_P", "ENE_F", "DEM_P", "DEM_F", "DIC", "FIC") for month in range(1, 13)]
LIMITATIONS = [
    "Capacidade disponível/residual não determinada. Não é zero e não é ilimitada.",
    "UCMT/UCAT representam consumidores PJ cadastrados, não trechos de rede nem toda a carga do alimentador.",
    "Proximidade não comprova conexão elétrica, área de concessão ou viabilidade de acesso. Alimentadores/subestações são candidatos.",
    "Datas-base podem diferir. Identificadores só podem ser cruzados com distribuidora e referência compatíveis.",
    "Não há curva residual de 24 h, recomendação de horário de recarga ou dimensionamento de reforço com estes dados isolados.",
    "Consumos são da amostra retornada. Maior demanda individual não é pico simultâneo; DIC/FIC individuais não são DEC/FEC do conjunto.",
    "Tarifas e continuidade usam conjuntos/CNPJs candidatos, sem homologar o vínculo DIST–CNPJ nem a conexão na coordenada. Tarifas configuradas não são alteradas.",
    "Para aprofundar: BDGD completa, topologia/caminho, condutores, transformadores, cargas e curvas. Disponibilidade final requer a distribuidora.",
]


def now():
    return datetime.now(timezone.utc).isoformat()


class PublicClient:
    """Cache pequeno de consultas, nunca download implícito de geodatabases."""
    def __init__(self, cache_dir=None, refresh=False):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.refresh = refresh

    def get(self, url, params, ttl=21600):
        key = hashlib.sha256(json.dumps([VERSION, url, params], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / (key + ".json") if self.cache_dir else None
        if path and path.exists() and not self.refresh:
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["retrieved_at"])).total_seconds()
                if 0 <= age < ttl:
                    return cached["data"], dict(cached["provenance"], cached=True)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        response = requests.get(url, params=params, headers={"User-Agent": "EletropostoResearch/1.0"}, timeout=(8, 25))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is False or "error" in data:
            raise RuntimeError("A API recusou a consulta ou retornou erro; não equivale a ausência de dados.")
        provenance = {"url": url, "parameters": params, "retrieved_at": now(), "cached": False}
        if path:
            atomic_json(path, {"retrieved_at": provenance["retrieved_at"], "provenance": provenance, "data": data})
        return data, provenance

    def action(self, name, params, ttl=21600):
        data, source = self.get(CKAN + name, params, ttl)
        if not isinstance(data.get("result"), dict):
            raise ValueError("Resposta CKAN sem resultado válido.")
        return data["result"], source


def validate_point(lat, lon, radius):
    if not all(math.isfinite(v) for v in (lat, lon, radius)) or not (-34 <= lat <= 6 and -74 <= lon <= -34 and 0.5 <= radius <= 5):
        raise ValueError("Informe coordenada no enquadramento brasileiro e raio entre 0,5 e 5 km.")


def envelope(lat, lon, radius):
    # Conservative angular envelope; exact ellipsoidal distance is checked later.
    dy = radius / 110.0
    dx = radius / (110.0 * math.cos(math.radians(abs(lat) + dy)))
    return lon - dx, lat - dy, lon + dx, lat + dy


def coordinate_query(low, high):
    """Prefix OR covering 0.1-degree cells, including sign/degree boundaries."""
    terms = set()
    for cell in range(math.floor(low * 10), math.floor(high * 10) + 1):
        mid = (cell + 0.5) / 10
        prefix = ("-" if mid < 0 else "") + f"{math.floor(abs(mid) * 10) / 10:.1f}"
        terms.add(f"'{prefix}':*")
        # Coordinates exactly at an integer may be serialized without decimals.
        if prefix.endswith(".0"):
            terms.add(f"'{prefix[:-2]}'")
    return " | ".join(sorted(terms))


def number(value):
    try:
        value = float(str(value).strip().replace(",", "."))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def nearby_consumers(client, resource, kind, lat, lon, radius, max_records=3000):
    rid = resource["id"]
    schema, provenance = client.action("datastore_search", {"resource_id": rid, "limit": 0})
    available = {f["id"] for f in schema.get("fields", [])}
    if not {"POINT_X", "POINT_Y", "DIST", "_id"}.issubset(available):
        raise ValueError(f"{kind}: esquema sem coordenadas/distribuidora/identificador de paginação.")
    xmin, ymin, xmax, ymax = envelope(lat, lon, radius)
    query = {"POINT_X": coordinate_query(xmin, xmax), "POINT_Y": coordinate_query(ymin, ymax)}
    selected = ["_id"] + [f for f in FIELDS if f in available]
    rows, sources, offset, total, seen = [], [provenance], 0, None, set()
    rejected = 0
    while offset < max_records:
        page, source = client.action("datastore_search", {
            "resource_id": rid, "fields": ",".join(selected), "q": json.dumps(query),
            "plain": "false", "sort": "_id asc", "limit": min(1000, max_records - offset), "offset": offset,
        })
        records = page.get("records")
        if not isinstance(records, list) or not isinstance(page.get("total"), int):
            raise ValueError(f"{kind}: resposta incompleta, sem registros/contagem.")
        if total is not None and total != page["total"]:
            raise RuntimeError(f"{kind}: base alterada durante paginação; repita a consulta.")
        total = page["total"]
        sources.append(source)
        if not records and offset < total:
            raise RuntimeError(f"{kind}: paginação interrompida pela API.")
        for row in records:
            if row.get("_id") is None or row["_id"] in seen:
                raise RuntimeError(f"{kind}: paginação sem identificadores únicos.")
            seen.add(row["_id"])
            x, y = number(row.get("POINT_X")), number(row.get("POINT_Y"))
            if x is None or y is None or not (-180 <= x <= 180 and -90 <= y <= 90):
                rejected += 1
                continue
            distance = GEOD.inv(lon, lat, x, y)[2]
            if distance <= radius * 1000:
                # Whitelist protects against an API ignoring the field projection.
                clean = {f: row.get(f) for f in selected if f != "_id"}
                clean.update(kind=kind, latitude=y, longitude=x, distance_m=round(distance, 1))
                clean["reference_date"], clean["reference_origin"] = reference_date(clean, resource.get("description", ""))
                rows.append(clean)
        offset += len(records)
        if offset >= total:
            break
    return {"status": "partial" if offset < total else "ok", "kind": kind,
            "resource_id": rid, "resource_modified": resource.get("last_modified"),
            "records": sorted(rows, key=lambda r: r["distance_m"]), "scanned": offset,
            "cell_total": total, "rejected_coordinates": rejected, "sources": sources,
            "note": "Busca por prefixos decimais seguida de distância geodésica; universo público PJ. Ausência de retorno não comprova ausência de rede."}


def network_geometry(client, lat, lon, radius):
    metadata, source = client.get(SIGEL + "/13", {"f": "json"}, ttl=86400)
    extent = metadata.get("extent", {})
    if extent.get("spatialReference", {}).get("wkid") not in (4326, 4674):
        raise ValueError("Referencial da extensão SIGEL não reconhecido.")
    xmin, ymin, xmax, ymax = envelope(lat, lon, radius)
    if xmax < extent["xmin"] or xmin > extent["xmax"] or ymax < extent["ymin"] or ymin > extent["ymax"]:
        return {"status": "outside", "sources": [source], "features": [],
                "note": "Fora da extensão do conector AME_2023; não significa ausência de rede. Outros serviços regionais não estão integrados."}
    params = {"f": "json", "where": "1=1", "geometry": json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}),
              "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "COD_ID,CTMT,DIST,DATA_BASE",
              "returnGeometry": "true", "resultRecordCount": 1000, "orderByFields": "OBJECTID ASC"}
    data, query_source = client.get(SIGEL + "/13/query", params)
    if not isinstance(data.get("features"), list):
        raise ValueError("SIGEL sem lista de feições válida.")
    features = []
    for row in data["features"]:
        paths = row.get("geometry", {}).get("paths", [])
        if paths:
            features.append({"type": "Feature", "properties": row.get("attributes", {}),
                             "geometry": {"type": "MultiLineString", "coordinates": paths}})
    return {"status": "partial" if data.get("exceededTransferLimit") else "ok", "sources": [source, query_source],
            "features": features, "note": "Trechos MT do serviço regional AME_2023 (não nacional); recorte retangular, até 1.000 feições. Sem inferência de capacidade."}


def analyze_online(lat, lon, radius=1.5, cache_dir=None, refresh=False, tariff_subgroup="A4", tariff_date=None):
    validate_point(lat, lon, radius)
    client = PublicClient(cache_dir, refresh)
    result = {"mode": "online_preliminary", "version": VERSION, "analyzed_at": now(),
              "location": {"latitude": lat, "longitude": lon}, "radius_km": radius,
              "capacity_kw": None, "is_network_valid": False, "limitations": LIMITATIONS,
              "consumers": [], "consumer_sources": [], "errors": [], "package_url": PACKAGE_URL}

    def consumers():
        package, source = client.action("package_show", {"id": PACKAGE}, ttl=86400)
        result["catalog_source"] = source
        for kind in ("UCMT", "UCAT"):
            resources = [r for r in package.get("resources", []) if re.fullmatch(kind + r"_PJ\.csv", r.get("name", ""), re.I) and r.get("datastore_active")]
            if len(resources) != 1:
                result["errors"].append(f"{kind}: recurso DataStore único não encontrado no catálogo.")
                continue
            try:
                data = nearby_consumers(client, resources[0], kind, lat, lon, radius)
                result["consumer_sources"].append({k: v for k, v in data.items() if k != "records"})
                result["consumers"].extend(data["records"])
            except Exception as exc:
                result["errors"].append(f"{kind}: {exc}")

    # Independent sources: SIGEL failure must not hide CKAN results (or vice versa).
    with ThreadPoolExecutor(max_workers=2) as pool:
        uc = pool.submit(consumers)
        geo = pool.submit(network_geometry, client, lat, lon, radius)
        try:
            uc.result()
        except Exception as exc:
            result["errors"].append(f"Catálogo CKAN: {exc}")
        try:
            result["network"] = geo.result()
        except Exception as exc:
            result["network"] = {"status": "error", "features": [], "sources": [], "note": str(exc)}
            result["errors"].append(f"SIGEL: {exc}")
    result["consumers"].sort(key=lambda r: r["distance_m"])
    result["characterization"] = enrich(client, result["consumers"], tariff_subgroup, tariff_date)
    result["errors"].extend(result["characterization"]["warnings"])
    result["status"] = "partial" if result["errors"] or any(s["status"] == "partial" for s in result["consumer_sources"]) or result["network"]["status"] == "partial" else "ok"
    if any(result["characterization"][key]["status"] in ("partial", "error", "unavailable") for key in ("continuity", "tariffs")):
        result["status"] = "partial"
    return result
