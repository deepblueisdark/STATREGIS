"""STATREGIS - 04 - Filtragem anual/mensal, consolidação (aba ALL) e mapas de um sumário JÁ existente.

Uso:
    python statregis_executa_filtragem_completa.py -i ../02_DOWNLOAD_E_PROCESSO/sumario_RJ.xlsx \
           -o filtrados_RJ.xlsx --criterio omm -s ../00_STUFF/RIODEJANEIROPoly.shp

Mesmo resultado de `statregis_processa_dados.py --criterio ...` (o código agora é um só:
comum/filtragem.py). Use este script quando já tem o sumário e não quer reprocessar os brutos.

Critérios: omm (IDV>=80 e 30 anos completos), anos (IDV>=80 e --anos-minimos), idv (só IDV>=--idv-corte).
Antes 'anos' e 'idv' faziam exatamente a mesma coisa.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from comum.estatisticas import NOMES_MESES
from comum.filtragem import consolidar, gravar_consolidado
from comum.graficos import ler_shape, mapas_filtragem

ABAS_GERADAS = {"ANUAL", "MENSAL", "ALL", "MEDIAS", "ESTACOES_ANALISE", "BRUTOS", "Historico", *NOMES_MESES.values()}


def main():
    pasta = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-i", "--entrada", type=Path,
                   default=pasta.parent / "02_DOWNLOAD_E_PROCESSO" / "sumario_artigo_RSRJ.xlsx")
    p.add_argument("-o", "--saida", type=Path, default=pasta / "filtrados_artigo_RSRJ.xlsx")
    p.add_argument("--campo", default="P99", help="Campo mensal a consolidar (padrão P99)")
    p.add_argument("--criterio", choices=["omm", "anos", "idv"], default="omm")
    p.add_argument("--anos-minimos", type=int, default=10)
    p.add_argument("--idv-corte", type=float, default=80.0)
    p.add_argument("-s", "--shapefile", type=Path,
                   default=pasta.parent / "00_STUFF" / "buffer_final_regiaoserrana_srtm30metrosPoly.shp")
    p.add_argument("--sem-mapas", action="store_true")
    a = p.parse_args()

    entrada, saida = a.entrada.resolve(), a.saida.resolve()
    if not entrada.is_file():
        p.error(f"Arquivo de entrada não encontrado: {entrada}")
    if entrada == saida:
        p.error("A saída deve ser diferente da entrada.")

    abas = pd.read_excel(entrada, sheet_name=None)
    faltam = [m for m in ["ANUAL", *NOMES_MESES.values()] if m not in abas]
    if faltam:
        p.error(f"Abas ausentes no Excel: {', '.join(faltam)}")

    try:
        cons = consolidar(abas["ANUAL"], {m: abas[m] for m in NOMES_MESES.values()},
                          a.criterio, a.anos_minimos, a.campo, a.idv_corte)
    except ValueError as e:
        p.error(str(e))
    print(f"ANUAL: {len(cons['ANUAL'])} estações após filtro ({len(abas['ANUAL'])} antes)")
    for m, df in cons["mensais"].items():
        print(f"{m}: {len(df)} estações após filtro")

    extras = {k: v for k, v in abas.items() if k not in ABAS_GERADAS}   # mantém ANUAIS, Excluidas_IDV etc.
    brutos = abas.get("BRUTOS")
    hist = abas.get("Historico")
    saida.parent.mkdir(parents=True, exist_ok=True)
    gravar_consolidado(saida, cons, brutos, hist, extras)
    print(f"Excel salvo: {saida} | comuns aos 12 meses: {len(cons['comuns'])}")

    if not a.sem_mapas:
        mapas_filtragem(cons, saida.parent, ler_shape(a.shapefile))
        print(f"Mapas salvos em: {saida.parent}")


if __name__ == "__main__":
    main()
