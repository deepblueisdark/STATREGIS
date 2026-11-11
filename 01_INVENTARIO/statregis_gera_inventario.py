# =======================================================================
# STATREGIS - 01_INVENTARIO - Inventário de estações da ANA + mapa
# Autor: Reginaldo Ventura de Sá
#
# Uso:
#   python statregis_gera_inventario.py -x inventario_RJ.xlsx -u RJ -s ../00_STUFF/RIODEJANEIROPoly.shp
#   python statregis_gera_inventario.py -x inv_serra.xlsx -u RJ -s ../00_STUFF/buffer_...Poly.shp --tipo 2
#
# Correções: o fundo 'naturalearth_lowres' foi removido do geopandas >= 1.0 (o mapa quebrava);
# agora o fundo é o próprio shapefile (ou --fundo). Estações em polígonos sobrepostos não
# saem mais duplicadas. O cliente ANA é o mesmo do 02 (comum/ana.py), com timeout e novas tentativas.
# ========================================================================
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.pyplot as plt

from comum.ana import UF_ANA_MAP, ServiceANA
from comum.graficos import ler_shape


def filtrar_por_shape(inv, shape):
    import geopandas as gpd
    pts = gpd.GeoDataFrame(inv, geometry=gpd.points_from_xy(inv.Longitude, inv.Latitude), crs="EPSG:4326")
    dentro = gpd.sjoin(pts, shape[["geometry"]], predicate="within", how="inner")
    return inv.loc[dentro.index.unique()]


def plot_station_map(inv, xlsx, shape=None, fundo=None):
    if inv.empty:
        print("Aviso: inventário vazio; mapa não gerado.")
        return
    saida = Path(xlsx).with_name(Path(xlsx).stem + "_map.png")
    fig, ax = plt.subplots(figsize=(10, 8))
    handles = []
    if fundo is not None:
        fundo.plot(ax=ax, color="lightgrey", edgecolor="white", alpha=0.6)
    if shape is not None:
        shape.plot(ax=ax, facecolor="none", edgecolor="blue", linewidth=1.5, linestyle="--")
        handles.append(mlines.Line2D([], [], color="blue", linestyle="--", label="Área do shapefile"))
    ax.scatter(inv.Longitude, inv.Latitude, color="red", s=12, zorder=3)
    handles.insert(0, mlines.Line2D([], [], color="red", marker="o", linestyle="None", label=f"Estações (n={len(inv)})"))
    ref = shape if shape is not None else None
    if ref is not None:
        x0, y0, x1, y1 = ref.total_bounds
    else:
        x0, x1, y0, y1 = inv.Longitude.min(), inv.Longitude.max(), inv.Latitude.min(), inv.Latitude.max()
    px, py = max((x1 - x0) * 0.1, 0.2), max((y1 - y0) * 0.1, 0.2)
    ax.set(xlim=(x0 - px, x1 + px), ylim=(y0 - py, y1 + py), title="Inventário de estações ANA",
           xlabel="Longitude", ylabel="Latitude")
    import numpy as np
    ax.set_aspect(1 / np.cos(np.radians((y0 + y1) / 2)))
    ax.legend(handles=handles, loc="upper left")
    ax.annotate("N", xy=(0.94, 0.22), xytext=(0.94, 0.10), arrowprops=dict(facecolor="black", width=3, headwidth=10),
                ha="center", va="center", fontsize=12, fontweight="bold", xycoords=ax.transAxes)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(saida, dpi=300)
    plt.close(fig)
    print(f"Mapa salvo: {saida}")


def main():
    p = argparse.ArgumentParser(description="Inventário de estações da ANA com mapa.")
    p.add_argument("-x", "--xls", required=True, help="Excel de saída")
    p.add_argument("-s", "--shapefile", help="Shapefile para filtrar espacialmente (opcional)")
    p.add_argument("-u", "--uf", help="UF (sigla ou nome) para filtrar na consulta (opcional)")
    p.add_argument("--tipo", default="", help="Tipo de estação na ANA: 1=fluviométrica, 2=pluviométrica (padrão: todas)")
    p.add_argument("--fundo", help="Shapefile de fundo do mapa (opcional)")
    a = p.parse_args()

    ana = ServiceANA()
    estado = UF_ANA_MAP.get(a.uf.upper(), a.uf) if a.uf else ""
    print(f"Gerando inventário: {estado or 'Brasil inteiro'}...")
    try:
        inv = ana.inventario(estado=estado, tipo=a.tipo)
    except Exception as e:
        sys.exit(f"Erro ao acessar a ANA: {e}")
    print(f"{len(inv)} estações retornadas.")

    shape = ler_shape(a.shapefile) if a.shapefile else None
    if a.shapefile and shape is None:
        sys.exit(f"Shapefile não encontrado: {a.shapefile}")
    if shape is not None and not inv.empty:
        inv = filtrar_por_shape(inv, shape)
        print(f"{len(inv)} estações dentro do shapefile.")

    if inv.empty:
        print("Aviso: inventário vazio; nenhum arquivo criado.")
        return
    inv.to_excel(a.xls, index=True)
    print(f"Inventário salvo: {a.xls}")
    plot_station_map(inv, a.xls, shape, ler_shape(a.fundo) if a.fundo else None)


if __name__ == "__main__":
    main()
