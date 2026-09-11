"""Serviços usados pela interface sem duplicar a lógica científica."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import GRID_NETWORK, OUTPUT_DIR, PV_LOCATION, SCENARIO_ANNUAL, TARIFF
from .grid_bdgd import build_grid_limit_profile
from .aneel_online import analyze_online
from .service_policy import normalize_policy


def new_run_dir(kind: str, latitude: float, longitude: float) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = OUTPUT_DIR / "interface" / f"{kind}_{stamp}_{latitude:.5f}_{longitude:.5f}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def analyze_preliminary(latitude, longitude, radius_km=1.5, refresh=False, tariff_subgroup="A4", tariff_date=None):
    """Consulta APIs e salva um snapshot; não abre BDGD nem chama o otimizador."""
    result = analyze_online(latitude, longitude, radius_km, OUTPUT_DIR / "api_cache", refresh, tariff_subgroup, tariff_date)
    output = new_run_dir("preliminar_api", latitude, longitude)
    result["output_dir"] = str(output)
    (output / "analise_preliminar.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Análise preliminar — APIs ANEEL", "",
             f"Ponto: {latitude:.7f}, {longitude:.7f}; raio: {radius_km} km.",
             f"Consulta: {result['analyzed_at']}; situação: {result['status']}.", "",
             f"Registros PJ no raio: {len(result['consumers'])}. Não representa inventário completo da rede.",
             "Capacidade residual: **não determinada**. Otimização elétrica não executada.", "",
             "## Limitações", ""] + ["- " + s for s in result["limitations"]]
    lines += ["", "## Fontes", "", result["package_url"], "", result["network"]["note"]]
    for source in result["consumer_sources"]:
        lines += [f"- {source['kind']}: recurso {source['resource_id']}; {source['scanned']}/{source['cell_total']} registros lidos nas células de busca; estado {source['status']}."]
    lines += ["", "## Ocorrências", ""] + ["- " + s for s in result["errors"]]
    lines += ["", "O JSON anexo contém coordenadas consultadas, parâmetros, datas de coleta, datas-base disponíveis e registros retornados para auditoria."]
    characterization = result.get("characterization", {})
    monthly_rows = []
    lines += ["", "## Consumo e demandas declaradas", "",
              "Totais de energia referem-se apenas à amostra PJ retornada; demandas são máximos individuais, nunca pico simultâneo de circuito. DIC/FIC são individuais, não DEC/FEC."]
    for group in characterization.get("monthly", []):
        header = {k: v for k, v in group.items() if k != "months"}
        monthly_rows.extend(dict(header, **month) for month in group["months"])
        lines += [f"- DIST {group['distributor_id']}, {group['kind']}, circuito {group['circuit']}, referência {group['reference_date']}, situação {group['registration_status']}: {group['consumer_count']} registros; energia anual reportada {group['annual_energy_kwh_reported']} kWh; meses completos na amostra: {group['annual_energy_complete']}. Maior demanda contratada individual: {group['contracted_demand_max_individual_kw']} kW."]
    pd.DataFrame(monthly_rows).to_csv(output / "consumo_demanda_mensal.csv", index=False)
    for key, filename, title in (("continuity", "continuidade_conjuntos.csv", "Continuidade dos conjuntos candidatos"), ("tariffs", "tarifas_referencia.csv", "Tarifas de referência")):
        section = characterization.get(key, {})
        pd.DataFrame(section.get("records", [])).to_csv(output / filename, index=False)
        lines += ["", "## " + title, "", f"Estado: {section.get('status', 'não consultado')}. Registros: {len(section.get('records', []))}.", section.get("note", ""), f"Tabela completa: {filename}. Fontes e filtros no snapshot JSON."]
        if key == "tariffs":
            lines += [f"Subgrupo consultado: {section.get('subgroup', '—')}; data de vigência consultada: {section.get('on_date', '—')}. Nenhuma tarifa do otimizador foi alterada."]
    (output / "analise_preliminar.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def analyze_point(latitude: float, longitude: float, threshold_kw: float, network_config=None) -> dict:
    output_dir = new_run_dir("rede", latitude, longitude)
    scenario = dict(SCENARIO_ANNUAL)
    scenario["base_grid_limit_kw"] = float(TARIFF["contracted_demand_max_kw"])
    location = dict(PV_LOCATION)
    location.update(latitude=float(latitude), longitude=float(longitude))
    network = dict(network_config or GRID_NETWORK)
    network["critical_capacity_threshold_kw"] = float(threshold_kw)
    profile = build_grid_limit_profile(scenario, location, network, output_dir)
    assessment = json.loads((output_dir / "grid_connection_assessment.json").read_text())
    critical_path = output_dir / "grid_capacity_critical_analysis.json"
    critical = json.loads(critical_path.read_text()) if critical_path.exists() else {}
    values = list(map(float, profile.values()))
    return {
        "output_dir": str(output_dir),
        "location": {"latitude": float(latitude), "longitude": float(longitude)},
        "threshold_kw": float(threshold_kw),
        "bdgd_reference_date": assessment.get("bdgd_reference_date"),
        "network_profile_calendar_start": assessment.get("network_profile_calendar_start"),
        "diagnostic": assessment,
        "assessment": assessment.get("assessment", {}),
        "is_network_valid": assessment.get("effective_limit_source") in ("bdgd", "minimum"),
        "critical": critical,
        "minimum_kw": min(values),
        "mean_kw": sum(values) / len(values),
        "maximum_kw": max(values),
    }


def simulate_point(latitude: float, longitude: float, mode: str,
                   configs: list[str], demand_scale: float,
                   local_scale: float, threshold_kw: float, network_config=None,
                   contracted_demand_cap_kw=None, service_policy=None) -> dict:
    policy = normalize_policy(service_policy)
    cap = None if contracted_demand_cap_kw is None else float(contracted_demand_cap_kw)
    if cap is not None and (not math.isfinite(cap) or cap <= 0
                           or cap < float(TARIFF.get("contracted_demand_min_kw", 0))):
        raise ValueError("Teto de demanda inválido: informe valor positivo e não inferior ao mínimo contratual.")
    output_dir = new_run_dir("simulacao", latitude, longitude)
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["EV_SERVICE_POLICY"] = json.dumps(policy)
    env.pop("EV_CONTRACTED_DEMAND_MAX_KW", None)
    env["EV_GRID_LIMIT_SOURCE"] = "bdgd" if cap is None else "minimum"
    if cap is not None:
        env["EV_CONTRACTED_DEMAND_MAX_KW"] = str(cap)
    env.update({
        "EV_OUTPUT_DIR": str(output_dir),
        "EV_SITE_LATITUDE": str(latitude),
        "EV_SITE_LONGITUDE": str(longitude),
        "EV_SIMULATION_MODE": mode,
        "EV_CONFIGS": ",".join(configs),
        "EV_DEMAND_SCALE": str(demand_scale),
        "EV_LOCAL_LOAD_SCALE": str(local_scale),
        "EV_CRITICAL_CAPACITY_KW": str(threshold_kw),
    })
    env["EV_BDGD_PATH"] = str((network_config or GRID_NETWORK)["bdgd_path"])
    inputs = {"latitude": latitude, "longitude": longitude, "mode": mode,
              "configs": sorted(configs), "demand_scale": demand_scale,
              "local_scale": local_scale, "threshold_kw": threshold_kw,
              "bdgd_path": env["EV_BDGD_PATH"],
              "limit_source": env["EV_GRID_LIMIT_SOURCE"],
              "contracted_demand_cap_kw": cap, "service_policy": policy}
    (output_dir / "simulation_inputs.json").write_text(
        json.dumps(inputs, indent=2, ensure_ascii=False), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(project_root / "main.py")], cwd=project_root,
        env=env, capture_output=True, text=True,
    )
    log = process.stdout + "\n" + process.stderr
    (output_dir / "simulation.log").write_text(log, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"A simulação falhou. Consulte {output_dir / 'simulation.log'}\n{process.stderr[-1500:]}")
    summary_path = output_dir / ("summary_annual.csv" if mode == "annual" else "summary_base.csv")
    expansion_path = output_dir / "grid_expansion_diagnostic.json"
    return {
        "output_dir": str(output_dir),
        "location": {"latitude": float(latitude), "longitude": float(longitude)},
        "diagnostic": json.loads((output_dir / "grid_connection_assessment.json").read_text()),
        "simulation_mode": mode,
        "inputs": inputs,
        "summary": pd.read_csv(summary_path),
        "expansion_diagnostic": (
            json.loads(expansion_path.read_text(encoding="utf-8"))
            if expansion_path.exists() else {}
        ),
        "log": log,
    }
