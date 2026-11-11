# STATREGIS

Sistema para inventário, download, estatística, filtragem, classificação e interpolação de dados de
chuva das estações da ANA (HidroWeb).

Autor: Reginaldo Ventura de Sá — reginaldo.venturadesa@gmail.com

## Fluxo

| Etapa | Script | Faz |
|---|---|---|
| 00 | `00_STUFF/` | Shapefiles das áreas de estudo |
| 01 | `01_INVENTARIO/statregis_gera_inventario.py` | Inventário de estações pluviométricas da ANA (por UF e/ou shapefile) + mapa |
| 02 | `02_DOWNLOAD_E_PROCESSO/statregis_download_processa.py` | Baixa as séries de chuva do inventário e gera o sumário |
| 02 | `02_DOWNLOAD_E_PROCESSO/statregis_processa_dados.py` | Recalcula o sumário para outro período/critério sem baixar de novo |
| 03 | `03_PLOTA_MAPAS/` | Mapas de estações (planilhas) e de NetCDF interpolados |
| 04 | `04_FILTRAGEM/` | Filtragem OMM/anos/IDV e consolidação mensal (aba ALL) |
| 05 | `05_CLASSIFICACAO/cluster_V2.py` | Faixas, KMeans/GMM e associação com Köppen |
| 06 | `06_INTERPOLACAO/interpolacao_novo_10.py` | Interpolação (Kriging, IDW, RBF...) com validação cruzada |

Código compartilhado em `comum/`; escalas e paletas em `escalas.config`.
Detalhes e histórico das correções em `ANALISE_STATREGIS.md`.

## Instalação

```bash
pip install -r requirements.txt
```

## Exemplo rápido

```bash
cd 01_INVENTARIO
python statregis_gera_inventario.py -x inventario_RJ.xlsx -u RJ -s ../00_STUFF/RIODEJANEIROPoly.shp

cd ../02_DOWNLOAD_E_PROCESSO
python statregis_download_processa.py -x ../01_INVENTARIO/inventario_RJ.xlsx -n RJ -i 1991-01-01 -f 2020-12-31
python statregis_processa_dados.py -x dados_RJ.xlsx -o sumario_RJ_omm.xlsx --criterio omm

cd ../06_INTERPOLACAO
python interpolacao_novo_10.py -c RJ_P99_Jan -x ../02_DOWNLOAD_E_PROCESSO/sumario_RJ_omm_FILTRADO.xlsx \
       -a ALL -v Jan -i p99 -m escala_cores --todos --unidade mm
```
