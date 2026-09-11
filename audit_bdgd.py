"""Auditoria repetível: cadastro completo da topologia e pontos geográficos.

Execute com o Python do projeto. Não altera coordenadas/configuração original.
Saídas em outputs/auditoria_bdgd; --output permite diretório separado.
"""
import argparse
import json
from pathlib import Path
from collections import Counter

import pandas as pd
import pyogrio

from src.config import GRID_NETWORK, SCENARIO_ANNUAL, TARIFF
from src.grid_bdgd import resolve_gdb_path, build_grid_limit_profile
from src.grid_data_quality import operational_rows


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        parent = self.parent
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def audit_topology(gdb, output):
    feeders = pyogrio.read_dataframe(gdb, layer="CTMT", read_geometry=False,
                                     columns=["COD_ID", "PAC_INI", "UNI_TR_AT"])
    layers, inventory = {}, {}
    for layer, status in [("SSDMT", "SITCONT"), ("UNSEMT", "SIT_ATIV"), ("UNREMT", "SIT_ATIV")]:
        columns = ["COD_ID", "CTMT", "PAC_1", "PAC_2", status]
        if layer == "UNSEMT":
            columns += ["P_N_OPE"]
        frame = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=False, columns=columns)
        inventory[layer] = {"rows": len(frame), "statuses": dict(Counter(frame[status].astype(str)))}
        layers[layer] = {str(k): v for k, v in frame.groupby("CTMT", sort=False)}
        print(layer, inventory[layer], flush=True)
    rows = []
    for feeder in feeders.itertuples():
        before, after = UnionFind(), UnionFind()
        segments = layers["SSDMT"].get(str(feeder.COD_ID), pd.DataFrame())
        if segments.empty:
            rows.append(dict(feeder_id=feeder.COD_ID, status="no_segments"))
            continue
        for layer, grouped in layers.items():
            frame = grouped.get(str(feeder.COD_ID), pd.DataFrame())
            if frame.empty:
                continue
            status = "SITCONT" if layer == "SSDMT" else "SIT_ATIV"
            if layer == "UNSEMT":
                frame = frame.loc[frame.P_N_OPE == "F"]
            old = frame.loc[frame[status].astype(str).str.startswith("AT")]
            new = operational_rows(frame, status)
            for graph, selected in [(before, old), (after, new)]:
                for a, b in selected[["PAC_1", "PAC_2"]].itertuples(index=False, name=None):
                    if str(a).strip().lower() not in {"", "0", "none", "nan"} and str(b).strip().lower() not in {"", "0", "none", "nan"}:
                        graph.join(a, b)
        active = operational_rows(segments, "SITCONT")
        old_count = new_count = 0
        for a, b in active[["PAC_1", "PAC_2"]].itertuples(index=False, name=None):
            old_count += before.find(a) == before.find(feeder.PAC_INI) or before.find(b) == before.find(feeder.PAC_INI)
            new_count += after.find(a) == after.find(feeder.PAC_INI) or after.find(b) == after.find(feeder.PAC_INI)
        rows.append(dict(feeder_id=feeder.COD_ID, operational_segments=len(active),
                         root_connected_before=old_count, root_connected_after=new_count,
                         disconnected_after=len(active)-new_count, status="audited"))
    pd.DataFrame(rows).to_csv(output / "topology_all_feeders.csv", index=False)
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return pd.DataFrame(rows)


POINTS = [
    ("São Carlos informado", -22.0377531, -47.8436565),
    ("CRO03 informado", -22.9817847, -46.9112778),
    ("Original", -22.817, -47.069),
    ("Campinas", -22.9056, -47.0608),
    ("Piracicaba", -22.7253, -47.6492),
    ("Ribeirão Preto", -21.1775, -47.8103),
    ("Araraquara", -21.7946, -48.1756),
    ("Bauru", -22.3145, -49.0587),
    ("Franca", -20.5386, -47.4008),
    ("Limeira", -22.5645, -47.4017),
    ("Rio Claro", -22.4114, -47.5614),
    ("Americana", -22.7392, -47.3313),
    ("Rural AUX33 com transformação série", -23.23132635537695, -48.47073825821403),
    ("Controle fora da região - São Paulo", -23.5505, -46.6333),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gdb", default=str(GRID_NETWORK["bdgd_path"]))
    parser.add_argument("--output", default="outputs/auditoria_bdgd")
    parser.add_argument("--skip-topology", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    gdb = resolve_gdb_path(args.gdb)
    if not args.skip_topology:
        table = audit_topology(gdb, output)
        print(table.select_dtypes("number").sum().to_dict(), flush=True)
    results = []
    for index, (label, lat, lon) in enumerate(POINTS):
        cfg = dict(GRID_NETWORK, bdgd_path=gdb, limit_source="bdgd")
        scenario = dict(SCENARIO_ANNUAL, base_grid_limit_kw=TARIFF["contracted_demand_max_kw"])
        folder = output / f"point_{index+1:02d}"
        build_grid_limit_profile(scenario, dict(latitude=lat, longitude=lon), cfg, folder)
        diagnostic = json.loads((folder / "grid_connection_assessment.json").read_text())
        assessment = diagnostic.get("assessment") or {}
        result = dict(label=label, latitude=lat, longitude=lon,
                      feeder=assessment.get("feeder_id"),
                      status="estimated" if diagnostic["effective_limit_source"] == "bdgd" else "inconclusive",
                      minimum_kw=diagnostic["physical_network_limit_kw_min"],
                      mean_kw=diagnostic["physical_network_limit_kw_mean"],
                      maximum_kw=diagnostic["physical_network_limit_kw_max"], error=assessment.get("error"))
        results.append(result)
        pd.DataFrame(results).to_csv(output / "point_tests.csv", index=False)
        print(result, flush=True)


if __name__ == "__main__":
    main()
