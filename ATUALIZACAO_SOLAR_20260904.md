# Referência solar validada em 4 de setembro de 2026

Backup anterior: backups/pre_pvgis6_20260904.tar.gz. O nome identifica a investigação de migração, não uma migração efetivada.

## Decisão

Atualizado o padrão de 2021 para 2023, com endpoint explícito PVGIS 5.3 e PVGIS-ERA5. O calendário anual e o início do recorte solar acompanham SOLAR_REFERENCE_YEAR em src/config.py. A BDGD continua com sua própria data-base de 2025; não se trata de reconstrução histórica sincronizada da rede e do clima. O modelo FV pvlib, suas perdas e eficiências, o AMPL e os limites BDGD não foram substituídos.

2024 é o ano mais recente documentado no PVGIS 6, mas não foi aprovado como entrada padrão deste pipeline na validação do ponto -22.817, -47.069. Não se conclui que toda a base 2024 seja inválida: as falhas abaixo dizem respeito aos retornos consultados, que podem decorrer dos dados ou do serviço.

## Consultas e evidências

- PVGIS 5.3 /seriescalc, ERA5, 2023: 8.760 registros horários retornados. O conector valida ano UTC, contagem, espaçamento, duplicatas, ausentes e valores finitos de irradiância, temperatura e vento.
- PVGIS 6 /power/broadband, SARAH-3, 2024, UTC, CSV, verbose=9, inclinação 20 graus, orientação norte e apply_reflectivity_factor=false: 8.784 registros, 5 lacunas diurnas de irradiância em 17/08/2024. Temperatura e vento completos.
- Mesma consulta ERA5: 8.784 registros, 46 lacunas diurnas de irradiância. Temperatura e vento completos.
- O JSON PVGIS 6 não apresentou temperatura e vento nas consultas verbose=8 e 9, embora os exemplos OpenAPI os listem. CSV retornou essas variáveis.
- A consulta anual PVGIS 6 diretamente no fuso America/Sao_Paulo retornou apenas 8.781 registros; em UTC retornou 8.784. A borda do ano e os offsets temporais do satélite exigem tratamento explícito antes de migração.

Não foram preenchidas lacunas diurnas com zero, nem misturados anos ou bancos silenciosamente. Novas execuções gravam solar_provenance em pv_profile_metadata.json com endpoint, banco, ano, data de consulta e contagem. A interface informa a referência solar. Resultados antigos e o relatório de arquivamento não foram sobrescritos por esta atualização.

## Próximo passo para 2024

Revalidar os retornos do serviço, comparar com fonte independente e definir tratamento auditável de lacunas e limites de ano. Uma eventual combinação SARAH-3/ERA5 deve explicitar horas substituídas, diferenças de instante e confiança; não deve ser feita por preenchimento automático sem validação. 2024 possui 8.784 horas, exigindo também revisão das convenções de anualização econômica se adotado integralmente.

## Fontes oficiais

- [PVGIS 5.3 e cobertura até 2023](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5_en)
- [PVGIS 6](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-6_en)
- [API e esquema PVGIS 6](https://photovoltaic-geographic-information-system.ec.europa.eu/api/v6/docs)
- [Dados PVGIS 6, período 2014-2024](https://data.jrc.ec.europa.eu/dataset/131b88ed-74b7-4ceb-81da-b48b49a47ce1)

Crédito dos dados: PVGIS, Comissão Europeia / Joint Research Centre.

## Validação da implementação

93 testes automatizados aprovados em 04/09/2026. Consulta real pelo novo conector: 8.760 horas de 2023, zero ausentes nas variáveis obrigatórias e 8.760 valores entregues ao otimizador. Produção calculada de aproximadamente 1.575,00 kWh/kWp no calendário anual configurado, mantendo as hipóteses existentes de perdas e inversor. Não foi executada nova otimização econômica. Evidências salvas em outputs/validacao_solar_20260904, separadas dos resultados de simulação.
