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

POR QUE SE DIBUJA CON EL 0x0008. El paquete con el que el servidor original
presenta a OTRO jugador no se conoce: las 1.230 sesiones grabadas del
proyecto no traen ni uno. Se comprobo sacando todos los nombres de los
0x0008 que no figuran en las tablas de monstruos ni de NPC, y los 180 que
salieron son nombres de bicho CORTADOS a los 16 bytes del campo, no
jugadores. El que capturo iba siempre solo.

Asi que se usa lo que si esta medido y funciona: el 0x0008 dibuja una
entidad con su nombre, su casilla y su sprite, y el 0x0005 la mueve. Es como
se dibujan los NPC y los monstruos. El aspecto no sera el del equipo que
lleve puesto el otro jugador -- para eso haria falta el paquete de verdad --
pero se le ve, se le ve moverse y se le lee el nombre encima.

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


def _spawn(ses):
    """El 0x0008 que presenta a ese jugador ante los demas."""
    d = _datos(ses)
    if d is None:
        return None
    import login as _lg
    eid, nombre, tx, ty, sprite = d
    # klass 400: en las capturas los 0x0008 de klass alto son NPC con figura
    # de persona. No es el valor que usa el servidor original para un
    # jugador -- no se conoce -- pero dibuja un muneco con nombre encima,
    # que es lo que hace falta para verse.
    return _lg._npc_spawn(eid, 0, nombre[:16], (tx, ty),
                          sprite=sprite or 40001, klass=400, visible=1)


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
