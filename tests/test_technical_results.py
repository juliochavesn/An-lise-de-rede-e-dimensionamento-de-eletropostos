import numpy as np
import pandas as pd
import pytest

from src.technical_results import REQUIRED, prepare_dispatch, metrics, export_technical_results
from src.technical_ui import load_dispatch


def fixture():
    frame = pd.DataFrame({col: [0., 0.] for col in REQUIRED})
    frame['hour'] = [.125, .375]
    frame['local_load_kw'] = 2.
    frame['served_kw'] = frame['request_kw'] = 4.
    frame['grid_import_kw'] = 6.
    frame['grid_limit_kw'] = 10.
    frame['soc_kwh'] = [20., 30.]
    frame['expired_unserved_kwh'] = [1., 2.]
    return frame, dict(config='SMART_BESS', solve_status='solved', dt_h=.25,
                       bess_e_kwh=100., bess_soc_init_frac=.1)


def test_units_and_state_timing():
    frame, summary = fixture()
    df = prepare_dispatch(frame, summary)
    m = metrics(df)
    assert m['ev_served_kwh'] == 2.
    assert m['expired_unserved_kwh'] == 3.
    assert m['maximum_power_balance_error_kw'] == 0.
    assert df['soc_pct'].tolist() == [20., 30.]
    assert df['soc_start_pct'].tolist() == [10., 20.]
    assert df['interval_end_h'].tolist() == [.25, .5]


def test_absent_battery_and_zero_limit():
    frame, summary = fixture()
    summary['bess_e_kwh'] = 0
    frame['grid_limit_kw'] = 0
    df = prepare_dispatch(frame, summary)
    assert df['soc_pct'].isna().all()
    assert df['grid_utilization_pct'].isna().all()
    assert metrics(df)['grid_limit_exceedance_intervals'] == 2


@pytest.mark.parametrize('problem', ['infeasible', 'missing', 'nan', 'irregular', 'timestamp'])
def test_invalid_series_rejected(problem):
    frame, summary = fixture()
    if problem == 'infeasible': summary['solve_status'] = 'infeasible'
    if problem == 'missing': frame = frame.drop(columns='served_kw')
    if problem == 'nan': frame.loc[0, 'served_kw'] = np.nan
    if problem == 'irregular': frame.loc[1, 'hour'] = 1.
    if problem == 'timestamp': frame['timestamp'] = ['2021-01-01', '2021-01-02']
    with pytest.raises(ValueError): prepare_dispatch(frame, summary)


def test_balance_accounts_for_storage_and_export():
    frame, summary = fixture()
    frame['pv_avail_kw'] = 5.
    frame['pv_used_kw'] = 4.
    frame['pv_curt_kw'] = 1.
    frame['bess_ch_kw'] = 3.
    frame['grid_export_kw'] = 1.
    df = prepare_dispatch(frame, summary)
    assert metrics(df)['maximum_power_balance_error_kw'] == 0.
    assert metrics(df)['maximum_pv_balance_error_kw'] == 0.


def test_exports_and_exact_run_loading(tmp_path):
    frame, summary = fixture()
    frame.to_csv(tmp_path / 'timeseries_SMART_BESS.csv', index=False)
    assert len(load_dispatch(tmp_path, summary, 'daily')) == 2
    with pytest.raises(ValueError): load_dispatch(tmp_path, summary, 'annual')
    export_technical_results(frame, summary, tmp_path)
    assert (tmp_path / 'technical_peak_day_SMART_BESS.png').read_bytes().startswith(b'\x89PNG')
    assert (tmp_path / 'technical_overview_SMART_BESS.png').exists()
    assert (tmp_path / 'technical_metrics_SMART_BESS.json').exists()
