"""Analise topologica e relatorio auditavel do ponto de conexao BDGD."""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd
from src.grid_data_quality import operational_rows, local_utm_epsg

# ANEEL PRODIST módulo 10, revisão 2 (01/01/2021), TCOR, pp. 173–174.
# https://www.cerpro.com.br/publico/arquivos/prodist/Modulo10.pdf
# COR_NOM é código, NÃO ampères. Código 0 ou desconhecido nunca vira infinito.
TCOR_AMPS = dict(enumerate([
    25, 40, 50, 56, 60, 70, 71.6, 75, 78.7, 80, 87.5, 100, 112,
    125, 125.5, 150, 160, 200, 209, 209.2, 219, 250, 280, 300,
    320, 328, 400, 420, 438, 440, 450, 500, 560, 600, 630, 800,
    850, 875, 1200, 1250, 1300, 1600, 1700, 1800, 1875, 2000,
    2100, 2400, 2500, 3000, 3150, 3500, 10000, 12000, 16000,
    20000, 25000, 50000,
], start=1))


def decode_current(code):
    try:
        numeric = float(code)
        if not math.isfinite(numeric) or numeric != int(numeric):
            return None
        return TCOR_AMPS.get(int(numeric))
    except (TypeError, ValueError):
        return None


def regulator_rating(unit, equipment, voltage_kv, power_factor, utilization):
    """Triagem trifásica conservadora; não soma correntes de unidades do banco."""
    identifier = str(unit["COD_ID"])
    rows = _active(equipment, "SITCONT")
    rows = rows.loc[rows["UN_RE"].astype(str) == identifier]
    if rows.empty:
        raise ValueError(f"Regulador {identifier}: sem equipamento EQRE ativo associado; capacidade não validada.")
    currents = [decode_current(value) for value in rows["COR_NOM"]]
    if any(value is None for value in currents):
        raise ValueError(f"Regulador {identifier}: COR_NOM ausente ou não mapeado; capacidade não validada.")
    # Não aplicar fórmula trifásica a ligações incompletas/desconhecidas.
    allowed = {"A", "B", "C", "AN", "BN", "CN", "AB", "BC", "CA", "AC", "ABC", "ABCN"}
    for field in ("LIG_FAS_P", "LIG_FAS_S"):
        phases = rows[field].astype(str).str.strip().str.upper().tolist()
        if any(value not in allowed for value in phases) or not set("ABC").issubset(set("".join(phases))):
            raise ValueError(f"Regulador {identifier}: ligação de fases incompleta/desconhecida; capacidade trifásica não validada.")
    if str(unit.get("FAS_CON", "")).strip() not in ("ABC", "ABCN"):
        raise ValueError(f"Regulador {identifier}: unidade não trifásica; capacidade não validada.")
    current = float(min(currents))
    return {
        "current_a": current,
        "capacity_kw": math.sqrt(3) * voltage_kv * current * power_factor * utilization,
        "equipment_ids": rows["COD_ID"].astype(str).tolist(),
        "current_codes": rows["COR_NOM"].astype(str).tolist(),
        "method": "minimum_equipment_current_as_conservative_line_current",
    }


def _active(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return operational_rows(frame, column)


def _closed_switches(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _active(frame, "SIT_ATIV")
    if "P_N_OPE" in frame:
        frame = frame.loc[frame["P_N_OPE"].astype(str) == "F"].copy()
    return frame


def _valid_pac(value):
    return str(value).strip().lower() not in {"", "0", "none", "nan", "null"}


def _dijkstra(adjacency, root: str, target: str):
    distances = {root: 0.0}
    previous = {}
    queue = [(0.0, root)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        if node == target:
            break
        for neighbor, weight, element in adjacency.get(node, []):
            candidate = distance + weight
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = (node, element)
                heapq.heappush(queue, (candidate, neighbor))
    if target not in distances:
        return None
    elements = []
    node = target
    while node != root:
        prior, element = previous[node]
        elements.append((prior, node, element))
        node = prior
    return distances[target], list(reversed(elements))


def find_connection_path(segments: pd.DataFrame, switches: pd.DataFrame,
                         root_pac: str, connection_segment_id: str,
                         regulators: pd.DataFrame | None = None,
                         topology_connectors: pd.DataFrame | None = None,
                         max_topology_connectors: int = 8):
    """Encontra caminho operacional ate o segmento, sem atravessar a si mesmo."""
    segment_ids = segments["COD_ID"].astype(str)
    target_rows = segments.loc[segment_ids == str(connection_segment_id)]
    if target_rows.empty:
        raise LookupError("Segmento de conexao nao pertence ao alimentador ativo.")
    target = target_rows.iloc[0]
    if not all(_valid_pac(v) for v in (root_pac, target["PAC_1"], target["PAC_2"])):
        raise LookupError("PAC da origem ou do trecho ausente/inválido; conexão não validada.")
    adjacency = defaultdict(list)

    for index, row in segments.iterrows():
        if str(row["COD_ID"]) == str(connection_segment_id):
            continue
        first, second = str(row["PAC_1"]), str(row["PAC_2"])
        if not _valid_pac(first) or not _valid_pac(second):
            continue
        weight = max(float(row.get("COMP", 0.0)), 0.001)
        element = ("segment", index)
        adjacency[first].append((second, weight, element))
        adjacency[second].append((first, weight, element))

    for index, row in switches.iterrows():
        first, second = str(row["PAC_1"]), str(row["PAC_2"])
        if not _valid_pac(first) or not _valid_pac(second):
            continue
        element = ("switch", index)
        adjacency[first].append((second, 0.001, element))
        adjacency[second].append((first, 0.001, element))

    # Alguns agentes representam ligações internas de subestação por trechos
    # com situação contábil não classificada. Eles podem fechar o grafo, mas
    # nunca fornecem ampacidade, impedância ou estado operacional ao cálculo.
    if topology_connectors is not None:
        for index, row in topology_connectors.iterrows():
            first, second = str(row["PAC_1"]), str(row["PAC_2"])
            if not _valid_pac(first) or not _valid_pac(second):
                continue
            element = ("topology_connector", index)
            penalty = 1_000_000_000.0 + max(float(row.get("COMP", 0.0)), 0.001)
            adjacency[first].append((second, penalty, element))
            adjacency[second].append((first, penalty, element))

    if regulators is not None:
        for index, row in _active(regulators, "SIT_ATIV").iterrows():
            first, second = str(row["PAC_1"]).strip(), str(row["PAC_2"]).strip()
            if first.lower() in ("", "0", "none", "nan") or second.lower() in ("", "0", "none", "nan"):
                continue
            element = ("regulator", index)
            adjacency[first].append((second, 0.001, element))
            adjacency[second].append((first, 0.001, element))

    candidates = []
    for endpoint in (str(target["PAC_1"]), str(target["PAC_2"])):
        result = _dijkstra(adjacency, str(root_pac), endpoint)
        if result is not None:
            candidates.append((result[0], endpoint, result[1]))
    if not candidates:
        raise LookupError(
            f"Não foi encontrado caminho fechado pelos PACs entre a origem {root_pac} "
            f"e o trecho {connection_segment_id}. Foram incluídos trechos operacionais "
            "AT1/SF/NIM/BOP/COM, chaves fechadas, reguladores ativos e conectores "
            "topológicos permitidos. Verificar "
            "PACs, chaves, equipamentos série e vínculos CTMT; não significa capacidade zero."
        )
    _, endpoint, path = min(candidates, key=lambda item: item[0])
    connector_count = sum(element[2][0] == "topology_connector" for element in path)
    if connector_count > int(max_topology_connectors):
        raise LookupError(
            f"O único caminho encontrado exige {connector_count} conectores de topologia "
            f"não classificados, acima do máximo seguro de {max_topology_connectors}."
        )
    return endpoint, path, target


def _reachable_node_count(segments: pd.DataFrame, switches: pd.DataFrame,
                          root_pac: str, regulators=None, topology_connectors=None) -> int:
    adjacency = defaultdict(set)
    for frame in (segments, switches, regulators if regulators is not None else pd.DataFrame(),
                  topology_connectors if topology_connectors is not None else pd.DataFrame()):
        for _, row in frame.iterrows():
            first, second = str(row["PAC_1"]), str(row["PAC_2"])
            if not _valid_pac(first) or not _valid_pac(second):
                continue
            adjacency[first].add(second)
            adjacency[second].add(first)
    visited = {str(root_pac)}
    queue = deque(visited)
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return len(visited)


def _nearby_transformers(gdb_path: Path, feeder_id: str, latitude: float,
                         longitude: float, radius_km: float):
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import Point

    delta_lat = radius_km / 111.0
    delta_lon = radius_km / max(
        111.0 * math.cos(math.radians(latitude)), 1e-6
    )
    frame = pyogrio.read_dataframe(
        gdb_path,
        layer="UNTRMT",
        bbox=(
            longitude - delta_lon,
            latitude - delta_lat,
            longitude + delta_lon,
            latitude + delta_lat,
        ),
        columns=["COD_ID", "CTMT", "POT_NOM", "SIT_ATIV", "PAC_1"],
    )
    frame = _active(frame, "SIT_ATIV")
    frame = frame.loc[frame["CTMT"].astype(str) == str(feeder_id)].copy()
    if frame.empty:
        return []
    zone = int((longitude + 180.0) // 6.0) + 1
    epsg = local_utm_epsg(latitude, longitude)
    point = gpd.GeoSeries(
        [Point(longitude, latitude)], crs="EPSG:4674"
    ).to_crs(epsg=epsg).iloc[0]
    projected = frame.to_crs(epsg=epsg)
    frame["distance_m"] = projected.geometry.distance(point).to_numpy()
    frame = frame.loc[frame["distance_m"] <= radius_km * 1000.0]
    frame["POT_NOM"] = pd.to_numeric(frame["POT_NOM"], errors="coerce")
    return [
        {
            "transformer_id": str(row["COD_ID"]),
            "nominal_power_kva": (
                float(row["POT_NOM"]) if pd.notna(row["POT_NOM"]) else None
            ),
            "distance_m": float(row["distance_m"]),
            "connection_point_id": str(row["PAC_1"]),
        }
        for _, row in frame.nsmallest(5, "distance_m").iterrows()
    ]


def assess_connection_path(gdb_path: Path, assessment: dict,
                           network_config: dict):
    """Monta o caminho eletrico, calcula impedancia e encontra o gargalo."""
    import pyogrio

    feeder_id = str(assessment["feeder_id"])
    escaped = feeder_id.replace("'", "''")
    feeder = pyogrio.read_dataframe(
        gdb_path,
        layer="CTMT",
        where=f"COD_ID='{escaped}'",
        columns=[
            "COD_ID", "PAC_INI", "BARR", "UNI_TR_AT", "SUB", "TEN_NOM",
            "TEN_OPE", "DIST", "RECONFIG",
        ],
        read_geometry=False,
    )
    if feeder.empty:
        raise LookupError(f"Alimentador {feeder_id} nao encontrado.")
    feeder_row = feeder.iloc[0]
    segment_columns = [
        "COD_ID", "CTMT", "PAC_1", "PAC_2", "PN_CON_1", "PN_CON_2",
        "TIP_CND", "COMP", "SITCONT", "FAS_CON", "TIP_INST",
    ]
    segments_all = pyogrio.read_dataframe(
        gdb_path,
        layer="SSDMT",
        where=f"CTMT='{escaped}'",
        columns=segment_columns,
        read_geometry=False,
    )
    segments = _active(segments_all, "SITCONT")
    accounting = segments_all["SITCONT"].astype(str).str.strip().str.upper()
    connector_codes = {str(value).strip().upper() for value in
                       network_config.get("topology_only_accounting_codes", ["0"])}
    topology_connectors = segments_all.loc[
        accounting.isin(connector_codes)
        & segments_all["PAC_1"].map(_valid_pac)
        & segments_all["PAC_2"].map(_valid_pac)
        & segments_all["FAS_CON"].astype(str).str.strip().isin(["ABC", "ABCN"])
    ].copy()
    switches_all = pyogrio.read_dataframe(
        gdb_path,
        layer="UNSEMT",
        where=f"CTMT='{escaped}'",
        columns=[
            "COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV", "P_N_OPE",
            "TIP_UNID", "COR_NOM",
        ],
        read_geometry=False,
    )
    active_switches = _active(switches_all, "SIT_ATIV")
    closed_switches = _closed_switches(switches_all)
    regulators = _active(pyogrio.read_dataframe(
        gdb_path, layer="UNREMT", where=f"CTMT='{escaped}'",
        columns=["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV", "FAS_CON", "TIP_REGU"],
        read_geometry=False,
    ), "SIT_ATIV")
    try:
        endpoint, path, target = find_connection_path(
            segments, closed_switches, str(feeder_row["PAC_INI"]),
            str(assessment["segment_id"]), regulators, topology_connectors,
            int(network_config.get("max_topology_only_connectors", 8)),
        )
    except LookupError as exc:
        units = _active(pyogrio.read_dataframe(
            gdb_path, layer="UNTRMT", where=f"CTMT='{escaped}'",
            columns=["COD_ID", "CTMT", "PAC_1", "PAC_2", "SIT_ATIV"],
            read_geometry=False,
        ), "SIT_ATIV")
        mt_nodes = set()
        for frame in (segments, closed_switches, regulators, topology_connectors):
            mt_nodes.update(frame["PAC_1"].astype(str))
            mt_nodes.update(frame["PAC_2"].astype(str))
        series = units.loc[units.PAC_1.astype(str).isin(mt_nodes) & units.PAC_2.astype(str).isin(mt_nodes)]
        extra = ""
        if not series.empty:
            extra = (" Há transformadores UNTRMT entre PACs da rede MT neste alimentador: "
                     + ", ".join(series.COD_ID.astype(str).head(10))
                     + ". A travessia requer modelar relação de tensão, potência e impedância; "
                     "não são tratados como fios nem como reguladores.")
        raise LookupError(str(exc) + extra) from exc

    regulator_equipment = pd.DataFrame()
    if any(element[2][0] == "regulator" for element in path):
        regulator_equipment = pyogrio.read_dataframe(
            gdb_path, layer="EQRE", read_geometry=False,
            columns=["COD_ID", "UN_RE", "SITCONT", "COR_NOM", "LIG_FAS_P", "LIG_FAS_S"],
        )

    conductor_ids = set(segments["TIP_CND"].astype(str))
    conductors = pyogrio.read_dataframe(
        gdb_path,
        layer="SEGCON",
        columns=["COD_ID", "CMAX", "CNOM", "R1", "X1", "CND_FAS", "DESCR"],
        read_geometry=False,
    )
    conductors = conductors.loc[
        conductors["COD_ID"].astype(str).isin(conductor_ids)
    ].copy()
    conductor_lookup = {
        str(row["COD_ID"]): row for _, row in conductors.iterrows()
    }

    # Um mínimo calculado ignorando um elo desconhecido não valida o caminho.
    path_indices = [element[1] for _, _, element in path if element[0] == "segment"]
    for _, row in segments.loc[path_indices + [target.name]].iterrows():
        conductor = conductor_lookup.get(str(row["TIP_CND"]))
        current = float(conductor["CMAX"]) if conductor is not None else float("nan")
        if not math.isfinite(current) or not 0 < current < 900:
            raise ValueError(f"Trecho {row['COD_ID']}: CMAX ausente/inválido; caminho não validado.")
        if str(row["FAS_CON"]).strip() not in {"ABC", "ABCN"}:
            raise ValueError(f"Trecho {row['COD_ID']}: ligação {row['FAS_CON']} não trifásica; modelo trifásico não aplicável.")
        if any(not math.isfinite(float(conductor[k])) or float(conductor[k]) < 0 for k in ("R1", "X1")):
            raise ValueError(f"Trecho {row['COD_ID']}: impedância ausente/inválida; caminho não validado.")

    voltage_kv = float(assessment["voltage_kv"])
    power_factor = float(network_config.get("power_factor", 0.95))
    utilization = float(
        network_config.get("thermal_utilization_factor", 0.80)
    )
    records = []
    segment_indices = []
    for sequence, (source, destination, element) in enumerate(path, start=1):
        kind, index = element
        frame = {"segment": segments, "switch": closed_switches, "regulator": regulators,
                 "topology_connector": topology_connectors}[kind]
        row = frame.loc[index]
        record = {
            "sequence": sequence,
            "element_type": kind,
            "element_id": str(row["COD_ID"]),
            "pac_from": source,
            "pac_to": destination,
            "length_m": float(row.get("COMP", 0.0)) if kind == "segment" else 0.0,
            "conductor_id": str(row.get("TIP_CND", "")) if kind == "segment" else "",
            "cmax_a": None,
            "thermal_capacity_kw": None,
            "r1_ohm_per_km": None,
            "x1_ohm_per_km": None,
        }
        if kind == "segment":
            segment_indices.append(index)
            conductor = conductor_lookup.get(record["conductor_id"])
            if conductor is not None:
                current = float(conductor["CMAX"])
                record["cmax_a"] = current
                record["thermal_capacity_kw"] = (
                    math.sqrt(3.0) * voltage_kv * current
                    * power_factor * utilization
                )
                record["r1_ohm_per_km"] = float(conductor["R1"])
                record["x1_ohm_per_km"] = float(conductor["X1"])
        elif kind == "regulator":
            rating = regulator_rating(row, regulator_equipment, voltage_kv, power_factor, utilization)
            record["cmax_a"] = rating["current_a"]
            record["thermal_capacity_kw"] = rating["capacity_kw"]
            record["equipment_ids"] = ",".join(rating["equipment_ids"])
            record["current_codes"] = ",".join(rating["current_codes"])
            record["capacity_method"] = rating["method"]
        elif kind == "topology_connector":
            record["capacity_method"] = "topology_only_no_electrical_rating"
            record["accounting_status"] = str(row.get("SITCONT", ""))
        records.append(record)

    # Inclui o proprio segmento onde o ponto foi projetado.
    target_conductor = conductor_lookup.get(str(target["TIP_CND"]))
    target_capacity = None
    target_current = None
    target_r1 = None
    target_x1 = None
    if target_conductor is not None:
        target_current = float(target_conductor["CMAX"])
        target_capacity = (
            math.sqrt(3.0) * voltage_kv * target_current
            * power_factor * utilization
        )
        target_r1 = float(target_conductor["R1"])
        target_x1 = float(target_conductor["X1"])
    records.append({
        "sequence": len(records) + 1,
        "element_type": "connection_segment",
        "element_id": str(target["COD_ID"]),
        "pac_from": endpoint,
        "pac_to": "connection_point_on_segment",
        "length_m": float(target["COMP"]),
        "conductor_id": str(target["TIP_CND"]),
        "cmax_a": target_current,
        "thermal_capacity_kw": target_capacity,
        "r1_ohm_per_km": target_r1,
        "x1_ohm_per_km": target_x1,
    })
    path_frame = pd.DataFrame(records)
    segment_path = path_frame.loc[
        path_frame["element_type"].isin(["segment", "connection_segment"])
    ].copy()
    capacity_numeric = pd.to_numeric(
        path_frame["thermal_capacity_kw"], errors="coerce"
    )
    valid_capacity = capacity_numeric.dropna()
    if valid_capacity.empty:
        raise ValueError("Nenhum condutor do caminho possui CMAX valido.")
    bottleneck_kw = float(valid_capacity.min())
    bottlenecks = path_frame.loc[np.isclose(
        capacity_numeric.fillna(float("inf")), bottleneck_kw
    )]
    total_length_km = float(segment_path["length_m"].sum()) / 1000.0
    r_total = float((
        pd.to_numeric(segment_path["r1_ohm_per_km"], errors="coerce").fillna(0.0)
        * segment_path["length_m"] / 1000.0
    ).sum())
    x_total = float((
        pd.to_numeric(segment_path["x1_ohm_per_km"], errors="coerce").fillna(0.0)
        * segment_path["length_m"] / 1000.0
    ).sum())
    reference_power = float(
        network_config.get("connection_reference_power_kw", 250.0)
    )
    current_a = reference_power / (
        math.sqrt(3.0) * voltage_kv * power_factor
    )
    reactive_factor = math.sqrt(max(1.0 - power_factor ** 2, 0.0))
    voltage_drop_percent = (
        math.sqrt(3.0) * current_a
        * (r_total * power_factor + x_total * reactive_factor)
        / (voltage_kv * 1000.0) * 100.0
    )

    nearby_radius = float(network_config.get("nearby_asset_radius_km", 1.0))
    nearby_transformers = _nearby_transformers(
        gdb_path,
        feeder_id,
        float(assessment["location"]["latitude"]),
        float(assessment["location"]["longitude"]),
        nearby_radius,
    )
    detail = {
        "method": "closed_switch_and_active_regulator_topological_path",
        "topology_recovery_used": bool((path_frame["element_type"] == "topology_connector").any()),
        "path_topology_connector_count": int((path_frame["element_type"] == "topology_connector").sum()),
        "path_topology_connector_ids": path_frame.loc[path_frame["element_type"] == "topology_connector", "element_id"].astype(str).tolist(),
        "path_regulator_count": int((path_frame["element_type"] == "regulator").sum()),
        "regulators": path_frame.loc[path_frame["element_type"] == "regulator"].dropna(axis=1, how="all").to_dict("records"),
        "bottleneck_element_ids": bottlenecks["element_id"].astype(str).tolist(),
        "bottleneck_element_types": sorted(bottlenecks["element_type"].unique().tolist()),
        "feeder_id": feeder_id,
        "feeder_name": str(feeder_row.get("COD_ID", feeder_id)),
        "feeder_root_pac": str(feeder_row["PAC_INI"]),
        "substation_bus": str(feeder_row.get("BARR", "")),
        "substation_transformer_id": str(feeder_row.get("UNI_TR_AT", "")),
        "connection_segment_id": str(assessment["segment_id"]),
        "connection_endpoint_used": endpoint,
        "connection_distance_to_segment_m": float(
            assessment["distance_to_mt_segment_m"]
        ),
        "path_length_km_upper_bound": total_length_km,
        "path_segment_count": int(len(segment_path)),
        "path_closed_switch_count": int(
            (path_frame["element_type"] == "switch").sum()
        ),
        "path_conductor_type_count": int(segment_path["conductor_id"].nunique()),
        "path_resistance_r1_ohm": r_total,
        "path_reactance_x1_ohm": x_total,
        "path_thermal_limit_kw": bottleneck_kw,
        "bottleneck_segment_ids": bottlenecks.loc[bottlenecks["element_type"].isin(["segment", "connection_segment"]), "element_id"].astype(str).tolist(),
        "bottleneck_conductor_ids": sorted(
            bottlenecks["conductor_id"].astype(str).unique().tolist()
        ),
        "reference_power_kw": reference_power,
        "reference_voltage_drop_percent": float(voltage_drop_percent),
        "feeder_active_segment_count": int(len(segments)),
        "feeder_total_segment_length_km": float(segments["COMP"].sum()) / 1000.0,
        "feeder_active_switch_count": int(len(active_switches)),
        "feeder_closed_switch_count": int(len(closed_switches)),
        "feeder_open_switch_count": int(
            (active_switches["P_N_OPE"].astype(str) == "A").sum()
        ),
        "feeder_reachable_node_count": _reachable_node_count(
            segments, closed_switches, str(feeder_row["PAC_INI"]), regulators,
            topology_connectors
        ),
        "nearby_asset_radius_km": nearby_radius,
        "nearby_transformers": nearby_transformers,
        "limitations": [
            "Chaves e elos fusíveis não têm coordenação de proteção modelada; limites de condutores/reguladores não autorizam acesso.",
            "Reguladores ativos UNREMT integram o caminho pelos PACs; os limites vêm de EQRE/COR_NOM convertido por TCOR.",
            "Triagem conservadora: menor corrente dos equipamentos do banco como corrente de linha, sem somar fases ou bancos paralelos.",
            "Não modela taps, controle, perdas nem impedância dos reguladores; queda de tensão refere-se somente aos condutores.",
            "O ponto e projetado no segmento mais proximo; nao confirma o PAC contratual.",
            "Chaves com P_N_OPE=F foram consideradas fechadas e A abertas.",
            "A queda de tensao e uma triagem por impedancia de sequencia positiva.",
            "Conectores topológicos de situação contábil não classificada, quando indispensáveis, fecham apenas o grafo: não fornecem capacidade, impedância nem autorização operacional.",
            "Nao inclui curto-circuito, protecao, fluxo trifasico ou criterio N-1.",
        ],
    }
    return detail, path_frame


def write_connection_detail_outputs(detail: dict, path_frame: pd.DataFrame,
                                    residual_metadata: dict,
                                    output_dir: Path):
    """Salva JSON, CSV e relatorio Markdown legivel pelo usuario."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(detail)
    payload["residual_capacity"] = residual_metadata
    conclusions = []
    if detail["connection_distance_to_segment_m"] > 50.0:
        conclusions.append(
            "O ponto esta afastado da rede MT cadastrada; uma extensao de rede "
            "ou redefinicao do PAC provavelmente sera necessaria."
        )
    conclusions.append(
        "O gargalo termico do caminho e formado pelos elementos "
        + ", ".join(detail.get("bottleneck_element_ids", detail["bottleneck_segment_ids"]))
        + f", com limite preliminar de {detail['path_thermal_limit_kw']:.2f} kW."
    )
    if detail.get("topology_recovery_used"):
        conclusions.append(
            "A continuidade cadastral exigiu conectores apenas topológicos: "
            + ", ".join(detail["path_topology_connector_ids"])
            + ". Eles não participaram do limite térmico nem da queda de tensão."
        )
    if residual_metadata["zero_capacity_intervals"] > 0:
        conclusions.append(
            "Existem intervalos sem margem incremental conservadora; conexao "
            "firme sem flexibilidade requer estudo de reforco ou dados medidos."
        )
    if detail["reference_voltage_drop_percent"] <= 3.0:
        conclusions.append(
            "A queda de tensao de triagem na potencia de referencia e inferior "
            "a 3%, mas deve ser confirmada por fluxo de potencia."
        )
    payload["conclusions"] = conclusions
    json_path = output_dir / "grid_connection_detailed.json"
    csv_path = output_dir / "grid_connection_path.csv"
    report_path = output_dir / "grid_connection_detailed_report.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    path_frame.to_csv(csv_path, index=False)

    residual = residual_metadata
    transformers = detail.get("nearby_transformers", [])
    critical_analysis = residual.get("critical_period_analysis", {})
    transformer_lines = (
        "\n".join(
            f"- {item['transformer_id']}: {item['nominal_power_kva']} kVA, "
            f"distancia {item['distance_m']:.1f} m"
            for item in transformers
        )
        if transformers else "- Nenhum transformador MT/BT ativo encontrado no raio."
    )
    critical_section = ""
    regulator_lines = "\n".join(
        f"- Regulador {item['element_id']}: corrente conservadora {item['cmax_a']:.1f} A; "
        f"teto {item['thermal_capacity_kw']:.2f} kW; equipamentos {item.get('equipment_ids', '')}."
        for item in detail.get("regulators", [])
    ) or "- Nenhum regulador atravessado neste caminho."
    if critical_analysis:
        preferred = ", ".join(
            f"{hour:02d}h"
            for hour in critical_analysis["preferred_charging_hours"]
        )
        constrained = ", ".join(
            f"{hour:02d}h"
            for hour in critical_analysis[
                "constrained_hours_p10_below_threshold"
            ]
        ) or "nenhum"
        critical_section = f"""
## Periodos criticos e recarga

- Pior dia: {critical_analysis['worst_date']}
- Limiar operacional analisado: {critical_analysis['threshold_kw']:.1f} kW
- Intervalos abaixo do limiar: {critical_analysis['critical_interval_count']}
- Intervalos com capacidade zero: {critical_analysis['zero_capacity_interval_count']}
- Horas preferenciais pelo P10: {preferred}
- Horas com P10 abaixo do limiar: {constrained}
"""
    report = f"""# Analise detalhada do ponto de conexao

## Identificacao

- Coordenadas: {payload.get('location', 'ver grid_connection_assessment.json')}
- Subestacao: {payload.get('substation_id', 'ver diagnostico principal')}
- Alimentador: {detail['feeder_id']}
- Segmento de conexao: {detail['connection_segment_id']}
- Distancia geografica ao segmento: {detail['connection_distance_to_segment_m']:.1f} m

## Caminho eletrico estimado

- Comprimento ate o ponto: ate {detail['path_length_km_upper_bound']:.3f} km
- Trechos de MT: {detail['path_segment_count']}
- Chaves fechadas atravessadas: {detail['path_closed_switch_count']}
- Reguladores atravessados: {detail.get('path_regulator_count', 0)}
- Tipos de condutor: {detail['path_conductor_type_count']}
- Resistencia R1 acumulada: {detail['path_resistance_r1_ohm']:.4f} ohm
- Reatancia X1 acumulada: {detail['path_reactance_x1_ohm']:.4f} ohm
- Gargalo termico do caminho: {detail['path_thermal_limit_kw']:.2f} kW
- Segmentos limitantes: {', '.join(detail['bottleneck_segment_ids'])}
- Queda de tensao preliminar a {detail['reference_power_kw']:.1f} kW: {detail['reference_voltage_drop_percent']:.3f}%

## Reguladores no caminho

{regulator_lines}

Correntes não são somadas entre equipamentos do banco. A menor corrente nominal
é aplicada como corrente de linha conservadora. Não inclui controle de taps.

## Capacidade residual

- Minima: {residual['residual_capacity_kw_min']:.2f} kW
- Media: {residual['residual_capacity_kw_mean']:.2f} kW
- Maxima: {residual['residual_capacity_kw_max']:.2f} kW
- Intervalos sem margem incremental: {residual['zero_capacity_intervals']}
- Fator de seguranca da carga: {residual['existing_load_safety_factor']:.2f}
- Credito firme da geracao distribuida: {residual['distributed_generation_credit_fraction']:.2f}

## Alimentador

- Segmentos ativos: {detail['feeder_active_segment_count']}
- Extensao total cadastrada: {detail['feeder_total_segment_length_km']:.2f} km
- Chaves ativas: {detail['feeder_active_switch_count']}
- Chaves fechadas: {detail['feeder_closed_switch_count']}
- Chaves abertas: {detail['feeder_open_switch_count']}
- Nos alcancaveis a partir da origem: {detail['feeder_reachable_node_count']}

## Transformadores proximos ({detail['nearby_asset_radius_km']:.1f} km)

{transformer_lines}

{critical_section}

## Interpretacao

{residual.get('warning', '')}

O limite usado pelo otimizador combina a margem do caminho e a margem estimada
do transformador compartilhado. Intervalo com capacidade
residual zero significa ausencia de margem incremental sob as premissas adotadas,
nao interrupcao do fornecimento existente.

## Conclusoes automaticas

""" + "\n".join(f"- {item}" for item in conclusions) + """

## Limitacoes

""" + "\n".join(f"- {item}" for item in detail["limitations"]) + "\n"
    report_path.write_text(report, encoding="utf-8")
    return {
        "json": json_path,
        "path_csv": csv_path,
        "report": report_path,
    }
