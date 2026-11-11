# Interpoladores disponíveis:
# Kriging, IDW (potência 2), Shepard (potência 1), Thin Plate RBF,
# Bivariate Smoothing Spline, Clough-Tocher cúbico, RBF multiquadrático,
# regressão polinomial, Linear Delaunay e vizinho mais próximo/Thiessen.
#
# Redundâncias removidas/esclarecidas:
# NRN e Thiessen eram ambos vizinho mais próximo; TLI e Linear eram ambos
# interpolação linear de Delaunay. `griddata(cubic)` implementa Clough-Tocher,
# não Natural Neighbor. A antiga função chamada co-kriging era apenas a média
# de dois krigings ordinários, portanto não era co-kriging. IDW e Shepard usam
# a mesma família de pesos com potências 2 e 1; não produzem o mesmo resultado.

import argparse
import ast
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Executa interpolação a partir de uma planilha Excel."
    )
    parser.add_argument("-c", "--caso", required=True, help="Identificador do caso.")
    parser.add_argument("-x", "--file-path", type=Path, required=True, help="Caminho do arquivo Excel de entrada.")
    parser.add_argument("-a", "--sheet-name", required=True, help="Nome da aba da planilha.")
    parser.add_argument("-v", "--variavel", required=True, help="Nome da coluna da variável a interpolar.")
    parser.add_argument(
        "-t",
        "--titulo",
        default=None,
        help="Título principal das imagens geradas. Se omitido, usa o padrão atual do código.",
    )
    parser.add_argument(
        "-k",
        "--subtitulo",
        default=None,
        help="Subtítulo das imagens geradas, centralizado abaixo do título principal.",
    )
    parser.add_argument(
        "-m",
        "--cmap",
        nargs="?",
        const="cmap",
        default=None,
        help="Nome do mapa de cores no interpola.config. Se usado sem valor, usa 'cmap'.",
    )
    parser.add_argument(
        "-i",
        "--intervalos",
        nargs="?",
        const="intervalos",
        default=None,
        help="Nome da lista de intervalos no interpola.config. Se usado sem valor, usa 'intervalos'.",
    )
    pasta = Path(__file__).resolve().parent
    parser.add_argument(
        "--shapefile",
        type=Path,
        default=pasta.parent / "00_STUFF" / "buffer_final_regiaoserrana_srtm30metrosPoly.shp",
        help="Shapefile do limite da região (padrão: 00_STUFF/buffer_final_regiaoserrana_srtm30metrosPoly.shp).",
    )
    parser.add_argument(
        "--mascara",
        type=Path,
        default=pasta.parent / "00_STUFF" / "MASCARA_REGIAOSERRANAPoly.shp",
        help="Shapefile da máscara/área de estudo.",
    )
    parser.add_argument(
        "--saida-dir",
        type=Path,
        default=None,
        help="Pasta de saída; por padrão cria uma pasta com o nome do caso no diretório atual.",
    )
    parser.add_argument(
        "--resolucao",
        type=float,
        default=0.01,
        help="Resolução da grade em graus (padrão: 0.01).",
    )
    parser.add_argument(
        "--extensao",
        nargs=4,
        type=float,
        metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"),
        default=(-43.5, -41.55, -22.7, -21.45),
        help="Limites da grade em longitude/latitude.",
    )
    parser.add_argument(
        "--metodos",
        nargs="+",
        choices=[
            "IDW", "Thin Plate Spline", "Bivariate Smoothing Spline", "Kriging",
            "Clough-Tocher Cubic", "RBF Multiquadratic",
            "Polynomial Surface Regression", "Linear (Delaunay)",
            "Shepard", "Nearest Neighbor (Thiessen)",
        ],
        default=["Kriging"],
        help="Métodos a executar (padrão: Kriging).",
    )
    parser.add_argument(
        "--variogramas",
        nargs="+",
        choices=["linear", "power", "gaussian", "spherical", "exponential", "hole-effect"],
        default=["spherical"],
        help="Modelos de variograma para Kriging (padrão: spherical).",
    )
    parser.add_argument("--anisotropy-scaling", type=float, default=1.0, help="Fator de anisotropia do Kriging (padrão: 1, sem alongamento).")
    parser.add_argument("--anisotropy-angle", type=float, default=0.0, help="Ângulo de anisotropia do Kriging em graus (padrão: 0).")
    parser.add_argument("--unidade", default=None, help="Unidade da variável para os metadados NetCDF (ex.: mm/mês).")
    return parser.parse_args()


args = parse_args()

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.pyplot as plt2
import os
from pykrige.ok import OrdinaryKriging
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.ticker import FuncFormatter
from scipy.interpolate import SmoothBivariateSpline, Rbf  # Para interpolação TPS e SPT com Tensão
import time
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score, explained_variance_score, 
    max_error, mean_squared_log_error, median_absolute_error, mean_absolute_percentage_error
)
from scipy.interpolate import griddata
import simplekml  # Biblioteca para criar arquivos KML
import xarray as xr
from simplekml import Kml

from matplotlib.patches import FancyArrow, Rectangle
import pyproj

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interpola.config")
OUTPUT_DIR = Path.cwd()


def caminho_saida(nome_arquivo):
    return OUTPUT_DIR / nome_arquivo


def le_atribuicao_config(nome, config_path=CONFIG_PATH):
    with open(config_path, "r", encoding="utf-8") as arquivo:
        tree = ast.parse(arquivo.read(), filename=config_path)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == nome:
                    return node.value

    raise ValueError(f"Variável '{nome}' não encontrada em {config_path}")


def carrega_intervalos_config(nome):
    valor = ast.literal_eval(le_atribuicao_config(nome))
    if not isinstance(valor, list):
        raise ValueError(f"'{nome}' deve ser uma lista de intervalos no interpola.config")
    return valor


def normaliza_cor(cor):
    if isinstance(cor, tuple) and len(cor) == 2 and isinstance(cor[0], tuple):
        cor = cor[0]
    if isinstance(cor, tuple) and len(cor) in (3, 4) and all(isinstance(v, int) for v in cor):
        return tuple(v / 255 for v in cor)
    return cor


def carrega_cmap_config(nome):
    node = le_atribuicao_config(nome)

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ListedColormap"
        and node.args
    ):
        cores = ast.literal_eval(node.args[0])
    else:
        cores = ast.literal_eval(node)

    if not isinstance(cores, list):
        raise ValueError(f"'{nome}' deve ser uma lista de cores ou ListedColormap(...) no interpola.config")

    return ListedColormap([normaliza_cor(cor) for cor in cores])


# Seta do Norte (em coords do eixo)
def add_north_arrow(ax, xy=(0.93, 0.18), length=0.08, text="N", fontsize=12, pad=0.04):
    """
    Desenha uma seta do norte.

    xy      = posição da base da seta (em frações do eixo, 0–1)
    length  = comprimento da seta (em frações do eixo)
    pad     = espaço extra entre a ponta da seta e o texto "N"
    """
    x, y = xy
    # desenha a seta para cima
    ax.add_patch(FancyArrow(x, y, 0, length, width=0.01,
                            transform=ax.transAxes, color="k",
                            head_width=0.03, head_length=0.03, zorder=20))
    # escreve o "N" um pouco acima
    ax.text(x, y + length + pad, text,
            transform=ax.transAxes,
            ha="center", va="bottom",
            fontsize=fontsize, fontweight="bold", zorder=21)

# Barra de escala EXATA (geodésica) para mapas em lat/lon (SIRGAS 2000 / GRS80)
def add_scale_bar_geodesic(ax, x_min, x_max, y_min, y_max,
                           length_km=20, anchor_axes_xy=(0.93, 0.12),
                           pad_frac=0.006, height_frac=0.010, fontsize=10):
    """
    Desenha uma barra de escala de length_km (exata em termos geodésicos) ancorada na posição
    'anchor_axes_xy' em coordenadas do eixo (0-1). A barra é desenhada horizontalmente
    ao longo do paralelo local (latitude fixa).

    - x_min..y_max: limites do mapa (em graus)
    - length_km: comprimento da barra em km
    - anchor_axes_xy: (x,y) no sistema do eixo onde ficará o CENTRO da barra (próximo da direita)
    - height_frac/pad_frac: altura e folga em fração da altura do mapa (em dados)
    """
    geod = pyproj.Geod(ellps="GRS80")  # SIRGAS 2000

    # Converte âncora do sistema do eixo (0-1) para coordenadas de dados (lon/lat)
    ax_x, ax_y = anchor_axes_xy
    lon_c = x_min + (x_max - x_min) * ax_x
    lat_c = y_min + (y_max - y_min) * ax_y

    # Calcula o delta de longitude exato para length_km ao longo do paralelo (azimute 90° = Leste)
    length_m = length_km * 1000.0
    lon_r, lat_r, _ = geod.fwd(lon_c, lat_c, 90.0, length_m / 2)  # metade para a direita
    lon_l, lat_l, _ = geod.fwd(lon_c, lat_c, -90.0, length_m / 2) # metade para a esquerda
    # Observação: lat_r e lat_l ≈ lat_c (pequenas variações numéricas)

    # Altura e posição vertical da barra em coordenadas de dados
    bar_h = (y_max - y_min) * height_frac
    y0 = lat_c - bar_h / 2

    # Metade esquerda branca
    ax.add_patch(Rectangle((lon_l, y0), (lon_c - lon_l), bar_h,
                        facecolor="w", edgecolor="k", zorder=19))
    # Metade direita preta
    ax.add_patch(Rectangle((lon_c, y0), (lon_r - lon_c), bar_h,
                        facecolor="k", edgecolor="k", zorder=19))

    # Texto central
    ax.text(lon_c, y0 + bar_h + (y_max - y_min) * pad_frac,
            f"{int(round(length_km))} km",
            ha="center", va="bottom", fontsize=fontsize, color="k", zorder=20)


def add_projection_label(ax, crs_text="CRS de dados: EPSG:4326 (lat/lon); Ref. cartográfica: EPSG:31983 (UTM 23S)",
                         loc=(0.01, 0.01), fontsize=9):
    ax.text(loc[0], loc[1], crs_text, transform=ax.transAxes,
            ha="left", va="bottom", fontsize=fontsize, color="dimgray", zorder=25)


def formata_coordenada_gms(valor, tipo):
    """Converte graus decimais para graus, minutos e segundos com hemisfério."""
    hemisferios = {
        "latitude": ("N", "S"),
        "longitude": ("L", "O"),
    }
    positivo, negativo = hemisferios[tipo]
    hemisferio = positivo if valor >= 0 else negativo

    total_segundos = int(round(abs(valor) * 3600))
    graus, restante = divmod(total_segundos, 3600)
    minutos, segundos = divmod(restante, 60)
    return f'{graus}°{minutos:02d}\'{segundos:02d}"{hemisferio}'


def aplica_formatacao_coordenadas(ax):
    """Exibe longitude e latitude nos eixos em graus, minutos e segundos."""
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda valor, _: formata_coordenada_gms(valor, "longitude"))
    )
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda valor, _: formata_coordenada_gms(valor, "latitude"))
    )
    ax.tick_params(axis="both", labelsize=9)

def make_legend(ax):
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0],[0], marker='o', color='w', markerfacecolor='black', markersize=7, label='Estações'),
        Line2D([0],[0], color='black', lw=2.2, label='Limite Região Serrana'),
        Line2D([0],[0], color='blue', lw=2.0, label='Limite Espacial para seleção das estações'),
    ]
    ax.legend(handles=handles, loc="upper left", frameon=True, framealpha=0.9)



def salvar_em_kml(nome_arquivo, latitudes, longitudes, valores):
    kml = Kml()

    for lat, lon, val in zip(latitudes, longitudes, valores):
        pnt = kml.newpoint(name=f"{val:.2f}", coords=[(lon, lat)])
        pnt.description = f"Valor interpolado: {val:.2f}"
        pnt.style.labelstyle.color = 'ff0000ff'  # Azul (em formato ABGR)
        pnt.style.labelstyle.scale = 1.2  # Tamanho do ícone

    kml.save(str(caminho_saida(f"{nome_arquivo}.kml")))


# Função para interpolação Spline Cúbica (Bicúbica) com griddata
def interpola_clough_tocher(olat, olon, valores, gridx, gridy):
    points = np.vstack((olon, olat)).T  # Combina latitudes e longitudes em pontos
    grid_x, grid_y = np.meshgrid(gridx, gridy)  # Cria a malha de interpolação
    z_spline = griddata(points, valores, (grid_x, grid_y), method='cubic')  # Interpolação cúbica
    return z_spline



# def interpola_clough_tocher(olat, olon, valores, gridx, gridy):
#     cs = CubicSpline(np.vstack((olon, olat)).T, valores)
#     grid_x, grid_y = np.meshgrid(gridx, gridy)
#     z_spline = cs(grid_x, grid_y)
#     return z_spline


# interpola_spline_bicubica removido na versão limpa (método duplicado).

def interpola_rbf_multiquadrica(olat, olon, valores, gridx, gridy):
    rbf = Rbf(olon, olat, valores, function='multiquadric')
    grid_x, grid_y = np.meshgrid(gridx, gridy)
    z_rbf_multiquadric = rbf(grid_x, grid_y)
    return z_rbf_multiquadric

from numpy.polynomial.polynomial import Polynomial

# def interpola_polinomial(olat, olon, valores, gridx, gridy, degree=3):
#     poly = Polynomial.fit(np.vstack((olon, olat)).T, valores, degree)
#     grid_x, grid_y = np.meshgrid(gridx, gridy)
#     z_poly = poly(grid_x, grid_y)
#     return z_poly
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression

# Função para interpolação Polinomial Multivariada
def interpola_polinomial(olat, olon, valores, gridx, gridy, degree=3):
    # Combina latitudes e longitudes em uma matriz de pontos
    points = np.vstack((olon, olat)).T

    # Cria a transformação polinomial para latitude e longitude
    poly_features = PolynomialFeatures(degree=degree)
    X_poly = poly_features.fit_transform(points)

    # Ajusta o modelo de regressão linear polinomial
    poly_reg_model = LinearRegression()
    poly_reg_model.fit(X_poly, valores)

    # Gera a malha para interpolação
    grid_x, grid_y = np.meshgrid(gridx, gridy)
    grid_points = np.vstack((grid_x.ravel(), grid_y.ravel())).T  # Transformando em lista de pontos

    # Aplica a transformação polinomial à malha
    grid_points_poly = poly_features.transform(grid_points)

    # Prediz os valores na malha
    z_poly = poly_reg_model.predict(grid_points_poly)
    z_poly = z_poly.reshape(grid_x.shape)  # Remodela para o formato da malha

    return z_poly



from pykrige.ok import OrdinaryKriging

# ATENÇÃO: esta implementação não é um Co-Kriging verdadeiro.
# Ela produz praticamente o mesmo resultado do Kriging.
# interpola_co_kriging removido na versão limpa (método duplicado).

def interpola_linear_delaunay(olat, olon, valores, gridx, gridy):
    points = np.vstack((olon, olat)).T
    z_bilinear = griddata(points, valores, (gridx[None, :], gridy[:, None]), method='linear')
    return z_bilinear


# Shepard original substituído por griddata(cubic). Recomenda-se
# implementar Shepard verdadeiro usando pesos inversamente proporcionais à distância.
def interpola_shepard(olat, olon, valores, gridx, gridy, power=1):
    """Shepard verdadeiro (IDW com power=1)."""
    z = np.zeros((len(gridy), len(gridx)))
    for i in range(len(gridx)):
        for j in range(len(gridy)):
            dist = np.sqrt((olon-gridx[i])**2 + (olat-gridy[j])**2)
            dist[dist == 0] = 1e-10
            w = 1.0 / dist**power
            z[j, i] = np.sum(w * valores) / np.sum(w)
    return z





# Função para interpolação de Thiessen (Voronoi)
def interpola_thiessen(olat, olon, valores, gridx, gridy):
    """Vizinho mais próximo, equivalente a polígonos de Thiessen/Voronoi."""
    points = np.column_stack((olon, olat))
    grid_x, grid_y = np.meshgrid(gridx, gridy)
    return griddata(points, valores, (grid_x, grid_y), method="nearest")



# Função para interpolação Nearest Neighbor (NRN)
# interpola_nrn removido na versão limpa (método duplicado).

# Função para interpolação Triangulação com Interpolação Linear (TLI)
# ATENÇÃO: este método é equivalente ao método Linear.
# interpola_tli removido na versão limpa (método duplicado).

# Função para interpolação Natural Neighbor (NN)
# interpola_nn removido na versão limpa (método duplicado).

# Amostra a superfície na posição real das estações, sem índices fora da grade.
def extrair_valores_no_grid(latitudes, longitudes, z, gridx, gridy):
    from scipy.interpolate import RegularGridInterpolator

    interpolador = RegularGridInterpolator(
        (gridy, gridx),
        np.asarray(z),
        method="linear",
        bounds_error=False,
        fill_value=np.nan,
    )
    pontos = np.column_stack((np.asarray(latitudes), np.asarray(longitudes)))
    return interpolador(pontos)

# Função para calcular as métricas de desempenho (com tratamento de NaN, valores negativos e cálculo das porcentagens)

def calcula_metricas(valores_reais, valores_interpolados):
    valores_reais = np.asarray(valores_reais, dtype=float)
    valores_interpolados = np.asarray(valores_interpolados, dtype=float)
    total_pontos = len(valores_interpolados)

    total_nan = (~np.isfinite(valores_interpolados)).sum()
    porcentagem_nan = (total_nan / total_pontos) * 100 if total_pontos > 0 else np.nan

    total_negativos = (np.isfinite(valores_interpolados) & (valores_interpolados < 0)).sum()
    porcentagem_negativos = (total_negativos / total_pontos) * 100 if total_pontos > 0 else np.nan

    # Erros gerais incluem previsões negativas; excluí-las mascarava falhas dos métodos.
    mask = np.isfinite(valores_reais) & np.isfinite(valores_interpolados)

    valores_reais_filtrados = np.asarray(valores_reais)[mask]
    valores_interpolados_filtrados = np.asarray(valores_interpolados)[mask]

    if len(valores_reais_filtrados) == 0:
        return (
            np.nan, np.nan, np.nan, np.nan,
            np.nan, np.nan, np.nan, np.nan,
            np.nan, porcentagem_nan, porcentagem_negativos
        )

    mae = mean_absolute_error(valores_reais_filtrados,
                              valores_interpolados_filtrados)

    mse = mean_squared_error(valores_reais_filtrados,
                             valores_interpolados_filtrados)

    rmse = np.sqrt(mse)

    r2 = r2_score(valores_reais_filtrados,
                  valores_interpolados_filtrados)

    explained_var = explained_variance_score(
        valores_reais_filtrados,
        valores_interpolados_filtrados
    )

    max_err = max_error(valores_reais_filtrados,
                        valores_interpolados_filtrados)

    msle_mask = (valores_reais_filtrados >= 0) & (valores_interpolados_filtrados >= 0)
    try:
        msle = mean_squared_log_error(
            valores_reais_filtrados[msle_mask],
            valores_interpolados_filtrados[msle_mask]
        ) if msle_mask.any() else np.nan
    except ValueError:
        msle = np.nan

    try:
        medae = median_absolute_error(
            valores_reais_filtrados,
            valores_interpolados_filtrados
        )
    except Exception:
        medae = np.nan

    try:
        mape = mean_absolute_percentage_error(
            valores_reais_filtrados,
            valores_interpolados_filtrados
        )
        if not np.isfinite(mape):
            mape = np.nan
    except Exception:
        mape = np.nan

    return (
        mae, mse, rmse, r2, explained_var,
        max_err, msle, medae, mape,
        porcentagem_nan, porcentagem_negativos
    )

# Função para interpolação Kriging
def interpola_kriging(olat, olon, valores, gridx, gridy, variogram_model, anisotropy_scaling, anisotropy_angle, variogram_parameters):
    parametros_pykrige = {k: v for k, v in variogram_parameters.items() if k != "opt"}
    if not parametros_pykrige:
        parametros_pykrige = None  # Ajuste automático do variograma.
    OK = OrdinaryKriging(
        olon,
        olat,
        valores,
        variogram_model=variogram_model,
        anisotropy_scaling=anisotropy_scaling,
        anisotropy_angle=anisotropy_angle,
        variogram_parameters=parametros_pykrige,
        verbose=False,
        enable_plotting=False,
    )
    z, _ = OK.execute("grid", gridx, gridy)
    return np.asarray(np.ma.filled(z, np.nan), dtype=float)

# Função para interpolação IDW
def interpola_idw(olat, olon, valores, gridx, gridy, power=2):
    z_idw = np.zeros((len(gridy), len(gridx)))
    for i in range(len(gridx)):
        for j in range(len(gridy)):
            dist = np.sqrt((olon - gridx[i])**2 + (olat - gridy[j])**2)
            dist[dist == 0] = 1e-10
            weights = 1 / dist**power
            z_idw[j, i] = np.sum(weights * valores) / np.sum(weights)
    return z_idw

# Função para interpolação SPT (Thin Plate Splines)
def interpola_thin_plate_rbf(olat, olon, valores, gridx, gridy):
    tps = Rbf(olon, olat, valores, function='thin_plate')
    grid_x, grid_y = np.meshgrid(gridx, gridy)
    z_spt = tps(grid_x, grid_y)
    return z_spt

# Função para interpolação SPT com Tensão

def interpola_spline_suavizada(
        olat,
        olon,
        valores,
        gridx,
        gridy,
        s=None):

    if s is None:
        s = len(valores) * np.var(valores)
    print(s,"------------------------------------")

    spline = SmoothBivariateSpline(
        olon,
        olat,
        valores,
        kx=3,
        ky=3,
        s=s
    )

    grid_x, grid_y = np.meshgrid(gridx, gridy)

    z = spline.ev(
        grid_x.ravel(),
        grid_y.ravel()
    ).reshape(grid_x.shape)

    # Não truncar a previsão aos extremos observados: isso esconderia
    # extrapolações/overshoot e enviesaria as métricas de comparação.
    return z


# Função para salvar as interpolações em formato NetCDF
def salvar_netcdf(caso, metodo, gridx, gridy, z):
    # Criar um Dataset do xarray
    ds = xr.Dataset(
        {
            "interpolacao": (["latitude", "longitude"], z)  # A matriz de valores interpolados
        },
        coords={
            "latitude": gridy,  # Array das latitudes
            "longitude": gridx  # Array das longitudes
        }
    )

    # Definir atributos (opcional)
    unidade = globals().get("unidade_interpolada")
    if unidade:
        ds["interpolacao"].attrs["units"] = unidade
    ds["interpolacao"].attrs["source_variable"] = globals().get("variavel_interpolada", "")
    ds.attrs["description"] = f"Interpolação {metodo} - {caso}"
    ds.attrs["created_by"] = "SeuNome"
    ds.attrs["interpolation_method"] = metodo

    # Salvar o Dataset como NetCDF
    netcdf_filename = caminho_saida(f"{caso}_interpolacao_{metodo}.nc")
    ds.to_netcdf(netcdf_filename)
    print(f"Arquivo NetCDF salvo: {netcdf_filename}")

def formata_titulos(caso, metodo, titulo=None, subtitulo=None):
    if titulo is None:
        titulo = globals().get("titulo_imagens")
    if subtitulo is None:
        subtitulo = globals().get("subtitulo_imagens")
    if titulo:
        return titulo, subtitulo
    return f"{caso} - Interpolação Método:{metodo}", subtitulo


def aplica_titulos_pyplot(pyplot_module, caso, metodo, titulo=None, subtitulo=None, fontsize_titulo=25, fontsize_subtitulo=16):
    titulo_principal, texto_subtitulo = formata_titulos(caso, metodo, titulo, subtitulo)
    pyplot_module.suptitle(titulo_principal, fontsize=fontsize_titulo, y=0.98)
    if texto_subtitulo:
        pyplot_module.title(texto_subtitulo, fontsize=fontsize_subtitulo, pad=12)
    else:
        pyplot_module.title("")


def plota_mapa(caso, gridx, gridy, z, variavel, intervalos, metodo, cmap, titulo=None):
    plt.figure(figsize=(15, 10))
    grid_x, grid_y = np.meshgrid(gridx, gridy)

    norm = BoundaryNorm(intervalos, cmap.N)
    cf = plt.contourf(grid_x, grid_y, z, levels=intervalos, cmap=cmap, norm=norm)
    cbar = plt.colorbar(cf, label=variavel, ticks=intervalos, boundaries=intervalos)
    cbar.ax.set_yticklabels([str(interval) for interval in intervalos])

    plt.scatter(olon, olat, color='black', s=50)
    for i in range(len(olon)):
        plt.text(olon[i], olat[i], f"{valores[i]:.1f}", fontsize=5, ha='right', va='bottom', color='black')
    # Limite Região Serrana (gdf) – linha mais grossa
    gdf.boundary.plot(ax=plt.gca(), color='black', linewidth=2.2)
    # Limite Espacial para seleção das estações (gdf2)
    gdf2.plot(ax=plt.gca(), facecolor='none', edgecolor='blue', linewidth=2.0)

    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    aplica_titulos_pyplot(plt, caso, metodo, titulo)
    plt.grid(True)

    # >>> Garanta que o recorte bate na grade desejada:
    # limites fixos (você já adicionou)
    plt.xlim(x_min, x_max)
    plt.ylim(y_min, y_max)
    plt.gca().set_aspect('equal', adjustable='box')
    aplica_formatacao_coordenadas(plt.gca())

    # Itens de mapa (à direita, pertinho da seta Norte)
    add_north_arrow(plt.gca(), xy=(0.93, 0.18), length=0.08, pad=0.06)
    add_scale_bar_geodesic(plt.gca(), x_min, x_max, y_min, y_max,
                           length_km=20, anchor_axes_xy=(0.93, 0.12))
    make_legend(plt.gca())
    add_projection_label(plt.gca(),
        crs_text="CRS de dados: EPSG:4326 (lat/lon); Ref. cartográfica: EPSG:31983 (UTM 23S)")
    plt.savefig(caminho_saida(f"{caso}_interpolacao_{metodo}.png"), dpi=300, bbox_inches="tight")
    plt.close()
    salvar_netcdf(caso, metodo, gridx, gridy, z)




# Função para plotar os mapas e criar arquivos KML e NetCDF
def plota_mapa_kml(caso, gridx, gridy, z, variavel, intervalos, metodo, cmap, titulo=None):
    plt2.figure(figsize=(15, 10))

    grid_x, grid_y = np.meshgrid(gridx, gridy)

    # Criando a normalização com BoundaryNorm
    norm = BoundaryNorm(intervalos, cmap.N)

    # Plotando com contourf para preencher as áreas usando o cmap e norm definidos
    #cf = plt.contourf(grid_x, grid_y, z, levels=intervalos, cmap=cmap, norm=norm)

    # Adicionando as isolinhas (linhas de contorno) nos intervalos usando o mesmo cmap
    contornos = plt2.contour(grid_x, grid_y, z, levels=intervalos, cmap=cmap, norm=norm, linewidths=2)

    # Adicionando rótulos às isolinhas
    #cf=plt.clabel(contornos, inline=True, fontsize=10, fmt='%1.0f')

    # Adicionando a barra de cores com os mesmos cmap e norm
   # cbar = plt.colorbar(cf, label=variavel, ticks=intervalos, boundaries=intervalos)

    # Ajustando os rótulos da barra de cores se necessário
   # cbar.ax.set_yticklabels([str(interval) for interval in intervalos])

    # Continuando com o resto da sua plotagem
    plt2.scatter(olon, olat, color='white', s=50)
    for i in range(len(olon)):
         plt2.text(olon[i], olat[i], f"{valores[i]:.1f}", fontsize=7, ha='right', va='bottom', color='white')
    gdf.boundary.plot(ax=plt2.gca(), color='white', linewidth=1)
    #gdf2.plot(ax=plt.gca(), edgecolor='black', linewidth=1)
    plt2.xlabel('Longitude')
    plt2.ylabel('Latitude')
    aplica_titulos_pyplot(plt2, caso, metodo, titulo)
    plt2.grid(True)
    plt2.xlim(x_min, x_max)
    plt2.ylim(y_min, y_max)
    plt2.gca().set_aspect('equal', adjustable='box')
    aplica_formatacao_coordenadas(plt2.gca())

    # Salvar a figura com fundo transparente
    image_filename = caminho_saida(f"{caso}_interpolacao_{metodo}_contornos.png")
    plt2.savefig(image_filename, dpi=300, bbox_inches="tight", transparent=True)
    plt2.close()

    # Criar um arquivo KML com GroundOverlay
    kml = simplekml.Kml()
    titulo_overlay, subtitulo_overlay = formata_titulos(caso, metodo, titulo)
    if subtitulo_overlay:
        titulo_overlay = f"{titulo_overlay} - {subtitulo_overlay}"
    ground = kml.newgroundoverlay(name=titulo_overlay)
    ground.icon.href = image_filename.name
    ground.latlonbox.north = y_max
    ground.latlonbox.south = y_min
    ground.latlonbox.east = x_max
    ground.latlonbox.west = x_min
    ground.latlonbox.rotation = 0
    kml_filename = caminho_saida(f"{caso}_interpolacao_{metodo}.kml")
    kml.save(str(kml_filename))



    
    

# Função para plotar o mapa de pontos (se necessário)
def plota_mapa_pontos(caso,valores):
    plt.figure(figsize=(15, 10))
    plt.scatter(olon, olat, color='black', s=50)
    for i in range(len(olon)):
        plt.text(olon[i], olat[i], f"{valores[i]:.1f}", fontsize=5, ha='right', va='bottom', color='black')
    gdf.boundary.plot(ax=plt.gca(), color='black', linewidth=1)
    gdf2.plot(ax=plt.gca(), facecolor='none', edgecolor='black', linewidth=1)
    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.grid(True)
    aplica_formatacao_coordenadas(plt.gca())
    plt.savefig(caminho_saida(f"{caso}_mapa_de_pontos.png"), dpi=300, bbox_inches="tight")
    plt.close()

def metricas(opcao_interp, caso, olat, olon, valores, gridx, gridy, variavel, intervalos, cmap, arqout, anisotropy_scaling, anisotropy_angle, variogram_parameters_list):
    resultados = []
    falhas = []
    metodos_ativos = set(opcao_interp)
    if not metodos_ativos:
        raise ValueError("Nenhum método de interpolação foi selecionado.")

    def registra_resultado(nome, z):
        plota_mapa(caso, gridx, gridy, z, variavel, intervalos, nome, cmap)
        valores_interpolados = extrair_valores_no_grid(olat, olon, z, gridx, gridy)
        mae, mse, rmse, r2, explained_var, max_err, msle, medae, mape, pnan, pneg = calcula_metricas(valores, valores_interpolados)
        resultados.append([nome, mae, mse, rmse, r2, explained_var, max_err, msle, medae, mape, pnan, pneg])

    def executa(nome, funcao, *parametros):
        try:
            print(f"---------------------------- {nome}")
            z = funcao(*parametros)
            registra_resultado(nome, z)
            return z
        except Exception as erro:
            falhas.append([nome, str(erro)])
            print(f"[ERRO] Método {nome} falhou: {erro}")
            return None

    if "IDW" in metodos_ativos:
        z_idw = executa("IDW", interpola_idw, olat, olon, valores, gridx, gridy, 2)
        if z_idw is not None:
            try:
                salvar_em_kml(f"{caso}_pontos_IDW", olat, olon, valores)
            except Exception as erro:
                falhas.append(["KML IDW", str(erro)])

    if "Thin Plate Spline" in metodos_ativos:
        executa("Thin Plate Spline", interpola_thin_plate_rbf, olat, olon, valores, gridx, gridy)

    if "Bivariate Smoothing Spline" in metodos_ativos:
        executa("Bivariate Smoothing Spline", interpola_spline_suavizada, olat, olon, valores, gridx, gridy, None)

    if "Kriging" in metodos_ativos:
        print("---------------------------- Kriging para todos os modelos de variograma")
        for k, model in enumerate(variograma):
            if variogram_parameters_list[k].get('opt', False):
                parametros = dict(variogram_parameters_list[k])
                if model == "hole-effect":
                    print("[AVISO] PyKrige considera hole-effect tecnicamente válido apenas em 1D; interprete este resultado com cautela.")
                executa(
                    f"Kriging_{model}", interpola_kriging,
                    olat, olon, valores, gridx, gridy, model,
                    anisotropy_scaling, anisotropy_angle, parametros,
                )

    if "Clough-Tocher Cubic" in metodos_ativos:
        executa("Clough-Tocher Cubic", interpola_clough_tocher, olat, olon, valores, gridx, gridy)

    if "RBF Multiquadratic" in metodos_ativos:
        executa("RBF Multiquadratic", interpola_rbf_multiquadrica, olat, olon, valores, gridx, gridy)

    if "Polynomial Surface Regression" in metodos_ativos:
        executa("Polynomial Surface Regression", interpola_polinomial, olat, olon, valores, gridx, gridy, 3)

    if "Linear (Delaunay)" in metodos_ativos:
        executa("Linear (Delaunay)", interpola_linear_delaunay, olat, olon, valores, gridx, gridy)

    if "Shepard" in metodos_ativos:
        executa("Shepard", interpola_shepard, olat, olon, valores, gridx, gridy, 1)

    if "Nearest Neighbor (Thiessen)" in metodos_ativos:
        executa("Nearest Neighbor (Thiessen)", interpola_thiessen, olat, olon, valores, gridx, gridy)

    df_metricas = pd.DataFrame(resultados, columns=['Metodo', 'MAE', 'MSE', 'RMSE', 'R2', 'Explained Variance', 'Max Error', 'MSLE', 'MedAE', 'MAPE', 'PNAN', 'PNEG'])
    df_metricas.replace([np.inf, -np.inf], np.nan, inplace=True)
    df_falhas = pd.DataFrame(falhas, columns=["Metodo", "Erro"])

    try:
        with pd.ExcelWriter(caminho_saida(arqout), engine='openpyxl', mode='w') as writer:
            df_metricas.to_excel(writer, sheet_name='Metricas', index=False)
            df_falhas.to_excel(writer, sheet_name='Falhas', index=False)
            pd.DataFrame({
                "Observacao": [
                    "As métricas amostram a superfície ajustada nos mesmos pontos usados na interpolação; não representam validação cruzada independente."
                ]
            }).to_excel(writer, sheet_name="Notas", index=False)
        print(f'Arquivo salvo: {caminho_saida(arqout)}')
    except Exception as e:
        print(f'Erro ao salvar Excel: {e}')


def main():
    global OUTPUT_DIR, gdf, gdf2, gridx, gridy, x_min, x_max, y_min, y_max
    global olat, olon, valores, titulo_imagens, subtitulo_imagens, unidade_interpolada, variavel_interpolada

    start_time = time.time()
    caso = args.caso
    file_path = args.file_path.resolve()
    sheet_name = args.sheet_name
    variavel = args.variavel
    titulo_imagens = args.titulo
    subtitulo_imagens = args.subtitulo

    OUTPUT_DIR = (args.saida_dir or (Path.cwd() / caso)).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not file_path.is_file():
        raise FileNotFoundError(f"Planilha de entrada não encontrada: {file_path}")
    shapefile_path = args.shapefile.resolve()
    mascara_path = args.mascara.resolve()
    if not shapefile_path.is_file():
        raise FileNotFoundError(f"Shapefile de referência não encontrado: {shapefile_path}")
    if not mascara_path.is_file():
        raise FileNotFoundError(f"Shapefile da máscara não encontrado: {mascara_path}")
    if args.resolucao <= 0:
        raise ValueError("--resolucao precisa ser maior que zero.")

    x_min, x_max, y_min, y_max = args.extensao
    if x_min >= x_max or y_min >= y_max:
        raise ValueError("A extensão deve obedecer X_MIN < X_MAX e Y_MIN < Y_MAX.")
    nx = int(round((x_max - x_min) / args.resolucao)) + 1
    ny = int(round((y_max - y_min) / args.resolucao)) + 1
    gridx = np.linspace(x_min, x_max, nx)
    gridy = np.linspace(y_min, y_max, ny)

    gdf = gpd.read_file(shapefile_path)
    gdf2 = gpd.read_file(mascara_path)
    if gdf.crs is not None:
        gdf = gdf.to_crs("EPSG:4326")
    if gdf2.crs is not None:
        gdf2 = gdf2.to_crs("EPSG:4326")

    df = pd.read_excel(file_path, sheet_name=sheet_name)
    colunas_obrigatorias = {"Latitude", "Longitude", variavel}
    ausentes = colunas_obrigatorias.difference(df.columns)
    if ausentes:
        raise ValueError(f"Colunas não encontradas na aba '{sheet_name}': {', '.join(sorted(ausentes))}")

    df = df[["Latitude", "Longitude", variavel]].copy()
    for coluna in ["Latitude", "Longitude", variavel]:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=["Latitude", "Longitude", variavel], inplace=True)
    quantidade_duplicada = int(df.duplicated(["Latitude", "Longitude"]).sum())
    if quantidade_duplicada:
        print(f"[AVISO] {quantidade_duplicada} coordenadas duplicadas foram agregadas pela média.")
        df = df.groupby(["Latitude", "Longitude"], as_index=False)[variavel].mean()
    if len(df) < 3:
        raise ValueError("São necessários ao menos três pontos válidos para interpolar em 2D.")

    olat = df["Latitude"].to_numpy(dtype=float)
    olon = df["Longitude"].to_numpy(dtype=float)
    valores = df[variavel].to_numpy(dtype=float)
    unidade_interpolada = args.unidade
    variavel_interpolada = variavel

    variograma = ["linear", "power", "gaussian", "spherical", "exponential", "hole-effect"]
    # 'opt' é só uma chave local para selecionar modelos; ela é removida antes da chamada ao PyKrige.
    # Sem parâmetros manuais: PyKrige ajusta os parâmetros do variograma aos dados.
    variogram_parameters_list = [{"opt": modelo in args.variogramas} for modelo in variograma]

    anisotropy_scaling = args.anisotropy_scaling
    anisotropy_angle = args.anisotropy_angle
    nome_arquivo = caso
    arqout = f"{caso}_metricas_interpolacao_completas.xlsx"

    intervalos = carrega_intervalos_config(args.intervalos) if args.intervalos else [10, 30, 100, 200, 300, 500]
    if len(intervalos) < 2 or any(b <= a for a, b in zip(intervalos, intervalos[1:])):
        raise ValueError("Os intervalos de cor devem conter pelo menos dois valores em ordem crescente.")
    cmap = carrega_cmap_config(args.cmap) if args.cmap else ListedColormap(["red", "orange", "yellow", "green", "blue"])

    metricas(
        args.metodos, nome_arquivo, olat, olon, valores, gridx, gridy, variavel,
        intervalos, cmap, arqout, anisotropy_scaling, anisotropy_angle,
        variogram_parameters_list,
    )
    print(f"Concluído em {time.time() - start_time:.1f} s. Saídas em: {OUTPUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, OSError) as erro:
        raise SystemExit(f"Erro: {erro}")
