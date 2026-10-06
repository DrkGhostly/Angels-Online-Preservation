"""Star Blessing (Ctrl+S): las cartas de estrella de star_client.xml.

572 filas: cada carta con su rango, nombre, nivel, el stat que da, lo que
da al convertirla y lo que cuesta subirla.

    一般 / 力量 / nivel 1  -> 物理攻擊 +40, convertir 50, subir 100
    nivel 2                -> +80, convertir 100, subir 200

Lo que el cliente NO trae son las PROBABILIDADES de la adivinacion ni las
del bingo: eso lo decidia el servidor. El equipo de RE:Angels Online llego
a lo mismo y las tiene como hipotesis.
"""
import json
import pathlib

_TABLA = None

STATS = {
    '物理攻擊': 'atk', '魔法攻擊': 'matk', '物理防禦': 'dfs',
    '魔法防禦': 'mdef', '生命力': 'hp', '魔力': 'mp',
    '精準': 'rigor', '靈敏': 'agilidad', '重擊': 'critico',
}


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'estrellas.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def carta(nombre: str, nivel: int):
    for c in tabla():
        if c.get('nombre') == nombre and int(c.get('nivel') or 0) == int(nivel):
            return c
    return None


def bonos(puestas) -> dict:
    """Los stats que suman las cartas equipadas.

    `puestas` es una lista de (nombre, nivel).
    """
    out = {}
    for nom, nv in (puestas or []):
        c = carta(nom, nv)
        if not c:
            continue
        for campo, valor in (('stat', 'valor'), ('stat2', 'valor2')):
            k = STATS.get(str(c.get(campo) or ''))
            if not k:
                continue
            try:
                out[k] = out.get(k, 0) + int(c.get(valor) or 0)
            except (TypeError, ValueError):
                pass
    return out


def cuesta_subir(nombre: str, nivel: int) -> int:
    c = carta(nombre, nivel)
    try:
        return int(c.get('cuesta_subir') or 0) if c else 0
    except (TypeError, ValueError):
        return 0
