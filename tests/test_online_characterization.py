from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from src import online_characterization as c


def consumer(**kwargs):
    return dict({"DIST": "63", "kind": "UCMT", "CTMT": "A", "SIT_ATIV": "AT", "CONJ": "13807",
                 "reference_date": "2025-12-31", "distance_m": 1}, **kwargs)


def test_decimal_parser_and_zero_missing_negative():
    assert c.numeric("1.234,56") == 1234.56
    assert c.numeric(",19") == .19
    assert c.nonnegative("0") == 0
    assert c.nonnegative("") is None
    assert c.nonnegative("nan") is None
    assert c.nonnegative("-3") is None


def test_reference_provenance_and_invalid_date_not_replaced():
    assert c.reference_date({"DATA_BASE": "31DEC2025:00:00:00.0000000"}) == ("2025-12-31", "campo DATA_BASE")
    assert c.reference_date({}, "Posição em 31/12/2025.")[0] == "2025-12-31"
    assert "descrição" in c.reference_date({}, "Posição em 31/12/2025.")[1]
    assert c.reference_date({"DATA_BASE": "invalid"}, "Posição em 31/12/2025.")[0] is None


def test_monthly_energy_sum_but_demand_and_continuity_not_summed():
    groups = c.monthly_characterization([consumer(ENE_01="100", DEM_01="20", DIC_01="2", FIC_01="1"),
                                         consumer(ENE_01="200", DEM_01="30", DIC_01="3", FIC_01="2")])
    m = groups[0]["months"][0]
    assert m["energy_kwh_reported"] == 300
    assert m["demand_max_individual_kw"] == 30
    assert m["dic_max_individual_h"] == 3 and m["fic_max_individual"] == 2
    assert groups[0]["months"][1]["energy_kwh_reported"] is None
    assert not groups[0]["annual_energy_complete"]


def test_unknown_and_zero_preserved_and_quality_flagged():
    g = c.monthly_characterization([consumer(ENE_01="100", DEM_01="0"), consumer(ENE_01="", DEM_01="")])[0]
    m = g["months"][0]
    assert m["energy_reported_count"] == 1 and m["demand_reported_count"] == 1
    assert m["demand_zero_count"] == 1 and m["positive_energy_zero_demand_count"] == 1


def test_separate_distributors_years_circuits_and_registration_status():
    rows = [consumer(), consumer(DIST="64"), consumer(reference_date="2024-12-31"), consumer(CTMT="B"), consumer(SIT_ATIV="DS")]
    assert len(c.monthly_characterization(rows)) == 5


def test_ucat_does_not_sum_peak_demands_or_fill_missing_offpeak_energy():
    row = consumer(kind="UCAT", ENE_P_01="10", ENE_F_01="40", DEM_P_01="20", DEM_F_01="30", ENE_P_02="10")
    m = c.monthly_characterization([row])[0]["months"]
    assert m[0]["energy_kwh_reported"] == 50
    assert m[0]["demand_max_individual_kw"] == 30
    assert m[1]["energy_kwh_reported"] is None


def tariff(**kwargs):
    return dict({"DatInicioVigencia": "2025-01-01", "DatFimVigencia": "2025-12-31", "DscSubGrupo": "A4",
                 "DscBaseTarifaria": "Tarifa de Aplicação", "DscUnidadeTerciaria": "MWh", "VlrTE": "300,00", "VlrTUSD": "200,00"}, **kwargs)


def test_tariff_validity_boundaries_units_and_no_demand_conversion():
    rows, invalid = c.tariff_rows([tariff(), tariff(DscUnidadeTerciaria="kW"), tariff(DatFimVigencia="2024-12-31"), tariff(DscSubGrupo="B3"), tariff(DscBaseTarifaria="Base Econômica")], date(2025, 12, 31), "A4")
    assert len(rows) == 2 and invalid == 1
    assert rows[0]["energy_te_plus_tusd_brl_kwh"] == .5
    assert rows[1]["energy_te_plus_tusd_brl_kwh"] is None
    assert c.tariff_rows([tariff()], date(2026, 1, 1), "A4")[0] == []
    assert c.tariff_rows([tariff(VlrTE="")], date(2025, 1, 1), "A4")[0][0]["energy_te_plus_tusd_brl_kwh"] is None


def test_continuity_candidate_only_from_same_reference_year():
    rows = [{"IdeConjUndConsumidoras": 13807, "AnoIndice": y, "NumPeriodoIndice": 1,
             "NumCNPJ": "123", "SigAgente": "Agent", "SigIndicador": "DEC", "VlrIndiceEnviado": "0"} for y in (2024, 2025)]
    with patch.object(c, "discover", return_value=({"id": "x"}, {})), patch.object(c, "search_pages", return_value={"records": rows[:1], "sources": [], "total": 1, "status": "ok"}):
        d = c.continuity(None, [consumer()])
        assert d["candidates"] == [] and len(d["records"]) == 1
    with patch.object(c, "discover", return_value=({"id": "x"}, {})), patch.object(c, "search_pages", return_value={"records": rows, "sources": [], "total": 2, "status": "ok"}):
        d = c.continuity(None, [consumer()])
        assert len(d["candidates"]) == 1 and "não homologadas" in d["association"]


def test_tariff_unknown_identity_skips_network_and_rejects_unexpected_cnpj():
    with patch.object(c, "discover") as discover:
        assert c.tariffs(None, [])["status"] == "unavailable"
        discover.assert_not_called()
    with patch.object(c, "discover", return_value=({"id": "x"}, {})), patch.object(c, "search_pages", return_value={"records": [tariff(NumCNPJDistribuidora="999")], "sources": [], "total": 1, "status": "ok"}):
        assert c.tariffs(None, [{"cnpj": "00000000000123"}], on_date="2025-01-01")["records"] == []


def test_partial_enrichment_preserves_monthly_when_api_fails():
    with patch.object(c, "continuity", side_effect=RuntimeError("offline")):
        result = c.enrich(None, [consumer(ENE_01="10")])
    assert result["monthly"][0]["months"][0]["energy_kwh_reported"] == 10
    assert result["continuity"]["status"] == "error" and result["tariffs"]["status"] == "unavailable"


def test_online_ocm_only_and_tariff_filters_invalidate_results(tmp_path):
    root = Path(__file__).parents[1]
    assert not (root / "src/charging_stations.py").exists()
    assert "overpass" not in (root / "app.py").read_text().lower()
    with patch("streamlit_folium.st_folium", return_value={}), patch("src.ocm_ui.cached_ocm", return_value={"stations": [], "partial": False, "retrieved_at": "test"}) as fetch, patch("src.ocm_ui.cached_google_evcs", return_value={"stations": [], "database_updated_at": "test"}):
        app = AppTest.from_file(str(root / "app.py")).run()
        assert not app.exception
        fetch.assert_not_called()
        next(t for t in app.toggle if t.label == "Exibir eletropostos existentes").set_value(True).run()
        fetch.assert_called_once()
        assert not any(c.label == "Complementar com Open Charge Map" for c in app.checkbox)
        app.session_state["preliminary_result"] = {"invalid": "must disappear before rendering"}
        next(s for s in app.selectbox if s.label == "Subgrupo para consulta tarifária").set_value("B3").run()
        assert "preliminary_result" not in app.session_state and not app.exception
