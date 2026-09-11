# Open Charge Map — integração local

Nos dois modos da interface, ative **Exibir eletropostos existentes**.
Open Charge Map é a única API de eletropostos. Os marcadores aparecem em azul,
ou cinza se o cadastro declara não operacional. O controle do mapa permite
ocultar a camada. A integração Overpass/OSM foi removida do código de trabalho.
O fundo cartográfico padrão do Folium ainda pode usar mapas OpenStreetMap;
isso é independente da fonte/API dos eletropostos.

Os marcadores e a tabela mostram nome, endereço, operador, acesso, estado
cadastral, conectores, potência por conector, quantidades declaradas, cobrança,
observações e datas, quando fornecidos. A fonte e a licença de cada fornecedor
acompanham os registros. Não há indicação de vagas livres em tempo real;
número de conectores não comprova capacidade simultânea de recarga.

Cadastro privado OCM (códigos 2, 3 e 6) não é exibido. Público com aviso prévio
ou acesso desconhecido requer habilitar a opção de acesso condicionado/não
informado. Público com assinatura/pagamento mantém a condição informada na
ficha. Cadastros podem estar desatualizados; confirme antes de viajar.

Consulta por raio até 25 km, no máximo 500 registros, cache de seis horas.
Se alcançar o limite, há aviso de possível truncamento. Falhas OCM não impedem
a análise elétrica. Registros repetidos com o mesmo ID são eliminados.

## Credencial

Prioridade: variável `OPENCHARGEMAP_API_KEY`, depois arquivo privado
`/Users/julionunes/.config/eletropostos/openchargemap.key`.
O arquivo instalado tem permissão 600; a pasta, 700. Ele está fora do projeto,
do código e dos backups do projeto. Não copie essa credencial para relatórios,
versionamento ou distribuições. É enviada exclusivamente ao domínio oficial
`api.openchargemap.io`, no cabeçalho `X-API-Key`; redirecionamentos são recusados.
O aplicativo não coloca a chave na URL, nos dados retornados ou em mensagens
de erro. Nenhuma credencial foi inserida neste documento.

## Validação

Chave validada com HTTP 200. Campinas (-22.817, -47.069), raio 10 km:
API retornou cinco cadastros na consulta de implantação. A quantidade exibida
depende do filtro de acesso. Testes cobrem autenticação por cabeçalho,
ausência da chave nos resultados, filtros, coordenadas, duplicações por ID,
metadados, HTML escapado e regressões da interface. Cálculo elétrico inalterado.

Backup anterior à exclusividade OCM e à triagem ampliada:
`backups/pre_triagem_ampliada_ocm_20260904_01.tar.gz`.

Condições e documentação: https://openchargemap.org/develop
