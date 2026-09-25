"""Camada combinada de eletropostos Google Places e Open Charge Map."""

import html

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster

from .google_evcs import fetch_google_evcs, merge_station_sources
from .openchargemap import fetch_ocm


@st.cache_data(ttl=21600, max_entries=128, show_spinner=False)
def cached_ocm(lat, lon, radius):
    return fetch_ocm(lat, lon, radius)


@st.cache_data(ttl=21600, max_entries=128, show_spinner=False)
def cached_google_evcs(lat, lon, radius):
    return fetch_google_evcs(lat, lon, radius)


def describe_connections(row):
    return "; ".join(
        f"{c['connector']} · {c['power_kw'] if c['power_kw'] is not None else '?'} kW "
        f"· quantidade {c['quantity'] if c['quantity'] is not None else '?'} · {c['current']}"
        for c in row["connections"]
    ) or "Não informados"


def _maximum_power(row):
    if row.get("maximum_power_kw") is not None:
        return float(row["maximum_power_kw"])
    powers = [
        float(item["power_kw"]) for item in row.get("connections", [])
        if item.get("power_kw") is not None
    ]
    return max(powers) if powers else None


def add_ocm_layer(view, lat, lon, radius, include_uncertain=False):
    """Mantém o nome público legado, agora combinando as duas fontes."""
    ocm_data = {"stations": [], "partial": False, "retrieved_at": "indisponível"}
    google_data = {"stations": [], "database_updated_at": "não informada"}
    errors = []
    try:
        with st.spinner("Consultando Open Charge Map..."):
            ocm_data = cached_ocm(round(lat, 5), round(lon, 5), radius)
    except Exception as exc:
        errors.append(f"Open Charge Map: {exc}")
    try:
        with st.spinner("Consultando inventário Google de eletropostos..."):
            google_data = cached_google_evcs(round(lat, 5), round(lon, 5), radius)
    except Exception as exc:
        errors.append(f"Base Google: {exc}")

    combined, duplicate_count = merge_station_sources(
        ocm_data.get("stations", []), google_data.get("stations", [])
    )
    rows = [
        row for row in combined
        if include_uncertain or row["access"] == "Público declarado"
    ]
    cluster = MarkerCluster().add_to(
        folium.FeatureGroup(name="Eletropostos — Google + Open Charge Map").add_to(view)
    )
    esc = lambda value: html.escape(str(value), quote=True)
    for row in rows:
        connectors = describe_connections(row)
        sources = " + ".join(row.get("sources", [row.get("provider", "Fonte não informada")]))
        max_power = _maximum_power(row)
        lines = [
            f"<b>{esc(row['name'])}</b>", esc(row["address"]),
            *[
                f"{label}: {esc(row[key])}"
                for label, key in [
                    ("Operador", "operator"), ("Acesso", "usage"),
                    ("Estado cadastrado", "status"), ("Cobrança", "usage_cost"),
                    ("Pontos/tomadas declarados", "number_of_points"),
                    ("Última verificação", "verified_at"),
                    ("Observações", "access_comments"),
                ]
            ],
            "Potência máxima por conector: "
            + esc(f"{max_power:g} kW" if max_power is not None else "Não informada"),
            "Conectores: " + esc(connectors),
            "Fontes combinadas: " + esc(sources),
            "Condições da fonte: " + esc(row.get("license", "Não informadas")),
            f'<a href="{esc(row["url"])}" target="_blank" rel="noopener noreferrer">Abrir registro da fonte</a>',
            "Estado cadastral, não disponibilidade em tempo real. Conectores não garantem recarga simultânea.",
        ]
        color = "gray" if row["operational"] is False else (
            "green" if len(row.get("sources", [])) > 1 else "blue"
        )
        folium.Marker(
            [row["latitude"], row["longitude"]], tooltip=esc(row["name"]),
            popup=folium.Popup("<br>".join(lines), max_width=450),
            icon=folium.Icon(color=color, icon="plug", prefix="fa"),
        ).add_to(cluster)

    st.caption(
        f"Eletropostos: {len(rows)} locais exibidos · OCM {len(ocm_data.get('stations', []))} · "
        f"Google {len(google_data.get('stations', []))} · "
        f"{duplicate_count} coincidência(s) entre fontes fundidas."
    )
    st.markdown(
        "Fontes: [Open Charge Map](https://openchargemap.org) e inventário Google Places "
        "fornecido por Daniel Guimarães. Dados cadastrais; confirme acesso, potência e disponibilidade com o operador."
    )
    for error in errors:
        st.warning(error)
    if ocm_data.get("partial"):
        st.warning("Consulta OCM atingiu 500 registros e pode estar incompleta. Reduza o raio.")
    if not rows:
        st.info("Nenhum cadastro com o filtro selecionado. Inclua acesso condicionado ou não informado.")
    with st.expander("Dados dos eletropostos — fontes combinadas"):
        if rows:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Nome": row["name"], "Endereço": row["address"],
                        "Operador": row["operator"], "Distância (m)": row["distance_m"],
                        "Acesso": row["usage"], "Estado cadastrado": row["status"],
                        "Conectores": describe_connections(row),
                        "Pontos/tomadas": row["number_of_points"],
                        "Potência máxima (kW)": _maximum_power(row),
                        "Cobrança": row["usage_cost"], "Verificação": row["verified_at"],
                        "Fontes": " + ".join(row.get("sources", [])),
                    }
                    for row in rows
                ]),
                hide_index=True, width="stretch",
            )
