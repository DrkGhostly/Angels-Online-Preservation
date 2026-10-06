"""
Dialogo con los NPC.

Protocolo, establecido con una captura del servidor privado que lleva marca de
tiempo en los dos sentidos (logs/proxy/*_orden.jsonl, tools/correlacionar.py):

    C -> S  0x0005  [LE32 entity_id][LE16 0]   clic en el NPC
    C -> S  0x0007  [U8 direccion]             el personaje se gira hacia el
    S -> C  0x0012  una linea de dialogo
    C -> S  0x000B  [U8 01]                    "siguiente"
    S -> C  0x0012  la linea siguiente
      ...
    S -> C  0x0012  nueve ceros                se acabo, cerrar el cuadro

Forma de la linea (0x0012):

    +0  LE32  id del texto      el texto en si vive en el cliente
    +4  LE16  valor             3 para Raphael, 2 para el Tutor, 52 para Aide
    +6  U8    cuantas cadenas vienen despues
    +7  U8    cuantas opciones de menu vienen despues
    +8  U8    0 SIEMPRE, lleve cadenas u opciones
    +9        primero las cadenas (terminadas en NUL), despues las opciones
              (LE32 con el id de dialogo de cada una)

Comprobado con las dos formas que aparecen en la captura: la primera linea de
Angel Raphael trae +6=2 y +7=0, y sus dos cadenas son "1" y el nombre del
jugador; la del Interface Tutor trae +6=0 y +7=2, y detras van los ids 5241 y
5242, que son las dos opciones que ofrece.

El texto NO viaja por la red: el servidor manda el id y el cliente lo busca.
Por eso alcanza con reproducir los ids para que salgan los dialogos.

De donde salen los ids: de la captura, no inventados. Son los del tutorial de
Guide Palace, iguales para cualquier personaje nuevo -- no son progreso de
nadie. Lo unico que se sustituye es el nombre del jugador, que el servidor
manda como parametro en la primera linea de Angel Raphael.
"""
import json
import pathlib
import struct

PLANTILLA = pathlib.Path(__file__).parent / 'plantillas' / 'dialogos_guide_palace.json'
FIN = bytes(9)                      # nueve ceros = cerrar el cuadro
_GUION = None


def _cargar():
    global _GUION
    if _GUION is None:
        crudo = json.loads(PLANTILLA.read_text(encoding='utf-8'))
        _GUION = {int(k): [bytes.fromhex(x) for x in v] for k, v in crudo.items()}
    return _GUION


def _con_nombre(linea: bytes, nombre: str) -> bytes:
    """Cambia el nombre del personaje grabado por el de quien esta jugando.

    Solo toca lineas que traigan cadenas (+6 > 0). El nombre es la ultima
    cadena de la lista.
    """
    if len(linea) <= 9 or linea[6] == 0:
        return linea
    partes = linea[9:].split(b'\x00')
    if len(partes) < 2:
        return linea
    partes[-2] = nombre.encode('ascii', 'replace')[:33]
    return linea[:9] + b'\x00'.join(partes)


def guion(entity_id: int):
    """Las lineas de dialogo de ese NPC, o None si no se le conoce ninguna."""
    return _cargar().get(entity_id)


def linea(entity_id: int, paso: int, nombre: str) -> bytes:
    """Sub-mensaje 0x0012 con la linea `paso`, o el de cierre si ya no hay."""
    g = guion(entity_id)
    if not g or paso >= len(g):
        return struct.pack('<H', 0x0012) + FIN
    return struct.pack('<H', 0x0012) + _con_nombre(g[paso], nombre)


def linea_de(guion, paso: int, nombre: str) -> bytes:
    """Sub-mensaje 0x0012 con la linea `paso` de ese guion, o el de cierre."""
    if not guion or paso >= len(guion):
        return struct.pack('<H', 0x0012) + FIN
    return struct.pack('<H', 0x0012) + _con_nombre(guion[paso], nombre)


def hay_mas(entity_id: int, paso: int) -> bool:
    g = guion(entity_id)
    return bool(g) and paso < len(g)


# ------------------------------------------------- tutorial por etapas
# El guion del tutorial, medido del servidor privado. Cada tramo es una
# conversacion entera: el jugador habla, avanza con 0x000B y al final llega el
# 0x0012 de ceros. Al terminar un tramo el personaje pasa al siguiente.
#
#   Angel Raphael
#     0  5001..5005  elegir clase
#     1  5006, 5007 (opciones 5008/5009), 5014..5018  da la ropa y ensena a
#                                                     equiparsela
#     2  5021, 5039..5043  confirma y da 10 de oro para el examen
#     3  5047  confirma el examen; despues cambia de mapa
#
#   Angel Aide
#     0  5022 (opciones 5045 comprar / 5046 salir)
#
# El entity_id de los NPC CAMBIA entre sesiones: Raphael fue 19 en unas
# capturas y 16 en otras. Por eso el guion va por nombre y no por numero.
TUTORIAL = pathlib.Path(__file__).parent / 'plantillas' / 'tutorial.json'
NOMBRE_POR_ENTIDAD = {19: 'raphael', 20: 'interface', 21: 'aide'}
_TUT = None


def _tutorial():
    global _TUT
    if _TUT is None:
        crudo = json.loads(TUTORIAL.read_text(encoding='utf-8'))
        _TUT = {k: [[bytes.fromhex(x) for x in tramo] for tramo in v]
                for k, v in crudo.items() if not k.startswith('_')}
    return _TUT


def recargar_tutorial():
    global _TUT
    _TUT = None


def guion_etapa(entity_id: int, etapa: int):
    """El tramo de dialogo que toca, o None si ese NPC ya no tiene mas."""
    nom = NOMBRE_POR_ENTIDAD.get(entity_id)
    if nom is None:
        return None
    tramos = _tutorial().get(nom, [])
    if not tramos:
        return None
    # Pasada la ultima etapa se repite la ultima, que es lo que hace el juego:
    # el NPC sigue contestando algo en vez de quedarse mudo.
    return tramos[min(etapa, len(tramos) - 1)]


def etapas(entity_id: int) -> int:
    nom = NOMBRE_POR_ENTIDAD.get(entity_id)
    return len(_tutorial().get(nom, [])) if nom else 0


# ------------------------------------------- dialogo propio de cada NPC
# Sacado de setting/eng/msg.xml, que trae los 42.036 textos del juego
# indexados por el mismo id que viaja en el 0x0012. Buscando el texto donde
# cada NPC se presenta ("I am X", "I'm X", "my name is X") se le puede dar su
# dialogo sin capturar nada: el texto vive en el cliente y el servidor solo
# manda el numero.
#
# Se llego tarde a esto: se dijo varias veces que los dialogos solo salian de
# capturas, y el jugador insistio en que estaban en los xml. Tenia razon.
DIALOGOS_NPC = pathlib.Path(__file__).parent / 'plantillas' / 'dialogos_npc.json'
_PROPIOS = None


def _propios():
    global _PROPIOS
    if _PROPIOS is None:
        if DIALOGOS_NPC.exists():
            _PROPIOS = json.loads(DIALOGOS_NPC.read_text(encoding='utf-8'))['npcs']
        else:
            _PROPIOS = {}
    return _PROPIOS


_ENTIDADES_NPC = None


def _cargar_npcs():
    """Indexa nombre, sprite y stage de todos los NPCs del juego desde plantillas."""
    global _ENTIDADES_NPC
    if _ENTIDADES_NPC is not None:
        return _ENTIDADES_NPC
    _ENTIDADES_NPC = {}
    plant = pathlib.Path(__file__).parent / 'plantillas'
    for f in plant.glob('*.json'):
        if f.name in ('dialogos_npc.json', 'tutorial.json', 'npc_por_mapa.json', 'lista_totems.json'):
            continue
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(d, dict) and 'spawns' in d:
                for sp in d['spawns']:
                    eid = sp.get('entity_id')
                    if eid and not sp.get('monstruo'):
                        _ENTIDADES_NPC[eid] = {
                            'nombre': sp.get('nombre', ''),
                            'sprite': sp.get('sprite', 0),
                            'stage': d.get('stage', 0),
                        }
        except Exception:
            pass
    f_mapas = plant / 'npc_por_mapa.json'
    if f_mapas.exists():
        try:
            d_mapas = json.loads(f_mapas.read_text(encoding='utf-8')).get('mapas', {})
            for st_str, npcs in d_mapas.items():
                st_val = int(st_str) if st_str.isdigit() else 0
                for idx, n in enumerate(npcs):
                    eid = 900 + idx
                    if eid not in _ENTIDADES_NPC:
                        _ENTIDADES_NPC[eid] = {
                            'nombre': n.get('nombre', ''),
                            'sprite': n.get('sprite', 0),
                            'stage': st_val,
                        }
        except Exception:
            pass
    return _ENTIDADES_NPC


def info_npc(entidad: int):
    """Devuelve dict con nombre, sprite y stage de la entidad, o None si no existe."""
    return _cargar_npcs().get(entidad)


def val_por_entidad(entidad: int, val_defecto: int = 3) -> int:
    """Calcula el ID de retrato val a partir de la entidad."""
    info = info_npc(entidad)
    if info:
        spr = info.get('sprite', 0)
        if 40200 <= spr < 41000:
            return 1000 + (spr - 40200)
        if 40000 <= spr < 50000:
            return spr - 40000
        if spr > 0:
            return spr
    return val_defecto



def armar_linea(mid: int, val: int = 4, opts: list = None, strings: list = None,
                acciones: list = None) -> bytes:
    """Construye un sub-mensaje 0x0012 completo.

    `acciones` son los LE32 que van DESPUES de las opciones, uno por opcion.
    En la captura del Angels' Tutor el 10102 lleva sus dos opciones y detras
    0x0f4272 y 0x0f4391, y el 10124 lleva 0x0f4393 y 0x0f4271. Nunca los
    mandabamos; los dialogos de tienda funcionan sin ellos, pero el del tutor
    los trae y conviene reproducirlos.
    """
    opts = opts or []
    strings = strings or []
    acciones = acciones or []
    cadenas_b = b''.join(s.encode('ascii', 'replace') + b'\x00' for s in strings)
    # El byte de relleno del +8 va SIEMPRE, con opciones o sin ellas. Se
    # llego a quitarlo creyendo que faltaba en las lineas con cadenas, por
    # haber copiado a mano un hex recortado de la captura; con eso todas las
    # lineas quedaban un byte corridas y el cliente se cerraba con un error.
    # Comprobado con las seis lineas del Angels' Tutor: en las seis el byte 8
    # es 0x00.
    hdr = struct.pack('<IHBBB', mid, val, len(strings), len(opts), 0)
    # El orden es opciones, acciones y AL FINAL las cadenas. Comprobado con
    # el 10201 del Aurora Angel, que lleva las dos cosas: cuatro opciones,
    # cuatro acciones y detras "1" y el nombre del jugador. Poniendo las
    # cadenas delante, una linea con las dos quedaba ilegible para el
    # cliente.
    body = (b''.join(struct.pack('<I', o) for o in opts)
            + b''.join(struct.pack('<I', a) for a in acciones)
            + cadenas_b)
    return struct.pack('<H', 0x0012) + hdr + body


# nombre -> (retrato, mensaje tras hablar con Michael, opciones, acciones)
# El Angel que vive en cada ciudad, con su menu propio. Solo esta medido el
# de Breeze Woods; los de las otras tres ciudades haran falta capturarlos.
# El Angel que vive en cada ciudad. Tiene TRES estados, medidos con el de
# Breeze Woods:
#
#   sin registrar (con la mision de registro pendiente)
#       50001, retrato 112, dos cadenas y CINCO opciones; la primera es
#       "I have come here to register!"
#   ya registrado
#       el mismo 50001 pero con CUATRO: desaparece la de registrarse
#   rango alto
#       55803, otro mensaje distinto
#
# El Angel de cada ciudad. LAS CUATRO CIUDADES SON EL MISMO DIALOGO con la
# base cambiada, y eso no es una suposicion: los cuatro bloques estan en
# msg.xml uno al lado del otro y dicen lo mismo palabra por palabra.
#
#   base    ciudad         x0001 bienvenida        x0002 registrarse
#   20000   Aurora City    "...Angel Protector of Aurora City..."
#   30000   Dark City      "...Guard Angel of Dark City..."
#   40000   Iron Castle    "...Guard Angel in Iron Castle..."
#   50000   Breeze Woods   "...Angel Protector of Breeze Woods..."
#
# y dentro de cada bloque: x0002 registrarse, x0003 la mision, x0004 el
# honor, x0005 salir, x0018 volver al Lyceum, x0019 el traslado.
#
# Las quests van igual de ordenadas en quest.xml:
#   registro  127 Aurora  128 Dark City  129 Iron Castle  130 Breeze Woods
#   conocer   133         134            135              136
#   nivel     137         138            139              140
#
# ANTES AQUI SOLO ESTABA BREEZE WOODS (stage 29). En las otras tres ciudades
# el Angel no encontraba entrada y se caia al dialogo de ELEGIR FACCION del
# Graduation Palace: salia con otro texto y otro retrato, la quest de
# registro no se completaba y la opcion de volver al Lyceum no existia.
#
# OJO: los codigos de accion (0x0f42xx) SOLO estan medidos para Breeze
# Woods. Para las otras tres se reutilizan los suyos porque la respuesta se
# despacha por el ID DE OPCION, no por la accion; si alguna vez se captura
# el Angel de otra ciudad, hay que comprobarlos.
_CIUDADES = (
    # stage, base del dialogo, indice para las quests
    (3,  20000, 0),   # Aurora City
    (26, 30000, 1),   # Dark City
    (38, 40000, 2),   # Iron Castle
    (29, 50000, 3),   # Breeze Woods  <- el unico medido
)

ANGEL_DE_CIUDAD = {}
for _st, _b, _i in _CIUDADES:
    ANGEL_DE_CIUDAD[_st] = {
        'sin_registrar': (_b + 1, (_b + 2, _b + 3, _b + 4, _b + 18, _b + 5),
                          (0x0f4258, 0x0f4252, 0x0f4254, 0x0f4260, 0)),
        'registrado': (_b + 1, (_b + 3, _b + 4, _b + 18, _b + 5),
                       (0x0f4252, 0x0f4254, 0x0f425d, 0)),
        'mision_registro': 127 + _i,
        'mision_conocer': 133 + _i,
        'mision_nivel': 137 + _i,
        'opcion_registrar': _b + 2,
        'opcion_lyceum': _b + 18,
        'msg_traslado': _b + 19,
        '_medido': _st == 29,
    }
del _st, _b, _i

# opcion -> stage, para despachar sin saber donde esta el jugador
CIUDAD_POR_OPCION = {}
for _st, _cfg in ANGEL_DE_CIUDAD.items():
    CIUDAD_POR_OPCION[_cfg['opcion_registrar']] = _st
    CIUDAD_POR_OPCION[_cfg['opcion_lyceum']] = _st
del _st, _cfg

ANGELES_FACCION = {
    'Aurora Angel':     (5,  10201, (10207, 10208, 10205, 10206),
                         (0x0f4252, 0x0f4253, 0x0f4254, 0)),
    'Dark City Angel':  (49, 10202, (10209, 10210, 10205, 10206),
                         (0x0f425d, 0x0f425e, 0x0f425f, 0)),
    'IronCastle Angel': (53, 10203, (10211, 10212, 10205, 10206),
                         (0x0f426a, 0x0f426b, 0x0f426c, 0)),
    'BreezeWood Angel': (52, 10204, (10213, 10214, 10205, 10206),
                         (0x0f4276, 0x0f4277, 0x0f4278, 0)),
}


# La linea de Cupid cambia de ciudad en ciudad. Se indexa por ENTIDAD y no
# por stage: la entidad es unica por ciudad y llega siempre, tambien cuando
# quien pregunta no sabe en que mapa esta.
# {entidad: (mensaje, opciones, acciones)}. Lo que no este aqui usa la
# generica, la 5745 con tres opciones.
CUPID_POR_ENTIDAD = {
    123721: (511112, [5746, 5747], [1000071, 1000072]),   # Twinkle Town
    123791: (511763, [5746, 5747], [1000080, 1000081]),   # Specter Village
}


def propio(nombre: str, faccion: str = "Heaven", jugador: str = "",
           visto_michael: bool = False, stage: int = 0,
           registrado: bool = False, entidad: int = 0, val: int = 0):
    """Una linea de dialogo para ese NPC, o None si no se le conoce ninguna."""
    npc_val = val or (val_por_entidad(entidad, 0) if entidad else 0)

    # --- Busy Market (region de Warring Realm) ---
    # Medido en mundo_131157_254492_orden.jsonl, seis clics. Misma forma
    # que Yatiss y Chilly: banco, tecnico que repara, mercader con dos
    # tiendas y los dos investigadores. Tampoco hay vendedores de productor.
    #
    # Por entidad: esta es la CUARTA pareja de Spell/Skill Researcher.
    if entidad == 123988:   # Bank Staff
        return [armar_linea(515831, npc_val or 1526, [515832, 515833],
                            acciones=[1000016, 1000020])[2:]]
    if entidad == 123991:   # Market Technician -- el reparador
        return [armar_linea(515843, npc_val or 1387, [515844, 515834],
                            acciones=[1000023, 0])[2:]]
    if entidad == 123993:   # Market Merchant
        return [armar_linea(515849, npc_val or 1063, [515850, 515851],
                            acciones=[1000026, 0])[2:]]
    if entidad == 123987:   # Spell Researcher
        return [armar_linea(515845, npc_val or 1527, [515846, 515851],
                            acciones=[1000024, 0])[2:]]
    if entidad == 123992:   # Skill Researcher
        return [armar_linea(515847, npc_val or 115, [515848, 515834],
                            acciones=[1000025, 0])[2:]]
    if entidad == 123989:   # Athena
        return [armar_linea(153805, npc_val or 1515, [])[2:]]

    # --- Chilly Village (region de Celestia) / los Elf ---
    # Medido en mundo_130629_352397_orden.jsonl, cinco clics. Calcado a
    # Yatiss: banco con respuesta de cinco lineas, un tecnico que repara,
    # mercader con dos tiendas y los dos investigadores. Tampoco hay
    # vendedores de productor.
    #
    # Por entidad, que esta es la TERCERA pareja de Spell/Skill Researcher
    # del juego -- las otras dos estan en Desolate Sea.
    if entidad == 123967:   # Banker Elf
        return [armar_linea(515188, npc_val or 1247, [515189, 515190],
                            acciones=[1000009, 1000010])[2:]]
    if entidad == 123968:   # Technician Elf -- el reparador
        return [armar_linea(515200, npc_val or 1292, [515201, 515191],
                            acciones=[1000016, 0])[2:]]
    if entidad == 123969:   # Merchant Elf
        return [armar_linea(515206, npc_val or 34, [515207, 515208],
                            acciones=[1000019, 0])[2:]]
    if entidad == 123971:   # Spell Researcher
        return [armar_linea(515202, npc_val or 1306, [515203, 515208],
                            acciones=[1000017, 0])[2:]]
    if entidad == 123970:   # Skill Researcher
        return [armar_linea(515204, npc_val or 1307, [515205, 515208],
                            acciones=[1000018, 0])[2:]]

    # --- Desolate Sea / Yatiss ---
    # Medido en mundo_125556_957230_orden.jsonl, ocho clics. Aqui NO hay
    # vendedores de productor: ni Smith ni Master de recetas. Lo que hay es
    # banco, dos investigadores, mercader y un tecnico que es el reparador.
    #
    # Va TODO por entidad y no por nombre porque 'Spell Researcher' y
    # 'Skill Researcher' ya existen en Atlantis Blue Ocean con otras lineas
    # y otras tiendas (89 y 90); por nombre ganaria Atlantis.
    if entidad == 123912:   # Yatiss Banker
        return [armar_linea(514636, npc_val or 187, [514637, 514638, 514639],
                            acciones=[1000055, 1000056, 0])[2:]]
    if entidad == 123910:   # Spell Researcher
        return [armar_linea(514650, npc_val or 186, [514651, 514656],
                            acciones=[1000062, 0])[2:]]
    if entidad == 123911:   # Skill Researcher
        return [armar_linea(514652, npc_val or 186, [514653, 514656],
                            acciones=[1000063, 0])[2:]]
    if entidad == 123913:   # Yatiss Merchant
        return [armar_linea(514654, npc_val or 183, [514655, 514656],
                            acciones=[1000065, 0])[2:]]
    if entidad == 123914:   # Yatiss Technician -- el reparador
        return [armar_linea(514648, npc_val or 181, [514649, 514639],
                            acciones=[1000064, 0])[2:]]
    if entidad == 123908:   # Manager Pete
        return [armar_linea(150101, npc_val or 1466, [150102, 150103],
                            acciones=[1000041, 0])[2:]]
    if entidad == 123916:   # Pierre
        return [armar_linea(150504, npc_val or 1463, [])[2:]]
    if entidad == 123932:   # Biologist Boris
        return [armar_linea(150804, npc_val or 1496, [])[2:]]

    # Prioridad por id de entidad exacto de NPC de ciudad
    # --- Aurora City (Stage 3) ---
    if entidad == 121625:  # Ride Seller (Horses/Steeds, Magic Donkey)
        return [armar_linea(5189, npc_val or 66, [5262, 5190, 5191])[2:]]
    if entidad == 121654:  # Ride Seller C (Top Steeds, Top Donkey)
        return [armar_linea(5189, npc_val or 10, [5262, 5190, 5191])[2:]]
    if entidad == 121631:  # Repair Expert
        return [armar_linea(5226, npc_val or 3, [5227, 5191])[2:]]
    if entidad == 121681:  # Healer
        return [armar_linea(5775, npc_val or 10, [5190, 5191])[2:]]

    # --- Breeze Woods (Stage 29) ---
    if entidad == 121934:  # Ride Seller (Nightwolf, Chicken, Pig Dodo)
        return [armar_linea(5224, npc_val or 92, [5262, 5190, 5191])[2:]]
    if entidad == 121927:  # Ride Seller C (Top Nightwolf, Top Chicken)
        return [armar_linea(5224, npc_val or 147, [5262, 5190, 5191])[2:]]
    if entidad == 121958:  # Repair Expert
        return [armar_linea(5233, npc_val or 33, [5227, 5191])[2:]]
    if entidad == 121959:  # Healer
        return [armar_linea(5775, npc_val or 33, [5190, 5191])[2:]]

    # --- Iron Castle (Stage 38) ---
    if entidad == 122099:  # Ride Seller (Boars, Gerbil)
        return [armar_linea(5202, npc_val or 38, [5262, 5190, 5191])[2:]]
    if entidad == 122138:  # Ride Seller C (Top Boars, Top Gerbil)
        return [armar_linea(5202, npc_val or 158, [5262, 5190, 5191])[2:]]
    if entidad == 122098:  # Technician (Repair)
        return [armar_linea(5229, npc_val or 38, [5227, 5191])[2:]]
    if entidad == 122089:  # Healer
        return [armar_linea(5775, npc_val or 74, [5190, 5191])[2:]]

    # --- Dark City (Stage 26) ---
    if entidad == 121853:  # Ride Seller (Lizards, Evil Cat)
        return [armar_linea(5213, npc_val or 17, [5262, 5190, 5191])[2:]]
    if entidad == 121889:  # Ride Seller C (Top Lizards, Top Evil Cat)
        return [armar_linea(5213, npc_val or 80, [5262, 5190, 5191])[2:]]
    if entidad == 121871:  # Repair Slave
        return [armar_linea(5231, npc_val or 19, [5227, 5191])[2:]]
    if entidad == 121883:  # Healer
        return [armar_linea(5775, npc_val or 107, [5190, 5191])[2:]]

    # --- Secondary Towns Repair NPCs ---
    if entidad == 121715:  # Cherry Village Repair Expert
        return [armar_linea(5226, npc_val or 67, [5227, 5191])[2:]]
    if entidad == 121829:  # Mysterious Garden Repair Expert
        return [armar_linea(5233, npc_val or 33, [5227, 5191])[2:]]
    if entidad == 122060:  # Memory Cave Repair Slave
        return [armar_linea(5231, npc_val or 137, [5227, 5191])[2:]]
    if entidad == 122079:  # Gebuer Vale Technician
        return [armar_linea(5229, npc_val or 38, [5227, 5191])[2:]]

    if nombre == 'Director Wolay':
        if faccion in ("Heaven", "Neutral", "Neutrally", "Graduated"):
            return [armar_linea(10004, 49, [])[2:]]
        else:
            return [armar_linea(5079, 49, [5080, 5081])[2:]]
    if 'Repair Angel' in nombre:
        return [armar_linea(5100, 4, [5101, 12105])[2:]]
    if 'Cupid' in nombre:
        # CUPID TIENE SU PROPIA LINEA EN CADA CIUDAD. La generica es la
        # 5745 con tres opciones, medida en Angelic Cave; en Twinkle Town
        # usa la 511112 con solo dos. Se mira el stage antes de caer en la
        # generica.
        propia = CUPID_POR_ENTIDAD.get(int(entidad or 0))
        if propia:
            mid, ops, acc = propia
            return [armar_linea(mid, 6, ops, acciones=acc)[2:]]
        # Las acciones salieron de la captura de Angelic Cave del 28/09/2026.
        # Antes se mandaba la linea sin ellas y el cliente la aceptaba igual,
        # pero el servidor real las manda y ahora la linea sale identica.
        return [armar_linea(5745, 6, [5746, 5747, 5748],
                            acciones=[1000029, 1000030, 0])[2:]]
    # --- Graduation Palace -------------------------------------------
    # Los cuatro Angeles de faccion tienen DOS dialogos, medidos en la
    # captura del 22/09:
    #   antes de hablar con Michael  -> 10242 para los cuatro, cambiando
    #                                   solo el retrato, con las dos cadenas
    #   despues                      -> el suyo, con cuatro opciones
    # El retrato y el mensaje de cada uno:
    #   Aurora 5/10201, Dark City 49/10202, IronCastle 53/10203,
    #   BreezeWood 52/10204
    # Las dos primeras opciones de cada uno son "hablame de la ciudad" y
    # "hablame del totem"; las dos ultimas, 10205 (unirse) y 10206 (salir),
    # son iguales para los cuatro.
    # El Angel de una ciudad NO es el del Graduation Palace: tiene su propio
    # dialogo. Medido con el BreezeWood Angel de Breeze Woods: msg 55803,
    # retrato 112, cuatro opciones 20003, 20004, 20018 y 20005. La tercera es
    # "Send me back to the Angel Lyceum".
    if stage in ANGEL_DE_CIUDAD and nombre in ANGELES_FACCION:
        _cfg = ANGEL_DE_CIUDAD[stage]
        _clave = 'registrado' if registrado else 'sin_registrar'
        _msg, _ops, _acc = _cfg[_clave]
        return [armar_linea(_msg, 112, list(_ops),
                            ['1', jugador or '?'], list(_acc))[2:]]
    if nombre in ANGELES_FACCION:
        _retrato, _msg, _ops, _acc = ANGELES_FACCION[nombre]
        # El cambio de dialogo depende de haber hablado con MICHAEL, no de
        # la faccion: al llegar al Graduation Palace el personaje ya viene
        # como "Graduated", asi que atandolo a la faccion se veia siempre el
        # segundo dialogo sin haber hablado con el.
        if visto_michael:
            # Solo el de Aurora lleva las cadenas con el nombre; los otros
            # tres van sin ninguna. Asi esta en la captura.
            _cad = ['1', jugador or '?'] if _msg == 10201 else []
            return [armar_linea(_msg, _retrato, list(_ops),
                                _cad, list(_acc))[2:]]
        return [armar_linea(10242, _retrato, [], ['1', jugador or '?'])[2:]]
    if nombre == 'Michael':
        # Cinco lineas seguidas. La primera y la ultima llevan el nombre.
        return [armar_linea(10130, 1, [], ['1', jugador or '?'])[2:],
                armar_linea(10131, 1, [])[2:],
                armar_linea(10132, 1, [])[2:],
                armar_linea(10133, 1, [])[2:],
                armar_linea(10134, 1, [], ['1', jugador or '?'])[2:]]

    if "Angels' Tutor" in nombre:
        # Dos lineas seguidas, copiadas de la captura:
        #   10101  val 2, dos cadenas ("1" y el nombre), sin opciones
        #   10102  val 2, opciones 10135 y 10110 + una accion por opcion
        # Van las DOS opciones con sus dos acciones, exactamente como el
        # servidor real. Se probo recortarlo a la de salir y fue un error:
        # el cliente elige por INDICE, y con una sola opcion "Quit" pasaba a
        # ser la 0 mientras el cliente manda la 1. La otra opcion (10135) no
        # lleva a ningun lado aqui, asi que cierra el cuadro.
        return [armar_linea(10101, 2, [], ['1', jugador or '?'])[2:],
                armar_linea(10102, 2, [10135, 10110],
                            acciones=[0x0f4272, 0x0f4391])[2:]]
    if 'Jack' in nombre:
        return [armar_linea(5235, 4, [20001, 20002])[2:]]
    if 'Shiva' in nombre:
        return [armar_linea(5235, 4, [20003, 20004])[2:]]
    if 'Aurora Totem' in nombre:
        # msg.xml 5136. Un totem solo dice su frase: el bloque
        # anterior devolvia, para faccion Heaven, el dialogo 10201 que es
        # del Angel Protector ('I'm the Angel Protector from Aurora City').
        return [armar_linea(5136, 0, [])[2:]]
    if 'Breeze Totem' in nombre:
        # msg.xml 5139. Un totem solo dice su frase: el bloque
        # anterior devolvia, para faccion Heaven, el dialogo 10201 que es
        # del Angel Protector ('I'm the Angel Protector from Aurora City').
        return [armar_linea(5139, 0, [])[2:]]
    if 'Dark City Totem' in nombre:
        # msg.xml 5137. Un totem solo dice su frase: el bloque
        # anterior devolvia, para faccion Heaven, el dialogo 10201 que es
        # del Angel Protector ('I'm the Angel Protector from Aurora City').
        return [armar_linea(5137, 0, [])[2:]]
    if 'Iron Totem' in nombre:
        # msg.xml 5138. Un totem solo dice su frase: el bloque
        # anterior devolvia, para faccion Heaven, el dialogo 10201 que es
        # del Angel Protector ('I'm the Angel Protector from Aurora City').
        return [armar_linea(5138, 0, [])[2:]]
    # Entrenadores de skills y magias
    if 'Weapon Expert' in nombre:
        return [armar_linea(5168, npc_val or (158 if stage == 21 else 162), [5190, 5191])[2:]]
    if 'Sword Expert' in nombre:
        return [armar_linea(5823, npc_val or (153 if stage in (26, 35) else 3), [5190, 5191])[2:]]
    if 'Axe Expert' in nombre:
        return [armar_linea(5824, npc_val or (154 if stage in (26, 35) else 3), [5190, 5191])[2:]]
    if 'Spear Expert' in nombre:
        return [armar_linea(5825, npc_val or (155 if stage in (26, 35) else 3), [5190, 5191])[2:]]
    if 'Bow Expert' in nombre:
        return [armar_linea(5826, npc_val or (160 if stage == 21 else (164 if stage == 15 else (156 if stage in (26, 35) else 3))), [5190, 5191])[2:]]
    if 'Life Mage' in nombre:
        return [armar_linea(5185, npc_val or 82, [5190, 5191])[2:]]
    if 'Wraith Mage' in nombre or 'Wraith Priest' in nombre:
        return [armar_linea(5186, npc_val or (77 if stage == 21 else (90 if stage == 15 else 83)), [5190, 5191])[2:]]
    if 'Chaos Mage' in nombre:
        return [armar_linea(5187, npc_val or 84, [5190, 5191])[2:]]
    if 'Earth Mage' in nombre or 'Earth Priest' in nombre:
        return [armar_linea(5188, npc_val or (39 if stage == 21 else (34 if stage == 15 else 85)), [5190, 5191])[2:]]

    # Maestros de recetas avanzadas y vendedores de armas/equipo
    if 'Senior Smith' in nombre or 'Super Smith' in nombre:
        return [armar_linea(5260, npc_val or (75 if stage == 21 else (92 if stage == 15 else 139)), [5190, 5191])[2:]]
    if 'Senior Master' in nombre or 'Super Master' in nombre:
        return [armar_linea(5261, npc_val or (35 if stage == 21 else (88 if stage == 15 else 140)), [5190, 5191])[2:]]
    if 'Armament Seller' in nombre:
        return [armar_linea(5179, npc_val or 106, [5190, 5191])[2:]]
    if 'Bowset Seller' in nombre:
        return [armar_linea(5180, npc_val or 107, [5190, 5191])[2:]]

    # --- Lava Cave (Stage 69) & Flaming Door (Stage 70) ---
    if 'Earth Life Mage' in nombre:
        return [armar_linea(5166, npc_val or 34, [5190, 5191], acciones=[1000076, 0])[2:]]
    if 'ChaosWraith Mage' in nombre:
        return [armar_linea(5167, npc_val or 90, [5190, 5191], acciones=[1000077, 0])[2:]]
    if 'Weapon Boffin' in nombre:
        return [armar_linea(5168, npc_val or 162, [5190, 5191], acciones=[1000078, 0])[2:]]
    if 'Bow Researcher' in nombre:
        return [armar_linea(5826, npc_val or 164, [5190, 5191], acciones=[1000079, 0])[2:]]
    if 'Rock Master' in nombre:
        return [armar_linea(5261, npc_val or 17, [5190, 5191], acciones=[1000075, 0])[2:]]
    if 'Rock Smith' in nombre:
        return [armar_linea(5260, npc_val or 19, [5190, 5191], acciones=[1000074, 0])[2:]]

    # --- Palm Base (Stage 88 - Atlantis) ---
    if 'StuffShop' in nombre:
        return [armar_linea(5269, npc_val or 11, [5270, 5271])[2:]]
    if 'Deputy' in nombre:
        return [armar_linea(7530, npc_val or 82, [7535, 7536])[2:]]
    if 'Weapon Master' in nombre:
        return [armar_linea(7531, npc_val or 23, [7535, 7536])[2:]]
    if 'Archer Trainer' in nombre:
        return [armar_linea(7532, npc_val or 116, [7535, 7536])[2:]]
    if 'Palm Base Smith' in nombre:
        return [armar_linea(5260, npc_val or 73, [5190, 5191])[2:]]
    if 'Palm Master' in nombre:
        return [armar_linea(5261, npc_val or 38, [5190, 5191])[2:]]
    if 'Robot Repairman' in nombre:
        return [armar_linea(5233, npc_val or 36, [5227, 5191])[2:]]
    if 'Weapon Clerk' in nombre:
        return [armar_linea(5254, npc_val or 38, [5190, 5191])[2:]]
    if 'Armor Clerk' in nombre:
        return [armar_linea(5255, npc_val or 74, [5190, 5191])[2:]]
    if 'Art Clerk' in nombre:
        return [armar_linea(5256, npc_val or 38, [5190, 5191])[2:]]
    if 'Sewing Clerk' in nombre:
        return [armar_linea(5257, npc_val or 75, [5190, 5191])[2:]]
    if 'Cooking Clerk' in nombre:
        return [armar_linea(5258, npc_val or 74, [5190, 5191])[2:]]
    if 'Bankclerk' in nombre:
        return [armar_linea(5236, npc_val or 35, [5237, 5238])[2:]]
    if 'General Campbell' in nombre:
        return [armar_linea(72700, npc_val or 104, [])[2:]]
    if 'Ocean Scholar' in nombre:
        return [armar_linea(74301, npc_val or 77, [])[2:]]
    if 'Charge Nurse' in nombre:
        return [armar_linea(71009, npc_val or 31, [])[2:]]
    if 'Trainer Noya' in nombre:
        return [armar_linea(70422, npc_val or 113, [])[2:]]
    if 'Premier Shanell' in nombre:
        return [armar_linea(71110, npc_val or 40, [])[2:]]
    if 'Villiersas' in nombre:
        return [armar_linea(97604, npc_val or 128, [])[2:]]
    if 'Disciple Andsen' in nombre:
        return [armar_linea(76322, npc_val or 187, [])[2:]]
    if 'BattlefieldAngel' in nombre or 'PuqiVillageAngel' in nombre:
        return [armar_linea(50001, npc_val or 112, [])[2:]]
    if any(d in nombre for d in ['Trade Director', 'Science Director', 'Prod. Director', 'Banking Director', 'Gravity Boffin']):
        return [armar_linea(7538, npc_val or 23, [])[2:]]
    if any(m in nombre for m in ['Merchant Corian', 'Merchant Kulepas', 'Scholar Oxford']):
        return [armar_linea(7537, npc_val or 29, [])[2:]]
    if 'Pyalu' in nombre:
        return [armar_linea(70707, npc_val or 56, [])[2:]]

    # --- Desolate Sea, la otra pareja de investigadores ---
    # Medido en mundo_112545_412238_orden.jsonl. Son de la region de
    # Desolate Sea, no de Atlantis: estaban mal etiquetados. Otras
    # entidades que los de Yatiss (122411/122412 frente a 123910/123911)
    # y otras tiendas, asi que van por nombre; los de Yatiss se resuelven
    # antes por entidad y no se los comen.
    if 'Spell Researcher' in nombre:
        return [armar_linea(7533, npc_val or 158, [7535, 7536],
                            acciones=[1000050, 0])[2:]]
    if 'Skill Researcher' in nombre:
        return [armar_linea(7534, npc_val or 108, [7535, 7536],
                            acciones=[1000051, 0])[2:]]
    if 'Scholar Lubo' in nombre:
        return [armar_linea(70705, npc_val or 56, [])[2:]]
    if 'Watt. Lightening' in nombre:
        return [armar_linea(74801, npc_val or 9, [])[2:]]

    # --- Waterfall Camp (Stage 104) & Desert Racetrack (Stage 121) ---
    if 'Water Expert(W)' in nombre:
        return [armar_linea(7928, npc_val or 1038, [7932, 7933])[2:]]
    if 'Water Expert(S)' in nombre:
        return [armar_linea(7929, npc_val or 1029, [7932, 7933])[2:]]
    if 'Desert Expert(W)' in nombre:
        return [armar_linea(7930, npc_val or 1063, [7932, 7933])[2:]]
    if 'Desert Expert(S)' in nombre:
        return [armar_linea(7931, npc_val or 1064, [7932, 7933])[2:]]
    if 'Waterfall Blacks' in nombre or 'Desert Smith' in nombre:
        return [armar_linea(5260, npc_val or (1034 if 'Waterfall' in nombre else 1065), [5190, 5191])[2:]]
    if 'Waterfall Guide' in nombre or 'Desert Master' in nombre:
        return [armar_linea(5261, npc_val or (1035 if 'Waterfall' in nombre else 1067), [5190, 5191])[2:]]
    if 'Waterfall Mender' in nombre or 'Desert Repairman' in nombre:
        return [armar_linea(5233, npc_val or (1033 if 'Waterfall' in nombre else 1066), [5227, 5191])[2:]]
    if 'Waterfall Banker' in nombre or 'Desert Banker' in nombre:
        return [armar_linea(5236, npc_val or (1032 if 'Waterfall' in nombre else 1068), [5237, 5238])[2:]]

    # --- Airship Station (Stage 146 - Floating Island) ---
    if 'Station Expert(W' in nombre:
        return [armar_linea(7972, npc_val or 1075, [7932, 7933])[2:]]
    if 'Station Expert(S' in nombre:
        return [armar_linea(7973, npc_val or 1074, [7932, 7933])[2:]]
    if 'Station Blacksmi' in nombre:
        return [armar_linea(5260, npc_val or 1093, [5190, 5191])[2:]]
    if 'Station Guide' in nombre:
        return [armar_linea(5261, npc_val or 3, [5190, 5191])[2:]]
    if 'Station Mender' in nombre:
        return [armar_linea(5233, npc_val or 1078, [5227, 5191])[2:]]
    if 'Station Banker' in nombre:
        return [armar_linea(5236, npc_val or 1076, [5237, 5238])[2:]]
    if 'Carstensen' in nombre:
        return [armar_linea(47004, npc_val or 1095, [])[2:]]
    if 'Researcher Lolla' in nombre:
        return [armar_linea(68311, npc_val or 41, [])[2:]]

    # --- Building Blocks City (Stage 153 - Candyland) ---
    if 'Blocks Expert(W)' in nombre:
        return [armar_linea(7985, npc_val or 1116, [7986, 7983])[2:]]
    if 'Blocks Expert(S)' in nombre:
        return [armar_linea(7987, npc_val or 1117, [7988, 7983])[2:]]
    if 'Blocks Blacksmit' in nombre:
        return [armar_linea(7981, npc_val or 1118, [7982, 7983])[2:]]
    if 'Blocks Guild' in nombre or 'Blocks Guide' in nombre:
        return [armar_linea(7984, npc_val or 1119, [7982, 7983])[2:]]
    if 'Repair Robot' in nombre:
        return [armar_linea(7989, npc_val or 1115, [7990, 7991])[2:]]
    if 'Blocks Banker' in nombre:
        return [armar_linea(7980, npc_val or 1114, [5237, 5238])[2:]]
    if 'Lord Kahn' in nombre:
        return [armar_linea(14315, npc_val or 1112, [])[2:]]

    # --- Hoca Village (Stage 163 - Dinoland) ---
    if 'Gurkha Expert(W)' in nombre:
        return [armar_linea(7972, npc_val or 16, [7932, 7933])[2:]]
    if 'Gurkha Expert(S)' in nombre:
        return [armar_linea(7973, npc_val or 70, [7932, 7933])[2:]]
    if 'Gurkha Smith' in nombre:
        return [armar_linea(5260, npc_val or 180, [5190, 5191])[2:]]
    if 'Gurkha Master' in nombre:
        return [armar_linea(5261, npc_val or 1133, [5190, 5191])[2:]]
    if 'Gurkha Repairer' in nombre:
        return [armar_linea(5233, npc_val or 130, [5227, 5191])[2:]]
    if 'Gurkha Banker' in nombre:
        return [armar_linea(5236, npc_val or 1125, [5237, 5238])[2:]]
    if 'Tribe Leader' in nombre:
        return [armar_linea(19201, npc_val or 1120, [])[2:]]
    if 'Hungry Lukas' in nombre:
        return [armar_linea(18904, npc_val or 187, [])[2:]]
    if 'Lady Gurkha' in nombre:
        return [armar_linea(19001, npc_val or 1126, [])[2:]]
    if 'Drake' in nombre:
        return [armar_linea(19607, npc_val or 181, [])[2:]]
    if 'Stone Tablet' in nombre:
        return [armar_linea(26304, npc_val or 0, [])[2:]]
    if 'Researcher Corbe' in nombre:
        return [armar_linea(18719, npc_val or 1132, [])[2:]]
    if 'Douglas the Herm' in nombre:
        return [armar_linea(19625, npc_val or 1079, [])[2:]]
    if 'Leader Hanks' in nombre:
        return [armar_linea(98507, npc_val or 180, [])[2:]]

    # --- Pharaoh Village (Stage 170 - Egypt) ---
    if 'Pharaoh Expert(W' in nombre:
        return [armar_linea(7972, npc_val or 1147, [7932, 7933])[2:]]
    if 'Pharaoh Expert(S' in nombre:
        return [armar_linea(7973, npc_val or 1068, [7932, 7933])[2:]]
    if 'Pharaoh Smith' in nombre:
        return [armar_linea(5260, npc_val or 1026, [5190, 5191])[2:]]
    if 'Pharaoh Master' in nombre:
        return [armar_linea(5261, npc_val or 1047, [5190, 5191])[2:]]
    if 'Pharaoh Repairer' in nombre:
        return [armar_linea(5233, npc_val or 1142, [5227, 5191])[2:]]
    if 'Pharaoh Banker' in nombre:
        return [armar_linea(5236, npc_val or 1143, [5237, 5238])[2:]]
    # --- Angelic Cave (Stage 194 - East Orient) ---
    # Medido el 28/09/2026 en una captura propia: clic 0x0005 sobre cada NPC y
    # el 0x0012 que contesta el servidor. Los val salen ademas solos de
    # val_por_entidad, que para sprites 40200..40999 devuelve 1000+(spr-40200):
    # 40373 -> 1173, 40374 -> 1174, 40358 -> 1158, 40357 -> 1157. Se dejan
    # escritos igual por si el sprite cambiara.
    if 'Convo Master' in nombre:
        return [armar_linea(5261, npc_val or 1173, [5190, 5191],
                            acciones=[1000028, 0])[2:]]
    if 'Convo Smith' in nombre:
        return [armar_linea(5260, npc_val or 1174, [5190, 5242],
                            acciones=[1000027, 0])[2:]]
    if 'Convo Expert(W' in nombre:
        return [armar_linea(7985, npc_val or 1158, [5190, 5191],
                            acciones=[1000033, 0])[2:]]
    if 'Convo Expert(S' in nombre:
        return [armar_linea(7987, npc_val or 31, [5190, 5191],
                            acciones=[1000034, 0])[2:]]
    if 'Convo Repairer' in nombre:
        return [armar_linea(5226, npc_val or 1157, [5227, 5242],
                            acciones=[1000026, 0])[2:]]
    # El banquero NO se llego a clicar en la captura. Lleva la linea que usan
    # los banqueros de TODAS las demas ciudades -- 5236 con [5237, 5238] -- y
    # su val sale del sprite 40356, o sea 1156. Confirmar con un clic.
    if 'Convo Bank Clerk' in nombre:
        return [armar_linea(5236, npc_val or 1156, [5237, 5238])[2:]]

    # --- Snowball Village (Stage 210 - Snow) ---
    # Medido el 28/09/2026 en captura propia. Los nombres llegan cortados a 16
    # bytes y uno trae DOS espacios, 'Snowball  Engine'; se comparan tal cual
    # para no fallar por eso. Los val vuelven a salir solos del sprite:
    # 40379 -> 1179, 40380 -> 1180, 40088 -> 88, 40113 -> 113.
    if 'Snowball  Engine' in nombre:
        return [armar_linea(5260, npc_val or 1179, [5270, 5278],
                            acciones=[1000031, 0])[2:]]
    if 'Snowball Master' in nombre:
        return [armar_linea(5261, npc_val or 88, [5270, 5371],
                            acciones=[1000032, 0])[2:]]
    if 'Snowball Combat' in nombre:
        return [armar_linea(104734, npc_val or 113, [104735, 5242],
                            acciones=[1000034, 0])[2:]]
    if 'Snowball Magic R' in nombre:
        return [armar_linea(104736, npc_val or 1180, [104737, 5242],
                            acciones=[1000035, 0])[2:]]
    # Estos dos NO SE CLICARON en la captura, asi que sus lineas no estan
    # medidas: llevan las genericas, que funcionan pero puede que no sean las
    # que manda el servidor real.
    #
    # El Worker es el reparador de la ciudad, como el 'Steam Worker' de Steam
    # Town. Alli el mensaje es propio de la ciudad, el 112015, y la opcion que
    # abre la ventana tambien, la 112016; aqui se usan la 5226 y la 5227
    # genericas porque el mensaje propio de Snowball no se puede adivinar: su
    # bloque es el 104xxx y de el solo se conocen dos numeros, el 104734 y el
    # 104736.
    #
    # El banquero empieza por la 5225, que si es compartida entre ciudades.
    # Lo que no se puede saber son sus acciones -- en Steam Town son la
    # 1000049 y la 1000050, y van por NPC -- asi que va sin ellas, como el
    # resto de banqueros del archivo.
    if 'Snowball Worker' in nombre:
        return [armar_linea(5226, npc_val or 128, [5227, 5191])[2:]]
    if 'Snowball Bank Em' in nombre:
        return [armar_linea(5225, npc_val or 1181, [5030, 5032, 5033])[2:]]

    # --- Steam Town (Stage 223 - Space Cowboy) ---
    # Medido el 28/09/2026 en captura propia. Otra vez un nombre con DOS
    # espacios, 'Steam  Engineer'. Los val salen solos del sprite: 40392 ->
    # 1192, 40327 -> 1127, 40393 -> 1193, 40394 -> 1194, 40405 -> 1205 y
    # 40345 -> 1145.
    if 'Steam  Engineer' in nombre:
        return [armar_linea(112017, npc_val or 1192, [5270, 5278],
                            acciones=[1000056, 0])[2:]]
    if 'Steam Master' in nombre:
        return [armar_linea(112018, npc_val or 1127, [5270, 5278],
                            acciones=[1000057, 0])[2:]]
    if 'Steam Magic Rese' in nombre:
        return [armar_linea(112013, npc_val or 1193, [112014, 5278],
                            acciones=[1000059, 0])[2:]]
    if 'Steam Combat Spe' in nombre:
        return [armar_linea(112011, npc_val or 1194, [112012, 5278],
                            acciones=[1000058, 0])[2:]]
    if 'Steam Worker' in nombre:
        return [armar_linea(112015, npc_val or 1205, [112016, 112004],
                            acciones=[1000055, 0])[2:]]
    # El banquero NO empieza por la 5236, que es lo que se venia poniendo en
    # las demas ciudades: al clicarlo manda la 5225, con tres opciones, y la
    # 5236 ("Which warehouse do you want to use?") solo llega DESPUES, al
    # elegir la del medio. La captura lo deja claro: clic, 5225, el cliente
    # contesta 0x000B con 0x0b -- que es 11, o sea el indice 1 -- y recien ahi
    # el servidor manda la 5236. El paso de la 5032 a la 5236 esta en
    # respuesta_a.
    if 'Steam Bank Emplo' in nombre:
        return [armar_linea(5225, npc_val or 1145, [5030, 5032, 5033],
                            acciones=[1000049, 1000050, 0])[2:]]

    # --- Edo City (Stage 232 - Sakura Festival) ---
    # Medido el 28/09/2026 en captura propia, los SEIS NPC de servicio. Los
    # val vuelven a salir del sprite: 40403 -> 1203, 40369 -> 1169, 40433 ->
    # 1233, 40432 -> 1232, 40332 -> 1132 y 40427 -> 1227.
    if 'City Senior Blac' in nombre:
        return [armar_linea(117124, npc_val or 1203, [5270, 5271],
                            acciones=[1000080, 0])[2:]]
    if 'City Senior Guid' in nombre:
        return [armar_linea(117125, npc_val or 1169, [5270, 5271],
                            acciones=[1000081, 0])[2:]]
    if 'City War Researc' in nombre:
        return [armar_linea(117118, npc_val or 1233, [117119, 5012],
                            acciones=[1000086, 0])[2:]]
    if 'City Magic Resea' in nombre:
        return [armar_linea(117120, npc_val or 1232, [117121, 5012],
                            acciones=[1000087, 0])[2:]]
    if 'City Maintenance' in nombre:
        return [armar_linea(117122, npc_val or 1132, [117123, 5020],
                            acciones=[1000073, 0])[2:]]
    # Segundo banquero medido, y confirma lo de Steam Town: al clicar manda
    # SOLO la 5225. Sus acciones son otras -- 1000072 y 1000077 frente a
    # 1000049 y 1000050 -- asi que van por NPC y no se pueden copiar de una
    # ciudad a otra.
    if 'City Banker' in nombre:
        return [armar_linea(5225, npc_val or 1227, [5030, 5032, 5033],
                            acciones=[1000072, 1000077, 0])[2:]]

    # --- Fruity Village (Stage 246 - Sequoia) ---
    # Medido el 28/09/2026 en captura propia, los NUEVE que se clicaron. Los
    # val vuelven a salir del sprite: 40181 -> 181, 40359 -> 1159, 40033 ->
    # 33, 40454 -> 1254, 40457 -> 1257, 40451 -> 1251, 40275 -> 1075 y
    # 40440 -> 1240.
    if 'Fruity Expert(W' in nombre:
        return [armar_linea(121012, npc_val or 181, [121013, 5012],
                            acciones=[1000131, 0])[2:]]
    if 'Fruity Expert(S' in nombre:
        return [armar_linea(121014, npc_val or 1159, [121015, 5012],
                            acciones=[1000132, 0])[2:]]
    if 'Fruity Smith' in nombre:
        return [armar_linea(121018, npc_val or 33, [5270, 5271],
                            acciones=[1000125, 0])[2:]]
    if 'Fruity Master' in nombre:
        return [armar_linea(121019, npc_val or 1254, [5270, 5271],
                            acciones=[1000126, 0])[2:]]
    if 'Fruity Repairer' in nombre:
        return [armar_linea(121016, npc_val or 1257, [121017, 121004],
                            acciones=[1000124, 0])[2:]]
    if 'Fruity Bank Cler' in nombre:
        return [armar_linea(5225, npc_val or 1251, [5030, 5032, 5033],
                            acciones=[1000117, 1000118, 0])[2:]]
    # Estos dos no venden nada: una linea de texto y ya.
    if 'Scholar Taern' in nombre:
        return [armar_linea(119116, npc_val or 1075, [])[2:]]
    if 'Chief Roluck' in nombre:
        return [armar_linea(121202, npc_val or 1240, [])[2:]]

    # --- Shuwa Market (Stage 258 - Shuwa) ---
    # Medido el 28/09/2026 en captura propia. Los cuatro vendedores de
    # habilidades y recetas usan los MISMOS mensajes que los de Building
    # Blocks City (7981, 7984, 7985, 7987) y las mismas opciones, asi que
    # aqui la tienda la tiene que decidir la entidad, no la opcion.
    if 'Shuwa Expert(S' in nombre:
        return [armar_linea(7987, npc_val or 1284, [7982, 7983],
                            acciones=[1000084, 0])[2:]]
    if 'Shuwa Expert(W' in nombre:
        return [armar_linea(7985, npc_val or 1157, [7982, 7983],
                            acciones=[1000083, 0])[2:]]
    if 'Shuwa Smith' in nombre:
        return [armar_linea(7981, npc_val or 1282, [7982, 7983],
                            acciones=[1000081, 0])[2:]]
    if 'Shuwa Master' in nombre:
        return [armar_linea(7984, npc_val or 1275, [7982, 7983],
                            acciones=[1000082, 0])[2:]]
    if 'Shuwa Repairer' in nombre:
        return [armar_linea(5226, npc_val or 187, [5227, 5242],
                            acciones=[1000080, 0])[2:]]
    if 'Shuwa Bank Clerk' in nombre:
        return [armar_linea(5225, npc_val or 1276, [5030, 5032, 5033],
                            acciones=[1000073, 1000074, 0])[2:]]
    # El guardia de Bayan es el primero de VARIAS PAGINAS: manda tres lineas
    # sueltas que el cliente va pidiendo con 0x000B valor 1, y la cuarta ya
    # trae opciones. Al elegir la primera contesta la 8388 con cinco, que
    # estan en respuesta_a.
    if 'Bayan Entry Guar' in nombre:
        return [armar_linea(8382, npc_val or 5, [])[2:],
                armar_linea(8383, npc_val or 5, [])[2:],
                armar_linea(8384, npc_val or 5, [])[2:],
                armar_linea(8385, npc_val or 5, [8386, 8387],
                            acciones=[1000093, 0])[2:]]

    # Brin, en Shuwa Market. Solo una linea de texto.
    #
    # Se llego a poner aqui el menu de Siam Square como si fuera su segunda
    # pagina, y era falso: en la captura el menu aparece DESPUES, cuando el
    # jugador ya se habia ido de Brin y piso el tornado de (19,175). Lo
    # delataba el tramo del MOVE_REQ, que acaba en (20,174), justo al lado de
    # ese tornado. El menu es del PORTAL, no de este NPC.
    if nombre == 'Brin':
        return [armar_linea(126714, npc_val or 1285, [])[2:]]

    # --- Joaquin (Stage 276 - Sylvan Chaos) ---
    # La familia Florentia. Medido el 28/09/2026, y con dos novedades.
    #
    # UNA: el banquero NO usa la 5225 ni la 5236, que se habian tomado por
    # compartidas entre ciudades. Aqui tiene las suyas, la 508053 y la 508062,
    # con la misma forma -- tres opciones y luego dos -- pero otros numeros.
    #
    # DOS: el Smith y el Master tienen DOS tiendas cada uno. Su primera opcion
    # abre una segunda pagina, la 508315, y ahi se elige banda de nivel: la
    # 211-215 o la 221-225. Es el primer NPC del proyecto que vende dos cosas
    # distintas segun lo que contestes.
    if 'Florentia Smith' in nombre:
        return [armar_linea(508045, npc_val or 1249, [508046, 508047],
                            acciones=[1000122, 0])[2:]]
    if 'Florentia Master' in nombre:
        return [armar_linea(508048, npc_val or 1156, [508046, 508047],
                            acciones=[1000123, 0])[2:]]
    if 'Florentia Magic' in nombre:
        return [armar_linea(508051, npc_val or 1290, [508052, 508047],
                            acciones=[1000070, 0])[2:]]
    if 'Florentia Melee' in nombre:
        return [armar_linea(508049, npc_val or 1291, [508050, 508047],
                            acciones=[1000071, 0])[2:]]
    if 'Florentia Repair' in nombre:
        return [armar_linea(508043, npc_val or 1292, [508044, 508047],
                            acciones=[1000069, 0])[2:]]
    if 'Florentia Banker' in nombre:
        return [armar_linea(508053, npc_val or 1247,
                            [508054, 508055, 508056],
                            acciones=[1000062, 1000063, 0])[2:]]
    if 'Young Greenie' in nombre:
        return [armar_linea(128402, npc_val or 160, [])[2:],
                armar_linea(128403, npc_val or 160, [128404, 128405],
                            acciones=[1000012, 1000013])[2:]]
    if 'Elite Raiden Wei' in nombre:
        return [armar_linea(127911, npc_val or 1290, [])[2:]]

    if 'Prof. Stein' in nombre:
        return [armar_linea(37410, npc_val or 1122, [])[2:]]
    if 'Priest Eaglearch' in nombre:
        return [armar_linea(37311, npc_val or 1150, [])[2:]]
    if 'Elder Fredderick' in nombre:
        return [armar_linea(39120, npc_val or 29, [])[2:]]

    if 'Little Childe' in nombre:
        return [armar_linea(64201, npc_val or 151, [])[2:]]
    if "Cook's Assistant" in nombre:
        return [armar_linea(75901, npc_val or 0, [])[2:]]
    if 'Chef Fatz' in nombre:
        return [armar_linea(60319, npc_val or 64, [])[2:]]
    if 'Heavenly Officer' in nombre:
        return [armar_linea(60301, npc_val or 46, [])[2:]]
    if 'Vilo 3' in nombre:
        return [armar_linea(60305, npc_val or 62, [])[2:]]
    if 'Sick Zapo' in nombre:
        return [armar_linea(60308, npc_val or 20, [])[2:]]
    if 'Gustav' in nombre:
        return [armar_linea(60312, npc_val or 92, [])[2:]]
    if 'Ugly Saladan' in nombre:
        return [armar_linea(60295, npc_val or 89, [])[2:]]
    if 'Annoying Clerk' in nombre:
        return [armar_linea(60296, npc_val or 125, [])[2:]]
    if 'Trouble Student' in nombre:
        return [armar_linea(60297, npc_val or 114, [])[2:]]
    if 'Jamier' in nombre:
        return [armar_linea(60298, npc_val or 152, [])[2:]]

    # Quest NPCs - Mysterious Wetland (Stage 15) & Dragon Graveyard (Stage 21)
    if 'Explorer Peter' in nombre:
        return [armar_linea(82601, npc_val or 11, [82602, 82603])[2:]]
    if 'Researcher Mary' in nombre:
        return [armar_linea(82701, npc_val or 38, [82702, 82703, 82704])[2:]]
    if 'Warlock Ofer' in nombre:
        return [armar_linea(82901, npc_val or 23, [82902, 82903])[2:]]
    if 'Warrior Gegen' in nombre:
        return [armar_linea(83001, npc_val or 32, [83002, 83003, 83004])[2:]]
    if 'Paladin Gerison' in nombre:
        return [armar_linea(83201, npc_val or 13, [83202, 83203])[2:]]
    if 'Mad Mike' in nombre:
        return [armar_linea(83401, npc_val or 17, [83402, 83403])[2:]]
    if 'Chef Boship' in nombre:
        return [armar_linea(60319, npc_val or 64, [])[2:]]
    if 'Angel Agent' in nombre:
        return [armar_linea(93302, npc_val or 112, [93303, 93304])[2:]]

    # Healer (Vendedora de pociones, martillos, soap, etc.)
    if 'Healer' in nombre or 'Healing Angel' in nombre:
        return [armar_linea(5775, npc_val or 33, [5190, 5191])[2:]]

    # Reparadores de equipo segun ciudad
    if 'Repair Slave' in nombre or (stage == 26 and 'Repair' in nombre):
        return [armar_linea(5231, npc_val or 19, [5227, 5191])[2:]]
    if 'Technician' in nombre or (stage == 38 and ('Repair' in nombre or 'Technician' in nombre)):
        return [armar_linea(5229, npc_val or 38, [5227, 5191])[2:]]
    if stage == 3 and 'Repair' in nombre:
        return [armar_linea(5226, npc_val or 3, [5227, 5191])[2:]]
    if any(r in nombre for r in ['Repair Expert', 'Repair Angel', 'Repair Worker', 'Repair Slave']):
        return [armar_linea(5233, npc_val or 33, [5227, 5191])[2:]]

    # Vendedores de monturas (Ride Seller / Ride Seller C) segun ciudad
    if 'Ride Seller C' in nombre:
        v_c = {3: (5189, 10), 38: (5202, 158), 26: (5213, 80), 29: (5224, 147)}.get(stage, (5224, 147))
        return [armar_linea(v_c[0], npc_val or v_c[1], [5262, 5190, 5191])[2:]]
    if 'Ride Seller' in nombre:
        v_s = {3: (5189, 66), 38: (5202, 38), 26: (5213, 17), 29: (5224, 92)}.get(stage, (5224, 92))
        return [armar_linea(v_s[0], npc_val or v_s[1], [5262, 5190, 5191])[2:]]

    # Plan Sellers (Recetas de produccion)
    if 'W. Plan Seller' in nombre:
        return [armar_linea(5254, npc_val or 3, [5190, 5191])[2:]]
    if any(a in nombre for a in ['A. Recipe Seller', 'A. Plan Seller']):
        return [armar_linea(5255, npc_val or 3, [5190, 5191])[2:]]
    if 'C. Plan Seller' in nombre:
        return [armar_linea(5256, npc_val or 3, [5190, 5191])[2:]]
    if 'D. Plan Seller' in nombre:
        return [armar_linea(5257, npc_val or 3, [5190, 5191])[2:]]
    if 'F. Plan Seller' in nombre:
        return [armar_linea(5258, npc_val or 3, [5190, 5191])[2:]]
    if 'Adv. Plan Seller' in nombre:
        return [armar_linea(5259, npc_val or 3, [5190, 5191])[2:]]

    # Mercaderes y artesanos
    if 'Weaponsmith' in nombre:
        return [armar_linea(5179, npc_val or 3, [5190, 5191])[2:]]
    if 'Armorsmith' in nombre:
        return [armar_linea(5195, npc_val or 3, [5190, 5191])[2:]]
    if 'Lightgear Seller' in nombre:
        return [armar_linea(5183, npc_val or 3, [5190, 5191])[2:]]
    if 'Heavygear Seller' in nombre:
        return [armar_linea(5182, npc_val or 3, [5190, 5191])[2:]]
    if 'Mage Gear Seller' in nombre:
        return [armar_linea(5184, npc_val or 3, [5190, 5191])[2:]]
    if 'Bow Seller' in nombre:
        return [armar_linea(5180, npc_val or 3, [5190, 5191])[2:]]
    if 'Borg Seller' in nombre:
        return [armar_linea(5181, npc_val or 3, [5190, 5191])[2:]]
    if 'Material Seller' in nombre:
        return [armar_linea(5269, npc_val or 3, [5190, 5191])[2:]]

    # Salesman de la camara de comercio Suft (ordenes)
    if 'Weapon Salesman' in nombre:
        return [armar_linea(70000, npc_val or 3, [5190, 5191])[2:]]
    if 'Armor Salesman' in nombre:
        return [armar_linea(70001, npc_val or 3, [5190, 5191])[2:]]
    if 'Sewing Salesman' in nombre:
        return [armar_linea(70002, npc_val or 3, [5190, 5191])[2:]]
    if 'Cooking Salesman' in nombre:
        return [armar_linea(70003, npc_val or 3, [5190, 5191])[2:]]
    if any(s in nombre for s in ['Art Salesman', 'Art Saleman']):
        return [armar_linea(70004, npc_val or 3, [5190, 5191])[2:]]
    # --- Whitefang Village (Stage 288 - Magma Flux) ---
    # Los Vulcan. Medido en mundo_165036_535764_orden.jsonl, nueve clics.
    #
    # Aqui se repite lo de Joaquin y va a mas: el Merchant tiene DOS tiendas
    # y el Smith y el Master abren cada uno una segunda pagina, la 509136,
    # que es la MISMA para los tres. Lo que cambia son sus acciones, asi que
    # esa pagina no se puede meter en una tabla por opcion a secas: va por
    # cual fue la opcion que la abrio.
    #
    # La 508869 sale como ultima opcion en casi todos y nadie la pulso: por
    # su sitio es el "adios" de siempre.
    if 'Vulcan Master' in nombre:
        return [armar_linea(508870, npc_val or 1307, [508871, 508869],
                            acciones=[1000035, 0])[2:]]
    if 'Vulcan Smith' in nombre:
        return [armar_linea(508867, npc_val or 1194, [508868, 508869],
                            acciones=[1000036, 0])[2:]]
    if 'Vulcan Repairer' in nombre:
        return [armar_linea(508865, npc_val or 1301, [508866, 508869],
                            acciones=[1000037, 0])[2:]]
    if 'Vulcan Merchant' in nombre:
        # Su retrato es el 1006 FIJO. El que sale del sprite da 1007, y es
        # el unico de la ciudad en el que la cuenta automatica no acierta.
        return [armar_linea(509042, 1006, [509043, 509044],
                            acciones=[1000090, 0])[2:]]
    if 'Vulcan Banker' in nombre:
        return [armar_linea(508876, npc_val or 1295,
                            [508877, 508878, 508879],
                            acciones=[1000038, 1000042, 0])[2:]]
    if 'Vulcan Magic Dev' in nombre:
        return [armar_linea(508874, npc_val or 1306, [508875, 508869],
                            acciones=[1000045, 0])[2:]]
    if 'Vulcan Melee Dev' in nombre:
        return [armar_linea(508872, npc_val or 1308, [508873, 508869],
                            acciones=[1000046, 0])[2:]]
    if 'Firefae Sammi' in nombre:
        return [armar_linea(130911, npc_val or 1309, [])[2:]]

    # --- Coo Village (Stage 298) ---
    # Los Magikale. Medido en mundo_170658_001641_orden.jsonl, siete clics.
    # Misma forma que Whitefang: cada oficio con una opcion y el adios, el
    # banquero con tres, y el Merchant con una segunda pagina de dos tiendas.
    #
    # El 509773 es el adios compartido y el 509770 (la opcion del Worker) se
    # pulso pero no llego respuesta en la captura, asi que no se cablea.
    if 'Magikale Instruc' in nombre:
        return [armar_linea(509774, npc_val or 1146, [509775, 509773],
                            acciones=[1000011, 0])[2:]]
    if 'Magikale Master' in nombre:
        return [armar_linea(509771, npc_val or 1164, [509772, 509773],
                            acciones=[1000012, 0])[2:]]
    if 'Magikale Worker' in nombre:
        return [armar_linea(509769, npc_val or 1196, [509770, 509773],
                            acciones=[1000008, 0])[2:]]
    if 'Magikale Bank Em' in nombre:
        return [armar_linea(509780, npc_val or 1239,
                            [509781, 509782, 509783],
                            acciones=[1000001, 1000005, 0])[2:]]
    if 'Magikale Spell R' in nombre:
        return [armar_linea(509778, npc_val or 1323, [509779, 509773],
                            acciones=[1000009, 0])[2:]]
    if 'Magikale Tactici' in nombre:
        return [armar_linea(509776, npc_val or 1322, [509777, 509773],
                            acciones=[1000010, 0])[2:]]
    if 'Magikale Merchan' in nombre:
        return [armar_linea(509810, npc_val or 1259, [509811, 509812],
                            acciones=[1000013, 0])[2:]]

    # --- Rainbow Town (Stage 308) ---
    # Los Chrono. Medido en mundo_121453_667578_orden.jsonl, siete clics.
    # Aqui se complica: el Instructor y el Smith abren LA MISMA segunda
    # pagina, la 510422, con seis opciones, y cada uno con sus acciones. El
    # Instructor tiene ademas una TERCERA pagina detras de la opcion 5366.
    # El 510101 es el adios compartido.
    if 'Chrono Worker' in nombre:
        return [armar_linea(510097, npc_val or 192, [510098, 510101],
                            acciones=[1000030, 0])[2:]]
    if 'Chrono Smith' in nombre:
        return [armar_linea(510099, npc_val or 1337, [510100, 510101],
                            acciones=[1000056, 0])[2:]]
    if 'Chrono Instructo' in nombre:
        return [armar_linea(510102, npc_val or 1338, [510103, 510101],
                            acciones=[1000057, 0])[2:]]
    if 'Chrono Tactician' in nombre:
        return [armar_linea(510104, npc_val or 1336, [510105, 510101],
                            acciones=[1000033, 0])[2:]]
    if 'Chrono Researche' in nombre:
        return [armar_linea(510106, npc_val or 188, [510107, 510101],
                            acciones=[1000034, 0])[2:]]
    if 'Chrono Banker' in nombre:
        return [armar_linea(510108, npc_val or 10, [510109, 510110],
                            acciones=[1000035, 1000039])[2:]]
    if 'Chrono Merchant' in nombre:
        # Retrato 1007 FIJO: el que sale del sprite da 1008. Le pasa lo
        # mismo que al Vulcan Merchant de Whitefang.
        return [armar_linea(510138, 1007, [510139, 510140],
                            acciones=[1000062, 0])[2:]]

    # --- Twinkle Town (Stage 320) ---
    # Medido en mundo_122145_779758_orden.jsonl, diez clics. Misma forma que
    # Rainbow: el Smith y el Instructor abren la MISMA pagina, la 511118, y
    # hasta comparten la opcion que abre tienda (511574), asi que ahi la
    # tienda tiene que salir de la pareja (entidad, opcion).
    # El 511076 es el adios compartido.
    if 'Twinkle Worker' in nombre:
        return [armar_linea(511072, npc_val or 1372, [511073, 511076],
                            acciones=[1000075, 0])[2:]]
    if 'Twinkle Smith' in nombre:
        return [armar_linea(511074, npc_val or 1206, [511075, 511076],
                            acciones=[1000076, 0])[2:]]
    if 'Twinkle Instruct' in nombre:
        return [armar_linea(511077, npc_val or 1305, [511078, 511076],
                            acciones=[1000079, 0])[2:]]
    if 'Twinkle Tacticia' in nombre:
        return [armar_linea(511079, npc_val or 1316, [511080, 511076],
                            acciones=[1000082, 0])[2:]]
    if 'Twinkle Research' in nombre:
        return [armar_linea(511081, npc_val or 1328, [511082, 511076],
                            acciones=[1000083, 0])[2:]]
    if 'Twinkle Banker' in nombre:
        return [armar_linea(511083, npc_val or 1374,
                            [511084, 511085, 511086],
                            acciones=[1000084, 1000085, 0])[2:]]
    if 'Twinkle Merchant' in nombre:
        return [armar_linea(511113, npc_val or 1193, [511114, 511115],
                            acciones=[1000105, 0])[2:]]
    if 'Whisp Clerk' in nombre:
        # Dos paginas: el cliente las pide una a una.
        return [
            armar_linea(511095, npc_val or 5, [])[2:],
            armar_linea(510761, npc_val or 5, [511571, 511572],
                        acciones=[1000091, 1000117])[2:],
        ]
    if 'Rich Bill' in nombre:
        return [armar_linea(140501, npc_val or 1375, [140502, 140503],
                            acciones=[1000068, 0])[2:]]
    if 'Adored Henri' in nombre:
        return [armar_linea(140408, npc_val or 1248, [])[2:]]

    # --- Specter Village (Stage 335) ---
    # Medido en mundo_123002_293264_orden.jsonl, nueve clics. El 511727 es
    # el adios compartido. El Crystal Guard suelta CUATRO paginas seguidas.
    if 'Specter Worker' in nombre:
        return [armar_linea(511723, npc_val or 1392, [511724, 511727],
                            acciones=[1000050, 0])[2:]]
    if 'Specter Smith' in nombre:
        return [armar_linea(511725, npc_val or 1300, [511726, 511727],
                            acciones=[1000051, 0])[2:]]
    if 'Specter Instruct' in nombre:
        return [armar_linea(511728, npc_val or 1288, [511729, 511727],
                            acciones=[1000054, 0])[2:]]
    if 'Specter Tacticia' in nombre:
        return [armar_linea(511730, npc_val or 1395, [511731, 511727],
                            acciones=[1000057, 0])[2:]]
    if 'Specter Research' in nombre:
        return [armar_linea(511732, npc_val or 1332, [511733, 511727],
                            acciones=[1000058, 0])[2:]]
    if 'Specter Banker' in nombre:
        return [armar_linea(511734, npc_val or 1383,
                            [511735, 511736, 511737],
                            acciones=[1000059, 1000060, 0])[2:]]
    if 'Specter Merchant' in nombre:
        return [armar_linea(511764, npc_val or 1398, [511765, 511766],
                            acciones=[1000084, 0])[2:]]
    if 'Crystal Guard' in nombre:
        return [
            armar_linea(511746, npc_val or 5, [])[2:],
            armar_linea(511747, npc_val or 5, [])[2:],
            armar_linea(511748, npc_val or 5, [])[2:],
            armar_linea(511749, npc_val or 5, [511750, 511751],
                        acciones=[1000069, 0])[2:],
        ]

    # --- Teddy Amusement (Stage 347) ---
    # Medido en mundo_123802_521873_orden.jsonl, ocho clics. Dos novedades:
    # el Merchant tiene TRES tiendas (la 3, la 35 y la 210) y el banquero
    # encadena una TERCERA pagina. El 512962 es el adios de los oficios y
    # el 512972 el del banquero y el worker.
    if 'Park Worker' in nombre:
        # Retrato 33 FIJO: el que sale del sprite da 143.
        return [armar_linea(512958, 33, [512959, 512972],
                            acciones=[1000099, 0])[2:]]
    if 'Park Smith' in nombre:
        return [armar_linea(512960, npc_val or 1196, [512961, 512962],
                            acciones=[1000117, 0])[2:]]
    if 'Park Instructor' in nombre:
        return [armar_linea(512963, npc_val or 1170, [512964, 512962],
                            acciones=[1000114, 0])[2:]]
    if 'Park Tactician' in nombre:
        return [armar_linea(512965, npc_val or 1060, [512966, 512962],
                            acciones=[1000113, 0])[2:]]
    if 'Park Researcher' in nombre:
        return [armar_linea(512967, npc_val or 1181, [512968, 512962],
                            acciones=[1000112, 0])[2:]]
    if 'Park Banker' in nombre:
        return [armar_linea(512969, npc_val or 1165,
                            [512970, 512971, 512972],
                            acciones=[1000105, 1000106, 0])[2:]]
    if 'Park Merchant' in nombre:
        return [armar_linea(512999, npc_val or 1189, [513000, 513001],
                            acciones=[1000100, 0])[2:]]
    if 'Beary Manager' in nombre:
        return [
            armar_linea(512981, npc_val or 5, [])[2:],
            armar_linea(512982, npc_val or 5, [])[2:],
            armar_linea(512983, npc_val or 5, [])[2:],
            armar_linea(512984, npc_val or 5, [512985, 512986],
                        acciones=[1000088, 0])[2:],
        ]

    # --- Los fijos del Lyceum (stage 41) ---
    # Sacados de los sp_*.xml de los paks (tools/npcs_de_sp_xml.py), que
    # son los unicos archivos del cliente que dicen DONDE va cada NPC y con
    # que linea abre:
    #
    #     <npc id="11119" msgid="514888" map="41" x="153" y="88" dir="下"/>
    #
    # Ojo: el msgid NO siempre es el saludo. En el Gear Clerk apunta a una
    # OPCION ("Skills") y el saludo es el 505825; en el Scrollmaker si es
    # el saludo. Hay que leer el bloque, no fiarse del numero.
    if stage == 41:
        if nombre == 'Hestia':
            # 514888 saluda, 514889/514890 son sus dos opciones. Detras
            # viene el Angel Training Quest y el Hestia Gift Coupon.
            return [armar_linea(514888, npc_val or 4, [514889, 514890])[2:]]
        if nombre == 'Scrollmaker':
            # El de los Arcane Scraps: cambia fragmentos por pergaminos o
            # por habilidades (513265 y 513266), que es el que faltaba.
            return [armar_linea(513261, npc_val or 4, [513262, 513263])[2:]]
        if nombre == 'Gear Clerk':
            # El saludo es el 505825; el 505823 que trae sp_gear_clerk.xml
            # es una de las opciones, no la linea de apertura.
            return [armar_linea(505825, npc_val or 4,
                                [505822, 505823, 505824, 505826])[2:]]
        if nombre == 'Astrologer':
            return [armar_linea(142535, npc_val or 4, [142536])[2:]]
        if nombre == 'Fortunia':
            # La cambiadora de vales. Su bloque es el 504131-504141:
            # saluda y ofrece cambiar vales o Convention Tickets, y detras
            # vienen las categorias (armas, robots, muebles, pergaminos V,
            # gemas...).
            #
            # OJO CON EL TEXTO: el id 504131 NO dice lo mismo en todos los
            # paks. En UPDATE8 es "Howdy! Name's Fortunia...", en UPDATE6 y
            # UPDATE7 es un NPC del Huevo, y desde UPDATE9 en adelante es
            # "Hi, I'm Pasqua". Manda el pak mas nuevo, asi que el cliente
            # de hoy la hace presentarse como Pasqua aunque el NPC siga
            # llamandose Fortunia en npc.xml, en los 26 updates.
            #
            # Las opciones y toda la estructura son las mismas en los dos,
            # solo cambia la redaccion.
            return [armar_linea(504131, npc_val or 4, [504132, 504133])[2:]]
        if nombre == 'Voucher Angel':
            # Vende los dos Angelic Voucher, el de 100 y el de 10 millones
            # (items 42399 y 42400). Los dos se compran y se venden al
            # MISMO precio, asi que sirven para guardar oro sin perderlo,
            # que es lo que el banco no deja hacer. La tienda es la 159 de
            # shop.xml, que trae exactamente esos dos y nada mas.
            return [armar_linea(507715, npc_val or 4, [5190, 5191])[2:]]

    # --- Clank Oasis (407) y Commercial Street (419) ---
    # Los dos ultimos mapas de ALO TW, tambien sin captura. Las lineas
    # salen de msg.xml: Clank Oasis en 516648-516657 y Commercial Street
    # en 517063-517068, los dos ya en ingles.
    #
    # Van por STAGE y no por nombre ni entidad: 'Spell Analyst' y
    # 'Technique Analyst' se llaman IGUAL en los dos mapas y venden cosas
    # distintas, y el entity_id de la plantilla es el de la sesion de
    # Taiwan y no sobrevive a la conexion.
    #
    # Quien es quien: el "stance researcher" de Clank y el "strategy
    # researcher" de Commercial son el de guerrero (Technique Analyst), y
    # el "spell/magic researcher" el de magias (Spell Analyst).
    if stage == 407:
        if nombre == 'Spell Analyst':
            return [armar_linea(516648, npc_val or 4, [516649])[2:]]
        if nombre == 'Technique Analyst':
            return [armar_linea(516650, npc_val or 4, [516651])[2:]]
        if nombre == 'Oasis Mechanic':
            return [armar_linea(516652, npc_val or 4, [516653])[2:]]
        if nombre == 'Oasis Merchant':
            return [armar_linea(516654, npc_val or 4, [516655])[2:]]
        if nombre == 'Oasis Banker':
            # Sin opciones: msg.xml no trae ninguna para el banquero de
            # este mapa. Habla y ya; el almacen necesita una captura.
            return [armar_linea(516656, npc_val or 4, [])[2:]]
    if stage == 419:
        # OJO: las opciones son las MISMAS que las de Clank Oasis. No es un
        # descuido: Commercial Street no tiene ni una linea de opcion en
        # ningun pak que tengamos, solo los seis saludos. Como el texto de
        # las de Clank es generico ("Okay, I'd like to buy spell scrolls")
        # se reusan para que la ciudad sirva, y la tienda se decide por el
        # stage. Si algun dia sale una captura, estos ids son lo primero
        # que hay que corregir.
        if nombre == 'Spell Analyst':
            return [armar_linea(517063, npc_val or 4, [516649])[2:]]
        if nombre == 'Technique Analyst':
            return [armar_linea(517064, npc_val or 4, [516651])[2:]]
        if nombre == 'Street Mechanic':
            return [armar_linea(517065, npc_val or 4, [516653])[2:]]
        if nombre == 'Street Vendor':
            return [armar_linea(517066, npc_val or 4, [516655])[2:]]
        if nombre == 'Street Banker':
            return [armar_linea(517067, npc_val or 4, [])[2:]]

    # --- Floral Alley (stage 398, region de Sun Sea Maze) ---
    # Este mapa NO viene de una captura: se poblo desde el cliente oficial
    # de Taiwan y sus NPC estaban mudos. Las lineas salen de msg.xml
    # (bloque 516188-516210) y la forma del menu se copia de Chilly
    # Village, que si esta medida y usa exactamente el mismo reparto de
    # cadenas un millar mas abajo.
    #
    # Sin acciones a proposito: no las podemos saber sin captura y los
    # dialogos de tienda funcionan sin ellas, asi que van vacias en vez de
    # inventadas. La ultima opcion de cada menu es la 516201, "me voy".
    #
    # Va al FINAL de propio(), por debajo de todas las comprobaciones
    # por entidad: 'Bank Staff' y 'Merchant' son tambien los nombres de
    # NPC de Busy Market y de media ciudad mas, y arriba del todo este
    # bloque se los comia.
    #
    # Por nombre EXACTO y no por entidad: el entity_id de la plantilla es
    # el de la sesion de Taiwan y no sobrevive a la conexion. Exacto y no
    # 'in' porque 'Merchant' y 'Repairman' son subcadenas de media docena
    # de NPC de otras ciudades.
    if nombre == 'Researcher (S)':      # el de las magias
        return [armar_linea(516188, npc_val or 4, [516189, 516201])[2:]]
    if nombre == 'Researcher (C)':      # el de las de guerrero
        return [armar_linea(516190, npc_val or 4, [516191, 516201])[2:]]
    if nombre == 'Repairman':
        return [armar_linea(516192, npc_val or 4, [516193, 516201])[2:]]
    if nombre == 'Merchant':
        return [armar_linea(516194, npc_val or 4, [516195, 516201])[2:]]
    if nombre == 'Bank Staff':
        return [armar_linea(516198, npc_val or 4,
                            [516199, 516200, 516201])[2:]]

    # --- Galaxia Square (Stage 355) ---
    # Medido en mundo_124443_082465_orden.jsonl, nueve clics. Dos cosas que
    # no salen en otras ciudades:
    #   - el banquero contesta a UNA opcion con CINCO lineas seguidas
    #   - el Researcher y el Tactician tienen TRES opciones y comparten la
    #     514279, que nadie pulso: por su sitio es la de invocaciones
    if 'Star Worker' in nombre:
        return [armar_linea(514110, npc_val or 127, [514111, 514101],
                            acciones=[1000045, 0])[2:]]
    if 'Star Master' in nombre:
        return [armar_linea(514116, npc_val or 1184, [514117, 514120],
                            acciones=[1000048, 0])[2:]]
    if 'Star Smith' in nombre:
        return [armar_linea(514118, npc_val or 1370, [514119, 514120],
                            acciones=[1000049, 0])[2:]]
    if 'Star Tactician' in nombre:
        return [armar_linea(514114, npc_val or 116,
                            [514279, 514115, 514120],
                            acciones=[1000082, 1000047, 0])[2:]]
    if 'Star Researcher' in nombre:
        return [armar_linea(514112, npc_val or 1169,
                            [514279, 514113, 514120],
                            acciones=[1000079, 1000046, 0])[2:]]
    if 'Star Banker' in nombre:
        return [armar_linea(514098, npc_val or 1181, [514099, 514100],
                            acciones=[1000038, 1000042])[2:]]
    if 'Star Merchant' in nombre:
        return [armar_linea(514124, npc_val or 1132, [514125, 514126],
                            acciones=[1000050, 0])[2:]]
    if 'Starry Manager' in nombre:
        return [
            armar_linea(514130, npc_val or 5, [])[2:],
            armar_linea(514131, npc_val or 5, [])[2:],
            armar_linea(514132, npc_val or 5, [])[2:],
            armar_linea(514133, npc_val or 5, [514134, 514135],
                        acciones=[1000068, 0])[2:],
        ]
    if 'Floren' in nombre:
        return [armar_linea(147510, npc_val or 1432, [])[2:]]

    d = _propios().get(nombre)
    if not d:
        return None
    res_b = bytearray(bytes.fromhex(d['hex']))
    if npc_val > 0 and len(res_b) >= 6:
        struct.pack_into('<H', res_b, 4, npc_val)
    return [bytes(res_b)]


# ------------------------------------------- elegir una opcion del cuadro
PRIMERA_OPCION = 10
RESPUESTAS = {
    5798: 5800,
    # Descripciones de ciudades y totems
    10207: 10215,
    10208: 10223,
    10209: 10217,
    10210: 10224,
    10211: 10219,
    10212: 10225,
    10213: 10221,
    10214: 10226,
    # Pet Expert
    6101: 6105,
    6106: 6112,
    6107: 6113,
    6108: 6114,
    6109: 6115,
    6110: 6116,
    # Ride Seller
    5262: 5264,   # "Tell me about the Rides" -> 5264
    # Angels' Tutor
    10107: 10112,   # Score Regulation
    10108: 10115,   # Top Student Training
    # Medido: al decir que si llega el 10127 ("What a pity! ... I now will
    # transport you to Graduation Palace"), no el 10130. El 10130 es el
    # saludo de Michael, que ya es del otro mapa.
    10125: 10127,   # Quit training, confirmar -> 10127
    10119: 10121,   # Graduate confirm Yes -> 10121
}

# Mapeo por nombre de NPC a su Shop ID correspondiente
TIENDAS_POR_NOMBRE = {
    # El Voucher Angel del Lyceum: tienda 159, los dos Angelic Voucher.
    # Va por NOMBRE y no por opcion: su opcion es la 5190, la generica
    # de 'quiero ver tus cosas', que apunta a la tienda 1. El nombre se
    # mira antes que la opcion, asi que gana este.
    'Voucher Angel': 159,
    # --- Whitefang Village (Stage 288) ---
    'Vulcan Magic Dev': 160,
    'Vulcan Melee Dev': 161,
    # --- Galaxia Square (Stage 355) ---
    'Star Tactician': 211,
    'Star Researcher': 212,
    # --- Floral Alley (stage 398) ---
    # El par que le toca por orden de ciudad: 215/216 Desolate Sea,
    # 217/218 Chilly, 219/220 Busy Market, 221/222 Floral Alley. En
    # shop.xml el impar son espadas y el par magias, y estas dos son las
    # de nivel 310 (Edge Guard I y Astro Impact I).
    'Researcher (C)': 221,   # guerrero
    'Researcher (S)': 222,   # magias
    # --- Teddy Amusement (Stage 347) ---
    'Park Tactician': 208,
    'Park Researcher': 209,
    # --- Specter Village (Stage 335) ---
    'Specter Tacticia': 201,
    'Specter Research': 202,
    # --- Twinkle Town (Stage 320) ---
    'Twinkle Tacticia': 190,
    'Twinkle Research': 191,
    # --- Rainbow Town (Stage 308) ---
    'Chrono Tactician': 176,
    'Chrono Researche': 177,
    # --- Coo Village (Stage 298) ---
    'Magikale Instruc': 171,
    'Magikale Master': 170,
    'Magikale Spell R': 169,
    'Magikale Tactici': 168,
    'Sword Expert': 36,
    'Axe Expert': 39,
    'Spear Expert': 40,
    'Bow Expert': 41,
    'Earth Mage': 11,
    'Life Mage': 8,
    'Wraith Mage': 9,
    'Chaos Mage': 10,
    'Weapon Salesman': 2,
    'Armor Salesman': 5,
    'Bow Seller': 3,
    'Borg Seller A': 4,
    'Borg Seller B': 42,
    'Heavygear Seller': 5,
    'Lightgear Seller': 6,
    'Mage Gear Seller': 7,
    'Cooking Salesman': 7,
    'Sewing Salesman': 5,
    'Art Saleman': 6,
    'Material Seller': 56,
    'Pet Expert': 69,
    'Rock Smith': 74,
    'Rock Master': 75,
    'Earth Life Mage': 76,
    'ChaosWraith Mage': 77,
    'Weapon Boffin': 78,
    'Bow Researcher': 79,
    'Weaponsmith': 2,         # Armas de guerrero hasta lv 35
    'Armorsmith': 3,          # Armaduras
    'A. Recipe Seller': 20,   # Recetas de armaduras (A. Plan)
    'A. Plan Seller': 20,
    'C. Plan Seller': 21,     # Recetas de artesania (Crafting)
    'D. Plan Seller': 22,     # Recetas de sastreria / costura (Dress/Tailor)
    'F. Plan Seller': 23,     # Recetas de comida (Food/Cooking)
    'W. Plan Seller': 16,     # Recetas de armas (Weapon Plan)
    'Adv. Plan Seller': 24,   # Recetas avanzadas
    'Weapon Director': 16,
    'Armor Director': 20,
    'Sewing Director': 22,
    'Cooking Director': 23,
    'Art Director': 21,
    'Scroll Seller': 17,
    'Magic Seller': 18,
    'Shopkeeper': 1,
    'Healer': 35,             # Pociones HP/MP, Ring of Angel Wings, Piercing Hammers, Soap Powder
    'Senior Smith': 25,       # Recetas avanzadas de armas
    'Senior Master': 26,      # Recetas avanzadas de artesania/cocina/costura
    'Super Smith': 66,        # Recetas maestras de armas (W.Plan)
    'Super Master': 67,       # Recetas maestras de artesania/cocina/costura (C/D/F.Plan)
    'Weapon Expert': 64,      # Habilidades de armas maestras (Sword, Axe, Spear)
    'Earth Priest': 62,       # Magias de sacerdote (Life & Earth)
    'Wraith Priest': 63,      # Magias de sacerdote (Chaos & Wraith)
    'Armament Seller': 51,    # Armas intermedias
    'Bowset Seller': 52,      # Arcos y catapultas intermedias
    'Palm Base Smith': 81,    # Recetas de herreria lvl 80-90
    'Palm Master': 82,       # Recetas maestras lvl 80-90
    'Weapon Master': 87,     # Habilidades de armas lvl 80-90
    'Archer Trainer': 88,    # Habilidades de arquero lvl 80-90
    'Priest Deputy': 83,     # Magias Life & Holy lvl 80-90
    'Wizard Deputy': 84,     # Magias Chaos & Wraith lvl 80-90
    'Summoner Deputy': 85,   # Magias Earth & Invocaciones lvl 80-90
    'Magic Deputy': 86,      # Spells avanzados lvl 80-90
    'StuffShop': 56,         # Materiales y consumibles de faccion
    'Weapon Clerk': 24,      # Recetas de armas
    'Armor Clerk': 20,       # Recetas de armaduras
    'Art Clerk': 21,         # Recetas de artesania
    'Sewing Clerk': 22,      # Recetas de sastreria
    'Cooking Clerk': 23,     # Recetas de cocina
    'Spell Researcher': 89,  # Desolate Sea - Spells (Action Sealed IV, Power Shield I-II, Anti-locked Shield I-III)
    'Skill Researcher': 90,  # Desolate Sea - Skills (Dream Slaughter IV, Silence IV, Defence Wall II-IV, Speedup Attack II-IV, Anti-locked Tactics I-III)
    'Water Expert(W)': 96,   # Waterfall Camp - Weapon skills lv 90-100
    'Desert Expert(W)': 96,  # Desert Racetrack - Weapon skills lv 90-100
    'Water Expert(S)': 95,   # Waterfall Camp - Spell skills lv 90-100
    'Desert Expert(S)': 95,  # Desert Racetrack - Spell skills lv 90-100
    'Waterfall Blacks': 93,  # Waterfall Camp - Smith recipes lv 90-100
    'Desert Smith': 93,      # Desert Racetrack - Smith recipes lv 90-100
    'Waterfall Guide': 94,   # Waterfall Camp - Master recipes lv 90-100
    'Desert Master': 94,     # Desert Racetrack - Master recipes lv 90-100
    'Station Expert(W': 105, # Airship Station - Weapon skills lv 100-110
    'Station Expert(S': 104, # Airship Station - Spell skills lv 100-110
    'Station Blacksmi': 102, # Airship Station - Smith recipes lv 121-125
    'Station Guide': 103,    # Airship Station - Master recipes lv 121-125
    'Blocks Expert(W)': 109, # Building Blocks City - Weapon skills
    'Blocks Expert(S)': 108, # Building Blocks City - Spell skills
    'Blocks Blacksmit': 106, # Building Blocks City - Smith recipes lv 131-145
    'Blocks Guild': 107,     # Building Blocks City - Master recipes lv 131-145
    'Blocks Guide': 107,     # Building Blocks City - Master recipes lv 131-145
    'Healing Angel': 35,     # Building Blocks City - Potions & supplies
    'Gurkha Expert(W)': 113, # Hoca Village - Weapon skills
    'Gurkha Expert(S)': 112, # Hoca Village - Spell skills
    'Gurkha Smith': 114,     # Hoca Village - Smith recipes
    'Gurkha Master': 115,    # Hoca Village - Master recipes
    'Pharaoh Expert(W)': 117, # Pharaoh Village - Weapon skills
    'Pharaoh Expert(S)': 116, # Pharaoh Village - Spell skills
    'Pharaoh Smith': 118,     # Pharaoh Village - Smith recipes
    'Pharaoh Master': 119,    # Pharaoh Village - Master recipes
    'Convo Expert(W)': 123,   # Angelic Cave - Weapon skills
    'Convo Expert(S)': 122,   # Angelic Cave - Spell skills
    'Convo Smith': 118,       # Angelic Cave - Smith recipes
    'Convo Master': 119,      # Angelic Cave - Master recipes
    'Snowball Combat': 128,   # Snowball Village - Weapon skills
    'Snowball Magic R': 129,  # Snowball Village - Spell skills
    'Snowball Master': 130,   # Snowball Village - Master recipes
    'Snowball  Engine': 131,  # Snowball Village - Smith recipes
    'Steam Magic Rese': 133,  # Steam Town - Spell skills
    'Steam Combat Spe': 134,  # Steam Town - Weapon skills
    'Steam  Engineer': 135,   # Steam Town - Smith recipes
    'Steam Master': 136,      # Steam Town - Master recipes
    'City Magic Resea': 138,  # Edo City - Spell skills
    'City War Researc': 139,  # Edo City - Weapon skills
    'City Senior Blac': 140,  # Edo City - Smith recipes
    'City Senior Guid': 141,  # Edo City - Master recipes
    'Fruity Expert(S)': 143,  # Fruity Village - Spell skills
    'Fruity Expert(W)': 144,  # Fruity Village - Weapon skills
    'Fruity Smith': 145,      # Fruity Village - Smith recipes
    'Fruity Master': 146,     # Fruity Village - Master recipes
    'Shuwa Expert(S)': 151,   # Shuwa Market - Spell skills
    'Shuwa Expert(W)': 152,   # Shuwa Market - Weapon skills
    'Shuwa Smith': 145,       # Shuwa Market - Smith recipes
    'Shuwa Master': 146,      # Shuwa Market - Master recipes
}

# UN MISMO NPC CON DOS TIENDAS, segun la opcion que se elija.
#
# Hasta Joaquin cada vendedor tenia una sola y bastaba con TIENDAS_POR_ENTIDAD.
# El Florentia Smith y el Florentia Master abren una segunda pagina y ahi se
# escoge banda de nivel, asi que la entidad sola no alcanza: hace falta la
# pareja (entidad, opcion).
TIENDAS_POR_ENTIDAD_Y_OPCION = {
    # --- Joaquin (Stage 276) ---
    (123498, 508316): 155,   # Florentia Smith  -> recetas nivel 211-215
    (123498, 508317): 157,   # Florentia Smith  -> recetas nivel 221-225
    (123499, 508316): 156,   # Florentia Master -> recetas nivel 211-215
    (123499, 508317): 158,   # Florentia Master -> recetas nivel 221-225
    # --- Whitefang Village (Stage 288) ---
    # El Merchant abre una segunda pagina y ahi se elige tienda.
    (123581, 509139): 3,     # Vulcan Merchant -> tienda 3
    (123581, 509140): 35,    # Vulcan Merchant -> tienda 35
    # El Smith y el Master comparten la pagina 509136 y por tanto sus dos
    # opciones, asi que la tienda tiene que salir de la PAREJA. Del Smith
    # esta medida la primera; las otras tres no se pulsaron.
    (123578, 509137): 162,   # Vulcan Smith -> tienda 162
    # --- Coo Village (Stage 298) ---
    (123623, 509813): 3,     # Magikale Merchant -> tienda 3
    (123623, 509814): 35,    # Magikale Merchant -> tienda 35
    # --- Rainbow Town (Stage 308) ---
    (123661, 510423): 171,   # Chrono Instructor -> tienda 171
    (123661, 510875): 185,   # Chrono Instructor -> tienda 185
    (123667, 510141): 3,     # Chrono Merchant   -> tienda 3
    (123667, 510142): 35,    # Chrono Merchant   -> tienda 35
    # --- Twinkle Town (Stage 320) ---
    # El Smith y el Instructor comparten la opcion 511574 y cada uno abre
    # su tienda, asi que aqui no vale la opcion sola.
    (123719, 511574): 194,   # Twinkle Smith
    (123718, 511574): 195,   # Twinkle Instructor
    (123720, 511116): 3,     # Twinkle Merchant
    (123720, 511117): 35,    # Twinkle Merchant
    # --- Specter Village (Stage 335) ---
    # El Smith y el Instructor abren la misma pagina con las mismas dos
    # opciones, asi que la tienda sale de la pareja.
    (123788, 511121): 198,   # Specter Instructor
    (123790, 511122): 199,   # Specter Smith
    (123786, 511767): 3,     # Specter Merchant
    (123786, 511768): 35,    # Specter Merchant
    # --- Teddy Amusement (Stage 347) ---
    (123847, 513005): 205,   # Park Instructor
    (123845, 513006): 206,   # Park Smith
    (123844, 513002): 3,     # Park Merchant
    (123844, 513003): 35,    # Park Merchant
    (123844, 513007): 210,   # Park Merchant -- este tiene TRES
    # --- Busy Market (region de Warring Realm) ---
    (123993, 515852): 3,     # Market Merchant
    (123993, 515853): 35,    # Market Merchant, su segunda tienda
    # --- Chilly Village (region de Celestia) / los Elf ---
    (123969, 515209): 3,     # Merchant Elf
    (123969, 515210): 35,    # Merchant Elf, su segunda tienda
    # --- Desolate Sea / Yatiss ---
    (123913, 514657): 3,     # Yatiss Merchant
    (123913, 514658): 35,    # Yatiss Merchant, su segunda tienda
    # --- Galaxia Square (Stage 355) ---
    (123873, 514122): 207,   # Star Master
    (123874, 514123): 213,   # Star Smith
}

# Tiendas especificas segun la entidad del NPC que vende
TIENDAS_POR_ENTIDAD = {
    # --- Whitefang Village (Stage 288 - Magma Flux) ---
    123575: 160,   # Vulcan Magic Dev (opcion 508875)
    123576: 161,   # Vulcan Melee Dev (opcion 508873)
    # --- Busy Market (region de Warring Realm) ---
    123987: 220,   # Spell Researcher (opcion 515846)
    123992: 219,   # Skill Researcher (opcion 515848)
    # --- Chilly Village (region de Celestia) / los Elf ---
    123971: 218,   # Spell Researcher (opcion 515203)
    123970: 217,   # Skill Researcher (opcion 515205)
    # --- Desolate Sea / Yatiss ---
    # Ni estos ni los de Chilly van en TIENDAS_POR_NOMBRE: el nombre
    # 'Spell/Skill Researcher' lo repiten TRES zonas con tiendas distintas.
    123910: 216,   # Spell Researcher (opcion 514651)
    123911: 215,   # Skill Researcher (opcion 514653)
    # --- Galaxia Square (Stage 355) ---
    123871: 211,   # Star Tactician (opcion 514115)
    123876: 212,   # Star Researcher (opcion 514113)
    123875: 3,     # Star Merchant (opcion 514127)
    # --- Teddy Amusement (Stage 347) ---
    123842: 208,   # Park Tactician (opcion 512966)
    123846: 209,   # Park Researcher (opcion 512968)
    # --- Specter Village (Stage 335) ---
    123785: 201,   # Specter Tactician (opcion 511731)
    123787: 202,   # Specter Researcher (opcion 511733)
    # --- Twinkle Town (Stage 320) ---
    123717: 190,   # Twinkle Tactician (opcion 511080)
    123716: 191,   # Twinkle Researcher (opcion 511082)
    # --- Rainbow Town (Stage 308) ---
    123666: 176,   # Chrono Tactician (opcion 510105)
    123663: 177,   # Chrono Researcher (opcion 510107)
    # --- Coo Village (Stage 298) ---
    123621: 171,   # Magikale Instructor (opcion 509775)
    123622: 170,   # Magikale Master     (opcion 509772)
    123619: 169,   # Magikale Spell R    (opcion 509779)
    123620: 168,   # Magikale Tactician  (opcion 509777)

    # --- Lyceum (Stage 41) ---
    11: 17,    # Scroll Seller -> Shop 17 (Crazy Roar, Recovery Shield, etc.)
    19: 18,    # Magic Seller -> Shop 18 (Shock Wave, Cure Spell, etc.)
    46: 21,    # C. Plan Seller -> Shop 21 (Craft / Wood recipes)
    47: 22,    # D. Plan Seller -> Shop 22 (Tailor / Sewing recipes)
    17: 16,    # Ironsmith -> Shop 16 (Weaponsmith recipes)
    18: 20,    # Ironsmith -> Shop 20 (Armorsmith recipes)
    36: 2,     # Weapon Salesman -> Shop 2
    37: 3,     # Armor Salesman -> Shop 3
    38: 5,     # Sewing Salesman -> Shop 5
    39: 7,     # Cooking Salesman -> Shop 7
    40: 6,     # Art Saleman -> Shop 6
    24: 1,     # Shopkeeper -> Shop 1

    # --- Aurora City (Stage 3) ---
    121625: 12, # Ride Seller -> Shop 12 (White/Brown Steed, Magic Donkey)
    121654: 57, # Ride Seller C -> Shop 57 (Top Steed, Top Donkey, Pig Dodo)
    121681: 35, # Healer -> Shop 35 (HP/MP Potions, Ring of Angel Wings, Soap, Hammers)
    121627: 2,  # Weapon Seller -> Shop 2
    121636: 3,  # Bow Seller -> Shop 3
    121651: 4,  # Borg Seller A -> Shop 4
    121652: 42, # Borg Seller B -> Shop 42
    121649: 5,  # Armor Salesman -> Shop 5
    121645: 6,  # Lightgear Seller -> Shop 6
    121619: 7,  # Mage Gear Seller -> Shop 7
    121616: 56, # Material Seller -> Shop 56
    121676: 16, # W. Plan Seller -> Shop 16
    121673: 20, # A. Recipe Seller -> Shop 20
    121674: 21, # C. Plan Seller -> Shop 21
    121677: 22, # D. Plan Seller -> Shop 22
    121678: 23, # F. Plan Seller -> Shop 23
    121657: 36, # Sword Expert -> Shop 36
    121615: 39, # Axe Expert -> Shop 39
    121617: 40, # Spear Expert -> Shop 40
    121646: 41, # Bow Expert -> Shop 41
    121666: 69, # Pet Expert -> Shop 69

    # --- Breeze Woods (Stage 29) ---
    121934: 13, # Ride Seller -> Shop 13 (Nightwolf, Orange Chicken, Pig Dodo)
    121927: 58, # Ride Seller C -> Shop 58 (Top Nightwolf, Top Chicken)
    121959: 35, # Healer -> Shop 35
    121960: 2,  # Weaponsmith -> Shop 2
    121954: 3,  # Bow Seller -> Shop 3
    121939: 4,  # Borg Seller A -> Shop 4
    121952: 42, # Borg Seller B -> Shop 42
    121955: 5,  # Armor Salesman -> Shop 5
    121933: 6,  # Lightgear Seller -> Shop 6
    121941: 7,  # Mage Gear Seller -> Shop 7
    121932: 56, # Material Seller -> Shop 56
    121971: 16, # W. Plan Seller -> Shop 16
    121972: 20, # A. Recipe Seller -> Shop 20
    121973: 21, # C. Plan Seller -> Shop 21
    121974: 22, # D. Plan Seller -> Shop 22
    121975: 23, # F. Plan Seller -> Shop 23
    121929: 36, # Sword Expert -> Shop 36
    121930: 39, # Axe Expert -> Shop 39
    121931: 40, # Spear Expert -> Shop 40
    121950: 41, # Bow Expert -> Shop 41
    121982: 69, # Pet Expert -> Shop 69

    # --- Iron Castle (Stage 38) ---
    122099: 14, # Ride Seller -> Shop 14 (Yellow/Brown/Red Boar, Gerbil)
    122138: 59, # Ride Seller C -> Shop 59 (Top Boar, Top Gerbil)
    122089: 35, # Healer -> Shop 35
    122093: 2,  # Weaponsmith -> Shop 2
    122104: 3,  # Bow Seller -> Shop 3
    122106: 4,  # Borg Seller A -> Shop 4
    122126: 42, # Borg Seller B -> Shop 42
    122102: 5,  # Armor Salesman -> Shop 5
    122105: 6,  # Lightgear Seller -> Shop 6
    122130: 7,  # Mage Gear Seller -> Shop 7
    122088: 56, # Material Seller -> Shop 56
    122131: 16, # W. Plan Seller -> Shop 16
    122132: 20, # A. Recipe Seller -> Shop 20
    122133: 21, # C. Plan Seller -> Shop 21
    122134: 22, # D. Plan Seller -> Shop 22
    122135: 23, # F. Plan Seller -> Shop 23
    122094: 36, # Sword Expert -> Shop 36
    122095: 39, # Axe Expert -> Shop 39
    122096: 40, # Spear Expert -> Shop 40
    122128: 41, # Bow Expert -> Shop 41
    122148: 69, # Pet Expert -> Shop 69

    # --- Dark City (Stage 26) ---
    121853: 15, # Ride Seller -> Shop 15 (Cyan/Green/Red Lizard, Evil Cat)
    121889: 60, # Ride Seller C -> Shop 60 (Top Lizard, Top Evil Cat, Pig Dodo)
    121883: 35, # Healer -> Shop 35
    121851: 2,  # Weaponsmith -> Shop 2
    121886: 3,  # Bow Seller -> Shop 3
    121885: 4,  # Borg Seller A -> Shop 4
    121882: 42, # Borg Seller B -> Shop 42
    121861: 5,  # Armor Salesman -> Shop 5
    121887: 6,  # Lightgear Seller -> Shop 6
    121859: 7,  # Mage Gear Seller -> Shop 7
    121875: 56, # Material Seller -> Shop 56
    121876: 16, # W. Plan Seller -> Shop 16
    121877: 20, # A. Recipe Seller -> Shop 20
    121878: 21, # C. Plan Seller -> Shop 21
    121879: 22, # D. Plan Seller -> Shop 22
    121880: 23, # F. Plan Seller -> Shop 23
    121864: 36, # Sword Expert -> Shop 36
    121869: 39, # Axe Expert -> Shop 39
    121870: 40, # Spear Expert -> Shop 40
    121888: 41, # Bow Expert -> Shop 41
    121898: 69, # Pet Expert -> Shop 69

    # --- Cherry Village (Stage 5 - Aurora) ---
    121701: 51, # Armament Seller -> Shop 51
    121702: 52, # Bowset Seller -> Shop 52
    121704: 26, # Senior Master -> Shop 26
    121705: 25, # Senior Smith -> Shop 25
    121706: 53, # Mage Gear Seller -> Shop 53
    121707: 43, # Life Mage -> Shop 43
    121708: 44, # Wraith Mage -> Shop 44
    121709: 45, # Chaos Mage -> Shop 45
    121710: 46, # Earth Mage -> Shop 46
    121711: 47, # Sword Expert -> Shop 47
    121712: 48, # Axe Expert -> Shop 48
    121713: 49, # Spear Expert -> Shop 49
    121714: 50, # Bow Expert -> Shop 50

    # --- Mysterious Garden (Stage 22 - Beasts) ---
    121816: 25, # Senior Smith -> Shop 25
    121817: 26, # Senior Master -> Shop 26
    121818: 51, # Armament Seller -> Shop 51
    121819: 52, # Bowset Seller -> Shop 52
    121820: 53, # Mage Gear Seller -> Shop 53
    121821: 47, # Sword Expert -> Shop 47
    121822: 48, # Axe Expert -> Shop 48
    121823: 50, # Bow Expert -> Shop 50
    121824: 43, # Life Mage -> Shop 43
    121825: 44, # Wraith Mage -> Shop 44
    121826: 45, # Chaos Mage -> Shop 45
    121827: 46, # Earth Mage -> Shop 46
    121830: 49, # Spear Expert -> Shop 49

    # --- Memory Cave (Stage 35 - Shadow) ---
    122044: 47, # Sword Expert -> Shop 47
    122045: 26, # Senior Master -> Shop 26
    122046: 25, # Senior Smith -> Shop 25
    122050: 48, # Axe Expert -> Shop 48
    122051: 49, # Spear Expert -> Shop 49
    122052: 50, # Bow Expert -> Shop 50
    122053: 51, # Armament Seller -> Shop 51
    122054: 52, # Bowset Seller -> Shop 52
    122055: 43, # Life Mage -> Shop 43
    122056: 44, # Wraith Mage -> Shop 44
    122057: 45, # Chaos Mage -> Shop 45
    122058: 46, # Earth Mage -> Shop 46
    122059: 53, # Mage Gear Seller -> Shop 53

    # --- Gebuer Vale (Stage 36 - Iron) ---
    122066: 25, # Senior Smith -> Shop 25
    122067: 26, # Senior Master -> Shop 26
    122068: 51, # Armament Seller -> Shop 51
    122069: 52, # Bowset Seller -> Shop 52
    122070: 53, # Mage Gear Seller -> Shop 53
    122071: 47, # Sword Expert -> Shop 47
    122072: 48, # Axe Expert -> Shop 48
    122073: 49, # Spear Expert -> Shop 49
    122074: 50, # Bow Expert -> Shop 50
    122075: 44, # Wraith Mage -> Shop 44
    122076: 45, # Chaos Mage -> Shop 45
    122077: 46, # Earth Mage -> Shop 46
    122078: 43, # Life Mage -> Shop 43

    # --- Mysterious Wetland (Stage 15) ---
    121766: 66, # Super Smith -> Shop 66 (Weapon Recipe / W.Plan)
    121767: 67, # Super Master -> Shop 67 (Craft / Tailor / Cook Recipe: C/D/F.Plan)
    121768: 65, # Bow Expert -> Shop 65 (Bow expert skills)
    121769: 64, # Weapon Expert -> Shop 64 (Sword, Axe, Spear expert skills)
    121770: 62, # Earth Priest -> Shop 62 (Life & Earth magic skills)
    121771: 63, # Wraith Priest -> Shop 63 (Chaos & Wraith magic skills)

    # --- Dragon Graveyard (Stage 21) ---
    121800: 66, # Super Smith -> Shop 66 (Weapon Recipe / W.Plan)
    121801: 67, # Super Master -> Shop 67 (Craft / Tailor / Cook Recipe: C/D/F.Plan)
    121802: 65, # Bow Expert -> Shop 65 (Bow expert skills)
    121803: 64, # Weapon Expert -> Shop 64 (Sword, Axe, Spear expert skills)
    121804: 62, # Earth Priest -> Shop 62 (Life & Earth magic skills)
    121805: 63, # Wraith Priest -> Shop 63 (Chaos & Wraith magic skills)

    # --- Lava Cave (Stage 69) ---
    122299: 74, # Rock Smith -> Shop 74 (Smith recipes: Black Sycee, Shy Batten, Reborn Sword, Shake Axe...)
    122300: 76, # Earth Life Mage -> Shop 76 (Earth & Life magic: Wolf Bellowing, Bear Shift 4, Stealth, Unicorn Shift...)
    122301: 77, # ChaosWraith Mage -> Shop 77 (Chaos & Wraith magic: Demon Surge, Thunder Trap 4, Icy Storm...)

    # --- Flaming Door (Stage 70) ---
    122308: 75, # Rock Master -> Shop 75 (Master recipes: Cherry Oil, Shy Batten, Benison Ring, Fool Staff...)
    122310: 78, # Weapon Boffin -> Shop 78 (Weapon skills: Defence Wall, Speedup Attack, Swift Cut, Aurora Trap...)
    122311: 79, # Bow Researcher -> Shop 79 (Bow skills: Defence Wall, Speedup Attack, Scorpion Snipe, Demon Sealed, Triple Shot...)

    # --- Palm Base (Stage 88 - Atlantis) ---
    122392: 52, # Bowset Seller -> Shop 52 (Bow, Arrows, Bullets, Catapults)
    122403: 56, # Aurora StuffShop -> Shop 56 (Sundries, materials)
    122366: 56, # SteelS StuffShop -> Shop 56
    122400: 56, # Beasts StuffShop -> Shop 56
    122401: 56, # Shadow StuffShop -> Shop 56
    122399: 87, # Weapon Master -> Shop 87 (Physical skill scrolls: Great Chop, Death Chop...)
    122398: 88, # Archer Trainer -> Shop 88 (Bow skill scrolls: Scorpion Snipe, Demon Sealed...)
    122394: 83, # Priest Deputy -> Shop 83 (Holy & Life magic: Protection Spell, Aurora Trap...)
    122396: 84, # Wizard Deputy -> Shop 84 (Chaos & Wraith magic: Icy Storm, Thunder Strike...)
    122395: 85, # Summoner Deputy -> Shop 85 (Earth magic: Demon-Sucking, Chaos Melody, Azrael...)
    122397: 86, # Magic Deputy -> Shop 86 (Spell scrolls: Unicorn Shift, Natural Antibody...)
    122371: 35, # Healer -> Shop 35 (HP/MP Potions, Angel Wings, Soap, Hammers)
    122393: 51, # Armament Seller -> Shop 51 (Swords, axes, spears...)
    122391: 53, # Mage Gear Seller -> Shop 53 (Mage robes, caps, staff...)
    122373: 81, # Palm Base Smith -> Shop 81 (Smith recipes: Aerolite Ingot, Beech Batten...)
    122363: 82, # Palm Master -> Shop 82 (Master recipes: Thyme Oil, Beech Batten...)
    122359: 69, # Pet Expert -> Shop 69 (Pet cookies, cans, eggs)
    122387: 24, # Weapon Clerk -> Shop 24 (Weapon recipes)
    122388: 20, # Armor Clerk -> Shop 20 (Armor recipes)
    122389: 21, # Art Clerk -> Shop 21 (Art recipes)
    122362: 22, # Sewing Clerk -> Shop 22 (Sewing recipes)
    122372: 23, # Cooking Clerk -> Shop 23 (Cooking recipes)

    # --- Blue Ocean (Stage 90 - Atlantis) ---
    122411: 90, # Skill Researcher -> Shop 90 (Dream Slaughter IV, Silence IV, Defence Wall II-IV, Speedup Attack II-IV, Anti-locked Tactics I-III)
    122412: 89, # Spell Researcher -> Shop 89 (Action Sealed IV, Power Shield I-II, Anti-locked Shield I-III)

    # --- Waterfall Camp (Stage 104) ---
    122480: 96, # Water Expert(W) -> Shop 96 (Weapon Skill Scrolls lv 90-100)
    122481: 95, # Water Expert(S) -> Shop 95 (Spell Skill Scrolls lv 90-100)
    122469: 93, # Waterfall Blacks -> Shop 93 (Smith recipes lv 90-100)
    122470: 94, # Waterfall Guide -> Shop 94 (Master recipes lv 90-100)

    # --- Desert Racetrack (Stage 121) ---
    122592: 96, # Desert Expert(W) -> Shop 96 (Weapon Skill Scrolls lv 90-100)
    122599: 95, # Desert Expert(S) -> Shop 95 (Spell Skill Scrolls lv 90-100)
    122598: 93, # Desert Smith -> Shop 93 (Smith recipes lv 90-100)
    122594: 94, # Desert Master -> Shop 94 (Master recipes lv 90-100)

    # --- Airship Station (Stage 146 - Floating Island) ---
    122738: 105, # Station Expert(W) -> Shop 105 (Weapon Skill Scrolls lv 100-110)
    122737: 104, # Station Expert(S) -> Shop 104 (Spell Skill Scrolls lv 100-110)
    122735: 102, # Station Blacksmi -> Shop 102 (Smith recipes lv 121-125)
    122736: 103, # Station Guide -> Shop 103 (Master recipes lv 121-125)

    # --- Building Blocks City (Stage 153 - Candyland) ---
    122802: 109, # Blocks Expert(W) -> Shop 109 (Weapon skill scrolls)
    122801: 108, # Blocks Expert(S) -> Shop 108 (Spell skill scrolls)
    122805: 106, # Blocks Blacksmit -> Shop 106 (Smith recipes lv 131-145)
    122806: 107, # Blocks Guild -> Shop 107 (Master recipes lv 131-145)
    122812: 35,  # Healing Angel -> Shop 35 (Potions & supplies)

    # --- Hoca Village (Stage 163 - Dinoland) ---
    122898: 113, # Gurkha Expert(W) -> Shop 113 (Weapon skill scrolls)
    122897: 112, # Gurkha Expert(S) -> Shop 112 (Spell skill scrolls)
    122899: 114, # Gurkha Smith -> Shop 114 (Smith recipes lv 151-155)
    122900: 115, # Gurkha Master -> Shop 115 (Master recipes lv 151-155)

    # --- Pharaoh Village (Stage 170 - Egypt) ---
    123009: 117, # Pharaoh Expert(W) -> Shop 117 (Weapon skill scrolls)
    123013: 116, # Pharaoh Expert(S) -> Shop 116 (Spell skill scrolls)
    123011: 118, # Pharaoh Smith -> Shop 118 (Smith recipes lv 161-165)
    123012: 119, # Pharaoh Master -> Shop 119 (Master recipes lv 161-165)

    # --- Angelic Cave (Stage 194 - East Orient) ---
    # Los cuatro salen de la captura del 28/09/2026: se clico el NPC, se
    # contesto la primera opcion y se leyo el 0x0034 que devolvio el servidor.
    # Las recetas 118 y 119 son las MISMAS que las de Pharaoh Village, no es
    # un error de copia: las dos ciudades venden la banda de nivel 161.
    123057: 123, # Convo Expert(W) -> Shop 123 (Shockwave, Aegis... lv 163-190)
    123060: 122, # Convo Expert(S) -> Shop 122 (Holy Yoke, Divine Prayer... lv 163-190)
    123058: 118, # Convo Smith -> Shop 118 (recetas de Smith lv 161)
    123059: 119, # Convo Master -> Shop 119 (recetas de Master lv 161)

    # --- Snowball Village (Stage 210 - Snow) ---
    # Misma captura del 28/09/2026, mismo metodo: clic, primera opcion y el
    # 0x0034 de vuelta. Aqui la banda de nivel es la 171.
    123153: 128, # Snowball Combat -> Shop 128 (Earth Tremor, Armor Flip... lv 172+)
    123154: 129, # Snowball Magic R -> Shop 129 (Holy Light, Holy Prayer... lv 171+)
    123157: 130, # Snowball Master -> Shop 130 (recetas de Master lv 171)
    123155: 131, # Snowball  Engine -> Shop 131 (recetas de Smith lv 171)

    # --- Steam Town (Stage 223 - Space Cowboy) ---
    # Misma captura del 28/09/2026. Banda de nivel 181.
    123214: 133, # Steam Magic Rese -> Shop 133 (Mirror Reflect... lv 186+)
    123215: 134, # Steam Combat Spe -> Shop 134 (Angry Charge... lv 187+)
    123216: 135, # Steam  Engineer -> Shop 135 (recetas de Smith lv 181)
    123217: 136, # Steam Master -> Shop 136 (recetas de Master lv 181)

    # --- Edo City (Stage 232 - Sakura Festival) ---
    # Misma captura del 28/09/2026. Los articulos de estas cuatro tiendas NO
    # estan en nuestro content.db: son de un parche posterior al cliente del
    # que salieron los xml. El id de tienda si es el que manda el servidor.
    123277: 138, # City Magic Resea -> Shop 138
    123278: 139, # City War Researc -> Shop 139
    123279: 140, # City Senior Blac -> Shop 140
    123281: 141, # City Senior Guid -> Shop 141

    # --- Fruity Village (Stage 246 - Sequoia) ---
    123376: 143, # Fruity Expert(S) -> Shop 143
    123378: 144, # Fruity Expert(W) -> Shop 144
    123377: 145, # Fruity Smith -> Shop 145
    123374: 146, # Fruity Master -> Shop 146

    # --- Shuwa Market (Stage 258 - Shuwa) ---
    # Las recetas 145 y 146 son las MISMAS que las de Fruity Village: las dos
    # ciudades venden la misma banda.
    123440: 151, # Shuwa Expert(S) -> Shop 151
    123441: 152, # Shuwa Expert(W) -> Shop 152
    123442: 145, # Shuwa Smith -> Shop 145
    123443: 146, # Shuwa Master -> Shop 146

    # --- Joaquin (Stage 276 - Sylvan Chaos) ---
    # Las de skills se PREDIJERON por la banda de nivel antes de medirlas, y
    # acertaron: los bichos de Joaquin son de 220 a 235 y estas dos venden de
    # 220 a 250. El Smith y el Master no estan aqui porque tienen dos cada
    # uno; van en TIENDAS_POR_ENTIDAD_Y_OPCION.
    123496: 153, # Florentia Magic -> Shop 153 (Sacred Wrath...)
    123497: 154, # Florentia Melee -> Shop 154 (Shield Wall...)
}

# Opciones de dialogo que abren la ventana de tienda (WND_NPCSALE).
# Medido en sub_605190/sub_656E70 del cliente: opcode S->C 0x0034 [LE16 shop_id].
TIENDAS_POR_OPCION = {
    # --- Floral Alley (stage 398) ---
    # El mercader no tiene entidad estable, asi que sus dos tiendas van por
    # opcion. Los numeros son los de siempre: flechas la 3 y pociones la 35.
    516196: 3,   # 箭矢, flechas
    516197: 35,  # 藥水、雜貨, pociones y varios
    12103: 1,    # Default compra/venta
    5190: 1,     # "I wish to look at your goods" (Skills & gear)
    5270: 56,    # "Let me see." (StuffShop / Material Seller)
    7535: 87,    # "I wish to buy the scroll." (Deputy / Weapon Master / Archer Trainer)
    7932: 96,    # "I want to buy" (Waterfall / Desert Experts)
    7982: 106,   # "Can you show me what skills you have?" (Blocks Smith & Guild)
    7986: 109,   # "Oh, I want to learn them!" (Blocks Expert(W))
    7988: 108,   # "Oh, I want to learn them!" (Blocks Expert(S))
    6102: 69,    # Pet Expert -> Shop 69 (Comida y galletas de mascota)
    5045: 37,    # Angel Aide (Guide Palace) -> Shop 37
    104735: 128, # Snowball Combat -> Shop 128
    104737: 129, # Snowball Magic R -> Shop 129
    112012: 134, # Steam Combat Spe -> Shop 134
    112014: 133, # Steam Magic Rese -> Shop 133
    117119: 139, # City War Researc -> Shop 139
    117121: 138, # City Magic Resea -> Shop 138
    121013: 144, # Fruity Expert(W) -> Shop 144
    121015: 143, # Fruity Expert(S) -> Shop 143
}


# Las acciones de la 5236, la linea "Which warehouse do you want to use?".
#
# Van por NPC, no por mensaje: el banquero de Steam Town manda 1000051 y
# 1000054, y el de Edo City 1000078 y 1000079, con la misma linea. Por eso
# esto es una tabla y no un par de numeros fijos, que fue como se puso al
# principio y hacia que la linea de Edo City saliera con las de Steam Town.
#
# Un banquero que no este aqui manda la linea SIN acciones. Funciona: el
# cliente la acepta igual y abre el almacen.
ACCIONES_ALMACEN = {
    123211: [1000051, 1000054],   # Steam Bank Emplo (Steam Town)
    123276: [1000078, 1000079],   # City Banker (Edo City)
    123373: [1000122, 1000123],   # Fruity Bank Cler (Fruity Village)
    123438: [1000078, 1000079],   # Shuwa Bank Clerk (Shuwa Market)
}


# Opciones de dialogo que MANDAN A OTRO MAPA.
#
# El menu sale al PISAR un tornado de los que preguntan: el de (19,175) en
# Shuwa Market y el de (272,148) en Bayan Village. El mensaje es el mismo en
# los dos, el 125309, pero cada uno deja en su casilla.
#
# La segunda, "Elite Siam Square", lleva al stage 262, "Hell Siam Square", y
# deja en la MISMA casilla que la normal. Las dos estan medidas.
# La clave es (mapa DESDE EL QUE se pregunta, opcion), no la opcion sola: el
# mismo menu 125309 sale en dos sitios y cada uno deja en su casilla.
VIAJES_POR_OPCION = {
    # Shuwa Market, pisando el tornado de (19,175). Las dos dejan en la misma
    # casilla, que es casi el punto "Entrance" del jumpmap, el (286,8).
    (258, 125310): (261, [289, 11]),   # Siam Square
    (258, 125311): (262, [289, 11]),   # Hell Siam Square, la version Elite
    # Bayan Village, pisando el tornado de (272,148). Aqui las dos casillas
    # son distintas entre si y ninguna se parece a las de Shuwa.
    (259, 125310): (261, [10, 11]),
    (259, 125311): (262, [17, 7]),
}


def es_opcion(valor: int) -> bool:
    return valor >= PRIMERA_OPCION


def indice_opcion(valor: int) -> int:
    return valor - PRIMERA_OPCION


def opciones_de(linea: bytes):
    """Los ids de opcion que lleva una linea de dialogo."""
    if len(linea) < 9 or not linea[7]:
        return []
    n = linea[7]
    base = 9                   # las opciones van siempre justo tras la cabecera
    if len(linea) < base + 4 * n:
        return []
    return [struct.unpack_from('<I', linea, base + 4 * k)[0] for k in range(n)]


def respuesta_a(opcion_id: int, entidad: int = 0, val: int = 4,
                nombre: str = '', stage: int = 0, nivel: int = 0):
    """Devuelve tupla de sub-mensajes: apertura de tienda y/o cierre/continuacion de dialogo."""
    # --- Clank Oasis (407) y Commercial Street (419) ---
    # Las cuatro opciones son las mismas en los dos mapas (ver la nota de
    # propio()), asi que la tienda la decide el STAGE. El par que les toca
    # por orden de ciudad es 223/224 y 225/226, impar espadas y par magias.
    if stage in (407, 419) and opcion_id in (516649, 516651, 516653, 516655):
        cierre = struct.pack('<H', 0x0012) + FIN
        if opcion_id == 516653:                       # reparar
            return (struct.pack('<HBB', 0x004F, 0, 1), cierre)
        if opcion_id == 516655:                       # tienda general
            return (struct.pack('<HH', 0x0034, 3), cierre)
        oasis = (stage == 407)
        if opcion_id == 516649:                       # magias, el par
            tienda = 224 if oasis else 226
        else:                                         # espadas, el impar
            tienda = 223 if oasis else 225
        return (struct.pack('<HH', 0x0034, tienda), cierre)

    if (opcion_id in (5190, 5270, 7535, 7932, 7982, 7986, 7988, 12103,
                      508050, 508052, 508316, 508317,
                      # Whitefang Village (288): los dos Dev venden directo
                      # y el Merchant lo hace desde su segunda pagina.
                      508875, 508873, 509139, 509140, 509137, 509138,
                      # Coo Village (298)
                      509775, 509772, 509779, 509777, 509813, 509814,
                      # Rainbow Town (308)
                      510105, 510107, 510423, 510875, 510141, 510142,
                      # Twinkle Town (320)
                      511080, 511082, 511574, 511116, 511117,
                      # Specter Village (335)
                      511731, 511733, 511121, 511122, 511767, 511768,
                      # Teddy Amusement (347)
                      512966, 512968, 513005, 513006, 513002, 513003, 513007,
                      # Galaxia Square (355)
                      514115, 514113, 514122, 514123, 514127, 514128,
                      # Desolate Sea / Yatiss
                      514651, 514653, 514657, 514658,
                      # Chilly Village
                      515203, 515205, 515209, 515210,
                      # Busy Market
                      515846, 515848, 515852, 515853,
                      # Floral Alley
                      516189, 516191, 516196, 516197)
            or opcion_id in TIENDAS_POR_OPCION):
        shop_id = 0
        # 0. Lo primero: los NPC que venden DOS cosas segun la opcion.
        if (entidad, opcion_id) in TIENDAS_POR_ENTIDAD_Y_OPCION:
            shop_id = TIENDAS_POR_ENTIDAD_Y_OPCION[(entidad, opcion_id)]
        # 1. Prioridad: por entity_id exacto (garantiza tienda correcta por ciudad)
        elif entidad in TIENDAS_POR_ENTIDAD:
            shop_id = TIENDAS_POR_ENTIDAD[entidad]
        # 2. Vendedores de monturas segun ciudad (stage) si no vino en TIENDAS_POR_ENTIDAD
        elif 'Ride Seller C' in nombre:
            shop_id = {3: 57, 26: 60, 38: 59, 29: 58}.get(stage, 58)
        elif 'Ride Seller' in nombre:
            shop_id = {3: 12, 26: 15, 38: 14, 29: 13}.get(stage, 13)
        # 3. Mapeo general por nombre
        elif nombre:
            if nombre in TIENDAS_POR_NOMBRE:
                shop_id = TIENDAS_POR_NOMBRE[nombre]
            else:
                for k in sorted(TIENDAS_POR_NOMBRE.keys(), key=len, reverse=True):
                    if k.lower() in nombre.lower():
                        shop_id = TIENDAS_POR_NOMBRE[k]
                        break
        # 4. Fallback por opcion
        if not shop_id and opcion_id in TIENDAS_POR_OPCION:
            shop_id = TIENDAS_POR_OPCION[opcion_id]

        if shop_id:
            pkg_shop = struct.pack('<HH', 0x0034, shop_id)
            pkg_cierre = struct.pack('<H', 0x0012) + FIN
            return (pkg_shop, pkg_cierre)

    if opcion_id == 5976:
        if nivel >= 60:
            return (armar_linea(7503, val, [7505, 7506],
                                acciones=[0x0f42dc, 0x0f42dd]),)
        return (armar_linea(7504, val, [7507, 7508],
                            acciones=[0x0f42de, 0x0f42df]),)
    if opcion_id == 7509:
        return (armar_linea(7510, val), armar_linea(7511, val))
    if opcion_id == 7554 or opcion_id in (7505, 7506, 7507, 7508):
        return (struct.pack('<H', 0x0012) + FIN,)

    # Pet Expert: 6101 "Tell me about pets", 6103 "Pet Revival" (WND_PET_RESURRECT 0x0066)
    if opcion_id == 6101:
        return (armar_linea(6105, 48, [6106, 6107, 6108, 6109, 6110, 6111]),)
    if opcion_id == 6103:
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        pkg_revival = struct.pack('<HBB', 0x0066, 1, 0)
        return (pkg_revival, pkg_cierre)
    if opcion_id in (6104, 6111, 6119, 5665, 5793) or 5802 <= opcion_id <= 5812:
        return (struct.pack('<H', 0x0012) + FIN,)

    # Opcion 10110: "Quit the training" con Angels' Tutor.
    # La confirmacion es el 10124 con val 2, no el 10123: medido en la
    # captura, 8c270000 02 0000 02 00 | 8d270000 8e270000, o sea msg 10124,
    # val 2, dos opciones 10125 (si) y 10126 (no).
    if opcion_id == 10110:
        # Son DOS lineas, medidas en la captura: primero el 10123 suelto
        # (val 2, sin cadenas ni opciones) y despues el 10124 con las dos
        # opciones 10125 (si) y 10126 (no). Mandabamos solo el 10123.
        return (armar_linea(10123, 2, []),
                armar_linea(10124, 2, [10125, 10126],
                            acciones=[0x0f4393, 0x0f4271]))

    # Opcion 10109: "Graduation" con Angels' Tutor
    if opcion_id == 10109:
        pkg_pregunta = armar_linea(10118, val, [10119, 10120])
        return (pkg_pregunta,)

    # Opcion 10205: "I decided to be an Angel Protector".
    #
    # La confirmacion depende de la FACCION del NPC con el que hablas. La
    # tabla iba por id de totem y los cuatro Angeles del Graduation Palace no
    # estaban en ella, asi que con cualquiera de ellos salia la de Aurora.
    # Ahora va por nombre, que sirve para los totems y para los Angeles.
    #
    # Medido con el BreezeWood Angel: msg 10234, retrato 52, opciones 10235 y
    # 10236, y una accion 0x0f427d. De las otras tres no hay captura de la
    # accion, asi que van sin ella.
    if opcion_id == 10205:
        por_nombre = {
            'aurora': (10231, ()),
            'dark city': (10232, ()),
            'iron': (10233, ()),
            'breeze': (10234, (0x0f427d, 0)),
        }
        mid, acc = 10231, ()
        _n = (nombre or '').lower()
        for clave, (m, a) in por_nombre.items():
            if clave in _n:
                mid, acc = m, a
                break
        return (armar_linea(mid, val, [10235, 10236], None, list(acc)),)

    # Opcion 50002: "I have come here to register!" con el Angel de la
    # ciudad. Medido: cinco lineas seguidas y al final las misiones nuevas y
    # la de registro completada.
    if opcion_id == 50002:
        return tuple(armar_linea(m, 112) for m in
                     (50006, 50007, 50008, 50009, 50010, 50017))

    # Opcion 20018: "Send me back to the Angel Lyceum" del Angel de una
    # ciudad. Medido: contesta con el 50019 y al cerrarse el cuadro cambia al
    # mapa 41.
    #
    # Hay DOS numeros para la misma opcion segun el menu del que salga: el
    # de rango alto (55803) la lleva como 20018 y los de registro (50001)
    # como 50018. Solo estaba puesto el primero, asi que despues de
    # registrarse el boton no hacia nada.
    if opcion_id in CIUDAD_POR_OPCION and opcion_id % 10000 == 18:
        # Cada ciudad contesta con SU mensaje de traslado, no con el de
        # Breeze Woods. Antes se devolvia siempre el 50019, asi que en
        # Aurora, Dark City o Iron Castle el jugador leia el texto de otra
        # ciudad.
        _cfg = ANGEL_DE_CIUDAD[CIUDAD_POR_OPCION[opcion_id]]
        return (armar_linea(_cfg['msg_traslado'], 112),)

    # Opcion 10235: confirmar que si. NO cierra el cuadro: quedan dos lineas
    # mas antes del viaje. Medido con el BreezeWood Angel:
    #   c2s 10 -> 10240  "I will send you to the Breeze Woods..."
    #   c2s 01 -> 10241  "At last, the Lyceum leader Michael..."
    #   c2s 01 -> las misiones, el cierre y el cambio de mapa
    # Aqui se contestaba con el cierre directamente y por eso el NPC
    # teletransportaba en el acto, sin decir nada.
    if opcion_id == 10235:
        return (armar_linea(10240, val), armar_linea(10241, val))

    # Banco: la opcion del medio de la 5225 abre la pregunta de QUE almacen.
    #
    # Se quedaba sin contestar y el cuadro se cerraba solo, sin abrir nada. La
    # captura de Steam Town del 28/09/2026 tiene la secuencia entera: la 5225
    # ofrece [5030, 5032, 5033], el cliente manda 0x000B con 0x0b (indice 1,
    # la 5032) y el servidor contesta con la 5236 y sus dos opciones, la
    # propia y la de la corporacion.
    # Guardia de Bayan: al aceptar contesta la 8388 con cinco opciones. Que
    # hace cada una no se llego a ver, la captura se corta ahi.
    if opcion_id == 8386:
        return (armar_linea(8388, val, [8389, 8390, 8391, 8392, 8393],
                            acciones=[1000094, 1000095, 1000096, 1000097,
                                      1000098]),)

    # --- Joaquin: la segunda pagina del Smith y del Master ---
    # La primera opcion de los dos abre esta, donde se elige la banda de
    # nivel. Que tienda abre cada una depende del NPC, no de la opcion: por
    # eso va en TIENDAS_POR_ENTIDAD_Y_OPCION y no aqui.
    if opcion_id == 508046:
        # Las acciones son distintas en cada uno de los dos, medidas: el
        # Smith manda 1000121 y 1000072, y el Master 1000124 y 1000073.
        acc = ([1000124, 1000073] if 'Master' in (nombre or '')
               else [1000121, 1000072])
        return (armar_linea(508315, val, [508316, 508317], acciones=acc),)

    # --- Floral Alley: las segundas paginas ---
    # Copiadas de Chilly Village: el banquero explica en cuatro lineas y
    # vuelve al menu, y el mercader abre la 513011 con sus dos tiendas.
    if opcion_id == 516199:
        return (armar_linea(516202, val, []),
                armar_linea(516203, val, []),
                armar_linea(516204, val, []),
                armar_linea(516205, val, []),
                armar_linea(516198, val, [516199, 516200, 516201]))
    if opcion_id == 516200:
        return (armar_linea(516207, val, [516208, 516209]),)
    if opcion_id in (516195, 516196):             # Merchant
        return (armar_linea(513011, val, [516196, 516197]),)

    # --- Busy Market: las segundas paginas ---
    # El Bank Staff NO tiene la respuesta de cinco lineas: cada opcion suya
    # da una sola. La 515832 acaba sin opciones, la 515833 sigue.
    if opcion_id == 515832:
        return (armar_linea(515835, val, []),)
    if opcion_id == 515833:
        return (armar_linea(515840, val, [515841, 515842],
                            acciones=[1000021, 1000022]),)
    if opcion_id in (515850, 515852):             # Market Merchant
        return (armar_linea(513011, val, [515852, 515853],
                            acciones=[1000027, 1000028]),)

    # --- Chilly Village (region de Celestia): las segundas paginas ---
    # El Banker Elf contesta a la 515189 con CINCO lineas, igual que el
    # banquero de Galaxia: cuatro de explicacion y la quinta vuelve al menu.
    if opcion_id == 515189:
        return (armar_linea(515192, val, []),
                armar_linea(515193, val, []),
                armar_linea(515194, val, []),
                armar_linea(515195, val, []),
                armar_linea(515188, val, [515189, 515190],
                            acciones=[1000009, 1000010]))
    if opcion_id == 515190:
        return (armar_linea(515197, val, [515198, 515199],
                            acciones=[1000014, 1000015]),)
    if opcion_id in (515207, 515209):             # Merchant Elf
        return (armar_linea(513011, val, [515209, 515210],
                            acciones=[1000020, 1000021]),)

    # --- Desolate Sea / Yatiss: las segundas paginas ---
    if opcion_id == 514638:                       # Yatiss Banker
        return (armar_linea(514645, val, [514646, 514647],
                            acciones=[1000060, 1000061]),)
    if opcion_id == 150102:                       # Manager Pete
        return (armar_linea(150104, val, []),)
    # El Merchant reusa la 513011, la misma linea que los de Teddy y Galaxia,
    # con sus dos tiendas. La segunda opcion vuelve a la misma pagina.
    if opcion_id in (514655, 514657):
        return (armar_linea(513011, val, [514657, 514658],
                            acciones=[1000066, 1000067]),)

    # --- Galaxia Square (355): las segundas paginas ---
    #
    # El Smith y el Master comparten la 514121 con las mismas dos opciones,
    # igual que en Specter; la tienda sale de la pareja (entidad, opcion).
    PAGINA2_GALAXIA = {
        514119: [1000053, 1000054],   # Star Smith
        514117: [1000055, 1000056],   # Star Master
    }
    if opcion_id in PAGINA2_GALAXIA:
        return (armar_linea(514121, val, [514122, 514123],
                            acciones=PAGINA2_GALAXIA[opcion_id]),)

    # El Merchant de Galaxia, con sus dos tiendas.
    if opcion_id == 514125:
        return (armar_linea(513011, val, [514127, 514128],
                            acciones=[1000051, 1000052]),)

    # El banquero de Galaxia. La opcion 514100 abre su segunda pagina,
    # pero la 514099 contesta con CINCO lineas de corrido: cuatro de
    # explicacion y la quinta vuelve al menu con sus dos opciones. No pasa
    # en ninguna de las otras seis ciudades.
    if opcion_id == 514100:
        return (armar_linea(514107, val, [514108, 514109],
                            acciones=[1000043, 1000044]),)
    if opcion_id == 514099:
        return (armar_linea(514102, val, []),
                armar_linea(514103, val, []),
                armar_linea(514104, val, []),
                armar_linea(514105, val, []),
                armar_linea(514098, val, [514099, 514100],
                            acciones=[1000038, 1000042]))

    # --- Whitefang Village (288): la segunda pagina ---
    #
    # El Smith, el Master y el Merchant abren LA MISMA linea, la 509136, y
    # lo unico que cambia son sus acciones. Por eso no vale una tabla por
    # opcion a secas: hay que mirar cual fue la opcion que la abrio.
    PAGINA2_WHITEFANG = {
        508871: [1000107, 1000108],   # Vulcan Master
        508868: [1000105, 1000106],   # Vulcan Smith
        509043: [1000103, 1000104],   # Vulcan Merchant
        509139: [1000103, 1000104],   # Merchant, al volver a la pagina
    }
    if opcion_id in PAGINA2_WHITEFANG:
        # Las opciones de la pagina tambien cambian: el Merchant elige entre
        # sus dos tiendas y los otros dos entre dos bandas de recetas.
        es_merchant = opcion_id in (509043, 509139)
        ops = [509139, 509140] if es_merchant else [509137, 509138]
        # El Merchant arrastra su retrato fijo tambien a la segunda pagina.
        v = 1006 if es_merchant else val
        return (armar_linea(509136, v, ops,
                            acciones=PAGINA2_WHITEFANG[opcion_id]),)

    # --- Teddy Amusement (347): las paginas encadenadas ---
    PAGINA2_TEDDY = {
        512961: [1000118, 1000119],   # Park Smith
        512964: [1000115, 1000116],   # Park Instructor
    }
    if opcion_id in PAGINA2_TEDDY:
        return (armar_linea(513004, val, [513005, 513006],
                            acciones=PAGINA2_TEDDY[opcion_id]),)

    # El Merchant de Teddy: TRES tiendas en su segunda pagina.
    if opcion_id in (513000, 513002):
        return (armar_linea(513011, val, [513002, 513003, 513007, 5020],
                            acciones=[1000128, 1000129, 1000130, 0]),)

    # El banquero de Teddy, con su tercera pagina.
    if opcion_id == 512971:
        return (armar_linea(512978, val, [512979, 512980],
                            acciones=[1000110, 1000111]),)
    if opcion_id == 512979:
        return (armar_linea(513008, val, [513009, 513010],
                            acciones=[1000131, 1000132]),)

    # --- Specter Village (335): las segundas paginas ---
    #
    # El Smith y el Instructor abren la misma 511769 con las mismas dos
    # opciones y distintas acciones; la tienda sale luego de la pareja
    # (entidad, opcion).
    PAGINA2_SPECTER = {
        511726: [1000052, 1000053],   # Specter Smith
        511729: [1000055, 1000056],   # Specter Instructor
    }
    if opcion_id in PAGINA2_SPECTER:
        return (armar_linea(511769, val, [511121, 511122],
                            acciones=PAGINA2_SPECTER[opcion_id]),)

    # El Merchant de Specter, con sus dos tiendas.
    if opcion_id in (511765, 511767):
        return (armar_linea(511764, val, [511767, 511768, 5020],
                            acciones=[1000085, 1000086, 0]),)

    # El banquero de Specter.
    if opcion_id == 511736:
        return (armar_linea(511743, val, [511744, 511745],
                            acciones=[1000064, 1000065]),)

    # --- Twinkle Town (320): las segundas paginas ---
    #
    # El Smith y el Instructor abren la misma 511118 con las mismas cuatro
    # opciones y distintas acciones; la tienda de la 511574 sale luego de
    # la pareja (entidad, opcion).
    PAGINA2_TWINKLE = {
        511075: [1000077, 1000078, 1000133, 1000134],   # Twinkle Smith
        511078: [1000080, 1000081, 1000131, 1000132],   # Twinkle Instructor
    }
    if opcion_id in PAGINA2_TWINKLE:
        return (armar_linea(511118, val, [511126, 511127, 511573, 511574],
                            acciones=PAGINA2_TWINKLE[opcion_id]),)

    # El Merchant de Twinkle, con sus dos tiendas.
    if opcion_id in (511114, 511116):
        return (armar_linea(510422, val, [511116, 511117, 511115],
                            acciones=[1000106, 1000107, 0]),)

    # El banquero de Twinkle.
    if opcion_id == 511085:
        return (armar_linea(511092, val, [511093, 511094],
                            acciones=[1000089, 1000090]),)

    # Rich Bill: su opcion contesta una linea suelta, sin opciones.
    if opcion_id == 140502:
        return (armar_linea(140504, val, []),)

    # --- Rainbow Town (308): las paginas encadenadas ---
    #
    # El Instructor y el Smith abren LA MISMA linea, la 510422, con las
    # mismas seis opciones, y lo unico distinto son sus acciones. Como en
    # Whitefang, hay que mirar que opcion la abrio y no solo cual es.
    #
    # Y el Instructor tiene una tercera pagina detras de la 5366, con otras
    # cuatro opciones.
    PAGINA2_RAINBOW = {
        510103: [1000074, 1000032, 1000117, 1000118, 1000137, 0],  # Instructor
        510423: [1000074, 1000032, 1000117, 1000118, 1000137, 0],  # al volver
        510100: [1000073, 1000031, 1000115, 1000116, 1000138, 0],  # Smith
    }
    if opcion_id in PAGINA2_RAINBOW:
        return (armar_linea(510422, val,
                            [510423, 510424, 510766, 510767, 5366, 5020],
                            acciones=PAGINA2_RAINBOW[opcion_id]),)

    # La TERCERA pagina del Instructor.
    if opcion_id == 5366:
        return (armar_linea(510422, val, [510874, 510875, 5367, 5020],
                            acciones=[1000135, 1000136, 1000057, 0]),)

    # El Merchant de Rainbow, con sus dos tiendas.
    if opcion_id in (510139, 510141):
        return (armar_linea(510138, 1007, [510141, 510142, 5020],
                            acciones=[1000063, 1000064, 0]),)

    # El banquero de Rainbow.
    if opcion_id == 510110:
        return (armar_linea(510117, val, [510118, 510119],
                            acciones=[1000040, 1000041]),)

    # --- Coo Village (298): las segundas paginas ---
    PAGINA2_COO = {
        509811: [1000014, 1000015],   # Magikale Merchant
        509813: [1000014, 1000015],   # al volver a la pagina
    }
    if opcion_id in PAGINA2_COO:
        return (armar_linea(509810, val, [509813, 509814],
                            acciones=PAGINA2_COO[opcion_id]),)

    # El banquero de Coo: su segunda pagina.
    if opcion_id == 509782:
        return (armar_linea(509789, val, [509790, 509791],
                            acciones=[1000006, 1000007]),)

    # El banquero Vulcan: como el de Joaquin, con sus propios numeros.
    if opcion_id == 508878:
        return (armar_linea(508885, val, [508886, 508887],
                            acciones=[1000043, 1000044]),)

    # El banquero de Joaquin: sus mensajes son propios, no los 5225/5236.
    if opcion_id == 508055:
        return (armar_linea(508062, val, [508063, 508064],
                            acciones=[1000067, 1000068]),)

    if opcion_id == 5032:
        return (armar_linea(5236, val, [5237, 5238],
                            acciones=ACCIONES_ALMACEN.get(entidad, [])),)

    # Almacen / Banco (Bao Clerk y Chief Director)
    if opcion_id in (5030, 5237, 508054, 508063, 516208):
        # Abrir almacen personal: WND_WAREHOUSE (opcode 0x002B)
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        # El almacen es el 0x004E, NO el 0x002B.
        #
        # Con el 0x002B el cliente no abria nada y soltaba un aviso de la
        # lista de amigos, porque ese opcode es de otro mensaje. El bueno
        # esta medido: en la captura de Edo City del 28/09/2026, al elegir
        # "I wish to use my own warehouse" el servidor contesta un 0x004E de
        # 824 bytes y detras el cierre del dialogo.
        #
        # El cuerpo resulto ser EL MISMO que el del inventario 0x001A: un
        # LE32 con el numero de entradas y detras las entradas, de 86 bytes
        # las corrientes y 119 las equipables. Los 824 bytes de la captura son
        # cuatro de cabecera y ocho entradas, cuatro de cada clase.
        # Marcador: app.py lo sustituye por el almacen de verdad, armado con
        # lo que el personaje tenga guardado. El cuerpo es el mismo que el del
        # inventario 0x001A -- cuenta y entradas de 86 o 119 bytes -- y eso lo
        # sabe inventario.py, no este archivo.
        pkg_bank = struct.pack('<HI', 0x004E, 0)
        return (pkg_bank, pkg_cierre)

    # Skill Angel: 5024 ("Change Skill" / redistribucion) vs 5820 ("Choose profession skills")
    if opcion_id == 5024:
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        # 0x001D kind=10 es la ventana nativa de redistribucion de puntos
        pkg_skill_reset = struct.pack('<HIBBII', 0x001D, entidad, 1, 10, 0, 0)
        return (pkg_skill_reset, pkg_cierre)
    if opcion_id == 5820:
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        # 0x001D kind=12 es la ventana de seleccion de profesion
        pkg_prof = struct.pack('<HIBBII', 0x001D, entidad, 1, 12, 0, 0)
        return (pkg_prof, pkg_cierre)

    # Reparacion de equipo (Repair Angel: 5101 / Repair Expert: 5227 / Repair Robot: 7990) -> abre WND_REPAIR (opcode 0x004F)
    # El 508866 es el del Vulcan Repairer de Whitefang: estaba pulsado en la
    # captura y el extractor se lo salto, pero contesta igual que los demas.
    # El 509770 es el Magikale Worker de Coo Village y el 510098 el Chrono
    # Worker de Rainbow: los dos, pese al nombre, son el reparador. Su clic quedo sin respuesta en la captura y
    # va aqui por lo que hace, no por lo medido.
    if opcion_id in (5101, 5227, 7990, 112016, 117123, 121017, 508044,
                     508866, 509770, 510098, 511073, 511724, 512959, 514111, 514649, 515201, 515844, 516193):
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        # Los dos bytes van 00 01, no 01 00. Estaban del reves desde siempre
        # y no se habia notado porque nadie comparo el paquete con la captura:
        # las NUEVE aperturas de la ventana de reparacion que hay capturadas,
        # de tres ciudades distintas, mandan las mismas 0001.
        pkg_repair = struct.pack('<HBB', 0x004F, 0, 1)
        return (pkg_repair, pkg_cierre)

    # Healer / Curacion (5140 "Revival." / 5178)
    if opcion_id in (5140, 5178):
        return (armar_linea(5178, val, []),)

    # Cupid: 5747 ("Set the place for your revival.") fija donde revives.
    #
    # Son DOS lineas de dialogo, 5751 y 5752, y NADA en el chat. Aqui se
    # mandaba un aviso escrito a mano ("Revival point has been set to X!")
    # que el juego no manda: el texto real sale del propio 5751, que dice
    # "Now, your [renascence place] is registered here...".
    if opcion_id == 5747:
        return (armar_linea(5751, val), armar_linea(5752, val))

    if opcion_id == 5746:
        # Descripcion de ayuda
        return (armar_linea(5749, val, []),)
    if opcion_id == 5748:
        return (struct.pack('<H', 0x0012) + FIN,)

    # Director Wolay: 5080 (Return to City), 5081 (Leave)
    if opcion_id == 5080:
        return (armar_linea(5082, val, []),)
    if opcion_id in (5081, 20002, 20004):
        return (struct.pack('<H', 0x0012) + FIN,)

    # Angel Raphael (Guide Palace)
    if opcion_id == 5009:  # "I don't want to join in." -> 5010 (preguntar si esta seguro)
        return (armar_linea(5010, 3, [5011, 5012]),)
    # 5278 y 5371 son los "Quit" de los dos vendedores de recetas de Snowball
    # Village; sin ellos el dialogo se quedaba abierto al decir que no.
    if opcion_id in (5012, 5191, 5242, 5046, 5059, 5064, 5271, 7536, 5238, 7933, 7983, 7991,
                     5278, 5371, 112004, 5033, 5020, 121004,
                     8387, 508047, 508056, 508064):  # Quit / cerrar
        return (struct.pack('<H', 0x0012) + FIN,)

    # Angel Raphael (Fighting Palace): 5063 "I'm ready to go to the Angel Lyceum."
    if opcion_id == 5063:
        return (armar_linea(5065, val, []),)

    sig = RESPUESTAS.get(opcion_id)
    if sig is None:
        return (struct.pack('<H', 0x0012) + FIN,)
    return (armar_linea(sig, val, []),)


def guion_fighting_palace(kills: int, nombre: str):
    """Guion de Angel Raphael en Fighting Palace segun las muertes de Little Slarm."""
    val = 5
    if kills < 2:
        return [
            armar_linea(5048, val, [], strings=["1", nombre])[2:],
            armar_linea(5049, val, [])[2:],
            armar_linea(5050, val, [])[2:],
            armar_linea(5051, val, [])[2:],
            armar_linea(5052, val, [])[2:],
            armar_linea(5053, val, [])[2:],
            armar_linea(5054, val, [])[2:],
            armar_linea(5055, val, [])[2:],
            armar_linea(5056, val, [5058, 5059])[2:],
        ]
    else:
        return [
            armar_linea(5060, val, [])[2:],
            armar_linea(5061, val, [])[2:],
            armar_linea(5062, val, [5063, 5064])[2:],
        ]




