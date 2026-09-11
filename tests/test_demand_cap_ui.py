import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src import ui_service
from src.grid_bdgd import build_network_aware_tariff, combine_grid_limits


@pytest.mark.parametrize("cap", [None, 80.0])
def test_service_sends_and_archives_cap(tmp_path, monkeypatch, cap):
    monkeypatch.setenv("EV_CONTRACTED_DEMAND_MAX_KW", "999")
    def run(*args, **kwargs):
        env = kwargs["env"]
        assert env["EV_GRID_LIMIT_SOURCE"] == ("bdgd" if cap is None else "minimum")
        assert env.get("EV_CONTRACTED_DEMAND_MAX_KW") == (None if cap is None else "80.0")
        policy = json.loads(env["EV_SERVICE_POLICY"])
        assert policy["mode"] == "economic"
        assert policy["target"] == .99
        assert policy["strict"] is False
        (tmp_path / "grid_connection_assessment.json").write_text(json.dumps({
            "effective_limit_source": env["EV_GRID_LIMIT_SOURCE"]}))
        pd.DataFrame([{"config": "SMART", "served_ratio": 1.0}]).to_csv(tmp_path / "summary_base.csv", index=False)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    with patch.object(ui_service, "new_run_dir", return_value=tmp_path), patch.object(
            ui_service.subprocess, "run", side_effect=run):
        result = ui_service.simulate_point(-22, -47, "daily", ["SMART"], 1, 1, 250,
                                          contracted_demand_cap_kw=cap,
                                          service_policy=dict(mode="economic", target=.99, strict=False))
    assert result["inputs"]["contracted_demand_cap_kw"] == cap
    assert json.loads((tmp_path / "simulation_inputs.json").read_text()) == result["inputs"]


@pytest.mark.parametrize("cap", [0, -1, float("nan"), float("inf")])
def test_service_rejects_invalid_caps(cap):
    with patch.object(ui_service, "new_run_dir") as directory:
        with pytest.raises(ValueError):
            ui_service.simulate_point(-22, -47, "daily", ["SMART"], 1, 1, 250,
                                      contracted_demand_cap_kw=cap)
        directory.assert_not_called()


@pytest.mark.parametrize("source,cap,expected", [("bdgd", None, [250, 50]), ("minimum", 80, [80, 50])])
def test_runtime_cap_reaches_network_and_contract(monkeypatch, source, cap, expected):
    import main
    for key in ("GRID_NETWORK", "TARIFF", "SCENARIO_BASE", "SCENARIO_ANNUAL"):
        monkeypatch.setattr(main, key, dict(getattr(main, key)))
    env = {"EV_GRID_LIMIT_SOURCE": source}
    env["EV_SERVICE_POLICY"] = json.dumps(dict(mode="economic", target=.99))
    if cap is not None:
        env["EV_CONTRACTED_DEMAND_MAX_KW"] = str(cap)
    main.apply_runtime_overrides(env)
    assert main.TARIFF["service_policy"]["target"] == .99
    profile = combine_grid_limits([250, 50], main.TARIFF["contracted_demand_max_kw"],
                                  main.GRID_NETWORK["limit_source"], 2)
    assert list(profile) == expected
    tariff = build_network_aware_tariff(main.TARIFF, dict(enumerate(profile)), main.GRID_NETWORK)
    assert tariff["contracted_demand_max_kw"] == (250 if cap is None else cap)
    assert main.GRID_NETWORK["on_error"] == "raise"


def test_interface_cap_and_comparison(tmp_path):
    from pathlib import Path
    from shapely.geometry import box, mapping
    from streamlit.testing.v1 import AppTest
    from src.config import PV_LOCATION
    polygon = box(-51, -24, -46, -19)
    coverage = {"geometry": polygon, "bounds": [[-24, -51], [-19, -46]],
                "geojson": {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {}, "geometry": mapping(polygon)}]}}
    location = {k: PV_LOCATION[k] for k in ("latitude", "longitude")}
    network = {"location": location, "threshold_kw": 250, "output_dir": str(tmp_path),
               "is_network_valid": True, "assessment": {}, "critical": {},
               "minimum_kw": 50, "mean_kw": 150, "maximum_kw": 250}
    def simulate(lat, lon, mode, configs, demand, local, threshold, network_config,
                 contracted_demand_cap_kw=None, service_policy=None):
        return {"output_dir": str(tmp_path), "simulation_mode": mode, "diagnostic": {},
                "inputs": {"latitude": lat, "longitude": lon, "mode": mode, "configs": configs,
                           "contracted_demand_cap_kw": contracted_demand_cap_kw},
                "summary": pd.DataFrame([{"config": "SMART", "served_ratio": 0.95,
                    "contracted_demand_kw": 80, "expired_unserved_energy_kwh": 5}])}
    with patch("src.grid_map.load_bdgd_coverage", return_value=coverage), patch(
            "src.grid_map.load_network_window", side_effect=LookupError("teste")), patch(
            "streamlit_folium.st_folium", return_value={}), patch(
            "src.ui_service.analyze_point", return_value=network), patch(
            "src.ui_service.simulate_point", side_effect=simulate) as sim, patch(
            "src.technical_ui.render_technical_panel"):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
        app.radio(key="analysis_mode").set_value("Detalhada — BDGD local").run()
        toggle = next(c for c in app.checkbox if c.label == "Limitar demanda contratada")
        assert not toggle.value
        next(b for b in app.button if b.label == "Simular eletroposto neste ponto").click().run()
        assert not app.exception
        assert sim.call_args.kwargs["contracted_demand_cap_kw"] is None
        assert sim.call_args.kwargs["service_policy"]["mode"] == "economic"
        assert sim.call_args.kwargs["service_policy"]["target"] == .98
        next(c for c in app.checkbox if c.label == "Limitar demanda contratada").check().run()
        next(c for c in app.number_input if c.label == "Teto da demanda contratada (kW)").set_value(80.0).run()
        next(b for b in app.button if b.label == "Simular eletroposto neste ponto").click().run()
        assert not app.exception
        assert sim.call_args.kwargs["contracted_demand_cap_kw"] == 80.0
        assert any(h.value == "Comparação dos tetos de demanda" for h in app.subheader)
        sim.reset_mock()
        next(c for c in app.checkbox if c.label == "Comparar metas 95%, 98%, 99% e 100%").check().run()
        next(b for b in app.button if b.label == "Simular eletroposto neste ponto").click().run()
        assert not app.exception
        assert [call.kwargs["service_policy"]["target"] for call in sim.call_args_list] == [.95, .98, .99, 1.]
