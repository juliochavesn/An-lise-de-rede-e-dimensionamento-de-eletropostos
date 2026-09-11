import pandas as pd

from src.profiles import (
    save_homer_load_profiles,
    save_homer_served_profile,
)


def test_save_homer_load_profiles(tmp_path):
    data = {
        "time_index": [0, 1, 2],
        "timestamps": [
            "2021-01-01T00:00:00",
            "2021-01-01T01:00:00",
            "2021-01-01T02:00:00",
        ],
        "local_load_kw": {0: 10.0, 1: 20.0, 2: 30.0},
        "request_kw": {0: 1.5, 1: 2.5, 2: 3.5},
    }

    paths = save_homer_load_profiles(data, tmp_path)

    assert set(paths) == {
        "homer_local_load_kw.csv",
        "homer_ev_request_kw.csv",
        "homer_total_load_kw.csv",
        "homer_load_profiles_audit.csv",
    }
    local = pd.read_csv(paths["homer_local_load_kw.csv"], header=None)[0]
    ev = pd.read_csv(paths["homer_ev_request_kw.csv"], header=None)[0]
    total = pd.read_csv(paths["homer_total_load_kw.csv"], header=None)[0]
    assert local.tolist() == [10.0, 20.0, 30.0]
    assert ev.tolist() == [1.5, 2.5, 3.5]
    assert total.tolist() == [11.5, 22.5, 33.5]


def test_save_homer_served_profile(tmp_path):
    results = pd.DataFrame({"served_kw": [10.25, 20.5, 30.75]})

    path = save_homer_served_profile(
        results,
        tmp_path,
        "SMART_PV_BESS",
    )

    assert path.name == "homer_ev_served_SMART_PV_BESS_kw.csv"
    served = pd.read_csv(path, header=None)[0]
    assert served.tolist() == [10.25, 20.5, 30.75]
