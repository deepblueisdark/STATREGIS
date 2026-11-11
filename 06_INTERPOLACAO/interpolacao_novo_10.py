# =============================================================================
# STATREGIS - 06_INTERPOLACAO - interpolacao_novo_10.py
# Autor: Reginaldo Ventura de Sá
#
# Versão corrigida de interpolacao_novo_09.py (escalas lidas de ../escalas.config). Mesma linha de comando
# (os argumentos antigos continuam válidos), com as correções:
#
#  1. BUG: Kriging (método padrão!) quebrava com NameError porque a lista
#     `variograma` só existia dentro de main(). Agora é passada explicitamente.
#  2. Distâncias em km (projeção equiretangular local), não em graus. Em graus,
#     1° de longitude a 22°S vale ~103 km e 1° de latitude ~111 km: todos os
#     métodos baseados em distância (IDW, Shepard, RBF, Kriging) ficavam
#     anisotrópicos sem querer. O variograma do Kriging passa a ter alcance em km.
#  3. Métricas por VALIDAÇÃO CRUZADA (leave-one-out). As métricas antigas
#     amostravam a superfície nos próprios pontos usados no ajuste: Kriging,
#     IDW, RBF e Linear são interpoladores exatos e davam erro ~0, então a
#     tabela não servia para comparar métodos. A métrica antiga continua na
#     aba "Metricas_Ajuste" só como referência.
#  4. IDW e Shepard vetorizados (eram dois laços Python por célula da grade:
#     lentos com resolução 0.01°).
#  5. Bivariate Smoothing Spline: o padrão s = n*var(valores) permitia resíduo
#     igual à variância total (superfície praticamente plana). Agora
#     s = --spline-s-frac * n * var (padrão 0.1 = resíduo de 10% da variância).
#  6. Rbf (descontinuado no SciPy) substituído por RBFInterpolator.
#  7. Mapa: valores fora de --intervalos apareciam em BRANCO (contourf não
#     pinta fora dos níveis). Agora a cor das pontas é usada (setas na barra).
#  8. Recorte opcional da grade pelo shapefile (--recortar mascara|limite);
#     o NetCDF recebe atributos CF (unidades, CRS) e o nome do autor real.
#  9. Rótulos da legenda vêm da linha de comando (antes eram fixos em
#     "Região Serrana" e estavam trocados entre limite e máscara).
# 10. Sem --extensao, a grade usa os limites dos shapefiles (+2%), em vez da
#     extensão fixa da Região Serrana.
# 11. Tabela de ranking (melhor método por RMSE da validação cruzada) e
#     planilha com previsões LOOCV por estação.
#
# Interpoladores: Kriging (Ordinário, PyKrige), IDW (p=2), Shepard (p=1),
# Thin Plate Spline, RBF Multiquadratic, Bivariate Smoothing Spline,
# Clough-Tocher Cubic, Linear (Delaunay), Polynomial Surface Regression,
# Nearest Neighbor (Thiessen).
# =============================================================================

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from comum import escalas

METODOS = [
    "IDW", "Thin Plate Spline", "Bivariate Smoothing Spline", "Kriging",
    "Clough-Tocher Cubic", "RBF Multiquadratic",
    "Polynomial Surface Regression", "Linear (Delaunay)",
    "Shepard", "Nearest Neighbor (Thiessen)",
]
VARIOGRAMAS = ["linear", "power", "gaussian", "spherical", "exponential", "hole-effect"]
KM_POR_GRAU_LAT = 110.574
KM_POR_GRAU_LON_EQUADOR = 111.320


# -----------------------------------------------------------------------------
# Argumentos
# -----------------------------------------------------------------------------
def parse_args(argv=None):
    pasta = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Interpolação espacial a partir de uma planilha Excel (STATREGIS).")
    p.add_argument("-c", "--caso", required=True, help="Identificador do caso (prefixo das saídas).")
    p.add_argument("-x", "--file-path", type=Path, required=True, help="Planilha Excel de entrada.")
    p.add_argument("-a", "--sheet-name", required=True, help="Aba da planilha.")
    p.add_argument("-v", "--variavel", required=True, help="Coluna a interpolar.")
    p.add_argument("-t", "--titulo", default=None, help="Título das figuras.")
    p.add_argument("-k", "--subtitulo", default=None, help="Subtítulo das figuras.")
    p.add_argument("-m", "--cmap", nargs="?", const="cmap", default=None,
                   help="Nome do mapa de cores no escalas.config (sem valor = 'cmap').")
    p.add_argument("-i", "--intervalos", nargs="?", const="intervalos", default=None,
                   help="Nome da lista de intervalos no escalas.config (sem valor = 'intervalos').")
    p.add_argument("--config", type=Path, default=None,
                   help="Arquivo de escalas alternativo (padrão: ../escalas.config).")
    p.add_argument("--shapefile", type=Path,
                   default=pasta.parent / "00_STUFF" / "buffer_final_regiaoserrana_srtm30metrosPoly.shp",
                   help="Shapefile do limite usado na seleção das estações.")
    p.add_argument("--mascara", type=Path,
                   default=pasta.parent / "00_STUFF" / "MASCARA_REGIAOSERRANAPoly.shp",
                   help="Shapefile da área de estudo.")
    p.add_argument("--rotulo-limite", default="Limite espacial para seleção das estações",
                   help="Texto da legenda para --shapefile.")
    p.add_argument("--rotulo-mascara", default="Área de estudo",
                   help="Texto da legenda para --mascara.")
    p.add_argument("--recortar", choices=["nenhum", "mascara", "limite"], default="nenhum",
                   help="Põe NaN na grade fora do polígono escolhido (padrão: nenhum).")
    p.add_argument("--saida-dir", type=Path, default=None, help="Pasta de saída (padrão: ./<caso>).")
    p.add_argument("--resolucao", type=float, default=0.01, help="Resolução da grade em graus (padrão 0.01).")
    p.add_argument("--extensao", nargs=4, type=float, metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"),
                   default=None, help="Limites da grade; padrão: limites dos shapefiles + 2%%.")
    p.add_argument("--metodos", nargs="+", choices=METODOS, default=["Kriging"],
                   help="Métodos a executar (padrão: Kriging). Use 'todos' via --todos.")
    p.add_argument("--todos", action="store_true", help="Executa todos os métodos.")
    p.add_argument("--variogramas", nargs="+", choices=VARIOGRAMAS, default=["spherical"],
                   help="Modelos de variograma do Kriging (padrão: spherical).")
    p.add_argument("--anisotropy-scaling", type=float, default=1.0)
    p.add_argument("--anisotropy-angle", type=float, default=0.0)
    p.add_argument("--nlags", type=int, default=6, help="Número de lags do variograma experimental (PyKrige).")
    p.add_argument("--spline-s-frac", type=float, default=0.1,
                   help="Suavização da Bivariate Spline: s = frac*n*var(valores) (padrão 0.1).")
    p.add_argument("--rbf-suavizacao", type=float, default=0.0,
                   help="Parâmetro 'smoothing' das RBF (0 = interpolação exata).")
    p.add_argument("--grau-polinomio", type=int, default=3)
    p.add_argument("--truncar-negativos", action="store_true",
                   help="Zera valores negativos na grade final (chuva não pode ser negativa).")
    p.add_argument("--sem-validacao-cruzada", action="store_true",
                   help="Pula a validação cruzada leave-one-out (mais rápido).")
    p.add_argument("--sem-kml", action="store_true", help="Não grava KML.")
    p.add_argument("--unidade", default=None, help="Unidade da variável (metadados NetCDF), ex.: mm/ano.")
    p.add_argument("--autor", default="Reginaldo Ventura de Sá - STATREGIS", help="Atributo created_by do NetCDF.")
    a = p.parse_args(argv)
    if a.todos:
        a.metodos = list(METODOS)
    if a.resolucao <= 0:
        p.error("--resolucao precisa ser > 0.")
    return a


# -----------------------------------------------------------------------------
# Escalas: ../escalas.config (arquivo único do STATREGIS). --config aponta outro arquivo,
# por exemplo o antigo interpola.config.
# -----------------------------------------------------------------------------
def carrega_intervalos_config(nome, config=None):
    return escalas.lista(nome, config)


def carrega_cores_config(nome, config=None):
    return escalas.cores(nome, config)


# -----------------------------------------------------------------------------
# Coordenadas: graus -> km (equiretangular local, centrada nas estações)
# Erro < 0,5% em regiões de poucas centenas de km; suficiente para pesos de
# distância e variograma. Para áreas do tamanho de um estado grande, use UTM.
# -----------------------------------------------------------------------------
@dataclass
class Projecao:
    lon0: float
    lat0: float

    @property
    def kx(self):
        return KM_POR_GRAU_LON_EQUADOR * np.cos(np.radians(self.lat0))

    def km(self, lon, lat):
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * KM_POR_GRAU_LAT


# -----------------------------------------------------------------------------
# Interpoladores. Contrato comum:
#   f(xs, ys, vs, xq, yq, opc) -> valores previstos em (xq, yq)
#   xs, ys, xq, yq em km; xq/yq são vetores 1D (pontos).
# Isso permite usar a MESMA função na grade e na validação cruzada.
# -----------------------------------------------------------------------------
def _idw(xs, ys, vs, xq, yq, power, bloco=20000):
    out = np.empty(len(xq), dtype=float)
    for i in range(0, len(xq), bloco):
        dx = xq[i:i + bloco, None] - xs[None, :]
        dy = yq[i:i + bloco, None] - ys[None, :]
        d = np.hypot(dx, dy)
        exato = d < 1e-9
        w = 1.0 / np.maximum(d, 1e-9) ** power
        z = (w * vs).sum(axis=1) / w.sum(axis=1)
        linhas = exato.any(axis=1)
        if linhas.any():  # ponto coincide com estação -> valor da estação
            z[linhas] = vs[exato[linhas].argmax(axis=1)]
        out[i:i + bloco] = z
    return out


def m_idw(xs, ys, vs, xq, yq, opc):
    return _idw(xs, ys, vs, xq, yq, 2.0)


def m_shepard(xs, ys, vs, xq, yq, opc):
    return _idw(xs, ys, vs, xq, yq, 1.0)


def _rbf(xs, ys, vs, xq, yq, kernel, opc):
    from scipy.interpolate import RBFInterpolator
    pts = np.column_stack((xs, ys))
    kw = {"kernel": kernel, "smoothing": opc.rbf_suavizacao}
    if kernel == "multiquadric":
        # Mesmo epsilon padrão do antigo scipy Rbf (distância média entre nós),
        # convertido para a convenção do RBFInterpolator (eps = 1/dist).
        area = np.ptp(xs) * np.ptp(ys)
        dist_media = (area / len(xs)) ** 0.5 if area > 0 else 1.0
        kw["epsilon"] = 1.0 / dist_media
    rbf = RBFInterpolator(pts, vs, **kw)
    return rbf(np.column_stack((xq, yq)))


def m_tps(xs, ys, vs, xq, yq, opc):
    return _rbf(xs, ys, vs, xq, yq, "thin_plate_spline", opc)


def m_multiquadric(xs, ys, vs, xq, yq, opc):
    return _rbf(xs, ys, vs, xq, yq, "multiquadric", opc)


def m_spline_suavizada(xs, ys, vs, xq, yq, opc):
    from scipy.interpolate import SmoothBivariateSpline
    if len(vs) < 16:
        raise ValueError("Bivariate Smoothing Spline cúbica exige pelo menos 16 estações.")
    s = opc.spline_s_frac * len(vs) * np.var(vs)
    sp = SmoothBivariateSpline(xs, ys, vs, kx=3, ky=3, s=s)
    return sp.ev(xq, yq)


def m_griddata(metodo):
    def f(xs, ys, vs, xq, yq, opc):
        from scipy.interpolate import griddata
        return griddata(np.column_stack((xs, ys)), vs, (xq, yq), method=metodo)
    return f


def m_polinomio(xs, ys, vs, xq, yq, opc):
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import PolynomialFeatures
    pf = PolynomialFeatures(degree=opc.grau_polinomio)
    X = pf.fit_transform(np.column_stack((xs, ys)))
    if X.shape[1] > len(vs):
        raise ValueError(f"Polinômio grau {opc.grau_polinomio} precisa de ≥ {X.shape[1]} estações.")
    mod = LinearRegression().fit(X, vs)
    return mod.predict(pf.transform(np.column_stack((xq, yq))))


def m_kriging(modelo):
    def f(xs, ys, vs, xq, yq, opc):
        from pykrige.ok import OrdinaryKriging
        ok = OrdinaryKriging(
            xs, ys, vs,
            variogram_model=modelo,
            nlags=opc.nlags,
            anisotropy_scaling=opc.anisotropy_scaling,
            anisotropy_angle=opc.anisotropy_angle,
            coordinates_type="euclidean",
            verbose=False, enable_plotting=False,
        )
        z, _ = ok.execute("points", xq, yq)
        f.parametros = dict(zip(_nomes_parametros(modelo), np.atleast_1d(ok.variogram_model_parameters)))
        return np.asarray(np.ma.filled(z, np.nan), dtype=float)
    f.parametros = {}
    return f


def _nomes_parametros(modelo):
    return {
        "linear": ["slope", "nugget"],
        "power": ["scale", "exponent", "nugget"],
    }.get(modelo, ["psill", "range_km", "nugget"])


def lista_metodos(opc):
    """Retorna [(nome, função)] na ordem pedida."""
    tabela = {
        "IDW": m_idw,
        "Shepard": m_shepard,
        "Thin Plate Spline": m_tps,
        "RBF Multiquadratic": m_multiquadric,
        "Bivariate Smoothing Spline": m_spline_suavizada,
        "Clough-Tocher Cubic": m_griddata("cubic"),
        "Linear (Delaunay)": m_griddata("linear"),
        "Nearest Neighbor (Thiessen)": m_griddata("nearest"),
        "Polynomial Surface Regression": m_polinomio,
    }
    saida = []
    for nome in opc.metodos:
        if nome == "Kriging":
            for v in opc.variogramas:
                if v == "hole-effect":
                    print("[AVISO] PyKrige considera hole-effect válido só em 1D; use com cautela.")
                saida.append((f"Kriging_{v}", m_kriging(v)))
        else:
            saida.append((nome, tabela[nome]))
    return saida


# -----------------------------------------------------------------------------
# Métricas e validação cruzada
# -----------------------------------------------------------------------------
COLUNAS_METRICAS = ["Metodo", "N", "ME (viés)", "MAE", "MSE", "RMSE", "R2", "Explained Variance",
                    "Max Error", "MedAE", "MAPE (%)", "PNAN", "PNEG"]


def calcula_metricas(nome, obs, prev):
    obs = np.asarray(obs, float)
    prev = np.asarray(prev, float)
    n = len(prev)
    pnan = 100 * (~np.isfinite(prev)).sum() / n if n else np.nan
    pneg = 100 * (np.isfinite(prev) & (prev < 0)).sum() / n if n else np.nan
    m = np.isfinite(obs) & np.isfinite(prev)
    o, p = obs[m], prev[m]
    if len(o) < 2:
        return [nome, len(o)] + [np.nan] * 9 + [pnan, pneg]
    e = p - o
    sst = ((o - o.mean()) ** 2).sum()
    r2 = 1 - (e ** 2).sum() / sst if sst > 0 else np.nan
    ev = 1 - np.var(e) / np.var(o) if np.var(o) > 0 else np.nan
    nz = o != 0
    mape = 100 * np.mean(np.abs(e[nz] / o[nz])) if nz.any() else np.nan
    return [nome, len(o), e.mean(), np.abs(e).mean(), (e ** 2).mean(), np.sqrt((e ** 2).mean()),
            r2, ev, np.abs(e).max(), np.median(np.abs(e)), mape, pnan, pneg]


def validacao_cruzada(func, xs, ys, vs, opc):
    """Leave-one-out: remove cada estação, ajusta com as demais e prevê nela."""
    n = len(vs)
    prev = np.full(n, np.nan)
    idx = np.arange(n)
    for i in range(n):
        m = idx != i
        try:
            prev[i] = func(xs[m], ys[m], vs[m], xs[i:i + 1], ys[i:i + 1], opc)[0]
        except Exception:
            prev[i] = np.nan
    return prev


# -----------------------------------------------------------------------------
# Grade, recorte e saídas
# -----------------------------------------------------------------------------
@dataclass
class Grade:
    gridx: np.ndarray
    gridy: np.ndarray
    mascara: np.ndarray = field(default=None)  # True = dentro

    @property
    def extent(self):
        return self.gridx[0], self.gridx[-1], self.gridy[0], self.gridy[-1]


def cria_grade(extensao, resolucao):
    x_min, x_max, y_min, y_max = extensao
    if x_min >= x_max or y_min >= y_max:
        raise ValueError("A extensão deve obedecer X_MIN < X_MAX e Y_MIN < Y_MAX.")
    nx = int(round((x_max - x_min) / resolucao)) + 1
    ny = int(round((y_max - y_min) / resolucao)) + 1
    return Grade(np.linspace(x_min, x_max, nx), np.linspace(y_min, y_max, ny))


def mascara_poligono(gdf, grade):
    from shapely import contains_xy
    gx, gy = np.meshgrid(grade.gridx, grade.gridy)
    geom = gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
    return contains_xy(geom, gx, gy)


def salvar_netcdf(caminho, grade, z, metodo, caso, opc, info_metodo=None):
    import xarray as xr
    da = xr.DataArray(
        z.astype("float32"), dims=("latitude", "longitude"),
        coords={"latitude": grade.gridy, "longitude": grade.gridx}, name="interpolacao",
    )
    da.attrs.update({"long_name": f"{opc.variavel} interpolado ({metodo})",
                     "source_variable": opc.variavel, "grid_mapping": "crs"})
    if opc.unidade:
        da.attrs["units"] = opc.unidade
    da["latitude"].attrs.update({"units": "degrees_north", "standard_name": "latitude"})
    da["longitude"].attrs.update({"units": "degrees_east", "standard_name": "longitude"})
    ds = da.to_dataset()
    ds["crs"] = xr.DataArray(0, attrs={"grid_mapping_name": "latitude_longitude", "epsg_code": "EPSG:4326"})
    ds.attrs.update({"title": f"Interpolação {metodo} - {caso}", "interpolation_method": metodo,
                     "created_by": opc.autor, "Conventions": "CF-1.8",
                     "history": f"{pd.Timestamp.now():%Y-%m-%d %H:%M} interpolacao_novo_10.py"})
    if info_metodo:
        ds.attrs.update({f"variogram_{k}": float(v) for k, v in info_metodo.items()})
    ds.to_netcdf(caminho)


def add_north_arrow(ax, xy=(0.93, 0.18), length=0.08, pad=0.06):
    from matplotlib.patches import FancyArrow
    x, y = xy
    ax.add_patch(FancyArrow(x, y, 0, length, width=0.01, transform=ax.transAxes, color="k",
                            head_width=0.03, head_length=0.03, zorder=20))
    ax.text(x, y + length + pad, "N", transform=ax.transAxes, ha="center", va="bottom",
            fontsize=12, fontweight="bold", zorder=21)


def add_scale_bar_geodesic(ax, x_min, x_max, y_min, y_max, length_km=20, anchor=(0.82, 0.08)):
    from matplotlib.patches import Rectangle
    lon_c = x_min + (x_max - x_min) * anchor[0]
    lat_c = y_min + (y_max - y_min) * anchor[1]
    try:
        import pyproj
        g = pyproj.Geod(ellps="GRS80")
        lon_r = g.fwd(lon_c, lat_c, 90.0, length_km * 500)[0]
        lon_l = g.fwd(lon_c, lat_c, -90.0, length_km * 500)[0]
    except ImportError:
        half = length_km / 2 / (KM_POR_GRAU_LON_EQUADOR * np.cos(np.radians(lat_c)))
        lon_l, lon_r = lon_c - half, lon_c + half
    h = (y_max - y_min) * 0.010
    y0 = lat_c - h / 2
    ax.add_patch(Rectangle((lon_l, y0), lon_c - lon_l, h, facecolor="w", edgecolor="k", zorder=19))
    ax.add_patch(Rectangle((lon_c, y0), lon_r - lon_c, h, facecolor="k", edgecolor="k", zorder=19))
    ax.text(lon_c, y0 + h + (y_max - y_min) * 0.006, f"{length_km:g} km",
            ha="center", va="bottom", fontsize=10, zorder=20)


def add_projection_label(ax, texto):
    ax.text(0.01, 0.01, texto, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=9, color="dimgray", zorder=25)


def _gms(valor, tipo):
    pos, neg = {"latitude": ("N", "S"), "longitude": ("L", "O")}[tipo]
    s = int(round(abs(valor) * 3600))
    g, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{g}°{m:02d}'{s:02d}\"{pos if valor >= 0 else neg}"


def aplica_formatacao_coordenadas(ax):
    from matplotlib.ticker import FuncFormatter
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _gms(v, "longitude")))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _gms(v, "latitude")))
    ax.tick_params(axis="both", labelsize=9)


def plota_mapa(caminho, grade, z, est, metodo, cores, intervalos, ctx, opc):
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.lines import Line2D

    x_min, x_max, y_min, y_max = grade.extent
    nb = len(intervalos) - 1
    # Uma cor por intervalo (reamostra a paleta se o nº de cores for diferente).
    base = ListedColormap(cores)
    cores_bins = cores if len(cores) == nb else [base(f) for f in np.linspace(0, 1, nb)]
    cmap = ListedColormap(cores_bins)
    # Abaixo/acima dos intervalos: cor da ponta (antes essas áreas ficavam em branco).
    cmap.set_under(cmap(0))
    cmap.set_over(cmap(nb - 1))
    norm = BoundaryNorm(intervalos, nb)

    fig, ax = plt.subplots(figsize=(15, 10))
    gx, gy = np.meshgrid(grade.gridx, grade.gridy)
    cf = ax.contourf(gx, gy, z, levels=intervalos, cmap=cmap, norm=norm, extend="both")
    cbar = fig.colorbar(cf, ax=ax, ticks=intervalos, label=opc.unidade or opc.variavel, shrink=0.85)
    cbar.ax.set_yticklabels([f"{v:g}" for v in intervalos])

    ax.scatter(est["lon"], est["lat"], color="black", s=40, zorder=5)
    for lo, la, v in zip(est["lon"], est["lat"], est["val"]):
        ax.text(lo, la, f"{v:.1f}", fontsize=5, ha="right", va="bottom", zorder=6)
    ctx["mascara"].boundary.plot(ax=ax, color="black", linewidth=2.2)
    ctx["limite"].plot(ax=ax, facecolor="none", edgecolor="blue", linewidth=2.0)

    titulo = opc.titulo or f"{opc.caso} - Interpolação método: {metodo}"
    fig.suptitle(titulo, fontsize=22, y=0.97)
    if opc.subtitulo:
        ax.set_title(opc.subtitulo, fontsize=15, pad=12)
    ax.set(xlim=(x_min, x_max), ylim=(y_min, y_max), xlabel="Longitude", ylabel="Latitude")
    ax.set_aspect(1 / np.cos(np.radians((y_min + y_max) / 2)))  # aspecto real na latitude média
    ax.grid(True, alpha=0.4)
    aplica_formatacao_coordenadas(ax)
    add_north_arrow(ax)
    add_scale_bar_geodesic(ax, x_min, x_max, y_min, y_max, length_km=ctx["escala_km"])
    add_projection_label(ax, "CRS: EPSG:4326 (SIRGAS 2000 ≈ WGS84) - distâncias de interpolação em km")
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor="black", markersize=7, label="Estações"),
        Line2D([0], [0], color="black", lw=2.2, label=opc.rotulo_mascara),
        Line2D([0], [0], color="blue", lw=2.0, label=opc.rotulo_limite),
    ], loc="upper left", framealpha=0.9)
    fig.savefig(caminho, dpi=300, bbox_inches="tight")
    plt.close(fig)


def salvar_kml_pontos(caminho, est):
    import simplekml
    kml = simplekml.Kml()
    for lo, la, v in zip(est["lon"], est["lat"], est["val"]):
        p = kml.newpoint(name=f"{v:.2f}", coords=[(lo, la)])
        p.description = f"Valor observado: {v:.2f}"
    kml.save(str(caminho))


def escala_automatica_km(extent):
    x_min, x_max, y_min, y_max = extent
    largura = (x_max - x_min) * KM_POR_GRAU_LON_EQUADOR * np.cos(np.radians((y_min + y_max) / 2))
    alvo = largura / 6
    for v in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v >= alvo:
            return v
    return 1000


# -----------------------------------------------------------------------------
# Leitura das estações
# -----------------------------------------------------------------------------
def le_estacoes(caminho, aba, variavel):
    df = pd.read_excel(caminho, sheet_name=aba)
    faltam = {"Latitude", "Longitude", variavel}.difference(df.columns)
    if faltam:
        raise ValueError(f"Colunas ausentes na aba '{aba}': {', '.join(sorted(faltam))}")
    cols = ["Latitude", "Longitude", variavel] + (["Codigo"] if "Codigo" in df.columns else [])
    df = df[cols].copy()
    for c in ["Latitude", "Longitude", variavel]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["Latitude", "Longitude", variavel])
    dup = int(df.duplicated(["Latitude", "Longitude"]).sum())
    if dup:
        print(f"[AVISO] {dup} coordenadas duplicadas agregadas pela média.")
        agg = {variavel: "mean"}
        if "Codigo" in df.columns:
            agg["Codigo"] = lambda s: "+".join(map(str, s))
        df = df.groupby(["Latitude", "Longitude"], as_index=False).agg(agg)
    if len(df) < 3:
        raise ValueError("São necessários ao menos 3 pontos válidos.")
    if "Codigo" not in df.columns:
        df["Codigo"] = np.arange(1, len(df) + 1)
    return df.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Execução
# -----------------------------------------------------------------------------
def executar(opc):
    import geopandas as gpd

    t0 = time.time()
    out = (opc.saida_dir or (Path.cwd() / opc.caso)).resolve()
    out.mkdir(parents=True, exist_ok=True)

    for caminho, rot in [(opc.file_path, "Planilha"), (opc.shapefile, "Shapefile limite"),
                         (opc.mascara, "Shapefile máscara")]:
        if not Path(caminho).is_file():
            raise FileNotFoundError(f"{rot} não encontrado: {caminho}")

    limite = gpd.read_file(opc.shapefile)
    mascara = gpd.read_file(opc.mascara)
    limite = limite.to_crs("EPSG:4326") if limite.crs else limite.set_crs("EPSG:4326")
    mascara = mascara.to_crs("EPSG:4326") if mascara.crs else mascara.set_crs("EPSG:4326")

    df = le_estacoes(opc.file_path, opc.sheet_name, opc.variavel)
    lon, lat, val = (df["Longitude"].to_numpy(float), df["Latitude"].to_numpy(float),
                     df[opc.variavel].to_numpy(float))

    if opc.extensao:
        extensao = opc.extensao
    else:
        b = np.vstack([limite.total_bounds, mascara.total_bounds])
        x0, y0, x1, y1 = b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()
        px, py = 0.02 * (x1 - x0), 0.02 * (y1 - y0)
        extensao = (x0 - px, x1 + px, y0 - py, y1 + py)
        print(f"[INFO] Extensão da grade pelos shapefiles: {np.round(extensao, 4).tolist()}")
    grade = cria_grade(extensao, opc.resolucao)
    if opc.recortar != "nenhum":
        grade.mascara = mascara_poligono(mascara if opc.recortar == "mascara" else limite, grade)

    proj = Projecao(lon0=float(lon.mean()), lat0=float(lat.mean()))
    xs, ys = proj.km(lon, lat)
    gx, gy = np.meshgrid(grade.gridx, grade.gridy)
    xq, yq = proj.km(gx.ravel(), gy.ravel())

    intervalos = (carrega_intervalos_config(opc.intervalos, opc.config) if opc.intervalos
                  else [10, 30, 100, 200, 300, 500])
    if len(intervalos) < 2 or any(b <= a for a, b in zip(intervalos, intervalos[1:])):
        raise ValueError("Intervalos devem ter ≥ 2 valores em ordem crescente.")
    cores = carrega_cores_config(opc.cmap, opc.config) if opc.cmap else ["red", "orange", "yellow", "green", "blue"]
    ctx = {"limite": limite, "mascara": mascara, "escala_km": escala_automatica_km(grade.extent)}
    est = {"lon": lon, "lat": lat, "val": val}

    print(f"[INFO] {len(val)} estações | grade {len(grade.gridx)}x{len(grade.gridy)} | "
          f"min={val.min():.2f} média={val.mean():.2f} max={val.max():.2f}")
    if val.min() < intervalos[0] or val.max() > intervalos[-1]:
        print(f"[AVISO] Dados ({val.min():.1f}–{val.max():.1f}) fora dos intervalos de cor "
              f"({intervalos[0]:g}–{intervalos[-1]:g}); considere outro -i.")

    loocv, ajuste, falhas, previsoes, variog = [], [], [], {"Codigo": df["Codigo"], "Latitude": lat,
                                                             "Longitude": lon, "Observado": val}, []
    for nome, func in lista_metodos(opc):
        print(f"---------------------------- {nome}")
        try:
            t = time.time()
            z = func(xs, ys, val, xq, yq, opc).reshape(gx.shape)
            info = dict(getattr(func, "parametros", {}) or {})
            if opc.truncar_negativos:
                z = np.where(z < 0, 0.0, z)
            if grade.mascara is not None:
                z = np.where(grade.mascara, z, np.nan)

            # Métrica antiga (ajuste nos próprios pontos) - só referência.
            pts_ajuste = func(xs, ys, val, xs, ys, opc)
            ajuste.append(calcula_metricas(nome, val, pts_ajuste))
            if not opc.sem_validacao_cruzada:
                prev = validacao_cruzada(func, xs, ys, val, opc)
                if opc.truncar_negativos:
                    prev = np.where(prev < 0, 0.0, prev)
                loocv.append(calcula_metricas(nome, val, prev))
                previsoes[nome] = prev
            if info:
                variog.append({"Metodo": nome, **info})

            base = out / f"{opc.caso}_interpolacao_{nome}"
            plota_mapa(base.with_suffix(".png"), grade, z, est, nome, cores, intervalos, ctx, opc)
            salvar_netcdf(base.with_suffix(".nc"), grade, z, nome, opc.caso, opc, info)
            print(f"    ok em {time.time() - t:.1f} s -> {base.name}.png/.nc")
        except Exception as erro:
            falhas.append([nome, f"{type(erro).__name__}: {erro}"])
            print(f"[ERRO] {nome}: {erro}")

    if not opc.sem_kml:
        try:
            salvar_kml_pontos(out / f"{opc.caso}_estacoes.kml", est)
        except Exception as erro:
            falhas.append(["KML", str(erro)])

    arq = out / f"{opc.caso}_metricas_interpolacao_completas.xlsx"
    with pd.ExcelWriter(arq, engine="openpyxl") as w:
        if loocv:
            m = pd.DataFrame(loocv, columns=COLUNAS_METRICAS)
            m.to_excel(w, sheet_name="Metricas_LOOCV", index=False)
            m.sort_values("RMSE")[["Metodo", "RMSE", "MAE", "ME (viés)", "R2", "PNAN"]] \
             .to_excel(w, sheet_name="Ranking", index=False)
            pd.DataFrame(previsoes).to_excel(w, sheet_name="Previsoes_LOOCV", index=False)
        pd.DataFrame(ajuste, columns=COLUNAS_METRICAS).to_excel(w, sheet_name="Metricas_Ajuste", index=False)
        if variog:
            pd.DataFrame(variog).to_excel(w, sheet_name="Variogramas", index=False)
        pd.DataFrame(falhas, columns=["Metodo", "Erro"]).to_excel(w, sheet_name="Falhas", index=False)
        pd.DataFrame({"Nota": [
            "Metricas_LOOCV: validação cruzada leave-one-out (cada estação prevista sem ela mesma). "
            "É a métrica correta para comparar métodos.",
            "Metricas_Ajuste: superfície amostrada nos pontos de ajuste (método antigo). Interpoladores "
            "exatos (Kriging sem pepita, IDW, RBF, Linear) dão erro ~0 aqui; não use para escolher método.",
            "Distâncias calculadas em km (equiretangular local, lat0="
            f"{proj.lat0:.4f}, lon0={proj.lon0:.4f}). Alcance do variograma em km.",
            "PNAN: % de estações sem previsão (ex.: fora do fecho convexo em Linear/Clough-Tocher).",
        ]}).to_excel(w, sheet_name="Notas", index=False)
    print(f"Métricas: {arq}")
    if loocv:
        print(pd.DataFrame(loocv, columns=COLUNAS_METRICAS)[["Metodo", "RMSE", "MAE", "ME (viés)", "R2"]]
              .sort_values("RMSE").to_string(index=False))
    print(f"Concluído em {time.time() - t0:.1f} s. Saídas em: {out}")


if __name__ == "__main__":
    try:
        executar(parse_args())
    except (FileNotFoundError, ValueError, OSError) as erro:
        raise SystemExit(f"Erro: {erro}")
