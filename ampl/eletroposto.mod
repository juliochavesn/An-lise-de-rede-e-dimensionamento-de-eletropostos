# ============================================================
# MODELO AMPL - ELETROPOSTO COM FV + BESS
# ============================================================

# ============================================================
# CONJUNTO TEMPORAL
# ============================================================

# Conjunto ordenado dos intervalos temporais.
#
# Exemplo:
# T = {1,2,3,...,96}
#
# para um horizonte de 24 h com resolução de 15 min.
set T ordered;

# Meses/períodos de faturamento representados no horizonte.
set M ordered;


# ============================================================
# PARÂMETROS OPERACIONAIS
# ============================================================

# Passo temporal [h].
#
# Exemplo:
# 0.25 h = 15 min
param dt > 0;

# Horizonte total da simulação [h].
param horizon_h > 0;

# Modo de limitação da rede:
#
# 0 -> limita apenas importação da rede.
#
# 1 -> considera também carga local dentro
#      do limite total do site.
param grid_limit_mode_id integer >= 0 <= 1;

# Flags tecnológicas.
#
# use_pv = 1 -> habilita FV
# use_pv = 0 -> desabilita FV
#
# use_bess = 1 -> habilita BESS
# use_bess = 0 -> desabilita BESS
param use_pv binary;
param use_bess binary;


# ============================================================
# SÉRIES TEMPORAIS
# ============================================================

# Demanda EV solicitada [kW].
param request_kw {T} >= 0;

# Carga local do estabelecimento [kW].
param local_load_kw {T} >= 0;

# Limite de importação da rede [kW].
param grid_limit_kw {T} >= 0;

# Tarifa da energia da rede.
param price_grid {T} >= 0;

# Perfil FV normalizado.
#
# 0 <= pv_cf <= 1
#
# Representa o fator de capacidade FV horário.
param pv_cf {T} >= 0 <= 1;

# Associação de cada intervalo ao mês de faturamento e fração daquele
# mês coberta pelo horizonte (1 no ano completo).
param month_of_t {T} integer, in M;
param month_weight {M} > 0, <= 1;

# Limite máximo de exportação [kW].
param export_limit_kw >= 0;


# ============================================================
# LIMITES TECNOLÓGICOS
# ============================================================

# Potência máxima total dos carregadores [kW].
param charger_max_kw >= 0;
param ev_max_delay_steps integer >= 1;
param maximum_pv_curtailment_fraction >= 0, <= 1;

# Potência máxima permitida para FV [kW].
param pv_max_kw >= 0;

# Capacidade energética máxima do BESS [kWh].
param bess_e_max_kwh >= 0;

# Potência máxima do BESS [kW].
param bess_p_max_kw >= 0;

# Eficiência de carga do BESS.
param bess_eta_ch > 0 <= 1;

# Eficiência de descarga do BESS.
param bess_eta_dis > 0 <= 1;

# Fração inicial do SOC.
#
# Exemplo:
# 0.0 -> bateria vazia
# 0.5 -> metade carregada
# 1.0 -> totalmente carregada
param bess_soc_init_frac >= 0 <= 1;

# Limites operacionais do SOC em relação à capacidade nominal.
# Exemplo 0,10-0,90: janela útil de 80% da energia instalada.
param bess_soc_min_frac >= 0 <= 1;
param bess_soc_max_frac >= bess_soc_min_frac <= 1;

# Duração mínima e máxima permitida para o BESS [h].
param bess_duration_min_h > 0;
param bess_duration_max_h >= bess_duration_min_h;


# ============================================================
# PARÂMETROS ECONÔMICOS
# ============================================================

# Custos reais, anualização e peso temporal.
param pv_capex_per_kwp >= 0;              # [R$/kWp]
param pv_fixed_om_per_kwp_year >= 0;      # [R$/kWp.ano]
param pv_capital_recovery_factor >= 0;    # [1/ano]

param bess_energy_capex_per_kwh >= 0;     # [R$/kWh instalado]
param bess_power_capex_per_kw >= 0;       # [R$/kW instalado]
param bess_fixed_om_per_kw_year >= 0;     # [R$/kW.ano]
param bess_capital_recovery_factor >= 0;  # [1/ano]
param bess_degradation_cost_per_kwh_throughput >= 0; # [R$/kWh]

# Fração de um ano representada pelo horizonte operacional.
# Para 24 h: 24/8760 = 1/365.
param horizon_weight_years > 0;

# Parâmetros comerciais e de demanda contratada.
param contracted_demand_min_kw >= 0;                # [kW]
param contracted_demand_max_kw >= contracted_demand_min_kw; # [kW]
param demand_tariff_brl_per_kw_month >= 0;          # [R$/kW.mês]
param demand_exceedance_tolerance_fraction >= 0;    # [fração]
param demand_exceedance_multiplier >= 0;            # [adimensional]
param charging_price_brl_per_kwh >= 0;              # [R$/kWh]
param charging_net_price_brl_per_kwh >= 0;          # [R$/kWh]
param charging_variable_fee_fraction >= 0, <= 1;    # [fração]

# Penalização por curtailment FV.
param curtailment_penalty >= 0;

# Penalização backlog final.
param final_unserved_penalty >= 0;

# Penalização backlog acumulado.
param backlog_penalty >= 0;

# Piso atualizado pelo Python após encontrar o atendimento máximo
# tecnicamente possível para cada configuração.
param served_energy_quality_floor_kwh >= 0 default 0;

# Teto atualizado pelo Python após minimizar o backlog acumulado
# entre as soluções que preservam o atendimento máximo.
# A grandeza limitada é sum {t in T} backlog_kwh[t]. Apesar do
# sufixo histórico "_kwh", a soma representa uma medida discreta
# de energia em espera ao longo dos intervalos [kWh.intervalo].
param backlog_quality_ceiling_kwh >= 0 default 1e30;

# ============================================================
# POLÍTICA ECONÔMICA E QUALIDADE DO ATENDIMENTO EV
# ============================================================

# Seleciona a formulação de atendimento:
# 0 = referência lexicográfica de máximo atendimento;
# 1 = minimização econômica com metas e coortes de chegada.
param economic_service_mode binary default 0;       # [0/1]

# Define se as metas global e por período são obrigatórias:
# 0 = metas preferenciais; déficits fisicamente inevitáveis são medidos;
# 1 = metas rígidas; qualquer déficit torna o caso inviável.
param strict_service_targets binary default 0;      # [0/1]

# Fração mínima da energia solicitada que deve ser atendida em
# todo o horizonte no modo econômico (ex.: 0,98 = 98%).
param service_target >= 0, <= 1 default 0.98;       # [fração]

# Fração mínima de atendimento exigida separadamente em cada
# grupo temporal QG (dia, mês ou outro agrupamento criado no Python).
param period_service_target >= 0, <= 1 default 0.95; # [fração]

# Penalidade econômica da energia de recarga definitivamente não
# atendida: energia expirada mais backlog remanescente no horizonte.
param ev_unserved_cost >= 0 default 0;              # [R$/kWh]

# Penalidade econômica do tempo de espera energético. Multiplica
# dt * sum backlog_kwh, resultando em kWh.h na função objetivo.
param ev_waiting_cost >= 0 default 0;               # [R$/(kWh.h)]

# Instantes de chegada das solicitações EV. Cada a em EA define
# uma coorte de energia que entra no sistema no intervalo a.
set EA within T;

# Pares (a,t) permitidos para atendimento: a é a chegada e t é
# um intervalo dentro da janela máxima de espera dessa coorte.
set EV_ARCS within EA cross T;

# Grupos usados para avaliar qualidade por período. Podem representar
# dias, meses ou ficar vazios quando não há proteção adicional.
set QG;

# Associa cada coorte de chegada a ao seu grupo temporal g em QG.
param quality_group {EA} default 0;

# Energia da coorte que chegou em a e é efetivamente fornecida em t.
var cohort_served {EV_ARCS} >= 0;                   # [kWh]

# Energia da coorte a que completou a janela máxima de espera sem
# ser atendida. Representa corte definitivo dentro do horizonte.
var cohort_rejected {EA} >= 0;                      # [kWh]

# Energia ainda pendente ao final do horizonte porque a janela de
# espera da coorte ultrapassa last(T); não é rejeição antecipada.
var cohort_pending {EA} >= 0;                       # [kWh]

# Folga da meta de atendimento global. No modo preferencial registra
# quanto faltou para a meta; no modo rígido é forçada a zero.
var global_target_shortfall_kwh >= 0;               # [kWh]

# Folga da meta de atendimento de cada grupo temporal g.
var period_target_shortfall_kwh {QG} >= 0;          # [kWh]

# Após minimizar as folgas, o Python fixa este teto para que a etapa
# de custo não piore a melhor qualidade de atendimento encontrada.
param target_shortfall_ceiling_kwh >= 0 default 1e30; # [kWh]

# Conservação de energia por coorte: toda solicitação que chega
# em a deve terminar atendida, rejeitada ou ainda pendente.
subject to Cohort_Balance {a in EA}:
    sum {(aa,t) in EV_ARCS: aa=a} cohort_served[aa,t]
      + cohort_rejected[a] + cohort_pending[a] = request_kw[a]*dt;

# Se a janela da coorte ultrapassa o horizonte, ela não pode ser
# rejeitada antes de vencer; eventual saldo é classificado como pendente.
subject to Cohort_No_Early_Rejection {a in EA: a+ev_max_delay_steps > last(T)}:
    cohort_rejected[a] = 0;

# Se a janela termina dentro do horizonte, não pode sobrar energia
# pendente: o saldo deve ter sido atendido ou rejeitado ao expirar.
subject to Cohort_No_Late_Pending {a in EA: a+ev_max_delay_steps <= last(T)}:
    cohort_pending[a] = 0;

# Limita, em cada grupo temporal, a energia não atendida à parcela
# permitida por period_service_target. A folga mantém o problema
# solucionável no modo preferencial e quantifica a insuficiência física.
subject to Period_Service_Floor {g in QG}:
    sum {a in EA: quality_group[a]=g} (cohort_rejected[a]+cohort_pending[a])
      <= (1-period_service_target)*sum {a in EA: quality_group[a]=g} request_kw[a]*dt
         + period_target_shortfall_kwh[g];

# No modo rígido, elimina todas as folgas periódicas; cada grupo
# deve cumprir integralmente period_service_target.
subject to Strict_Period_Targets {g in QG: strict_service_targets=1}:
    period_target_shortfall_kwh[g] = 0;


# ============================================================
# VARIÁVEIS DE DECISÃO
# ============================================================

# Potência EV efetivamente atendida [kW].
var p_served_kw {T} >= 0;

# Backlog energético acumulado [kWh].
#
# Representa energia EV ainda não atendida.
var backlog_kwh {T} >= 0;

# Importação da rede [kW].
var p_grid_import_kw {T} >= 0;

# Exportação da rede [kW].
var p_grid_export_kw {T} >= 0;

# Energia EV efetivamente atendida no intervalo [kWh].
var e_served_kwh {T} >= 0;

# Energia EV que atingiu o prazo máximo sem atendimento [kWh].
var expired_unserved_kwh {T} >= 0;

# ============================================================
# SISTEMA FV
# ============================================================

# Potência ótima instalada FV [kW].
var pv_size_kw >= 0, <= pv_max_kw;

# Potência FV utilizada [kW].
var p_pv_used_kw {T} >= 0;

# Curtailment FV [kW].
#
# Energia solar disponível mas não utilizada.
var p_pv_curt_kw {T} >= 0;


# ============================================================
# SISTEMA BESS
# ============================================================

# Capacidade energética ótima do BESS [kWh].
var bess_e_kwh >= 0, <= bess_e_max_kwh;

# Potência ótima do BESS [kW].
var bess_p_kw >= 0, <= bess_p_max_kw;

# Potência de carga do BESS [kW].
var p_bess_ch_kw {T} >= 0;

# Potência de descarga do BESS [kW].
var p_bess_dis_kw {T} >= 0;

# Estado operacional do conversor:
# 1 -> carga habilitada; 0 -> descarga habilitada ou espera.
# Carga e descarga iguais a zero representam o estado de espera.
var bess_charge_mode {T} binary;

# Estado de carga do BESS [kWh].
var soc_kwh {T} >= 0;

# Pico de importação e parcelas faturáveis de demanda.
var monthly_peak_grid_kw {M} >= 0;
var contracted_demand_kw >= contracted_demand_min_kw,
                         <= contracted_demand_max_kw;
var demand_above_contract_kw {M} >= 0;
var demand_exceedance_kw {M} >= 0;



# ============================================================
# RESTRIÇÕES DA REDE
# ============================================================

# Limitação da rede no modo grid_only.
subject to Grid_Import_Limit_Grid_Only
{t in T : grid_limit_mode_id = 0}:

    p_grid_import_kw[t]
    <= grid_limit_kw[t];


# Limitação da rede considerando carga local.
subject to Grid_Import_Limit_Site_Total
{t in T : grid_limit_mode_id = 1}:

    p_grid_import_kw[t]
    + local_load_kw[t]

    <= grid_limit_kw[t];

# A demanda contratada otimizada representa a capacidade comercial
# escolhida para operação. A importação não pode ultrapassá-la;
# o limite físico da conexão continua sendo imposto separadamente.
subject to Contracted_Demand_Import_Limit {t in T}:
    p_grid_import_kw[t]
    <= contracted_demand_kw;


# Limite de exportação.
subject to Grid_Export_Limit {t in T}:

    p_grid_export_kw[t]
    <= export_limit_kw;


# ============================================================
# RESTRIÇÕES EV
# ============================================================

# Limite físico dos carregadores.
subject to Charger_Limit {t in T}:
    p_served_kw[t] <= charger_max_kw;

# No modo econômico, agrega no intervalo t toda energia despachada
# para as diferentes coortes de chegada e a liga ao balanço geral EV.
subject to Cohort_Dispatch {t in T: economic_service_mode=1}:
    e_served_kwh[t] = sum {(a,tt) in EV_ARCS: tt=t} cohort_served[a,tt];

# Registra em t a energia cuja janela máxima de espera acabou nesse
# intervalo sem atendimento. Essa energia deixa o backlog como expirada.
subject to Cohort_Expiration {t in T: economic_service_mode=1}:
    expired_unserved_kwh[t] = sum {a in EA: a+ev_max_delay_steps=t} cohort_rejected[a];

# Impõe a meta global no modo econômico. global_target_shortfall_kwh
# mede o déficit quando a meta é preferencial e fisicamente inalcançável.
subject to Economic_Service_Floor {dummy in 1..economic_service_mode}:
    sum {t in T} e_served_kwh[t] + global_target_shortfall_kwh
      >= service_target * sum {t in T} request_kw[t]*dt;

# Em política rígida, proíbe folga na meta global.
subject to Strict_Global_Target {dummy in 1..strict_service_targets}:
    global_target_shortfall_kwh = 0;


# Conversão de potência atendida para energia atendida.
subject to Served_Energy_Definition {t in T}:
    e_served_kwh[t] = p_served_kw[t] * dt;


# A energia atendida não pode exceder a energia solicitada no
# intervalo mais o backlog acumulado anterior.
subject to Served_Energy_Limit_First:
    e_served_kwh[first(T)]
    <= request_kw[first(T)] * dt;


subject to Served_Energy_Limit_Other {t in T : ord(t) > 1}:
    e_served_kwh[t]
    <= request_kw[t] * dt
    + backlog_kwh[prev(t)];

# Prioridade operacional da demanda nova.
#
# A parcela da solicitação corrente que pode ser atendida apenas com
# a capacidade já disponível da rede deve ser recarregada no próprio
# intervalo. Isso impede acumular backlog artificialmente para criar
# carga futura e absorver geração FV. Energia acima dessa capacidade
# continua podendo entrar no backlog e usar a janela de atraso.
subject to Immediate_EV_Service_Grid_Only_Full
{t in T :
    economic_service_mode = 0 and grid_limit_mode_id = 0
    and request_kw[t] + local_load_kw[t] <= grid_limit_kw[t]}:
    p_served_kw[t] >= request_kw[t];


subject to Immediate_EV_Service_Grid_Only_Partial
{t in T :
    economic_service_mode = 0 and grid_limit_mode_id = 0
    and request_kw[t] + local_load_kw[t] > grid_limit_kw[t]
    and grid_limit_kw[t] > local_load_kw[t]}:
    p_served_kw[t]
    >= grid_limit_kw[t] - local_load_kw[t];


# No modo site_total, a restrição de importação reserva explicitamente
# local_load_kw além da carga local presente no balanço de potência.
subject to Immediate_EV_Service_Site_Total_Full
{t in T :
    economic_service_mode = 0 and grid_limit_mode_id = 1
    and request_kw[t] + 2 * local_load_kw[t] <= grid_limit_kw[t]}:
    p_served_kw[t] >= request_kw[t];


subject to Immediate_EV_Service_Site_Total_Partial
{t in T :
    economic_service_mode = 0 and grid_limit_mode_id = 1
    and request_kw[t] + 2 * local_load_kw[t] > grid_limit_kw[t]
    and grid_limit_kw[t] > 2 * local_load_kw[t]}:
    p_served_kw[t]
    >= grid_limit_kw[t] - 2 * local_load_kw[t];


# A energia só pode expirar após completar a janela configurada.
subject to Disable_Early_Expiration
{t in T : ord(t) <= ev_max_delay_steps}:
    expired_unserved_kwh[t] = 0;


subject to Expiration_Cohort_Limit
{t in T : ord(t) > ev_max_delay_steps}:
    expired_unserved_kwh[t]
    <= request_kw[
        member(ord(t) - ev_max_delay_steps, T)
    ] * dt;


# Ao vencer o prazo, cada solicitação deve estar atendida ou
# contabilizada como não atendida.
subject to EV_Maximum_Delay
{t in T : ord(t) > ev_max_delay_steps}:
    backlog_kwh[t]
    <= sum {
        tau in T :
        ord(tau) > ord(t) - ev_max_delay_steps
        and ord(tau) <= ord(t)
    } request_kw[tau] * dt;


# Dinâmica do backlog energético.
subject to Backlog_Balance_First:
    backlog_kwh[first(T)]
    =
    request_kw[first(T)] * dt
    - e_served_kwh[first(T)]
    - expired_unserved_kwh[first(T)];


subject to Backlog_Balance_Other {t in T : ord(t) > 1}:
    backlog_kwh[t]
    =
    backlog_kwh[prev(t)]
    + request_kw[t] * dt
    - e_served_kwh[t]
    - expired_unserved_kwh[t];


# Preserva, na etapa econômica, o atendimento máximo encontrado na
# primeira etapa da otimização.
subject to Preserve_Maximum_EV_Service:
    sum {t in T} e_served_kwh[t]
    >= served_energy_quality_floor_kwh;

# Preserva, na etapa econômica, o menor backlog acumulado obtido
# sem reduzir o atendimento máximo. A soma tem unidade kWh.intervalo
# e funciona como medida discreta do tempo total de espera.
subject to Preserve_Minimum_EV_Backlog:
    sum {t in T} backlog_kwh[t]
    <= backlog_quality_ceiling_kwh;

# ============================================================
# RESTRIÇÕES FV
# ============================================================

# Desabilita FV quando o cenário não permite solar.
subject to Disable_PV:

    pv_size_kw
    <= use_pv * pv_max_kw;


# Toda geração FV potencial deve ser alocada entre energia
# aproveitada no site/exportação e curtailment.
subject to PV_Generation_Allocation {t in T}:

    p_pv_used_kw[t]
    + p_pv_curt_kw[t]

    = pv_cf[t] * pv_size_kw;


# Guardrail de projeto: limita a fração de geração FV cortada em todo
# o horizonte (diário ou anual).
subject to Maximum_PV_Curtailment:
    sum {t in T} p_pv_curt_kw[t] * dt
    <= maximum_pv_curtailment_fraction
       * sum {t in T} pv_cf[t] * pv_size_kw * dt;
# ============================================================
# RESTRIÇÕES BESS
# ============================================================

# Desabilita energia BESS quando necessário.
subject to Disable_BESS_Energy:

    bess_e_kwh
    <= use_bess * bess_e_max_kwh;


# Desabilita potência BESS quando necessário.
subject to Disable_BESS_Power:

    bess_p_kw
    <= use_bess * bess_p_max_kw;


# Limite de carga do BESS.
subject to BESS_Charge_Limit {t in T}:

    p_bess_ch_kw[t]
    <= bess_p_kw;


# Limite de descarga do BESS.
subject to BESS_Discharge_Limit {t in T}:

    p_bess_dis_kw[t]
    <= bess_p_kw;

# Carga e descarga compartilham o mesmo PCS/conversor. Além de
# representar o limite físico do equipamento, esta restrição evita
# usar simultaneamente toda a potência nominal nos dois sentidos.
subject to BESS_Shared_Converter_Limit {t in T}:
    p_bess_ch_kw[t] + p_bess_dis_kw[t]
    <= bess_p_kw;


# Exclusividade física do sentido do fluxo no BESS. Usa-se o limite
# tecnológico constante como Big-M para evitar o produto não linear
# entre a variável binária e a potência ótima bess_p_kw.
subject to BESS_Charge_Mode_Limit {t in T}:
    p_bess_ch_kw[t]
    <= bess_p_max_kw * bess_charge_mode[t];


subject to BESS_Discharge_Mode_Limit {t in T}:
    p_bess_dis_kw[t]
    <= bess_p_max_kw * (1 - bess_charge_mode[t]);


# Nos cenários sem BESS, fixa também o estado binário em zero.
subject to Disable_BESS_Mode {t in T}:
    bess_charge_mode[t] <= use_bess;


# Mantém a relação energia/potência dentro da faixa tecnológica
# coerente com a referência de custo do BESS.
subject to BESS_Minimum_Duration:
    bess_e_kwh >= bess_duration_min_h * bess_p_kw;

subject to BESS_Maximum_Duration:
    bess_e_kwh <= bess_duration_max_h * bess_p_kw;


# Dinâmica do estado de carga.
subject to SOC_Balance_First:
    soc_kwh[first(T)]
    =
    bess_soc_init_frac * bess_e_kwh
    + bess_eta_ch * p_bess_ch_kw[first(T)] * dt
    - p_bess_dis_kw[first(T)] * dt / bess_eta_dis;


subject to SOC_Balance_Other {t in T : ord(t) > 1}:
    soc_kwh[t]
    =
    soc_kwh[prev(t)]
    + bess_eta_ch * p_bess_ch_kw[t] * dt
    - p_bess_dis_kw[t] * dt / bess_eta_dis;
subject to SOC_Lower {t in T}:
    soc_kwh[t]
    >= bess_soc_min_frac * bess_e_kwh;


subject to SOC_Upper {t in T}:
    soc_kwh[t]
    <= bess_soc_max_frac * bess_e_kwh;


# Condição cíclica do horizonte: a bateria termina com a mesma energia
# com que iniciou. Vale tanto para o dia representativo quanto para o
# ano completo e impede consumo/acúmulo gratuito entre horizontes.
subject to Cyclic_SOC:
    soc_kwh[last(T)]
    = bess_soc_init_frac * bess_e_kwh;
# Garante que o BESS só carregue a partir de fontes reais.
subject to BESS_Charge_Source_Limit {t in T}:

    p_bess_ch_kw[t]
    <=
    p_grid_import_kw[t]
    + p_pv_used_kw[t];

# ============================================================
# BALANÇO DE POTÊNCIA
# ============================================================

# Conservação de potência do sistema.
#
# Fontes:
# - rede;
# - FV;
# - descarga do BESS.
#
# Demandas:
# - carga local;
# - recarga EV;
# - carga do BESS;
# - exportação.
subject to Power_Balance {t in T}:

    p_grid_import_kw[t]

    + p_pv_used_kw[t]

    + p_bess_dis_kw[t]

    =

    local_load_kw[t]

    + p_served_kw[t]

    + p_bess_ch_kw[t]

    + p_grid_export_kw[t];


# ============================================================
# DEMANDA CONTRATADA
# ============================================================

subject to Monthly_Peak_Definition {t in T}:
    monthly_peak_grid_kw[month_of_t[t]] >= p_grid_import_kw[t];

subject to Demand_Above_Contract {m in M}:
    demand_above_contract_kw[m]
    >= monthly_peak_grid_kw[m] - contracted_demand_kw;

subject to Demand_Exceedance {m in M}:
    demand_exceedance_kw[m]
    >= monthly_peak_grid_kw[m]
       - contracted_demand_kw
         * (1 + demand_exceedance_tolerance_fraction);


# ============================================================
# FUNÇÃO OBJETIVO
# ============================================================

# Primeiro nível do modo econômico com metas preferenciais:
# minimiza conjuntamente o déficit global e os déficits por período.
minimize Service_Target_Shortfall:
    global_target_shortfall_kwh + sum {g in QG} period_target_shortfall_kwh[g];

# Depois que o Python grava o menor déficit encontrado no teto,
# impede que a minimização de custo sacrifique esse atendimento.
subject to Preserve_Minimum_Target_Shortfall:
    global_target_shortfall_kwh + sum {g in QG} period_target_shortfall_kwh[g]
      <= target_shortfall_ceiling_kwh;

maximize EV_Service_Objective:
    sum {t in T} e_served_kwh[t];

# Segundo nível lexicográfico: entre as soluções com atendimento
# máximo, prioriza o atendimento tão cedo quanto possível.
minimize EV_Backlog_Objective:
    sum {t in T} backlog_kwh[t];


minimize Total_Cost:

    # ========================================================
    # CUSTO ENERGIA DA REDE
    # ========================================================

    sum {t in T}

        p_grid_import_kw[t]
        * price_grid[t]
        * dt


    # ========================================================
    # CUSTO DE DEMANDA CONTRATADA E ULTRAPASSAGEM
    # ========================================================

    + demand_tariff_brl_per_kw_month
        * sum {m in M} month_weight[m]
            * (
                contracted_demand_kw
                + demand_above_contract_kw[m]
                + demand_exceedance_multiplier
                  * demand_exceedance_kw[m]
            )


    # ========================================================
    # RECEITA LÍQUIDA DAS RECARGAS ATENDIDAS
    # ========================================================

    - charging_net_price_brl_per_kwh
        * sum {t in T}
            p_served_kw[t] * dt


    # ========================================================
    # INVESTIMENTO FV
    # ========================================================

    + horizon_weight_years
        * (
            pv_capex_per_kwp
            * pv_capital_recovery_factor
            + pv_fixed_om_per_kwp_year
        )
        * pv_size_kw


    # ========================================================
    # INVESTIMENTO BESS
    # ========================================================

    + horizon_weight_years
        * bess_capital_recovery_factor
        * (
            bess_energy_capex_per_kwh * bess_e_kwh
            + bess_power_capex_per_kw * bess_p_kw
        )

    + horizon_weight_years
        * bess_fixed_om_per_kw_year
        * bess_p_kw

    # Degradação cíclica por throughput bidirecional.
    + bess_degradation_cost_per_kwh_throughput
        * sum {t in T}
            (
                p_bess_ch_kw[t]
                + p_bess_dis_kw[t]
            ) * dt


    # ========================================================
    # CURTAILMENT FV
    # ========================================================

    + curtailment_penalty

        * sum {t in T}

            p_pv_curt_kw[t]
            * dt


    # ========================================================
    # BACKLOG ACUMULADO
    # ========================================================

    + backlog_penalty

        * sum {t in T}

            backlog_kwh[t]


    # ========================================================
    # BACKLOG FINAL
    # ========================================================

    + final_unserved_penalty
        * backlog_kwh[last(T)]
    + economic_service_mode * ev_unserved_cost
        * (sum {t in T} expired_unserved_kwh[t] + backlog_kwh[last(T)])
    + economic_service_mode * ev_waiting_cost * dt * sum {t in T} backlog_kwh[t];
