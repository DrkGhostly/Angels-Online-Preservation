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


def test_las_dos_que_tiran_de_tabla_se_abren():
    for iid in (ANGEL_TREASURE, ASSASSIN_EGG):
        assert bolsas.es_bolsa(iid), iid
        assert bolsas.abrir(iid), iid


def test_el_sellado_no_se_abre_con_un_item_inventado():
    """El fallo que destapo el usuario. El Kyrio Angel Magic Stone sellado
    (60534) tiene 動態資料1=22430, y el primer intento dio por hecho que ese
    era el item que sale. Es falso: al desellarlo sale el 63816, la piedra
    sin sellar, no el 22430, que es "Transform into Cactus".

    Que el numero exista como item no prueba nada -- casi cualquier numero
    de ese rango existe -- asi que mientras no se sepa que es, esa bolsa no
    se abre. Mas vale que no haga nada a que de lo que no es."""
    assert not bolsas.es_bolsa(KYRIO_STONE)
    assert bolsas.abrir(KYRIO_STONE) is None


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


def test_solo_se_abren_las_que_tienen_tabla():
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
    # Solo las que apuntan a una fila de drop_table, que son las unicas
    # comprobadas. Las otras 18.199 se quedan fuera a proposito.
    assert 3000 < cubiertas < 5000, cubiertas


def test_el_servidor_las_abre_al_usarlas():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert '_bol.es_bolsa(item_id)' in fuente, 'no se enganchó al usar objeto'
    assert 'no se gasta la bolsa' in fuente or 'NO se gasta' in fuente, \
        'quito la proteccion de no gastar una bolsa vacia'


# ---------------------------------------------------------------------------
# Objetos que bufean
# ---------------------------------------------------------------------------
KYRIO_SIN_SELLAR = 63816
MAGIA_KYRIO = 20834


def test_el_item_sabe_que_magia_aplica():
    assert bolsas.hechizo_de(KYRIO_SIN_SELLAR) == MAGIA_KYRIO


def test_la_magia_de_la_piedra_es_la_que_dice_el_juego():
    """No hay que interpretar nada a mano: datos_magia() ya parsea la fila."""
    import combate as cb
    m = cb.datos_magia(MAGIA_KYRIO)
    assert m['es_buff'] is True
    assert m['dur_ms'] == 3600 * 1000, m['dur_ms']
    assert m['hp_bonus'] == 12000 and m['mp_bonus'] == 9600
    assert m['def_bonus'] == 4000 and m['matk_bonus'] == 2800
    assert m['hit_bonus'] == 100 and m['eva_bonus'] == 100


def test_hay_miles_de_objetos_que_bufean():
    assert len(bolsas._cargar_buffs()) > 9000, len(bolsas._cargar_buffs())


def test_una_bolsa_no_se_confunde_con_un_buff():
    assert bolsas.hechizo_de(ANGEL_TREASURE) is None
    assert not bolsas.es_bolsa(KYRIO_SIN_SELLAR)


def test_el_servidor_aplica_el_buff_al_usar_el_objeto():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert '_bol0.buff_de(item_id' in fuente, 'no se engancho el buff'
    assert 'personaje.buffs[_mid_buff]' in fuente, 'no se guarda el buff'
    assert '_fin_buff_item' in fuente, 'el buff no expira'


def test_el_buff_trae_cada_linea_del_cartel_del_objeto():
    """El cartel de la piedra en el juego dice, linea por linea:

        Increase 12000 Maximum HP      Increase 9600 Maximum MP
        Increase 4000 Defense          Increase 2800 Spell Attack
        Increase 100 Rigor             Increase 100 Agility
        Increase 16% Movement Speed    Effect lasts for 1 hrs.

    Todas tienen que acabar en el diccionario de buffs del personaje, y con
    las claves que lee la funcion de stats del servidor."""
    mid, entrada, dur = bolsas.buff_de(KYRIO_SIN_SELLAR, 0.0)
    assert mid == MAGIA_KYRIO
    assert dur == 3600 * 1000, dur
    assert entrada['hp_bonus'] == 12000
    assert entrada['mp_bonus'] == 9600
    assert entrada['def'] == 4000
    assert entrada['matk'] == 2800
    assert entrada['hit'] == 100, 'Rigor'
    assert entrada['eva'] == 100, 'Agility'
    # la velocidad no va suelta: _velocidad_de la saca de dentro de 'mag'
    assert entrada['mag']['move_speed_bonus'] == 16


def test_las_claves_del_buff_son_las_que_lee_el_servidor():
    """Si alguien renombra una clave, el buff se aplicaria a medias y en
    silencio. Se comprueba contra el codigo que suma los stats."""
    # La suma de stats vive en inventario.py, no en app.py.
    fuente = (RAIZ / 'server' / 'inventario.py').read_text(encoding='utf-8')
    vel = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    _mid, entrada, _d = bolsas.buff_de(KYRIO_SIN_SELLAR, 0.0)
    for clave in ('def', 'matk', 'hit', 'eva'):
        assert "b_data['%s']" % clave in fuente, clave
    for clave in ('hp_bonus', 'mp_bonus'):
        assert "b_data['%s']" % clave in fuente or \
               "b_data.get('%s')" % clave in fuente, clave
    assert "move_speed_bonus" in vel, 'la velocidad no se lee'
    assert set(('def', 'matk', 'hit', 'eva', 'hp_bonus', 'mp_bonus')) <= set(entrada)


def test_la_piedra_no_se_gasta_al_usarla():
    """Lo conto el usuario: "es un consumible permanente, se usa y queda ahi
    hasta que se pierda el buff y lo uses de nuevo". Lo dice la columna
    使用不扣 ("usar sin descontar"), que marca 2.069 objetos."""
    assert bolsas.se_gasta(KYRIO_SIN_SELLAR) is False
    assert bolsas.se_gasta(1228) is True       # una hierba normal si


def test_el_buff_va_antes_que_los_consumibles():
    """EL FALLO QUE SE VIO EN VIVO. efecto_consumible() lee el hp y el mp de
    la fila de magia y los toma por una pocion, asi que la piedra "curaba"
    12000 de vida, SE GASTABA y no bufeaba nada. El hp de esa fila no es una
    cura: es +12000 al MAXIMO."""
    import inventario as inv
    # el consumible generico sigue viendo hp/mp en ese item...
    assert inv.efecto_consumible(KYRIO_SIN_SELLAR), 'cambio efecto_consumible'
    # ...asi que el orden de los casos es lo unico que lo salva
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert fuente.index('Caso 4.9') < fuente.index('Caso 5: Consumibles'),         'el buff volvio a quedar detras de los consumibles'


def test_no_se_gasta_el_objeto_que_no_se_gasta():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert 'if _bol0.se_gasta(item_id):' in fuente,         'volvio a gastarse siempre el objeto'



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
