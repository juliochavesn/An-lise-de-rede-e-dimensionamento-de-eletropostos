# Análise de rede e dimensionamento de eletropostos

Aplicação de pesquisa para análise locacional de eletropostos, avaliação preliminar e detalhada da rede de distribuição e otimização de configurações com recarga inteligente, geração fotovoltaica e BESS.

**Autor:** Júlio Cesar C. Nunes — FEEC/UNICAMP  
**Contato:** j298971@dac.unicamp.br

## Funcionalidades

- triagem preliminar por APIs públicas;
- análise detalhada com BDGD local ou tratada em nuvem;
- mapa da rede de média tensão, transformadores e subestações de distribuição;
- camada PNL de rotas de transporte de cargas, fluxos, saturação trimestral e corredores;
- conversão auditável do fluxo rodoviário PNL em cenários P10/P50/P90 de caminhões, recargas, energia e perfil horário;
- estimativa temporal de capacidade residual;
- identificação de períodos críticos e oportunidades de carregamento;
- otimização econômica e de qualidade de atendimento;
- comparação entre recarga, solar, BESS e combinações;
- geração de gráficos e relatórios técnicos.

As estimativas são instrumentos de triagem e pesquisa. Elas não substituem estudo de acesso, fluxo de potência completo ou parecer da distribuidora.

## Dados

As bases BDGD não são armazenadas neste repositório devido ao volume. A aplicação pode consultar os pacotes tratados no Google Drive sob demanda. O modo local continua disponível quando uma BDGD é instalada pelo usuário.

A rede de transportes do PNL 2050 também é obtida do Google Drive somente quando sua camada é ativada. O arquivo é mantido em cache temporário e as consultas usam recortes espaciais. A interface aplica o dicionário oficial da Infra S.A. para identificar os modais e apresentar os carregamentos em toneladas. As saturações trimestrais são interpretadas somente para links rodoviários (`GTYPE = 1`).

Quando solicitado pelo usuário, o fluxo do segmento rodoviário mais próximo é convertido em demanda de recarga. O fluxo PNL continua sendo o único dado logístico observado/modelado da origem; carga útil, retornos vazios por viagem carregada, participação elétrica, captura pelo eletroposto, energia por parada e dias operacionais são hipóteses editáveis. A interface apresenta P10/P50/P90, grava as hipóteses junto aos resultados e pode enviar a curva selecionada ao otimizador. Fatores de veículo equivalente usados em capacidade viária não entram na demanda elétrica.

## Execução local

Requer Python e as dependências de `requirements.txt`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

A chave do Open Charge Map deve ser fornecida pela variável de ambiente `OPENCHARGEMAP_API_KEY` ou pelo gerenciamento de segredos da hospedagem. Nunca grave chaves no repositório.

## Implantação

O ponto de entrada da interface é `app.py`. Para Streamlit Community Cloud, conecte este repositório, selecione a branch `main` e cadastre os segredos nas configurações da aplicação.
