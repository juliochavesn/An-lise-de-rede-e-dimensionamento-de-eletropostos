# Integração nacional ANEEL e eletropostos existentes

## Versão atual — OCM exclusivo e triagem ampliada

A API de eletropostos OSM/Overpass foi removida. **Exibir eletropostos existentes**
consulta somente Open Charge Map, nos dois modos. O fundo cartográfico OSM
do Folium não é a API de cadastro de eletropostos e foi preservado.
As seções históricas abaixo descrevem versões anteriores.

### Triagem online

- Campos mensais UCMT: ENE, DEM, DIC e FIC, de janeiro a dezembro; DEM_CONT,
  CAR_INST e FAS_CON também são coletados. UCAT: energia e demanda de ponta
  e fora ponta, além de DIC/FIC. Nenhum endereço/identificador de cliente foi
  adicionado à projeção da consulta.
- Grupos separados por DIST, tipo de UC, circuito, data-base e situação
  cadastral. Não misturam UCAT/UCMT, circuitos, datas ou registros ativos e
  outras situações. São apenas as UCs retornadas no raio, não todo o circuito.
- Energia: soma dos valores mensais válidos na amostra. UCAT exige ambos os
  postos para compor o total. Nulos, negativos/inválidos não viram zero;
  contagens de valores válidos/zeros acompanham cada mês. Energia positiva
  com demanda zero recebe aviso, sem correção arbitrária.
- Demanda: maior valor **individual**, não soma de máximos de diferentes UCs.
  Ponta/fora ponta UCAT não são somadas. DIC/FIC apresentados como máximos
  individuais da amostra, nunca chamados de DEC/FEC.
- Referência: DATA_BASE quando válido; na ausência do campo (UCAT), usa a
  posição explicitamente informada na descrição do recurso ANEEL, registrando
  essa origem. Não usa a data de atualização da API como data-base.
- Continuidade: API DEC/FEC, até dez chaves próximas de DIST/CONJ/referência;
  ano de referência e dois anteriores (a partir de 2020). Períodos 1–12 são
  plotados; demais códigos são preservados separadamente. Conflitos de valor
  no mesmo indicador/mês suspendem o gráfico. Não há soma de períodos nem
  dimensionamento automático de BESS a partir de DEC/FEC.
- Associação com distribuidora: CONJ e ano vêm da UC; CNPJ/SigAgente vêm da
  API de continuidade. Candidatos tarifários exigem registro no mesmo ano de
  referência da UC. **Isso não homologa equivalência DIST–CNPJ nem conexão na
  coordenada.** O cadastro de agentes inspecionado não contém DIST; o vínculo
  é rotulado como candidato, não presumido como validado por proximidade.
- Tarifas: busca por CNPJ candidato, subgrupo escolhido e Tarifa de Aplicação;
  filtra vigência pela data escolhida. A4 é apenas filtro inicial, não decisão
  de enquadramento. Interface separa CNPJ, modalidade, classe, subclasse,
  detalhe e agente acessante. Mantém posto, unidade e resolução visíveis;
  múltiplas linhas vigentes não são fundidas automaticamente.
- TE+TUSD em R$/kWh é calculado somente para linhas de energia em MWh. Linhas
  de demanda em kW ficam separadas. Não calcula fatura completa nem aplica
  tributos/bandeiras por inferência. Tarifas da otimização permanecem intactas.
- Consultas de continuidade/tarifas paginadas e limitadas a 3.000 registros
  por recurso. Limites, erros e ausências são explicitados. Falha nesses
  serviços não apaga os dados mensais já coletados. Cache versionado para
  evitar reutilizar recortes antigos sem os novos campos.

Saídas de cada consulta: `analise_preliminar.json`, `analise_preliminar.md`,
`consumo_demanda_mensal.csv`, `continuidade_conjuntos.csv` e
`tarifas_referencia.csv`, em `outputs/interface/preliminar_api_*`.
O JSON registra fontes/filtros e dados; o relatório descreve limites e tabelas.

### Separação do cálculo elétrico

`capacity_kw` continua nulo e `is_network_valid` falso no modo online.
Nenhuma energia, demanda ou tarifa da triagem é passada ao AMPL. O modo
detalhado, download de BDGD e comportamento de `limit_source` permanecem
inalterados. A BDGD permite estimativas físicas com suas premissas; não é
telemetria em tempo real nem autorização da distribuidora.

### Testes reais desta versão (raio de 1,5 km)

| Ponto | UCs PJ | Grupos mensais | Registros DEC/FEC | Linhas tarifárias A4 vigentes |
| --- | ---: | ---: | ---: | ---: |
| Campinas (-22.817, -47.069) | 35 | 11 | 119 | 31 |
| Manaus (-3.12, -60.02) | 250 | 37 | 96 | 19 |
| Boa Vista (2.82, -60.67) | 30 | 9 | 24 | 19 |

Contagens da consulta de implantação, não indicadores de cobertura completa.
Manaus permanece parcial na camada SIGEL, limitada a 1.000 trechos. Os dados
mensais, de continuidade e tarifários foram retornados sem erro nesses testes.
Teste programático da interface com dados reais de Campinas: seis gráficos,
quatro tabelas e troca de grupo mensal sem exceções.

Backup anterior: `backups/pre_triagem_ampliada_ocm_20260904_01.tar.gz`.

## Atualização: preliminar online como padrão (03/09/2026)

Na abertura da interface, **Preliminar — APIs online** é o modo padrão.
Digite a coordenada ou clique no mapa, ajuste o raio e use **Consultar APIs
neste ponto**. Não é necessário instalar, abrir ou extrair uma BDGD.

- `src/aneel_online.py`: descoberta de UCMT_PJ e UCAT_PJ por `package_show`,
  validação de esquema e consultas `datastore_search` com campos selecionados.
  O endpoint SQL foi testado e não está habilitado nesse portal. A busca usa
  prefixos de coordenadas em células de 0,1 grau, abrangendo o retângulo de
  busca; o resultado é filtrado pela distância geodésica WGS84 exata ao ponto.
- Paginação de até 1.000 registros por requisição, com teto de 3.000 por
  recurso/consulta. Quando atingido, a amostra é explicitamente parcial e o
  registro mais próximo pode estar ausente. Não baixa o cadastro nacional.
- Consome a API vetorial SIGEL AME_2023 para trechos MT dentro da extensão
  publicada por esse serviço regional. Máximo de 1.000 trechos por recorte,
  com aviso de truncamento. Não representa uma API vetorial de todo o Brasil.
  Fora dessa extensão, a caracterização CKAN continua independente.
- Cache de consultas por seis horas e metadados do catálogo/SIGEL por um dia,
  em `outputs/api_cache`. A opção **Atualizar APIs sem usar cache** faz nova
  consulta no próximo clique. Erros não são tratados como respostas vazias.
- `src/ui_service.py:analyze_preliminary` salva relatório Markdown e snapshot
  JSON em `outputs/interface/preliminar_api_*`, com parâmetros, fontes,
  datas de coleta, datas-base disponíveis, paginação e ocorrências. Não
  confunde data de atualização do recurso com data-base dos registros.
- O mapa distingue consumidores PJ (laranja), rede SIGEL (azul) e eletropostos
  OSM. Consumidor não é trecho da rede. Distâncias apresentadas são às UCs
  retornadas, não ao ponto físico de conexão. Não são expostos endereço,
  nome ou identificador individual do consumidor.

Para aprofundar, altere **Modo de análise** para **Detalhada — BDGD local**.
Nesse modo permanecem o catálogo/download por distribuidora, seleção da base,
área de abrangência, cálculo residual, gráficos e otimização existentes.
A mesma coordenada é preservada ao trocar de modo; resultados anteriores
são descartados para não misturar fontes. O `main.py` continua sendo o motor
de otimização detalhada; não usa a triagem online como restrição elétrica.

**Limites científicos:** códigos de alimentador/subestação dos consumidores
são candidatos, não comprovação de ligação do novo eletroposto. A API PJ não
representa toda a carga do circuito e a base UCAT inspecionada não informa
DATA_BASE. A preliminar retorna `capacity_kw=null` e `is_network_valid=false`:
não produz capacidade zero, infinita ou fallback manual, nem inicia AMPL.
Não determina reforços de rede ou horários preferenciais com dados parciais.
Tarifas e DEC/FEC não foram incorporados automaticamente nesta etapa; exigem
vínculo validado de distribuidora, conjunto, modalidade e referência.
As regras anteriores de `limit_source="bdgd"`, `manual` e `minimum` do modo
detalhado foram preservadas sem alteração de configuração.

### Validação desta atualização

Consultas reais com raio de 1,5 km em 03/09/2026:

| Local/coordenada | Registros PJ no raio | Rede vetorial online |
| --- | ---: | --- |
| Campinas: -22.817, -47.069 | 35 | Fora da extensão AME_2023 |
| Manaus: -3.12, -60.02 | 250 | 1.000 trechos, recorte parcial sinalizado |
| Boa Vista: 2.82, -60.67 | 30 | Fora da extensão AME_2023 |

São quantidades retornadas, não inventários completos nem capacidades.
O conjunto de testes passou com 68 testes, incluindo regressões do modo
detalhado, modo online padrão sem leitura de BDGD, atualização de coordenada
e raio, cache, paginação, falhas de fonte, limites e hemisfério norte.

Backup antes desta atualização:
`backups/pre_modos_api_bdgd_20260903_02.tar.gz`.

Fontes dos conectores:
[BDGD / CKAN ANEEL](https://dadosabertos.aneel.gov.br/dataset/base-de-dados-geografica-da-distribuidora-bdgd),
[SIGEL AME_2023](https://sigel.aneel.gov.br/server/rest/services/Dados_Abertos/AME_2023/FeatureServer),
[documentação DataStore CKAN](https://docs.ckan.org/en/2.10/maintaining/datastore.html).

As seções seguintes registram a implantação anterior do modo detalhado e da
camada OSM. Onde mencionam a necessidade de arquivo local para calcular,
referem-se ao cálculo de capacidade/otimização, não à nova triagem online.

## O que está implementado

A interface preserva o mapa local, os controles existentes e a base original
CPFL Paulista. Foram acrescentados:

- **Explorar Brasil:** permite navegar/selecionar coordenadas fora da base
  carregada, sem confundir o enquadramento nacional com cobertura de cálculo.
- **Catálogo nacional ANEEL / API:** consulta paginada da organização oficial
  ANEEL no ArcGIS. A consulta de implantação retornou 1.013 arquivos/versões,
  agrupados em 114 identificadores de distribuidoras. A seleção padrão do
  catálogo usa a data de referência mais recente e depois a revisão, e não
  simplesmente a data em que um arquivo antigo foi editado no portal.
- **Download sob demanda:** tamanho consultado antes de habilitar o botão,
  progresso, timeout, limite de 6 GB por ZIP, margem de disco, validação do ZIP,
  escrita temporária e publicação somente após download completo. O SHA-256
  calculado, a identificação e a data do item ficam registrados. Não é um
  checksum assinado pela ANEEL, mas um identificador local para auditoria.
- **BDGD carregada para cálculo:** seleciona bases instaladas, desenha a área
  ARAT da base escolhida e usa essa mesma base na análise e no subprocesso de
  otimização. Resultados antigos são descartados ao trocar a fonte.
- **Exibir eletropostos existentes:** liga/desliga a consulta e a camada OSM,
  com agrupamento de marcadores, raio de 1–25 km, cache de seis horas e intervalo
  mínimo de 30 segundos entre consultas novas. Há também controle de camada
  no próprio mapa. Desligar a opção não faz novas consultas de eletropostos.

As bases são instaladas em `Dados BDGD/Nacional`, sem substituir a CPFL original.
O catálogo nacional não significa que os 114 arquivos foram todos baixados.
Não foi implementado download massivo: vários arquivos têm gigabytes e a
BDGD contém muitas camadas desnecessárias para uma única consulta local.

## Como usar

1. Abra **Catálogo nacional ANEEL / API** na barra lateral.
2. Atualize o catálogo se desejar uma consulta mais recente.
3. Escolha a distribuidora/data e clique em **Baixar BDGD selecionada**.
4. Selecione o arquivo em **BDGD carregada para cálculo**.
5. Use **Centralizar na área carregada**, digite a coordenada ou clique no mapa.
6. Analise ou simule somente dentro da área da base carregada.
7. Ative **Exibir eletropostos existentes** para consultar os locais próximos.

O catálogo exige seleção da distribuidora: não há identificação nacional
automática da concessionária por coordenada nesta implementação. Navegar
em outra região não faz download silencioso. A cobertura ARAT só é conhecida
com precisão depois de abrir a base. Sem a base correspondente, o cálculo
permanece desabilitado, mas a consulta de eletropostos funciona de forma independente.

## Natureza das APIs e limites

O [portal ANEEL informado](https://dadosabertos-aneel.opendata.arcgis.com/search?tags=distribuicao)
expõe o catálogo e os arquivos **File Geodatabase** via ArcGIS REST:

- Busca: `https://www.arcgis.com/sharing/rest/search`
- Metadados: `https://www.arcgis.com/sharing/rest/content/items/{id}`
- Arquivo: `https://www.arcgis.com/sharing/rest/content/items/{id}/data`
- Organização verificada no próprio portal: `J5unWNi0P2dwjI3y`.

Não foi encontrada/validada uma API nacional única que devolva todos os
parâmetros necessários ao cálculo de capacidade residual por coordenada.
O serviço vetorial AME_2023 inspecionado contém 17 camadas espaciais, mas
não publica as tabelas de energia e curvas de carga necessárias ao modelo;
não foi tratado como equivalente à BDGD completa ou como cobertura nacional.
O serviço AREA_ATUACAO apresentou timeout na inspeção e não foi tornado uma
dependência do funcionamento local. Outros dados ANEEL (geração, tarifas,
qualidade, subestações) poderão ser integrados separadamente após validação
de esquema, data e abrangência; não foram misturados automaticamente.

As datas de referência variam por distribuidora; ‘mais recente’ não significa
medição em tempo real. Campos, códigos e topologias ainda passam pelo modelo
existente. Transformadores MT–MT, fases incompatíveis, dados ausentes e demais
limitações podem tornar a análise inconclusiva. A seleção da fonte não altera
`limit_source="bdgd"` nem impõe um teto manual à análise válida.

**As tarifas continuam sendo as parametrizadas no projeto.** Não há atualização
automática de tarifas por distribuidora. Comparações econômicas fora da base
original exigem revisar essas premissas, mesmo quando a análise elétrica conclui.

## Fonte dos eletropostos

Integração ativa: [OpenStreetMap / Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API).
É uma API pública de leitura, usada com consultas pequenas por raio, sem chave
ou cobrança implementada no projeto. Não há garantia de serviço/completude.
O servidor pode limitar ou recusar consultas; a falha é mostrada sem afetar o
cálculo elétrico. A consulta envia a coordenada e o raio ao provedor público.

Filtro: `amenity=charging_station`. Locais explicitamente privados/proibidos,
desativados e incompatíveis com automóveis são excluídos. Por padrão, somente
registros com acesso público declarado aparecem. A opção adicional inclui
acesso condicionado (clientes, por exemplo) e acesso não informado, sempre
identificando essas categorias no marcador. Ausência de marcador não comprova
ausência de eletroposto. Acesso público não significa recarga gratuita.

Os marcadores mostram nome, operador, acesso, horário, cobrança e informações
de conectores quando cadastradas. Não informam vagas livres, funcionamento
confirmado ou ocupação em tempo real. Os textos externos são escapados antes
de inseridos nos popups. A interface exibe atribuição e link da licença
[© OpenStreetMap contributors — ODbL](https://www.openstreetmap.org/copyright).

Também foi avaliado [Open Charge Map](https://openchargemap.io/develop), mas
sua API hospedada [exige chave](https://community.openchargemap.org/t/reminder-api-keys-are-mandatory/218).
Não foi criada conta nem utilizada chave de terceiros. Essa alternativa não
está ativada; poderá complementar o OSM se houver chave autorizada e atribuição
adequada aos fornecedores de cada registro.

## Validações realizadas

- Catálogo oficial: paginação completa, 1.013 versões / 114 distribuidoras.
- Download real: Forcel, referência 31/12/2025, ZIP de 3.050.832 bytes,
  com 43 camadas; carregamento ARAT e rede MT bem-sucedidos.
- Forcel, ponto -26,0524740 / -52,6434882: mapa com 114 trechos no recorte;
  cálculo inconclusivo por trecho CA incompatível com o modelo trifásico.
- Forcel, ponto -25,9789807 / -52,5735224: inconclusivo por energia CTMT zero.
- Forcel, ponto -25,9789362 / -52,5734474, alimentador 1_SFOR_1: análise anual
  concluída; triagem residual entre 4.007,94 e 6.200,08 kW. Não é capacidade
  homologada e mantém as premissas conservadoras da metodologia existente.
- São Paulo, ponto -23,5505 / -46,6333, raio 20 km: 13 registros não privados
  normalizados, incluindo registros com acesso não informado. O total exibido
  depende do filtro; não é um inventário completo da cidade.
- Campinas, raio 5 km na consulta exploratória: retorno vazio, tratado como
  ausência de cadastro retornado, não ausência física de eletropostos.
- Testes automatizados cobrem regressões anteriores, paginação, seleção da
  versão, itens não oficiais, acesso público/privado/incerto, HTML externo,
  rate limit, projeção UTM nos dois hemisférios, propagação da base selecionada
  à simulação e controles de navegação/camada da interface.

Os testes geográficos validaram a análise da rede; não foi rodada otimização
econômica em todas as distribuidoras. O projeto continua sendo local e não
foi publicado em um serviço externo.

Backup anterior à implementação:
`backups/pre_api_brasil_eletropostos_20260903.tar.gz`.
