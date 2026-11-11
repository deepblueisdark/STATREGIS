"""Normalização de códigos de estação lidos do Excel (int, float '838029.0', texto)."""
import math

import pandas as pd


def normalizar_codigo(valor):
    """Retorna o código como texto, sem '.0' e sem perder zeros à esquerda. None se vazio."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        if math.isfinite(valor) and valor.is_integer():
            return str(int(valor))
        return str(valor).strip()
    if hasattr(valor, "item"):                         # numpy escalares
        return normalizar_codigo(valor.item())
    texto = str(valor).strip()
    if not texto:
        return None
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto


def serie_codigos(serie):
    return serie.map(normalizar_codigo)
