# Atualização: otimização econômica e qualidade de atendimento

Data: 04/09/2026. Complemento técnico aos relatórios arquivados, que permanecem como registros das versões anteriores.

## Segurança e compatibilidade

Backup anterior às alterações: `backups/pre_modo_economico_20260904.tar.gz`.
O código de trabalho permanece na pasta Otimização de Eletropostos, não no backup.
O modo de máximo atendimento continua disponível: maximiza a energia atendida, minimiza a espera e então minimiza o custo, preservando as prioridades anteriores.
A interface passa a iniciar no modo econômico, com meta global preferencial de 98% e proteção mensal preferencial de 95%. Execuções diretas sem política explícita mantêm o modo máximo atendimento.

## Formulação econômica

No padrão preferencial, o modo econômico primeiro minimiza o déficit em relação às metas e depois minimiza o custo líquido sem piorar o menor déficit encontrado. Quando a meta é fisicamente possível, ela funciona como piso; quando não é, o modelo devolve o melhor atendimento alcançável e quantifica o corte de recarga. Isso distingue insuficiência para recarga flexível de inviabilidade física do barramento. A opção de meta rígida mantém o piso obrigatório e declara inviável o caso que não o alcançar. A meta nunca é uma ordem para rejeitar exatamente o complemento da porcentagem escolhida.

Para cada chegada de energia a, define-se energia solicitada R[a], energia atendida x[a,t], rejeitada r[a] e pendente ao final p[a]:

    soma_t x[a,t] + r[a] + p[a] = R[a]
    soma_a,t x[a,t] >= meta_global × soma_a R[a]

Os pares permitidos (a,t) limitam o atendimento à chegada e aos intervalos seguintes dentro da janela de recarga configurada, sem antecipação nem transferência além do prazo. O prazo é discretizado pela resolução temporal do modelo. A energia expira ao atingir o prazo; chegadas cujo prazo ultrapassa o horizonte podem terminar pendentes, mas essa energia também conta como não atendida para a meta.

Quando a proteção mensal ou diária está ativa, para cada grupo de chegadas g:

    soma_a_em_g (r[a] + p[a]) <= (1 - meta_periodo) × soma_a_em_g R[a]

O agrupamento usa a origem da demanda, não o horário da entrega. Assim, uma recarga que cruza a meia-noite ou o fim do mês é contabilizada no período correto. A proteção evita concentrar todas as perdas em poucos períodos; não garante atendimento individual de cada veículo. A demanda local continua obrigatória.

No modo econômico, as antigas restrições de atendimento imediato são desativadas: o otimizador pode usar a janela de recarga. No modo de referência, permanecem como antes. Limites de carregadores, balanço elétrico, SOC, potência de bateria e limites da rede permanecem obrigatórios.

## Penalidades opcionais

Pode-se acrescentar custo de não atendimento, em R$/kWh, aplicado à energia expirada e pendente ao final, e custo de espera, em R$/kWh·h, aplicado à integral do estoque de energia em espera. Ambos começam em zero. As receitas já diminuem quando se atende menos energia; a penalidade é um custo adicional, não a receita perdida novamente. Espera energética não representa tempo médio de fila de veículos.

## Limites elétricos e demanda contratada

O modo BDGD continua utilizando os limites estimados da rede. Sem teto contratual do usuário, não se introduz um teto manual adicional. Com a opção de limitar a demanda contratada, preserva-se o menor limite aplicável e o teto do contrato. A caracterização por APIs não se torna potência disponível. A capacidade BDGD permanece uma estimativa com as limitações documentadas de cadastro, curvas típicas e ausência de medições completas; não substitui parecer de acesso da concessionária.

## Interface e saídas

- Escolha modo econômico ou referência, meta global, proteção mensal/diária, meta preferencial ou rígida e penalidades.
- A opção de comparar 95%, 98%, 99% e 100% executa quatro otimizações completas, mantendo o mesmo ponto, limite contratual e proteção por período. Pode levar aproximadamente quatro vezes o tempo de uma execução; a proteção escolhida pode tornar uma meta global mais baixa redundante.
- Curvas cronológicas exibem todo o horizonte simulado, sem médias que escondam picos, com seleção de janela, além do detalhe diário. Não se cria artificialmente um ano quando a execução é diária.
- Gráficos mostram carga local, recarga solicitada/atendida, importação e limite, FV, carga/descarga de BESS e SOC. SOC não se aplica quando a solução não instala bateria.
- Indicadores mostram atendimento energético, energia expirada e pendente ao final; tabelas mensais/diárias mostram os piores períodos. No modo legado, percentuais por período são baseados em fluxos e podem exceder 100% por transferência de espera, sinalizada na interface.
- O corte total de recarga é solicitado menos atendido e equivale, dentro da tolerância numérica, à energia expirada mais a pendência final. Ele não é curtailment de geração FV.
- Comparação custo × atendimento utiliza execuções comparáveis da sessão, mantendo até dez no histórico. Casos inviáveis permanecem identificados e não recebem despacho fictício.
- São exportadas séries CSV, qualidade mensal/diária e PNG cronológico, além dos resultados anteriores. Política de atendimento acompanha os parâmetros e resultados para auditoria.

Custo líquido negativo decorre das receitas consideradas no objetivo: não significa investimento inicial negativo nem prova, por si só, de rentabilidade integral do empreendimento.

## Validação controlada anual

Teste sintético de 8.760 horas: carga local 10 kW; recarga usual 20 kW; doze picos curtos de 200 kW; rede constante de 300 kW; sem FV/BESS; janela de uma hora e proteção mensal de 95%. Não é uma avaliação de ponto real da BDGD.

| Política | Atendimento obtido | Demanda contratada |
|---|---:|---:|
| Máximo atendimento | 100% | 210 kW |
| Econômico 95% | 95% | 30 kW |
| Econômico 98% | 98% | 30 kW |
| Econômico 99% | 99% | 62,2 kW |
| Econômico 100% | 100% | 210 kW |

Os testes verificaram metas globais e mensais e respeito ao limite da rede. Evidenciam o efeito esperado dos picos breves, não resultados garantidos para outros perfis ou tarifas. O comportamento econômico pode também rejeitar energia em horários de menor retorno, não apenas nos maiores picos.

Também foram validados no solver quatro casos curtos: transferência entre meses dentro do prazo, expiração sem atendimento tardio, detecção de meta inviável e pendência ao final do horizonte. A suíte automatizada cobre interface, comparação em lote, transporte de parâmetros e agrupamento pela data de chegada, além das funcionalidades anteriores.

Na revisão posterior, um caso SMART + FV controlado, sem produção FV e com 40 kWh solicitados diante de apenas 20 kWh fisicamente disponíveis, confirmou: meta preferencial de 100% retorna solução válida com 50% atendidos e déficit de 20 kWh; a mesma meta marcada como rígida retorna inviável. O gráfico custo × atendimento passou a ser gerado como figura explícita, incluindo ponto único e curvas separadas por configuração.

## Limitações e próximos avanços

O atendimento é modelado por energia e coortes temporais, não por veículos individuais, conectores ocupados, filas físicas ou compromissos individuais de partida. Esses indicadores exigem sessões com chegada, saída, energia solicitada, potência admissível e número de vagas. Dados medidos de rede e consumo e séries reais de recarga continuam importantes. Recomenda-se avaliar a sensibilidade às metas, às penalidades e à proteção diária, e validar a solução com séries fora da amostra de dimensionamento.

## Referências temporais independentes

A análise elétrica vigente utiliza exclusivamente a edição BDGD CPFL Paulista de 31/12/2025. Seus doze valores mensais e curvas típicas são reconstruídos no calendário civil de 2025. O perfil solar permanece PVGIS/ERA5 2023, último ano integral validado na fonte adotada. Os vetores podem ser combinados por mês, dia da semana e intervalo operacional, mas as saídas registram separadamente `bdgd_reference_date`, `network_profile_calendar_start` e o ano meteorológico: 2023 não é apresentado como ano dos dados elétricos.

## Recuperação topológica nacional conservadora

As distribuidoras podem cadastrar ligações internas ou trechos de diagrama com situação contábil `0`, embora eles sejam necessários para ligar o PAC inicial ao grafo operacional. A rotina nacional não contém exceções pelo nome da concessionária ou pelo código do condutor. Primeiro procura um caminho apenas por segmentos contábeis operacionais, chaves ativas fechadas e reguladores ativos. Somente se necessário, permite segmentos trifásicos de códigos contábeis explicitamente configurados como conectores de topologia, preferindo lexicograficamente o menor número desses conectores e limitando o caminho a oito por padrão.

Essas pontes não fornecem ampacidade, impedância, comprimento elétrico ou situação operacional; portanto, não podem elevar nem reduzir diretamente o limite térmico e não entram na queda de tensão. Chaves abertas continuam excluídas. Todos os condutores elétricos reais do caminho continuam sujeitos à validação de fases, `CMAX`, `R1` e `X1`. O relatório registra se a recuperação foi usada, quantidade e identificadores. Se a ponte não alcançar a rede validável ou exceder o limite de segurança, a capacidade permanece indisponível.

No ponto ENEL SP `-23.4503334, -46.7548943`, quatro conectores internos foram necessários. Depois deles, o caminho validado contém 348 trechos elétricos e 18 chaves fechadas; o gargalo real é `5288369S5`, com teto térmico preliminar de 3.487,82 kW. Os conectores não participam desse valor. A estimativa residual anual resultante continua uma triagem conservadora porque desconta a carga agregada conforme as limitações já documentadas; resultado zero não comprova falta física de capacidade.
