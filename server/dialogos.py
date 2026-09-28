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


def propio(nombre: str, faccion: str = "Heaven", jugador: str = "",
           visto_michael: bool = False, stage: int = 0,
           registrado: bool = False, entidad: int = 0, val: int = 0):
    """Una linea de dialogo para ese NPC, o None si no se le conoce ninguna."""
    npc_val = val or (val_por_entidad(entidad, 0) if entidad else 0)

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
        return [armar_linea(5745, 6, [5746, 5747, 5748])[2:]]
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

    # Atlantis - Blue Ocean (Stage 90)
    if 'Spell Researcher' in nombre:
        return [armar_linea(7533, npc_val or 158, [7535, 7536])[2:]]
    if 'Skill Researcher' in nombre:
        return [armar_linea(7534, npc_val or 108, [7535, 7536])[2:]]
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
    'Spell Researcher': 89,  # Atlantis Blue Ocean - Spells (Action Sealed IV, Power Shield I-II, Anti-locked Shield I-III)
    'Skill Researcher': 90,  # Atlantis Blue Ocean - Skills (Dream Slaughter IV, Silence IV, Defence Wall II-IV, Speedup Attack II-IV, Anti-locked Tactics I-III)
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
}

# Tiendas especificas segun la entidad del NPC que vende
TIENDAS_POR_ENTIDAD = {
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
}

# Opciones de dialogo que abren la ventana de tienda (WND_NPCSALE).
# Medido en sub_605190/sub_656E70 del cliente: opcode S->C 0x0034 [LE16 shop_id].
TIENDAS_POR_OPCION = {
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
    if opcion_id in (5190, 5270, 7535, 7932, 7982, 7986, 7988, 12103) or opcion_id in TIENDAS_POR_OPCION:
        shop_id = 0
        # 1. Prioridad: por entity_id exacto (garantiza tienda correcta por ciudad)
        if entidad in TIENDAS_POR_ENTIDAD:
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

    # Almacen / Banco (Bao Clerk y Chief Director)
    if opcion_id in (5030, 5237):
        # Abrir almacen personal: WND_WAREHOUSE (opcode 0x002B)
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        pkg_bank = struct.pack('<HII', 0x002B, 1, 0)
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
    if opcion_id in (5101, 5227, 7990):
        pkg_cierre = struct.pack('<H', 0x0012) + FIN
        pkg_repair = struct.pack('<HBB', 0x004F, 1, 0)
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
    if opcion_id in (5012, 5191, 5242, 5046, 5059, 5064, 5271, 7536, 5238, 7933, 7983, 7991):  # Quit / cerrar
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




