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
    """Una mascota acabada de salir, como las que dieron los huevos.

    Los 127 de vida y 70 de mana son los del nivel 1 en petattrib, y son los
    que traian el FireElf Egg y el Dragon's Egg recien abiertos.
    """
    return {'nombre': nombre, 'sprite': sprite, 'nivel': nivel,
            'hp': hp, 'hp_max': hp, 'mp': mp, 'mp_max': mp,
            'exp': 0, 'exp_max': 0, 'saciedad': 0, 'intimidad': 0}


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
