"""Camada combinada de eletropostos Google Places e Open Charge Map."""

import html

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from branca.element import Element

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


def _station_symbol(row):
    """Retorna cor, diâmetro e descrição sem inferir potência ausente."""
    power = _maximum_power(row)
    if row.get("operational") is False:
        color, category = "#64748b", "Fora de operação"
    elif power is None:
        color, category = "#2563eb", "Potência não informada"
    else:
        color, category = "#16a34a", "Potência informada"

    if power is None:
        size = 18
    elif power <= 22:
        size = 20
    elif power < 100:
        size = 24
    elif power < 200:
        size = 28
    else:
        size = 32
    return color, size, category


def _add_station_legend(view):
    legend = """
    <style>
      .evcs-marker { transition: transform .12s ease, filter .12s ease; }
      .evcs-marker:hover { transform: scale(1.18); filter: drop-shadow(0 0 4px #facc15); }
      .evcs-legend { position: fixed; z-index: 9998; right: 18px; bottom: 28px;
        width: 218px; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 10px;
        background: rgba(255,255,255,.96); color: #0f172a; font: 12px/1.35 Arial, sans-serif;
        box-shadow: 0 3px 12px rgba(15,23,42,.18); }
      .evcs-legend b { display:block; margin-bottom:6px; font-size:13px; }
      .evcs-dot { display:inline-block; width:12px; height:12px; border-radius:50%;
        margin-right:6px; vertical-align:-1px; }
      .evcs-ring { border:3px solid #f59e0b; box-sizing:border-box; }
      .evcs-sizes { margin-top:5px; color:#334155; }
    </style>
    <div class="evcs-legend">
      <b>Eletropostos</b>
      <div><span class="evcs-dot" style="background:#16a34a"></span>Potência informada</div>
      <div><span class="evcs-dot" style="background:#2563eb"></span>Potência não informada</div>
      <div><span class="evcs-dot" style="background:#64748b"></span>Fora de operação</div>
      <div><span class="evcs-dot evcs-ring" style="background:#fff"></span>Confirmado nas duas fontes</div>
      <div class="evcs-sizes">Tamanho por potência: ≤22 · 23–99 · 100–199 · ≥200 kW</div>
      <div class="evcs-sizes">O realce ao passar o mouse serve apenas para seleção.</div>
    </div>
    """
    view.get_root().html.add_child(Element(legend))


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
    _add_station_legend(view)
    esc = lambda value: html.escape(str(value), quote=True)
    for row in rows:
        connectors = describe_connections(row)
        sources = " + ".join(row.get("sources", [row.get("provider", "Fonte não informada")]))
        max_power = _maximum_power(row)
        color, marker_size, power_category = _station_symbol(row)
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
            "Classe visual: " + esc(power_category),
            "Conectores: " + esc(connectors),
            "Fontes combinadas: " + esc(sources),
            "Condições da fonte: " + esc(row.get("license", "Não informadas")),
            f'<a href="{esc(row["url"])}" target="_blank" rel="noopener noreferrer">Abrir registro da fonte</a>',
            "Estado cadastral, não disponibilidade em tempo real. Conectores não garantem recarga simultânea.",
        ]
        dual_source = len(row.get("sources", [])) > 1
        border = "#f59e0b" if dual_source else "#ffffff"
        ring = "0 0 0 2px #f59e0b, 0 2px 6px rgba(15,23,42,.45)" if dual_source \
            else "0 2px 6px rgba(15,23,42,.45)"
        icon_html = (
            f'<div class="evcs-marker" style="width:{marker_size}px;height:{marker_size}px;'
            f'border-radius:50%;background:{color};border:2px solid {border};box-sizing:border-box;'
            f'box-shadow:{ring};display:flex;align-items:center;justify-content:center;'
            f'color:white;font-size:{max(10, marker_size // 2)}px;font-weight:700">&#9889;</div>'
        )
        folium.Marker(
            [row["latitude"], row["longitude"]], tooltip=esc(row["name"]),
            popup=folium.Popup("<br>".join(lines), max_width=450),
            icon=folium.DivIcon(
                html=icon_html,
                icon_size=(marker_size, marker_size),
                icon_anchor=(marker_size // 2, marker_size // 2),
                class_name="",
            ),
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
