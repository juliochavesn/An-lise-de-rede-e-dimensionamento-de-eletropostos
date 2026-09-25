"""Consulta espacial do inventário Google Places fornecido pelo colaborador."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import unicodedata

from pyproj import Geod


DRIVE_FILE_ID = "1RO2nvJGPb48XVBmsBOT9R49OmqdthqUx"
DRIVE_FILE_URL = f"https://drive.google.com/file/d/{DRIVE_FILE_ID}/view"
_GEOD = Geod(ellps="WGS84")
_CONNECTOR_NAMES = {
    "EV_CONNECTOR_TYPE_TYPE_2": "Tipo 2",
    "EV_CONNECTOR_TYPE_CCS_COMBO_2": "CCS Combo 2",
    "EV_CONNECTOR_TYPE_CHADEMO": "CHAdeMO",
    "EV_CONNECTOR_TYPE_TESLA": "Tesla",
    "EV_CONNECTOR_TYPE_NACS": "NACS",
    "EV_CONNECTOR_TYPE_J1772": "J1772",
}


def _database_path() -> Path:
    configured = os.environ.get("GOOGLE_EVCS_DB_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError("GOOGLE_EVCS_DB_PATH não aponta para um arquivo válido.")
        return path
    target = Path(tempfile.gettempdir()) / "eletroposto_google_evcs" / "EVCS.db"
    if target.exists() and target.stat().st_size > 1_000_000:
        return target
    import gdown

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    result = gdown.download(id=DRIVE_FILE_ID, output=str(partial), quiet=True)
    if not result or not partial.exists() or partial.stat().st_size <= 1_000_000:
        partial.unlink(missing_ok=True)
        raise ConnectionError("Não foi possível baixar a base Google de eletropostos.")
    with partial.open("rb") as stream:
        header = stream.read(16)
    if header != b"SQLite format 3\x00":
        partial.unlink(missing_ok=True)
        raise ValueError("O arquivo Google EVCS baixado não é um banco SQLite válido.")
    os.replace(partial, target)
    return target


def _json(value):
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}


def _connector_rows(options: dict) -> list[dict]:
    rows = []
    for item in options.get("connectorAggregation") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("type") or "Não informado")
        rows.append({
            "connector": _CONNECTOR_NAMES.get(
                code, code.replace("EV_CONNECTOR_TYPE_", "").replace("_", " ").title()
            ),
            "power_kw": item.get("maxChargeRateKw"),
            "quantity": item.get("count"),
            "current": "Não informado",
            "available_count": item.get("availableCount"),
            "out_of_service_count": item.get("outOfServiceCount"),
            "availability_updated_at": item.get("availabilityLastUpdateTime"),
        })
    return rows


def _status(connections: list[dict]) -> tuple[str, bool | None]:
    available = sum(int(row.get("available_count") or 0) for row in connections)
    unavailable = sum(int(row.get("out_of_service_count") or 0) for row in connections)
    if available > 0:
        return "Disponibilidade informada no cadastro Google", True
    if unavailable > 0:
        return "Conectores cadastrados como fora de serviço", False
    return "Situação operacional não informada", None


def fetch_google_evcs(latitude: float, longitude: float, radius_km: float = 10.0) -> dict:
    """Retorna somente registros dentro do raio, sem carregar a base toda na UI."""
    lat, lon, radius = float(latitude), float(longitude), float(radius_km)
    if not all(math.isfinite(v) for v in (lat, lon, radius)) or not (
        -90 <= lat <= 90 and -180 <= lon <= 180 and 0 < radius <= 25
    ):
        raise ValueError("Coordenada ou raio inválido para a base Google EVCS.")
    dlat = radius / 111.0
    dlon = radius / max(111.0 * abs(math.cos(math.radians(lat))), 1e-6)
    with sqlite3.connect(f"file:{_database_path()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT EVCS_ID, DISPLAY_NAME, LAT, LNG, CITY, STATE,
                      SEARCH_JSON, DETAILS_JSON, UPDATED_AT
                 FROM EVCS
                WHERE LAT BETWEEN ? AND ? AND LNG BETWEEN ? AND ?""",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()
        database_updated_at = connection.execute(
            "SELECT MAX(UPDATED_AT) FROM EVCS"
        ).fetchone()[0]
    stations = []
    for identifier, name, y, x, city, state, search_raw, detail_raw, updated_at in rows:
        distance = _GEOD.inv(lon, lat, float(x), float(y))[2]
        if distance > radius * 1000:
            continue
        search, details = _json(search_raw), _json(detail_raw)
        source = details or search
        options = details.get("evChargeOptions") or {}
        connections = _connector_rows(options)
        status, operational = _status(connections)
        powers = [float(row["power_kw"]) for row in connections if row.get("power_kw") is not None]
        maximum_power = max(powers) if powers else None
        estimated_total_power = sum(
            float(row["power_kw"]) * int(row.get("quantity") or 1)
            for row in connections if row.get("power_kw") is not None
        ) or None
        address = source.get("formattedAddress") or source.get("shortFormattedAddress") or ", ".join(
            str(value) for value in (city, state) if value
        )
        stations.append({
            "id": f"google:{identifier}", "google_place_id": identifier,
            "latitude": float(y), "longitude": float(x), "distance_m": round(distance, 1),
            "name": name or (source.get("displayName") or {}).get("text") or "Eletroposto sem nome",
            "access": "Acesso não informado", "usage": "Cadastro Google Maps; acesso a confirmar",
            "status": status, "operational": operational, "operator": "Não informado",
            "address": address, "connections": connections,
            "number_of_points": options.get("connectorCount"),
            "maximum_power_kw": maximum_power,
            "estimated_total_power_kw": estimated_total_power,
            "usage_cost": "Não informado",
            "access_comments": "Confirme acesso, tarifa e disponibilidade com o operador.",
            "verified_at": updated_at or "Não informado", "updated_at": updated_at or "Não informado",
            "provider": "Google Places (base fornecida por Daniel Guimarães)",
            "license": "Uso sujeito aos termos da fonte Google e da base compartilhada.",
            "url": details.get("googleMapsUri") or search.get("googleMapsUri") or DRIVE_FILE_URL,
            "sources": ["Google Places"],
        })
    return {
        "stations": sorted(stations, key=lambda row: row["distance_m"]),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "database_updated_at": database_updated_at,
        "source": "Google Places — base compartilhada", "radius_km": radius,
    }


def _name_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    words = [
        word for word in "".join(ch if ch.isalnum() else " " for ch in value).split()
        if word not in {"estacao", "recarga", "carregamento", "eletroposto", "charging", "station", "de", "da", "do"}
    ]
    return " ".join(words)


def _same_place(left: dict, right: dict) -> tuple[bool, float]:
    distance = _GEOD.inv(
        float(left["longitude"]), float(left["latitude"]),
        float(right["longitude"]), float(right["latitude"]),
    )[2]
    if distance <= 30.0:
        return True, distance
    left_name, right_name = _name_key(left.get("name", "")), _name_key(right.get("name", ""))
    ratio = SequenceMatcher(None, left_name, right_name).ratio() if left_name and right_name else 0.0
    overlap = bool(set(left_name.split()) & set(right_name.split()))
    return distance <= 100.0 and (ratio >= 0.45 or overlap), distance


def merge_station_sources(ocm_rows: list[dict], google_rows: list[dict]) -> tuple[list[dict], int]:
    """Funde duplicatas entre fontes e preserva locais distintos da mesma base."""
    merged = [dict(row, sources=["Open Charge Map"]) for row in ocm_rows]
    duplicate_count = 0
    matched_ocm_indices = set()
    for google in google_rows:
        matches = []
        for index, existing in enumerate(merged):
            same, distance = _same_place(existing, google)
            if (
                same
                and index not in matched_ocm_indices
                and "Open Charge Map" in existing.get("sources", [])
            ):
                matches.append((distance, index))
        if not matches:
            merged.append(dict(google))
            continue
        _, index = min(matches)
        target = merged[index]
        matched_ocm_indices.add(index)
        duplicate_count += 1
        target["sources"] = ["Open Charge Map", "Google Places"]
        target["google_place_id"] = google.get("google_place_id")
        target["google_url"] = google.get("url")
        target["google_name"] = google.get("name")
        if not target.get("address"):
            target["address"] = google.get("address")
        if not target.get("connections") and google.get("connections"):
            target["connections"] = google["connections"]
        if target.get("number_of_points") is None:
            target["number_of_points"] = google.get("number_of_points")
        target["maximum_power_kw"] = max(
            [value for value in (target.get("maximum_power_kw"), google.get("maximum_power_kw")) if value is not None],
            default=None,
        )
        target["estimated_total_power_kw"] = google.get("estimated_total_power_kw")
    return sorted(merged, key=lambda row: row.get("distance_m", float("inf"))), duplicate_count
