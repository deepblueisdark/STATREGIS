"""Sumário estatístico das estações - implementação ÚNICA usada pelo download (02) e pelo processador (02).

Antes, statregis_download_processa.py e statregis_processa_dados.py tinham cada um a sua cópia,
com nomes de coluna diferentes ('Desvio Padrao' x 'Desvio', 'Média mm/mes' x 'Média mm/mês') e
denominadores de IDV mensal diferentes. Agora os dois chamam calcular_sumario().

Definições:
- dado válido: valor >= 0 (negativos e vazios = falha);
- período: [inicio, fim] se informados; senão do primeiro ao último registro da estação;
- IDV  = dias válidos / dias do período * 100;   IDV LDU: dias >= limite;  IDV Nonzero: dias >= 0,1 mm;
- ano (ou mês-ano) completo: civil, inteiro dentro do período, com >= 80% dos dias válidos;
- Média mm/ano = média diária * 365 (mantida por compatibilidade);
- Média mm/ano (climatológica) = soma das 12 médias diárias mensais * dias médios do mês.
  É menos enviesada quando as falhas se concentram numa estação do ano.
"""
import math

import numpy as np
import pandas as pd

from .codigos import normalizar_codigo
from .planilhas import gravar_abas

NOMES_MESES = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
               7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"}
DIAS_MEDIOS_MES = {1: 31, 2: 28.2425, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
LIMIAR_NONZERO = 0.1
COBERTURA_ANO_COMPLETO = 80.0

CHAVES_ESTAT = ["Total", "Média mm/dia", "Média mm/mês", "Média mm/ano", "Mediana", "Moda", "Máximo",
                "Mínimo", "Desvio", "Variância", "P25", "P50", "P75", "P90", "P95", "P99"]

META = [("Nome", "Nome"), ("Latitude", "Latitude"), ("Longitude", "Longitude"), ("Altitude", "Altitude"),
        ("Cidade", "Municipio"), ("UF", "UF"), ("Bacia", "Bacia"), ("Sub Bacia", "Sub Bacia"),
        ("Rio", "Rio"), ("Orgão", "Orgão"), ("Data Ultimo dado", "Ultima Atualizacao")]


def estatisticas(d, sufixo=""):
    s = f" {sufixo}" if sufixo else ""
    if d is None or len(d) == 0:
        return {f"{k}{s}": np.nan for k in CHAVES_ESTAT}
    v = d.to_numpy(float)
    media = v.mean()
    moda = d.mode()
    q = np.quantile(v, [0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    return {
        f"Total{s}": v.sum(), f"Média mm/dia{s}": media, f"Média mm/mês{s}": media * 30,
        f"Média mm/ano{s}": media * 365, f"Mediana{s}": float(np.median(v)),
        f"Moda{s}": float(moda.iloc[0]) if not moda.empty else np.nan,
        f"Máximo{s}": v.max(), f"Mínimo{s}": v.min(),
        f"Desvio{s}": float(d.std()) if len(v) > 1 else np.nan,
        f"Variância{s}": float(d.var()) if len(v) > 1 else np.nan,
        f"P25{s}": q[0], f"P50{s}": q[1], f"P75{s}": q[2], f"P90{s}": q[3], f"P95{s}": q[4], f"P99{s}": q[5],
    }


def _tres_estatisticas(validos, limite):
    out = estatisticas(validos)
    out.update(estatisticas(validos[validos >= LIMIAR_NONZERO], "NZ"))
    out.update(estatisticas(validos[validos >= limite], "LDU"))
    return out


def _dias_periodo(inicio, fim):
    """Índice diário do período (para contar dias por mês/ano)."""
    return pd.date_range(inicio.normalize(), fim.normalize(), freq="D")


def contar_completos(validos, inicio, fim, mes=None, cobertura=COBERTURA_ANO_COMPLETO):
    """Anos (mes=None) ou meses-ano (mes=1..12) civis inteiros dentro do período com >= cobertura % válidos."""
    if inicio is None or fim is None or len(validos) == 0:
        return 0
    inicio, fim = pd.Timestamp(inicio).normalize(), pd.Timestamp(fim).normalize()
    v = validos[(validos.index >= inicio) & (validos.index <= fim)]
    if mes is None:
        cont = v.groupby(v.index.year).size()
        total = 0
        for ano, n in cont.items():
            if pd.Timestamp(ano, 1, 1) >= inicio and pd.Timestamp(ano, 12, 31) <= fim:
                dias = 366 if calendar_isleap(ano) else 365
                total += n / dias * 100 >= cobertura
        return int(total)
    v = v[v.index.month == mes]
    cont = v.groupby(v.index.year).size()
    total = 0
    for ano, n in cont.items():
        ndias = pd.Timestamp(ano, mes, 1).days_in_month
        if pd.Timestamp(ano, mes, 1) >= inicio and pd.Timestamp(ano, mes, ndias) <= fim:
            total += n / ndias * 100 >= cobertura
    return int(total)


def calendar_isleap(ano):
    return ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)


def _meta_de(meta, codigo):
    vazio = {destino: np.nan for destino, _ in META}
    if meta is None or meta.empty:
        return vazio
    linha = meta.loc[meta["_cod"] == codigo]
    if linha.empty:
        return vazio
    linha = linha.iloc[0]
    return {destino: linha.get(origem, np.nan) for destino, origem in META}


def preparar_brutos(df):
    """Recebe a aba BRUTOS (1ª coluna = data) ou um DataFrame já indexado por data; devolve float, índice DatetimeIndex único."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0], errors="coerce")
        df = df.rename(columns={df.columns[0]: "Data"}).dropna(subset=["Data"]).set_index("Data")
    df.index = pd.DatetimeIndex(df.index).normalize()
    df.index.name = "Data"
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.columns = [normalizar_codigo(c) for c in df.columns]
    # Converte SÓ o que não é numérico. O .apply(pd.to_numeric) antigo refazia as ~1486
    # colunas mesmo quando já eram float, duplicando o quadro inteiro na memória.
    nao_numericas = [c for c, t in zip(df.columns, df.dtypes) if not pd.api.types.is_numeric_dtype(t)]
    for coluna in nao_numericas:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    return df


def calcular_sumario(brutos, meta=None, inicio="", fim="", limite=1.0, idv_minimo=None):
    """Calcula ANUAL, ANUAIS, MENSAL, Excluidas_IDV e MEDIA_DIARIA.

    brutos: DataFrame (índice = data diária, colunas = códigos).
    meta:   DataFrame com coluna 'Codigo' e metadados (aba Historico ou inventário).
    Retorna dict de DataFrames e 'BRUTOS' (sem as estações excluídas, cortado ao período).
    """
    brutos = preparar_brutos(brutos)
    p_ini = pd.Timestamp(inicio) if inicio and fim else None
    p_fim = pd.Timestamp(fim) if inicio and fim else None
    if p_ini is not None:
        brutos = brutos.loc[p_ini:p_fim]
    if meta is not None and not meta.empty:
        meta = meta.copy()
        meta["_cod"] = meta["Codigo"].map(normalizar_codigo)

    anual, anuais, mensal, excluidas, manter = [], [], [], [], []
    for codigo in brutos.columns:
        serie = brutos[codigo]
        registros = serie.dropna()
        md = _meta_de(meta, codigo)
        if registros.empty:
            if idv_minimo is not None and idv_minimo > 0:
                dias = (p_fim - p_ini).days + 1 if p_ini is not None else 0
                excluidas.append({"Codigo": codigo, "Nome": md.get("Nome"), "Latitude": md.get("Latitude"),
                                  "Longitude": md.get("Longitude"), "UF": md.get("UF"),
                                  "Data Inicial": inicio or "", "Data Final": fim or "", "Num de Dias": dias,
                                  "Num Dados Válidos": 0, "IDV": 0.0, "IDV LDU": 0.0, "IDV Nonzero": 0.0,
                                  "IDV mínimo aplicado": idv_minimo, "Motivo": "Sem dados válidos (IDV = 0%)"})
            continue

        ini = p_ini if p_ini is not None else registros.index.min()
        fim_ = p_fim if p_fim is not None else registros.index.max()
        dias_periodo = _dias_periodo(ini, fim_)
        num_dias = len(dias_periodo)
        num_anos = math.ceil(num_dias / 365.25)
        validos = registros[registros >= 0]
        ldu = validos[validos >= limite]
        nz = validos[validos >= LIMIAR_NONZERO]
        idv = len(validos) / num_dias * 100
        base = {"Codigo": codigo, **md}

        if idv_minimo is not None and idv < idv_minimo:
            excluidas.append({"Codigo": codigo, "Nome": md.get("Nome"), "Latitude": md.get("Latitude"),
                              "Longitude": md.get("Longitude"), "UF": md.get("UF"),
                              "Data Inicial": registros.index.min().date(), "Data Final": registros.index.max().date(),
                              "Num de Dias": num_dias, "Num Dados Válidos": len(validos), "IDV": idv,
                              "IDV LDU": len(ldu) / num_dias * 100, "IDV Nonzero": len(nz) / num_dias * 100,
                              "IDV mínimo aplicado": idv_minimo, "Motivo": f"IDV inferior a {idv_minimo:g}%"})
            continue
        manter.append(codigo)

        # ---------------- mensal (climatologia de cada mês) ----------------
        dias_mes = pd.Series(dias_periodo.month).value_counts()
        medias_mes = {}
        for mes, nome_mes in NOMES_MESES.items():
            n_mes = int(dias_mes.get(mes, 0))
            vm = validos[validos.index.month == mes]
            lm, nm = vm[vm >= limite], vm[vm >= LIMIAR_NONZERO]
            medias_mes[mes] = vm.mean() if len(vm) else np.nan
            linha = {**base, "Mes": mes, "Nome do Mês": nome_mes,
                     "Data Inicial": registros.index.min().date(), "Data Final": registros.index.max().date(),
                     "Num de Dias": n_mes, "Num de Anos Total": num_anos,
                     "Num Dados Válidos": len(vm), "Num Dados chuva non_zero": len(nm), "Num Dados >= LDU": len(lm),
                     "IDV": len(vm) / n_mes * 100 if n_mes else 0.0,
                     "IDV LDU": len(lm) / n_mes * 100 if n_mes else 0.0,
                     "IDV Nonzero": len(nm) / n_mes * 100 if n_mes else 0.0,
                     "Num Anos Completos": contar_completos(validos, ini, fim_, mes=mes)}
            linha.update(_tres_estatisticas(vm, limite))
            mensal.append(linha)

        # ---------------- anual (um registro por ano) ----------------
        dias_ano = pd.Series(dias_periodo.year).value_counts()
        for ano in sorted(dias_ano.index):
            n_ano = int(dias_ano[ano])
            va = validos[validos.index.year == ano]
            la, na = va[va >= limite], va[va >= LIMIAR_NONZERO]
            linha = {**base, "Ano": int(ano), "Num de Dias": n_ano,
                     "Num Dados Válidos": len(va), "Num Dados chuva non_zero": len(na), "Num Dados >= LDU": len(la),
                     "IDV": len(va) / n_ano * 100, "IDV LDU": len(la) / n_ano * 100,
                     "IDV Nonzero": len(na) / n_ano * 100}
            linha.update(_tres_estatisticas(va, limite))
            anuais.append(linha)

        # ---------------- resumo do período ----------------
        climatologica = (sum(medias_mes[m] * DIAS_MEDIOS_MES[m] for m in range(1, 13))
                         if all(np.isfinite(medias_mes[m]) for m in range(1, 13)) else np.nan)
        linha = {"Codigo": codigo, "Num Total de registros": len(registros), **md,
                 "Data Inicial": registros.index.min().date(), "Data Final": registros.index.max().date(),
                 "Num de Dias": num_dias, "Num de Anos Total": num_anos,
                 "Num Anos Completos": contar_completos(validos, ini, fim_),
                 "Num Dados Válidos": len(validos), "Num Dados chuva non_zero": len(nz), "Num Dados >= LDU": len(ldu),
                 "IDV": idv, "IDV LDU": len(ldu) / num_dias * 100, "IDV Nonzero": len(nz) / num_dias * 100}
        linha.update(_tres_estatisticas(validos, limite))
        linha["Média mm/ano (climatológica)"] = climatologica
        anual.append(linha)

    brutos_saida = brutos[manter]
    validos_df = brutos_saida.where(brutos_saida >= 0)
    media_diaria = pd.DataFrame({
        "Data": validos_df.index,
        "Media_Diaria": validos_df.mean(axis=1, skipna=True).to_numpy(),
        "N_Estacoes": validos_df.notna().sum(axis=1).to_numpy(),
    })
    return {
        "ANUAL": pd.DataFrame(anual),
        "ANUAIS": pd.DataFrame(anuais),
        "MENSAL": pd.DataFrame(mensal),
        "Excluidas_IDV": pd.DataFrame(excluidas),
        "MEDIA_DIARIA": media_diaria,
        "BRUTOS": brutos_saida,
    }


def gravar_sumario(caminho, res, incluir_brutos=False):
    """Grava o sumário no formato esperado por 04/05/06: ANUAL, ANUAIS, MENSAL, Excluidas_IDV, Jan..Dez.

    Escrita em streaming (comum/planilhas.py). A aba ANUAIS tem uma linha por estação e
    por ano: com 1485 estações e a série histórica completa passa de 10 milhões de
    células, que o openpyxl não consegue montar na memória.
    """
    abas = {}
    if incluir_brutos:
        abas["BRUTOS"] = (res["BRUTOS"], res["BRUTOS"].index.name or "Data")
        abas["MEDIA_DIARIA"] = res["MEDIA_DIARIA"]
        abas["ESTATISTICAS"] = res["ANUAL"]  # nome antigo, mesmo conteúdo
    abas["ANUAL"] = res["ANUAL"]
    abas["ANUAIS"] = res["ANUAIS"]
    abas["MENSAL"] = res["MENSAL"]
    abas["Excluidas_IDV"] = res["Excluidas_IDV"]
    if not incluir_brutos:
        abas["MEDIA_DIARIA"] = res["MEDIA_DIARIA"]
    mensal = res["MENSAL"]
    for mes, nome in NOMES_MESES.items():
        abas[nome] = mensal[mensal["Mes"] == mes] if "Mes" in mensal.columns else mensal
    return gravar_abas(caminho, abas)
