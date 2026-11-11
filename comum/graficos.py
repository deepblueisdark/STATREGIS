"""Gráficos compartilhados (antes copiados em 02 x2, 03 e 04)."""
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap

from . import escalas as _esc


def ler_shape(caminho):
    if not caminho:
        return None
    caminho = Path(caminho)
    if not caminho.is_file():
        print(f"[AVISO] Shapefile não encontrado: {caminho}")
        return None
    import geopandas as gpd
    g = gpd.read_file(caminho)
    return g.to_crs("EPSG:4326") if g.crs is not None else g.set_crs("EPSG:4326")


def colormap(cores, n=None, discreto=False):
    """Lista de cores (qualquer formato do escalas.config) -> Colormap."""
    if isinstance(cores, str):
        cores = _esc.cores(cores)
    cores = [_esc.normaliza_cor(c) for c in cores]
    if discreto:
        base = ListedColormap(cores)
        if n and n != len(cores):
            return ListedColormap([base(f) for f in np.linspace(0, 1, n)])
        return base
    return LinearSegmentedColormap.from_list("statregis", cores, N=n or 256)


def histograma(dados, legenda, bins, destino, titulo):
    dados = pd.to_numeric(pd.Series(dados), errors="coerce").dropna()
    if dados.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(dados, bins=bins if bins is not None and len(bins) > 1 else 30, color="gray", edgecolor="black")
    ax.set(title=titulo, xlabel=legenda, ylabel="Frequência")
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plota_estacoes(df, destino, campo, legenda="", cores="cmap1", bounds=None, titulo="",
                   histograma_=False, shapefile=None, idv_min=None, idv_max=None, gdf=None,
                   extensao=None):
    """Mapa de pontos colorido por `campo`. idv_min/idv_max filtram pela coluna IDV (opcional)."""
    if campo not in df.columns:
        print(f"[AVISO] Campo '{campo}' não está na planilha; mapa não gerado.")
        return
    d = df.copy()
    if idv_min is not None and idv_max is not None and idv_min != idv_max and "IDV" in d.columns:
        idv = pd.to_numeric(d["IDV"], errors="coerce")
        d = d[(idv >= idv_min) & (idv <= idv_max)]
    d["_v"] = pd.to_numeric(d[campo], errors="coerce")
    d = d.dropna(subset=["_v", "Latitude", "Longitude"])
    if d.empty:
        print(f"[AVISO] Sem dados para o campo '{campo}'.")
        return
    destino = str(destino)
    bounds = list(bounds) if bounds is not None and len(bounds) > 1 else None
    if histograma_:
        histograma(d["_v"], legenda or campo, bounds, destino.replace(".png", "_hist.png"), f"Histograma - {campo}")

    if bounds:
        nb = len(bounds) - 1
        cmap = colormap(cores, n=nb, discreto=True)
        cmap.set_under(cmap(0)); cmap.set_over(cmap(nb - 1))
        norm = BoundaryNorm(bounds, nb)
    else:
        lo, hi = np.floor(d["_v"].min() / 10) * 10, np.ceil(d["_v"].max() / 10) * 10
        cmap = colormap(cores)
        norm = plt.Normalize(lo, hi if hi > lo else lo + 1)

    fig, ax = plt.subplots(figsize=(10, 8))
    g = gdf if gdf is not None else ler_shape(shapefile)
    if g is not None:
        g.plot(ax=ax, edgecolor="gray", facecolor="none", lw=1)
    sc = ax.scatter(pd.to_numeric(d["Longitude"]), pd.to_numeric(d["Latitude"]), c=d["_v"], cmap=cmap,
                    norm=norm, marker="o", s=30, edgecolors="black", linewidths=0.25, zorder=3)
    cb = fig.colorbar(sc, ax=ax, extend="both" if bounds else "neither")
    if bounds:
        cb.set_ticks(bounds)
    cb.set_label(legenda or campo, labelpad=15)
    if extensao is not None:
        ax.set(xlim=extensao[:2], ylim=extensao[2:])
    elif g is not None:
        x0, y0, x1, y1 = g.total_bounds
        ax.set(xlim=(x0, x1), ylim=(y0, y1))
    ax.set(title=titulo or f"Distribuição das estações - {campo}", xlabel="Longitude", ylabel="Latitude")
    ax.grid(True, linestyle="--", alpha=0.4)
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


def linha_tempo_estacoes(dados, arquivo_png, nomes=None, inicio=None, fim=None, por_pagina=80):
    """Por estação, os anos com pelo menos um registro válido. Retorna lista de arquivos gerados."""
    if dados is None or dados.empty:
        return []
    m = dados.copy()
    m.index = pd.to_datetime(m.index, errors="coerce")
    m = m.loc[~m.index.isna()]
    m = m.loc[~m.index.duplicated(keep="first")].apply(pd.to_numeric, errors="coerce").where(lambda v: v >= 0)
    m = m.loc[:, ~m.isna().all()]
    if m.empty:
        return []
    ano_max = max(pd.Timestamp.today().year, int(m.index.year.max()))
    ano_min = min(1900, int(m.index.year.min()))
    anos = np.arange(ano_min, ano_max + 1)
    fixo = bool(inicio and fim)
    a_ini = pd.Timestamp(inicio).year if fixo else int(m.index.year.min())
    a_fim = pd.Timestamp(fim).year if fixo else int(m.index.year.max())
    pres = m.notna().groupby(m.index.year).any().reindex(anos, fill_value=False)
    primeiro = {c: (anos[pres[c].to_numpy()].min() if pres[c].any() else ano_max + 1) for c in m.columns}
    ordem = sorted(m.columns, key=lambda c: (primeiro[c], str(c)))
    rot = [f"{c} - {nomes.get(str(c), '')}".rstrip(" -") if nomes else str(c) for c in ordem]
    cores = plt.get_cmap("tab20")
    caminho = Path(arquivo_png)
    arquivos = []
    paginas = math.ceil(len(ordem) / por_pagina)
    for p in range(paginas):
        cods = ordem[p * por_pagina:(p + 1) * por_pagina]
        rots = rot[p * por_pagina:(p + 1) * por_pagina]
        destino = caminho if p == 0 else caminho.with_name(f"{caminho.stem}_parte_{p + 1:02d}{caminho.suffix}")
        fig, ax = plt.subplots(figsize=(15, max(6, 2 + len(cods) * 0.18)))
        for i, c in enumerate(cods):
            f = pres[c].to_numpy()
            j = 0
            while j < len(f):
                if f[j]:
                    k = j
                    while k + 1 < len(f) and f[k + 1]:
                        k += 1
                    ax.hlines(i, anos[j], anos[k] + 1, color=cores((p * por_pagina + i) % 20), linewidth=2)
                    j = k + 1
                else:
                    j += 1
        titulo = "Períodos de dados das estações (anos com pelo menos um registro válido)"
        if paginas > 1:
            titulo += f" — página {p + 1}/{paginas}"
        ax.set(title=titulo, xlabel="Ano", ylabel="Estação pluviométrica", xlim=(a_ini, a_fim + 1))
        passo = 5 if a_fim - a_ini <= 50 else 10
        ax.set_xticks(list(range(a_ini - a_ini % passo, a_fim + 2, passo)))
        ax.set_xlim(a_ini, a_fim + 1)
        ax.set_yticks(range(len(cods)), rots)
        ax.tick_params(axis="y", labelsize=6)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_ylim(-1, len(cods))
        fig.tight_layout()
        fig.savefig(destino, dpi=200, bbox_inches="tight")
        plt.close(fig)
        arquivos.append(str(destino))
    return arquivos


def mapa_comuns(coords, comuns, todos, destino, gdf=None):
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for ax, cods, cor, titulo in [(axes[0], comuns, "royalblue", f"Comuns aos 12 meses (n={len(comuns)})"),
                                  (axes[1], todos - comuns, "firebrick", f"Não comuns (n={len(todos - comuns)})")]:
        if gdf is not None:
            gdf.plot(ax=ax, facecolor="whitesmoke", edgecolor="gray", linewidth=0.7)
        sub = coords[coords["Codigo"].isin(cods)]
        ax.scatter(sub["Longitude"], sub["Latitude"], c=cor, s=34, edgecolors="black", linewidths=0.25, zorder=3)
        ax.set(title=titulo, xlabel="Longitude", ylabel="Latitude")
        ax.grid(True, linestyle="--", alpha=0.35)
    fig.tight_layout()
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


def mapas_filtragem(cons, pasta, gdf=None, prefixo="filtragem"):
    """Mapas de IDV por mês, ANUAL e comuns/não comuns (saída padrão do 04 e do 02 --criterio)."""
    pasta = Path(pasta)
    bounds = _esc.lista("idv") if _esc.existe("idv") else None
    for nome, df in cons["mensais"].items():
        if not df.empty:
            plota_estacoes(df, pasta / f"{prefixo}_{nome}_IDV.png", "IDV", "IDV (%)", "cmap1", bounds,
                           f"Estações filtradas — {nome}", gdf=gdf)
    if not cons["ANUAL"].empty:
        plota_estacoes(cons["ANUAL"], pasta / f"{prefixo}_ANUAL_IDV.png", "IDV", "IDV (%)", "cmap1", bounds,
                       "Estações filtradas — ANUAL", gdf=gdf)
    if not cons["coords"].empty:
        mapa_comuns(cons["coords"], cons["comuns"], cons["todos"], pasta / "Figura_estacoes_mensais.png", gdf)
