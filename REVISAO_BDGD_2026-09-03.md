# Revisão da BDGD e da metodologia — 03/09/2026

## Resultado principal

Foi corrigida uma falha sistêmica no filtro dos trechos: `SITCONT` (situação
contábil) não deve ser interpretada como `SIT_ATIV` (situação operacional).
O filtro antigo aceitava qualquer código começando por AT e excluía SF.
O novo filtro inclui AT1/SF/NIM/BOP/COM e exclui AT2/NOP/0/desconhecidos.
Nesta base de SSDMT, a mudança efetiva é incluir **54.947 trechos SF**.
Eles reconectam ramificações inteiras, não somente os próprios trechos.

Referência: ANEEL, discussão da seção 4.4.1 do Manual BDGD na
[Consulta Pública 041/2020](https://antigo.aneel.gov.br/web/guest/consultas-publicas?_participacaopublica_WAR_participacaopublicaportlet_ideDocumento=40574&_participacaopublica_WAR_participacaopublicaportlet_jspPage=%2Fhtml%2Fpp%2Fvisualizar.jsp&_participacaopublica_WAR_participacaopublicaportlet_tipoFaseReuniao=fase&p_p_cacheability=cacheLevelPage&p_p_col_count=2&p_p_col_id=column-2&p_p_col_pos=1&p_p_id=participacaopublica_WAR_participacaopublicaportlet&p_p_lifecycle=2&p_p_mode=view&p_p_state=normal).

## Escopo e varredura

Base: CPFL Paulista 63, data-base 31/12/2025, V11. Leitura integral das
camadas de trechos MT, chaves MT e reguladores MT, confrontadas com os
1.777 registros CTMT. Não é auditoria integral de todos os atributos das
demais camadas nem validação em campo.

| Camada | Registros lidos |
|---|---:|
| SSDMT | 1.810.130 |
| UNSEMT | 192.358 |
| UNREMT | 752 |
| CTMT | 1.777 |

No conjunto de 1.789.987 trechos operacionais associados aos CTMT auditados:

| Verificação topológica por PAC | Antes | Depois |
|---|---:|---:|
| Trechos ligados à origem do CTMT | 952.808 | 1.652.020 |
| Trechos ainda não ligados pelo modelo | — | 137.967 |

Ganho: **699.212 trechos** ligados à origem, em 1.472 alimentadores com melhora.
Após a correção, 1.352 alimentadores têm todos os seus trechos operacionais
ligados; 422 têm alguma descontinuidade; três não têm trechos nesse inventário.
Há ainda 225 trechos operacionais fora do conjunto associado aos CTMT auditados.
Uma descontinuidade no modelo não demonstra que a rede física esteja desligada.
Não foram criadas ligações por proximidade, nem fechadas chaves abertas.

O arquivo `outputs/auditoria_bdgd_20260903/topology_all_feeders.csv` permite
localizar cada caso. No SCA01, os 3.210 trechos operacionais ficaram ligados
à origem; no CRO03, 1.810 de 1.834; no MDE25, 593 de 593.

## Alterações de metodologia

- Curvas de cada classe normalizadas pela sua própria energia mensal antes
  da agregação: uma curva de escala maior não recebe peso energético artificial.
- Perfil diário extraído do calendário mensal completo, coerente com o anual.
- Transformador AT/MT compartilhado passa a considerar a soma das energias de
  todos os CTMT associados. A forma horária do alimentador local é usada como
  aproximação da simultaneidade; isso está identificado nos metadados, não é SCADA.
- Capacidade final combina separadamente margem do caminho e do transformador.
- Caminho com condutor de capacidade/impedância inválida ou fases incompatíveis
  com o modelo trifásico não recebe uma capacidade supostamente validada.
- PAC vazio/zero não une trechos sem relação. Falhas preservam identificação
  do ponto, alimentador e tipo de erro, em vez de apagar todo o diagnóstico.
- Busca espacial expande a caixa quando o candidato está no canto e verifica
  o raio efetivo em metros; usa o mesmo filtro operacional da topologia e mapa.
- Falhas em alimentadores com transformadores entre PACs MT ganham indicação
  dos equipamentos que exigem modelagem de transformação.

O modo padrão continua `limit_source="bdgd"`, com a semântica anterior.
Não foi imposto limite manual na análise válida. Os modos manual/minimum e
o fallback histórico permanecem. A interface continua bloqueando simulação
que tente interpretar esse fallback como disponibilidade BDGD.

## Testes geográficos — análise anual da rede

Valores em kW, arredondados. São estimativas conservadoras, não capacidade
de acesso homologada. Não foi executada nesta auditoria a otimização econômica
AMPL de cada ponto.

| Ponto | Alimentador | Mínima | Média | Máxima |
|---|---|---:|---:|---:|
| São Carlos: -22,0377531 / -47,8436565 | SCA01 | 0 | 162,81 | 772,80 |
| -22,9817847 / -46,9112778 | CRO03 | 0 | 83,16 | 739,07 |
| Original: -22,817 / -47,069 | MDE25 | 0 | 2.525,23 | 3.569,11 |
| Campinas: -22,9056 / -47,0608 | CAM17 | 0 | 474,66 | 1.342,53 |
| Piracicaba: -22,7253 / -47,6492 | NZE09 | 888,24 | 3.157,94 | 4.708,16 |
| Ribeirão Preto: -21,1775 / -47,8103 | MTN16 | 0 | 1.087,51 | 2.380,89 |
| Araraquara: -21,7946 / -48,1756 | PAI16 | 2.013,72 | 3.731,53 | 5.087,67 |
| Bauru: -22,3145 / -49,0587 | BAU23 | 0 | 13,60 | 676,18 |
| Franca: -20,5386 / -47,4008 | DMT14 | 0 | 2.052,19 | 3.890,55 |
| Americana: -22,7392 / -47,3313 | CVE23 | 0 | 674,41 | 1.623,85 |

Controles adicionais: coordenadas em Limeira, Rio Claro e São Paulo sem
SSDMT operacional encontrado em até 10 km nesta base; e um ponto rural AUX33
(-23,2313263554 / -48,4707382582) com caminho não validado e transformadores
entre PACs MT identificados no alimentador (29017492 e 43567008).
Consultar `point_tests.csv` para mensagens exatas e resultados da execução.

## O que ainda não foi resolvido

1. **Carga por ramal:** continua sendo descontada toda a carga do alimentador
   do gargalo do caminho. Isso pode superestimar a ocupação de ramais e produzir
   zeros excessivamente conservadores. O próximo passo é alocar as UCs aos PACs,
   UCBT aos UNTRMT, agregar a carga a jusante por elemento e calibrar perdas.
2. **Transformadores MT–MT:** há registros na base, mas atravessá-los exige
   relação de tensão, ligação de fases, potência e impedância. A leitura de um
   registro não equivale à implementação de um modelo elétrico válido.
3. **Fases, malhas e demais equipamentos:** a seleção de caminho não resolve
   fluxo de potência trifásico, divisão de corrente em malhas ou coordenação
   de chaves e elos fusíveis. Limites nominais não são autorização de acesso.
4. **Dados não medidos:** a energia mensal e curvas típicas não fornecem
   simultaneidade medida, tensão horária, reservas de acesso ou critério N-1.
5. **Qualidade cadastral:** PACs e vínculos ausentes, equipamentos sem parâmetros
   e áreas sem cobertura continuam exigindo diagnóstico, não preenchimento
   automático com capacidade fictícia.

Portanto, **zero de triagem não prova falta de capacidade real**, e
**inconclusivo não significa zero**. A revisão melhora substancialmente a
cobertura, mas não permite garantir cálculo válido para qualquer coordenada.

## Reprodução e segurança

Na pasta permanente do projeto: `.venv/bin/python audit_bdgd.py`.
O script preserva a coordenada de configuração e grava uma auditoria repetível.
As saídas por ponto contêm perfil anual, gráficos de 24 h e relatório detalhado.

Backup anterior às alterações:
`backups/pre_auditoria_bdgd_metodologia_20260903.tar.gz`.
Os arquivos de trabalho permanecem na pasta **Otimização de Eletropostos**;
o backup não foi editado. Validação automatizada: **48 testes aprovados**.
