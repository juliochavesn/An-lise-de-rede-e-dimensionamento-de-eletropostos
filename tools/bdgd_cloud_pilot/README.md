# Piloto BDGD preparado para consulta remota

O conversor le uma BDGD `.gdb.zip` uma unica vez e gera Parquet comprimido com
Zstandard. A fonte original nao e modificada.

## Organizacao

- `global/`: area de atuacao, subestacoes, transformadores AT, curvas e cadastros comuns;
- `feeders/<codigo>/<camada>/part-*.parquet`: rede e tabelas separadas por alimentador;
- `indexes/feeders.parquet`: caixas espaciais para selecionar candidatos por coordenada;
- `manifest.json`: fonte, SHA-256, data, contagens, tamanhos e alertas.

## Execucao

```bash
python process_bdgd_cloud.py BASE.gdb.zip SAIDA \
  --distributor CPFL_Paulista --reference-date 2025-12-31
```

O resultado pode ser enviado ao Drive. A interface baixa o manifesto, o indice
e apenas os arquivos do alimentador candidato. Para leitura HTTP realmente
parcial por intervalos, a etapa seguinte e publicar o mesmo pacote em
armazenamento de objetos ou carregar as tabelas em PostGIS.

Para o Drive, compacte cada diretório de alimentador em um pacote independente:

```bash
python package_for_drive.py SAIDA/DISTRIBUIDORA/2025-12-31 PACOTES/DISTRIBUIDORA/2025-12-31
```
