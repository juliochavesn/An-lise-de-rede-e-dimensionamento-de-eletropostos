"""Camada OCM compartilhada pelos dois modos da interface."""
import html

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster

from .openchargemap import fetch_ocm


@st.cache_data(ttl=21600, max_entries=128, show_spinner=False)
def cached_ocm(lat, lon, radius):
    return fetch_ocm(lat, lon, radius)


def describe_connections(row):
    return "; ".join(f"{c['connector']} · {c['power_kw'] if c['power_kw'] is not None else '?'} kW · quantidade {c['quantity'] if c['quantity'] is not None else '?'} · {c['current']}" for c in row["connections"]) or "Não informados"


def add_ocm_layer(view, lat, lon, radius, include_uncertain=False):
    try:
        with st.spinner("Consultando Open Charge Map..."):
            data = cached_ocm(round(lat, 5), round(lon, 5), radius)
    except Exception as exc:
        st.warning(str(exc))
        return
    rows = [r for r in data["stations"] if include_uncertain or r["access"] == "Público declarado"]
    cluster = MarkerCluster().add_to(folium.FeatureGroup(name="Eletropostos — Open Charge Map").add_to(view))
    esc = lambda x: html.escape(str(x), quote=True)
    for r in rows:
        connectors = describe_connections(r)
        lines = [f"<b>{esc(r['name'])}</b>", esc(r["address"]),
                 *[f"{label}: {esc(r[key])}" for label, key in [("Operador", "operator"), ("Acesso", "usage"),
                    ("Estado cadastrado", "status"), ("Cobrança", "usage_cost"), ("Pontos declarados", "number_of_points"),
                    ("Última verificação", "verified_at"), ("Observações", "access_comments")]],
                 "Conectores: " + esc(connectors), "Fornecedor: " + esc(r["provider"]), esc(r["license"]),
                 f'<a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">Detalhes no Open Charge Map</a>',
                 "Estado cadastral, não disponibilidade em tempo real. Conectores não garantem recarga simultânea."]
        folium.Marker([r["latitude"], r["longitude"]], tooltip=esc(r["name"]),
                      popup=folium.Popup("<br>".join(lines), max_width=430),
                      icon=folium.Icon(color="gray" if r["operational"] is False else "blue", icon="plug", prefix="fa")).add_to(cluster)
    st.caption(f"Open Charge Map: {len(rows)} locais exibidos de {len(data['stations'])} cadastros não privados no raio de {radius} km · consulta {data['retrieved_at'][:10]}.")
    st.markdown("Fonte dos eletropostos: [Open Charge Map](https://openchargemap.org) e fornecedores identificados em cada marcador. Estado cadastral, não disponibilidade em tempo real.")
    if data["partial"]:
        st.warning("Consulta OCM atingiu 500 registros e pode estar incompleta. Reduza o raio.")
    if not rows:
        st.info("Nenhum cadastro OCM com o filtro selecionado. Experimente incluir acesso condicionado ou não informado.")
    with st.expander("Dados dos eletropostos — Open Charge Map"):
        if rows:
            st.dataframe(pd.DataFrame([{"Nome": r["name"], "Endereço": r["address"], "Operador": r["operator"],
                "Distância (m)": r["distance_m"], "Acesso": r["usage"], "Estado cadastrado": r["status"],
                "Conectores": describe_connections(r), "Pontos declarados": r["number_of_points"],
                "Cobrança": r["usage_cost"], "Verificação": r["verified_at"], "Fornecedor": r["provider"],
                "Licença": r["license"]} for r in rows]), hide_index=True, width="stretch")
