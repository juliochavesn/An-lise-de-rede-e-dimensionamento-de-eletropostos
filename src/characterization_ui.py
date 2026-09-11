"""Tabelas e gráficos descritivos; nenhuma saída usada como limite de potência."""
from pathlib import Path

import pandas as pd
import streamlit as st


def render_characterization(result):
    data = result.get("characterization", {})
    st.subheader("Consumo, demandas e continuidade individuais")
    groups = data.get("monthly", [])
    if groups:
        if st.session_state.get("monthly_group", 0) not in range(len(groups)):
            st.session_state.pop("monthly_group", None)
        index = st.selectbox("Amostra mensal — distribuidora / tipo / circuito / referência / situação", range(len(groups)),
            format_func=lambda i: f"DIST {groups[i]['distributor_id']} · {groups[i]['kind']} · {groups[i]['circuit']} · {groups[i]['reference_date'] or 'data desconhecida'} · {groups[i]['registration_status']}", key="monthly_group")
        group = groups[index]
        st.caption(f"{group['consumer_count']} registros no recorte, não a totalidade do circuito. Grupos com datas, circuitos ou situações cadastrais diferentes não são misturados. AT é a situação ativa declarada.")
        months = pd.DataFrame(group["months"]).set_index("month").reindex(range(1, 13))
        months.index.name = "Mês"
        a, b = st.columns(2)
        with a:
            st.write("Energia mensal reportada na amostra (kWh)")
            st.line_chart(months[["energy_kwh_reported"]].rename(columns={"energy_kwh_reported": "Energia (kWh)"}))
        with b:
            st.write("Maior demanda individual reportada (kW)")
            st.line_chart(months[["demand_max_individual_kw"]].rename(columns={"demand_max_individual_kw": "Máximo individual (kW)"}))
        st.warning("Demanda individual não é demanda simultânea do alimentador, nem potência disponível. Consumo não é demanda prevista de veículos. Lacunas não foram preenchidas com zero.")
        contract = group["contracted_demand_max_individual_kw"]
        st.write("Maior demanda contratada individual reportada: " + (f"{contract:,.2f} kW" if contract is not None else "não informada"))
        if not group["annual_energy_complete"]:
            st.warning("Há energia mensal ausente/inválida em parte dos registros. Totais mostrados são apenas os valores reportados; compare também a quantidade de registros válidos por mês.")
        if months["positive_energy_zero_demand_count"].sum() > 0:
            st.warning("Há registros com energia positiva e demanda mensal declarada zero. O zero foi preservado e sinalizado; não é evidência de ausência de carga.")
        a, b = st.columns(2)
        with a:
            st.write("Maior DIC individual da amostra (horas)")
            st.line_chart(months[["dic_max_individual_h"]].rename(columns={"dic_max_individual_h": "DIC máximo (h)"}))
        with b:
            st.write("Maior FIC individual da amostra (interrupções)")
            st.line_chart(months[["fic_max_individual"]].rename(columns={"fic_max_individual": "FIC máximo"}))
        st.caption("DIC/FIC acima são máximos de consumidores retornados, não DEC/FEC e não previsão para o eletroposto. Em UCAT, energia exige ponta e fora ponta presentes; demandas por posto não são somadas.")
        labels = {"energy_kwh_reported": "Energia reportada (kWh)", "energy_reported_count": "UCs com energia válida",
            "energy_zero_count": "UCs com energia zero", "demand_max_individual_kw": "Demanda máxima individual (kW)",
            "demand_reported_count": "UCs com demanda válida", "demand_zero_count": "UCs com demanda zero",
            "demand_peak_max_individual_kw": "Demanda individual ponta (kW)", "demand_offpeak_max_individual_kw": "Demanda individual fora ponta (kW)",
            "dic_max_individual_h": "DIC máximo individual (h)", "dic_reported_count": "UCs com DIC válido",
            "fic_max_individual": "FIC máximo individual", "fic_reported_count": "UCs com FIC válido",
            "positive_energy_zero_demand_count": "UCs: energia positiva/demanda zero"}
        with st.expander("Tabela mensal e qualidade dos dados"):
            st.dataframe(months.rename(columns=labels), width="stretch")
    else:
        st.info("Sem consumidores retornados para caracterização mensal.")

    st.subheader("DEC/FEC dos conjuntos candidatos")
    continuity = data.get("continuity", {})
    st.caption(continuity.get("note", "Consulta indisponível."))
    st.warning(continuity.get("association", "Conjunto cadastrado não comprova o vínculo elétrico da coordenada."))
    if continuity.get("status") in ("error", "partial", "unavailable"):
        st.warning(f"Consulta de continuidade: {continuity.get('status')}. Conjuntos omitidos pelo limite de consulta: {continuity.get('omitted_set_count', 0)}.")
    rows = continuity.get("records", [])
    if rows:
        frame = pd.DataFrame(rows)
        frame["series"] = frame.apply(lambda r: f"{r['SigAgente']} · CNPJ {r['cnpj']} · conjunto {r['IdeConjUndConsumidoras']} · {r['DscConjUndConsumidoras']} · {r['year']}", axis=1)
        options = sorted(frame["series"].unique())
        if st.session_state.get("continuity_series", options[0]) not in options:
            st.session_state.pop("continuity_series", None)
        chosen = st.selectbox("Conjunto, agente e ano de continuidade", options, key="continuity_series")
        selected = frame[frame["series"] == chosen]
        monthly = selected[selected["period"].between(1, 12)][["period", "SigIndicador", "value"]].drop_duplicates()
        if monthly.duplicated(["period", "SigIndicador"]).any():
            st.warning("Há valores conflitantes para o mesmo indicador e mês. Gráfico suspenso; consulte os registros originais abaixo.")
        elif not monthly.empty:
            plot = monthly.pivot(index="period", columns="SigIndicador", values="value").reindex(range(1, 13))
            plot.index.name = "Mês"
            a, b = st.columns(2)
            for col, indicator, label in ((a, "DEC", "DEC — horas por UC"), (b, "FEC", "FEC — interrupções por UC")):
                if indicator in plot:
                    with col:
                        st.write(label)
                        st.line_chart(plot[[indicator]])
        st.caption("Meses ausentes permanecem vazios. Outros códigos de período ficam na tabela, sem serem tratados como meses. Indicadores não foram somados nem convertidos em autonomia de bateria.")
        with st.expander("Valores originais de continuidade"):
            st.dataframe(selected.drop(columns=["series"]).rename(columns={"cnpj": "CNPJ normalizado", "year": "Ano", "period": "Período", "value": "Valor numérico"}), hide_index=True, width="stretch")
    else:
        st.info("Sem DEC/FEC retornado para os conjuntos/anos consultados; não significa ausência de interrupções.")

    st.subheader("Tarifas de referência — não aplicadas à otimização")
    tariffs = data.get("tariffs", {})
    st.caption(f"Subgrupo: {tariffs.get('subgroup', '—')} · vigência consultada: {tariffs.get('on_date', '—')}")
    st.info(tariffs.get("note", "Consulta indisponível."))
    if tariffs.get("status") in ("error", "partial", "unavailable"):
        st.warning(f"Consulta tarifária: {tariffs.get('status')}. Resultados incompletos ou vínculo ausente não são tarifa zero.")
    rows = tariffs.get("records", [])
    if rows:
        frame = pd.DataFrame(rows)
        selected = frame.copy()
        for field, label in (("NumCNPJDistribuidora", "CNPJ da distribuidora candidata"),
                             ("DscModalidadeTarifaria", "Modalidade tarifária"), ("DscClasse", "Classe"),
                             ("DscSubClasse", "Subclasse"), ("DscDetalhe", "Detalhe de aplicação"),
                             ("SigAgenteAcessante", "Agente acessante")):
            selected[field] = selected[field].fillna("Não informado").astype(str)
            options = sorted(selected[field].unique())
            if st.session_state.get("tariff_" + field, options[0]) not in options:
                st.session_state.pop("tariff_" + field, None)
            default = options.index("Não se aplica") if "Não se aplica" in options else 0
            option = st.selectbox(label, options, index=default, key="tariff_" + field)
            selected = selected[selected[field] == option]
        labels = {"SigAgente": "Distribuidora", "NomPostoTarifario": "Posto tarifário", "te": "TE (R$/unidade)",
                  "tusd": "TUSD (R$/unidade)", "unit": "Unidade", "energy_te_plus_tusd_brl_kwh": "TE+TUSD energia (R$/kWh)",
                  "DatInicioVigencia": "Início da vigência", "DatFimVigencia": "Fim da vigência", "DscREH": "Resolução"}
        st.dataframe(selected[list(labels)].rename(columns=labels), hide_index=True, width="stretch")
        if selected.duplicated(["NomPostoTarifario", "DscUnidadeTerciaria"]).any():
            st.warning("Mais de uma linha vigente para o mesmo posto/unidade. Compare resoluções e condições; nenhuma linha foi escolhida ou somada automaticamente.")
        st.caption("Conversão para R$/kWh somente nas linhas em MWh. Linhas de demanda em kW permanecem separadas. Não somar postos nem misturar modalidades, classes ou resoluções. Valores não incluem necessariamente todos os componentes da fatura.")
    else:
        st.info("Nenhuma tarifa vigente retornada com os filtros e vínculos disponíveis. Ajuste o subgrupo/data na barra lateral e consulte novamente.")

    with st.expander("Fontes e filtros da caracterização ampliada"):
        st.json({key: {k: v for k, v in data.get(key, {}).items() if k != "records"} for key in ("continuity", "tariffs")})
    output = Path(result["output_dir"])
    for name, label in (("consumo_demanda_mensal.csv", "Baixar consumo/demanda mensal CSV"),
                        ("continuidade_conjuntos.csv", "Baixar continuidade CSV"), ("tarifas_referencia.csv", "Baixar tarifas CSV")):
        path = output / name
        if path.exists(): st.download_button(label, path.read_bytes(), name, "text/csv")
