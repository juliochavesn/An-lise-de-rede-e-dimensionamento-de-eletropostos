import json

import numpy as np
import pandas as pd

from src.grid_capacity_analysis import (
    analyze_capacity_profile,
    run_capacity_critical_analysis,
)


def _audit_frame():
    timestamps = pd.date_range("2021-01-01", periods=48, freq="h")
    residual = np.r_[
        np.full(24, 1000.0),
        np.full(24, 800.0),
    ]
    residual[19] = 0.0
    residual[20] = 100.0
    residual[24 + 19] = 50.0
    residual[24 + 20] = 200.0
    return pd.DataFrame({
        "timestamp": timestamps,
        "residual_capacity_kw": residual,
    })


def test_analysis_finds_worst_day_and_constrained_hours():
    *_, summary = analyze_capacity_profile(
        _audit_frame(), threshold_kw=250.0, preferred_hour_count=3
    )
    assert summary["worst_date"] == "2021-01-01"
    assert summary["zero_capacity_interval_count"] == 1
    assert summary["critical_interval_count"] == 4
    assert summary["constrained_hours_p10_below_threshold"] == [19, 20]
    assert summary["preferred_charging_hours"] == [0, 1, 2]


def test_permanent_analysis_writes_all_outputs(tmp_path):
    summary = run_capacity_critical_analysis(
        _audit_frame(),
        tmp_path,
        {
            "critical_capacity_threshold_kw": 250.0,
            "preferred_charging_hour_count": 3,
        },
    )
    for path in summary["output_files"].values():
        assert pd.io.common.file_exists(path)
    saved = json.loads(
        (tmp_path / "grid_capacity_critical_analysis.json").read_text()
    )
    assert saved["critical_interval_count"] == 4
