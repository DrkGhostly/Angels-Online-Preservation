"""Un bicho de nivel 400 no puede soltar equipo de nivel 15.

El juego REUSA NOMBRES. Hay 21 nombres que comparten dos monstruos con mas
de cien niveles de diferencia, y la tabla de drops se buscaba por nombre
cuando no habia nada mejor, asi que el grande heredaba la del chico:

    Dragon Soldier    nivel 414 -> items de nivel 89
    Blue Merman       nivel 384 -> items de nivel 89
    Magic Pumpkinman  nivel 300 -> items de nivel 15
    Spring Fairy      nivel 264 -> items de nivel 110

Son cuatro en todo el juego, pero son justo los que dejan a un bicho de
nivel 400 soltando basura. Ahora, si lo que sale por el nombre esta por
debajo de la mitad del nivel del monstruo, se descarta y se usa el cubo de
nivel, que da equipo de su nivel.

OJO CON UN FALSO POSITIVO: los items "(P)" de nivel 410 se llaman igual que
las armas del principio -- Copper Sword (P) es el item 64346 y pide nivel
410, mientras que el Copper Sword de toda la vida es el 73 y pide 1. Ver un
Copper Sword cayendo de un bicho de 410 NO es un fallo.
"""
import pathlib
import sqlite3
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import combate as cb

# Los cuatro homonimos, con el nivel que tienen y el que tenian sus drops.
HOMONIMOS = {23419: ('Dragon Soldier', 414), 23389: ('Blue Merman', 384),
             23544: ('Magic Pumpkinman', 300), 17048: ('Spring Fairy', 264)}


def _niveles(npc_type, nombre, nivel):
    cb._DROPS_CACHE.pop(int(npc_type), None)
    cb.botin_items(int(npc_type), nombre, int(nivel))
    cand = cb._DROPS_CACHE.get(int(npc_type)) or []
    # cb._nivel_item y no inventario.nivel_de_item: ese abre una conexion
    # nueva a content.db por cada item y el barrido tardaba minutos.
    return [x for x in (cb._nivel_item(i) or 0 for i, _ in cand) if x]


def test_los_cuatro_homonimos_sueltan_de_su_nivel():
    for npc, (nombre, nivel) in HOMONIMOS.items():
        niv = _niveles(npc, nombre, nivel)
        assert niv, (npc, nombre, 'se quedo sin drops')
        niv.sort()
        mediana = niv[len(niv) // 2]
        assert mediana * 2 >= nivel, (nombre, nivel, 'mediana', mediana)


def test_el_filtro_no_descarta_una_tabla_buena():
    """Solo tiene que saltar con lo que esta MUY por debajo. Una tabla con
    algun material de nivel bajo suelto sigue valiendo."""
    assert cb._nivel_plausible([[73, 1]], 1)
    assert cb._nivel_plausible([[64346, 1]], 410)        # Copper Sword (P)
    assert not cb._nivel_plausible([[73, 1]], 410)       # el de nivel 1
    # sin datos de nivel no se descarta nada
    assert cb._nivel_plausible([[999999999, 1]], 410)


def test_el_copper_sword_de_410_existe_y_no_es_el_de_nivel_1():
    """El falso positivo que hay que saber reconocer."""
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    nom = '\u57fa\u672c\u540d\u7a31'
    lv = '\u7269\u54c1\u7b49\u7d1a'
    r1 = con.execute('select "%s","%s" from item where id=73' % (nom, lv)).fetchone()
    r2 = con.execute('select "%s","%s" from item7 where id=64346' % (nom, lv)).fetchone()
    assert r1[0] == 'Copper Sword' and r1[1] == '1', r1
    assert r2[0] == 'Copper Sword (P)' and r2[1] == '410', r2


def test_ningun_bicho_de_395_para_arriba_suelta_nivel_10_o_menos():
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    malos = []
    for mid, nombre, nivel in con.execute(
            "select id,name,level from monster "
            "where cast(level as integer)>=395"):
        for x in _niveles(mid, nombre, nivel):
            if x <= 10:
                malos.append((mid, nombre, x))
                break
    assert not malos, malos[:5]


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK    %s' % nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA %s: %s' % (nombre, e))
    print('fallos:', fallos)
    raise SystemExit(1 if fallos else 0)
