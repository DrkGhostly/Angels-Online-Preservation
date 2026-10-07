"""Que los monstruos suelten algo, y que la plantilla de drops cargue.

Esto estuvo roto mucho tiempo sin que se notara: `json` no estaba importado
en combate.py, el NameError caia en un `except Exception` y los 12.715
drops de drops_monstruos.json quedaban muertos EN SILENCIO. El sintoma era
que de la region de Forest/Desert en adelante los bichos solo daban exp y
oro.
"""
import glob
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import combate as cb


def test_la_plantilla_de_drops_carga():
    """Lo que fallaba: volvia {} y nadie se enteraba."""
    pl = cb._cargar_drops_plantilla()
    assert pl, 'drops_monstruos.json no carga'
    for clave in ('drops', 'por_nombre', 'por_nivel'):
        assert pl.get(clave), 'falta o esta vacio: %s' % clave


def test_combate_importa_json():
    """El import que faltaba. Sin el, lo de arriba vuelve a pasar."""
    assert hasattr(cb, 'json'), 'combate.py no importa json'


def _monstruos_de_las_plantillas():
    vistos = {}
    for f in glob.glob(str(RAIZ / 'server' / 'plantillas' / '*.json')):
        try:
            d = json.loads(pathlib.Path(f).read_text(encoding='utf-8'))
        except Exception:
            continue
        sp = d.get('spawns') if isinstance(d, dict) else None
        if not isinstance(sp, list):
            continue
        for s in sp:
            if (isinstance(s, dict) and s.get('monstruo')
                    and s.get('nivel') and s.get('npc_type')):
                vistos[(s['npc_type'], s.get('nombre', ''), s['nivel'])] = f
    return vistos


def test_ningun_monstruo_se_queda_sin_botin():
    """Incluidos los de nivel alto, que caen en el respaldo por nivel."""
    vistos = _monstruos_de_las_plantillas()
    assert len(vistos) > 1000, 'no se leyeron las plantillas de mapa'
    sin = []
    for nt, nom, nv in vistos:
        cb.botin_items(nt, nom, nv)
        if not cb._DROPS_CACHE.get(nt):
            sin.append((nom, nv))
    assert not sin, '%d monstruos sin botin, p.ej. %s' % (len(sin), sin[:5])


def test_los_de_nivel_alto_tienen_de_donde_soltar():
    """El tramo que se quejaba el usuario: Forest/Desert en adelante.

    Se mira que TENGAN candidatos, no cuantas veces caen: cuanto cae lo
    decide TASA_DROP_BASE, que es del gusto de cada quien. Comprobando la
    tirada, el test se rompia solo con bajar la tasa.
    """
    for nt, nom, nv in ((20770, 'Emerald Croc', 322), (23459, 'Playful Imp', 381)):
        cb.botin_items(nt, nom, nv)
        assert cb._DROPS_CACHE.get(nt), '%s (nivel %d) no tiene nada que soltar' % (nom, nv)


def test_la_tasa_de_drop_manda_en_cuanto_cae():
    """Con la tasa alta cae casi siempre; con la baja, casi nunca."""
    import configuracion as cf
    original = cf.TASA_DROP_BASE
    try:
        cf.TASA_DROP_BASE = 10.5
        alto = sum(1 for _ in range(300) if cb.botin_items(20770, 'Emerald Croc', 322))
        cf.TASA_DROP_BASE = 0.01
        bajo = sum(1 for _ in range(300) if cb.botin_items(20770, 'Emerald Croc', 322))
    finally:
        cf.TASA_DROP_BASE = original
    assert alto > 240, 'con tasa 10.5 solo cayo %d de 300' % alto
    assert bajo < 60, 'con tasa 0.01 cayo %d de 300' % bajo


def test_el_botin_pega_con_el_nivel_del_bicho():
    """Un bicho de nivel 390 no puede soltar equipo de nivel 300.

    Los cubos de nivel se cortaban en 300 en los dos sitios -- al generar
    drops_monstruos.json y al elegir cubo en botin_items -- asi que TODA la
    ultima region (Clink Harbor va de 390 a 403) caia en el cubo de 300.
    Esos bichos no tienen tabla propia: su drop_id (27336 a 27343) no esta
    ni en drop.xml ni en drop_table, asi que acaban siempre en el fallback.
    """
    import sqlite3
    import sys, pathlib as _pl
    RZ = _pl.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(RZ / 'server'))
    import combate
    con = sqlite3.connect(RZ / 'corpus' / 'content.db')

    def nivel_item(iid):
        for t in ('item', 'item2', 'item3', 'item4', 'item5', 'item6',
                  'item7', 'item8', 'item9'):
            try:
                r = con.execute('select 物品等級 from %s where id=?' % t,
                                (str(iid),)).fetchone()
            except Exception:
                continue
            if r and str(r[0] or '').isdigit():
                return int(r[0])
        return None

    for npc_type, nombre, nivel in ((23765, 'Hardworking Pig', 390),
                                    (23771, 'E-Hardworking Pig', 401),
                                    (23770, 'Icy Automaton', 399)):
        combate._DROPS_CACHE.clear()
        combate.botin_items(npc_type, nombre, nivel)
        cands = combate._DROPS_CACHE.get(npc_type) or []
        assert cands, nombre
        niveles = [nivel_item(i) for i, _ in cands]
        niveles = [n for n in niveles if n]
        assert niveles, nombre
        # ni un escalon entero por debajo del bicho
        assert min(niveles) >= nivel - 20, (nombre, nivel, min(niveles))


def test_los_cubos_llegan_hasta_el_ultimo_bicho():
    """El monstruo mas alto del juego es de nivel 485."""
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / 'server'))
    import combate
    cubos = sorted(int(k) for k in combate._cargar_drops_plantilla()['por_nivel'])
    assert max(cubos) >= 470, cubos[-5:]


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK   %s' % nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA %s: %s' % (nombre, e))
    print('fallos:', fallos)
