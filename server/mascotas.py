"""Mascotas: el bloque de estado que el cliente usa para su ficha.

Todo lo de aqui sale de una captura del 29/09/2026 en la que se invoco una
mascota, se compro otra y se habilito una tercera. Los opcodes que aparecen:

    c2s 0x015E  [u8]        invocar o guardar la mascota
    c2s 0x003E  [u8]        orden a la mascota (atacar, seguir...)
    c2s 0x012D  (vacio)     abrir la lista de la tienda -> s2c 0x005F
    c2s 0x012B  [u32]       comprar -> s2c 0x0062 (oro) + 0x0061 (item)
    s2c 0x0065  200 bytes   ESTADO DE LA MASCOTA, que es lo que hay aqui
    s2c 0x0062  4 bytes     el oro que queda
    s2c 0x0061              el objeto comprado

El 0x0065 se mando setenta y tres veces en esa sesion: es el que pinta la
ficha. Su formato se saco comparando los bytes contra la ficha que el juego
enseñaba en ese momento -- una Battlemaid de nivel 246 con 37.550 de HP,
12.100 de ataque, 15.755 de defensa, 3.137 de ataque magico, 4.431 de defensa
magica, 1.947 de rigor, 1.127 de agilidad, 462 de saciedad y 78 de intimidad.
Todos esos numeros aparecieron, y por eso el mapa de abajo no es una
suposicion.

Cada stat viaja DOS VECES seguidas, en +83/+87, +91/+95 y asi. Es el valor
base y el efectivo, que es justo lo que la ventana enseña en sus dos
columnas: "Atk 12100" y "T.Atk 0".

Los dos u32 de +8 y +12 valen los dos la INSTANCIA del item en la mochila
(1167 para la Battlemaid, el mismo numero que lleva su entrada), y el u16 de
+16 es el sprite, que tambien esta en el +131 de la entrada. Se vio en
mundo_022355_871035, sacando y guardando la misma mascota.

El MP actual no esta aqui, pero si en la entrada del inventario, en el +127.
"""
import json
import pathlib
import struct

TAM = 200

# Donde vive cada cosa dentro del bloque.
OFF = {
    'entidad': 0,
    'tipo': 4,
    'instancia': 8,      # la del item en la mochila, repetida en el 12
    'sprite': 16,        # u16
    'nombre': 18,        # ASCIIZ
    'nivel': 31,
    'exp': 35,
    'exp_max': 51,
    'hp': 59,
    'hp_max': 71,
    'mp_max': 79,
    'atk': 83,
    'dfs': 91,
    'matk': 99,
    'mdef': 107,
    'rigor': 115,
    'agilidad': 123,
    'saciedad': 177,     # u16
    'intimidad': 179,
}

# Los que van repetidos: primero el base y cuatro bytes despues el efectivo.
DOBLES = ('atk', 'dfs', 'matk', 'mdef', 'rigor', 'agilidad')

# Cuanta saciedad hace falta para que la mascota mejore. Lo dice el Pet Feed:
# "Increases the satiation degree by 500. (The pet can enhance its abilities
# after the satiation degree is more than 100.)"
SACIEDAD_PARA_MEJORAR = 100
SACIEDAD_MAXIMA = 1000
SACIEDAD_POR_PIENSO = 500


def leer(cuerpo: bytes) -> dict:
    """Desmonta un 0x0065 en un diccionario."""
    if len(cuerpo) < TAM:
        return {}
    d = {}
    for campo, off in OFF.items():
        if campo == 'nombre':
            d[campo] = cuerpo[off:off + 16].split(b'\0')[0].decode(
                'latin1', 'replace')
        elif campo in ('saciedad', 'sprite'):
            d[campo] = struct.unpack_from('<H', cuerpo, off)[0]
        else:
            d[campo] = struct.unpack_from('<I', cuerpo, off)[0]
    return d


def armar(estado: dict) -> bytes:
    """El 0x0065 con el estado de una mascota.

    Lo que no se conoce se deja en cero: el bloque es de tamaño fijo, asi que
    un campo sin descifrar no corre a los demas de sitio.
    """
    b = bytearray(TAM)
    for campo, off in OFF.items():
        v = estado.get(campo)
        if v is None:
            continue
        if campo == 'nombre':
            nom = str(v).encode('latin1', 'replace')[:15]
            b[off:off + len(nom)] = nom
        elif campo in ('saciedad', 'sprite'):
            struct.pack_into('<H', b, off, min(0xFFFF, int(v)))
        else:
            struct.pack_into('<I', b, off, int(v) & 0xFFFFFFFF)
        if campo in DOBLES:
            struct.pack_into('<I', b, off + 4, int(v) & 0xFFFFFFFF)
    return struct.pack('<H', 0x0065) + bytes(b)


def alimentar(estado: dict, cantidad: int = SACIEDAD_POR_PIENSO) -> tuple:
    """El Pet Feed normal: sube la saciedad, no los stats.

    Su descripcion lo separa bien: el pienso corriente da saciedad, y es la
    saciedad la que deja que la mascota mejore. El que sube stats de verdad
    es el Improved Pet Feed, que va por mejoras.py.
    """
    antes = estado.get('saciedad', 0)
    estado['saciedad'] = min(SACIEDAD_MAXIMA, antes + cantidad)
    return estado['saciedad'], estado['saciedad'] >= SACIEDAD_PARA_MEJORAR


def aplicar_mejoras(estado: dict, pct: dict) -> dict:
    """Suma a la ficha los porcentajes que den los Improved Pet Feed.

    `pct` es lo que devuelve mejoras.stats_de_mejora(), o sea {'atk': 24} para
    tres piensos del 8%. Se devuelve una copia con los numeros ya subidos,
    para mandarla en el 0x0065 sin tocar la ficha guardada.
    """
    out = dict(estado)
    for stat, p in (pct or {}).items():
        if stat in OFF and stat not in ('nombre', 'entidad', 'tipo'):
            out[stat] = int(round(out.get(stat, 0) * (1 + p / 100.0)))
    return out


# Las ordenes que se le dan, del c2s 0x003E. El servidor real contesta con un
# 0x001D del JUGADOR -- no de la mascota -- con el tipo 0x11 y el modo dentro.
# Medidos 0, 1, 2 y 4 en la captura; los nombres son lo que hacen segun se
# vio, y el 4 no se llego a identificar.
ORDEN_QUIETA = 0
ORDEN_SEGUIR = 1
ORDEN_ATACAR = 2
KIND_ORDEN = 0x11


def paquete_orden(entidad_jugador: int, modo: int) -> bytes:
    """El 0x001D que confirma la orden.

    Medido: "1e010000 01 11 01 0000 0000 0000" para la orden 1 del jugador
    0x11e. Los seis ceros del final van siempre.
    """
    return (struct.pack('<HIBB', 0x001D, entidad_jugador, 1, KIND_ORDEN)
            + struct.pack('<B', modo & 0xFF) + bytes(7))


# ---------------------------------------------------------------------------
# La entrada del inventario, que es distinta de la ficha de arriba.
#
# Una mascota ocupa 231 bytes en la mochila, contra los 86 de un objeto normal
# y los 119 de uno que se equipa. Hasta ahora se le mandaba una de 86 y el
# cliente se cerraba al pasarle el raton por encima: leia una ficha que no
# estaba entera.
#
# El mapa sale de 51 entradas distintas de las capturas, cruzadas contra los
# 0x0065 de nueve mascotas (Battlemaid, Hicalu, Fire Elf, Heady Dragon, Civet
# Guardian, los dos huevos...). Cada campo de abajo cuadro en las 41 entradas
# cuyo 0x0065 tambien estaba en la captura; los que no cuadraron en todas no
# estan aqui.
#
# Lo que la entrada NO lleva: los stats de combate. Ataque, defensa, rigor y
# agilidad solo viajan en el 0x0065, cuando se abre la ventana de la mascota.
# Aqui solo va lo que se ve sin abrirla.
TAM_ENTRADA = 231

OFF_ENTRADA = {
    'hp': 86,
    'exp': 90,
    'exp_max': 98,
    'nombre': 106,      # 12 bytes, no 16 como en el 0x0065
    'hp_max': 119,
    'mp_max': 123,
    'mp': 127,          # el MP actual, que en el 0x0065 no aparecia
    'sprite': 131,      # u16; es el 動態資料1 del item
    'nivel': 133,
    'saciedad': 137,    # u16
    'intimidad': 139,
}
LARGO_NOMBRE = 12
_U16 = ('sprite', 'saciedad')


def entrada(plantilla: bytes, estado: dict) -> bytes:
    """Escribe la parte de mascota sobre una entrada de inventario.

    `plantilla` son los 231 bytes ya rellenos con lo comun a cualquier objeto
    (instancia, item, dueño, casilla, cantidad). Aqui solo se añade lo que es
    de la mascota.
    """
    e = bytearray(plantilla)
    if len(e) != TAM_ENTRADA:
        e = (e + bytes(TAM_ENTRADA))[:TAM_ENTRADA]
    for campo, off in OFF_ENTRADA.items():
        v = estado.get(campo)
        if v is None:
            continue
        if campo == 'nombre':
            # Los 12 bytes se llenan ENTEROS cuando hace falta: "Civet
            # Guardi" y "Dragon's Egg" ocupan los doce y no llevan el cero
            # final. Reservando sitio para el terminador se perdia la ultima
            # letra en doce de las sesenta y tres entradas capturadas.
            nom = str(v).encode('latin1', 'replace')[:LARGO_NOMBRE]
            e[off:off + LARGO_NOMBRE] = nom + bytes(LARGO_NOMBRE - len(nom))
        elif campo in _U16:
            struct.pack_into('<H', e, off, min(0xFFFF, int(v)))
        else:
            struct.pack_into('<I', e, off, int(v) & 0xFFFFFFFF)
    return bytes(e)


def recien_nacida(nombre: str, sprite: int, nivel: int = 1,
                  hp: int = 127, mp: int = 70) -> dict:
    """Una mascota de ese sprite, con su tipo, nombre y stats de pet.xml.

    El 'tipo' (el 圖號1) es imprescindible: dejandolo en cero el cliente no
    sabe que mascota es y la ventana sale sin nivel y sin dibujo.
    """
    d = ficha_de_sprite(sprite)
    f = {'nombre': d.get('nombre') or nombre, 'sprite': sprite,
         'tipo': d.get('tipo', 0), 'nivel': nivel,
         'hp': hp, 'hp_max': hp, 'mp': mp, 'mp_max': mp,
         'exp': 0, 'exp_max': 0, 'saciedad': 0, 'intimidad': 0}
    # Los stats de combate salen de petattrib. Sin esto la ventana de la
    # mascota sale entera en blanco, que es lo que pasaba: se creia que el
    # cliente los calculaba solo y no lo hace.
    f.update(stats_de(sprite, nivel))
    return f


# ---------------------------------------------------------------------------
# La mascota como criatura del mundo: el s2c 0x0050.
#
# Medido el 29/09/2026 en mundo_022355_871035. Sacando y guardando la misma
# Battlemaid tres veces solo cambiaron ocho bytes de los 103: la entidad, las
# dos coordenadas y el trozo del nombre que se acorto al renombrarla. Todo lo
# demas es fijo y va en la plantilla.
#
# No confundirlo con el 0x0008, que es el spawn de un NPC y tiene otro mapa:
# alli el sprite esta en el 34 y aqui en el 45.
TAM_MUNDO = 103

OFF_MUNDO = {
    'entidad': 0,
    'x': 8,
    'y': 12,
    'nombre': 16,       # 13 bytes
    'tipo': 34,
    'sprite': 45,       # u16
    'instancia': 62,    # la del item en la mochila, repetida en el 66
    'entidad2': 70,     # la suya otra vez
    'dueno': 74,        # LA ENTIDAD DEL JUGADOR
    'dueno_nombre': 78,  # 8 bytes
}
LARGO_NOMBRE_MUNDO = 13
LARGO_DUENO = 8


def entidad_mundo(plantilla: bytes, estado: dict) -> bytes:
    """El 0x0050 que pinta la mascota al lado del jugador."""
    b = bytearray(plantilla)
    if len(b) != TAM_MUNDO:
        b = (b + bytes(TAM_MUNDO))[:TAM_MUNDO]
    for campo, off in OFF_MUNDO.items():
        v = estado.get(campo)
        if v is None:
            continue
        if campo in ('nombre', 'dueno_nombre'):
            largo = (LARGO_NOMBRE_MUNDO if campo == 'nombre'
                     else LARGO_DUENO)
            t = str(v).encode('latin1', 'replace')[:largo]
            b[off:off + largo] = t + bytes(largo - len(t))
        elif campo == 'sprite':
            struct.pack_into('<H', b, off, int(v) & 0xFFFF)
        else:
            struct.pack_into('<I', b, off, int(v) & 0xFFFFFFFF)
    # La instancia y la entidad van repetidas cuatro bytes mas alla.
    if estado.get('instancia') is not None:
        struct.pack_into('<I', b, 66, int(estado['instancia']) & 0xFFFFFFFF)
    if estado.get('entidad') is not None:
        struct.pack_into('<I', b, 70, int(estado['entidad']) & 0xFFFFFFFF)
    return struct.pack('<H', 0x0050) + bytes(b)


# Renombrar: c2s 0x003D, y el cuerpo es el nombre y nada mas. Se vio poner
# "Battlemaids" y luego "Battle"; el servidor contesta remandando la entrada
# del inventario, que es donde vive el nombre. Mientras no se le ponga uno,
# el nombre es el de su clase, que es el 基本名稱 del item.
def nombre_pedido(cuerpo: bytes) -> str:
    """Saca el nombre del c2s 0x003D."""
    return cuerpo.split(b'\0')[0].decode('latin1', 'replace').strip()


# ---------------------------------------------------------------------------
# Los stats de combate. NO los calcula el cliente: viajan en el 0x0065 y si
# van a cero la ventana de la mascota sale entera en blanco.
#
# Salen de la tabla petattrib, que va por (tipo de mascota, nivel). El enlace
# item -> tipo NO esta en el cliente: no hay ninguna columna en item.xml ni
# ninguna otra tabla que lo lleve. Asi que aqui va lo MEDIDO, por sprite:
#
#   3049  Fire Elf Egg   輔助回復型   los ocho numeros de la ventana cuadran
#                                     con la wiki: 100/105 de vida y mana,
#                                     28 de ataque, 10 de defensa, 18 y 19
#                                     de magia, 15 de rigor y 15 de agilidad
#   3200  Battlemaid     強攻型       nivel 217: 16057 de vida, 7772 de mana
#
# Lo que no este aqui cae en el tipo medio, que es lo menos daniño.
#
# OJO con dos nombres: 'accuracy' de la tabla es el RIGOR de la ventana, y
# 'atk_avg' es el ataque. Se comprobo con el Elf Egg, donde los ocho valores
# coinciden uno a uno.
# La tabla de mascotas sale de pet.xml de los paks, volcada por
# tools/pets_de_pet_xml.py. Antes habia aqui dos sprites a mano y todo lo
# demas caia en un tipo por defecto, que es por lo que las mascotas salian
# con los stats de otra. Ahora son las 1751 del cliente.
#
# De cada una interesa:
#   tipo     el 圖號1, que va en el +4 del 0x0065. DEJANDOLO EN CERO el
#            cliente no sabe que mascota es y la ventana sale sin nivel y
#            sin dibujo
#   clase    el 寵物類型, con el que se buscan sus stats en petattrib
#   rama1/2  las dos evoluciones posibles: la 1 es la "mean" del arbol de
#            la wiki y la 2 la "nice"
#   crianza  el 條件成長值 que hace falta para pasar de etapa
TABLA = pathlib.Path(__file__).parent / 'plantillas' / 'mascotas.json'
TIPO_POR_DEFECTO = '平均型'

# Sta y Soul salen fijos en todas las fichas vistas y no estan en petattrib.
STA_BASE = 30
SOUL_BASE = 60

_MASC = {}
_TABLA = {}


def _tabla():
    """{sprite: {...}} de pet.xml, leido una sola vez."""
    if _MASC:
        return _MASC
    try:
        for k, v in json.loads(TABLA.read_text(encoding='utf-8')).items():
            _MASC[int(k)] = v
    except Exception:
        pass
    return _MASC


def ficha_de_sprite(sprite) -> dict:
    return _tabla().get(int(sprite or 0)) or {}


def _petattrib():
    """{(clase, nivel): fila} leido de una vez."""
    if _TABLA:
        return _TABLA
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return _TABLA
    try:
        con = sqlite3.connect(db)
        for f in con.execute('select 寵物類型,level,hp,mp,atk_avg,def,matk,'
                             'mdef,accuracy,agility from petattrib'):
            try:
                _TABLA[(f[0], int(f[1]))] = {
                    'hp_max': int(f[2]), 'mp_max': int(f[3]),
                    'atk': int(f[4]), 'dfs': int(f[5]), 'matk': int(f[6]),
                    'mdef': int(f[7]), 'rigor': int(f[8]),
                    'agilidad': int(f[9])}
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return _TABLA


def tipo_de(sprite) -> str:
    """La clase de petattrib de esa mascota, segun pet.xml."""
    return ficha_de_sprite(sprite).get('clase') or TIPO_POR_DEFECTO


def stats_de(sprite, nivel: int) -> dict:
    """Los stats que le tocan a esa mascota a ese nivel."""
    t = _petattrib().get((tipo_de(sprite), max(1, int(nivel or 1))))
    if not t:
        return {}
    d = dict(t)
    d['hp'] = d['hp_max']
    d['mp'] = d['mp_max']
    return d


# ---------------------------------------------------------------------------
# EVOLUCION. Una mascota no "sube de forma": cambia de tipo en petattrib, y
# con el tipo le cambian los ocho stats de golpe. Eso se comprobo cruzando
# el arbol del Elf Egg de la wiki contra la tabla, nivel a nivel:
#
#   nivel 15  Naughty Elf  408/304  atk 99  dfs 111  ->  魔攻型
#             Flying Guy   375/304  atk 95  dfs  85  ->  輔助回復型
#   nivel 55  Night Queen 1696/1204 atk 402 dfs 503  ->  魔攻型
#             Night Devil 1833/1066 atk 416 dfs 503  ->  遠程攻擊型
#             Elf Queen   1558/1204 atk 388 dfs 458  ->  輔助回復型
#
# Los cinco cuadran exactos, asi que la rama ES el tipo.
#
# Cuando evoluciona lo dicen los certificados: el Medium Blood Certificate a
# nivel 35 y el Advanced a nivel 55. Hacia DONDE lo dice el trato acumulado
# que se le haya dado con los Teach Pet -- strictly, softly o fondly -- que
# el juego suma por dentro. Un huevo de fusion (Fusion Pet Egg) no pasa por
# esto; las de monstruo si.
#
# LO QUE FALTA: cuanto suma cada Teach Pet y donde vive ese contador. Sin eso
# no se puede decidir la rama sola, y hay que capturarlo.
NIVEL_MEDIO = 35
NIVEL_AVANZADO = 55
NIVEL_PRIMERA_RAMA = 15

TRATOS = ('strictly', 'softly', 'fondly')

# rama -> tipo de petattrib, para el arbol del Elf Egg.
# Las ramas ya no se escriben a mano: cada mascota de pet.xml lleva las
# suyas en 升階變化1 y 升階變化2. La 1 es la "mean" del arbol de la wiki y la
# 2 la "nice". El Elf Egg (3181) va a Naughty Elf (3183) o a Flying Guy
# (3182), y de ahi a Fiend Lily / Incubus y a Night Queen / Night Devil.
RAMA_MEAN = 'rama1'
RAMA_NICE = 'rama2'


def ramas_de(sprite):
    """Las dos evoluciones posibles: (mean, nice). None donde no haya."""
    d = ficha_de_sprite(sprite)
    return (d.get('rama1'), d.get('rama2'))


def crianza_necesaria(sprite):
    """El 條件成長值 que pide esa etapa para pasar a la siguiente."""
    return ficha_de_sprite(sprite).get('crianza')


# Las cinco etapas, y cuales evolucionan. Contado sobre las 1751:
#
#   原型  147   huevo          2 ramas
#   初階  256   primera forma  2 ramas
#   中階  475   forma media    2 ramas
#   高階  585   forma final    SIN ramas -- aqui acaba la cadena normal
#   頂階  288   UNICA          SIN ramas -- las fusion y las de monstruo,
#                              que no evolucionan nunca. La Battlemaid es
#                              una de estas.
#
# O sea que una mascota normal hace tres evoluciones (huevo -> 初階 -> 中階
# -> 高階) eligiendo rama cada vez, y una 頂階 nace ya en su forma final.
ETAPA_UNICA = '頂階'
ETAPA_FINAL = '高階'


def evoluciona(sprite) -> bool:
    """Si esa mascota tiene a donde evolucionar."""
    return any(ramas_de(sprite))


def es_unica(sprite) -> bool:
    """Las 頂階: fusion y monstruo, que no pasan por ninguna evolucion."""
    return ficha_de_sprite(sprite).get('etapa') == ETAPA_UNICA


def evolucionar(ficha: dict, rama: str) -> dict:
    """Pasa la mascota a una de sus dos ramas.

    `rama` es 'mean' o 'nice'. Cambia el sprite, y con el cambian solos el
    nombre, el tipo y la clase de petattrib, porque todo eso sale de la
    tabla. El nivel y la experiencia no se tocan.
    """
    mean, nice = ramas_de(ficha.get('sprite'))
    destino = mean if rama == 'mean' else nice
    if not destino:
        return ficha
    ficha['sprite'] = int(destino)
    d = ficha_de_sprite(destino)
    ficha['tipo'] = d.get('tipo', 0)
    if d.get('nombre'):
        ficha['nombre'] = d['nombre']
    ficha.update(stats_de(ficha['sprite'], ficha.get('nivel', 1)))
    return ficha


# Quitar del mundo. Medido: al guardar la mascota el servidor manda un
# s2c 0x0007 de cinco bytes con SU entidad. Es el mismo mensaje que se usa
# para cualquier criatura que desaparece -- de las seis entidades que lo
# recibieron en la captura, tres habian salido antes con un 0x0008.
# Sin esto la mascota se quedaba pegada en pantalla y no habia forma de
# guardarla.
def quitar(entidad: int, modo: int = 1) -> bytes:
    return struct.pack('<HIB', 0x0007, int(entidad) & 0xFFFFFFFF, modo & 0xFF)


# Y el enlace jugador -> mascota, que va en un 0x001D del JUGADOR con el
# tipo 0x2a y la entidad de la mascota dentro:
#     "1e010000 01 2a c4501000 0000 0000"
KIND_MASCOTA = 0x2A


def enlazar(entidad_jugador: int, entidad_mascota: int) -> bytes:
    return (struct.pack('<HIBB', 0x001D, int(entidad_jugador) & 0xFFFFFFFF,
                        1, KIND_MASCOTA)
            + struct.pack('<I', int(entidad_mascota) & 0xFFFFFFFF)
            + bytes(4))


# ---------------------------------------------------------------------------
# CRIANZA. De petaspect.xml, volcado a plantillas/crianza.json.
#
# El juego va sacando escenas ("se pone a dar vueltas alrededor de su dueño")
# con tres opciones cada una, y cada opcion suma un valor que va de -3 a +3.
# El texto de la primera lo dice sin rodeos: "las acciones del dueño afectaran
# la direccion de crecimiento del pet". Ese acumulado es lo que decide a cual
# de las dos ramas evoluciona.
#
# El umbral es el 條件成長值 de cada mascota, que en todas las vistas vale 10.
#
# CONFIRMADO el 29/09/2026 con tres mascotas y nueve evoluciones seguidas en
# el proxy, y pet.xml acerto las nueve:
#
#   3085 Elf Egg -> 3087 Naughty Elf -> 3091 Fiend Lily -> 3096 Night Queen
#        las tres por la RAMA 1, y esa es la rama "mean" del arbol de la wiki.
#        Su rama 2 son Flying Guy, Incubus y Succubus, que es la "nice".
#   15828 -> 15830 -> 15834 -> 15839, las tres por la rama 2.
#   13590 -> 13591 (rama 1) -> 13594 (rama 2) -> 13598 (rama 1), alternando.
#
# O sea: 升階變化1 es la mean y 升階變化2 la nice, y la rama se ELIGE -- el
# porcino alterna entre las dos dentro de la misma cadena.
#
# Y OJO CON EL UMBRAL: ese huevo tenia 條件成長值=2, no 10. Varia por mascota,
# asi que hay que leerlo de la tabla y no dar por bueno ningun numero fijo.
#
# Lo que sigue sin medir es la rama 1: hace falta criar una en negativo.
#
# Aparte, los NOMBRES de pet.xml no siempre son los que enseña el servidor:
# el 15828 sale ahi como "Guardian Egg" y el juego lo llamaba "Oasis Egg", y
# el 15830 es "Blue Egg" contra "Violet Pixie". Los sprites y las ramas si
# cuadran, que es lo que importa; los nombres cambian entre versiones.
CRIANZA = pathlib.Path(__file__).parent / 'plantillas' / 'crianza.json'
UMBRAL_CRIANZA = 10

_CRIA = {}


def situaciones():
    """{numero: {'tipo', 'texto', 'opciones': [{'texto','valor'}]}}."""
    if _CRIA:
        return _CRIA
    try:
        _CRIA.update(json.loads(CRIANZA.read_text(encoding='utf-8')))
    except Exception:
        pass
    return _CRIA


def criar(ficha: dict, valor: int) -> int:
    """Suma a la mascota el valor de la opcion elegida y lo devuelve."""
    ficha['crianza'] = int(ficha.get('crianza', 0)) + int(valor)
    return ficha['crianza']


def rama_por_crianza(ficha: dict):
    """Que rama le toca segun lo criada que este.

    El umbral es el 條件成長值 de la propia mascota, y NO es siempre 10: en
    lo medido salieron 2, 0, 6 y hasta -4. Por eso es una comparacion suelta
    contra ese numero y no un "mas o menos N".

    Con la crianza por encima del umbral va a la rama 2 y por debajo a la 1.
    Esto encaja con lo capturado -- un huevo criado en positivo (intimidad
    41) fue a la rama 2 -- pero las seis evoluciones que se vieron no traen
    el contador de crianza a la vista, asi que el sentido de la comparacion
    es lo unico de aqui que no esta comprobado del todo.
    """
    tope = crianza_necesaria(ficha.get('sprite'))
    if tope is None:
        tope = UMBRAL_CRIANZA
    v = int(ficha.get('crianza', 0))
    return RAMA_NICE_NOMBRE if v >= int(tope) else RAMA_MEAN_NOMBRE


RAMA_MEAN_NOMBRE = 'mean'
RAMA_NICE_NOMBRE = 'nice'


# ---------------------------------------------------------------------------
# EXPERIENCIA. La que hace falta para pasar del nivel N al N+1 es
#
#     exp_max = redondear(36 * N^1.5)
#
# Sale de 23 fichas capturadas, de nivel 1 a 246, y da los 23 numeros
# EXACTOS, sin un solo punto de error:
#
#     nivel 1 -> 36      nivel 66 -> 19303     nivel 150 -> 66136
#     nivel 2 -> 102     nivel 102 -> 37085    nivel 246 -> 138901
#
# Ojo: NO es la tabla 寵物A/B/C/D de level.xml. Esa pide billones por nivel y
# no cuadra con ninguna ficha; se probo y se descarto. Y aunque pet.xml diga
# que cada mascota usa una tabla distinta, todas las capturadas comparten el
# mismo exp_max a igual nivel, asi que la curva es una sola.
FACTOR_EXP = 36


def exp_para_subir(nivel: int) -> int:
    """La experiencia que pide ese nivel para pasar al siguiente."""
    n = max(1, int(nivel or 1))
    return int(round(FACTOR_EXP * n * (n ** 0.5)))


def nivel_maximo(sprite) -> int:
    """El nivel mas alto que petattrib tiene para la clase de esa mascota.

    Sin esto, un vale de 100 millones la mandaba al nivel 545, que no existe
    en la tabla: stats_de() devolvia vacio y la mascota se quedaba con los
    stats de nivel 1 pese a marcar nivel 545.
    """
    clase = tipo_de(sprite)
    niveles = [n for (c, n) in _petattrib() if c == clase]
    return max(niveles) if niveles else 1


def multiplicador_exp(ficha: dict, ahora=None) -> float:
    """Cuanto multiplica la experiencia la Double EXP Card que este puesta.

    La carta (item 3460) no da experiencia: pone el hechizo 1866, que dura
    1800 segundos y lleva 經驗加倍=100, o sea un +100%. De ahi salen los
    "30 M." de su nombre y el doble de su descripcion.
    """
    import time
    b = ficha.get('buff_exp')
    if not b:
        return 1.0
    ahora = time.time() if ahora is None else ahora
    if ahora >= b.get('hasta', 0):
        ficha.pop('buff_exp', None)
        return 1.0
    return 1.0 + (b.get('pct', 0) / 100.0)


def poner_buff_exp(ficha: dict, segundos: int, pct: int, ahora=None) -> dict:
    """Arranca el contador de la carta de experiencia doble."""
    import time
    ahora = time.time() if ahora is None else ahora
    ficha['buff_exp'] = {'hasta': ahora + max(0, int(segundos)),
                         'pct': int(pct)}
    return ficha['buff_exp']


def dar_exp(ficha: dict, cantidad: int, ahora=None) -> int:
    """Suma experiencia y sube de nivel lo que haga falta.

    Devuelve cuantos niveles subio. Los stats se recalculan con el nivel
    nuevo, que es como los da el juego: no se guardan sueltos.
    """
    subidos = 0
    cantidad = int(max(0, int(cantidad)) * multiplicador_exp(ficha, ahora))
    ficha['exp'] = int(ficha.get('exp', 0)) + cantidad
    maximo = nivel_maximo(ficha.get('sprite'))
    while True:
        if int(ficha.get('nivel', 1)) >= maximo:
            # Al tope: la experiencia de sobra no se guarda, igual que la
            # barra llena que enseñaba la Battlemaid de nivel 246.
            ficha['exp'] = 0
            break
        tope = exp_para_subir(ficha.get('nivel', 1))
        if ficha['exp'] < tope:
            break
        ficha['exp'] -= tope
        ficha['nivel'] = int(ficha.get('nivel', 1)) + 1
        subidos += 1
    ficha['exp_max'] = exp_para_subir(ficha.get('nivel', 1))
    if subidos:
        ficha.update(stats_de(ficha.get('sprite'), ficha['nivel']))
    return subidos


# ---------------------------------------------------------------------------
# LA RESPUESTA AL CUADRO DE CRIANZA. Va por el MISMO c2s 0x003E que las
# ordenes, y lo que las separa es el valor:
#
#     0, 1, 2   ordenes: quieta, seguir, atacar. El servidor contesta con un
#               0x001D del jugador con el tipo 0x11.
#     4, 5, 6   las TRES OPCIONES del cuadro, en el orden en que salen. El
#               servidor contesta con un 0x000A, que es la estrellita que
#               aparece sobre la mascota.
#
# Medido el 29/09/2026: en una captura casi vacia se respondio al cuadro dos
# veces y aparecieron un 6 y un 5, uno por respuesta. En el total de las
# capturas salen 3, 20 y 3 para las ordenes y 24, 18 y 8 para las opciones.
#
# El texto del cuadro NO viaja: lo saca el cliente de su petaspect.xml. Se
# comprobo palabra por palabra con la escena 5, que es la que salio en
# pantalla ("put it's head out when its owner wasn't watching it") con sus
# valores 0, -1 y +1 en ese orden.
PRIMERA_OPCION_CRIANZA = 4
EFECTO_CRIANZA = 0x029A


def es_respuesta_crianza(valor: int) -> bool:
    return PRIMERA_OPCION_CRIANZA <= int(valor) <= PRIMERA_OPCION_CRIANZA + 2


def opcion_de(valor: int) -> int:
    """De 4, 5 o 6 al indice 0, 1 o 2 de la escena."""
    return int(valor) - PRIMERA_OPCION_CRIANZA


def responder_crianza(ficha: dict, escena, valor: int):
    """Aplica la opcion elegida y devuelve (sumado, total).

    `escena` es una de las de situaciones(). Si no se sabe cual salio -- el
    servidor no la manda, la elige el cliente -- se suma 0 y solo se apunta
    la respuesta.
    """
    i = opcion_de(valor)
    suma = 0
    if escena and 0 <= i < len(escena.get('opciones') or []):
        suma = int(escena['opciones'][i].get('valor') or 0)
    return suma, criar(ficha, suma)


def efecto(entidad_origen: int, entidad_destino: int,
           cual: int = EFECTO_CRIANZA) -> bytes:
    """El s2c 0x000A: la estrellita sobre la mascota al responder.

    Medido: "00511000 e8780f00 0100 9a02" -- dos entidades, un uno y el
    numero del efecto.
    """
    return (struct.pack('<HII', 0x000A, int(entidad_origen) & 0xFFFFFFFF,
                        int(entidad_destino) & 0xFFFFFFFF)
            + struct.pack('<HH', 1, int(cual) & 0xFFFF))
