"""
Creacion de personaje y actualizacion de ranura.

El cliente manda 0x0003 (57 B) al confirmar el dialogo "Character Info", y
espera 0x0001 con la ficha de la ranura creada.

Paquete 0x0003 CREAR, medido de una sesion real del cliente:

    +0   LE32   indice de ranura (0..2)
    +4   LE16   ?
    +6   char   nombre, terminado en nulo
    +20  LE32   ?
    +32..47     basura de pila cuando los campos opcionales quedan en
                "Choose." (Place/Job/Face/Pty). No se interpretan.

Valores del personaje nuevo: nivel 1 y mapa 41 "Angel Lyceum", que es el
nombre que usan las propias tarjetas del cliente ("Angel Lyceum ID Card") y
figura asi en stage.xml. NO se inventan stats.
"""
import json
import struct
import pathlib

MAPA_INICIAL = 51                 # Guide Palace (stage.name en content.db)
# Medido de la sesion real de AngelWar (mundo_163130_471128):
# Karmav2 aparece exactamente en tile=(247,24), frente a Angel Raphael (244,30),
# Interface Tutor (236,27) a la izquierda y Angel Aide (252,27) a la derecha.
TILE_INICIAL = tuple(int(x) for x in
                     __import__('os').environ.get('AO_TILE', '247,24').split(','))
NIVEL_INICIAL = 1
CLASE_INICIAL = 0          # "Novice" segun class.xml

# Stats iniciales REALES medidos de la tarjeta de seleccion en AngelWar:
# HP 205/205 y MP 154/154, mapa "Guide Palace" (id 51).
HP_INICIAL = 205
HP_MAX_INICIAL = 205
MP_INICIAL = 154
MP_MAX_INICIAL = 154


def parsear_creacion(cuerpo: bytes) -> dict:
    ranura = struct.unpack_from('<I', cuerpo, 0)[0] if len(cuerpo) >= 4 else 0
    fin = cuerpo.find(b'\x00', 6)
    nombre = cuerpo[6:fin if fin > 6 else 6].decode('ascii', 'replace').strip()
    # Los bytes +1..+5 llevan lo que el jugador eligio en el dialogo de
    # creacion (genero, peinado, etc.). Antes se tiraban y la apariencia
    # quedaba SIEMPRE en [0,0,0,8,8], que el cliente dibuja como mujer.
    # Medido: hombre -> 01 01 01 00 00. El primero es el genero.
    elegidos = list(cuerpo[1:6]) if len(cuerpo) >= 6 else []
    return {'ranura': ranura & 0xFF, 'nombre': nombre, 'elegidos': elegidos}


# Kit con el que arranca un personaje. Los id salen de item.xml y estan
# cruzados campo a campo contra las capturas de pantalla del cliente: peso 10,
# no comerciable, no almacenable, nivel minimo 1 y 5, "7 free slots" y la lista
# de contenido del Growth Box coinciden las seis veces.
#
# La ropa del cuerpo esta CONFIRMADA en el trafico real: el 0x001B que el
# servidor privado manda al equipar lleva el item 26 con su id de instancia.
#
# La Newborn Gift Box depende de la clase, por eso va aparte:
#     1944  Archer y Productor
#     1948  Guerrero
#     1952  Mago
# Se entrega al elegir clase, no al crear el personaje (el tooltip pide nivel 5).
CAJA_POR_CLASE = {'arquero': 1944, 'productor': 1944,
                  'guerrero': 1948, 'mago': 1952}

ROPA_INICIAL = {
    'cuerpo':  26,      # Students' Uniform  -- va equipada, da +10 de defensa
    'guantes': 28,      # Students' Gloves
    'zapatos': 30,      # Students' shoes
}
INVENTARIO_INICIAL = [
    20103,              # Level 1-10 Growth Box
]

# OJO: todavia no se entregan. Falta poder CONSTRUIR el 0x001B (el contenido
# del contenedor); hoy server/equipo.py solo sabe reproducir los dos estados
# que se capturaron. Ver docs/01_HECHOS_VERIFICADOS.md.


def apariencia_de_creacion(elegidos) -> list:
    """Apariencia inicial a partir de lo elegido en el dialogo de creacion.

    Medido con dos personajes de hombre:
        01 01 01 00 00   (peinado y color distintos)
        01 00 01 03 00   (peinado por defecto, color gris)
    O sea: +1 genero, +2 peinado, +4 color de pelo (el +3 y el +5 no
    cambiaron). Se guardan los CINCO tal cual los manda el cliente, que es lo
    que hace un servidor real: los devuelve en la ficha de la lista y en la
    del mundo. Si no llega nada, se usa la apariencia por defecto de siempre.
    """
    if not elegidos or len(elegidos) < 5:
        return [0, 0, 0, 8, 8]
    return [int(v) & 0xFF for v in list(elegidos)[:5]]


def personaje_nuevo(nombre: str, ranura: int, char_id: int,
                    elegidos=None) -> dict:
    return {
        'nombre': nombre,
        'char_id': char_id,
        'ranura': ranura,
        'nivel': NIVEL_INICIAL,
        'class_id': CLASE_INICIAL,
        'stage_id': MAPA_INICIAL,
        'faction': 'Heaven',
        'hp': HP_INICIAL,
        'hp_max': HP_MAX_INICIAL,
        'mp': MP_INICIAL,
        'mp_max': MP_MAX_INICIAL,
        'apariencia': apariencia_de_creacion(elegidos),
        'tile_x': TILE_INICIAL[0],
        'tile_y': TILE_INICIAL[1],
        'habilidades': [],
        'barra': [],
        'quests': [],
        'oro': 0,
        'inventario': {
            '0': 1,                           # Gold (item ID 1)
            '2': ROPA_INICIAL['cuerpo'],      # 26 Students' Uniform, puesta
        },
    }


def respuesta_creacion(ranura: int, p: dict) -> bytes:
    """Sub-mensaje 0x0001: el cliente copia 147 B desde el offset 4 a la
    ficha de la ranura y vuelve a dibujar la pantalla de seleccion."""
    from lista_personajes import _ficha
    cuerpo = bytearray(152)              # [LE16 error][ficha de 147 B + extra]
    # cuerpo[0:2] = 0  -> exito
    p_creacion = dict(p)
    # Bit 0x10000000 le indica al cliente inicializar HP Max = 205, MP Max = 154 y Job = Novice
    p_creacion['flags'] = p.get('flags') or 0x10000000
    _ficha(cuerpo, 2, ranura, p_creacion)
    return struct.pack('<H', 0x0001) + bytes(cuerpo)


def guardar(usuario: str, p: dict, archivo: pathlib.Path = None):
    import cuentas
    cuentas.guardar_personaje_nuevo(usuario, p)
