# Planejamento logístico-elétrico — implementação de 24/09/2026

## Objetivo

Integrar os carregamentos rodoviários do PNL 2050 ao dimensionamento do eletroposto sem atribuir significado não documentado aos campos da base. A entrega converte o fluxo anualizado do segmento rodoviário mais próximo em cenários de demanda e injeta a curva horária escolhida no mesmo modelo AMPL já usado pela aplicação.

## Cadeia de cálculo

1. Seleção espacial do segmento PNL mais próximo.
2. Validação de `GTYPE = 1` para impedir a conversão indevida de ferrovias, hidrovias ou conectores.
3. Conversão de toneladas em viagens carregadas pela carga útil informada.
4. Inclusão de retornos vazios por viagem carregada, sem fator de equivalência de tráfego.
5. Aplicação das parcelas de eletrificação e de captura do eletroposto.
6. Conversão de eventos em kWh/dia pela energia por parada.
7. Distribuição da energia em 24 horas por perfil representativo normalizado.
8. Simulação do perfil no modelo existente, sujeita à BDGD, demanda contratada opcional, smart charging, metas de atendimento, FV e BESS.

As equações centrais são:

`viagens_carregadas_ano = toneladas_ano / carga_util_t`

`viagens_fisicas_dia = viagens_carregadas_ano * (1 + retornos_vazios_por_carregada) / dias_operacionais`

`recargas_dia = viagens_fisicas_dia * participacao_eletrica * captura_eletroposto`

`energia_dia_kWh = recargas_dia * energia_por_parada_kWh`

## Incerteza

P50 usa diretamente as hipóteses centrais informadas. P10 combina maior carga útil e menores retorno vazio, eletrificação, captura e energia por parada. P90 combina o sentido oposto. Esses percentis são cenários paramétricos e não percentis estatísticos calibrados em amostra de campo.

## Rastreabilidade

Cada execução salva em `simulation_inputs.json`:

- origem do perfil (`PNL` ou `synthetic`);
- segmento PNL e carregamento utilizado;
- cenário escolhido;
- hipóteses centrais;
- valores derivados do cenário enviado ao otimizador.

## Limitações atuais

- O perfil de 24 horas é representativo, não uma contagem horária observada.
- A conversão usa o segmento mais próximo, sem identificar ainda a sobreposição de fluxos ou sentidos.
- P10/P90 não incorporam correlação estatística entre parâmetros.
- A capacidade BDGD permanece uma triagem; não substitui estudo de acesso da distribuidora.
- A saturação rodoviária é indicador logístico e não capacidade elétrica.

## Próximas validações de campo

Calibrar carga útil, retorno vazio, participação elétrica, captura, energia por parada e distribuição horária por grupo de mercadoria e corredor. Depois disso, a seleção pode evoluir do ponto isolado para ranking de candidatos ao longo de um corredor.
