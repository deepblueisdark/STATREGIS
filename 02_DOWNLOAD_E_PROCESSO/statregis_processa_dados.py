# =============================================================================
# STATREGIS - 02 - Reprocessa um dados_<caso>.xlsx (BRUTOS + Historico) sem baixar de novo
# Autor: Reginaldo Ventura de Sá
#
# Uso (mesmos argumentos de antes):
#   python statregis_processa_dados.py -x dados_RJ.xlsx -o sumario_RJ_1991a2020.xlsx \
#          -i 1991-01-01 -f 2020-12-31 --idv-minimo 50 --criterio omm -s ../00_STUFF/RIODEJANEIROPoly.shp
#
# Usa o mesmo cálculo do statregis_download_processa.py (comum/estatisticas.py), então os dois
# sumários têm as mesmas colunas. --criterio gera também <saída>_FILTRADO.xlsx (o que o 04 fazia).
#
# Correções: MEDIA_DIARIA agora é a média das estações com dado em cada dia (antes só usava dias em
# que TODAS tinham dado e quase sempre saía vazia); critérios 'anos' e 'idv' agora são diferentes.
# =============================================================================
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from comum import escalas
from comum.estatisticas import NOMES_MESES, calcular_sumario, gravar_sumario
from comum.filtragem import CRITERIOS, consolidar, gravar_consolidado
from comum.planilhas import ler_brutos
from comum.graficos import ler_shape, linha_tempo_estacoes, mapas_filtragem, plota_estacoes

APELIDOS_CAMPO = {"Média*365": "Média mm/ano", "Media*365": "Média mm/ano"}


def parse_args():
    p = argparse.ArgumentParser(description="Processa dados brutos de chuva e gera estatísticas e mapas.")
    p.add_argument("-x", "--entrada", required=True, help="Excel com abas BRUTOS e Historico")
    p.add_argument("-o", "--saida", required=True, help="Excel de saída")
    p.add_argument("-i", "--inicio", default="")
    p.add_argument("-f", "--fim", default="")
    p.add_argument("-l", "--limite", type=float, default=1.0, help="LDU em mm (padrão 1.0)")
    p.add_argument("--idv-minimo", type=float, default=None)
    p.add_argument("-s", "--shapefile", default="")
    p.add_argument("-c", "--campo", default="IDV", help="Campo do mapa (ex.: IDV, 'Média mm/ano', P99)")
    p.add_argument("-b", "--bounds", default="", help="Intervalos: nome no escalas.config ou 10,20,30")
    p.add_argument("--criterio", choices=CRITERIOS, default="nenhum",
                   help="omm: IDV>=80 e 30 anos | anos: IDV>=80 e --anos-minimos | idv: só IDV>=--idv-corte")
    p.add_argument("--anos-minimos", type=int, default=10)
    p.add_argument("--idv-corte", type=float, default=80.0, help="IDV mínimo dos critérios (padrão 80)")
    p.add_argument("--campo-mensal", default="P99", help="Campo mensal consolidado na aba ALL")
    p.add_argument("--saida-filtrada", default="")
    p.add_argument("--sem-mapas-filtrados", action="store_true")
    a = p.parse_args()
    if a.idv_minimo is not None and not 0 <= a.idv_minimo <= 100:
        p.error("--idv-minimo deve estar entre 0 e 100.")
    if a.anos_minimos < 0:
        p.error("--anos-minimos deve ser >= 0.")
    if bool(a.inicio) != bool(a.fim):
        p.error("Informe -i e -f juntos (ou nenhum).")
    a.campo = APELIDOS_CAMPO.get(a.campo, a.campo)
    return a


def main():
    a = parse_args()
    brutos = ler_brutos(a.entrada)
    hist = pd.read_excel(a.entrada, sheet_name="Historico", engine="openpyxl")
    res = calcular_sumario(brutos, hist, a.inicio, a.fim, a.limite, a.idv_minimo)
    gravar_sumario(a.saida, res, incluir_brutos=True)
    print(f"✅ Sumário: {a.saida} ({len(res['ANUAL'])} estações; {len(res['Excluidas_IDV'])} excluídas)")

    gdf = ler_shape(a.shapefile)
    if a.campo == "IDV":
        legenda, bounds = "Percentual (%)", escalas.lista("idv")
    elif a.campo == "Média mm/ano" and not a.bounds:
        legenda, bounds = "mm/ano", escalas.lista("media")
    else:
        legenda, bounds = a.campo, escalas.resolver_intervalos(a.bounds)
    sufixo = a.campo.replace("*", "").replace(" ", "_").replace("/", "-")
    plota_estacoes(res["ANUAL"], a.saida.replace(".xlsx", f"_mapa_{sufixo}.png"), a.campo, legenda, "cmap1",
                   bounds, f"Distribuição das estações - {a.campo}", histograma_=True, gdf=gdf)

    nomes = dict(zip(hist["Codigo"].astype(str), hist["Nome"].fillna(""))) if "Nome" in hist.columns else None
    for arq in linha_tempo_estacoes(res["BRUTOS"], a.saida.replace(".xlsx", "_linha_tempo_estacoes.png"),
                                    nomes, a.inicio or None, a.fim or None):
        print(f"✅ Linha do tempo: {arq}")

    if a.criterio != "nenhum":
        destino = Path(a.saida_filtrada or Path(a.saida).with_name(f"{Path(a.saida).stem}_FILTRADO.xlsx"))
        if destino.resolve() == Path(a.saida).resolve():
            sys.exit("--saida-filtrada deve ser diferente de --saida.")
        mensal = res["MENSAL"]
        mensais = {nome: mensal[mensal["Mes"] == mes] if "Mes" in mensal.columns else mensal.iloc[0:0]
                   for mes, nome in NOMES_MESES.items()}
        cons = consolidar(res["ANUAL"], mensais, a.criterio, a.anos_minimos, a.campo_mensal, a.idv_corte)
        destino.parent.mkdir(parents=True, exist_ok=True)
        gravar_consolidado(destino, cons, res["BRUTOS"].reset_index(), hist)
        print(f"✅ Filtrado ({a.criterio}): {destino} | ANUAL: {len(cons['ANUAL'])} | comuns aos 12 meses: {len(cons['comuns'])}")
        if not a.sem_mapas_filtrados:
            mapas_filtragem(cons, destino.parent, gdf)


if __name__ == "__main__":
    main()
