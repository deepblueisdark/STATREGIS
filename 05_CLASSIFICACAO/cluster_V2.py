# =============================================================================
# STATREGIS - 05 - Classificação em faixas, clustering (KMeans / GMM) e associação com Köppen
# Autor: Reginaldo Ventura de Sá
#
# Uso (mesmos argumentos de antes):
#   python cluster_V2.py -x ../04_FILTRAGEM/filtrados_RJ.xlsx -c ANUAL -v "Média mm/ano" \
#          --shapefile ../00_STUFF/RIODEJANEIROPoly.shp --bounds media
#
# Correções:
# - KMeans/GMM agora agrupam o VALOR da variável. Antes agrupavam 'Classificacao' (o limite inferior
#   da faixa do histograma): o resultado dependia de --bounds e perdia a informação dentro de cada faixa.
# - Valores fora de --bounds não quebram mais o script (antes: erro de tamanho ao gravar os rótulos).
# - Faixa de K segura (antes podia ficar vazia e quebrar em np.argmin) e --random-state fixo
#   (antes o resultado mudava a cada execução).
# - Figuras gravadas direto em ./<aba>/ (antes movia TODOS os .png da pasta atual).
# - Aba Desc_<aba> gravada sempre que houver descartes (antes só quando o Excel já existia).
# - Shapefile de Köppen opcional: se não existir, a etapa é pulada com aviso.
# - Escalas lidas de ../escalas.config.
# =============================================================================
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.cluster import KMeans
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.mixture import GaussianMixture

from comum import PASTA_SHAPES, escalas
from comum.graficos import colormap, ler_shape


# ----------------------------------------------------------------------------- intervalos
def calcular_intervalos(x, bounds=None, arredondar=False):
    vmin, vmax = float(x.min()), float(x.max())
    n = len(x)
    n_int = max(2, int(np.sqrt(n)))
    passo = (vmax - vmin) / n_int if vmax != vmin else 1.0
    if bounds:
        intervals = np.asarray(escalas.resolver_intervalos(bounds), dtype=float)
    elif arredondar:
        p = max(1, math.ceil(passo))
        intervals = np.arange(math.floor(vmin), math.ceil(vmax) + p, p, dtype=float)
    else:
        intervals = np.linspace(vmin, vmax, n_int + 1)
    if len(intervals) < 2:
        intervals = np.array([vmin - 0.5, vmax + 0.5])
    return intervals, passo


# ----------------------------------------------------------------------------- clustering
def executar_clustering(valores, k_max=10, random_state=42):
    """valores: array 1D da variável. Retorna dict com métricas por K e rótulos do melhor K."""
    x = np.asarray(valores, float).reshape(-1, 1)
    n_unicos = len(np.unique(x))
    # Como antes, K vai até ~raiz(n): com poucas estações, K grande só "decora" os pontos.
    k_lim = min(k_max, max(2, int(np.sqrt(len(x)))), n_unicos - 1, len(x) - 1)
    if k_lim < 2:
        raise ValueError(f"Poucos valores distintos ({n_unicos}) para clustering (mínimo 3).")
    K = list(range(2, k_lim + 1))
    r = {"K": K, "distortion": [], "silhouette": [], "davies": [], "calinski": [],
         "bic": [], "gmm_silhouette": [], "gmm_davies": []}
    rotulos_km, rotulos_gmm = {}, {}
    for k in K:
        km = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit(x)
        rotulos_km[k] = km.labels_
        r["distortion"].append(km.inertia_)
        r["silhouette"].append(silhouette_score(x, km.labels_))
        r["davies"].append(davies_bouldin_score(x, km.labels_))
        r["calinski"].append(calinski_harabasz_score(x, km.labels_))

        gmm = GaussianMixture(n_components=k, n_init=10, random_state=random_state).fit(x)
        lab = gmm.predict(x)
        rotulos_gmm[k] = lab
        r["bic"].append(gmm.bic(x))
        ok = len(np.unique(lab)) > 1
        r["gmm_silhouette"].append(silhouette_score(x, lab) if ok else np.nan)
        r["gmm_davies"].append(davies_bouldin_score(x, lab) if ok else np.nan)

    r["best_k"] = K[int(np.nanargmin(r["davies"]))]
    r["best_gmm_k"] = K[int(np.nanargmin(r["bic"]))]
    r["kmeans_labels"] = _reordenar(x.ravel(), rotulos_km[r["best_k"]])
    r["gmm_labels"] = _reordenar(x.ravel(), rotulos_gmm[r["best_gmm_k"]])
    return r


def _reordenar(v, labels):
    """Renumera clusters em ordem crescente da média (cluster 0 = valores mais baixos)."""
    ordem = pd.Series(v).groupby(labels).mean().sort_values().index
    mapa = {antigo: novo for novo, antigo in enumerate(ordem)}
    return np.array([mapa[l] for l in labels])


# ----------------------------------------------------------------------------- figuras
def plotar_histograma(x, intervals, titulo, ylabel, destino, porcentagem=False, xlabel=""):
    counts, bins = np.histogram(x, bins=intervals)
    if porcentagem and counts.sum():
        counts = counts / counts.sum() * 100
        ylabel += " (%)"
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(bins[:-1], counts, width=np.diff(bins), align="edge", edgecolor="black", alpha=0.75)
    for i, c in enumerate(counts):
        ax.text((bins[i] + bins[i + 1]) / 2, c, f"{c:.1f}{'%' if porcentagem else ''}", ha="center", va="bottom", fontsize=9)
    ax.set(xlabel=f"Intervalos ({xlabel})", ylabel=ylabel, title=titulo)
    ax.set_xticks(intervals)
    ax.set_xticklabels([f"{i:g}" for i in intervals], rotation=45)
    ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plotar_metricas(r, destino):
    nomes = [("distortion", "Distorção (Inércia)"), ("silhouette", "Coeficiente de Silhueta"),
             ("davies", "Davies-Bouldin"), ("calinski", "Calinski-Harabasz"),
             ("bic", "BIC (GMM)"), ("gmm_silhouette", "Silhueta GMM"), ("gmm_davies", "Davies-Bouldin GMM")]
    fig, axs = plt.subplots(3, 3, figsize=(18, 12))
    axs = axs.ravel()
    for i, (m, nome) in enumerate(nomes):
        axs[i].plot(r["K"], r[m], marker="o")
        axs[i].set_title(nome)
        axs[i].set_xlabel("Número de clusters")
        axs[i].xaxis.set_major_locator(MaxNLocator(integer=True))
        axs[i].grid(True)
        axs[i].text(0, -0.22, f"({chr(97 + i)})", transform=axs[i].transAxes, fontsize=12, fontweight="bold")
    for j in range(len(nomes), len(axs)):
        fig.delaxes(axs[j])
    fig.tight_layout()
    fig.savefig(destino, dpi=300)
    plt.close(fig)


def plotar_dendrograma(valores, destino):
    fig, ax = plt.subplots(figsize=(12, 6))
    dendrogram(linkage(np.asarray(valores, float).reshape(-1, 1), method="ward"), ax=ax,
               distance_sort="descending", show_leaf_counts=True, no_labels=len(valores) > 60)
    ax.set(title="Dendrograma hierárquico (Ward)", xlabel="Estações", ylabel="Distância")
    fig.tight_layout()
    fig.savefig(destino, dpi=300)
    plt.close(fig)


def plotar_correlacao(df, destino):
    corr = df.select_dtypes("number").corr()
    if corr.empty:
        return
    fig, ax = plt.subplots(figsize=(max(8, len(corr) * 0.35), max(6, len(corr) * 0.35)))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    fig.colorbar(im, ax=ax)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(corr)), corr.columns, fontsize=7)
    ax.set_title("Matriz de correlação")
    fig.tight_layout()
    fig.savefig(destino, dpi=300)
    plt.close(fig)


def plotar_mapa_categorias(df, coluna, gdf, cores, titulo, destino):
    d = df.dropna(subset=[coluna, "Latitude", "Longitude"])
    if d.empty:
        return
    cats = sorted(d[coluna].unique(), key=lambda v: float(v) if str(v).replace(".", "", 1).replace("-", "", 1).isdigit() else str(v))
    cmap = colormap(cores, n=len(cats), discreto=True)
    fig, ax = plt.subplots(figsize=(10, 10))
    if gdf is not None:
        gdf.plot(ax=ax, facecolor="none", edgecolor="gray", linewidth=1)
    for i, c in enumerate(cats):
        s = d[d[coluna] == c]
        ax.scatter(pd.to_numeric(s["Longitude"]), pd.to_numeric(s["Latitude"]), color=cmap(i), s=50,
                   edgecolors="black", linewidths=0.3, label=f"{c:g}" if isinstance(c, (int, float, np.number)) else str(c), zorder=3)
    ax.legend(title=coluna, bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    ax.set(title=titulo, xlabel="Longitude", ylabel="Latitude")
    ax.grid(True, alpha=0.4)
    fig.tight_layout()
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- Köppen
def classificar_clima_koppen(df, shapefile_clima):
    import geopandas as gpd
    clima = gpd.read_file(shapefile_clima)
    if "CLIMA_K" not in clima.columns:
        raise ValueError(f"{shapefile_clima} não tem o campo CLIMA_K. Campos: {', '.join(map(str, clima.columns))}")
    if clima.crs is None:
        raise ValueError("O shapefile climático não informa o CRS.")
    clima = clima.loc[clima["CLIMA_K"].notna(), ["CLIMA_K", "geometry"]].copy()
    clima["CLIMA_K"] = clima["CLIMA_K"].astype(str).str.strip()
    lat = pd.to_numeric(df["Latitude"], errors="coerce")
    lon = pd.to_numeric(df["Longitude"], errors="coerce")
    pos = np.arange(len(df))
    ok = (lat.between(-90, 90) & lon.between(-180, 180)).to_numpy()
    pts = gpd.GeoDataFrame({"_row": pos[ok]}, geometry=gpd.points_from_xy(lon[ok], lat[ok]), crs="EPSG:4326").to_crs(clima.crs)
    assoc = gpd.sjoin(pts, clima, how="left", predicate="within")
    sem = assoc.loc[assoc["CLIMA_K"].isna(), "_row"]
    if not sem.empty:
        borda = gpd.sjoin(pts[pts["_row"].isin(sem)], clima, how="inner", predicate="intersects")
        assoc = pd.concat([assoc[assoc["CLIMA_K"].notna()], borda], ignore_index=True)
    assoc = assoc.dropna(subset=["CLIMA_K"]).drop_duplicates("_row")
    classes = pd.Series("Sem classificação", index=pos, dtype="object")
    classes.loc[assoc["_row"].astype(int).to_numpy()] = assoc["CLIMA_K"].to_numpy()
    out = df.copy()
    out["Clima_Koppen"] = classes.to_numpy()
    return out, clima.to_crs("EPSG:4326")


def plotar_mapa_clima(df, clima, destino):
    classes = sorted(clima["CLIMA_K"].unique())
    pal = plt.get_cmap("tab10")
    cores = {c: pal(i % 10) for i, c in enumerate(classes)}
    fig, ax = plt.subplots(figsize=(11, 10))
    for c, pol in clima.groupby("CLIMA_K"):
        pol.plot(ax=ax, color=cores[c], edgecolor="white", linewidth=0.35)
    for c in classes:
        s = df[df["Clima_Koppen"] == c]
        if not s.empty:
            ax.scatter(pd.to_numeric(s["Longitude"]), pd.to_numeric(s["Latitude"]), color=[cores[c]],
                       edgecolors="black", linewidths=0.35, s=28, zorder=3)
    ax.legend(handles=[Patch(facecolor=cores[c], edgecolor="black", label=c) for c in classes],
              title="Classes de Köppen", loc="best", fontsize=9)
    ax.set(title="Classificação climática de Köppen nas estações", xlabel="Longitude", ylabel="Latitude")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(destino, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- principal
def main():
    p = argparse.ArgumentParser(description="Classificação e clusterização de dados pluviométricos")
    p.add_argument("-x", "--entrada", required=True)
    p.add_argument("-c", "--planilha", required=True)
    p.add_argument("-v", "--variavel", required=True)
    p.add_argument("--shapefile", default=None)
    p.add_argument("--shapefile-clima", default=str(PASTA_SHAPES / "BAHIA_COM_CLIMAPoly.shp"),
                   help="Polígonos com campo CLIMA_K (padrão BAHIA_COM_CLIMAPoly.shp); 'nenhum' para pular")
    p.add_argument("--cmap", default="cmap1", help="Paleta do escalas.config")
    p.add_argument("--arredondar", action="store_true")
    p.add_argument("--bounds", default=None, help="Nome no escalas.config ou 100,200,300")
    p.add_argument("--kmax", type=int, default=10, help="Maior K testado (padrão 10; também limitado a raiz(n))")
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--saida", default="resultado_clustering.xlsx")
    a = p.parse_args()

    aba = a.planilha
    pasta_fig = Path(".") / aba
    pasta_fig.mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(a.entrada, sheet_name=aba)
    if a.variavel not in df.columns:
        sys.exit(f"Coluna '{a.variavel}' não existe na aba {aba}.")

    clima_gdf = None
    if a.shapefile_clima and a.shapefile_clima != "nenhum" and Path(a.shapefile_clima).is_file():
        df, clima_gdf = classificar_clima_koppen(df, a.shapefile_clima)
        print("Estações por classe de Köppen:\n" + df["Clima_Koppen"].value_counts(dropna=False).to_string())
    elif a.shapefile_clima != "nenhum":
        print(f"[AVISO] Shapefile de Köppen não encontrado ({a.shapefile_clima}); etapa pulada.")

    x = pd.to_numeric(df[a.variavel], errors="coerce")
    xv = x.dropna()
    if xv.empty:
        sys.exit(f"A coluna '{a.variavel}' não tem valores numéricos.")
    intervals, passo = calcular_intervalos(xv, a.bounds, a.arredondar)
    print("-" * 48)
    print(f"Intervalos ({'--bounds' if a.bounds else 'automáticos'}): {np.round(intervals, 2)}")
    print(f"Mín {xv.min():.2f} | Máx {xv.max():.2f} | N {len(xv)} | passo base {passo:.2f}")
    print("-" * 48)

    df["Classificacao"] = pd.cut(x, bins=intervals, labels=intervals[:-1], include_lowest=True).astype(float)
    df["Intervalo"] = pd.cut(x, bins=intervals, labels=np.arange(1, len(intervals)), include_lowest=True).astype(float)
    fora = df["Classificacao"].isna() & x.notna()
    if fora.any():
        print(f"[AVISO] {int(fora.sum())} estações fora dos intervalos; vão para a aba Desc_{aba}.")

    dentro = x[df["Classificacao"].notna()]
    plotar_histograma(dentro, intervals, "Histograma - Frequência", "Frequência", pasta_fig / "hist_frequencia.png", xlabel=a.variavel)
    plotar_histograma(dentro, intervals, "Histograma - Porcentagem", "Porcentagem", pasta_fig / "hist_porcentagem.png", True, a.variavel)

    r = None
    try:
        r = executar_clustering(xv.to_numpy(), a.kmax, a.random_state)
        df.loc[xv.index, "Cluster"] = r["kmeans_labels"]
        df.loc[xv.index, "GMM_Cluster"] = r["gmm_labels"]
        plotar_metricas(r, pasta_fig / "metricas_clustering.png")
        print(f"Melhor K: KMeans (Davies-Bouldin) = {r['best_k']} | GMM (BIC) = {r['best_gmm_k']}")
    except ValueError as e:
        print(f"[AVISO] Clustering não executado: {e}")
    if len(xv) >= 2:
        plotar_dendrograma(xv, pasta_fig / "dendrograma.png")
    plotar_correlacao(df, pasta_fig / "matriz_correlacao.png")

    gdf = ler_shape(a.shapefile) if a.shapefile else None
    cores = a.cmap if escalas.existe(a.cmap) else "cmap1"
    plotar_mapa_categorias(df, "Classificacao", gdf, cores, f"Mapa de classificação - {aba}", pasta_fig / "mapa_classificacao.png")
    if r is not None:
        plotar_mapa_categorias(df, "Cluster", gdf, "escala_cores", f"Clusters KMeans (K={r['best_k']}) - {aba}", pasta_fig / "mapa_cluster_kmeans.png")
        plotar_mapa_categorias(df, "GMM_Cluster", gdf, "escala_cores", f"Clusters GMM (K={r['best_gmm_k']}) - {aba}", pasta_fig / "mapa_cluster_gmm.png")
    if clima_gdf is not None:
        plotar_mapa_clima(df, clima_gdf, pasta_fig / "mapa_clima_koppen_estacoes.png")

    counts, bins = np.histogram(dentro, bins=intervals)
    hist_df = pd.DataFrame({"Intervalo_Inicial": bins[:-1], "Intervalo_Final": bins[1:], "Frequencia": counts,
                            "Percentual (%)": counts / counts.sum() * 100 if counts.sum() else 0})
    metricas_df = pd.DataFrame({
        "Parametro": ["Variavel", "Numero_Observacoes", "Valor_Minimo", "Valor_Maximo", "Numero_Intervalos",
                      "Melhor_K_KMeans", "Melhor_K_GMM", "Random_State"],
        "Valor": [a.variavel, len(xv), xv.min(), xv.max(), len(intervals) - 1,
                  r["best_k"] if r else np.nan, r["best_gmm_k"] if r else np.nan, a.random_state]})
    abas = {f"Dados_{aba}": df, f"Hist_{aba}": hist_df, f"Metricas_{aba}": metricas_df}
    if r is not None:
        abas[f"K_{aba}"] = pd.DataFrame({k: r[k] for k in ["K", "distortion", "silhouette", "davies", "calinski",
                                                          "bic", "gmm_silhouette", "gmm_davies"]})
        resumo = df.groupby("Cluster")[a.variavel].agg(["count", "min", "mean", "max"]).reset_index()
        abas[f"Clusters_{aba}"] = resumo
    if "Clima_Koppen" in df.columns:
        abas["Clima_Koppen"] = df["Clima_Koppen"].value_counts().rename_axis("Clima_Koppen").reset_index(name="Numero_Estacoes")
        if "Cluster" in df.columns:
            abas["Cluster_Clima"] = pd.crosstab(df["Clima_Koppen"], df["Cluster"], margins=True).reset_index()
    if fora.any():
        abas[f"Desc_{aba}"] = df[fora]

    modo = {"mode": "a", "if_sheet_exists": "replace"} if Path(a.saida).is_file() else {"mode": "w"}
    with pd.ExcelWriter(a.saida, engine="openpyxl", **modo) as w:
        for nome, tab in abas.items():
            tab.to_excel(w, sheet_name=nome[:31], index=False)
    print(f"Resultados: {a.saida} | figuras em {pasta_fig.resolve()}")


if __name__ == "__main__":
    main()
