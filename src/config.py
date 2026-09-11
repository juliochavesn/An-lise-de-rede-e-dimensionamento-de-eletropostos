"""
Arquivo central de configuração do projeto.

A ideia é concentrar aqui os parâmetros que devem ser facilmente
alterados pelo usuário, sem necessidade de modificar o modelo AMPL
nem as funções de simulação.
"""

from pathlib import Path
import calendar

# Último ano completo validado com o pipeline meteorológico pvlib em 04/09/2026.
# PVGIS 6 possui 2024, mas as séries consultadas tiveram lacunas diurnas.
SOLAR_REFERENCE_YEAR = 2023


# ============================================================
# CAMINHOS DO PROJETO
# ============================================================

# Diretório raiz do projeto.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Diretório onde ficam os arquivos AMPL .mod e .run.
AMPL_DIR = PROJECT_ROOT / "ampl"

# Diretório onde ficam os resultados gerados.
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# Cria o diretório de saída caso ainda não exista.
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================
# INTEGRACAO COM A REDE DE DISTRIBUICAO (BDGD)
# ============================================================

GRID_NETWORK = {
    # manual: preserva o limite definido pela demanda maxima contratada;
    # bdgd: usa somente o teto tecnico estimado a partir da BDGD;
    # minimum: aplica o menor valor entre BDGD e o limite manual.
    "limit_source": "bdgd",

    # Base anual da CPFL Paulista armazenada dentro do projeto. Tambem pode
    # apontar diretamente para um diretorio .gdb ja descompactado.
    "bdgd_path": (
        PROJECT_ROOT
        / "Dados BDGD"
        / "CPFL_Paulista_63_2025-12-31_V11_20260822-0029.gdb.zip"
    ),
    # Data-base elétrica, independente do ano meteorológico do PVGIS.
    "bdgd_reference_date": "2025-12-31",

    # Primeira fase: avaliacao do segmento de media tensao mais proximo.
    "connection_level": "medium_voltage",
    # residual: desconta a carga horaria estimada do alimentador;
    # thermal: preserva apenas o teto termico bruto da fase anterior.
    "capacity_method": "residual",
    "power_factor": 0.95,
    "thermal_utilization_factor": 0.80,
    "transformer_utilization_factor": 0.80,
    # Margem conservadora para incerteza, crescimento e ausencia de SCADA.
    "existing_load_safety_factor": 1.10,
    # Geracao distribuida nao e tratada como capacidade firme por padrao.
    "distributed_generation_credit_fraction": 0.0,
    # Potencia usada apenas na triagem de queda de tensao do caminho.
    "connection_reference_power_kw": 250.0,
    # Raio para listar transformadores de distribuicao proximos ao ponto.
    "nearby_asset_radius_km": 1.0,
    # Recuperação nacional conservadora: código contábil desconhecido pode
    # fechar somente o diagrama, nunca fornecer limite ou impedância.
    "topology_only_accounting_codes": ["0"],
    "max_topology_only_connectors": 8,
    "enable_detailed_connection_report": True,
    # Analise automatica dos piores dias e das janelas de recarga.
    "enable_critical_period_analysis": True,
    # Considera critico um intervalo com capacidade abaixo deste valor.
    "critical_capacity_threshold_kw": 250.0,
    "zero_capacity_tolerance_kw": 1e-6,
    # Quantidade de horas robustas sugeridas pelo percentil P10 anual.
    "preferred_charging_hour_count": 6,
    "max_search_radius_km": 10.0,

    # Preserva o comportamento de seguranca anterior: se a BDGD falhar,
    # usa o limite manual e registra o fallback no diagnostico.
    "on_error": "manual",
}

# ============================================================
# Configurações de habilitação de fontes e tecnologias
# ============================================================

SYSTEM_OPTIONS = {
    # Rede elétrica disponível?
    "enable_grid": True,

    # Carga local do posto/restaurante/conveniência?
    "enable_local_load": True,

    # FV disponível para otimização?
    "enable_pv": True,

    # BESS disponível para otimização?
    "enable_bess": True,
}
# ============================================================
# CONFIGURAÇÃO DO SOLVER AMPL
# ============================================================

AMPL_MODEL_FILE = AMPL_DIR / "eletroposto.mod"

# Solver padrão. Pode ser alterado para cbc, gurobi, cplex etc.
SOLVER_NAME = "highs"


# ============================================================
# CENÁRIOS TECNOLÓGICOS
# ============================================================

# SMART: apenas rede e controle inteligente de atendimento.
# SMART_PV: rede + FV.
# SMART_BESS: rede + BESS.
# SMART_PV_BESS: rede + FV + BESS.
CONFIGS = ["SMART"]

if SYSTEM_OPTIONS["enable_pv"]:
    CONFIGS.append("SMART_PV")

if SYSTEM_OPTIONS["enable_bess"]:
    CONFIGS.append("SMART_BESS")

if SYSTEM_OPTIONS["enable_pv"] and SYSTEM_OPTIONS["enable_bess"]:
    CONFIGS.append("SMART_PV_BESS")

# ============================================================
# LIMITES TECNOLÓGICOS
# ============================================================

LIMITS = {
    # Potência máxima total dos carregadores EV no site [kW].
    "charger_max_kw": 300.0,

    # Prazo máximo para atender energia EV postergada [h].
    # A parcela não atendida após essa janela expira e é registrada
    # separadamente, sem penalidade subjetiva de qualidade.
    "ev_max_delay_h": 2.0,

    # Parcela máxima da geração FV potencial que pode ser cortada.
    "maximum_pv_curtailment_fraction": 0.30,

    # Limite superior para dimensionamento do sistema FV [kWp].
    "pv_max_kw": 1200.0,

    # Limite superior para capacidade energética do BESS [kWh].
    "bess_e_max_kwh": 3000.0,

    # Limite superior para potência do BESS [kW].
    "bess_p_max_kw": 1000.0,

    # Eficiência de carga do BESS.
    "bess_eta_ch": 0.95,

    # Eficiência de descarga do BESS.
    "bess_eta_dis": 0.95,

    # Estado inicial de carga do BESS como fração da capacidade.
    "bess_soc_init_frac": 0.40,

    # Janela operacional de SOC. A faixa 10%-90% disponibiliza 80%
    # da capacidade nominal e é coerente com o DoD usado no custo
    # de degradação. O SOC final é exclusivamente cíclico e igual
    # ao SOC inicial; portanto, não existe parâmetro final separado.
    "bess_soc_min_frac": 0.10,
    "bess_soc_max_frac": 0.90,

    # Faixa comercial de duração nominal E/P do BESS [h].
    # Sungrow PowerStack C&I: sistemas de 2-4 h.
    # https://uk.sungrowpower.com/productDetail/3982
    # Tesla Megapack: configurações comerciais de 2 h e 4 h.
    # https://www.tesla.com/megapack/design
    # Fluence Gridstack Pro: configurações de 2, 4, 6 e 8 h.
    # https://info.fluenceenergy.com/hubfs/
    # Fluence%20Gridstack%20Pro_Global_US%20EN.pdf
    # Adota-se 2-6 h para abranger tanto aplicações C&I quanto hubs
    # de maior duração, sem incluir a classe de 8 h neste estudo.
    "bess_duration_min_h": 2.0,
    "bess_duration_max_h": 6.0,
}

# ============================================================
# PARÂMETROS DE CUSTO E PENALIZAÇÃO
# ============================================================

COSTS = {
    # Todos os valores monetários estão em reais constantes (BRL)
    # com data-base dezembro de 2024. Não usar "mil R$".
    #
    # FONTE FV:
    # EPE/MME, PDE 2035 - Caderno de Parâmetros de Custos de
    # Geração e Transmissão, data-base dez/2024, pp. 8-12.
    # Faixa FV: R$ 3.000-6.000/kW; referências de R$ 3.000,
    # 3.500, 4.500 e 5.500/kW; O&M de R$ 60/kW.ano;
    # vida econômica de 25 anos; taxa real de 8% a.a.
    # https://www.epe.gov.br/sites-pt/publicacoes-dados-abertos/
    # publicacoes/PublicacoesArquivos/publicacao-894/
    # PDE%202035_Caderno%20Par%C3%A2metros%20de%20Custos_rev10.11.25.pdf
    "pv_capex_per_kwp": 3500.0,          # [R$/kWp DC]
    "pv_fixed_om_per_kwp_year": 60.0,   # [R$/kWp.ano]
    "pv_economic_lifetime_years": 25.0,

    # CAPEX INSTALADO DO BESS - CALIBRAÇÃO BRASILEIRA:
    # Cinco cotações nacionais da distribuidora BelEnergy para gabinetes
    # BESS C&I integrados, com aproximadamente 2 h (100-125 kW e
    # 215-261 kWh), resultaram em mediana de R$ 1.316/kWh nominal e
    # R$ 1.343/kWh útil somente para o equipamento, sem instalação.
    # Cotações comerciais coletadas em 2026 e fornecidas pelo autor;
    # usadas como referência de mercado, não como orçamento de EPC.
    #
    # A referência instalada foi calibrada pelo PDE 2035 da EPE/MME:
    # BESS Li-ion de 4 h, CAPEX de referência de R$ 5.000, 5.500 e
    # 6.000/kW (faixa ampla de R$ 5.000-9.000/kW), data-base dez/2024.
    # O caso central de R$ 5.500/kW foi decomposto em custo de energia
    # e de potência conforme a metodologia do NREL ATB. O resultado
    # C_E = R$ 1.225/kWh e C_P = R$ 600/kW preserva exatamente:
    # 4*C_E + C_P = R$ 5.500/kW para um sistema de 4 h. Para 2 h,
    # equivale a R$ 1.525/kWh instalado, cerca de 16% acima da mediana
    # nacional de fornecimento observada.
    #
    # EPE/MME, PDE 2035 - Caderno de Parâmetros de Custos:
    # https://www.epe.gov.br/sites-pt/publicacoes-dados-abertos/
    # publicacoes/PublicacoesArquivos/publicacao-894/
    # PDE%202035_Caderno%20Par%C3%A2metros%20de%20Custos_rev10.11.25.pdf
    # NREL ATB 2024 - Commercial Battery Storage:
    # https://atb.nrel.gov/electricity/2024/commercial_battery_storage
    #
    # FONTE O&M BESS:
    # EPE/MME, PDE 2035 - Caderno de Parâmetros de Custos,
    # referência para BESS Li-ion de 4 h: R$ 130-160/kW.ano.
    "bess_energy_capex_per_kwh": 1225.0, # [R$/kWh instalado]
    "bess_power_capex_per_kw": 600.0,    # [R$/kW instalado]
    "bess_fixed_om_per_kw_year": 140.0, # [R$/kW.ano]

    # Vida econômica adotada para a parte eletroquímica.
    # O caderno de baterias da EPE considera reposição no 10º ano.
    "bess_economic_lifetime_years": 10.0,

    # Degradação cíclica por throughput. Metodologia:
    # NREL, Optimization of Energy Storage, NREL/TP-5R00-85472.
    # https://www.nrel.gov/docs/fy23osti/85472.pdf
    # Hipóteses centrais configuráveis para BESS LFP.
    "bess_equivalent_full_cycles": 6000.0,
    "bess_usable_depth_fraction": 0.80,
    "bess_replacement_cost_fraction": 0.65,

    # Taxa de desconto real recomendada no PDE 2035.
    "real_discount_rate": 0.08,          # [fração/ano]

    # Curtailment é contabilizado como indicador físico. Por padrão,
    # não recebe custo adicional, pois o CAPEX FV já penaliza o
    # sobredimensionamento. Pode ser alterado quando houver um custo
    # de oportunidade economicamente justificado [u.m./kWh].
    "curtailment_penalty": 0.0,

    # Não atendimento não recebe, por enquanto, custo subjetivo de
    # frustração. A receita das recargas atendidas entra explicitamente
    # na função objetivo. Estes termos ficam zerados até que o custo de
    # qualidade de serviço seja estudado com maior profundidade.
    "final_unserved_penalty": 0.0,
    "backlog_penalty": 0.0,

}

# ============================================================
# TARIFA ELÉTRICA E MODELO COMERCIAL DE RECARGA
# ============================================================

TARIFF = {
    # CLI preserva referência anterior; a interface envia a política por execução.
    "service_policy": {"mode": "maximum", "target": 0.98, "period": "monthly",
                       "period_target": 0.95, "unserved_penalty": 0.0, "waiting_penalty": 0.0},
    # Caso de referência: CPFL Paulista, Grupo A4, modalidade Verde,
    # bandeira verde, vigência a partir de 24/04/2026.
    #
    # Fonte regulatória:
    # CPFL Paulista, Tarifas CPFL Empresas - Paulista,
    # Resolução Homologatória ANEEL nº 3.579/2026.
    # https://www.cpfl.com.br/empresas/tarifas-cpfl-paulista
    "utility": "CPFL Paulista",
    "consumer_group": "A4",
    "tariff_modality": "green",
    "tariff_flag": "green",

    # Tarifas reguladas sem tributos [R$/kWh].
    # A4 Verde, bandeira verde:
    # fora de ponta = TUSD 164,16 + TE 272,82 [R$/MWh];
    # ponta = TUSD 1.351,57 + TE 431,88 [R$/MWh].
    "energy_offpeak_before_tax_brl_per_kwh": 0.43698,
    "energy_peak_before_tax_brl_per_kwh": 1.78345,

    # Demanda A4 Verde sem tributos [R$/kW.mês].
    "demand_before_tax_brl_per_kw_month": 16.53,

    # ICMS para consumo comercial não residencial em São Paulo: 18%.
    # Fonte: SEFAZ-SP, RICMS/2000, art. 52, e RC 33164/2026.
    # https://legislacao.fazenda.sp.gov.br/Paginas/art052.aspx
    "icms_fraction": 0.18,

    # PIS/COFINS CPFL Paulista de julho de 2026.
    # As alíquotas variam mensalmente e devem ser atualizadas quando
    # outra data-base for utilizada.
    # https://www.cpfl.com.br/paulista/pis-cofins
    "pis_fraction": 0.0063,
    "cofins_fraction": 0.0285,

    # Horário de ponta adotado para o dia útil representativo [h].
    # O Grupo A4 Verde possui apenas ponta e fora de ponta.
    "peak_start_hour": 18.0,
    "peak_end_hour": 21.0,

    # Demanda contratada ótima como variável contínua [kW].
    # O limite máximo representa o teto contratual/manual nos modos
    # "manual" e "minimum". No modo "bdgd", ele e ignorado e a demanda
    # contratada pode ser otimizada ate a capacidade fisica estimada da rede.
    # Como o horizonte atual usa um dia representativo, o valor ótimo
    # deve ser entendido como aproximação; a formulação anual futura
    # representará melhor os picos mensais de faturamento.
    "contracted_demand_min_kw": 0.0,
    "contracted_demand_max_kw": 100.0,
    "demand_exceedance_tolerance_fraction": 0.05,
    "demand_exceedance_multiplier": 2.0,

    # Preço de venda da recarga ao cliente, já entendido como preço
    # final cobrado [R$/kWh]. Não existe tarifa nacional regulada:
    # a ANEEL permite preços livremente negociados na recarga pública.
    # Referência de mercado adotada: R$ 1,99/kWh.
    # https://www.gov.br/aneel/pt-br/assuntos/veiculos-eletricos
    # https://www.turbostation.com.br/
    "charging_price_brl_per_kwh": 1.99,

    # Parcela variável comercial: plataforma, meios de pagamento e
    # custos transacionais. Hipótese gerencial, não tarifa regulada.
    "charging_variable_fee_fraction": 0.08,
}

# ============================================================
# PARÂMETROS DO CENÁRIO BASE
# ============================================================

# Modo executado pelo main.py:
# "daily" preserva o estudo detalhado de 24 h em passos de 15 min;
# "annual" executa um ano civil completo em passos horários.
SIMULATION_MODE = "annual"

SCENARIO_BASE = {
    # Horizonte total de simulação [h].
    "horizon_h": 24.0,

    # Passo temporal [h]. 0.25 h equivale a 15 minutos.
    "dt_h": 0.25,

    # Semente para reprodutibilidade dos perfis sintéticos.
    "seed": 42,

    # Modo do limite da rede:
    # grid_only: limita apenas a importação da rede.
    # site_total: considera carga local dentro do limite total do site.
    "grid_limit_mode": "grid_only",

    # Limite de exportação para a rede [kW]. 0 significa zero exportação.
    "export_limit_kw": 0.0,

    # Carga local base do estabelecimento [kW].
    "local_base_kw": 25.0,

    # Pico local diurno [kW].
    "local_midday_peak_kw": 70.0,

    # Pico local noturno [kW].
    "local_evening_peak_kw": 45.0,

    # Demanda base de recarga EV [kW].
    "ev_base_kw": 10.0,

    # Pico matinal de recarga EV [kW].
    "ev_morning_peak_kw": 90.0,

    # Pico vespertino de recarga EV [kW].
    "ev_evening_peak_kw": 150.0,

}

# O modo anual é independente do diário. A primeira versão utiliza
# resolução horária (8.760 passos em anos não bissextos), adequada à
# validação econômica no HOMER Pro. Os multiplicadores de carga são
# hipóteses configuráveis; valores unitários preservam a mesma curva
# diária em todos os tipos de dia até existirem dados medidos.
SCENARIO_ANNUAL = {
    **SCENARIO_BASE,
    "horizon_h": float((366 if calendar.isleap(SOLAR_REFERENCE_YEAR) else 365) * 24),
    "dt_h": 1.0,
    "calendar_start": f"{SOLAR_REFERENCE_YEAR}-01-01 00:00:00",
    "weekday_load_factor": 1.0,
    "saturday_load_factor": 1.0,
    "sunday_load_factor": 1.0,
    "monthly_load_factors": [1.0] * 12,
    # Datas sem aplicação de tarifa de ponta. A lista deve ser ajustada
    # ao ano/local do estudo quando o calendário tarifário for refinado.
    "holiday_dates": [],
}

# No horizonte anual, a variável binária do sentido do PCS pode ser
# relaxada para reduzir fortemente o tempo de solução. A eficiência
# menor que 100% e o custo positivo de throughput tornam carga e
# descarga simultâneas economicamente dominadas; o pós-processamento
# continua verificando e reportando qualquer ocorrência. No diário,
# a exclusividade binária permanece exata.
ANNUAL_RELAX_BESS_BINARY = True

# Sensibilidades multiplicam muitas soluções e ficam desabilitadas por
# padrão no modo anual. O cenário-base anual continua sendo executado.
RUN_SENSITIVITIES_IN_ANNUAL_MODE = False


# ============================================================
# TESTE DE SENSIBILIDADE
# ============================================================

GRID_SENSITIVITY = {
    "enabled": True,

    # "relative": fatores da demanda contratada;
    # "range": intervalo absoluto;
    # "manual": lista explícita.
    "mode": "relative",

    # Parâmetros do modo relative.
    "factors": [0.5, 0.8, 1.0, 1.2, 1.5, 2.0],
    "rounding_kw": 10.0,

    # Parâmetros do modo range.
    "minimum_kw": None,
    "maximum_kw": None,
    "step_kw": None,

    # Parâmetro do modo manual.
    "values_kw": None,

    # Inclui sempre a demanda contratada do cenário-base.
    "include_base_limit": True,
}

# Sensibilidade do preço comercial de recarga por fatores relativos.
# A faixa acompanha automaticamente qualquer atualização do valor-base
# TARIFF["charging_price_brl_per_kwh"].
CHARGING_PRICE_SENSITIVITY = {
    "enabled": True,
    "factors": [0.75, 0.90, 1.00, 1.10, 1.25],
    "include_base": True,
}

# ============================================================
# CONFIGURAÇÃO DO PERFIL SOLAR REALISTA
# ============================================================

# Define se o modelo deve usar pvlib para gerar pv_cf realista.
USE_REALISTIC_PV_PROFILE = True

# Forma de converter a série anual para o horizonte do AMPL:
# "annual_average"  -> dia médio anual (uso exploratório);
# "specific_period" -> período meteorológico real iniciado em
#                      PV_PROFILE_START_TIME.
PV_PROFILE_MODE = "annual_average"

# Data inicial usada para recortar o perfil solar anual.
# Deve existir dentro do ano definido em PV_SYSTEM["year"].
PV_PROFILE_START_TIME = f"{SOLAR_REFERENCE_YEAR}-01-01 00:00:00"

# ============================================================
# LOCALIZAÇÃO DO SISTEMA FV
# ============================================================

PV_LOCATION = {
    # Latitude do local em graus decimais.
    "latitude": -22.817,

    # Longitude do local em graus decimais.
    "longitude": -47.069,

    # Altitude aproximada do local [m].
    "altitude_m": 650.0,

    # Fuso horário local.
    "timezone": "America/Sao_Paulo",

    # Nome do local.
    "name": "Campinas_SP",
}

# ============================================================
# CONFIGURAÇÃO SOLARIMÉTRICA DO ARRANJO FV
# ============================================================

PV_SYSTEM = {
    # Ano meteorológico usado na simulação solar.
    "year": SOLAR_REFERENCE_YEAR,
    "api_url": "https://re.jrc.ec.europa.eu/api/v5_3/",
    "radiation_database": "PVGIS-ERA5",

    # Inclinação dos módulos [graus].
    "surface_tilt_deg": 20.0,

    # Azimute dos módulos [graus].
    # Convenção pvlib:
    # 0   = norte
    # 90  = leste
    # 180 = sul
    # 270 = oeste
    # Para Brasil, normalmente usa-se 0° para orientação norte.
    "surface_azimuth_deg": 0.0,
    # Potência de referência para normalização [kW].
    # Não é a potência ótima do sistema.
    # A potência ótima continua sendo decidida no AMPL.
    "reference_capacity_kw": 1.0,

    # Relação entre potência nominal DC dos módulos [kWp] e
    # potência nominal AC do inversor [kWac].
    "dc_ac_ratio": 1.20,

    # Eficiência nominal do inversor no modelo PVWatts.
    "inverter_nominal_efficiency": 0.96,

    # Coeficiente térmico de potência dos módulos [1/°C].
    "gamma_pdc_per_c": -0.0035,

    # Perdas globais do sistema FV [%].
    "losses_percent": 14.0,

    # Modelo térmico para temperatura da célula.
    # Opções: "faiman" ou "sapm".
    "temperature_model": "faiman",

    # Coeficientes do modelo térmico de Faiman.
    "faiman_u0": 25.0,
    "faiman_u1": 6.84,

    # Coeficientes do modelo térmico SAPM.
    "sapm_a": -3.47,
    "sapm_b": -0.0594,
    "sapm_delta_t": 3.0,
}
