import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.national_bdgd import latest_by_distributor, fetch_catalog, install_dataset
from src.grid_data_quality import local_utm_epsg


def item(identifier, date, revision, modified=1):
    return dict(id=identifier, title=f"Empresa_83_{date}_V11_{revision}",
                type="File Geodatabase", modified=modified)


def test_catalog_uses_reference_date_not_recent_edit_of_old_data():
    old = item("old", "2023-12-31", "20260903-1200", 999)
    current = item("new", "2025-12-31", "20260803-1200", 1)
    assert latest_by_distributor([old, current])[0]["id"] == "new"


def test_catalog_pagination_and_partial_response():
    pages = [dict(results=[item("a", "2024-12-31", "20250803-1200")], nextStart=2, total=2),
             dict(results=[item("b", "2025-12-31", "20260803-1200")], nextStart=-1, total=2)]
    with patch("src.national_bdgd.api_json", side_effect=pages) as api:
        result = fetch_catalog()
        assert api.call_count == 2
        assert result["distributor_count"] == 1
        assert result["item_count"] == 2
    with patch("src.national_bdgd.api_json", return_value=dict(results=[], nextStart=-1, total=4)):
        with pytest.raises(RuntimeError):
            fetch_catalog()


def test_download_rejects_untrusted_items_and_paths(tmp_path):
    with pytest.raises(ValueError):
        install_dataset("../../anything", tmp_path)
    with patch("src.national_bdgd.api_json", return_value={"orgId": "other", "type": "File Geodatabase"}):
        with pytest.raises(ValueError):
            install_dataset("a"*32, tmp_path)


def test_northern_and_southern_hemispheres_use_correct_projection():
    assert local_utm_epsg(2.8, -60.7) == 32620
    assert local_utm_epsg(-22.9, -47.1) == 32723


def test_selected_database_is_forwarded_to_optimizer_process(tmp_path):
    from src.ui_service import simulate_point
    (tmp_path / "summary_base.csv").write_text("scenario,cost\nSMART,10\n")
    (tmp_path / "grid_connection_assessment.json").write_text("{}")
    selected = str(tmp_path / "selected.gdb.zip")
    with patch("src.ui_service.new_run_dir", return_value=tmp_path), patch("src.ui_service.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as process:
        simulate_point(-23, -47, "daily", ["SMART"], 1, 1, 250, {"bdgd_path": selected})
        assert process.call_args.kwargs["env"]["EV_BDGD_PATH"] == selected


def test_ui_national_navigation_and_optional_charging_layer():
    from shapely.geometry import box, mapping
    from streamlit.testing.v1 import AppTest
    polygon = box(-51, -24, -46, -19)
    coverage = {"geometry": polygon, "bounds": [[-24, -51], [-19, -46]],
                "geojson": {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {}, "geometry": mapping(polygon)}]}}
    with patch("src.grid_map.load_bdgd_coverage", return_value=coverage), patch("src.grid_map.load_network_window", side_effect=LookupError("Sem rede")), patch("streamlit_folium.st_folium", return_value={}), patch("src.ocm_ui.cached_ocm", return_value={"stations": [], "partial": False, "retrieved_at": "test"}) as fetch:
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
        app.radio(key="analysis_mode").set_value("Detalhada — BDGD local").run()
        assert not app.exception
        fetch.assert_not_called()
        next(t for t in app.toggle if t.label == "Explorar Brasil").set_value(True).run()
        app.text_input(key="latitude_text").set_value("-15.79")
        app.text_input(key="longitude_text").set_value("-47.88")
        next(b for b in app.button if b.label == "Aplicar coordenadas").click().run()
        assert app.session_state["latitude"] == -15.79
        assert next(b for b in app.button if b.label == "Analisar rede neste ponto").disabled
        next(t for t in app.toggle if t.label == "Exibir eletropostos existentes").set_value(True).run()
        assert not any(c.label == "Complementar com Open Charge Map" for c in app.checkbox)
        assert not app.exception
        fetch.assert_called_once()
        next(t for t in app.toggle if t.label == "Exibir eletropostos existentes").set_value(False).run()
        assert not app.exception
        fetch.assert_called_once()
