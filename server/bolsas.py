"""Bolsas de la suerte, huevos y regalos: que al abrirlos salga algo.

Son 22.055 items entre las dos categorias que usa el juego -- 紅包, que es
"sobre rojo" y agrupa las lucky bags y los huevos, y 禮物, que son los
regalos -- y hasta ahora ninguno hacia nada al usarlo.

DONDE ESTA EL CONTENIDO. En la columna 動態資料1 del propio item, y apunta a
una de dos cosas segun el item:

    * a una fila de drop_table -> se TIRA entre sus items, con sus pesos;
    * a un item suelto         -> se da ESE item, sin sorteo.

De los 22.055: 3.818 tiran de una tabla, 18.199 dan un item fijo y 38 no
declaran nada y se quedan fuera.

COMO SE SUPO. El Angel Treasure Lucky Bag, el item 3733, tiene 動態資料1=698,
y la fila 698 de drop_table se llama literalmente "Angel Treasure Lucky Bag".
Sus pesos suman 1000, que es exactamente su columna `factor`, asi que el
sorteo es un peso simple sobre el factor. Y hay una segunda confirmacion que
no depende de nada de esto: la descripcion del item lista los premios en
texto -- "Open it to get one of the following things randomly: Stealth Ring,
Swift Ring, Power Ring, Ice Magic Cat, Fiery Nightwolf, Beast God of Forest,
Marmot..." -- y son, en ese orden, los item1, item2, item3, item4, item5,
item6 y item7 de la fila 698.

El otro ejemplo que pidio el usuario cuadra igual: el Assassin Weapon Egg
(77224) apunta a la tabla 27154, y el Kyrio Angel Magic Stone (60534), que
es de los de "Right click to unseal", apunta al item 22430, que es
"Transform into Cactus" -- no sortea nada, se abre y da eso.

EL FACTOR NO SIEMPRE SE RESPETA. Hay tablas cuyos pesos no suman su factor;
en esas se sortea sobre la suma real, que es lo unico que no se puede
equivocar. Si una tabla no tiene ni un item utilizable, la bolsa NO se gasta:
mas vale que el jugador se quede con ella que perderla a cambio de nada.
"""
import logging
import pathlib
import random
import sqlite3

log = logging.getLogger('bolsas')

CAT_BOLSA = '紅包'       # sobre rojo: lucky bags y huevos
CAT_REGALO = '禮物'      # regalos
COL_NOMBRE = '基本名稱'
COL_CATEGORIA = '物品類別'
COL_DINAMICO = '動態資料1'
TABLAS_ITEM = ('item', 'item2', 'item3', 'item4', 'item5',
               'item6', 'item7', 'item8', 'item9')

_CACHE = None


def _db():
    return pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'


def _cargar():
    """item_id -> ('tabla', id) o ('item', id). Todo de una vez.

    De una vez porque abrir content.db por cada uso costaria un tiron, y son
    22.000 filas que entran en memoria sin despeinarse.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {}
    db = _db()
    if not db.exists():
        return _CACHE
    try:
        con = sqlite3.connect(db)
        tablas = {str(r[0]) for r in con.execute('select id from drop_table')}
        existentes = set()
        for t in TABLAS_ITEM:
            for (i,) in con.execute('select id from %s' % t):
                existentes.add(str(i))
        for t in TABLAS_ITEM:
            cols = [c[1] for c in con.execute('pragma table_info(%s)' % t)]
            if COL_CATEGORIA not in cols or COL_DINAMICO not in cols:
                continue
            for iid, cat, din in con.execute(
                    'select id, "%s", "%s" from %s where "%s" in (?, ?)'
                    % (COL_CATEGORIA, COL_DINAMICO, t, COL_CATEGORIA),
                    (CAT_BOLSA, CAT_REGALO)):
                d = str(din or '').strip()
                try:
                    clave = int(iid)
                except (TypeError, ValueError):
                    continue
                if clave in _CACHE or not d or d == '0':
                    continue
                if d in tablas:
                    _CACHE[clave] = ('tabla', d)
                elif d in existentes:
                    _CACHE[clave] = ('item', int(d))
        con.close()
    except Exception as e:
        log.warning('no se pudo leer el contenido de las bolsas (%s: %s); '
                    'no se abrira ninguna', type(e).__name__, e)
    return _CACHE


def es_bolsa(item_id: int) -> bool:
    return int(item_id or 0) in _cargar()


_TABLA_CACHE = {}


def _sorteo(tabla_id):
    """(item, cuantos) de esa tabla, por peso. None si no hay nada que dar."""
    if tabla_id in _TABLA_CACHE:
        opciones = _TABLA_CACHE[tabla_id]
    else:
        opciones = []
        db = _db()
        if db.exists():
            try:
                con = sqlite3.connect(db)
                cols = [c[1] for c in con.execute(
                    'pragma table_info(drop_table)')]
                fila = con.execute('select * from drop_table where id=?',
                                   (str(tabla_id),)).fetchone()
                con.close()
                if fila:
                    r = dict(zip(cols, fila))
                    for i in range(1, 41):
                        it = r.get('item%d' % i)
                        if not it or not str(it).isdigit() or int(it) <= 0:
                            continue
                        ct = r.get('count%d' % i)
                        pr = r.get('prob%d' % i)
                        opciones.append((
                            int(it),
                            int(ct) if ct and str(ct).isdigit() else 1,
                            int(pr) if pr and str(pr).isdigit() else 1))
            except Exception:
                log.debug('no se pudo leer la tabla %s', tabla_id,
                          exc_info=True)
        _TABLA_CACHE[tabla_id] = opciones
    if not opciones:
        return None
    total = sum(p for _i, _c, p in opciones)
    if total <= 0:
        it, ct, _p = random.choice(opciones)
        return (it, ct)
    tirada = random.randrange(total)
    for it, ct, p in opciones:
        if tirada < p:
            return (it, ct)
        tirada -= p
    it, ct, _p = opciones[-1]
    return (it, ct)


def abrir(item_id: int):
    """Que sale de esa bolsa: (item, cuantos), o None si no se puede abrir."""
    que = _cargar().get(int(item_id or 0))
    if not que:
        return None
    clase, valor = que
    if clase == 'item':
        return (int(valor), 1)
    return _sorteo(valor)
