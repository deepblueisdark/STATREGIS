"""Funções compartilhadas do STATREGIS (inventário ANA, estatísticas, filtros, gráficos, escalas).

Cada script das pastas 01..06 faz:
    import sys; from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
e importa daqui. Assim cada regra existe em um só lugar.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA_SHAPES = RAIZ / "00_STUFF"
