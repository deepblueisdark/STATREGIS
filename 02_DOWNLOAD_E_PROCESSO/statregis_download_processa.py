# =============================================================================
# STATREGIS - 02 - Download das séries de chuva da ANA + sumário estatístico
# Autor: Reginaldo Ventura de Sá
#
# Uso (mesmos argumentos de antes):
#   python statregis_download_processa.py -x ../01_INVENTARIO/inventario_RJ.xlsx -n RJ \
#          -i 1991-01-01 -f 2020-12-31 -s ../00_STUFF/RIODEJANEIROPoly.shp --idv-minimo 50
#
# Saídas: dados_<nome>.xlsx (BRUTOS, Historico, Excluidas_IDV), sumario_<nome>.xlsx
#         (ANUAL, ANUAIS, MENSAL, Excluidas_IDV, MEDIA_DIARIA, Jan..Dez), historico<nome>.csv,
#         linha do tempo e mapas. Opcional: dados_<nome>.csv (--cvs).
#
# O que mudou:
# - O sumário é calculado por comum/estatisticas.py, o MESMO código do statregis_processa_dados.py
#   (antes eram duas cópias com nomes de coluna e IDV mensal diferentes).
# - Download com timeout, novas tentativas e CACHE por estação (pasta cache_<nome>): se a
#   execução cair, rode de novo e ela continua de onde parou. --sem-cache força baixar tudo.
# - Datas enviadas no formato dd/mm/aaaa e série cortada localmente ao período.
# - --consistencia 1|2|ambos (padrão 1 = bruto, como antes; 'ambos' prefere o consistido).
# - Não depende mais de um escalas.py na pasta: usa ../escalas.config.
# - Estações fluviométricas do inventário (Tipo 1) são ignoradas; só chuva é baixada.
# =============================================================================
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from comum import escalas
from comum.ana import ServiceANA, eh_pluviometrica
from comum.codigos import normalizar_codigo
from comum.estatisticas import calcular_sumario, gravar_sumario
from comum.planilhas import PlanilhaGrandeDemais, gravar_abas, gravar_brutos_csv
from comum.graficos import linha_tempo_estacoes, plota_estacoes


def parse_args():
    p = argparse.ArgumentParser(description="Baixa séries de chuva da ANA e gera o sumário estatístico.")
    p.add_argument("-x", "--xlsx", required=True, help="Excel do inventário (saída do 01)")
    p.add_argument("-n", "--nome", required=True, help="Nome do caso, ex: saopaulo")
    p.add_argument("-l", "--limite", type=float, default=1.0, help="Limite de chuva LDU em mm (padrão 1.0)")
    p.add_argument("--idv-minimo", type=float, default=None, help="Exclui estações com IDV abaixo deste %% (0-100)")
    p.add_argument("-i", "--inicio", default="", help="Data inicial YYYY-MM-DD")
    p.add_argument("-f", "--fim", default="", help="Data final YYYY-MM-DD")
    p.add_argument("-s", "--shapefile", default="", help="Shapefile para os mapas")
    p.add_argument("-c", "--campo", help="Campo extra para mapear (padrão: IDV e Média mm/ano)")
    p.add_argument("-b", "--bounds", default="", help="Intervalos do campo extra: nome no escalas.config ou 10,20,30")
    p.add_argument("--cvs", "--csv", dest="cvs", action="store_true",
                   help="(obsoleto) o CSV dos brutos passou a ser sempre gravado")
    p.add_argument("--consistencia", choices=["1", "2", "ambos"], default="1",
                   help="1=bruto (padrão), 2=consistido, ambos=prefere consistido")
    p.add_argument("--cache", default=None, help="Pasta de cache (padrão: cache_<nome>)")
    p.add_argument("--sem-cache", action="store_true", help="Não usa nem grava cache")
    p.add_argument("--incluir-fluvio", action="store_true",
                   help="Não descarta estações fluviométricas do inventário (padrão: descarta)")
    p.add_argument("--pausa", type=float, default=0.0, help="Segundos de espera entre consultas à ANA")
    a = p.parse_args()
    if a.idv_minimo is not None and not 0 <= a.idv_minimo <= 100:
        p.error("--idv-minimo deve estar entre 0 e 100.")
    if bool(a.inicio) != bool(a.fim):
        p.error("Informe -i e -f juntos (ou nenhum).")
    return a


def main():
    a = parse_args()
    caso = a.nome
    historico_csv = Path(f"historico{caso}.csv")
    cache = None if a.sem_cache else Path(a.cache or f"cache_{caso}")

    try:
        inv = pd.read_excel(a.xlsx)
    except FileNotFoundError:
        sys.exit(f"Erro: inventário não encontrado: {a.xlsx}")
    if "Codigo" not in inv.columns:
        sys.exit("Erro: o inventário precisa da coluna 'Codigo'.")
    inv["Codigo"] = inv["Codigo"].map(normalizar_codigo)
    if "Tipo" in inv.columns and not a.incluir_fluvio:
        pluvio = inv["Tipo"].map(eh_pluviometrica)
        if (~pluvio).any():
            print(f"[INFO] {int((~pluvio).sum())} estações fluviométricas do inventário ignoradas (só chuva).")
        inv = inv[pluvio].reset_index(drop=True)

    ana = ServiceANA(pausa=a.pausa)
    series, registros = [], []
    colunas_hist = list(inv.columns) + ["tamanho", "data_min", "data_max", "status"]
    with open(historico_csv, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(colunas_hist)

    total = len(inv)
    for k, linha in inv.iterrows():
        cod = linha["Codigo"]
        try:
            s = ana.serie_chuva(cod, a.inicio, a.fim, a.consistencia, cache)
            status = "OK"
        except Exception as e:
            s = pd.Series(dtype=float)
            status = f"ERRO: {e}"
        validos = s[s >= 0]
        if status == "OK" and validos.empty:
            status = "NO DATA"
        if not validos.empty:
            series.append(validos.rename(cod))
        dmin = validos.index.min() if not validos.empty else ""
        dmax = validos.index.max() if not validos.empty else ""
        with open(historico_csv, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(list(linha.values) + [len(s), dmin, dmax, status])
        registros.append({**linha.to_dict(), "tamanho": len(s), "data_min": dmin, "data_max": dmax, "status": status})
        print(f"{cod} ({k + 1}/{total}) {linha.get('Nome', '')} - {linha.get('UF', '')} | {len(validos)} dias válidos [{status}]")

    if not series:
        sys.exit("Nenhum dado de chuva baixado. Encerrando.")

    brutos = pd.concat(series, axis=1, sort=True)
    series.clear()  # libera as 1485 séries individuais; daqui em diante só o quadro importa
    # Estações sem nenhum dado entram como coluna vazia (aparecem em Excluidas_IDV quando há --idv-minimo).
    brutos = brutos.reindex(columns=list(dict.fromkeys(inv["Codigo"])))
    brutos.index.name = "date"
    hist = pd.DataFrame(registros)
    res = calcular_sumario(brutos, hist, a.inicio, a.fim, a.limite, a.idv_minimo)

    excl = set(res["Excluidas_IDV"]["Codigo"]) if not res["Excluidas_IDV"].empty else set()
    hist.loc[hist["Codigo"].isin(excl) & (hist["status"] == "OK"), "status"] = "EXCLUDED_IDV"
    hist.to_csv(historico_csv, index=False)
    hist_ok = hist[hist["status"].isin(["OK", "EXCLUDED_IDV"])]

    brutos_saida = res["BRUTOS"]
    dias, estacoes = brutos_saida.shape

    # O CSV sai PRIMEIRO. É rápido, usa memória baixa e não tem limite de tamanho:
    # assim os dados baixados ficam seguros em disco antes de qualquer etapa pesada.
    # (Antes o xlsx vinha primeiro e, quando ele estourava a memória, o CSV nunca saía.)
    gravar_brutos_csv(brutos_saida, f"dados_{caso}.csv")
    print(f"✅ CSV dos brutos: dados_{caso}.csv ({dias} dias x {estacoes} estações)")

    abas = {"BRUTOS": (brutos_saida, "date"),
            "Excluidas_IDV": res["Excluidas_IDV"],
            "Historico": hist_ok}
    try:
        gravar_abas(f"dados_{caso}.xlsx", abas)
        print(f"✅ Brutos e histórico: dados_{caso}.xlsx ({estacoes} estações)")
    except PlanilhaGrandeDemais as e:
        # Não cabe no formato .xlsx. O CSV acima já tem tudo; o xlsx sai sem os brutos.
        del abas["BRUTOS"]
        gravar_abas(f"dados_{caso}.xlsx", abas)
        print(f"[AVISO] {e}")
        print(f"✅ Histórico: dados_{caso}.xlsx (brutos só em dados_{caso}.csv)")

    gravar_sumario(f"sumario_{caso}.xlsx", res)
    print(f"✅ Sumário: sumario_{caso}.xlsx ({len(res['ANUAL'])} estações; {len(excl)} excluídas por IDV)")

    nomes = dict(zip(inv["Codigo"], inv.get("Nome", pd.Series([""] * len(inv))).fillna("")))
    for arq in linha_tempo_estacoes(brutos_saida, f"{caso}_linha_tempo_estacoes.png", nomes,
                                    a.inicio or None, a.fim or None):
        print(f"✅ Linha do tempo: {arq}")

    anual = res["ANUAL"]
    if anual.empty:
        return
    plota_estacoes(anual, f"{caso}_mapa_IDV.png", "IDV", "Percentual (%)", "cmap1", escalas.lista("idv"),
                   "Distribuição das estações - IDV", histograma_=True, shapefile=a.shapefile)
    plota_estacoes(anual, f"{caso}_mapa_MEDIA.png", "Média mm/ano", "mm/ano", "cmap1", escalas.lista("media"),
                   "Distribuição das estações - Média anual", histograma_=True, shapefile=a.shapefile)
    if a.campo:
        plota_estacoes(anual, f"{caso}_mapa_{a.campo.replace(' ', '_').replace('/', '-')}.png", a.campo, a.campo,
                       "cmap1", escalas.resolver_intervalos(a.bounds), f"Distribuição das estações - {a.campo}",
                       histograma_=True, shapefile=a.shapefile)
    print("✅ Mapas gerados.")


if __name__ == "__main__":
    main()
