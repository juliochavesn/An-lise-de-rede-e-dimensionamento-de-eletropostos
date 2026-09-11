# Análise de rede e dimensionamento de eletropostos

Aplicação de pesquisa para análise locacional de eletropostos, avaliação preliminar e detalhada da rede de distribuição e otimização de configurações com recarga inteligente, geração fotovoltaica e BESS.

**Autor:** Júlio Cesar C. Nunes — FEEC/UNICAMP  
**Contato:** j298971@dac.unicamp.br

## Funcionalidades

- triagem preliminar por APIs públicas;
- análise detalhada com BDGD local ou tratada em nuvem;
- mapa da rede de média tensão, transformadores e subestações de distribuição;
- estimativa temporal de capacidade residual;
- identificação de períodos críticos e oportunidades de carregamento;
- otimização econômica e de qualidade de atendimento;
- comparação entre recarga, solar, BESS e combinações;
- geração de gráficos e relatórios técnicos.

As estimativas são instrumentos de triagem e pesquisa. Elas não substituem estudo de acesso, fluxo de potência completo ou parecer da distribuidora.

## Dados

As bases BDGD não são armazenadas neste repositório devido ao volume. A aplicação pode consultar os pacotes tratados no Google Drive sob demanda. O modo local local continua disponível quando uma BDGD é instalada pelo usuário.

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

