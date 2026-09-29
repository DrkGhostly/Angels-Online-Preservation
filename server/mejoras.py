"""Mejoras de equipo: morteros, martillos, piensos y gemas.

Todo lo que decide este modulo sale de los datos del cliente, no de tablas
escritas a mano. Cada objeto de mejora dice en su descripcion hasta que nivel
sirve y cuanto sube, y su categoria dice para que vale:

    強化道具   mortero de mejora, para armas, armaduras y escudos
    強化飼料   pienso de montura
    寵物強化   pienso de mascota
    打孔道具   martillo de perforar, el que abre el hueco de la gema
    寶石       la gema que se mete en ese hueco
    寵物寶石   gema de mascota

Ejemplo de lo que trae un mortero de 11 estrellas:

    Exclusively for enhancing gears under lvl 119. ...
    Weapon: Attack+6%, Spell Attack+6%
    Armor: Defense+3%, Spell Defense+3%
    Shield: Defense+3%, Spell Defense+3%

Y un pienso de montura:

    Feed for mounts under Lvl 209. Increases Attack by 8%, Spell Attack by 8%
    and Movement Speed by 2% ...

Y una gema:

    Weapon: Fire Attack +58,Attack +94
    Armor: HP +110,Defense +41
    Level Requirement: Level 100

De ahi salen el tope de nivel, los porcentajes por tipo de equipo y los bonos
absolutos de la gema. Si manana sale un mortero nuevo, funciona solo.

Lo que NO esta aqui es la conversacion con el cliente: que paquete manda el
juego al usar el mortero y cual contesta el servidor. Eso no se ha capturado
todavia, asi que este modulo es el motor -- las reglas y las cuentas -- y la
parte de red se enchufa cuando haya una captura.
"""
import pathlib
import random
import re
import sqlite3

RAIZ = pathlib.Path(__file__).parent.parent
_DB = RAIZ / 'corpus' / 'content.db'
_TABLAS = ['item', 'item2', 'item3', 'item4', 'item5', 'item6', 'item7',
           'item8', 'item9']

# Hasta donde se puede mejorar una pieza.
MAX_MEJORA = 15
# Cuantos stats verdes caben en la entrada del inventario. Ver el comentario
# de inventario.MAX_EXTRAS: el sexto pisaria el contenedor de la pieza.
MAX_EXTRAS_ENTRADA = 5

# Cuantos huecos de gema admite una pieza. Lo dijo el usuario: cinco.
MAX_HUECOS = 5

# Los carteles que manda el servidor real, de string.xml. Medidos el
# 29/09/2026 viendo que numero llega en cada caso.
MSG_MEJORA_OK = 1613      # "Succeed in intensifying %s."
MSG_MEJORA_FALLO = 1614   # "%s Failed to intensify"
MSG_HUECO_OK = 1603       # "%s Succeed in cutting a hole"
MSG_HUECO_FALLO = 1604    # "%s Fail to cut a hole"
MSG_HUECO_NIVEL = 1605    # "The level of the props for cutting are not high enough."
MSG_HUECO_TOPE = 1606     # "%s Unable to cut a hole because the upper limit..."
MSG_ATRIBUTOS_OK = 2137   # "%s Change the attribute succeeded."

# Las categorias, tal como vienen en 物品類別.
CAT_MORTERO = '強化道具'
CAT_PIENSO_MONTURA = '強化飼料'
CAT_PIENSO_MASCOTA = '寵物強化'
CAT_PERFORAR = '打孔道具'
CAT_GEMA = '寶石'
CAT_GEMA_MASCOTA = '寵物寶石'
# El "martillo verde": no mejora, REEMPLAZA los atributos extra por otros
# nuevos. Su descripcion lo dice: "Apply it to gear, rides or robots below
# level N to replace their additional attributes bonus with new attributes".
CAT_VERDE = '幸運骰'

CLASES = {
    CAT_MORTERO: 'mortero',
    CAT_PIENSO_MONTURA: 'pienso_montura',
    CAT_PIENSO_MASCOTA: 'pienso_mascota',
    CAT_PERFORAR: 'perforar',
    CAT_GEMA: 'gema',
    CAT_GEMA_MASCOTA: 'gema_mascota',
    CAT_VERDE: 'verde',
}

# Como se llama cada stat en las descripciones, y con que nombre se guarda.
_STATS = [
    ('spell attack', 'matk'), ('spell defense', 'mdef'),
    ('spell def', 'mdef'), ('movement speed', 'velocidad'),
    ('speed', 'velocidad'), ('attack power', 'atk'), ('attack', 'atk'),
    ('defense', 'dfs'), ('fire attack', 'atk_fuego'),
    ('fire defense', 'dfs_fuego'), ('agility', 'agilidad'),
    ('rigor', 'rigor'), ('hp', 'hp'), ('mp', 'mp'),
]
_TIPOS = {'weapon': 'arma', 'armor': 'armadura', 'shield': 'escudo'}

_CACHE = {}


def _fila(item_id):
    """(nombre, categoria, nivel, descripcion) del item, o None."""
    iid = str(int(item_id))
    if iid in _CACHE:
        return _CACHE[iid]
    fila = None
    if _DB.exists():
        con = sqlite3.connect(_DB)
        for t in _TABLAS:
            try:
                r = con.execute('select 基本名稱, 物品類別, 物品等級, 說明定義 '
                                'from %s where id=?' % t, (iid,)).fetchone()
            except sqlite3.OperationalError:
                continue
            if r:
                fila = r
                break
        con.close()
    _CACHE[iid] = fila
    return fila


_INDICE = None


def _indice():
    """{clase: [ids]} de TODOS los objetos de mejora, de una sola pasada.

    Antes cada consulta abria la base y recorria las nueve tablas por un solo
    id. Buscar "todas las gemas" salian trescientas mil consultas y tardaba
    minutos; asi es una por tabla.
    """
    global _INDICE
    if _INDICE is not None:
        return _INDICE
    _INDICE = {c: [] for c in CLASES.values()}
    if not _DB.exists():
        return _INDICE
    con = sqlite3.connect(_DB)
    marcas = ','.join('?' * len(CLASES))
    for t in _TABLAS:
        try:
            filas = con.execute(
                'select id, 基本名稱, 物品類別, 物品等級, 說明定義 from %s '
                'where 物品類別 in (%s)' % (t, marcas),
                list(CLASES)).fetchall()
        except sqlite3.OperationalError:
            continue
        for iid, nom, cat, lv, desc in filas:
            _CACHE.setdefault(str(iid), (nom, cat, lv, desc))
            _INDICE[CLASES[cat]].append(int(iid))
    con.close()
    return _INDICE


def ids_de_clase(clase: str):
    """Todos los ids de una clase: 'gema', 'mortero', 'pienso_montura'..."""
    return list(_indice().get(clase, []))


def clase_de(item_id) -> str:
    """'mortero', 'gema', 'pienso_montura'... o '' si no es de mejora."""
    f = _fila(item_id)
    return CLASES.get(f[1], '') if f else ''


def tope_nivel(item_id) -> int:
    """Hasta que nivel de equipo sirve, leido de la descripcion.

    Las descripciones dicen "under lvl 119", "under Lvl 209" o "for rides
    under Lvl 39". Se devuelve ese numero; 0 si no lo dice.
    """
    f = _fila(item_id)
    if not f or not f[3]:
        return 0
    # Cada familia lo escribe a su manera: los morteros dicen "under lvl
    # 119", los piensos "under Lvl 209" y el martillo verde "below level 19".
    for patron in (r'under\s+lvl\s*(\d+)', r'below\s+level\s*(\d+)',
                   r'under\s+level\s*(\d+)'):
        m = re.search(patron, f[3], re.I)
        if m:
            return int(m.group(1))
    return 0


def nivel_requerido(item_id) -> int:
    """El nivel que la gema EXIGE al arma. 0 si no lo dice.

    Una gema de nivel 120 solo entra en equipo de 120 para arriba, nunca al
    reves: eso es lo que hace que una Purple Light Rune no se pueda meter en
    un arma de 110.
    """
    f = _fila(item_id)
    if not f or not f[3]:
        return 0
    m = re.search(r'level\s+requirement\s*:\s*level\s*(\d+)', f[3], re.I)
    return int(m.group(1)) if m else 0


def _leer_stats(trozo: str, porcentaje: bool):
    """Saca {stat: valor} de un trozo como 'Attack+6%, Spell Attack+6%'."""
    out = {}
    patron = r'([A-Za-z][A-Za-z ]*?)\s*\+?\s*(\d+)\s*%' if porcentaje \
        else r'([A-Za-z][A-Za-z ]*?)\s*\+\s*(\d+)'
    for nom, val in re.findall(patron, trozo):
        nom = nom.strip().lower()
        for etiqueta, clave in _STATS:
            if nom.endswith(etiqueta):
                out[clave] = int(val)
                break
    return out


def bonos_de(item_id):
    """Lo que sube ese objeto, por tipo de equipo.

    Devuelve {'arma': {...}, 'armadura': {...}, 'escudo': {...}} o, si la
    descripcion no separa por tipo -- como la del pienso de montura --, un
    solo {'todos': {...}}. Los morteros y los piensos van en POR CIENTO; las
    gemas, en valores absolutos.
    """
    f = _fila(item_id)
    if not f or not f[3]:
        return {}
    desc = f[3]
    cl = clase_de(item_id)
    pct = cl in ('mortero', 'pienso_montura', 'pienso_mascota')
    out = {}
    for linea in desc.split('\n'):
        m = re.match(r'\s*(Weapon|Armor|Shield)\s*[:：]\s*(.+)', linea, re.I)
        if m:
            stats = _leer_stats(m.group(2), pct)
            if stats:
                out[_TIPOS[m.group(1).lower()]] = stats
    if not out:
        # El pienso de montura lo dice en prosa, todo en la misma frase.
        stats = _leer_stats(desc, pct)
        if stats:
            out['todos'] = stats
    return out


# Lo que sube un mortero cuando su descripcion NO lo dice.
#
# Los de once estrellas para arriba lo escriben: "Weapon: Attack+6%, Spell
# Attack+6% / Armor: Defense+3%, Spell Defense+3%". Los de diez para abajo no
# dicen nada, y son 85 de los 92 que hay. Se les da lo mismo que declaran sus
# hermanos mayores, que es lo unico que respaldan los datos.
BONOS_POR_DEFECTO = {
    'arma': {'atk': 6, 'matk': 6},
    'armadura': {'dfs': 3, 'mdef': 3},
    'escudo': {'dfs': 3, 'mdef': 3},
}

# Y lo que sube un pienso de montura, que si lo dicen todos.
BONOS_MONTURA = {'atk': 8, 'matk': 8, 'velocidad': 2}

# El pienso de mascota tampoco da numeros: "Enhances the attack power of pet".
# Se le da el mismo 8% de ataque que el de montura, que es lo unico parecido
# que hay medido, y queda pendiente de comprobar con uno de verdad. En
# Celestia no se venden, asi que no se ha podido ver.
BONOS_MASCOTA = {'atk': 8}


def puede_perforar(item_id, nivel_equipo: int, tipo: str):
    """Si ese martillo puede abrir un hueco en esa pieza."""
    if clase_de(item_id) != 'perforar':
        return False, 'no es un martillo de perforar'
    tope = tope_nivel(item_id)
    if tope and nivel_equipo > tope:
        return False, ('sirve hasta nivel %d y la pieza es de %d'
                       % (tope, nivel_equipo))
    if tipo not in ('arma', 'armadura', 'escudo'):
        return False, 'solo se perforan armas, armaduras y escudos'
    return True, ''


def perforar(estado: dict, ranura, item_id, nivel_equipo: int, tipo: str,
             exito_seguro: bool = False, rng=None):
    """Abre un hueco de gema. CUIDADO: fallar aqui cuesta caro.

    El martillo no se porta como el mortero. Su descripcion lo dice: "No
    damage to the gear if the piercing failed but former hole and diamond
    inside will vanish". O sea que la pieza no se rompe, pero el hueco que ya
    tenia -- y la gema que hubiera dentro -- desaparecen.
    """
    rng = rng or random
    st = estado.setdefault(int(ranura), {'veces': 0, 'gemas': [],
                                         'extra': {}, 'huecos': 0})
    st.setdefault('huecos', 0)
    ok, motivo = puede_perforar(item_id, nivel_equipo, tipo)
    if not ok:
        return False, motivo
    if st.get('huecos', 0) >= MAX_HUECOS:
        return False, 'la pieza ya tiene los %d huecos' % MAX_HUECOS
    # NO se puede abrir un hueco nuevo con el anterior vacio: hay que meterle
    # una gema primero. Lo dijo el usuario y encaja con que fallar se lleve
    # "el hueco anterior y la gema de dentro" -- si pudieras acumular huecos
    # vacios, esa frase no tendria sentido.
    if st.get('huecos', 0) > len(st['gemas']):
        return False, 'hay que engarzar una gema antes de abrir otro hueco'
    if exito_seguro or rng.random() < probabilidad(st.get('huecos', 0)):
        st['huecos'] = st.get('huecos', 0) + 1
        return True, 'hueco abierto (%d)' % st['huecos']
    # Al fallar se pierde el ultimo hueco y lo que llevara dentro.
    if st.get('huecos', 0) > 0:
        st['huecos'] -= 1
        if st['gemas']:
            perdida = st['gemas'].pop()
            return False, 'fallo: se perdio el hueco y la gema %d' % perdida
        return False, 'fallo: se perdio el hueco anterior'
    return False, 'fallo, pero no habia ningun hueco que perder'


def engarzar(estado: dict, ranura, gema_id, nivel_equipo: int, tipo: str):
    """Mete una gema en un hueco libre."""
    st = estado.setdefault(int(ranura), {'veces': 0, 'gemas': [],
                                         'extra': {}, 'huecos': 0})
    libres = st.get('huecos', 0) - len(st['gemas'])
    ok, motivo = puede_engarzar(gema_id, nivel_equipo, tipo, libres)
    if not ok:
        return False, motivo
    st['gemas'].append(int(gema_id))
    return True, 'gema engarzada'


def puede_mejorar(item_id, nivel_equipo: int, tipo: str, veces: int):
    """(True, '') si ese objeto sirve para esa pieza, o (False, motivo)."""
    cl = clase_de(item_id)
    if not cl:
        return False, 'no es un objeto de mejora'
    if veces >= MAX_MEJORA:
        return False, 'ya esta al maximo (+%d)' % MAX_MEJORA
    tope = tope_nivel(item_id)
    if tope and nivel_equipo > tope:
        return False, ('sirve hasta nivel %d y la pieza es de %d'
                       % (tope, nivel_equipo))
    if cl == 'pienso_montura' and tipo != 'montura':
        return False, 'el pienso es solo para monturas'
    if cl == 'pienso_mascota' and tipo != 'mascota':
        return False, 'ese pienso es solo para mascotas'
    if cl == 'mortero' and tipo not in ('arma', 'armadura', 'escudo'):
        return False, 'el mortero es para armas, armaduras y escudos'
    return True, ''


def puede_engarzar(gema_id, nivel_arma: int, tipo: str, huecos_libres: int):
    """Si esa gema entra en esa pieza."""
    if clase_de(gema_id) not in ('gema', 'gema_mascota'):
        return False, 'no es una gema'
    if huecos_libres < 1:
        return False, 'no hay ningun hueco libre'
    req = nivel_requerido(gema_id)
    if req and nivel_arma < req:
        return False, ('la gema es de nivel %d y la pieza es de %d: solo se '
                       'puede de ese nivel hacia arriba' % (req, nivel_arma))
    if tipo not in ('arma', 'armadura', 'escudo'):
        return False, 'las gemas van en armas, armaduras y escudos'
    return True, ''


def stats_de_mejora(item_id, tipo: str, veces: int):
    """Los porcentajes acumulados de llevar `veces` mejoras con ese objeto."""
    b = bonos_de(item_id)
    base = b.get(tipo) or b.get('todos')
    if not base:
        cl = clase_de(item_id)
        if cl == 'pienso_montura':
            base = BONOS_MONTURA
        elif cl == 'pienso_mascota':
            base = BONOS_MASCOTA
        elif cl == 'mortero':
            base = BONOS_POR_DEFECTO.get(tipo, {})
        else:
            base = {}
    return {k: v * veces for k, v in base.items()}


# Los rangos que el cuadro del juego enseña al usar el martillo verde:
# "Attack 0 (0-210), Defense 0 (0-210), Spell Attack 0 (0-210), Spell Defense
# 0 (0-210), Rigor 3 (0-54), Agility 0 (0-54), Movement Speed 37 (0-40)".
# Salen de una captura de pantalla, no de los datos: si dependen del nivel de
# la pieza, todavia no se sabe.
# Que stats reparte el martillo verde, POR TIPO DE PIEZA.
#
# Antes habia una sola tabla para todo y estaba mal por los dos lados: le
# daba ataque a unas botas y defensa a una espada, y no daba nunca ni vida ni
# mana, que son los dos que mas aparecen. Esto sale de contar los stats
# verdes de las entradas capturadas, agrupados por la categoria del item:
#
#   armas (劍 斧 刀 槍 弓箭 杖 影刃)  hp, mp, atk, matk, rigor -- ni una sola
#                                      vez defensa en 700 registros
#   armadura (衣服 頭飾 鞋子 手套)     hp, mp, dfs, mdef, agilidad -- nunca atk
#   montura (座騎)                     los de combate mas VELOCIDAD, que no
#                                      aparece en ninguna otra pieza
#   mochila (背包)                     hp, mp, dfs
#   capa (披風)                        hp, mp, dfs, mdef, agilidad
#   accesorio (飾品)                   dfs, mdef, rigor, agilidad
#
# Los topes son los mas altos vistos de cada uno. OJO: el rango de verdad
# sube con el nivel de la pieza -- en los 刀 el ataque va de 19 a 3794 segun
# el arma -- y esa relacion no esta resuelta. Aqui se usa el tope observado,
# que sirve para probar pero no es la formula del juego.
RANGOS_POR_TIPO = {
    'arma': {'hp': (0, 270), 'mp': (0, 253), 'atk': (0, 3794),
             'matk': (0, 519), 'rigor': (0, 230), 'agilidad': (0, 92)},
    'armadura': {'hp': (0, 240), 'mp': (0, 178), 'dfs': (0, 1051),
                 'mdef': (0, 137), 'agilidad': (0, 24)},
    # La velocidad va DELANTE: solo la dan las monturas y solo caben cinco.
    'montura': {'velocidad': (0, 40), 'atk': (0, 200), 'matk': (0, 105),
                'dfs': (0, 192), 'mdef': (0, 137), 'rigor': (0, 20),
                'agilidad': (0, 40)},
    'mochila': {'hp': (0, 29), 'mp': (0, 31), 'dfs': (0, 14)},
    'capa': {'hp': (0, 45), 'mp': (0, 31), 'dfs': (0, 23),
             'mdef': (0, 10), 'agilidad': (0, 6)},
    'accesorio': {'dfs': (0, 74), 'mdef': (0, 9), 'rigor': (0, 25),
                  'agilidad': (0, 20)},
}

CATEGORIAS_VERDE = {
    '劍': 'arma', '斧': 'arma', '刀': 'arma', '槍': 'arma',
    '弓箭': 'arma', '杖': 'arma', '影刃': 'arma',
    '衣服': 'armadura', '頭飾': 'armadura',
    '鞋子': 'armadura', '手套': 'armadura',
    '座騎': 'montura', '背包': 'mochila',
    '披風': 'capa', '飾品': 'accesorio',
}


def _topes(nivel):
    """Los topes del martillo verde para una pieza de ese nivel.

    MEDIDO en dos cuadros del juego, que los enseña antes de usarlo:
      nivel 22 -> Attack 0-50, Rigor 0-22, Agility 0-22, Speed 0-22
      nivel 70 -> Attack 0-290, Rigor 0-70, Agility 0-70, Speed 0-40
    De ahi salen las tres reglas: los de combate van a 5*nivel-60, rigor y
    agilidad son el nivel tal cual, y la velocidad es el nivel con tope 40.
    OJO: son dos puntos, no veinte. La recta pasa por los dos exactamente,
    pero si aparece una pieza que no cuadre hay que volver aqui.
    """
    n = max(1, int(nivel or 1))
    combate = max(1, 5 * n - 60)
    return {'combate': combate, 'nivel': n, 'velocidad': min(n, 40),
            'vida': max(1, n * 4)}


def nivel_de_pieza(item_id):
    """El 物品等級 del item, que es de donde salen los topes."""
    import inventario as _inv
    try:
        return int(_inv.nivel_de_item(item_id) or 1)
    except Exception:
        return 1


def rangos_verde(item_id):
    """Los rangos que le tocan a esa pieza por su categoria."""
    import inventario as _inv
    cat = _inv.categoria_item(item_id) or ''
    tipo = CATEGORIAS_VERDE.get(cat)
    if tipo is None:
        # Lo que no se reconoce se trata como armadura, que es el reparto
        # mas inofensivo: vida, mana y defensas.
        tipo = 'armadura'
    # QUE stats da lo dice la categoria; HASTA CUANTO lo dice el nivel de la
    # pieza. Antes habia un tope fijo por tipo, y por eso una montura de
    # nivel 22 ofrecia lo mismo que una de nivel 70.
    t = _topes(nivel_de_pieza(item_id))
    topes = {'hp': t['vida'], 'mp': t['vida'],
             'atk': t['combate'], 'dfs': t['combate'],
             'matk': t['combate'], 'mdef': t['combate'],
             'rigor': t['nivel'], 'agilidad': t['nivel'],
             'velocidad': t['velocidad']}
    return {st: (0, topes[st]) for st in RANGOS_POR_TIPO[tipo]}


# Se deja el nombre viejo apuntando a la armadura para no romper lo que ya
# lo usaba, pero lo bueno es rangos_verde().
RANGOS_VERDE = RANGOS_POR_TIPO['armadura']


def tirar_verde(rangos, todos: bool = False, rng=None):
    """El martillo verde: reparte stats al azar dentro de sus rangos.

    `rangos` es {stat: (minimo, maximo)}, que es lo que el cliente enseña en
    su cuadro: "Attack 0 (0-210), Rigor 3 (0-54)"...

    Con `todos` puesto sale el maximo de TODOS los stats a la vez, que es la
    bandera que se pidio para probar. Sin ella se sortea cada uno.
    """
    rng = rng or random
    out = {}
    for stat, (lo, hi) in rangos.items():
        out[stat] = hi if todos else rng.randint(lo, hi)
    # En la entrada solo caben CINCO. Con la bandera de "todos los stats"
    # salian siete y los dos ultimos se escribian encima del contenedor de
    # la pieza, lo que cerraba el cliente. Se quedan los cinco PRIMEROS de
    # la tabla, no los de numero mas alto: en una montura la velocidad vale
    # 40 y el ataque 200, asi que cortando por valor se perdia justo lo que
    # distingue a una montura.
    if len(out) > MAX_EXTRAS_ENTRADA:
        out = dict(list(out.items())[:MAX_EXTRAS_ENTRADA])
    return out


def aplicar(estado: dict, ranura, item_id, nivel_equipo: int, tipo: str,
            exito_seguro: bool = False, rng=None):
    """Usa un objeto de mejora sobre la pieza de esa ranura.

    `estado` es el diccionario de mejoras del personaje, {ranura: {...}}. Se
    modifica en el sitio y se devuelve (ok, mensaje).

    Si falla NO se rompe nada, que es lo que dicen todas las descripciones:
    "No damage to the gear if the enhancement fails but the number of times
    the gear can be enhanced decreases by 1". O sea que un fallo gasta un
    intento igual.
    """
    rng = rng or random
    st = estado.setdefault(int(ranura), {'veces': 0, 'gemas': [],
                                         'extra': {}})
    ok, motivo = puede_mejorar(item_id, nivel_equipo, tipo, st['veces'])
    if not ok:
        return False, motivo
    if not exito_seguro and rng.random() >= probabilidad(st['veces']):
        # AL FALLAR SE BAJA UN NIVEL. Lo dice la descripcion, aunque se leyo
        # mal la primera vez: "No damage to the gear if the enhancement fails
        # but the number of times the gear has been enhanced decreases by 1".
        # No son los intentos que quedan, es el +N.
        #
        # La captura del 29/09/2026 lo confirma. Sobre unas Boots Of Contempt:
        #     exito -> +6
        #     FALLO
        #     exito -> +6     <- volvio al 6, o sea que el fallo lo dejo en 5
        #     exito -> +7
        #     FALLO
        # Si el fallo no restara, el segundo exito habria dado +7.
        st['veces'] = max(0, st['veces'] - 1)
        return False, 'la mejora fallo y bajo a +%d' % st['veces']
    st['veces'] += 1
    return True, '+%d' % st['veces']


def probabilidad(veces: int) -> float:
    """Que probabilidad tiene el siguiente intento.

    No esta medida: no hay ninguna captura de un fallo. Se pone una curva que
    baja con el nivel de mejora, empezando en segura y llegando al 20% en la
    ultima. En cuanto haya numeros de verdad se cambia aqui y ya.
    """
    if veces <= 3:
        return 1.0
    return max(0.20, 1.0 - (veces - 3) * 0.07)
