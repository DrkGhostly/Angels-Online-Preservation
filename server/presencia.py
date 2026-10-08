"""Que los jugadores se vean entre ellos.

HASTA AHORA EL SERVIDOR NO TENIA NADA DE ONLINE. No es que las instancias
estuvieran separadas: lo estaban TODOS los mapas. Se comprobo buscando
cualquier envio de una sesion a otra y no habia ni uno; la lista de sesiones
de mundo (`self.mundos`) solo se usaba para que la consola de GM supiera a
quien darle un item. Cada jugador tenia su copia del mundo, con sus propios
monstruos armados por `_monstruos_de()` al cambiar de mapa.

Esto es la primera capa de las tres que hacen falta:

    1. PRESENCIA  <- esto
       verse, verse moverse y verse desaparecer.
    2. MUNDO COMPARTIDO
       que los monstruos cuelguen del mapa y no de la sesion, con la exp y
       el botin repartidos. Es el paso que toca el combate entero.
    3. EQUIPOS
       los opcodes 0x0017 (groupinvite) y 0x0018 (el resto: join, leave,
       kick, promote, disband, deny) y, encima, las copias de instancia por
       equipo.

EL PAQUETE ES EL 0x0001, Y SE SUPO POR UNA CAPTURA. El primer intento uso
el 0x0008, que es el que dibuja NPC y monstruos, y NO FUNCIONO: dos clientes
en Bling Plaza, en casillas pegadas, no se veian. Lo que faltaba era una
captura con jugadores de verdad dentro, y la trajo la sesion del Global con
tres cuentas montando un equipo (Yuki, KarmaSilk y KarmaWeapon).

Buscando que paquetes S2C llevan el nombre de un jugador salio en seguida:

    0x0026  98 B   x14845   la ficha de un jugador, el mismo bloque de 98
                            bytes que usa cada miembro en la lista del grupo
    0x0001  184 B  x73      APARECE UN JUGADOR

Y el 0x0001 se confirmo cruzandolo con el movimiento: las cinco entidades
que salen en sus 0x0001 son las mismas que luego andan en los 0x0005 -- la
de KarmaSilk dio 59 pasos -- asi que el id esta donde se creia y el
movimiento va por el mismo 0x0005 de siempre, que es lo unico que ya estaba
bien del primer intento.

    +0   u32 entity_id
    +8   u32 casilla x
    +12  u32 casilla y
    +16  nombre ASCIIZ (16 bytes)
    +150 nombre de la GUILD ASCIIZ
    el resto: apariencia y equipo

EL CUERPO SE COPIA. De los 184 bytes solo se entienden esos cuatro campos;
el resto es la apariencia y no se sabe armar. Se coge uno capturado de un
jugador de verdad y se le cambian la entidad, la casilla y el nombre, que es
el mismo truco que ya se usa para dibujar los tornados y los objetos de
mapa. Consecuencia: todos los jugadores se veran con la pinta del que se
capturo hasta que se sepa leer la apariencia. Se les ve, se les ve andar y
se les lee el nombre, que es lo que hacia falta.

EL SPRITE sale de la clase del personaje. El cliente arma la ruta del dibujo
como \\chr\\iNNNg\\2NNNN_Wait.spr a partir de la apariencia, y en la lista de
personajes esa apariencia son el class_id y cinco bytes. Aqui se usa el
mismo numero que el jugador ve en su propia ficha.
"""
import collections
import logging
import struct

log = logging.getLogger('presencia')

# Las entidades de los jugadores no pueden chocar con nada de lo que ya hay
# en un mapa: los monstruos del cliente van en 50.000.000, los objetos de
# mapa en 60.000.000 y los tornados dibujados en 70.000.000.
BASE_ENTIDAD = 80_000_000

# Quien esta en cada mapa. stage -> lista de sesiones.
_POR_MAPA = collections.defaultdict(list)


def entidad_de(ses) -> int:
    """El id con el que los DEMAS ven a este jugador.

    No vale el entity_id propio: cada sesion usa el suyo para su personaje y
    se repiten entre jugadores, asi que si se reenviara tal cual, el segundo
    jugador en entrar borraria al primero de la pantalla del tercero.
    """
    e = getattr(ses, '_entidad_publica', None)
    if e is None:
        e = BASE_ENTIDAD + (id(ses) % 1_000_000)
        ses._entidad_publica = e
    return e


def _datos(ses):
    p = getattr(ses, 'personaje', None)
    if p is None:
        return None
    return (entidad_de(ses), getattr(p, 'nombre', '') or '?',
            int(getattr(p, 'tile_x', 0)), int(getattr(p, 'tile_y', 0)),
            int(getattr(p, 'sprite', 0) or 0))


# Un 0x0001 de un jugador DE VERDAD, de la captura del Global
# (mundo_141825, KarmaWeapon en el stage de Bling Plaza). Se le cambian la
# entidad, la casilla y el nombre; lo demas es su apariencia y se copia.
PLANTILLA = bytes.fromhex(
    '14039a520000000053000000ca0000004b61726d61576561706f6e00e5859200c8000000'
    '53b9870801043d00e8030000a0526161777200db81620000a06b870801b30b0098967608'
    '00ee030cc6040000000000000000000009001a0102000000a0550100441300000a000000'
    '00000000a2550100a3550100dc1200003d1000000a0000001e55010000000000000000'
    '00000c000000004d6f6f6e6c69676874730084e5b88ce69c9b000300000000000004'
    '66010000000000')
OFF_ENTIDAD, OFF_X, OFF_Y, OFF_NOMBRE, TAM_NOMBRE = 0, 8, 12, 16, 16
OFF_GUILD, TAM_GUILD = 150, 10
APARECE = 0x0001


def _spawn(ses):
    """El 0x0001 que presenta a ese jugador ante los demas."""
    d = _datos(ses)
    if d is None:
        return None
    eid, nombre, tx, ty, _sprite = d
    b = bytearray(PLANTILLA)
    struct.pack_into('<I', b, OFF_ENTIDAD, eid)
    struct.pack_into('<I', b, OFF_X, tx)
    struct.pack_into('<I', b, OFF_Y, ty)
    n = nombre.encode('ascii', 'replace')[:TAM_NOMBRE - 1]
    b[OFF_NOMBRE:OFF_NOMBRE + TAM_NOMBRE] = n + bytes(TAM_NOMBRE - len(n))
    # La guild de la plantilla no es de este jugador: se borra.
    b[OFF_GUILD:OFF_GUILD + TAM_GUILD] = bytes(TAM_GUILD)
    return struct.pack('<H', APARECE) + bytes(b)


def _despawn(eid):
    import combate as _cb
    return _cb.despawn_monstruo(eid)


def _vivas(stage):
    """Las sesiones de ese mapa que siguen conectadas y con personaje."""
    vivas = []
    for s in _POR_MAPA.get(stage, []):
        if getattr(s, 'personaje', None) is None:
            continue
        if getattr(s, 'cerrada', False):
            continue
        vivas.append(s)
    _POR_MAPA[stage] = vivas
    return vivas


def _mandar(ses, *paquetes):
    paquetes = [p for p in paquetes if p]
    if not paquetes:
        return
    try:
        ses.enviar(*paquetes)
    except Exception:
        # Una sesion a medio cerrar no puede tumbar al que la saluda.
        log.debug('no se pudo mandar a una sesion', exc_info=True)


def entrar(ses, stage):
    """El jugador llega a un mapa: se le presenta a los que ya estaban y al
    reves."""
    salir(ses, avisar=True)
    yo = _spawn(ses)
    otros = _vivas(stage)
    for s in otros:
        if s is ses:
            continue
        _mandar(s, yo)                 # a el le sale el recien llegado
        _mandar(ses, _spawn(s))        # y al recien llegado le salen ellos
    if ses not in _POR_MAPA[stage]:
        _POR_MAPA[stage].append(ses)
    ses._mapa_presencia = stage
    if otros:
        log.info('%s entra al mapa %s, donde ya hay %d',
                 getattr(ses.personaje, 'nombre', '?'), stage, len(otros))


def salir(ses, avisar=True):
    """El jugador deja el mapa (o se desconecta): se le borra de las demas
    pantallas."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None:
        return
    ses._mapa_presencia = None
    lista = _POR_MAPA.get(stage) or []
    if ses in lista:
        lista.remove(ses)
    if not avisar:
        return
    fuera = _despawn(entidad_de(ses))
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, fuera)


def mover(ses, cur_x, cur_y, dst_x, dst_y, velocidad=50):
    """Reenvia el paso de un jugador a los demas del mapa.

    Las coordenadas van en PIXELES, igual que las manda el cliente en su
    0x0004 y que las espera el 0x0005.
    """
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None:
        return
    otros = [s for s in _vivas(stage) if s is not ses]
    if not otros:
        return
    try:
        import app as _app
        MOVE = _app.Msg.registry[(0x0005, 's2c', '*')]
        paso = MOVE.build(entity_id=entidad_de(ses), cur_x=int(cur_x),
                          cur_y=int(cur_y), dst_x=int(dst_x), dst_y=int(dst_y),
                          speed=int(velocidad) or 50)
    except Exception:
        log.debug('no se pudo armar el paso', exc_info=True)
        return
    for s in otros:
        _mandar(s, paso)


def cuantos(stage) -> int:
    return len(_vivas(stage))


def mapas_con_gente() -> dict:
    return {st: len(_vivas(st)) for st in list(_POR_MAPA) if _vivas(st)}
