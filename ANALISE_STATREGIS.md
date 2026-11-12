# STATREGIS — Análise do sistema (10/11/2026)

> **Atualização:** todos os itens da tabela abaixo foram corrigidos. Veja a seção 6 para a nova estrutura.
> Originais copiados em `_backup_20261110/`.

Fluxo atual: `00_STUFF` (shapes) → `01` inventário ANA → `02` download + sumários → `03` plots →
`04` filtragem → `05` cluster/Köppen → `06` interpolação.

## 1. Bugs (corrigir primeiro)

| # | Onde | Problema | Status |
|---|------|----------|--------|
| 1 | 06 `interpolacao_novo_09.py` l.792 | `variograma` só existe em `main()` → **Kriging (método padrão) quebra com NameError** | Corrigido em `interpolacao_novo_10.py` |
| 2 | 06 | Métricas calculadas nos próprios pontos do ajuste → Kriging/IDW/RBF/Linear dão erro ≈0; a tabela não compara nada | Corrigido: validação cruzada leave-one-out |
| 3 | 06 | Distâncias em graus (1° lon ≈103 km, 1° lat ≈111 km a 22°S) → anisotropia artificial em todos os métodos de distância; alcance do variograma sem unidade física | Corrigido: km |
| 4 | 06 | Spline suavizada com `s = n·var` → resíduo permitido = variância total (superfície quase plana) | Corrigido: `--spline-s-frac` (0,1) |
| 5 | 06 | Valores fora de `intervalos` ficam em branco no mapa | Corrigido |
| 6 | 06 | Legenda fixa "Região Serrana" e trocada (o *buffer* de seleção aparecia como "Limite Região Serrana") | Corrigido: `--rotulo-limite/--rotulo-mascara` |
| 7 | 03 `plota_mapas_interpolados.py` | Recria a grade com `arange(…,0.1)` do shapefile; o NetCDF do 06 usa `linspace` com 0,01 → mapa deslocado ou erro de dimensão. Caminhos da Bahia fixos no código | Substituído por `statregis_plota_netcdf.py` |
| 8 | 02 (ambos) | `import escalas`, mas não existe `escalas.py` na pasta 02 → só roda se copiado à mão | Corrigido |
| 9 | 01 | `gpd.datasets.get_path('naturalearth_lowres')` foi removido no geopandas ≥ 1.0 → mapa do inventário quebra | Corrigido |
| 10 | 05 `cluster_V2.py` | KMeans/GMM rodam sobre `Classificacao` (limite inferior da faixa do histograma), não sobre a variável → perde informação e o resultado depende de `--bounds` | Corrigido |
| 11 | 05 | Se algum valor cai fora de `--bounds`, `x` (dropna de Classificacao) fica menor que `x_validos` → `pd.Series(labels, index=x_validos.index)` quebra | Corrigido |
| 12 | 05 | `K = range(2, min(únicos, √n))` pode ficar vazio → `np.argmin([])` quebra; sem `random_state` → resultado muda a cada execução | Corrigido |
| 13 | 02 `processa_dados` | `MEDIA_DIARIA` usa `dropna(how="any")` → só dias em que **todas** as estações têm dado (quase sempre vazio) | Corrigido |
| 14 | 02 `download_processa` | IDV mensal usa anos inteiros de `data_min.year` a `data_max.year` como denominador; o IDV anual usa os dias reais → IDV mensal subestimado nas pontas | Corrigido |
| 15 | 02/04 | Critérios `anos` e `idv` são idênticos (mesmo código nos dois ramos) | Corrigido |

## 2. Duplicações

- **02: os dois scripts calculam o mesmo sumário.** `download_processa` baixa e já gera ANUAL/MENSAL/Jan–Dez; `processa_dados` recalcula tudo a partir de BRUTOS. As funções `contar_anos_completos`, `gerar_linha_tempo_estacoes`, `plota_estacoes`, `calcular_num_dias` e as estatísticas estão copiadas.
  Pior: **os nomes de coluna diferem** (`Desvio Padrao`×`Desvio`, `Variancia`×`Variância`, `Média mm/mes`×`Média mm/mês`, `Data Ultimo dado`×`data Ultimo dado`), então o 05/06 funciona ou não dependendo de qual dos dois gerou o Excel.
  → Proposta: `download` só baixa e grava BRUTOS + Historico; o sumário fica **só** no `processa_dados`.
- **04 ≈ `processa_dados --criterio`.** `gerar_saida_filtrada` (02) faz a mesma coisa que `statregis_executa_filtragem_completa.py` (04): filtra ANUAL e meses, ALL, MEDIAS, ESTACOES_ANALISE, BRUTOS filtrado, mapas. `statregis_filtra_dados_brutos.py` também é coberto pela aba BRUTOS do `_FILTRADO.xlsx`. → 04 pode virar só um `import` das funções do 02, ou ser aposentado.
- **Inventário duas vezes**: `ServiceANA.inventario2` em 01 e 02 (no 02 não é usado).
- **`plota_estacoes` em três lugares** (02 ×2 e 03 `statregis_plota_mapas.py`), com regras de filtro diferentes (uma filtra pelo campo, outra pelo IDV).
- **Escalas em 4 cópias**: `03/escalas.py`, `05/escalas.py`, `06/escalas.py` (05 e 06 idênticos, 03 levemente diferente) e `06/interpola.config`. `cmapp99` é cópia de `cmap1`.
- **Mesmos campos repetidos no sumário**: `Num Anos Validos` = `Num Anos Completos`; no mensal, `Num de Dias válidos` = `Num Dados Válidos` ≈ `Num Dias Validos`.
- **00_STUFF**: `QUITANDINHA`, `QUITANDINHA2`, `QUITANDINHA3` e `quitandinha_wgs84` têm o mesmo `.shp` (md5 igual); `QUITANDINHA.shp` está sem `.shx/.prj` (quebrado); `quitandinha_wgs84.dbf.*` é lixo de exportação; `SANTACATARINA.prj/.gsr2` sem `.shp`; `.zip` duplicam shapes já extraídos.

## 3. O que pode sair

- `03/__pycache__/`, arquivos `~$*.xlsx` (travas do Excel em 02 e 05).
- Código morto no 06 antigo: `plota_mapa_kml` (nunca chamada), `plota_mapa_pontos`, imports repetidos, funções comentadas.
- `03/plota_mapas_interpolados.py` (substituído) e, após unificar, o 04.

## 4. Sugestões de melhoria (por ordem de ganho)

1. **Um pacote comum** `statregis_comum/` com `ana.py` (cliente ANA), `estatisticas.py`, `plots.py`, `escalas.py`, `codigos.py` (`normalizar_codigo`). Cada etapa só importa. Acaba com 1, 2 e 8.
2. **Um `config.yaml` por caso** (shapefile, máscara, extensão, período, LDU, critério, intervalos de cor). Hoje cada script tem padrões fixos de casos diferentes (Bahia no 03/05, Região Serrana no 04/06, `artigo_RSRJ` no 04).
3. **Download robusto**: `timeout` + retry nas chamadas `requests.get` (hoje sem timeout em 02), **cache por estação** (`cache/<codigo>.csv`) para retomar uma execução interrompida, e baixar também o **consistido** (`nivelConsistencia=2`) preferindo-o ao bruto quando houver os dois para o mesmo dia (hoje fica o "primeiro" de forma arbitrária).
4. **Média anual**: `média diária × 365` enviesa quando a falta de dados é sazonal (ex.: falhas no verão). Mais robusto: soma das 12 médias mensais (média diária do mês × dias do mês).
5. **Cluster (05)**: agrupar a variável original (padronizada), `random_state` fixo, e opção de usar vários campos (ex.: média + P95 + lat/lon/altitude).
6. **Interpolação**: com a validação cruzada já dá para escolher o método objetivamente (aba `Ranking`). Próximos passos: Kriging com deriva de altitude (`UniversalKriging` / regressão-krigagem usando SRTM), já que chuva orográfica na Serra depende muito da altitude.
7. Um `run_caso.py` que encadeia 01→06 lendo o `config.yaml`, e um `requirements.txt` (geopandas, pykrige, xarray, netCDF4, simplekml, pyproj, openpyxl, scikit-learn).
8. Pasta `saidas/<caso>/` em vez de gravar Excel/PNG no diretório onde o script roda.

## 5. Novos arquivos entregues

- `06_INTERPOLACAO/interpolacao_novo_10.py` — mesma linha de comando do 09 + novas opções:
  `--todos`, `--recortar mascara|limite`, `--rotulo-limite`, `--rotulo-mascara`, `--sem-validacao-cruzada`,
  `--truncar-negativos`, `--spline-s-frac`, `--rbf-suavizacao`, `--grau-polinomio`, `--nlags`, `--autor`.
  Saída Excel: `Metricas_LOOCV`, `Ranking`, `Previsoes_LOOCV`, `Metricas_Ajuste`, `Variogramas`, `Falhas`, `Notas`.
  Atenção: sem `--extensao`, a grade agora usa os limites dos shapefiles (para manter a grade antiga da Serra, passe `--extensao -43.5 -41.55 -22.7 -21.45`).
- `03_PLOTA_MAPAS/statregis_plota_netcdf.py` — plota qualquer NetCDF do 06 lendo a grade do arquivo.

## 6. Nova estrutura (após as correções)

```
STATREGIS/
  escalas.config          <- ÚNICO arquivo de escalas e paletas (só dados; nada é executado)
  requirements.txt
  comum/                  <- código compartilhado (antes copiado em vários scripts)
    ana.py                   cliente ANA: timeout, novas tentativas, cache, consistência 1/2/ambos
    estatisticas.py          sumário ANUAL/ANUAIS/MENSAL/Jan..Dez (um só cálculo)
    filtragem.py             critérios omm/anos/idv e aba ALL
    graficos.py              mapa de estações, linha do tempo, mapas de filtragem
    escalas.py               leitor do escalas.config
    codigos.py               normalização de códigos de estação
  01_INVENTARIO/statregis_gera_inventario.py
  02_DOWNLOAD_E_PROCESSO/statregis_download_processa.py   (baixa + sumário)
  02_DOWNLOAD_E_PROCESSO/statregis_processa_dados.py      (reprocessa período/critério sem baixar)
  03_PLOTA_MAPAS/statregis_plota_mapas.py, statregis_plota_netcdf.py
  04_FILTRAGEM/statregis_executa_filtragem_completa.py, statregis_filtra_dados_brutos.py
  05_CLASSIFICACAO/cluster_V2.py
  06_INTERPOLACAO/interpolacao_novo_10.py
```

Os comandos antigos continuam valendo. Mudanças de comportamento a conhecer:

- **Colunas do sumário** (iguais nos dois scripts do 02): `Desvio`, `Variância`, `Média mm/mês`.
  `Num Anos Validos` (era cópia de `Num Anos Completos`) saiu. Nova coluna `Média mm/ano (climatológica)`
  e nova aba `ANUAIS` também no processa_dados.
- **Critérios**: `anos` = IDV ≥ 80 e ≥ `--anos-minimos` anos completos; `idv` = só IDV ≥ `--idv-corte` (80).
- **Mapas de estações**: com intervalos (`idv`, `media`...) as cores agora são por classe (uma cor por faixa),
  como na legenda, em vez de um degradê linear que comprimia as faixas desiguais.
- **escalas.config**: `p99` agora é a escala dos mapas interpolados (50–150, a do interpola.config);
  a antiga `p99` dos mapas de estações (10–100) chama-se `p99_estacoes`.
  Os antigos `escalas.py`, `interpola.config`, `interpolacao_novo_09.py` e `plota_mapas_interpolados.py`
  saíram do repositório (cópias em `_backup_20261110/` na pasta local e no histórico do git).
- **02 download**: cache em `cache_<nome>/` (apague a pasta, ou use `--sem-cache`, para baixar de novo);
  `--consistencia ambos` baixa bruto + consistido e prefere o consistido.
- **05 cluster**: K testado até raiz(n) (como antes) e no máximo `--kmax`; clusters numerados do menor para
  o maior valor médio; figuras em `./<aba>/`; Köppen pulado se o shapefile não existir (`--shapefile-clima nenhum`).

## 7. Memória: a aba BRUTOS estourava o processo (11/11/2026)

**Sintoma:** com ~1485 estações o processo terminava o download, ficava parado consumindo
memória (11 GB observados), era morto pelo sistema e **não gerava nem o .xlsx nem o .csv**.

**Causa:** a aba `BRUTOS` tem uma coluna por estação e uma linha por dia. Com 1485 estações
e 1991–2020 são ~16 milhões de células; na série histórica completa passa de 60 milhões.
O openpyxl monta um objeto Python por célula **antes** de escrever qualquer byte no disco.
Medido nesta base, no mesmo quadro de 2000 dias x 1485 estações:

| Gravador | Tempo | Pico de memória | Por célula |
|---|---|---|---|
| openpyxl (antes) | 85 s | 1,20 GB | 382 bytes |
| `comum/planilhas.py` (agora) | 28 s | 0,14 GB | ~1 byte |

Extrapolando o openpyxl para o caso real: 16 M de células = ~6 GB e ~30 min; 68 M = ~24 GB e ~2 h.
Os 11 GB eram o processo no meio da montagem da planilha. E como o `to_csv` vinha **depois**
do `to_excel`, o CSV nunca chegava a rodar.

**Armadilha evitada:** a saída natural seria `xlsxwriter` com `constant_memory=True` via
`pandas.to_excel`. Isso **corrompe os dados em silêncio**: o pandas emite as células coluna a
coluna e o `constant_memory` descarta tudo que volta para uma linha já fechada. O arquivo sai
com o tamanho e as datas certos e **todos os valores vazios**. Testado e confirmado.
Por isso `comum/planilhas.py` escreve linha a linha, na mão, direto no xlsxwriter.

**O que mudou:**

- Novo `comum/planilhas.py`: `gravar_abas` (escrita em streaming, memória constante),
  `gravar_brutos_csv`, `ler_brutos` e checagem dos limites do .xlsx (1.048.576 linhas, 16.384 colunas).
- `02 download`: o **CSV dos brutos sai primeiro**, sempre (antes era opcional e vinha depois do
  xlsx). Se a aba BRUTOS não couber no formato .xlsx, o xlsx sai sem ela e avisa; o CSV tem tudo.
  `--cvs` virou obsoleto (não faz mal manter nos comandos antigos).
- `gravar_sumario` e `gravar_consolidado` passaram a usar o mesmo gravador — a aba `ANUAIS`
  (uma linha por estação e por ano) também chegava a milhões de células.
- `preparar_brutos`: o `.apply(pd.to_numeric)` refazia as ~1486 colunas mesmo quando já eram
  float, duplicando o quadro inteiro. Agora converte só as colunas não numéricas.
- `ler_brutos`: `02 processa_dados` e `04` leem o CSV irmão quando ele existe e está atualizado —
  ler 16 M de células com openpyxl leva dezenas de minutos; em CSV são segundos.
- `requirements.txt`: `xlsxwriter>=3.1` (sem ele, o código avisa e recusa planilhas grandes
  em vez de travar a máquina).

**Verificado:** pipeline completo (02 download → 02 processa → 04) com 1485 estações sintéticas
em 1991–2020, caso pior sem filtro de IDV: 16.268.728 células gravadas, **pico de 1,68 GB e 218 s**
do início ao fim. Conferidos 7.404.116 valores um a um entre o CSV e a aba BRUTOS do .xlsx:
nenhuma diferença, padrão de falhas preservado, inteiros e datas preservados, abas com os mesmos nomes.
