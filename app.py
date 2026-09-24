"""Interface gráfica local para análise locacional e simulação do eletroposto."""

from __future__ import annotations

import json
import math
from pathlib import Path

import altair as alt
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.config import GRID_NETWORK, PV_LOCATION, PV_SYSTEM, SCENARIO_ANNUAL
from src.grid_map import load_bdgd_coverage, load_network_window, point_is_covered
from src.ui_service import analyze_point, simulate_point
from src.national_bdgd import fetch_catalog, atomic_json, install_dataset, installed_datasets, api_json
from src.online_ui import render_online
from src.ocm_ui import add_ocm_layer
from src.technical_ui import render_technical_panel
from src.service_policy import describe_policy
from src.cloud_bdgd import CLOUD_DATASETS, load_cloud_coverage, prepare_cloud_point
from src.pnl_routes import add_pnl_layer, gtype_label, load_pnl_window
from src.freight_energy import FreightAssumptions, estimate_freight_charging, scenario_table
from access_counter import register_access, render_access_footer


st.set_page_config(
    page_title="Atlas Eletropostos | FEEC/UNICAMP",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)
access_metrics = register_access(st)

st.markdown("""
<style>
    :root {
        --brand-navy: #071b33;
        --brand-blue: #0b63ce;
        --brand-cyan: #19b7c9;
        --brand-mint: #20c997;
        --surface: #f6f9fc;
        --line: #dbe6f1;
    }
    .stApp {
        background:
            radial-gradient(circle at 88% 2%, rgba(25,183,201,.10), transparent 24rem),
            linear-gradient(180deg, #ffffff 0%, var(--surface) 100%);
    }
    [data-testid="stHeader"] { background: rgba(255,255,255,.82); backdrop-filter: blur(14px); }
    [data-testid="stSidebar"] { border-right: 1px solid var(--line); color:#243b53; }
    [data-testid="stSidebar"] > div { background: linear-gradient(180deg,#f8fbff 0%,#eef5fb 100%); }
    [data-testid="stSidebar"] p { color:#243b53 !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
    [data-testid="stSidebar"] [data-testid="stRadioOption"] p,
    [data-testid="stSidebar"] [data-testid="stCheckbox"] p,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary p {
        color:#243b53 !important;
    }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { font-weight:650; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:#52657a !important; }
    [data-testid="stSidebar"] button p,
    [data-testid="stSidebar"] [data-baseweb="select"] * {
        color:#f8fafc !important;
    }
    [data-testid="stAlertContentSuccess"] p { color:#166534 !important; }
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] p {
        color:#243b53 !important;
    }
    [data-testid="stMetricLabel"] p { color:#243b53 !important; }
    .logistics-heading {
        color:#0b2340 !important;
        font-size:1.18rem;
        font-weight:750;
        line-height:1.35;
        margin:.65rem 0 .35rem 0;
    }
    .logistics-copy {
        color:#334e68 !important;
    }
    [data-testid="stExpander"] details,
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        background:#ffffff !important;
    }
    .block-container { max-width: 1480px; padding-top: 1.4rem; padding-bottom: 3rem; }
    .hero {
        position: relative; overflow: hidden; padding: 2.25rem 2.5rem; margin: .25rem 0 1.7rem;
        border-radius: 24px; color: white;
        background: linear-gradient(120deg, #061a31 0%, #0a3970 55%, #087e91 100%);
        box-shadow: 0 18px 55px rgba(7,27,51,.18);
    }
    .hero:after { content:""; position:absolute; width:290px; height:290px; right:-70px; top:-130px;
        border:1px solid rgba(255,255,255,.25); border-radius:50%; box-shadow:0 0 0 45px rgba(255,255,255,.035),0 0 0 90px rgba(255,255,255,.025); }
    .hero-kicker { color:#70e1ea; font-size:.78rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .hero h1 { color:white; font-size:clamp(2rem,4vw,3.6rem); line-height:1.02; letter-spacing:-.045em; margin:.45rem 0 .8rem; max-width:850px; }
    .hero p { color:#d9edf5; font-size:1.08rem; line-height:1.6; max-width:810px; margin:0; }
    .hero-tags { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.25rem; }
    .hero-tag { padding:.38rem .75rem; border:1px solid rgba(255,255,255,.22); border-radius:999px; background:rgba(255,255,255,.09); font-size:.82rem; }
    .section-eyebrow { color:var(--brand-blue); font-size:.75rem; font-weight:800; letter-spacing:.11em; text-transform:uppercase; margin-bottom:.15rem; }
    .section-title { color:var(--brand-navy); font-size:1.65rem; font-weight:760; letter-spacing:-.025em; margin-bottom:.25rem; }
    .section-copy { color:#52657a; margin-bottom:1.2rem; }
    div[data-testid="stMetric"] { background:rgba(255,255,255,.9); border:1px solid var(--line); border-radius:16px; padding:1rem 1.1rem; box-shadow:0 7px 24px rgba(25,55,88,.06); }
    div[data-testid="stMetricValue"] { color:var(--brand-navy); }
    div[data-testid="stExpander"], div[data-testid="stDataFrame"] { border-color:var(--line); border-radius:14px; overflow:hidden; }
    .stButton > button, .stDownloadButton > button, .stLinkButton > a { border-radius:12px; min-height:2.8rem; font-weight:700; transition:transform .15s ease, box-shadow .15s ease; }
    .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover { transform:translateY(-1px); box-shadow:0 8px 20px rgba(11,99,206,.14); }
    [data-testid="stForm"] { background:rgba(255,255,255,.6); border:1px solid var(--line); border-radius:16px; padding:1rem; }
    .footer-card { margin-top:2.5rem; padding:1.2rem 1.4rem; border-top:1px solid var(--line); color:#52657a; display:flex; justify-content:space-between; gap:1rem; }
    @media (max-width: 768px) {
        .block-container { padding: .65rem .85rem 2rem; }
        .hero { padding:1.45rem 1.25rem; border-radius:18px; margin-top:.15rem; }
        .hero h1 { font-size:2.05rem; max-width:92%; }
        .hero p { font-size:.95rem; }
        .hero-tag { font-size:.72rem; }
        .section-title { font-size:1.4rem; }
        div[data-testid="stHorizontalBlock"] { gap:.75rem; }
        div[data-testid="stMetric"] { padding:.8rem; }
        iframe[title="streamlit_folium.st_folium"] { height:430px !important; }
        .footer-card { flex-direction:column; }
        [data-testid="stDataFrame"] { max-width:calc(100vw - 1.7rem); overflow-x:auto; }
    }
</style>
<div class="hero">
  <div class="hero-kicker">Pesquisa aplicada · FEEC/UNICAMP</div>
  <h1>Inteligência de rede para eletropostos</h1>
  <p>Da escolha do ponto ao dimensionamento técnico-econômico: conectamos dados da distribuição, geração solar, armazenamento e recarga inteligente em uma única análise.</p>
  <div class="hero-tags"><span class="hero-tag">BDGD 2025</span><span class="hero-tag">Otimização anual</span><span class="hero-tag">Solar + BESS</span><span class="hero-tag">Qualidade de atendimento</span></div>
</div>
""", unsafe_allow_html=True)

analysis_mode = st.sidebar.radio(
    "Modo de análise",
    ["Preliminar — APIs online", "Detalhada — BDGD em nuvem", "Detalhada — BDGD local"],
    key="analysis_mode",
)
st.sidebar.caption("① Escolha a fonte  ·  ② Selecione o ponto  ·  ③ Analise e simule")
if st.session_state.get("previous_analysis_mode") != analysis_mode:
    for key in ("network_result", "simulation_result", "preliminary_result", "processed_click"):
        st.session_state.pop(key, None)
    st.session_state.coordinate_sync = True
    st.session_state.online_sync = True
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
    st.session_state.previous_analysis_mode = analysis_mode
if analysis_mode == "Preliminar — APIs online":
    render_online()
    render_access_footer(st, access_metrics)
    st.stop()

national_dir = Path(GRID_NETWORK["bdgd_path"]).parent / "Nacional"
network_config = dict(GRID_NETWORK)


@st.cache_data(show_spinner=False, ttl=86400)
def cached_item_info(item_id):
    return api_json(f"/content/items/{item_id}")


with st.sidebar:
    st.header("Bases e abrangência")
    cloud_mode = analysis_mode == "Detalhada — BDGD em nuvem"
    national_mode = st.toggle("Explorar Brasil", value=False, disabled=cloud_mode)
    cloud_dataset = None
    if cloud_mode:
        cloud_name = st.selectbox("BDGD tratada em nuvem", list(CLOUD_DATASETS), key="cloud_bdgd_source")
        cloud_dataset = CLOUD_DATASETS[cloud_name]
        source_path = f"cloud:{cloud_name}"
        st.caption("Piloto 2025: CPFL Paulista e Enel SP. A interface baixa somente o índice, os dados globais e o bloco do alimentador próximo; os arquivos ficam em cache.")
    else:
        sources = [(str(GRID_NETWORK["bdgd_path"]), "CPFL Paulista — base original")]
        sources += installed_datasets(national_dir)
        names = dict(sources)
        source_path = st.selectbox("BDGD carregada para cálculo", list(names), format_func=names.get, key="bdgd_source")
        network_config["bdgd_path"] = source_path
    if not cloud_mode and source_path != str(GRID_NETWORK["bdgd_path"]):
        st.warning("A base selecionada alimenta a análise da rede. As tarifas continuam sendo as configuradas no projeto; revise-as antes de comparar custos entre distribuidoras.")
    with st.expander("Catálogo nacional ANEEL / API", expanded=False):
        st.caption("Consulta nacional; download por distribuidora. Não baixa todo o Brasil de uma vez. Datas e cobertura variam entre bases.")
        catalog_path = national_dir / "catalog.json"
        if st.button("Atualizar catálogo ANEEL"):
            try:
                with st.spinner("Consultando o catálogo oficial..."):
                    atomic_json(catalog_path, fetch_catalog())
            except Exception as exc:
                st.error(f"Catálogo não atualizado: {exc}")
        catalog = None
        if catalog_path.exists():
            try:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                st.warning("Catálogo local inválido; atualize-o pela API.")
        if catalog:
            st.caption(f"{catalog['distributor_count']} distribuidoras · consulta: {catalog['retrieved_at'][:10]}")
            records = {item["id"]: item for item in catalog["items"]}
            chosen = st.selectbox("Distribuidora para baixar", list(records), format_func=lambda key:
                                  f"{records[key]['distributor_name']} · {records[key]['reference_date']}")
            item = records[chosen]
            try:
                info = cached_item_info(chosen)
                size = int(info.get("size", 0))
                st.caption(f"{item['title']} · {size/1e6:,.1f} MB comprimidos; extração requer espaço adicional.")
            except Exception:
                size = 0
                st.warning("Não foi possível consultar o tamanho do arquivo. Atualize a página para tentar novamente.")
            st.link_button("Ver registro e condições na ANEEL", f"https://www.arcgis.com/home/item.html?id={chosen}")
            if st.button("Baixar BDGD selecionada", disabled=not 0 < size <= 6_000_000_000):
                try:
                    bar = st.progress(0.0, text="Baixando a base selecionada...")
                    path, metadata = install_dataset(chosen, national_dir, progress=bar.progress)
                    st.success("Base salva. Selecione-a em ‘BDGD carregada para cálculo’.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Base não instalada: {exc}")
        else:
            st.info("Atualize o catálogo para consultar as distribuidoras disponíveis.")

for key, value in {"latitude": PV_LOCATION["latitude"], "longitude": PV_LOCATION["longitude"]}.items():
    st.session_state.setdefault(key, float(value))


@st.cache_resource(show_spinner=False)
def cached_coverage(source_path):
    if str(source_path).startswith("cloud:"):
        return load_cloud_coverage(CLOUD_DATASETS[str(source_path)[6:]])
    return load_bdgd_coverage(dict(GRID_NETWORK, bdgd_path=source_path))


@st.cache_resource(show_spinner=False)
def cached_cloud_point(source_path: str, latitude: float, longitude: float, context_radius_km: float):
    return prepare_cloud_point(CLOUD_DATASETS[source_path[6:]], latitude, longitude,
                               float(GRID_NETWORK.get("max_search_radius_km", 10.0)), context_radius_km)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_map(latitude: float, longitude: float, radius_km: float, source_path):
    return load_network_window(
        {"latitude": latitude, "longitude": longitude}, dict(GRID_NETWORK, bdgd_path=source_path), radius_km
    )


@st.cache_data(show_spinner=False, ttl=86400)
def cached_pnl_window(latitude: float, longitude: float, radius_km: float,
                      schema_version: str = "pnl-dictionary-v1"):
    del schema_version
    return load_pnl_window(latitude, longitude, radius_km)


try:
    with st.spinner("Preparando a área da BDGD carregada..."):
        coverage = cached_coverage(source_path)
except Exception as exc:
    coverage = None
    st.error(f"Não foi possível abrir a BDGD selecionada: {exc}")

if st.session_state.get("previous_bdgd_source", source_path) != source_path:
    for key in ("network_result", "simulation_result", "processed_click"):
        st.session_state.pop(key, None)
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
st.session_state.previous_bdgd_source = source_path


def select_point(latitude, longitude):
    st.session_state.latitude = float(latitude)
    st.session_state.longitude = float(longitude)
    st.session_state.coordinate_sync = True
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
    for key in ("network_result", "simulation_result", "coordinate_warning", "processed_click"):
        st.session_state.pop(key, None)


def apply_coordinates():
    try:
        latitude = float(st.session_state.latitude_text.strip().replace(",", "."))
        longitude = float(st.session_state.longitude_text.strip().replace(",", "."))
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except ValueError:
        st.session_state.coordinate_warning = "Informe latitude e longitude válidas; vírgula ou ponto decimal são aceitos."
        return
    if national_mode and not (-34 <= latitude <= 6 and -74 <= longitude <= -34):
        st.session_state.coordinate_warning = "Coordenadas fora do enquadramento geográfico do Brasil."
        return
    if not national_mode and (coverage is None or not point_is_covered(latitude, longitude, coverage)):
        st.session_state.coordinate_warning = "As coordenadas estão fora da BDGD carregada. Ative ‘Explorar Brasil’ para navegar em outras regiões."
        return
    select_point(latitude, longitude)


if st.session_state.pop("coordinate_sync", False) or "latitude_text" not in st.session_state:
    st.session_state.latitude_text = f"{st.session_state.latitude:.7f}"
    st.session_state.longitude_text = f"{st.session_state.longitude:.7f}"

with st.sidebar:
    st.header("Ponto e cenário")
    if coverage is not None and st.button("Centralizar na área carregada"):
        point = coverage["geometry"].representative_point()
        select_point(point.y, point.x)
        st.rerun()
    with st.form("coordinates"):
        st.text_input("Latitude", key="latitude_text")
        st.text_input("Longitude", key="longitude_text")
        st.form_submit_button("Aplicar coordenadas", on_click=apply_coordinates)
    if st.session_state.get("coordinate_warning"):
        st.warning(st.session_state.coordinate_warning)
    radius_km = st.slider("Raio exibido da rede (km)", 0.5, 5.0, 1.5, 0.5)
    show_substations = st.toggle("Exibir subestações", value=True,
        help="Mostra as subestações cadastradas na BDGD dentro do raio exibido da rede.")
    show_stations = st.toggle("Exibir eletropostos existentes", value=False)
    include_uncertain = False
    station_radius = 10.0
    if show_stations:
        station_radius = st.slider("Raio dos eletropostos (km)", 1, 25, 10)
        include_uncertain = st.checkbox("Incluir acesso condicionado ou não informado", value=False)
        st.caption("Fonte: Open Charge Map. Cache de 6 h; estado cadastral, não ocupação em tempo real.")
    show_pnl = st.toggle(
        "Exibir rotas de transporte de cargas (PNL)", value=False,
        help="Camada logística independente da BDGD. O primeiro acesso baixa e prepara o pacote mantido no Google Drive.",
    )
    pnl_radius_km, pnl_display_mode = 15.0, "Saturação"
    use_freight_demand = False
    freight_scenario = "P50"
    freight_assumptions = FreightAssumptions()
    if show_pnl:
        pnl_radius_km = st.slider("Raio das rotas PNL (km)", 5, 50, 15, 5)
        pnl_display_mode = st.selectbox(
            "Visualização das rotas PNL",
            ["Saturação", "Carregamento total", "Modal", "Corredores"],
        )
        st.caption(
            "PNL 2050: carregamentos modelados em toneladas. A saturação trimestral "
            "se aplica apenas aos links rodoviários."
        )
        use_freight_demand = st.toggle(
            "Converter fluxo PNL em demanda de recarga", value=False,
            help="Ativa cenários auditáveis; hipóteses de frota e recarga não são dados oficiais do PNL.",
        )
        if use_freight_demand:
            freight_scenario = st.selectbox("Cenário logístico aplicado", ["P10", "P50", "P90"], index=1)
            with st.expander("Hipóteses centrais da conversão"):
                payload_t = st.number_input("Carga útil média (t/viagem)", 1.0, 100.0, 30.0, 1.0)
                empty_ratio = st.number_input("Retornos vazios por viagem carregada", 0.0, 2.0, 0.35, 0.05)
                electric_share = st.number_input("Participação elétrica (%)", 0.0, 100.0, 15.0, 1.0) / 100
                capture_share = st.number_input("Captura pelo eletroposto (%)", 0.0, 100.0, 20.0, 1.0) / 100
                energy_stop = st.number_input("Energia por parada (kWh)", 1.0, 1500.0, 250.0, 10.0)
                operating_days = st.number_input("Dias operacionais por ano", 1, 366, 365, 1)
                freight_assumptions = FreightAssumptions(
                    payload_t=payload_t,
                    empty_returns_per_loaded_trip=empty_ratio,
                    electric_share=electric_share,
                    station_capture_share=capture_share,
                    energy_per_stop_kwh=energy_stop,
                    operating_days_per_year=int(operating_days),
                )
                st.caption("P10 e P90 variam todas as hipóteses em torno destes valores; P50 usa os valores informados.")
    threshold_kw = st.number_input("Limiar crítico (kW)", min_value=0.0, value=250.0, step=25.0)
    mode_label = st.selectbox("Horizonte da simulação", [f"Anual ({SCENARIO_ANNUAL['horizon_h']:.0f} h)", "Diário (24 h)"])
    st.caption(f"Recurso solar: {PV_SYSTEM['radiation_database']} · PVGIS 5.3 · ano {PV_SYSTEM['year']}. "
               "Ano meteorológico histórico, não previsão nem data-base da BDGD.")
    mode = "annual" if mode_label.startswith("Anual") else "daily"
    limit_contract = st.checkbox("Limitar demanda contratada", value=False,
        help="Desmarcado: somente limites BDGD. Marcado: mantém a BDGD e acrescenta um teto comercial.")
    contract_cap_kw = None
    if limit_contract:
        contract_cap_kw = st.number_input("Teto da demanda contratada (kW)",
            min_value=0.1, value=100.0, step=10.0)
        st.caption("É um máximo, não um contrato fixo. O otimizador pode contratar menos. "
                   "A capacidade residual da rede continua sendo respeitada em cada horário.")
    else:
        st.caption("Demanda contratada livre de teto do usuário, sujeita aos limites BDGD.")
    service_label = st.selectbox("Objetivo da otimização", ["Econômico com meta de atendimento", "Máximo atendimento (referência)"])
    policy = {"mode": "economic" if service_label.startswith("Econômico") else "maximum"}
    if policy["mode"] == "economic":
        policy["target"] = st.number_input("Meta mínima no horizonte (%)", 0.0, 100.0, 98.0, 1.0) / 100
        policy["strict"] = st.checkbox("Exigir a meta como restrição rígida", value=False,
            help="Desmarcado: entrega o melhor atendimento possível se a rede não alcançar a meta. Marcado: o caso é inviável se a meta não puder ser cumprida.")
        protection = st.selectbox("Proteção de atendimento por período", ["Mensal", "Diária", "Sem proteção adicional"])
        policy["period"] = {"Mensal": "monthly", "Diária": "daily", "Sem proteção adicional": "none"}[protection]
        if policy["period"] != "none":
            policy["period_target"] = st.number_input("Meta mínima por período (%)", 0.0, 100.0, 95.0, 1.0) / 100
        policy["unserved_penalty"] = st.number_input("Penalidade por energia não atendida (R$/kWh)", 0.0, value=0.0, step=0.1)
        policy["waiting_penalty"] = st.number_input("Penalidade de espera energética (R$/kWh·h)", 0.0, value=0.0, step=0.01)
        st.caption("Com meta preferencial, primeiro minimiza o déficit de atendimento e depois o custo; pode atender mais que a meta. "
                   "Se a rede não alcançar a meta, retorna a melhor solução e quantifica o corte. A opção rígida declara o caso inviável.")
    else:
        st.caption("Referência anterior: máximo atendimento, mínima espera e depois mínimo custo.")
    sweep = False
    if policy["mode"] == "economic":
        sweep = st.checkbox("Comparar metas 95%, 98%, 99% e 100%", value=False)
        if sweep:
            st.caption("Executará quatro otimizações com o mesmo teto e proteção temporal; pode levar mais tempo. No modo preferencial, déficit físico será quantificado; no rígido, metas impossíveis serão identificadas como inviáveis.")
    config_labels = {"SMART": "Recarga inteligente", "SMART_PV": "Recarga + solar",
                     "SMART_BESS": "Recarga + bateria", "SMART_PV_BESS": "Recarga + solar + bateria"}
    configs = st.multiselect(
        "Configurações", ["SMART", "SMART_PV", "SMART_BESS", "SMART_PV_BESS"],
        default=["SMART_PV_BESS"],
        format_func=lambda value: config_labels[value],
    )
    demand_scale = st.slider("Fator da demanda de recarga", 0.25, 3.0, 1.0, 0.05)
    local_scale = st.slider("Fator da carga local", 0.0, 3.0, 1.0, 0.05)

lat, lon = st.session_state.latitude, st.session_state.longitude
inside_coverage = coverage is not None and point_is_covered(lat, lon, coverage)
cloud_point = None
if cloud_mode and inside_coverage:
    try:
        with st.spinner("Baixando o bloco BDGD necessário para este ponto..."):
            cloud_point = cached_cloud_point(source_path, round(lat, 7), round(lon, 7), radius_km)
        source_path = cloud_point["bdgd_path"]
        network_config["bdgd_path"] = source_path
        network_config["bdgd_reference_date"] = cloud_point["reference_date"]
    except Exception as exc:
        inside_coverage = False
        st.error(f"Não foi possível preparar o recorte BDGD em nuvem: {exc}")
try:
    map_data = cached_map(round(lat, 7), round(lon, 7), radius_km, source_path) if inside_coverage else None
    map_error = None
except Exception as exc:
    map_data, map_error = None, str(exc)

pnl_data, pnl_error = None, None
if show_pnl:
    try:
        with st.spinner("Preparando a rede logística PNL; o primeiro acesso pode levar alguns minutos..."):
            pnl_data = cached_pnl_window(round(lat, 7), round(lon, 7), float(pnl_radius_km))
    except Exception as exc:
        pnl_error = str(exc)

freight_analysis = None
if pnl_data and use_freight_demand:
    nearest_route = pnl_data["nearest"]
    if nearest_route.get("is_road"):
        freight_analysis = estimate_freight_charging(
            nearest_route["total_flow"], freight_assumptions
        )

st.markdown("""
<div class="section-eyebrow">Etapa 1 · Diagnóstico locacional</div>
<div class="section-title">Rede elétrica e ponto de conexão</div>
<div class="section-copy">Explore a infraestrutura disponível, confirme o alimentador e execute a análise antes do dimensionamento.</div>
""", unsafe_allow_html=True)
map_col, action_col = st.columns([1.9, 1], gap="large")
with map_col:
    bounds = [[-34, -74], [6, -34]] if national_mode or coverage is None else coverage["bounds"]
    map_view = folium.Map(
        location=[lat, lon], zoom_start=14, control_scale=True,
        max_bounds=True, min_lat=bounds[0][0],
        max_lat=bounds[1][0], min_lon=bounds[0][1],
        max_lon=bounds[1][1],
    )
    folium.GeoJson(
        coverage["geojson"] if coverage else {"type": "FeatureCollection", "features": []}, name="Área da BDGD carregada para cálculo",
        style_function=lambda _: {
            "color": "#0f766e", "weight": 3, "fillColor": "#14b8a6",
            "fillOpacity": 0.08, "dashArray": "7 5",
        },
        tooltip="Área de atuação disponível na BDGD",
    ).add_to(map_view)
    if map_data:
        folium.GeoJson(
            map_data["segments_geojson"], name="Rede MT",
            style_function=lambda feature: {
                "color": "#ef4444" if feature["properties"].get("is_nearest") else "#2563eb",
                "weight": 6 if feature["properties"].get("is_nearest") else 2,
                "opacity": 0.9,
            },
            tooltip=folium.GeoJsonTooltip(fields=["COD_ID", "CTMT", "TIP_CND", "distance_m"],
                                          aliases=["Segmento", "Alimentador", "Condutor", "Distância (m)"]),
        ).add_to(map_view)
        folium.GeoJson(
            map_data["transformers_geojson"], name="Transformadores MT",
            marker=folium.CircleMarker(radius=4, color="#f59e0b", fill=True, fill_opacity=0.85),
            tooltip=folium.GeoJsonTooltip(fields=["COD_ID", "CTMT", "POT_NOM"],
                                          aliases=["Transformador", "Alimentador", "Potência nominal"]),
        ).add_to(map_view)
    folium.Marker([lat, lon], tooltip="Ponto do eletroposto", icon=folium.Icon(color="green", icon="bolt", prefix="fa")).add_to(map_view)
    folium.Circle(
        [lat, lon], radius=radius_km * 1000.0, color="#475569", weight=1,
        dash_array="6 5", fill=False, tooltip=f"Raio de análise: {radius_km:.1f} km",
    ).add_to(map_view)
    if map_data and show_substations:
        substation_group = folium.FeatureGroup(name="Subestações", show=True)
        for substation in map_data.get("substations", []):
            power = substation.get("installed_power_mva")
            power_label = f"{power:,.1f} MVA".replace(",", "X").replace(".", ",").replace("X", ".") if power is not None else "não informada"
            label = substation.get("name") or substation["substation_id"]
            popup = folium.Popup(
                f"<b>Subestação {label}</b><br>"
                f"Código: {substation['substation_id']}<br>"
                f"Distância: {substation['distance_m']:.0f} m<br>"
                f"Potência nominal instalada: {power_label}<br>"
                f"Transformadores AT ativos: {substation['transformer_count']}<br>"
                f"Alimentadores associados: {substation['feeder_count']}<br>"
                f"Código de propriedade BDGD: {substation.get('ownership_code') or 'não informado'}<br>"
                f"Descrição: {substation.get('description') or 'não informada'}",
                max_width=360,
            )
            folium.Marker(
                [substation["latitude"], substation["longitude"]],
                tooltip=f"Subestação {label} · {substation['distance_m']:.0f} m",
                popup=popup,
                icon=folium.Icon(color="purple", icon="industry", prefix="fa"),
            ).add_to(substation_group)
        substation_group.add_to(map_view)
    if show_stations:
        add_ocm_layer(map_view, lat, lon, station_radius, include_uncertain)
    if pnl_data:
        add_pnl_layer(map_view, pnl_data, pnl_display_mode)
    folium.LayerControl().add_to(map_view)
    event = st_folium(map_view, height=560, use_container_width=True,
                      key=f"network_map_{st.session_state.get('map_revision', 0)}",
                      returned_objects=["last_clicked"])
    click = event.get("last_clicked") if event else None
    if click:
        signature = f"{click['lat']:.7f},{click['lng']:.7f}"
        if signature != st.session_state.get("processed_click"):
            st.session_state.processed_click = signature
            if national_mode or (coverage is not None and point_is_covered(click["lat"], click["lng"], coverage)):
                select_point(click["lat"], click["lng"])
            else:
                st.session_state.coordinate_warning = (
                    "O ponto clicado está fora da área coberta pela BDGD e não foi selecionado."
                )
            st.rerun()

with action_col:
    if cloud_point:
        st.success(
            f"Base em nuvem pronta: {cloud_point['distributor']} · alimentador calculado "
            f"{cloud_point['feeder_id']} · {cloud_point['context_feeder_count']} alimentador(es) "
            f"no contexto cartográfico de {cloud_point['context_radius_km']:.1f} km"
        )
    st.subheader("Ponto selecionado")
    st.code(f"{lat:.7f}, {lon:.7f}")
    if inside_coverage:
        st.success("Ponto dentro da área BDGD")
    else:
        st.warning("Ponto fora da BDGD carregada. Escolha e baixe a distribuidora correspondente no catálogo nacional para calcular aqui.")
    if map_error:
        st.error(map_error)
    elif map_data:
        st.metric("Distância à rede MT", f"{map_data['nearest_distance_m']:.1f} m")
        st.write(f"**Alimentador:** {map_data['nearest_feeder_id']}")
        st.write(f"**Segmento:** {map_data['nearest_segment_id']}")
        st.caption(f"{map_data['segment_count']} segmentos e {map_data['transformer_count']} transformadores no recorte.")
        if show_substations:
            substations = map_data.get("substations", [])
            st.metric("Subestações no raio", len(substations))
            if substations:
                with st.expander("Dados das subestações no raio", expanded=True):
                    for substation in substations:
                        name = substation.get("name") or substation["substation_id"]
                        power = substation.get("installed_power_mva")
                        power_label = (f"{power:,.1f} MVA".replace(",", "X").replace(".", ",").replace("X", ".")
                                       if power is not None else "não informada")
                        st.markdown(
                            f"**{name}** (`{substation['substation_id']}`)  \n"
                            f"Distância: {substation['distance_m']:.0f} m · "
                            f"Potência instalada: {power_label} · "
                            f"Transformadores AT: {substation['transformer_count']} · "
                            f"Alimentadores: {substation['feeder_count']}"
                        )
            else:
                st.caption("Nenhuma subestação cadastrada na BDGD dentro deste raio.")
            excluded = map_data.get("excluded_substation_count", 0)
            if excluded:
                st.caption(
                    f"{excluded} instalação(ões) da camada SUB sem alimentador CTMT associado "
                    "foram omitidas para não misturar consumidores AT ou instalações particulares."
                )

    if pnl_error:
        st.error(f"Camada PNL indisponível: {pnl_error}")
    elif pnl_data:
        nearest_pnl = pnl_data["nearest"]
        with st.expander("Diagnóstico logístico PNL", expanded=True):
            st.metric("Distância à rota de carga mais próxima", f"{nearest_pnl['distance_km']:.2f} km")
            st.write(f"**Segmento PNL:** {nearest_pnl['segment_id']}")
            modal = nearest_pnl.get("modal") or gtype_label(nearest_pnl.get("gtype"))
            is_road = nearest_pnl.get("is_road", nearest_pnl.get("gtype") == 1)
            st.write(f"**Modal:** {modal} (`GTYPE = {nearest_pnl['gtype']}`)")
            st.write(f"**Corredor:** {nearest_pnl['corridor']}")
            saturation = nearest_pnl.get("max_saturation")
            st.write("**Saturação máxima:** " + (
                f"{saturation * 100:.1f}% · {nearest_pnl['saturation_label']}"
                if saturation is not None else (
                    "não aplicável ao modal" if not is_road else "não informada"
                )
            ))
            st.write(f"**Carregamento total modelado:** {nearest_pnl['total_flow']:,.0f} t")
            if nearest_pnl.get("main_load_group"):
                st.write(f"**Grupo de carga predominante:** {nearest_pnl['main_load_group']}")
                composition = pd.DataFrame([
                    {"Grupo de carga": group, "Carregamento (t)": value}
                    for group, value in nearest_pnl["load_composition_t"].items()
                    if value > 0
                ]).sort_values("Carregamento (t)", ascending=False)
                if not composition.empty:
                    with st.expander("Composição do carregamento por grupo"):
                        st.dataframe(composition, hide_index=True, use_container_width=True)
            st.caption(
                f"{pnl_data['segment_count']} trechos no raio; "
                f"{pnl_data['road_segment_count']} rodoviários; "
                f"{pnl_data['corridor_segment_count']} classificados como corredores; "
                f"{pnl_data['high_saturation_count']} links rodoviários com saturação ≥80%."
            )
            st.warning(pnl_data["interpretation_warning"])
            if use_freight_demand and not is_road:
                st.info("A conversão em recarga rodoviária não foi aplicada porque o segmento mais próximo não é rodoviário.")
            elif freight_analysis:
                st.markdown(
                    '<div class="logistics-heading">Cenários de demanda logístico-elétrica</div>',
                    unsafe_allow_html=True,
                )
                demand_table = pd.DataFrame(scenario_table(freight_analysis))
                compact_table = demand_table[[
                    "Cenário", "Recargas/dia", "Energia/dia (kWh)", "Pico do perfil (kW)"
                ]]
                st.dataframe(
                    compact_table,
                    hide_index=True, use_container_width=True,
                    column_config={
                        column: st.column_config.NumberColumn(column, format="%.1f")
                        for column in compact_table.columns if column != "Cenário"
                    },
                )
                with st.expander("Ver todos os indicadores dos cenários"):
                    st.dataframe(
                        demand_table,
                        hide_index=True, use_container_width=True,
                        column_config={
                            column: st.column_config.NumberColumn(column, format="%.1f")
                            for column in demand_table.columns if column != "Cenário"
                        },
                    )
                selected_freight = freight_analysis["scenarios"][freight_scenario]
                profile_table = pd.DataFrame({
                    "Hora do dia (h)": list(range(24)),
                    "Demanda de recarga (kW)": selected_freight["hourly_profile_kw"],
                })
                profile_chart = (
                    alt.Chart(profile_table)
                    .mark_line(point=True, strokeWidth=3, color="#0b63ce")
                    .encode(
                        x=alt.X(
                            "Hora do dia (h):Q",
                            title="Hora do dia (h)",
                            scale=alt.Scale(domain=[0, 23]),
                            axis=alt.Axis(values=list(range(0, 24, 2))),
                        ),
                        y=alt.Y(
                            "Demanda de recarga (kW):Q",
                            title="Demanda de recarga (kW)",
                            scale=alt.Scale(zero=True),
                        ),
                        tooltip=[
                            alt.Tooltip("Hora do dia (h):Q", title="Hora", format=".0f"),
                            alt.Tooltip("Demanda de recarga (kW):Q", title="Demanda", format=",.1f"),
                        ],
                    )
                    .properties(
                        title=f"Perfil horário de recarga — cenário {freight_scenario}",
                        height=320,
                    )
                    .configure_axis(
                        labelColor="#243b53", titleColor="#0b2340",
                        gridColor="#dbe6f1", titleFontSize=13, labelFontSize=11,
                    )
                    .configure_title(color="#0b2340", fontSize=15, anchor="start")
                    .configure_view(stroke="#dbe6f1")
                )
                st.altair_chart(profile_chart, use_container_width=True)
                st.caption(
                    f"{freight_scenario}: {selected_freight['charging_events_per_day']:.1f} recargas/dia, "
                    f"{selected_freight['daily_energy_kwh']:,.1f} kWh/dia e pico representativo de "
                    f"{selected_freight['profile_peak_kw']:,.1f} kW. O fator da demanda de recarga "
                    "da simulação é aplicado adicionalmente a esta curva."
                )
                st.warning(freight_analysis["scope_warning"])

    if st.button("Analisar rede neste ponto", type="primary", use_container_width=True,
                 disabled=not inside_coverage):
        with st.spinner("Consultando a BDGD e calculando capacidade residual..."):
            try:
                st.session_state.pop("network_result", None)
                st.session_state.pop("simulation_result", None)
                st.session_state.network_result = analyze_point(lat, lon, threshold_kw, network_config)
            except Exception as exc:
                st.error(str(exc))
    if st.button("Simular eletroposto neste ponto", use_container_width=True,
                 disabled=not configs or not inside_coverage):
        with st.spinner("Executando otimização; o modo anual pode levar alguns minutos..."):
            try:
                st.session_state.pop("simulation_result", None)
                network_result = st.session_state.get("network_result")
                if (not network_result or network_result.get("location") != {"latitude": lat, "longitude": lon}
                        or network_result.get("threshold_kw") != threshold_kw):
                    network_result = analyze_point(lat, lon, threshold_kw, network_config)
                    st.session_state.network_result = network_result
                if GRID_NETWORK.get("limit_source") != "manual" and not network_result.get("is_network_valid"):
                    st.error("Simulação não iniciada: a capacidade BDGD não foi validada. Consulte o diagnóstico abaixo.")
                else:
                    policies = [dict(policy, target=x) for x in (.95, .98, .99, 1.0)] if sweep else [policy]
                    for current_policy in policies:
                        logistics_kwargs = {}
                        if freight_analysis:
                            logistics_kwargs = {
                                "logistics_profile_kw": freight_analysis["scenarios"][freight_scenario]["hourly_profile_kw"],
                                "logistics_context": {
                                    "pnl_segment_id": pnl_data["nearest"]["segment_id"],
                                    "pnl_annual_tonnes": pnl_data["nearest"]["total_flow"],
                                    "scenario": freight_scenario,
                                    "analysis": freight_analysis["scenarios"][freight_scenario],
                                    "central_assumptions": freight_analysis["central_assumptions"],
                                },
                            }
                        st.session_state.simulation_result = simulate_point(
                            lat, lon, mode, configs, demand_scale, local_scale, threshold_kw, network_config,
                            contracted_demand_cap_kw=contract_cap_kw,
                            service_policy=current_policy,
                            **logistics_kwargs,
                        )
                        history = st.session_state.get("demand_comparison_history", [])
                        history.append(st.session_state.simulation_result)
                        st.session_state.demand_comparison_history = history[-10:]
            except Exception as exc:
                st.error(str(exc))

if "network_result" in st.session_state:
    result = st.session_state.network_result
    assessment, critical = result["assessment"], result["critical"]
    st.divider()
    st.markdown('<div class="section-eyebrow">Etapa 2 · Capacidade</div><div class="section-title">Análise da rede</div>', unsafe_allow_html=True)
    st.caption(f"Ponto analisado: {lat:.7f}, {lon:.7f}")
    reference = result.get("bdgd_reference_date") or assessment.get("residual_capacity", {}).get("bdgd_reference_date")
    profile_start = result.get("network_profile_calendar_start")
    profile_text = f"; perfil reconstruído a partir de {str(profile_start)[:10]}" if profile_start else ""
    st.caption("Referência elétrica: " + (f"BDGD de {reference}{profile_text}. " if reference else "data-base BDGD não identificada. ")
               + f"Referência solar independente: PVGIS/ERA5 {PV_SYSTEM['year']}.")
    valid_network = result.get("is_network_valid", False)
    if not valid_network:
        st.error("Análise BDGD inconclusiva: não foi possível validar a capacidade da rede neste ponto.")
        st.warning("O motor acionou o limite manual de segurança. Esse valor não representa capacidade residual BDGD e não será apresentado como disponibilidade da rede.")
        st.write("**Motivo:** " + assessment.get("error", "Diagnóstico indisponível; execute novamente a análise."))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Capacidade residual mínima", f"{result['minimum_kw']:,.1f} kW" if valid_network else "Indisponível")
    m2.metric("Capacidade residual média", f"{result['mean_kw']:,.1f} kW" if valid_network else "Indisponível")
    m3.metric("Capacidade residual máxima", f"{result['maximum_kw']:,.1f} kW" if valid_network else "Indisponível")
    m4.metric("Intervalos críticos", critical.get("critical_interval_count", "—"))
    st.info("Triagem baseada na BDGD pública; não substitui estudo de acesso nem parecer da concessionária.")
    if valid_network and freight_analysis:
        selected_freight = freight_analysis["scenarios"][freight_scenario]
        logistics_peak = selected_freight["profile_peak_kw"] * demand_scale
        limiting_residual = float(result["minimum_kw"])
        deficit_kw = max(0.0, logistics_peak - limiting_residual)
        st.subheader("Compatibilidade preliminar entre fluxo logístico e rede")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cenário", freight_scenario)
        c2.metric("Pico de recarga estimado", f"{logistics_peak:,.1f} kW")
        c3.metric("Residual mínimo BDGD", f"{limiting_residual:,.1f} kW")
        c4.metric("Déficit instantâneo indicativo", f"{deficit_kw:,.1f} kW")
        if deficit_kw > 0:
            st.warning(
                "O pico representativo supera o menor residual estimado. Isso não torna o "
                "projeto automaticamente inviável: a otimização testará deslocamento da "
                "recarga, atendimento parcial, BESS, solar e eventual reforço."
            )
        else:
            st.success(
                "Na comparação conservadora de pico contra residual mínimo, a rede apresenta "
                "margem. A conclusão depende ainda da simulação horária completa."
            )
    output = Path(result["output_dir"])
    plot = output / "grid_capacity_24h_analysis.png"
    left, right = st.columns([1.5, 1])
    with left:
        if valid_network and plot.exists():
            st.image(str(plot), use_container_width=True)
    with right:
        st.write(f"**Pior dia:** {critical.get('worst_date', '—')}")
        hours = critical.get("preferred_charging_hours", [])
        st.write("**Horas preferenciais:** " + ", ".join(f"{h:02d}h" for h in hours))
        if valid_network:
            detail = assessment.get("connection_detail", {})
            if detail.get("topology_recovery_used"):
                st.warning(
                    f"Continuidade cadastral recuperada com {detail.get('path_topology_connector_count', 0)} "
                    "conectores exclusivamente topológicos. Eles não fornecem capacidade ou impedância ao cálculo."
                )
            for label, key, unit in [
                ("Alimentador", "feeder_id", ""), ("Subestação", "substation_id", ""),
                ("Tensão nominal", "voltage_kv", " kV"),
                ("Corrente máxima do condutor", "conductor_cmax_a", " A"),
                ("Teto térmico do trecho — antes da carga existente", "estimated_network_limit_kw", " kW"),
            ]:
                value = assessment.get(key)
                display = f"{value:,.2f}" if isinstance(value, (float, int)) else str(value or "—")
                st.write(f"**{label}:** {display}{unit}")
            if detail.get("topology_recovery_used"):
                st.write("**Conectores topológicos:** " + ", ".join(detail.get("path_topology_connector_ids", [])))
        report = output / "grid_connection_detailed_report.md"
        if report.exists():
            st.download_button("Baixar relatório detalhado", report.read_bytes(), report.name)
    critical_csv = output / "grid_capacity_critical_intervals.csv"
    if critical_csv.exists():
        with st.expander("Ver intervalos críticos"):
            critical_table = pd.read_csv(critical_csv).rename(columns={
                "timestamp": "Data e hora",
                "feeder_existing_load_estimated_kw": "Carga estimada do alimentador (kW)",
                "load_with_safety_factor_kw": "Carga com margem de segurança (kW)",
                "distributed_generation_estimated_kw": "Geração distribuída estimada (kW)",
                "credited_generation_kw": "Geração distribuída considerada (kW)",
                "network_capacity_ceiling_kw": "Teto térmico da rede (kW)",
                "shared_transformer_load_estimated_kw": "Carga estimada no transformador compartilhado (kW)",
                "residual_capacity_kw": "Capacidade residual (kW)",
                "month": "Mês", "hour": "Hora", "hour_of_day": "Hora do dia",
                "is_zero": "Sem margem incremental", "is_critical": "Abaixo do limiar crítico",
            })
            for column in ("Sem margem incremental", "Abaixo do limiar crítico"):
                if column in critical_table:
                    critical_table[column] = critical_table[column].map(
                        {True: "Sim", False: "Não", "True": "Sim", "False": "Não"}
                    ).fillna(critical_table[column])
            st.dataframe(critical_table, use_container_width=True, hide_index=True)
    st.caption(f"Arquivos desta análise: {output}")

if "simulation_result" in st.session_state:
    result = st.session_state.simulation_result
    st.divider()
    st.markdown('<div class="section-eyebrow">Etapa 3 · Otimização</div><div class="section-title">Solução otimizada</div>', unsafe_allow_html=True)
    simulation_diagnostic = result.get("diagnostic", {})
    run_inputs = result.get("inputs", {})
    st.caption("Política desta execução: " + describe_policy(run_inputs.get("service_policy")))
    run_cap = run_inputs.get("contracted_demand_cap_kw")
    st.caption("Modo desta execução: " + ("BDGD sem teto de demanda do usuário." if run_cap is None
        else f"BDGD + teto de demanda contratada de {run_cap:.2f} kW."))
    st.caption("Alterar os controles não recalcula o resultado exibido; execute uma nova simulação.")
    if simulation_diagnostic.get("configured_limit_source") in {"bdgd", "minimum"} and simulation_diagnostic.get("effective_limit_source") not in {"bdgd", "minimum"}:
        st.error("Este resultado usou o limite manual de segurança, não a capacidade BDGD. Não deve ser interpretado como dimensionamento validado pela rede.")
    summary_labels = {
        "config": "Configuração", "solve_status": "Estado da solução",
        "objective_value": "Custo líquido no horizonte (R$)",
        "pv_size_kw": "Solar (kW)", "bess_e_kwh": "Bateria (kWh)",
        "bess_p_kw": "Potência da bateria (kW)",
        "contracted_demand_kw": "Demanda contratada (kW)",
        "monthly_peak_grid_kw": "Pico da rede (kW)",
        "served_energy_kwh": "Energia de recarga atendida (kWh)",
        "served_ratio": "Fração da recarga atendida (0–1)",
        "service_mode": "Modo de atendimento",
        "service_target": "Meta no horizonte (0–1)",
        "service_target_met": "Meta atingida",
        "global_target_shortfall_kwh": "Déficit para a meta (kWh)",
        "unserved_energy_kwh": "Recarga total não atendida (kWh)",
        "charging_curtailment_ratio": "Fração de recarga cortada (0–1)",
        "waiting_energy_hours": "Espera energética acumulada (kWh·h)",
        "expired_unserved_energy_kwh": "Recarga expirada sem atendimento (kWh)",
        "final_backlog_kwh": "Recarga pendente ao final (kWh)",
        "demand_cost_in_horizon_brl": "Custo de demanda no horizonte (R$)",
        "indicative_firm_reinforcement_kw": "Reforço firme indicativo para a carga local (kW)",
        "indicative_full_demand_reinforcement_kw": "Reforço indicativo para toda a demanda instantânea (kW)",
        "indicative_nominal_bess_required_kwh": "BESS nominal indicativo para o maior período sem margem (kWh)",
    }
    visible_summary = result["summary"][[key for key in summary_labels if key in result["summary"]]].copy()
    if "config" in visible_summary:
        visible_summary["config"] = visible_summary["config"].replace(config_labels)
    if "solve_status" in visible_summary:
        visible_summary["solve_status"] = visible_summary["solve_status"].replace({"solved": "Resolvido", "infeasible": "Inviável"})
    if "service_mode" in visible_summary:
        visible_summary["service_mode"] = visible_summary["service_mode"].replace({"economic": "Econômico", "maximum": "Máximo atendimento"})
    st.dataframe(visible_summary.rename(columns=summary_labels), use_container_width=True, hide_index=True)
    st.caption("Atendimento é medido por energia, não por número de veículos ou tempo individual de fila. "
               "Um teto muito baixo pode tornar a solução inviável porque a carga local é obrigatória.")
    expansion = result.get("expansion_diagnostic", {})
    feasibility = result["summary"].get("is_feasible", pd.Series(dtype=bool))
    if expansion and not feasibility.fillna(False).all():
        st.subheader("Diagnóstico e alternativas quando a margem da rede é insuficiente")
        st.warning(
            "Inviável descreve apenas o caso sem reforço. As alternativas abaixo são "
            "hipóteses quantitativas de melhoria, não uma autorização da distribuidora."
        )
        local_case = expansion["local_load_case"]
        full_case = expansion["full_instantaneous_demand_case"]
        storage = expansion["storage_screening"]
        improved = expansion["improved_local_support_case"]
        cols = st.columns(4)
        cols[0].metric("Reforço para sustentar a carga local", f"{local_case['reinforcement_to_eliminate_deficit_kw']:.2f} kW")
        cols[1].metric("Reforço para demanda simultânea", f"{full_case['reinforcement_to_eliminate_deficit_kw']:.2f} kW")
        cols[2].metric("Maior período sem margem", f"{storage['longest_zero_residual_hours']:.0f} h")
        cols[3].metric("BESS nominal indicativo", f"{storage['indicative_nominal_bess_required_kwh']:.0f} kWh")
        st.dataframe(pd.DataFrame([
            {"Alternativa": "Rede atual", "Reforço (kW)": 0.0,
             "Resultado": f"{local_case['deficit_intervals']} intervalos com déficit da carga local"},
            {"Alternativa": "Reforço firme mínimo da carga local",
             "Reforço (kW)": improved["firm_reinforcement_kw"],
             "Resultado": f"{improved['remaining_local_deficit_intervals']} intervalos restantes; libera margem para recarga inteligente"},
            {"Alternativa": "Reforço para atendimento instantâneo integral",
             "Reforço (kW)": full_case["reinforcement_to_eliminate_deficit_kw"],
             "Resultado": "Elimina o déficit estimado de carga local + recarga solicitada"},
            {"Alternativa": "Solar + BESS otimizado", "Reforço (kW)": 0.0,
             "Resultado": "Consulte a linha viável Recarga + solar + bateria, quando simulada"},
        ]), use_container_width=True, hide_index=True)
        st.caption(
            f"O maior período com residual zero exige aproximadamente "
            f"{storage['stored_energy_required_kwh']:.0f} kWh armazenados; com a janela de SOC "
            f"adotada, corresponde a {storage['indicative_nominal_bess_required_kwh']:.0f} kWh nominais. "
            "Esse valor é uma condição necessária, não um dimensionamento final."
        )
    history = st.session_state.get("demand_comparison_history", [])
    signature_keys = ("latitude", "longitude", "mode", "configs", "demand_scale", "local_scale", "threshold_kw", "bdgd_path")
    comparable = [r for r in history if r.get("inputs") and all(
        r["inputs"].get(k) == run_inputs.get(k) for k in signature_keys)]
    if len(comparable) > 1:
        st.subheader("Comparação dos tetos de demanda")
        st.caption("Custo × atendimento: políticas e metas podem variar entre as linhas. Compare casos com a mesma proteção temporal.")
        st.caption("Últimas execuções desta sessão com mesmo ponto, base, horizonte, configurações e fatores de carga. "
                   "Cada caso pode redimensionar FV e BESS; não é despacho de equipamentos fixos.")
        frames = []
        for previous in comparable:
            frame = previous["summary"][[k for k in summary_labels if k in previous["summary"]]].copy()
            cap = previous["inputs"].get("contracted_demand_cap_kw")
            frame.insert(0, "Teto do usuário", "Livre (BDGD)" if cap is None else f"{cap:.2f} kW")
            frame.insert(1, "Política", describe_policy(previous["inputs"].get("service_policy")))
            frames.append(frame)
        comparison = pd.concat(frames, ignore_index=True).rename(columns=summary_labels)
        if "Configuração" in comparison:
            comparison["Configuração"] = comparison["Configuração"].replace(config_labels)
        st.dataframe(comparison, use_container_width=True, hide_index=True)
        st.download_button("Baixar comparação CSV", comparison.to_csv(index=False).encode(), "comparacao_demanda.csv")
    render_technical_panel(result)
    output = Path(result["output_dir"])
    images = sorted(p for p in output.glob("*.png") if not p.name.startswith("technical_"))
    if images:
        with st.expander("Demais gráficos exportados pela simulação"):
            cols = st.columns(2)
            for index, path in enumerate(images):
                cols[index % 2].image(str(path), caption=path.stem, use_container_width=True)
    st.download_button("Baixar resumo CSV", result["summary"].to_csv(index=False).encode(), "resumo_simulacao.csv")
    st.caption(f"Arquivos desta simulação: {output}")


st.markdown("""
<div class="footer-card">
  <span><strong>Júlio Cesar C. Nunes</strong> · FEEC/UNICAMP</span>
  <span><a href="mailto:j298971@dac.unicamp.br">j298971@dac.unicamp.br</a> · Ferramenta de apoio ao planejamento</span>
</div>
""", unsafe_allow_html=True)
render_access_footer(st, access_metrics)
