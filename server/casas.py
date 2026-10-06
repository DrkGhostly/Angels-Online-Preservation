"""Housing: los muebles y la puntuacion de la casa (furniture.xml).

2.600 muebles en el pak vigente (update26), cada uno con su categoria, su
tipo y los PUNTOS DE DECORACION que aporta al ponerlo. Las categorias son
suelo, alfombra, papel de pared, colgantes, muebles de suelo y el aspecto
exterior de la casa.

Los puntos van de 0 a 10.000 y son lo que decide el nivel de la casa.

Lo que el cliente NO trae son los temporizadores ni las formulas del
cuarto de mascotas, los huevos, la pelota, el martillo, la maquina de
huevos y la limpieza. El equipo de RE:Angels Online los tiene como
hipotesis y nosotros tampoco los hemos medido.
"""
import json
import pathlib

_TABLA = None


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'casas.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['muebles']
        except Exception:
            _TABLA = []
    return _TABLA


def mueble(mid: int):
    for m in tabla():
        if m.get('id') == int(mid):
            return m
    return None


def puntos_de(puestos) -> int:
    """La decoracion que suman los muebles colocados."""
    total = 0
    for mid in (puestos or []):
        m = mueble(mid)
        if m:
            try:
                total += int(m.get('puntos') or 0)
            except (TypeError, ValueError):
                pass
    return total


def por_categoria() -> dict:
    out = {}
    for m in tabla():
        out.setdefault(m.get('categoria') or '?', []).append(m)
    return out
