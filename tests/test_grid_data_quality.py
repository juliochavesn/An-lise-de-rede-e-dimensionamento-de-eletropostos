import numpy as np
import pandas as pd
import pytest

from src.grid_data_quality import operational_rows
from src.grid_connection_detail import find_connection_path
from src.grid_residual_capacity import _build_existing_load_profile, CURVE_COLUMNS, ENERGY_COLUMNS


def test_accounting_status_is_not_operational_status():
    frame = pd.DataFrame({"SITCONT": ["AT1", "AT2", "SF", "BOP", "NIM", "NOP", "0", None]})
    assert operational_rows(frame, "SITCONT").SITCONT.tolist() == ["AT1", "SF", "BOP", "NIM"]
    assert operational_rows(pd.DataFrame({"SIT_ATIV": ["AT", "DS", "AT2"]}), "SIT_ATIV").SIT_ATIV.tolist() == ["AT"]


def test_physical_surplus_restores_path_but_accounting_only_does_not():
    frame = pd.DataFrame([
        dict(COD_ID="1", PAC_1="root", PAC_2="a", COMP=10, SITCONT="SF"),
        dict(COD_ID="2", PAC_1="a", PAC_2="b", COMP=10, SITCONT="AT1"),
    ])
    assert len(find_connection_path(operational_rows(frame, "SITCONT"), pd.DataFrame(), "root", "2")[1]) == 1
    frame.loc[0, "SITCONT"] = "AT2"
    with pytest.raises(LookupError):
        find_connection_path(operational_rows(frame, "SITCONT"), pd.DataFrame(), "root", "2")


def test_curves_preserve_class_energy_and_daily_annual_consistency():
    customers = pd.DataFrame([dict(TIP_CC=code, **{c: 372 for c in ENERGY_COLUMNS}) for code in ["a", "b"]])
    curves = pd.DataFrame([dict(COD_ID=code, TIP_DIA=day, **dict(zip(CURVE_COLUMNS, [amplitude]*(96))))
                           for code, amplitude in [("a", 1), ("b", 100)] for day in ["DU", "SA", "DO"]])
    month = pd.date_range("2021-01-01", periods=744, freq="h")
    full, missing = _build_existing_load_profile(np.full(12,744), customers, curves, month, 1)
    day, _ = _build_existing_load_profile(np.full(12,744), customers, curves, month[72:96], 1)
    assert missing == 0
    assert full.sum() == pytest.approx(744)
    np.testing.assert_allclose(day, full[72:96])
    np.testing.assert_allclose(full, 1)


def test_missing_pac_is_not_a_bus_connecting_unrelated_segments():
    frame = pd.DataFrame([
        dict(COD_ID="1", PAC_1="root", PAC_2="0", COMP=10),
        dict(COD_ID="2", PAC_1="0", PAC_2="a", COMP=10),
        dict(COD_ID="3", PAC_1="a", PAC_2="b", COMP=10),
    ])
    with pytest.raises(LookupError):
        find_connection_path(frame, pd.DataFrame(), "root", "3")
