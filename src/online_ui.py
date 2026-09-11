"""Interface da triagem por APIs, independente de cobertura/arquivos GDB locais."""
import html
import json
import math
from datetime import date
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from .config import PV_LOCATION
from .ui_service import analyze_preliminary
from .ocm_ui import add_ocm_layer
from .characterization_ui import render_characterization


def render_online():
    for key in ("latitude", "longitude"):
        st.session_state.setdefault(key, float(PV_LOCATION[key]))

    def select(lat, lon):
        st.session_state.latitude, st.session_state.longitude = lat, lon
        st.session_state.pop("preliminary_result", None)
        st.session_state.online_revision = st.session_state.get("online_revision", 0) + 1
        st.session_state.online_sync = True

    def apply():
        try:
            lat = float(st.session_state.online_lat.strip().replace(",", "."))
            lon = float(st.session_state.online_lon.strip().replace(",", "."))
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-34 <= lat <= 6 and -74 <= lon <= -34):
                raise ValueError
            select(lat, lon)
            st.session_state.pop("online_warning", None)
        except ValueError:
            st.session_state.online_warning = "Informe coordenadas válidas no enquadramento brasileiro."

    if st.session_state.pop("online_sync", False) or "online_lat" not in st.session_state:
        st.session_state.online_lat = f"{st.session_state.latitude:.7f}"
        st.session_state.online_lon = f"{st.session_state.longitude:.7f}"
    with st.sidebar:
        st.info("Modo online: não abre nem baixa BDGD. Para baixar uma base e calcular capacidade, selecione ‘Detalhada — BDGD local’ acima.")
        with st.form("online_coordinates"):
            st.text_input("Latitude", key="online_lat")
            st.text_input("Longitude", key="online_lon")
            st.form_submit_button("Aplicar coordenadas", on_click=apply)
        if st.session_state.get("online_warning"):
            st.warning(st.session_state.online_warning)
        radius = st.slider("Raio da consulta preliminar (km)", 0.5, 5.0, 1.5, 0.5)
        tariff_subgroup = st.selectbox("Subgrupo para consulta tarifária", ["A4", "A1", "A2", "A3", "A3a", "AS", "B1", "B2", "B3", "B4"])
        tariff_date = st.date_input("Data de referência das tarifas", value=date.today())
        st.caption("A4 é apenas o filtro inicial de consulta, não enquadramento confirmado do eletroposto. Não altera tarifas do otimizador.")
        refresh = st.checkbox("Atualizar APIs sem usar cache", value=False)
        st.caption("Consultas em cache por até 6 h; catálogo/esquema por até 24 h quando aplicável. Coordenadas e raio são enviados aos provedores públicos.")
        show_stations = st.toggle("Exibir eletropostos existentes", value=False)
        include_uncertain, station_radius = False, 10
        if show_stations:
            station_radius = st.slider("Raio dos eletropostos (km)", 1, 25, 10)
            include_uncertain = st.checkbox("Incluir acesso condicionado ou não informado", value=False)

    lat, lon = st.session_state.latitude, st.session_state.longitude
    signature = (lat, lon, radius, tariff_subgroup, tariff_date.isoformat())
    if st.session_state.get("online_signature") != signature:
        st.session_state.pop("preliminary_result", None)
        st.session_state.online_signature = signature
    st.markdown("""
    <div class="section-eyebrow">Triagem nacional</div>
    <div class="section-title">Análise preliminar por APIs públicas</div>
    <div class="section-copy">Caracterize o entorno antes de carregar uma BDGD detalhada. Esta etapa orienta a investigação, mas não declara potência disponível.</div>
    """, unsafe_allow_html=True)
    st.caption("Consulta nacional de consumidores PJ em MT/AT. Geometria de rede apenas onde o serviço regional integrado a publica; isso não é cobertura elétrica nacional completa.")
    st.code(f"{lat:.7f}, {lon:.7f}")
    if st.button("Consultar APIs neste ponto", type="primary"):
        st.session_state.pop("preliminary_result", None)
        with st.spinner("Consultando fontes públicas e filtrando o entorno; cada fonte pode levar alguns segundos..."):
            try:
                st.session_state.preliminary_result = analyze_preliminary(lat, lon, radius, refresh, tariff_subgroup, tariff_date.isoformat())
                st.session_state.online_revision = st.session_state.get("online_revision", 0) + 1
            except Exception as exc:
                st.error(f"Consulta não concluída: {exc}")
    result = st.session_state.get("preliminary_result")
    view = folium.Map(location=[lat, lon], zoom_start=14, control_scale=True,
                      max_bounds=True, min_lat=-34, max_lat=6, min_lon=-74, max_lon=-34)
    folium.Circle([lat, lon], radius=radius * 1000, color="#64748b", fill=False,
                  tooltip="Raio da consulta preliminar").add_to(view)
    folium.Marker([lat, lon], tooltip="Ponto em análise", icon=folium.Icon(color="green")).add_to(view)
    if result:
        group = folium.FeatureGroup(name="Consumidores PJ — não são trechos de rede")
        for row in result["consumers"]:
            label = f"{row['kind']} · DIST {row.get('DIST', '—')} · circuito candidato {row.get('CTMT') or row.get('CTAT') or '—'} · {row['distance_m']:.0f} m"
            folium.CircleMarker([row["latitude"], row["longitude"]], radius=4, color="#d97706",
                                fill=True, tooltip=html.escape(label)).add_to(group)
        group.add_to(view)
        if result["network"]["features"]:
            # No external property is rendered as HTML.
            folium.GeoJson({"type": "FeatureCollection", "features": result["network"]["features"]},
                           name="Rede MT via SIGEL — AME_2023",
                           style_function=lambda _: {"color": "#2563eb", "weight": 2}).add_to(view)
    if show_stations:
        add_ocm_layer(view, lat, lon, station_radius, include_uncertain)
    folium.LayerControl().add_to(view)
    event = st_folium(view, height=560, use_container_width=True,
                      key=f"online_map_{st.session_state.get('online_revision', 0)}", returned_objects=["last_clicked"])
    click = event.get("last_clicked") if event else None
    if click and (round(click["lat"], 7), round(click["lng"], 7)) != (round(lat, 7), round(lon, 7)):
        if -34 <= click["lat"] <= 6 and -74 <= click["lng"] <= -34:
            select(float(click["lat"]), float(click["lng"]))
            st.rerun()
    st.info("Capacidade disponível: não determinada pelas APIs integradas. Para calcular capacidade residual e simular, utilize o modo detalhado com a BDGD correspondente.")
    if result:
        st.header("Caracterização do entorno — não é parecer de conexão")
        st.caption(f"Análise: {result['analyzed_at']} · raio: {radius} km · situação: {'parcial' if result['status'] == 'partial' else 'consultas concluídas'}")
        for error in result["errors"]:
            st.warning(error)
        for source in result["consumer_sources"]:
            if source["status"] == "partial":
                st.warning(f"{source['kind']}: limite de consulta atingido ({source['scanned']}/{source['cell_total']} registros nas células). Amostra incompleta; o mais próximo pode não ter sido retornado. Reduza o raio.")
        records = result["consumers"]
        left, right = st.columns(2)
        left.metric("Consumidores PJ retornados no raio", len(records))
        right.metric("Menor distância entre UCs retornadas", f"{records[0]['distance_m']:.1f} m" if records else "Não determinada")
        if records:
            table = pd.DataFrame(records)
            columns = {"kind": "Tipo de UC", "DIST": "Código da distribuidora", "CTMT": "Alimentador candidato MT",
                       "CTAT": "Circuito candidato AT", "SUB": "Subestação candidata", "CONJ": "Conjunto",
                       "DATA_BASE": "Data-base informada", "reference_date": "Referência interpretada", "reference_origin": "Origem da referência", "distance_m": "Distância à UC (m)"}
            st.dataframe(table[[c for c in columns if c in table]].rename(columns=columns), hide_index=True, use_container_width=True)
            st.caption("Distância a consumidor, não distância à rede. Campos vazios são dados não fornecidos; códigos de tensão não foram convertidos em kV sem tabela de domínio.")
        else:
            st.warning("Nenhum registro PJ retornado neste raio. Isso não indica falta de rede nem capacidade zero.")
        st.write(result["network"]["note"])
        if result.get("characterization"):
            render_characterization(result)
        if result["network"].get("status") == "partial":
            st.warning("O serviço SIGEL atingiu o limite de 1.000 trechos. A camada exibida é parcial; reduza o raio. Não foi calculada distância ao trecho mais próximo nem capacidade com esse recorte.")
        with st.expander("Limitações e dados necessários para aprofundar", expanded=True):
            for item in result["limitations"]:
                st.write("• " + item)
        with st.expander("Fontes, paginação e datas de coleta"):
            st.json({"catalog": result.get("catalog_source"), "consumers": result["consumer_sources"], "network": result["network"]["sources"]})
        st.download_button("Baixar snapshot JSON das APIs", json.dumps(result, ensure_ascii=False, indent=2).encode(), "analise_preliminar.json", "application/json")
        report = Path(result["output_dir"]) / "analise_preliminar.md"
        if report.exists():
            st.download_button("Baixar relatório preliminar", report.read_bytes(), report.name)
        st.caption(f"Arquivos desta análise: {result['output_dir']}")
    st.markdown("""
    <div class="footer-card">
      <span><strong>Júlio Cesar C. Nunes</strong> · FEEC/UNICAMP</span>
      <span><a href="mailto:j298971@dac.unicamp.br">j298971@dac.unicamp.br</a> · Ferramenta de apoio ao planejamento</span>
    </div>
    """, unsafe_allow_html=True)
