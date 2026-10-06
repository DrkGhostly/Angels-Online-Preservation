"""El album de cartas (Alt+C): card.xml.

459 cartas en el pak vigente (update25), cada una con su sprite, nombre,
estrellas y categoria. Se consiguen matando al bicho que las suelta.

OJO con el pak: card.xml esta en once, y leyendo el equivocado salen 121
en vez de 459. Ver tools/paks.py.
"""
import json
import pathlib

_TABLA = None


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'cartas.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def de_id(cid: int):
    for c in tabla():
        if c.get('id') == int(cid):
            return c
    return None


def por_categoria() -> dict:
    out = {}
    for c in tabla():
        out.setdefault(c.get('categoria') or '?', []).append(c)
    return out


def resumen(tengo) -> dict:
    """Cuantas lleva de cada categoria y el total."""
    ids = set(int(x) for x in (tengo or []))
    out = {}
    for cat, cs in por_categoria().items():
        out[cat] = {'tengo': sum(1 for c in cs if c['id'] in ids),
                    'de': len(cs)}
    out['total'] = {'tengo': len(ids & {c['id'] for c in tabla()}),
                    'de': len(tabla())}
    return out


def estrellas_de(tengo) -> int:
    """La suma de estrellas de las cartas que tiene."""
    ids = set(int(x) for x in (tengo or []))
    return sum(int(c.get('estrellas') or 0) for c in tabla() if c['id'] in ids)
