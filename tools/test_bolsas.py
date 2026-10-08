"""Bolsas de la suerte, huevos y regalos.

Son 22.055 items entre las dos categorias que usa el juego -- 紅包 (sobre
rojo: lucky bags y huevos) y 禮物 (regalos) -- y no hacian nada al usarlos.

El contenido esta en la columna 動態資料1 del propio item, y apunta o a una
fila de drop_table, que se sortea con sus pesos, o a un item suelto, que se
da tal cual.

La comprobacion que no depende de nada: la DESCRIPCION del Angel Treasure
Lucky Bag lista los premios en texto, y son en ese mismo orden los primeros
items de su tabla.
"""
import collections
import pathlib
import sqlite3
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import bolsas

ANGEL_TREASURE = 3733        # -> tabla 698
ASSASSIN_EGG = 77224         # -> tabla 27154
KYRIO_STONE = 60534          # -> item 22430, sin sorteo
TRANSFORM_CACTUS = 22430


def test_las_tres_que_pidio_el_usuario_se_abren():
    for iid in (ANGEL_TREASURE, ASSASSIN_EGG, KYRIO_STONE):
        assert bolsas.es_bolsa(iid), iid
        assert bolsas.abrir(iid), iid


def test_el_regalo_sellado_da_siempre_lo_mismo():
    """Los de "Right click to unseal" no sortean: su 動態資料1 ES el item."""
    for _ in range(50):
        assert bolsas.abrir(KYRIO_STONE) == (TRANSFORM_CACTUS, 1)


def test_la_bolsa_sortea_entre_todos_los_de_su_tabla():
    salidas = {bolsas.abrir(ANGEL_TREASURE)[0] for _ in range(4000)}
    assert len(salidas) == 19, len(salidas)


def test_lo_que_dice_la_descripcion_es_lo_que_hay_en_la_tabla():
    """La prueba de fondo, y no depende del codigo: el texto del item lista
    los premios y son los primeros de la fila 698 en el mismo orden."""
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    nom = '\u57fa\u672c\u540d\u7a31'
    desc = con.execute('select "\u8aaa\u660e\u5b9a\u7fa9" from item where id=?',
                       (str(ANGEL_TREASURE),)).fetchone()[0]
    cols = [c[1] for c in con.execute('pragma table_info(drop_table)')]
    fila = dict(zip(cols, con.execute(
        'select * from drop_table where id=?', ('698',)).fetchone()))
    assert fila['monster_name'] == 'Angel Treasure Lucky Bag', fila['monster_name']
    for i in range(1, 8):
        iid = fila['item%d' % i]
        n = con.execute('select "%s" from item where id=?' % nom,
                        (str(iid),)).fetchone()
        assert n and n[0] in desc, (i, iid, n)


def test_los_pesos_de_esa_tabla_suman_su_factor():
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    cols = [c[1] for c in con.execute('pragma table_info(drop_table)')]
    fila = dict(zip(cols, con.execute(
        'select * from drop_table where id=?', ('698',)).fetchone()))
    suma = sum(int(fila['prob%d' % i]) for i in range(1, 41)
               if fila.get('item%d' % i) and str(fila['item%d' % i]).isdigit()
               and int(fila['item%d' % i]) > 0)
    assert suma == int(fila['factor']) == 1000, (suma, fila['factor'])


def test_el_sorteo_respeta_los_pesos():
    """El item4 pesa 10 de 1000 y el item8 pesa 30: tiene que salir mas."""
    c = collections.Counter(bolsas.abrir(ANGEL_TREASURE)[0]
                            for _ in range(20000))
    assert c[3730] > c[504], (c[3730], c[504])


def test_lo_que_no_es_bolsa_no_se_toca():
    assert not bolsas.es_bolsa(73)       # Copper Sword
    assert bolsas.abrir(73) is None


def test_cubre_casi_todas_las_bolsas_del_juego():
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    cat = '\u7269\u54c1\u985e\u5225'
    total = 0
    for t in bolsas.TABLAS_ITEM:
        cols = [c[1] for c in con.execute('pragma table_info(%s)' % t)]
        if cat not in cols:
            continue
        total += con.execute(
            'select count(*) from %s where "%s" in (?,?)' % (t, cat),
            (bolsas.CAT_BOLSA, bolsas.CAT_REGALO)).fetchone()[0]
    cubiertas = len(bolsas._cargar())
    assert total > 20000, total
    assert cubiertas > 14000, cubiertas


def test_el_servidor_las_abre_al_usarlas():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert '_bol.es_bolsa(item_id)' in fuente, 'no se enganchó al usar objeto'
    assert 'no se gasta la bolsa' in fuente or 'NO se gasta' in fuente, \
        'quito la proteccion de no gastar una bolsa vacia'


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
