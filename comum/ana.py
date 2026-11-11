"""Cliente do webservice da ANA (HidroWeb / ServiceANA.asmx) - único para 01 e 02.

Melhorias em relação às cópias antigas:
- timeout e novas tentativas automáticas (erros 5xx e quedas de conexão);
- cache por estação em CSV: uma execução interrompida retoma de onde parou;
- datas enviadas no formato dd/mm/aaaa que o serviço espera, e corte local do período;
- consistência '1' (bruto), '2' (consistido) ou 'ambos' (prefere o consistido no mesmo dia);
- XML lido com ElementTree (não precisa de xmltodict).
"""
import calendar
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    Retry = None

URL_ANA = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx/"

UF_ANA_MAP = {
    "AC": "ACRE", "AL": "ALAGOAS", "AP": "AMAPÁ", "AM": "AMAZONAS", "BA": "BAHIA", "CE": "CEARÁ",
    "DF": "DISTRITO FEDERAL", "ES": "ESPÍRITO SANTO", "GO": "GOIÁS", "MA": "MARANHÃO",
    "MT": "MATO GROSSO", "MS": "MATO GROSSO DO SUL", "MG": "MINAS GERAIS", "PA": "PARÁ",
    "PB": "PARAÍBA", "PR": "PARANÁ", "PE": "PERNAMBUCO", "PI": "PIAUÍ", "RJ": "RIO DE JANEIRO",
    "RN": "RIO GRANDE DO NORTE", "RS": "RIO GRANDE DO SUL", "RO": "RONDÔNIA", "RR": "RORAIMA",
    "SC": "SANTA CATARINA", "SP": "SÃO PAULO", "SE": "SERGIPE", "TO": "TOCANTINS",
}

CAMPOS_INVENTARIO = [
    ("Codigo", "Codigo"), ("Nome", "Nome"), ("Tipo", "TipoEstacao"), ("Latitude", "Latitude"),
    ("Longitude", "Longitude"), ("Altitude", "Altitude"), ("UF", "nmEstado"),
    ("Municipio", "nmMunicipio"), ("Bacia", "BaciaCodigo"), ("Sub Bacia", "SubBaciaCodigo"),
    ("Rio", "RioCodigo"), ("Orgão", "ResponsavelSigla"), ("Ultima Atualizacao", "UltimaAtualizacao"),
    ("data_ins", "DataIns"), ("data_alt", "DataAlt"),
]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _float(texto):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return np.nan


def data_ana(data):
    """'2020-01-31' -> '31/01/2020' (formato do ServiceANA). Vazio -> ''."""
    if not data:
        return ""
    return pd.Timestamp(data).strftime("%d/%m/%Y")


class ServiceANA:
    def __init__(self, url=URL_ANA, timeout=(15, 180), tentativas=4, pausa=0.0):
        self.url = url
        self.timeout = timeout
        self.pausa = pausa
        self.sessao = requests.Session()
        if Retry is not None:
            retry = Retry(total=tentativas, connect=tentativas, read=tentativas, backoff_factor=2,
                          status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
            self.sessao.mount("http://", HTTPAdapter(max_retries=retry))
            self.sessao.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, metodo, params):
        r = self.sessao.get(self.url + metodo, params=params, timeout=self.timeout)
        r.raise_for_status()
        if self.pausa:
            time.sleep(self.pausa)
        return r.content

    # ------------------------------------------------------------------ inventário
    def inventario(self, estado="", orgao="", tipo=""):
        params = {"codEstDE": "", "codEstATE": "", "tpEst": tipo, "nmEst": "", "nmRio": "",
                  "codSubBacia": "", "codBacia": "", "nmMunicipio": "", "nmEstado": estado,
                  "sgResp": orgao, "sgOper": "", "telemetrica": ""}
        return parse_inventario(self._get("HidroInventario", params))

    # ------------------------------------------------------------------ série histórica
    def serie_chuva(self, codigo, inicio="", fim="", consistencia="1", cache_dir=None):
        """Série diária de chuva (pd.Series indexada por data, float). Série vazia se não houver dado.

        consistencia: '1' bruto, '2' consistido, 'ambos' (duas consultas; consistido tem prioridade).
        """
        if consistencia == "ambos":
            bruto = self.serie_chuva(codigo, inicio, fim, "1", cache_dir)
            cons = self.serie_chuva(codigo, inicio, fim, "2", cache_dir)
            serie = pd.concat([cons, bruto])
            serie = serie[~serie.index.duplicated(keep="first")].sort_index()
            serie.name = str(codigo)
            return serie

        arq = None
        if cache_dir:
            ini_txt = pd.Timestamp(inicio).strftime("%Y%m%d") if inicio else "ini"
            fim_txt = pd.Timestamp(fim).strftime("%Y%m%d") if fim else "fim"
            arq = Path(cache_dir) / f"{codigo}_c{consistencia}_{ini_txt}_{fim_txt}.csv"
            if arq.is_file():
                df = pd.read_csv(arq, parse_dates=["data"])
                serie = pd.Series(df["valor"].to_numpy(float), index=pd.DatetimeIndex(df["data"]),
                                  name=str(codigo))
                return serie

        params = {"codEstacao": codigo, "dataInicio": data_ana(inicio), "dataFim": data_ana(fim),
                  "tipoDados": "2", "nivelConsistencia": consistencia}
        serie = parse_serie_chuva(self._get("HidroSerieHistorica", params), str(codigo))
        if inicio:
            serie = serie[serie.index >= pd.Timestamp(inicio)]
        if fim:
            serie = serie[serie.index <= pd.Timestamp(fim)]

        if arq is not None:
            arq.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"data": serie.index, "valor": serie.to_numpy()}).to_csv(arq, index=False)
        return serie


def parse_inventario(conteudo):
    raiz = ET.fromstring(conteudo)
    linhas = []
    for tabela in raiz.iter():
        if _local(tabela.tag) != "Table":
            continue
        filhos = {_local(f.tag): (f.text or "").strip() for f in tabela}
        linha = {nome: filhos.get(tag) or None for nome, tag in CAMPOS_INVENTARIO}
        for c in ("Latitude", "Longitude", "Altitude"):
            linha[c] = _float(linha[c])
        linhas.append(linha)
    if not linhas:
        return pd.DataFrame(columns=[n for n, _ in CAMPOS_INVENTARIO]).set_index("Codigo")
    return pd.DataFrame(linhas).set_index("Codigo")


def parse_serie_chuva(conteudo, codigo):
    """Converte o XML do HidroSerieHistorica (uma linha por mês, Chuva01..Chuva31) em série diária."""
    raiz = ET.fromstring(conteudo)
    datas, valores, niveis = [], [], []
    for reg in raiz.iter():
        if _local(reg.tag) != "SerieHistorica":
            continue
        campos = {_local(f.tag): (f.text or "").strip() for f in reg}
        base = pd.to_datetime(campos.get("DataHora"), errors="coerce")
        if pd.isna(base):
            continue
        nivel = _float(campos.get("NivelConsistencia"))
        nivel = 0 if np.isnan(nivel) else int(nivel)
        ndias = calendar.monthrange(base.year, base.month)[1]
        for dia in range(1, ndias + 1):
            v = _float(campos.get(f"Chuva{dia:02d}"))
            if np.isnan(v):
                continue
            datas.append(pd.Timestamp(base.year, base.month, dia))
            valores.append(v)
            niveis.append(nivel)
    if not datas:
        return pd.Series(dtype=float, name=codigo, index=pd.DatetimeIndex([], name="date"))
    df = pd.DataFrame({"data": datas, "valor": valores, "nivel": niveis})
    # Mesmo dia repetido (bruto e consistido): fica o de maior nível de consistência.
    df = df.sort_values(["data", "nivel"], ascending=[True, False]).drop_duplicates("data")
    serie = pd.Series(df["valor"].to_numpy(float), index=pd.DatetimeIndex(df["data"], name="date"), name=codigo)
    return serie
