import json
from unittest.mock import patch

import folium
import pytest

from src import openchargemap as ocm


def station(identifier=1, usage=1):
    return {"ID": identifier, "AddressInfo": {"Title": "Teste", "Latitude": -22.817, "Longitude": -47.069},
            "UsageType": {"ID": usage, "Title": "Public"}, "Connections": [{"PowerKW": 50, "Quantity": 2}],
            "DataProvider": {"Title": "Provider", "License": "CC BY 4.0"}}


def test_key_header_only_not_url_result_or_errors():
    with patch.object(ocm, "load_key", return_value="private-test-key"), patch.object(ocm.requests, "get") as get:
        get.return_value.status_code = 200
        get.return_value.json.return_value = [station()]
        result = ocm.fetch_ocm(-22.817, -47.069)
        assert get.call_args.kwargs["headers"]["X-API-Key"] == "private-test-key"
        assert "private-test-key" not in json.dumps(get.call_args.kwargs["params"])
        assert "private-test-key" not in json.dumps(result)
        assert get.call_args.kwargs["allow_redirects"] is False
        get.return_value.status_code = 401
        with pytest.raises(RuntimeError, match="autenticação"):
            ocm.fetch_ocm(-22.817, -47.069)


def test_access_distance_duplicates_and_metadata():
    payload = [station(), station(), station(2, 2), station(3, 3), station(4, 6), station(5, 7), station(6, 0)]
    far = station(7)
    far["AddressInfo"]["Latitude"] = 2
    payload.append(far)
    rows = ocm.normalize(payload, -22.817, -47.069, 10)
    assert len(rows) == 3
    assert [r["access"] for r in rows] == ["Público declarado", "Acesso condicionado", "Acesso não informado"]
    assert rows[0]["connections"][0]["power_kw"] == 50
    assert rows[0]["license"] == "CC BY 4.0"
    assert rows[0]["operational"] is None


def test_missing_key_and_invalid_input_do_not_request():
    with patch.object(ocm, "load_key", return_value=""), patch.object(ocm.requests, "get") as get:
        with pytest.raises(RuntimeError, match="não configurada"):
            ocm.fetch_ocm(-22, -47)
        with pytest.raises(ValueError):
            ocm.fetch_ocm(float("nan"), -47)
        get.assert_not_called()


def test_popup_escapes_external_markup():
    from src import ocm_ui
    row = ocm.normalize([station()], -22.817, -47.069, 10)[0]
    row["name"] = '<img src=x onerror="alert(1)">'
    with patch.object(ocm_ui, "cached_ocm", return_value={"stations": [row], "partial": False, "retrieved_at": "test"}), patch.object(ocm_ui, "cached_google_evcs", return_value={"stations": [], "database_updated_at": "test"}):
        view = folium.Map()
        ocm_ui.add_ocm_layer(view, -22.817, -47.069, 10)
        rendered = view.get_root().render()
        assert '<img src=x' not in rendered and '&lt;img' in rendered
        assert 'CC BY 4.0' in rendered
