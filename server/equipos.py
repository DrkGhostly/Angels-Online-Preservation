"""Equipos (party): invitar, aceptar, salir.

TODO ESTO SALE DE UNA CAPTURA DEL GLOBAL con tres cuentas montando un equipo
de verdad -- Yuki, KarmaSilk y KarmaWeapon -- grabada con el proxy delante.
Son los tres ficheros mundo_141825, mundo_141841 y mundo_144108. Sin esa
captura no habria habido forma: de las 1.230 sesiones anteriores del
proyecto, ninguna tiene un solo paquete de grupo, porque quien capturaba iba
siempre solo.

EL FLUJO, leido de la captura paquete a paquete:

    1. el lider manda   c2s 0x0017  con el NOMBRE del invitado
    2. al invitado le llega  s2c 0x0023  con el id y el nombre del lider
       -> ese es el cartel de "X te invita"
    3. el invitado contesta  c2s 0x0018  con [01][u32 0]
    4. a TODOS los del grupo les llega  s2c 0x0024  con la lista entera

C2S 0x0017, 34 bytes: el nombre del invitado en ASCIIZ al principio. Lo que
viene detras es BASURA DE PILA del cliente -- en las tres invitaciones
capturadas sale distinto y hasta con restos legibles como "t\\0 3\\0 2\\0
_\\0 1\\0 . \\0 D L L" -- asi que no se lee nada mas que el nombre.

C2S 0x0018, 5 bytes: [u8 accion][u32]. Medido el 1 = aceptar, que es lo que
mandaron los dos invitados. El lider mando un 4 en mitad de la sesion. Las
nativas del cliente dicen que por este mismo opcode van groupdeny,
groupdisband, groupjoin, groupkick, groupleave y grouppromote, o sea seis
acciones; solo el 1 esta confirmado y el resto se tratan como "salir", que
es lo seguro: deshacer el grupo nunca deja a nadie colgado.

S2C 0x0024, la lista: cabecera de 10 bytes y 98 por miembro.

    cabecera  +0  u32 ???          (0x400011ac en una sesion, 0x400011d3 en otra)
              +4  u8  0
              +5  u32 char_id del lider
              +9  u8  cuantos miembros
    miembro   +0  u32 char_id
              +4  u16 ???
              +6  u16 ???
              +8  nombre ASCIIZ
              +41 u16 nivel
              +51 u8  100   (un porcentaje, siempre 100 en la captura)

Las cuentas cuadran: 10 + 98 = 108, 10 + 2*98 = 206 y 10 + 3*98 = 304, que
son exactamente los tres tamanos que se vieron segun el grupo tenia uno, dos
o tres miembros.

S2C 0x0023, 38 bytes: u32 char_id del lider, nombre ASCIIZ y relleno.

NO CONFUNDIR CON LA GUILD. En la misma captura salen dos paquetes mas con
nombres dentro y no son del grupo: el 0x0055 (257 B) lleva "Moonlights",
que es el nombre de la GUILD, y el 0x0054 (232 B) su cartel -- "Se Acepta
de Todo / Mancos, Los del Genshin, Pinwinos..." --. Los tres personajes del
equipo son Yuki, KarmaSilk y KarmaWeapon, y son exactamente los tres que
aparecen en el 0x0024 de 304 bytes.
"""
import logging
import struct

log = logging.getLogger('equipos')

INVITAR = 0x0017          # c2s, lo manda el lider con el nombre
ACCION = 0x0018           # c2s, [u8 accion][u32]
CARTEL = 0x0023           # s2c, "X te invita"
LISTA = 0x0024            # s2c, la lista del grupo

ACEPTAR = 1               # medido
TAM_MIEMBRO = 98
CABECERA = 10

# char_id del lider -> [sesiones], en orden de entrada (el lider primero).
_GRUPOS = {}
# char_id -> char_id del lider de su grupo
_DE_QUIEN = {}
# char_id del invitado -> char_id del que le invito, mientras no conteste
_PENDIENTES = {}


def _char_id(ses) -> int:
    p = getattr(ses, 'personaje', None)
    return int(getattr(p, 'char_id', 0) or 0) if p else 0


def _nombre(ses) -> str:
    p = getattr(ses, 'personaje', None)
    return (getattr(p, 'nombre', '') or '') if p else ''


def grupo_de(ses):
    """Las sesiones del grupo de ese jugador, o [] si va solo."""
    lider = _DE_QUIEN.get(_char_id(ses))
    return list(_GRUPOS.get(lider) or []) if lider else []


def cartel_de_invitacion(ses_lider) -> bytes:
    """El s2c 0x0023 que le saca el cuadro al invitado."""
    b = bytearray(38)
    struct.pack_into('<I', b, 0, _char_id(ses_lider))
    n = _nombre(ses_lider).encode('ascii', 'replace')[:28]
    b[4:4 + len(n)] = n
    return struct.pack('<H', CARTEL) + bytes(b)


def lista_del_grupo(lider_id) -> bytes:
    """El s2c 0x0024 con los miembros, tal como lo arma el servidor real."""
    miembros = _GRUPOS.get(lider_id) or []
    b = bytearray(CABECERA + TAM_MIEMBRO * len(miembros))
    struct.pack_into('<I', b, 0, 0x400011AC)
    b[4] = 0
    struct.pack_into('<I', b, 5, int(lider_id))
    b[9] = len(miembros) & 0xFF
    for i, s in enumerate(miembros):
        o = CABECERA + i * TAM_MIEMBRO
        p = getattr(s, 'personaje', None)
        struct.pack_into('<I', b, o, _char_id(s))
        n = _nombre(s).encode('ascii', 'replace')[:30]
        b[o + 8:o + 8 + len(n)] = n
        if p is not None:
            struct.pack_into('<H', b, o + 41,
                             min(0xFFFF, int(getattr(p, 'nivel', 1) or 1)))
            b[o + 51] = 100
    return struct.pack('<H', LISTA) + bytes(b)


def _avisar(lider_id):
    """Le manda la lista nueva a todos los del grupo."""
    paquete = lista_del_grupo(lider_id)
    for s in list(_GRUPOS.get(lider_id) or []):
        try:
            s.enviar(paquete)
        except Exception:
            log.debug('no se pudo mandar la lista', exc_info=True)


def invitar(ses, nombre_invitado, buscar_sesion):
    """El lider invita por nombre. `buscar_sesion` resuelve nombre -> sesion."""
    nombre_invitado = (nombre_invitado or '').strip()
    if not nombre_invitado or nombre_invitado == _nombre(ses):
        return False, 'no hay a quien invitar'
    otro = buscar_sesion(nombre_invitado)
    if otro is None:
        return False, 'no esta conectado'
    if _DE_QUIEN.get(_char_id(otro)):
        return False, 'ya esta en un grupo'
    # El que invita arma el grupo si todavia no lo tiene.
    mio = _DE_QUIEN.get(_char_id(ses))
    if not mio:
        mio = _char_id(ses)
        _GRUPOS[mio] = [ses]
        _DE_QUIEN[mio] = mio
    _PENDIENTES[_char_id(otro)] = mio
    try:
        otro.enviar(cartel_de_invitacion(ses))
    except Exception:
        log.debug('no se pudo mandar el cartel', exc_info=True)
        return False, 'no se pudo avisar'
    log.info('%s invita a %s', _nombre(ses), nombre_invitado)
    return True, ''


def aceptar(ses):
    """El invitado dice que si."""
    yo = _char_id(ses)
    lider = _PENDIENTES.pop(yo, None)
    if not lider or lider not in _GRUPOS:
        return False
    if _DE_QUIEN.get(yo):
        return False
    _GRUPOS[lider].append(ses)
    _DE_QUIEN[yo] = lider
    _avisar(lider)
    log.info('%s entra al grupo de %s', _nombre(ses), lider)
    return True


def salir(ses):
    """El jugador deja el grupo, o se desconecta.

    Si se va el lider el grupo se deshace: no se sabe que paquete usa el
    servidor real para pasar el mando -- grouppromote va por el mismo 0x0018
    y no se capturo -- y dejar un grupo sin lider es peor que deshacerlo.
    """
    yo = _char_id(ses)
    _PENDIENTES.pop(yo, None)
    lider = _DE_QUIEN.pop(yo, None)
    if not lider:
        return False
    miembros = _GRUPOS.get(lider) or []
    if ses in miembros:
        miembros.remove(ses)
    if yo == lider or len(miembros) <= 1:
        for s in list(miembros):
            _DE_QUIEN.pop(_char_id(s), None)
        _GRUPOS.pop(lider, None)
        vacia = struct.pack('<H', LISTA) + bytes(CABECERA)
        for s in miembros + [ses]:
            try:
                s.enviar(vacia)
            except Exception:
                pass
        log.info('el grupo de %s se deshace', lider)
    else:
        _GRUPOS[lider] = miembros
        _avisar(lider)
        try:
            ses.enviar(struct.pack('<H', LISTA) + bytes(CABECERA))
        except Exception:
            pass
    return True


def accion(ses, codigo):
    """El c2s 0x0018. Solo el 1 (aceptar) esta medido."""
    if codigo == ACEPTAR:
        return 'aceptar' if aceptar(ses) else 'nada'
    # Las otras cinco -- deny, disband, kick, leave, promote -- van por el
    # mismo opcode y no se capturaron. Tratarlas como "salir" es lo seguro.
    return 'salir' if salir(ses) else 'nada'


def olvidar_todo():
    _GRUPOS.clear()
    _DE_QUIEN.clear()
    _PENDIENTES.clear()
