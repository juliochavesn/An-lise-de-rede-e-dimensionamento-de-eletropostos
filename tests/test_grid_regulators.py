import math

import pandas as pd
import pytest

from src.grid_connection_detail import find_connection_path, regulator_rating, decode_current


def test_regulator_connects_path_and_inactive_does_not():
    segments = pd.DataFrame([
        {"COD_ID": "s1", "PAC_1": "root", "PAC_2": "a", "COMP": 10},
        {"COD_ID": "target", "PAC_1": "b", "PAC_2": "c", "COMP": 10},
    ])
    units = pd.DataFrame([{"COD_ID": "r", "PAC_1": "a", "PAC_2": "b", "SIT_ATIV": "AT"}])
    empty = pd.DataFrame()
    with pytest.raises(LookupError):
        find_connection_path(segments, empty, "root", "target")
    endpoint, path, _ = find_connection_path(segments, empty, "root", "target", units)
    assert endpoint == "b"
    assert [edge[2][0] for edge in path] == ["segment", "regulator"]
    units["SIT_ATIV"] = "DS"
    with pytest.raises(LookupError):
        find_connection_path(segments, empty, "root", "target", units)


def equipment():
    return pd.DataFrame([{"COD_ID": str(i), "UN_RE": "r", "SITCONT": "AT1",
                          "COR_NOM": "24", "LIG_FAS_P": phase, "LIG_FAS_S": phase}
                         for i, phase in enumerate(["AB", "BC", "CA"])])


def test_rating_decodes_current_without_summing_phases():
    rating = regulator_rating({"COD_ID": "r", "FAS_CON": "ABC"}, equipment(), 11.4, .95, .8)
    assert rating["current_a"] == 300
    assert rating["capacity_kw"] == pytest.approx(math.sqrt(3)*11.4*300*.95*.8)
    assert decode_current("0") is None
    assert decode_current("999") is None
    assert decode_current("24.5") is None


@pytest.mark.parametrize("problem", ["missing", "unknown", "inactive", "phases"])
def test_unknown_rating_is_not_unlimited(problem):
    frame = equipment()
    if problem == "missing": frame = frame.iloc[:0]
    if problem == "unknown": frame.loc[0, "COR_NOM"] = "999"
    if problem == "inactive": frame["SITCONT"] = "DS"
    if problem == "phases": frame["LIG_FAS_P"] = "AN"
    with pytest.raises(ValueError, match="Regulador r"):
        regulator_rating({"COD_ID": "r", "FAS_CON": "ABC"}, frame, 11.4, .95, .8)
