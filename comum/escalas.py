"""Leitura do escalas.config (só dados; nada é executado).

Uso:
    from comum import escalas
    escalas.lista("idv")          -> [0.0, 10.0, ...]
    escalas.cores("cmap1")        -> [(0.545, 0, 0), ...]   (cores matplotlib)
    escalas.obter("idv")          -> valor bruto
    escalas.resolver_intervalos("idv" | "100,200,300" | ["100","200"])  -> lista ou None
"""
import ast
import os
from functools import lru_cache
from pathlib import Path

from . import RAIZ

CONFIG_PADRAO = Path(os.environ.get("STATREGIS_ESCALAS", RAIZ / "escalas.config"))


@lru_cache(maxsize=8)
def _carrega(caminho: str):
    with open(caminho, "r", encoding="utf-8") as f:
        arvore = ast.parse(f.read(), filename=caminho)
    nos = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    nos[alvo.id] = no.value
    return nos


def _avalia(no, nos, profundidade=0):
    if profundidade > 10:
        raise ValueError("Referência circular no escalas.config")
    if isinstance(no, ast.Name):                       # ex.: cmapp99 = cmap1
        if no.id not in nos:
            raise ValueError(f"'{no.id}' não definido no escalas.config")
        return _avalia(nos[no.id], nos, profundidade + 1)
    if isinstance(no, ast.Call) and getattr(no.func, "id", "") == "ListedColormap" and no.args:
        return _avalia(no.args[0], nos, profundidade + 1)
    return ast.literal_eval(no)


def nomes(config=None):
    return sorted(_carrega(str(config or CONFIG_PADRAO)))


def obter(nome, config=None):
    nos = _carrega(str(config or CONFIG_PADRAO))
    if nome not in nos:
        raise KeyError(f"'{nome}' não existe em {config or CONFIG_PADRAO}. Disponíveis: {', '.join(sorted(nos))}")
    return _avalia(nos[nome], nos)


def existe(nome, config=None):
    return nome in _carrega(str(config or CONFIG_PADRAO))


def lista(nome, config=None):
    valor = obter(nome, config)
    if not isinstance(valor, (list, tuple)) or not all(isinstance(v, (int, float)) for v in valor):
        raise ValueError(f"'{nome}' não é uma lista de números")
    return [float(v) for v in valor]


def normaliza_cor(cor):
    if isinstance(cor, (list, tuple)) and len(cor) == 2 and isinstance(cor[0], (list, tuple)):
        cor = cor[0]                                   # ((R,G,B), 'nome')
    if isinstance(cor, (list, tuple)) and len(cor) in (3, 4) and all(isinstance(v, (int, float)) for v in cor):
        return tuple(v / 255 for v in cor) if max(cor) > 1 else tuple(cor)
    return cor


def cores(nome, config=None):
    valor = obter(nome, config)
    if not isinstance(valor, (list, tuple)):
        raise ValueError(f"'{nome}' não é uma lista de cores")
    return [normaliza_cor(c) for c in valor]


def resolver_intervalos(valor, config=None):
    """Aceita nome no config, '100,200,300', ou lista de strings/números. Retorna lista ou None."""
    if valor is None or valor == "" or valor == []:
        return None
    if isinstance(valor, (list, tuple)):
        if len(valor) == 1:
            return resolver_intervalos(valor[0], config)
        return [float(v) for v in valor]
    texto = str(valor).strip()
    if existe(texto, config):
        return lista(texto, config)
    try:
        return [float(v) for v in texto.replace(";", ",").split(",") if v.strip()]
    except ValueError:
        raise ValueError(f"Intervalos '{valor}': use um nome do escalas.config ou números separados por vírgula")
