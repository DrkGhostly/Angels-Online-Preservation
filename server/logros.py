"""Logros, titulos y puntos (achievement.xml).

4.351 logros en 74 tipos de regla. Cada fila dice su categoria, el texto,
cuantos puntos da, si anuncia al servidor y, 543 de ellas, que titulo
desbloquea.

Las reglas son el campo 規法 de la tabla. Aqui se implementan las que se
pueden comprobar con lo que el servidor ya sabe; las demas quedan
registradas y se dan por un aviso externo (`otorgar`), para que la tabla
este entera aunque la condicion todavia no se vigile.

Reglas que SI se comprueban solas:

    達指定等級        llegar a nivel N
    技能到達指定等級    una habilidad a nivel N
    殺指定編號怪物      matar un npc_type
    角色素質          un stat por encima de N
    成就積分          acumular N puntos de logro
    達成成就          tener otros logros (param1 y param2)

Las que NO, y por que:

    任務完成 (850)    hace falta el sistema de misiones
    融合相關 (361)    la fusion de mascotas
    NPC觸發 (297)     que el servidor avise al hablar con el NPC
    房屋系統 (79)     el sistema de casas
"""
import json
import pathlib

_TABLA = None
_POR_REGLA = None


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'logros.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def por_regla(regla: str) -> list:
    global _POR_REGLA
    if _POR_REGLA is None:
        _POR_REGLA = {}
        for f in tabla():
            _POR_REGLA.setdefault(f.get('regla'), []).append(f)
    return _POR_REGLA.get(regla, [])


def de_id(lid: int):
    for f in tabla():
        if f.get('id') == lid:
            return f
    return None


def puntos_de(conseguidos) -> int:
    """La suma de puntos de los logros que ya tiene."""
    ids = set(int(x) for x in (conseguidos or []))
    return sum(int(f.get('puntos') or 0) for f in tabla() if f.get('id') in ids)


def titulos_de(conseguidos) -> list:
    """Los titulos que desbloquean esos logros."""
    ids = set(int(x) for x in (conseguidos or []))
    return sorted({int(f['titulo']) for f in tabla()
                   if f.get('id') in ids and f.get('titulo')})


# --------------------------------------------------------------- reglas
def _num(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


STATS = {
    'HP最大值': 'hp_max', 'MP最大值': 'mp_max', '攻擊': 'atk',
    '防禦': 'dfs', '魔攻': 'matk', '魔防': 'mdef',
    '精準': 'rigor', '靈敏': 'agilidad',
}


def comprobar(personaje, conseguidos, *, muertos=None, stats=None) -> list:
    """Los logros que el personaje cumple y todavia no tiene.

    `muertos` es {npc_type: cuantos} y `stats` un dict de atributos ya
    calculados, por si el llamador los tiene a mano.
    """
    ya = set(int(x) for x in (conseguidos or []))
    muertos = muertos or {}
    stats = stats or {}
    nuevos = []
    nivel = _num(getattr(personaje, 'nivel', 0))
    habs = {int(h[0]): _num(h[1], 1)
            for h in (getattr(personaje, 'habilidades', None) or [])
            if isinstance(h, (list, tuple))}
    pts = puntos_de(ya)

    for f in por_regla('達指定等級'):
        if f['id'] not in ya and nivel >= _num(f.get('param1')):
            nuevos.append(f['id'])
    for f in por_regla('技能到達指定等級'):
        if f['id'] in ya:
            continue
        pide = _num(f.get('param1'))
        if pide and any(v >= pide for v in habs.values()):
            nuevos.append(f['id'])
    for f in por_regla('殺指定編號怪物'):
        if f['id'] in ya:
            continue
        tipo = _num(f.get('param1'))
        if tipo and muertos.get(tipo, 0) >= max(1, _num(f.get('param2'), 1)):
            nuevos.append(f['id'])
    for f in por_regla('角色素質'):
        if f['id'] in ya:
            continue
        clave = STATS.get(str(f.get('param1') or ''))
        if clave and _num(stats.get(clave)) >= _num(f.get('param2')):
            nuevos.append(f['id'])
    for f in por_regla('成就積分'):
        if f['id'] not in ya and pts >= _num(f.get('param1')):
            nuevos.append(f['id'])
    for f in por_regla('達成成就'):
        if f['id'] in ya:
            continue
        pide = [_num(f.get('param1')), _num(f.get('param2'))]
        pide = [x for x in pide if x]
        if pide and all(x in ya for x in pide):
            nuevos.append(f['id'])
    return sorted(set(nuevos))


def otorgar(conseguidos, lid: int) -> bool:
    """Da un logro a mano. Para las reglas que el servidor no vigila."""
    lid = int(lid)
    if de_id(lid) is None or lid in set(int(x) for x in (conseguidos or [])):
        return False
    conseguidos.append(lid)
    return True
