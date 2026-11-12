"""Gravação de planilhas grandes sem estourar a memória.

Por que este módulo existe
--------------------------
A aba BRUTOS tem uma coluna por estação e uma linha por dia. Com 1485 estações e
30 anos são ~16 milhões de células; na série histórica completa passa de 60 milhões.

O openpyxl (engine padrão do pandas) monta um objeto Python por célula antes de
escrever qualquer coisa no disco. Medido nesta base: ~380 bytes e ~115 us por célula.
Ou seja, 16 M de células = ~6 GB e ~30 min; 68 M = ~24 GB e ~2 h. O processo é morto
pelo sistema antes de gerar o arquivo, e nada do que viria depois (o CSV) chega a rodar.

A saída natural seria o xlsxwriter em modo 'constant_memory', que escreve linha a
linha e descarta. MAS ele NÃO pode ser usado pelo pandas.to_excel: o pandas emite as
células coluna a coluna, e o constant_memory descarta tudo que volta para uma linha já
fechada. O arquivo sai com o tamanho e as datas certos e TODOS os valores vazios --
perda silenciosa de dados. Testado e confirmado.

Por isso aqui a escrita é feita linha a linha, na mão, direto no xlsxwriter.

Uso
---
    from comum.planilhas import gravar_abas
    gravar_abas("dados_RJ.xlsx", {
        "BRUTOS": (brutos, "date"),   # tupla = o índice vira a 1a coluna com esse nome
        "Historico": hist,            # DataFrame puro = sem índice
    })
"""
import datetime as _dt
from pathlib import Path

import pandas as pd

# Limites do formato .xlsx (não são escolha nossa; são do Excel).
LIMITE_LINHAS = 1_048_576
LIMITE_COLUNAS = 16_384

# Acima disto o openpyxl (usado só como alternativa) é inviável na prática.
LIMITE_CELULAS_OPENPYXL = 2_000_000

# Quantas células manter em memória por vez ao montar os blocos de linhas.
CELULAS_POR_BLOCO = 1_000_000

try:
    import xlsxwriter  # noqa: F401
    TEM_XLSXWRITER = True
except ImportError:  # pragma: no cover
    TEM_XLSXWRITER = False


class PlanilhaGrandeDemais(ValueError):
    """A aba não cabe no formato .xlsx (limite do Excel, não do computador)."""


def _nulo(v):
    """NaN/NaT/None -> None (o xlsxwriter recusa NaN e escreveria lixo)."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, float) and v != v:
        return None
    return v


def _colunas_de_data(df):
    """Colunas que contêm datas (datetime64 ou objetos date/datetime)."""
    achadas = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            achadas.append(c)
            continue
        if s.dtype == object:
            sem_nulo = s.dropna()
            if len(sem_nulo) and isinstance(sem_nulo.iloc[0], (pd.Timestamp, _dt.datetime, _dt.date)):
                achadas.append(c)
    return achadas


def _datas_para_texto(df, colunas):
    """Datas das colunas de metadados viram texto ISO (yyyy-mm-dd).

    Evita ter que despachar formato célula a célula. A coluna de datas da aba BRUTOS
    NÃO passa por aqui: aquela é gravada como data de verdade do Excel.
    """
    if not colunas:
        return df
    df = df.copy()
    for c in colunas:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def _linhas_por_bloco(n_colunas):
    return max(1, min(5000, CELULAS_POR_BLOCO // max(1, n_colunas)))


def conferir_limites(df, nome_aba, com_indice=False):
    """Levanta PlanilhaGrandeDemais se a aba não couber no .xlsx."""
    n_lin, n_col = df.shape
    n_col += 1 if com_indice else 0
    if n_lin + 1 > LIMITE_LINHAS:
        raise PlanilhaGrandeDemais(
            f"Aba '{nome_aba}': {n_lin:,} linhas excedem o limite do Excel "
            f"({LIMITE_LINHAS:,}). Use o CSV para esses dados.")
    if n_col > LIMITE_COLUNAS:
        raise PlanilhaGrandeDemais(
            f"Aba '{nome_aba}': {n_col:,} colunas excedem o limite do Excel "
            f"({LIMITE_COLUNAS:,}). Use o CSV para esses dados.")


def _escrever_aba(ws, df, nome_indice, fmt_cabecalho, fmt_data):
    """Escreve o DataFrame linha a linha, em ordem crescente de linha.

    A ordem importa: em constant_memory o xlsxwriter fecha cada linha ao passar
    para a seguinte, e gravar numa linha anterior perde o valor sem avisar.
    """
    desloc = 1 if nome_indice else 0
    cabecalho = ([nome_indice] if nome_indice else []) + [str(c) for c in df.columns]
    ws.write_row(0, 0, cabecalho, fmt_cabecalho)
    if df.empty:
        return
    ws.freeze_panes(1, desloc)

    df = _datas_para_texto(df, _colunas_de_data(df))
    indice_de_datas = isinstance(df.index, pd.DatetimeIndex)
    n_lin = len(df)
    passo = _linhas_por_bloco(len(df.columns) + desloc)

    for inicio in range(0, n_lin, passo):
        bloco = df.iloc[inicio:inicio + passo]

        # Por coluna: tolist() devolve tipos nativos do Python (o xlsxwriter recusa
        # numpy.int64), e a máscara de nulos é calculada de forma vetorizada.
        colunas = []
        for _, s in bloco.items():
            valores = s.tolist()
            if s.isna().any():
                nulos = s.isna().tolist()
                valores = [None if n else v for v, n in zip(valores, nulos)]
            colunas.append(valores)

        indice = bloco.index.tolist() if nome_indice else None
        for j, linha in enumerate(zip(*colunas)) if colunas else enumerate([()] * len(bloco)):
            r = inicio + j + 1
            if nome_indice:
                v = indice[j]
                if indice_de_datas and v is not pd.NaT:
                    ws.write_datetime(r, 0, pd.Timestamp(v).to_pydatetime(), fmt_data)
                else:
                    ws.write(r, 0, _nulo(v))
            if linha:
                ws.write_row(r, desloc, linha)


def _normalizar(abas):
    """{nome: df} ou {nome: (df, nome_indice)} -> [(nome, df, nome_indice)]"""
    saida = []
    for nome, item in abas.items():
        if isinstance(item, tuple):
            df, nome_indice = item
        else:
            df, nome_indice = item, None
        if df is None:
            df = pd.DataFrame()
        saida.append((str(nome)[:31], df, nome_indice))
    return saida


def gravar_abas(caminho, abas):
    """Grava várias abas num .xlsx com memória constante.

    abas: dict {nome_aba: DataFrame} ou {nome_aba: (DataFrame, nome_da_coluna_de_indice)}.
    Devolve o caminho gravado.
    """
    caminho = str(caminho)
    itens = _normalizar(abas)
    for nome, df, nome_indice in itens:
        conferir_limites(df, nome, com_indice=bool(nome_indice))

    if not TEM_XLSXWRITER:
        return _gravar_com_openpyxl(caminho, itens)

    wb = xlsxwriter.Workbook(caminho, {"constant_memory": True,
                                       "default_date_format": "yyyy-mm-dd"})
    try:
        fmt_cabecalho = wb.add_format({"bold": True})
        fmt_data = wb.add_format({"num_format": "yyyy-mm-dd"})
        for nome, df, nome_indice in itens:
            _escrever_aba(wb.add_worksheet(nome), df, nome_indice, fmt_cabecalho, fmt_data)
    finally:
        wb.close()
    return caminho


def _gravar_com_openpyxl(caminho, itens):
    """Alternativa quando o xlsxwriter não está instalado. Recusa abas grandes."""
    total = sum((len(df) + 1) * (len(df.columns) + (1 if ind else 0)) for _, df, ind in itens)
    if total > LIMITE_CELULAS_OPENPYXL:
        raise MemoryError(
            f"Seriam {total:,} células com o openpyxl (~{total * 380 / 1e9:.1f} GB de RAM).\n"
            "Instale o xlsxwriter para gravar com memória constante:\n"
            "    pip install xlsxwriter")
    with pd.ExcelWriter(caminho, engine="openpyxl") as w:
        for nome, df, nome_indice in itens:
            if nome_indice:
                df = df.reset_index().rename(columns={df.index.name or "index": nome_indice})
            df.to_excel(w, sheet_name=nome, index=False)
    return caminho


def gravar_brutos_csv(df, caminho, nome_indice="date"):
    """Grava os brutos em CSV (rápido, memória baixa, sem limite de linhas/colunas)."""
    df.to_csv(caminho, index_label=nome_indice, encoding="utf-8-sig")
    return str(caminho)


def ler_brutos(caminho, aba="BRUTOS", silencioso=False):
    """Lê a tabela de brutos (1a coluna = data).

    Se existir um CSV irmão (mesmo nome, .csv) pelo menos tão recente quanto o .xlsx,
    lê o CSV: ler 16 milhões de células com o openpyxl leva dezenas de minutos e
    gigabytes, enquanto o mesmo conteúdo em CSV sai em segundos. Se o CSV for mais
    antigo que o .xlsx ele é ignorado, para nunca usar dados desatualizados.
    """
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".csv":
        return pd.read_csv(caminho)
    irmao = caminho.with_suffix(".csv")
    if irmao.is_file() and irmao.stat().st_mtime >= caminho.stat().st_mtime:
        if not silencioso:
            print(f"[info] lendo os brutos de {irmao.name} (bem mais rápido que a aba {aba})")
        return pd.read_csv(irmao)
    return pd.read_excel(caminho, sheet_name=aba, engine="openpyxl")
