"""Painel técnico da solução, sempre restrito aos arquivos da execução selecionada."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from .technical_results import prepare_dispatch, metrics, dispatch_figure, overview_figure


def load_dispatch(output, summary, mode=None):
    config = str(summary.get("config"))
    if config not in ("SMART", "SMART_PV", "SMART_BESS", "SMART_PV_BESS"):
        raise ValueError("Configuração inválida.")
    mode = summary.get("simulation_mode", mode)
    if mode in ("annual", "daily"):
        filename = f"timeseries{'_annual' if mode == 'annual' else ''}_{config}.csv"
        paths = [Path(output) / filename]
    else:
        paths = [p for p in (Path(output) / f"timeseries_{config}.csv", Path(output) / f"timeseries_annual_{config}.csv") if p.exists()]
    if len(paths) != 1 or not paths[0].exists():
        raise ValueError("Série da execução ausente ou ambígua; não foi usada uma série de outro cenário.")
    return prepare_dispatch(pd.read_csv(paths[0]), summary)


def render_technical_panel(result):
    from .technical_dashboard import render_dashboard
    render_dashboard(result)


def _render_legacy_day_panel(result):
    st.subheader("Gráficos técnicos da solução otimizada")
    summaries = result["summary"]
    if not {"solve_status", "config"}.issubset(summaries):
        st.info("Resumo sem estado de solução/configuração; gráficos não disponíveis.")
        return
    solved = summaries[summaries["solve_status"] == "solved"]
    if solved.empty:
        st.info("Nenhuma configuração resolvida nesta execução. Não há despacho otimizado para representar.")
        return
    names = {"SMART": "Recarga inteligente", "SMART_PV": "Recarga + solar", "SMART_BESS": "Recarga + bateria", "SMART_PV_BESS": "Recarga + solar + bateria"}
    key = sha256(str(result["output_dir"]).encode()).hexdigest()[:10]
    config = st.selectbox("Configuração dos gráficos técnicos", solved["config"].tolist(), format_func=lambda c: names.get(c, c), key="technical_config_" + key)
    summary = solved[solved["config"] == config].iloc[0].to_dict()
    try:
        df = load_dispatch(result["output_dir"], summary, result.get("simulation_mode"))
    except (ValueError, OSError) as exc:
        st.warning(str(exc))
        return
    values = metrics(df)
    st.caption(f"Indicadores do horizonte completo: {values['horizon_h']:g} horas, passo {df['dt_h'].iloc[0]:g} h. Figuras abaixo permitem examinar um dia sem médias horárias artificiais.")
    a, b, c, d = st.columns(4)
    a.metric("Pico de importação", f"{values['grid_peak_kw']:,.2f} kW")
    b.metric("Recarga atendida", f"{values['ev_served_kwh']:,.1f} kWh")
    c.metric("Energia de recarga expirada", f"{values['expired_unserved_kwh']:,.2f} kWh")
    d.metric("Menor margem ao limite aplicado", f"{values['minimum_grid_margin_kw']:,.2f} kW")
    if values["grid_limit_exceedance_intervals"] or values["maximum_power_balance_error_kw"] > 1e-4:
        st.warning("Há desvios acima da tolerância na série exportada. Consulte os resíduos e os dados antes de interpretar a solução.")
    days = df["day_label"].drop_duplicates().tolist()
    choice = st.radio("Período técnico", ["Dia do maior pico da rede", "Dia de maior energia solicitada por veículos", "Dia de menor margem ao limite", "Escolher dia"], horizontal=True, key="technical_period_" + key + config)
    if choice.startswith("Dia do maior"):
        day = values["grid_peak_day"]
    elif choice.startswith("Dia de maior energia"):
        day = (df["request_kw"] * df["dt_h"]).groupby(df["day_label"], sort=False).sum().idxmax()
    elif choice.startswith("Dia de menor"):
        day = df.loc[df["grid_margin_kw"].idxmin(), "day_label"]
    else:
        day = st.selectbox("Dia da simulação", days, key="technical_day_" + key + config)
    st.caption(f"Dia exibido: {day}. Potências representam intervalos; SOC e backlog são estados ao fim de cada intervalo. Recarga atendida pode exceder a solicitação instantânea por atender energia em espera.")
    if df["soc_pct"].isna().all():
        st.info("BESS não dimensionado ou capacidade nominal ausente: SOC (%) não é definido. As séries de energia (kWh) permanecem no CSV.")
    if not (df["grid_limit_kw"] > 1e-9).all():
        st.warning("Utilização percentual não é definida quando o limite é zero; esses intervalos ficam sem percentual, não com 0%. A margem em kW permanece disponível.")
    figure = dispatch_figure(df, summary, day)
    st.pyplot(figure, use_container_width=True)
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=160)
    figure.clear()
    st.download_button("Baixar painel técnico do dia (PNG)", buffer.getvalue(), f"despacho_{config}.png", "image/png")
    with st.expander("Visão geral: energias, curva de duração e comportamento no horizonte", expanded=False):
        figure = overview_figure(df, summary)
        st.pyplot(figure, use_container_width=True)
        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=160)
        figure.clear()
        st.download_button("Baixar visão geral (PNG)", buffer.getvalue(), f"visao_geral_{config}.png", "image/png")
    st.download_button("Baixar séries técnicas completas (CSV)", df.to_csv(index=False).encode(), f"series_tecnicas_{config}.csv", "text/csv")
    st.caption("Energia = soma de potência × duração do intervalo. Balanço: rede importada + FV utilizado + descarga BESS − carga local − recarga − carga BESS − exportação. A margem é relativa ao limite usado no modelo, não autorização de conexão da distribuidora.")
