import json
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import box, mapping
from streamlit.testing.v1 import AppTest

from src import ui_service


def test_service_reads_nested_assessment(tmp_path):
    diagnostic = {"effective_limit_source": "bdgd", "assessment": {"feeder_id": "SCA01"}}

    def build(*args):
        (tmp_path / "grid_connection_assessment.json").write_text(json.dumps(diagnostic))
        return {1: 200.0}

    with patch.object(ui_service, "new_run_dir", return_value=tmp_path), patch.object(
        ui_service, "build_grid_limit_profile", side_effect=build
    ):
        result = ui_service.analyze_point(-22, -47, 250)
    assert result["assessment"]["feeder_id"] == "SCA01"
    assert result["is_network_valid"]


def test_coordinates_and_fallback_display(tmp_path):
    import pandas as pd
    pd.DataFrame([{"timestamp": "2025-01-01 18:00", "residual_capacity_kw": 100,
                   "is_zero": False, "is_critical": True, "hour": 18}]).to_csv(
        tmp_path / "grid_capacity_critical_intervals.csv", index=False)
    polygon = box(-51, -24, -46, -19)
    coverage = {"geometry": polygon, "bounds": [[-24, -51], [-19, -46]],
                "geojson": {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {}, "geometry": mapping(polygon)}]}}
    result = {"location": {"latitude": -22.0377531, "longitude": -47.8436565},
              "threshold_kw": 250, "output_dir": str(tmp_path), "is_network_valid": False,
              "assessment": {"error": "Caminho não encontrado"}, "critical": {},
              "minimum_kw": 100, "mean_kw": 100, "maximum_kw": 100}
    with patch("src.grid_map.load_bdgd_coverage", return_value=coverage), patch(
        "src.grid_map.load_network_window", side_effect=LookupError("Sem rede no recorte")
    ), patch("streamlit_folium.st_folium", return_value={}), patch(
        "src.ui_service.analyze_point", return_value=result
    ), patch("src.ui_service.simulate_point") as simulate:
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
        app.radio(key="analysis_mode").set_value("Detalhada — BDGD local").run()
        assert not app.exception
        app.text_input(key="latitude_text").set_value("-22,0377531")
        app.text_input(key="longitude_text").set_value("-47,8436565")
        next(button for button in app.button if button.label == "Aplicar coordenadas").click().run()
        assert not app.exception
        assert app.session_state["latitude"] == -22.0377531
        assert app.session_state["longitude"] == -47.8436565
        assert app.code[0].value == "-22.0377531, -47.8436565"
        next(button for button in app.button if button.label == "Analisar rede neste ponto").click().run()
        assert not app.exception
        assert any("inconclusiva" in error.value for error in app.error)
        assert all(metric.value != "100.0 kW" for metric in app.metric)
        assert any("Data e hora" in frame.value.columns and "Capacidade residual (kW)" in frame.value.columns
                   for frame in app.dataframe)
        assert not app.get("doc_string")
        next(button for button in app.button if button.label == "Simular eletroposto neste ponto").click().run()
        simulate.assert_not_called()
        app.text_input(key="latitude_text").set_value("-23")
        app.text_input(key="longitude_text").set_value("-48")
        next(button for button in app.button if button.label == "Aplicar coordenadas").click().run()
        assert "network_result" not in app.session_state
        app.text_input(key="latitude_text").set_value("0")
        next(button for button in app.button if button.label == "Aplicar coordenadas").click().run()
        assert app.session_state["latitude"] == -23
        assert any("fora" in warning.value for warning in app.warning)
