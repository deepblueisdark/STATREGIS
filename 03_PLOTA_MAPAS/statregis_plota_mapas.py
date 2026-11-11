#!/usr/bin/env python3
"""STATREGIS - 03 - Mapa de estações de uma aba de sumário (ANUAL, Jan, ALL...).

Exemplo:
    python statregis_plota_mapas.py -i ../02_DOWNLOAD_E_PROCESSO/sumario_RJ.xlsx -s ANUAL \
           -f "Média mm/ano" -u mm/ano --bounds media -shp ../00_STUFF/RIODEJANEIROPoly.shp -o mapa.png --hist

--bounds aceita um nome do escalas.config (idv, media, p99...) ou números (100 200 300).
--min/--max filtram pela coluna IDV.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from comum import escalas
from comum.graficos import ler_shape, plota_estacoes


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-s", "--sheet", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("-shp", "--shapefile", required=True)
    p.add_argument("-f", "--field", required=True)
    p.add_argument("-u", "--unidade", default="")
    p.add_argument("-t", "--titulo", default="Mapa de Estações")
    p.add_argument("--min", type=float, default=0.0, help="IDV mínimo (filtro)")
    p.add_argument("--max", type=float, default=0.0, help="IDV máximo (filtro)")
    p.add_argument("--bounds", nargs="*", help="Nome no escalas.config ou lista de números")
    p.add_argument("--hist", action="store_true")
    p.add_argument("--cmap", default="cmap1", help="Paleta do escalas.config")
    a = p.parse_args()

    if not escalas.existe(a.cmap):
        sys.exit(f"[ERRO] Paleta '{a.cmap}' não existe no escalas.config. Disponíveis: {', '.join(escalas.nomes())}")
    bounds = escalas.resolver_intervalos(a.bounds) if a.bounds else (escalas.lista("idv") if a.field == "IDV" else None)
    df = pd.read_excel(a.input, sheet_name=a.sheet)
    plota_estacoes(df, a.output, a.field, a.unidade, a.cmap, bounds, a.titulo, histograma_=a.hist,
                   gdf=ler_shape(a.shapefile), idv_min=a.min, idv_max=a.max)
    print(f"Mapa salvo: {a.output}")


if __name__ == "__main__":
    main()
