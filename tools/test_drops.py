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


def test_los_de_nivel_alto_tambien_sueltan():
    """El tramo que se quejaba el usuario: Forest/Desert en adelante."""
    for nt, nom, nv in ((20770, 'Emerald Croc', 322), (23459, 'Playful Imp', 381)):
        con = sum(1 for _ in range(200) if cb.botin_items(nt, nom, nv))
        assert con > 100, '%s solo solto %d de 200 veces' % (nom, con)


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
