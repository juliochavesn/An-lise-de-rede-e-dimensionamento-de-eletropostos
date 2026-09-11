from io import StringIO
import pandas as pd
import pytest
from src.service_policy import normalize_policy, write_service_parameters
from src.technical_dashboard import quality_table, chronological_figure
from src.technical_results import REQUIRED, prepare_dispatch


@pytest.mark.parametrize('policy', [dict(target=1.01), dict(target=float('nan')),
    dict(waiting_penalty=-1), dict(mode='unknown'), dict(period='weekly'), dict(strict=1)])
def test_invalid_policy(policy):
    with pytest.raises(ValueError):
        normalize_policy(policy)


def test_legacy_default_and_zero_target():
    assert normalize_policy()['mode'] == 'maximum'
    assert normalize_policy(dict(mode='economic', target=0))['target'] == 0
    assert normalize_policy(dict(mode='economic'))['strict'] is False


def test_sparse_arcs_and_grouping():
    data = dict(time_index=[0, 1, 2], dt_h=12, month_of_t={0:1, 1:1, 2:2})
    for period, group in [('monthly', '0 1\n1 1\n2 2'), ('daily', '0 1\n1 1\n2 2')]:
        out = StringIO()
        write_service_parameters(out, data, dict(service_policy=dict(mode='economic', period=period)), 2)
        text = out.getvalue()
        assert 'set EV_ARCS := (0,0) (0,1) (1,1) (1,2) (2,2);' in text
        assert group in text
    out = StringIO()
    write_service_parameters(out, data, {}, 2)
    assert 'set EA := ;' in out.getvalue()
    assert 'set QG := ;' in out.getvalue()
    assert 'param strict_service_targets := 0;' in out.getvalue()


def data_fixture():
    frame = pd.DataFrame({c: [0., 0., 0.] for c in REQUIRED})
    frame['hour'] = [.5, 1.5, 2.5]
    frame['timestamp'] = pd.date_range('2023-01-31 23:00', periods=3, freq='h')
    frame['request_kw'] = [10., 0., 0.]
    frame['served_kw'] = [0., 10., 0.]
    frame['grid_import_kw'] = frame['served_kw']
    frame['grid_limit_kw'] = 20.
    frame['backlog_kwh'] = [10., 0., 0.]
    frame['cohort_served_kwh'] = [10., 0., 0.]
    summary = dict(config='SMART', solve_status='solved', dt_h=1., bess_e_kwh=0.)
    return frame, summary


def test_daily_groups_use_calendar_not_elapsed_days():
    out = StringIO()
    data = dict(time_index=[0, 1, 2], dt_h=1,
                timestamps=['2023-01-31T23:00', '2023-02-01T00:00', '2023-02-01T01:00'])
    write_service_parameters(out, data, dict(service_policy=dict(mode='economic', period='daily')), 2)
    assert '0 1\n1 2\n2 2' in out.getvalue()


def test_quality_tracks_origin_across_month_boundary():
    frame, summary = data_fixture()
    df = prepare_dispatch(frame, summary)
    q = quality_table(df)
    assert q.loc['2023-01', 'Atendimento (%)'] == 100
    assert pd.isna(q.loc['2023-02', 'Atendimento (%)'])
    fig = chronological_figure(df)
    assert len(fig.axes) == 4
    assert len(fig.axes[0].lines[0].get_xdata()) == 3
    fig.clear()


def test_cost_service_figure_has_one_curve_per_configuration():
    from src.technical_dashboard import cost_service_figure
    table = pd.DataFrame({
        'Configuração': ['SMART', 'SMART', 'SMART_PV'],
        'Atendimento (%)': [95., 99., 98.],
        'Custo líquido (R$)': [100., 140., 90.],
        'Meta': ['95%', '99%', '98%'],
    })
    fig = cost_service_figure(table)
    assert len(fig.axes[0].lines) == 2
    assert fig.axes[0].get_xlabel() == 'Atendimento efetivamente obtido (%)'
    fig.clear()


def test_dashboard_tabs_and_infeasible_comparison(tmp_path):
    from streamlit.testing.v1 import AppTest
    frame, summary = data_fixture()
    frame.to_csv(tmp_path / 'timeseries_annual_SMART.csv', index=False)
    summary.update(served_ratio=1., objective_value=100., contracted_demand_kw=10.)
    app = '''
import streamlit as st
import pandas as pd
from src.technical_dashboard import render_dashboard
result = st.session_state['test_result']
st.session_state['demand_comparison_history'] = [result]
render_dashboard(result)
'''
    at = AppTest.from_string(app, default_timeout=30)
    at.session_state['test_result'] = dict(summary=pd.DataFrame([summary]), output_dir=str(tmp_path),
        simulation_mode='annual', inputs=dict(service_policy=dict(mode='economic')))
    at.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ['Ano / horizonte completo', 'Qualidade de atendimento', 'Detalhe diário', 'Custo × atendimento']
    summary['solve_status'] = 'infeasible'
    at.session_state['test_result'] = dict(summary=pd.DataFrame([summary]), output_dir=str(tmp_path), inputs={})
    at.run()
    assert not at.exception
    assert len(at.warning) > 0
    assert len(at.dataframe) > 0
