"""STATREGIS - 04 - Cópia dos dados brutos só com as estações selecionadas.

Exemplo:
    python statregis_filtra_dados_brutos.py -b ../02_DOWNLOAD_E_PROCESSO/dados_RJ.xlsx \
           -f filtrados_RJ.xlsx -o dados_RJ_FILTRADO.xlsx

Lê os códigos da aba --aba-filtro (padrão ALL) e grava BRUTOS + Historico só com essas estações.
O arquivo original nunca é alterado. (O _FILTRADO.xlsx do 02 --criterio já traz essa aba BRUTOS.)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from comum.codigos import normalizar_codigo
from comum.filtragem import filtrar_brutos, filtrar_historico
from comum.planilhas import gravar_abas, ler_brutos


def main():
    pasta = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-b", "--brutos", type=Path,
                   default=pasta.parent / "02_DOWNLOAD_E_PROCESSO" / "dados_BAHIA_IPCC_CLIMATOLOGIA.xlsx")
    p.add_argument("-f", "--filtrado", type=Path, default=pasta / "BAHIA_IPCC_CLIMATOLOGIA_FILTRADO.xlsx")
    p.add_argument("-o", "--saida", type=Path, required=True)
    p.add_argument("--aba-filtro", default="ALL")
    p.add_argument("--aba-brutos", default="BRUTOS")
    p.add_argument("--aba-historico", default="Historico")
    p.add_argument("--coluna-codigo", default="Codigo")
    a = p.parse_args()

    brutos_arq, filtro_arq, saida = a.brutos.resolve(), a.filtrado.resolve(), a.saida.resolve()
    for c, r in [(brutos_arq, "Arquivo bruto"), (filtro_arq, "Arquivo filtrado")]:
        if not c.is_file():
            p.error(f"{r} não encontrado: {c}")
    if saida in (brutos_arq, filtro_arq):
        p.error("A saída deve ser diferente das entradas.")

    sel = pd.read_excel(filtro_arq, sheet_name=a.aba_filtro)
    if a.coluna_codigo not in sel.columns:
        p.error(f"A aba '{a.aba_filtro}' não tem a coluna '{a.coluna_codigo}'.")
    codigos = {c for c in sel[a.coluna_codigo].map(normalizar_codigo) if c}
    if not codigos:
        p.error("Nenhum código encontrado na aba de seleção.")

    brutos = ler_brutos(brutos_arq, a.aba_brutos)
    hist = pd.read_excel(brutos_arq, sheet_name=a.aba_historico)
    b_f = filtrar_brutos(brutos, codigos)
    h_f = filtrar_historico(hist, codigos, a.coluna_codigo)
    saida.parent.mkdir(parents=True, exist_ok=True)
    gravar_abas(saida, {a.aba_brutos: b_f, a.aba_historico: h_f})

    achados = {normalizar_codigo(c) for c in b_f.columns[1:]}
    faltam = sorted(codigos - achados)
    print(f"Arquivo criado: {saida}")
    print(f"Pedidas: {len(codigos)} | encontradas em BRUTOS: {len(achados)} | histórico: {len(h_f)}")
    if faltam:
        print(f"[AVISO] {len(faltam)} códigos sem coluna em BRUTOS: {', '.join(faltam[:20])}{' ...' if len(faltam) > 20 else ''}")


if __name__ == "__main__":
    main()
