"""Critérios de seleção de estações e consolidação mensal (aba ALL) - versão única para 02 e 04.

Critérios (antes 'anos' e 'idv' eram o mesmo código):
  omm   : IDV >= idv_corte (80) E Num Anos Completos >= 30
  anos  : IDV >= idv_corte (80) E Num Anos Completos >= anos_minimos
  idv   : só IDV >= idv_corte (sem exigência de anos)
  nenhum: não filtra
"""
import pandas as pd

from .codigos import normalizar_codigo
from .estatisticas import NOMES_MESES
from .planilhas import gravar_abas

CRITERIOS = ["nenhum", "omm", "anos", "idv"]


def filtrar_por_criterio(df, criterio, anos_minimos=10, idv_corte=80.0):
    if criterio == "nenhum" or df.empty:
        return df.copy()
    exigidas = {"IDV"} if criterio == "idv" else {"IDV", "Num Anos Completos"}
    faltam = exigidas.difference(df.columns)
    if faltam:
        raise ValueError(f"Sumário sem {', '.join(sorted(faltam))}; regenere-o com o 02 atual.")
    mascara = pd.to_numeric(df["IDV"], errors="coerce") >= idv_corte
    if criterio in ("omm", "anos"):
        minimo = 30 if criterio == "omm" else anos_minimos
        mascara &= pd.to_numeric(df["Num Anos Completos"], errors="coerce") >= minimo
    return df.loc[mascara].copy()


def consolidar(anual, mensais, criterio, anos_minimos=10, campo="P99", idv_corte=80.0):
    """mensais: dict {'Jan': df, ...}. Retorna dict com abas filtradas, ALL, MEDIAS, ESTACOES_ANALISE e sets."""
    anual_f = filtrar_por_criterio(anual, criterio, anos_minimos, idv_corte)
    mens_f = {nome: filtrar_por_criterio(mensais.get(nome, pd.DataFrame()), criterio, anos_minimos, idv_corte)
              for nome in NOMES_MESES.values()}
    conjuntos = [set(df["Codigo"].map(normalizar_codigo)) if "Codigo" in df.columns else set()
                 for df in mens_f.values()]
    comuns = set.intersection(*conjuntos) if conjuntos else set()
    todos = set.union(*conjuntos) if conjuntos else set()

    partes = []
    for nome, df in mens_f.items():
        if df.empty:
            continue
        if campo not in df.columns:
            raise ValueError(f"Campo mensal '{campo}' não encontrado na aba {nome}.")
        sel = df[df["Codigo"].map(normalizar_codigo).isin(comuns)]
        partes.append(sel.assign(_cod=sel["Codigo"].map(normalizar_codigo))
                      .drop_duplicates("_cod")[["_cod", "Codigo", "Latitude", "Longitude", campo]]
                      .rename(columns={campo: nome}))
    meses = list(NOMES_MESES.values())
    if partes and comuns:
        todos_all = partes[0]
        for p in partes[1:]:
            todos_all = todos_all.merge(p[["_cod", p.columns[-1]]], on="_cod", how="inner")
        resultado_all = todos_all.drop(columns="_cod").reindex(columns=["Codigo", "Latitude", "Longitude", *meses])
        resultado_all = resultado_all.sort_values("Codigo").reset_index(drop=True)
    else:
        resultado_all = pd.DataFrame(columns=["Codigo", "Latitude", "Longitude", *meses])

    medias = resultado_all[meses].apply(pd.to_numeric, errors="coerce").mean()
    coords = pd.concat([df[[c for c in ["Codigo", "Nome", "Latitude", "Longitude"] if c in df.columns]]
                        for df in mens_f.values() if not df.empty] or [pd.DataFrame(columns=["Codigo"])],
                       ignore_index=True)
    coords["Codigo"] = coords["Codigo"].map(normalizar_codigo)
    coords = coords.drop_duplicates("Codigo")
    ordenados = sorted(todos)
    return {
        "ANUAL": anual_f, "mensais": mens_f, "ALL": resultado_all,
        "MEDIAS": pd.DataFrame({"Mês": meses, f"Média de {campo}": medias.reindex(meses).to_numpy()}),
        "ESTACOES_ANALISE": pd.DataFrame({"Codigo": ordenados,
                                          "Meses com dados": [sum(c in s for s in conjuntos) for c in ordenados]}),
        "comuns": comuns, "todos": todos, "coords": coords,
    }


def filtrar_brutos(brutos, codigos):
    """brutos com 1ª coluna = data (formato da aba BRUTOS)."""
    codigos = {normalizar_codigo(c) for c in codigos}
    cols = [c for c in brutos.columns[1:] if normalizar_codigo(c) in codigos]
    return brutos[[brutos.columns[0], *cols]].copy()


def filtrar_historico(historico, codigos, coluna="Codigo"):
    codigos = {normalizar_codigo(c) for c in codigos}
    if coluna not in historico.columns:
        return historico.iloc[0:0].copy()
    return historico[historico[coluna].map(normalizar_codigo).isin(codigos)].copy()


def gravar_consolidado(caminho, cons, brutos=None, historico=None, extras=None):
    """Grava o arquivo consolidado em streaming (ver comum/planilhas.py)."""
    abas = {"ANUAL": cons["ANUAL"]}
    abas["MENSAL"] = pd.concat([df for df in cons["mensais"].values() if not df.empty] or [pd.DataFrame()],
                               ignore_index=True)
    for nome, df in cons["mensais"].items():
        abas[nome] = df
    abas["ALL"] = cons["ALL"]
    abas["MEDIAS"] = cons["MEDIAS"]
    abas["ESTACOES_ANALISE"] = cons["ESTACOES_ANALISE"]
    if brutos is not None:
        abas["BRUTOS"] = filtrar_brutos(brutos, cons["comuns"])
    if historico is not None:
        abas["Historico"] = filtrar_historico(historico, cons["comuns"])
    for nome, df in (extras or {}).items():
        abas[nome[:31]] = df
    return gravar_abas(caminho, abas)
