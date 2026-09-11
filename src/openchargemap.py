"""Consulta OCM somente no servidor; credencial nunca integra URL/cache/retorno."""
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Geod

ENDPOINT = "https://api.openchargemap.io/v3/poi/"
KEY_FILE = Path.home() / ".config" / "eletropostos" / "openchargemap.key"


def load_key():
    key = os.environ.get("OPENCHARGEMAP_API_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def normalize(payload, lat, lon, radius):
    if not isinstance(payload, list):
        raise ValueError("Resposta Open Charge Map inválida.")
    rows, seen = [], set()
    for item in payload:
        if not isinstance(item, dict) or item.get("ID") is None or item["ID"] in seen:
            continue
        seen.add(item["ID"])
        address = item.get("AddressInfo") or {}
        try:
            x, y = float(address["Longitude"]), float(address["Latitude"])
            if not math.isfinite(x) or not math.isfinite(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
                continue
            distance = Geod(ellps="WGS84").inv(lon, lat, x, y)[2]
            if distance > radius * 1000:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        usage = item.get("UsageType") or {}
        usage_id = usage.get("ID", item.get("UsageTypeID"))
        # Official UsageType IDs: private residences/staff/public-notice excluded.
        if usage_id in (2, 3, 6):
            continue
        access = "Público declarado" if usage_id in (1, 4, 5) else (
            "Acesso condicionado" if usage_id == 7 else "Acesso não informado")
        status = item.get("StatusType") or {}
        provider = item.get("DataProvider") or {}
        connections = []
        for c in item.get("Connections") or []:
            power = c.get("PowerKW")
            quantity = c.get("Quantity")
            connections.append({"connector": (c.get("ConnectionType") or {}).get("Title", "Não informado"),
                                "power_kw": power, "quantity": quantity,
                                "current": (c.get("CurrentType") or {}).get("Title", "Não informado")})
        rows.append({"id": item["ID"], "latitude": y, "longitude": x, "distance_m": round(distance, 1),
                     "name": address.get("Title") or "Eletroposto sem nome", "access": access,
                     "usage": usage.get("Title") or "Não informado", "status": status.get("Title") or "Não informado",
                     "operational": status.get("IsOperational"),
                     "operator": (item.get("OperatorInfo") or {}).get("Title") or "Não informado",
                     "address": ", ".join(str(address[k]) for k in ("AddressLine1", "AddressLine2", "Town", "StateOrProvince") if address.get(k)),
                     "connections": connections, "number_of_points": item.get("NumberOfPoints"),
                     "usage_cost": item.get("UsageCost") or "Não informado",
                     "access_comments": item.get("GeneralComments") or "Não informado",
                     "verified_at": item.get("DateLastVerified") or "Não informado",
                     "updated_at": item.get("DateLastStatusUpdate") or "Não informado",
                     "provider": provider.get("Title") or "Fornecedor não informado",
                     "license": provider.get("License") or "Condições do fornecedor no Open Charge Map",
                     "url": f"https://openchargemap.org/site/poi/details/{int(item['ID'])}"})
    return sorted(rows, key=lambda r: r["distance_m"])


def fetch_ocm(latitude, longitude, radius_km=10):
    lat, lon, radius = float(latitude), float(longitude), float(radius_km)
    if not all(math.isfinite(v) for v in (lat, lon, radius)) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius <= 25):
        raise ValueError("Coordenada ou raio inválido para Open Charge Map.")
    key = load_key()
    if not key:
        raise RuntimeError("Chave Open Charge Map não configurada no servidor.")
    try:
        response = requests.get(ENDPOINT, params={"output": "json", "latitude": lat, "longitude": lon,
            "distance": radius, "distanceunit": "KM", "maxresults": 500,
            "compact": "false", "verbose": "false"},
            headers={"X-API-Key": key, "User-Agent": "EletropostoResearch/1.0"}, timeout=(8, 30), allow_redirects=False)
        if response.status_code in (401, 403):
            raise RuntimeError("Open Charge Map recusou a autenticação; revise a chave local.")
        if response.status_code != 200:
            raise RuntimeError(f"Open Charge Map indisponível (HTTP {response.status_code}).")
        payload = response.json()
    except (requests.RequestException, ValueError):
        # Never propagate a response/request object, headers or echoed credentials.
        raise RuntimeError("Falha de comunicação com Open Charge Map; tente novamente mais tarde.") from None
    return {"stations": normalize(payload, lat, lon, radius), "partial": len(payload) >= 500,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "source": "Open Charge Map",
            "radius_km": radius}
