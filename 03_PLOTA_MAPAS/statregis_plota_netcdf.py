"""Plota um ou mais NetCDF gerados por 06_INTERPOLACAO (substitui plota_mapas_interpolados.py).

Correção principal: a grade é lida do próprio NetCDF (coordenadas latitude/longitude).
O script antigo recriava a grade com np.arange(..., 0.1) a partir do shapefile, o que
não bate com a grade da interpolação (linspace, resolução 0.01) -> mapa deslocado ou erro
de dimensão. Caminhos, títulos e intervalos agora vêm da linha de comando.

Exemplo:
  python statregis_plota_netcdf.py -n MEDIA/bahia_1991a2020_interpolacao_Kriging_spherical.nc \
      -s ../00_STUFF/BAHIA_2020Poly.shp -t "Climatologia 1991-2020" -u "mm/ano" \
      -i media --cores climatologia -o climatologia_1991a2020.png
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

from comum import escalas


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-n", "--netcdf", type=Path, required=True)
    p.add_argument("-s", "--shapefile", type=Path, default=None)
    p.add_argument("-o", "--saida", type=Path, default=None, help="PNG de saída (padrão: <netcdf>.png)")
    p.add_argument("-t", "--titulo", default="")
    p.add_argument("-u", "--unidade", default=None)
    p.add_argument("-i", "--intervalos", nargs="+", default=None,
                   help="Nome no escalas.config (media, p99...) ou números; padrão: 10 classes entre min e max")
    p.add_argument("--cores", nargs="+", default=["escala_cores"],
                   help="Nome de paleta do escalas.config ou lista de cores matplotlib")
    p.add_argument("--variavel", default=None, help="Variável do NetCDF (padrão: primeira com 2 dimensões)")
    a = p.parse_args()
    import xarray as xr

    ds = xr.open_dataset(a.netcdf)
    nome = a.variavel or next(v for v in ds.data_vars if ds[v].ndim == 2)
    da = ds[nome]
    lat = da["latitude"].values
    lon = da["longitude"].values
    z = da.values
    unidade = a.unidade or da.attrs.get("units", nome)

    niveis = escalas.resolver_intervalos(a.intervalos) or list(np.linspace(np.nanmin(z), np.nanmax(z), 11))
    cores = escalas.cores(a.cores[0]) if len(a.cores) == 1 and escalas.existe(a.cores[0]) else a.cores
    nb = len(niveis) - 1
    base = ListedColormap(cores)
    cmap = ListedColormap(cores if len(cores) == nb else [base(f) for f in np.linspace(0, 1, nb)])
    cmap.set_under(cmap(0)); cmap.set_over(cmap(nb - 1))

    fig, ax = plt.subplots(figsize=(11, 8))
    cf = ax.contourf(lon, lat, z, levels=niveis, cmap=cmap, norm=BoundaryNorm(niveis, nb), extend="both")
    cb = fig.colorbar(cf, ax=ax, ticks=niveis, label=unidade)
    cb.ax.set_yticklabels([f"{v:g}" for v in niveis])
    if a.shapefile:
        import geopandas as gpd
        g = gpd.read_file(a.shapefile)
        g = g.to_crs("EPSG:4326") if g.crs else g
        g.boundary.plot(ax=ax, color="black", linewidth=1)
    ax.set(xlim=(lon.min(), lon.max()), ylim=(lat.min(), lat.max()), xlabel="Longitude", ylabel="Latitude",
           title=a.titulo or ds.attrs.get("title", a.netcdf.stem))
    ax.set_aspect(1 / np.cos(np.radians(lat.mean())))
    saida = a.saida or a.netcdf.with_suffix(".png")
    fig.savefig(saida, dpi=300, bbox_inches="tight")
    print(f"Figura salva: {saida}")


if __name__ == "__main__":
    main()
