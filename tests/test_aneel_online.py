import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from src import aneel_online as api


def record(identifier, x=-47.01, y=-22.01):
    return {"_id": identifier, "DIST": "63", "CTMT": "A", "SUB": "B",
            "DATA_BASE": "2025", "POINT_X": str(x), "POINT_Y": str(y),
            "LGRD": "Do not expose", "COD_ID_ENCR": "Do not expose"}


class FakeClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def action(self, action, params, **kwargs):
        self.calls.append(params)
        if params.get("limit") == 0:
            return {"fields": [{"id": key} for key in record(1)]}, {}
        return next(self.pages), {"retrieved_at": "test"}


def test_prefix_queries_cover_degree_and_equator_boundaries():
    q = api.coordinate_query(-47.02, -46.98)
    assert "'-47.0':*" in q and "'-46.9':*" in q
    q = api.coordinate_query(-0.01, 0.01)
    assert "'-0.0':*" in q and "'0.0':*" in q
    assert "'-47'" in api.coordinate_query(-47.01, -47)


def test_pagination_exact_radius_projection_and_partial_flags():
    client = FakeClient([{"records": [record(1), record(2, -47.09)], "total": 3},
                         {"records": [record(3)], "total": 3}])
    result = api.nearby_consumers(client, {"id": "test"}, "UCMT", -22.01, -47.01, 1.5)
    assert result["status"] == "ok" and len(result["records"]) == 2
    assert result["scanned"] == 3
    assert client.calls[-1]["offset"] == 2
    assert "LGRD" not in result["records"][0] and "COD_ID_ENCR" not in result["records"][0]
    client = FakeClient([{"records": [record(1)], "total": 3}])
    result = api.nearby_consumers(client, {"id": "test"}, "UCMT", -22.01, -47.01, 1.5, max_records=1)
    assert result["status"] == "partial" and result["cell_total"] == 3


@pytest.mark.parametrize("page", [{"records": [], "total": 2}, {"records": [record(1)]}])
def test_incomplete_api_not_treated_as_no_network(page):
    with pytest.raises((ValueError, RuntimeError)):
        api.nearby_consumers(FakeClient([page]), {"id": "test"}, "UCMT", -22, -47, 1)


def test_repeated_pages_rejected():
    client = FakeClient([{"records": [record(1)], "total": 2}, {"records": [record(1)], "total": 2}])
    with pytest.raises(RuntimeError, match="únicos"):
        api.nearby_consumers(client, {"id": "test"}, "UCMT", -22, -47, 1)


def test_invalid_coordinates_rejected_and_unknown_capacity_never_zero():
    with pytest.raises(ValueError):
        api.analyze_online(float("nan"), -47)
    with patch.object(api.PublicClient, "action", side_effect=RuntimeError("offline")), patch.object(api, "network_geometry", side_effect=RuntimeError("offline")):
        result = api.analyze_online(-22, -47)
    assert result["capacity_kw"] is None and not result["is_network_valid"]
    assert result["status"] == "partial" and len(result["errors"]) == 2


def test_cache_refresh_and_failed_response_not_cached(tmp_path):
    client = api.PublicClient(tmp_path)
    with patch.object(api.requests, "get") as get:
        get.return_value.json.return_value = {"success": True, "result": {"value": 1}}
        _, p1 = client.action("package_show", {"id": "a"})
        _, p2 = client.action("package_show", {"id": "a"})
        assert not p1["cached"] and p2["cached"] and get.call_count == 1
        assert p1["retrieved_at"] == p2["retrieved_at"]
        client.refresh = True
        client.action("package_show", {"id": "a"})
        assert get.call_count == 2
        get.return_value.json.return_value = {"success": False, "error": {}}
        with pytest.raises(RuntimeError):
            client.action("package_show", {"id": "bad"})
        assert len(list(tmp_path.glob("*.json"))) == 1


def test_geospatial_outside_extent_skips_query_without_claiming_no_network():
    with patch.object(api.PublicClient, "get", return_value=({"extent": {"spatialReference": {"wkid": 4674}, "xmin": -73, "xmax": -56, "ymin": -10, "ymax": 1}}, {})) as get:
        result = api.network_geometry(api.PublicClient(), -22, -47, 1.5)
        assert result["status"] == "outside" and get.call_count == 1


def test_default_online_ui_never_opens_bdgd_and_clears_point_and_radius(tmp_path):
    result = {"analyzed_at": "test", "location": {"latitude": -22, "longitude": -47},
              "radius_km": 1.5, "capacity_kw": None, "is_network_valid": False,
              "status": "ok", "errors": [], "consumer_sources": [], "consumers": [],
              "network": {"features": [], "note": "outside", "sources": []},
              "limitations": api.LIMITATIONS, "output_dir": str(tmp_path)}
    with patch("src.grid_map.load_bdgd_coverage", side_effect=AssertionError("Must not read BDGD")) as coverage, patch("src.grid_map.load_network_window", side_effect=AssertionError("Must not read BDGD")) as network, patch("src.ui_service.analyze_preliminary", return_value=result) as analyze, patch("streamlit_folium.st_folium", return_value={}):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
        assert not app.exception and app.radio(key="analysis_mode").value == "Preliminar — APIs online"
        coverage.assert_not_called()
        network.assert_not_called()
        assert not any(b.label == "Simular eletroposto neste ponto" for b in app.button)
        next(b for b in app.button if b.label == "Consultar APIs neste ponto").click().run()
        assert not app.exception and "preliminary_result" in app.session_state
        analyze.assert_called_once()
        next(s for s in app.slider if s.label == "Raio da consulta preliminar (km)").set_value(2.0).run()
        assert "preliminary_result" not in app.session_state
        next(b for b in app.button if b.label == "Consultar APIs neste ponto").click().run()
        app.text_input(key="online_lat").set_value("2,82")
        app.text_input(key="online_lon").set_value("-60,67")
        next(b for b in app.button if b.label == "Aplicar coordenadas").click().run()
        assert app.session_state["latitude"] == 2.82 and "preliminary_result" not in app.session_state
        assert not app.exception
        coverage.assert_not_called()
        network.assert_not_called()


def test_preliminary_service_does_not_call_physical_model(tmp_path):
    from src import ui_service
    result = {"analyzed_at": "now", "status": "partial", "consumers": [], "limitations": api.LIMITATIONS,
              "network": {"note": "unavailable"}, "package_url": api.PACKAGE_URL,
              "consumer_sources": [], "errors": [], "capacity_kw": None}
    with patch.object(ui_service, "analyze_online", return_value=result), patch.object(ui_service, "new_run_dir", return_value=tmp_path), patch.object(ui_service, "build_grid_limit_profile") as physical:
        ui_service.analyze_preliminary(-22, -47)
        physical.assert_not_called()
        assert json.loads((tmp_path / "analise_preliminar.json").read_text())["capacity_kw"] is None
        assert (tmp_path / "analise_preliminar.md").exists()
