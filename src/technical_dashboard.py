"""Ano cronológico, serviço por origem da demanda e comparação econômica."""
from io import BytesIO
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.figure import Figure
from .technical_results import metrics, dispatch_figure, overview_figure
from .service_policy import describe_policy

def chronological_figure(df):
    fig = Figure(figsize=(14, 12), layout="constrained")
    axes = fig.subplots(4, 1, sharex=True)
    x = df["timestamp"] if "timestamp" in df else df["interval_start_h"]
    series = [(["local_load_kw", "request_kw", "served_kw"], ["Carga local", "Recarga solicitada", "Recarga atendida"], "Carga e recarga (kW)"),
              (["grid_import_kw", "grid_limit_kw"], ["Importação", "Limite aplicado"], "Rede (kW)"),
              (["pv_avail_kw", "pv_used_kw", "bess_ch_kw", "bess_dis_kw"], ["FV disponível", "FV utilizado", "Carga BESS", "Descarga BESS"], "FV e BESS (kW)"),
              (["soc_pct"], ["SOC"], "Estado da bateria (%)")]
    for ax,(cols,labels,title) in zip(axes,series):
        for col,label in zip(cols,labels):
            ax.plot(x, df[col], label=label, linewidth=.65)
        ax.set_ylabel(title); ax.grid(alpha=.2); ax.legend(loc="upper right", fontsize=8)
        if not any(df[col].notna().any() for col in cols):
            ax.text(.5, .5, "Não aplicável — sem capacidade de BESS", transform=ax.transAxes, ha="center")
    axes[-1].set_xlabel("Data" if "timestamp" in df else "Hora da simulação")
    fig.suptitle("Despacho cronológico — sem agregação; selecione um período para examinar picos")
    return fig

def quality_table(df, period="monthly"):
    groups = (df["timestamp"].dt.strftime("%Y-%m") if period == "monthly" and "timestamp" in df
              else df["day_label"])
    source = pd.DataFrame({"Solicitada (kWh)": df["request_kw"]*df["dt_h"],
        "Atendida (kWh)": df.get("cohort_served_kwh", df["served_kw"]*df["dt_h"]),
        "Expirada no período (kWh)": df["expired_unserved_kwh"],
        "Espera energética (kWh·h)": df["backlog_kwh"]*df["dt_h"]})
    q = source.groupby(groups, sort=False).sum()
    q["Atendimento (%)"] = q["Atendida (kWh)"].div(q["Solicitada (kWh)"].where(q["Solicitada (kWh)"] > 1e-9))*100
    return q

def show_figure(fig, name):
    st.pyplot(fig, use_container_width=True)
    buf = BytesIO(); fig.savefig(buf, format="png", dpi=140); fig.clear()
    st.download_button("Baixar " + name + " (PNG)", buf.getvalue(), name + ".png", "image/png", key="png_"+name)

def cost_service_figure(table):
    fig = Figure(figsize=(9, 5), layout="constrained")
    ax = fig.subplots()
    for config, group in table.groupby("Configuração", sort=False):
        group = group.sort_values("Atendimento (%)")
        ax.plot(group["Atendimento (%)"], group["Custo líquido (R$)"], marker="o", linewidth=1.5, label=config)
        for _, row in group.iterrows():
            ax.annotate(str(row["Meta"]), (row["Atendimento (%)"], row["Custo líquido (R$)"]),
                        xytext=(4, 5), textcoords="offset points", fontsize=8)
    ax.set_xlabel("Atendimento efetivamente obtido (%)")
    ax.set_ylabel("Custo líquido no horizonte (R$)")
    ax.set_title("Custo × qualidade de atendimento")
    ax.grid(alpha=.25); ax.legend()
    return fig

def render_dashboard(result):
    from .technical_ui import load_dispatch
    solved = result["summary"]
    if not {"solve_status", "config"}.issubset(solved):
        st.info("Resumo sem estado de solução; gráficos indisponíveis."); return
    solved = solved[solved["solve_status"] == "solved"]
    if solved.empty:
        st.warning("Nenhuma solução viável. Revise metas, teto contratual e carga local; não há despacho para exibir.")
        render_cost_comparison(result)
        return
    config = st.selectbox("Configuração dos gráficos técnicos", solved["config"].tolist())
    summary = solved[solved["config"] == config].iloc[0].to_dict()
    try:
        df = load_dispatch(result["output_dir"], summary, result.get("simulation_mode"))
    except (ValueError, OSError) as exc:
        st.error(str(exc)); return
    values = metrics(df)
    if values["grid_limit_exceedance_intervals"]:
        st.error("Foram detectados intervalos acima do limite da rede. Não utilize este resultado sem revisão.")
    if max(values["maximum_power_balance_error_kw"], values["maximum_pv_balance_error_kw"]) > 1e-4:
        st.warning("Resíduo de balanço de potência acima da tolerância de verificação (0,0001 kW).")
    st.caption(f"Horizonte: {values['horizon_h']:g} h; resolução: {df['dt_h'].iloc[0]:g} h. " + describe_policy(result.get("inputs", {}).get("service_policy")))
    year, quality, day, cost = st.tabs(["Ano / horizonte completo", "Qualidade de atendimento", "Detalhe diário", "Custo × atendimento"])
    with year:
        days = df["day_label"].drop_duplicates().tolist()
        selected = days
        if len(days)>1:
            first,last = st.select_slider("Janela cronológica", options=days, value=(days[0],days[-1]))
            selected = days[days.index(first):days.index(last)+1]
        show_figure(chronological_figure(df[df["day_label"].isin(selected)]), "curvas_cronologicas_"+config)
        st.caption("Linhas conectam os valores calculados; não representam dados de resolução superior. SOC não definido quando não há BESS.")
        with st.expander("Resumo mensal e curva de duração"):
            show_figure(overview_figure(df, summary), "resumo_horizonte_"+config)
    with quality:
        requested = values["ev_requested_kwh"]; served = values["ev_served_kwh"]
        pending = float(df["backlog_kwh"].iloc[-1])
        a,b,c,d,e = st.columns(5)
        a.metric("Atendimento por energia", f"{100*served/requested:.2f}%" if requested>1e-9 else "Não aplicável")
        b.metric("Recarga solicitada", f"{requested:,.1f} kWh")
        c.metric("Recarga expirada", f"{values['expired_unserved_kwh']:,.1f} kWh")
        d.metric("Pendente ao final", f"{pending:,.1f} kWh")
        e.metric("Corte total de recarga", f"{max(0., requested-served):,.1f} kWh")
        if "cohort_served_kwh" in df:
            st.caption("Atendimento agrupado pelo horário de chegada da energia, inclusive recarga transferida entre dias/meses. Pendências finais contam contra a meta.")
        else:
            st.warning("Modo legado: percentuais por período usam fluxos, não origem da demanda; podem ultrapassar 100% por transferência de energia em espera.")
        period = st.radio("Agrupar qualidade", ["Mensal", "Diária"], horizontal=True)
        q = quality_table(df, "monthly" if period=="Mensal" else "daily")
        st.dataframe(q, use_container_width=True)
        st.line_chart(q[["Atendimento (%)"]])
        st.download_button("Baixar qualidade CSV", q.to_csv().encode(), "qualidade_"+config+".csv")
        st.write("Períodos de menor atendimento")
        st.dataframe(q.sort_values("Atendimento (%)").head(10))
        st.caption("Espera em kWh·h não é tempo médio de fila de veículos. A carga local continua obrigatória.")
    with day:
        chosen = st.selectbox("Dia da simulação", df["day_label"].drop_duplicates().tolist())
        show_figure(dispatch_figure(df, summary, chosen), "despacho_diario_"+config)
    with cost:
        render_cost_comparison(result)
    st.download_button("Baixar séries técnicas completas (CSV)", df.to_csv(index=False).encode(), "series_tecnicas_"+config+".csv")

def render_cost_comparison(result):
        st.caption("Use a opção de comparar metas 95%, 98%, 99% e 100%, ou execute tetos distintos. Cada execução redimensiona FV/BESS. São pontos de comparação, não uma fronteira contínua. Custo líquido inclui receitas; não equivale ao investimento inicial.")
        inputs = result.get("inputs", {})
        keys = ("latitude", "longitude", "mode", "configs", "demand_scale", "local_scale", "threshold_kw", "bdgd_path")
        rows = []
        history = list(st.session_state.get("demand_comparison_history", []))
        if not any(previous is result for previous in history):
            history.append(result)
        for previous in history:
            pi = previous.get("inputs", {})
            if not all(pi.get(k)==inputs.get(k) for k in keys): continue
            policy = pi.get("service_policy") or {}
            for row in previous["summary"].to_dict("records"):
                rows.append({"Configuração": row["config"], "Política": describe_policy(pi.get("service_policy")),
                    "Estado": row.get("solve_status", "solved"),
                    "Meta": f"{100*policy.get('target', 1):g}%",
                    "Teto (kW)": pi.get("contracted_demand_cap_kw"), "Atendimento (%)": 100*row.get("served_ratio", float("nan")),
                    "Custo líquido (R$)": row["objective_value"], "Contrato (kW)": row.get("contracted_demand_kw"),
                    "FV (kWp)": row.get("pv_size_kw"), "BESS (kWh)": row.get("bess_e_kwh")})
        table = pd.DataFrame(rows)
        if not table.empty:
            st.dataframe(table, use_container_width=True)
            feasible = table[table["Estado"].fillna("solved") == "solved"].copy()
            for column in ("Atendimento (%)", "Custo líquido (R$)"):
                feasible[column] = pd.to_numeric(feasible[column], errors="coerce")
            feasible = feasible.dropna(subset=["Atendimento (%)", "Custo líquido (R$)"])
            if not feasible.empty:
                show_figure(cost_service_figure(feasible), "custo_atendimento")
                if len(feasible) == 1:
                    st.info("Há apenas um ponto comparável. Ative a comparação de metas para formar a curva.")
            st.download_button("Baixar custo × atendimento CSV", table.to_csv(index=False).encode(), "custo_atendimento.csv")
