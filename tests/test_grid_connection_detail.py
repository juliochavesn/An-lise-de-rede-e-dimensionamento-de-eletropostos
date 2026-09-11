import pandas as pd
import pytest

from src.grid_connection_detail import find_connection_path


def _segments():
    return pd.DataFrame([
        {
            "COD_ID": "s1", "PAC_1": "root", "PAC_2": "b",
            "COMP": 100.0, "TIP_CND": "c1",
        },
        {
            "COD_ID": "target", "PAC_1": "c", "PAC_2": "d",
            "COMP": 10.0, "TIP_CND": "c2",
        },
    ])


def test_connection_path_crosses_closed_switch_to_reach_segment():
    switches = pd.DataFrame([
        {"COD_ID": "sw1", "PAC_1": "b", "PAC_2": "c"},
    ])
    endpoint, path, target = find_connection_path(
        _segments(), switches, "root", "target"
    )
    assert endpoint == "c"
    assert [element[2][0] for element in path] == ["segment", "switch"]
    assert target["COD_ID"] == "target"


def test_connection_path_fails_when_operational_graph_is_disconnected():
    with pytest.raises(LookupError):
        find_connection_path(
            _segments(),
            pd.DataFrame(columns=["COD_ID", "PAC_1", "PAC_2"]),
            "root",
            "target",
        )


def test_unknown_accounting_connector_closes_only_topology():
    connectors = pd.DataFrame([{
        "COD_ID": "internal", "PAC_1": "root", "PAC_2": "entry",
        "COMP": 1., "SITCONT": "0", "FAS_CON": "ABC",
    }])
    segments = pd.DataFrame([
        {"COD_ID": "s1", "PAC_1": "entry", "PAC_2": "c", "COMP": 10., "TIP_CND": "c1"},
        {"COD_ID": "target", "PAC_1": "c", "PAC_2": "d", "COMP": 10., "TIP_CND": "c1"},
    ])
    endpoint, path, _ = find_connection_path(
        segments, pd.DataFrame(), "root", "target",
        topology_connectors=connectors,
    )
    assert endpoint == "c"
    assert [element[2][0] for element in path] == ["topology_connector", "segment"]


def test_operational_path_is_preferred_and_connector_count_is_bounded():
    segments = pd.DataFrame([
        {"COD_ID": "s1", "PAC_1": "root", "PAC_2": "c", "COMP": 100., "TIP_CND": "c1"},
        {"COD_ID": "target", "PAC_1": "c", "PAC_2": "d", "COMP": 1., "TIP_CND": "c1"},
    ])
    shortcut = pd.DataFrame([{"COD_ID": "x", "PAC_1": "root", "PAC_2": "c", "COMP": 1.}])
    _, path, _ = find_connection_path(segments, pd.DataFrame(), "root", "target",
                                      topology_connectors=shortcut)
    assert [element[2][0] for element in path] == ["segment"]
    disconnected = segments.iloc[[1]].copy()
    with pytest.raises(LookupError, match="acima do máximo seguro"):
        find_connection_path(disconnected, pd.DataFrame(), "root", "target",
            topology_connectors=pd.DataFrame([
                {"COD_ID": "x1", "PAC_1": "root", "PAC_2": "a", "COMP": 1.},
                {"COD_ID": "x2", "PAC_1": "a", "PAC_2": "c", "COMP": 1.},
            ]), max_topology_connectors=1)
