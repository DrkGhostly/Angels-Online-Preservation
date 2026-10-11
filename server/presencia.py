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


_ENTIDADES_ASIGNADAS = set()


def entidad_de(ses) -> int:
    """El id con el que los DEMAS ven a este jugador en el cliente de Celestia."""
    e = getattr(ses, '_entidad_publica', None)
    if e is None:
        cand = 2001
        while cand in _ENTIDADES_ASIGNADAS:
            cand += 1
        _ENTIDADES_ASIGNADAS.add(cand)
        e = cand
        ses._entidad_publica = e
    return e


def liberar_entidad(ses):
    e = getattr(ses, '_entidad_publica', None)
    if e and e in _ENTIDADES_ASIGNADAS:
        _ENTIDADES_ASIGNADAS.remove(e)
    ses._entidad_publica = None


def _datos(ses):
    p = getattr(ses, 'personaje', None)
    if p is None:
        return None
    return (entidad_de(ses), getattr(p, 'nombre', '') or '?',
            int(getattr(p, 'tile_x', 0)), int(getattr(p, 'tile_y', 0)),
            int(getattr(p, 'sprite', 0) or 0))


# Un 0x0001 oficial de Celestia (128 bytes, medido en Hidden Grove).
# No confundir con los 184 B del servidor IGG Global que rompen el stream de Celestia.
PLANTILLA = bytes.fromhex(
    '5600000000000000b50000005f00000043686f636f000000000000000000000000000000'
    '00000000000000000000000000000100000000010100000004000000a9300000aa300000'
    'e703000000000000ab300000ac3000000000000096070000751d00000000000000000000'
    '0000000000000000000000000000000000000000'
)
OFF_ENTIDAD, OFF_X, OFF_Y, OFF_NOMBRE, TAM_NOMBRE = 0, 8, 12, 16, 16
APARECE = 0x0001


def transform_sprite_de(ses) -> int:
    """Devuelve el sprite de transformacion activo si el jugador esta transformado, o 0 si no."""
    import time
    p = getattr(ses, 'personaje', None)
    if not p:
        return 0
    buffs = getattr(p, 'buffs', None) or {}
    ahora = time.time()
    for b_id, b_data in buffs.items():
        if not isinstance(b_data, dict):
            continue
        if b_data.get('fin', 0) > ahora and b_data.get('es_transform'):
            ts = b_data.get('trans_sprite') or (b_data.get('mag') or {}).get('trans_sprite')
            if ts:
                return int(ts)
    return 0


def _spawn(ses):
    """El 0x0001 oficial de 128 bytes que presenta a ese jugador ante los demas."""
    d = _datos(ses)
    if d is None:
        return None
    eid, nombre, tx, ty, _sprite = d
    p = getattr(ses, 'personaje', None)
    b = bytearray(PLANTILLA)
    struct.pack_into('<I', b, OFF_ENTIDAD, eid)
    struct.pack_into('<I', b, 4, 0)
    struct.pack_into('<I', b, OFF_X, tx)
    struct.pack_into('<I', b, OFF_Y, ty)
    n = nombre.encode('ascii', 'replace')[:TAM_NOMBRE - 1]
    b[OFF_NOMBRE:OFF_NOMBRE + TAM_NOMBRE] = n + bytes(TAM_NOMBRE - len(n))

    # Apariencia base (5 bytes en offsets 55..59 segun sub_5E97F0 en Angel.exe)
    apariencia = getattr(p, 'apariencia', None) or [0, 0, 0, 8, 8]
    if isinstance(apariencia, (list, tuple)) and len(apariencia) >= 5:
        b[55] = int(apariencia[0])
        b[56] = int(apariencia[1])
        b[57] = int(apariencia[2])
        b[58] = int(apariencia[3])
        b[59] = int(apariencia[4])

    import login as _lg
    b[60] = _lg.CODIGO_FACCION.get(getattr(p, 'faction', ''), 5)

    # Equipo regular (8 slots de tabla 0x8c0904: 1, 2, 3, 4, 5, 6, 7, 10 en offsets 64..92):
    bolsa = getattr(ses, 'inventario', None) or {}
    it_head = int(bolsa.get(167) or bolsa.get(1) or 0)
    it_body = int(bolsa.get(2) or 0)
    it_weap = int(bolsa.get(169) or bolsa.get(3) or 0)
    it_shld = int(bolsa.get(170) or bolsa.get(4) or 0)
    it_glov = int(bolsa.get(171) or bolsa.get(5) or 0)
    it_shoe = int(bolsa.get(172) or bolsa.get(6) or 0)
    it_back = int(bolsa.get(173) or bolsa.get(7) or 0)
    # Montura (ranura 174 o 10; si no tiene montura equipada, 0 obligatorio para ir a pie)
    it_mnt  = int(bolsa.get(174) or bolsa.get(10) or 0)

    slots_8 = [it_head, it_body, it_weap, it_shld, it_glov, it_shoe, it_back, it_mnt]
    for idx, it in enumerate(slots_8):
        struct.pack_into('<I', b, 64 + idx * 4, it)

    # Estado del personaje: 8 montado, 7 sentado, 0 de pie
    if it_mnt > 0:
        b[61] = 8
    elif getattr(ses, 'sentado', False):
        b[61] = 7
    else:
        b[61] = 0

    # Fashion overlays (Angel.exe sub_5E97F0):
    # Offset 96: Slot 13 (Fashion Suit / Dress, ranura 168)
    it_suit = int(bolsa.get(168) or 0)
    struct.pack_into('<I', b, 96, it_suit)

    # Offset 100: Slot 14 (Fashion Hand 2 / Shield, ranura 170)
    it_fweap = int(bolsa.get(170) or 0)
    struct.pack_into('<I', b, 100, it_fweap)

    # Offset 106: Slot 15 (Fashion Badge / Aura, ranura 175)
    it_badge = int(bolsa.get(175) or 0)
    struct.pack_into('<I', b, 106, it_badge)

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
        if hasattr(ses, 'enviar_inmediato'):
            ses.enviar_inmediato(*paquetes)
        else:
            ses.enviar(*paquetes)
    except Exception:
        log.debug('no se pudo mandar a una sesion', exc_info=True)


def entrar(ses, stage):
    """El jugador llega a un mapa: se le presenta a los que ya estaban y al
    reves, incluyendo mascotas e invocaciones activas."""
    import combate as _cb
    import login as _lg
    salir(ses, avisar=True)
    yo_spawn = _spawn(ses)
    otros = _vivas(stage)
    ts_yo = transform_sprite_de(ses)

    for s in otros:
        if s is ses:
            continue
        # Presentar a 'ses' ante 's'
        _mandar(s, yo_spawn)
        if ts_yo:
            _mandar(s, _cb.atributo(entidad_de(ses), ts_yo, _cb.KIND_TRANSFORM))

        # Summons de 'ses' hacia 's'
        for inv_key in ('invocacion', 'invocacion2'):
            inv = getattr(ses, inv_key, None)
            if inv and inv.get('hp', 0) > 0:
                sp_pkg = _lg.spawn_invocacion(inv['entity_id'], inv.get('npc_tipo', 9999),
                                              inv['nombre'], (inv.get('tile_x', 0), inv.get('tile_y', 0)),
                                              sprite=inv.get('sprite', 0))
                hp_pkg = _cb.atributo(inv['entity_id'], int(100 * inv['hp'] / max(1, inv.get('hp_max', 1))), _cb.KIND_HP)
                _mandar(s, sp_pkg, hp_pkg)

        # Pet de 'ses' hacia 's'
        if getattr(ses, 'pet_entity_id', None):
            pet_spr = getattr(ses, 'pet_sprite', 0)
            if not pet_spr:
                pet_it = (getattr(ses, 'inventario', {}) or {}).get(9)
                if pet_it:
                    import inventario as _iv_p
                    pet_spr = _iv_p.sprite_de_mascota(pet_it)
            if pet_spr:
                ses.pet_sprite = pet_spr
                pet_pkg = _lg._npc_spawn(ses.pet_entity_id, 9999, "Pet",
                                         (ses.personaje.tile_x + 1, ses.personaje.tile_y),
                                         sprite=pet_spr)
                _mandar(s, pet_pkg)

        # Monstruo encantado / mercenario de 'ses' hacia 's'
        m_enc_yo = getattr(ses, 'monstruo_encantado', None)
        if m_enc_yo and getattr(m_enc_yo, 'vivo', False) and m_enc_yo.hp > 0:
            m_pkg = _lg._npc_spawn(m_enc_yo.entity_id, m_enc_yo.tipo, m_enc_yo.nombre,
                                   (m_enc_yo.tile_x, m_enc_yo.tile_y), sprite=m_enc_yo.sprite)
            m_hp = _cb.atributo(m_enc_yo.entity_id, m_enc_yo.porcentaje, _cb.KIND_HP)
            _mandar(s, m_pkg, m_hp)

        # Presentar a 's' ante 'ses'
        s_spawn = _spawn(s)
        _mandar(ses, s_spawn)
        ts_s = transform_sprite_de(s)
        if ts_s:
            _mandar(ses, _cb.atributo(entidad_de(s), ts_s, _cb.KIND_TRANSFORM))

        # Summons de 's' hacia 'ses'
        for inv_key in ('invocacion', 'invocacion2'):
            inv = getattr(s, inv_key, None)
            if inv and inv.get('hp', 0) > 0:
                sp_pkg = _lg.spawn_invocacion(inv['entity_id'], inv.get('npc_tipo', 9999),
                                              inv['nombre'], (inv.get('tile_x', 0), inv.get('tile_y', 0)),
                                              sprite=inv.get('sprite', 0))
                hp_pkg = _cb.atributo(inv['entity_id'], int(100 * inv['hp'] / max(1, inv.get('hp_max', 1))), _cb.KIND_HP)
                _mandar(ses, sp_pkg, hp_pkg)

        # Pet de 's' hacia 'ses'
        if getattr(s, 'pet_entity_id', None):
            pet_spr = getattr(s, 'pet_sprite', 0)
            if not pet_spr:
                pet_it = (getattr(s, 'inventario', {}) or {}).get(9)
                if pet_it:
                    import inventario as _iv_p
                    pet_spr = _iv_p.sprite_de_mascota(pet_it)
            if pet_spr:
                s.pet_sprite = pet_spr
                pet_pkg = _lg._npc_spawn(s.pet_entity_id, 9999, "Pet",
                                         (s.personaje.tile_x + 1, s.personaje.tile_y),
                                         sprite=pet_spr)
                _mandar(ses, pet_pkg)

        # Monstruo encantado / mercenario de 's' hacia 'ses'
        m_enc = getattr(s, 'monstruo_encantado', None)
        if m_enc and getattr(m_enc, 'vivo', False) and m_enc.hp > 0:
            m_pkg = _lg._npc_spawn(m_enc.entity_id, m_enc.tipo, m_enc.nombre,
                                   (m_enc.tile_x, m_enc.tile_y), sprite=m_enc.sprite)
            m_hp = _cb.atributo(m_enc.entity_id, m_enc.porcentaje, _cb.KIND_HP)
            _mandar(ses, m_pkg, m_hp)

    if ses not in _POR_MAPA[stage]:
        _POR_MAPA[stage].append(ses)
    ses._mapa_presencia = stage
    if otros:
        log.info('%s entra al mapa %s, donde ya hay %d',
                 getattr(ses.personaje, 'nombre', '?'), stage, len(otros))


def notificar_transformacion(ses, trans_sprite: int):
    """Avisa a todos los demas jugadores del mapa que este jugador cambio de forma."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None:
        return
    import combate as _cb
    eid = entidad_de(ses)
    pkt = _cb.atributo(eid, int(trans_sprite or 0), _cb.KIND_TRANSFORM)
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, pkt)


def notificar_equipo(ses):
    """Avisa a todos los demas jugadores del mapa que este jugador cambio de equipo o apariencia."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None:
        return
    yo_spawn = _spawn(ses)
    if not yo_spawn:
        return
    ts = transform_sprite_de(ses)
    import combate as _cb
    pkt_trans = _cb.atributo(entidad_de(ses), ts, _cb.KIND_TRANSFORM) if ts else None
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, yo_spawn)
            if pkt_trans:
                _mandar(s, pkt_trans)


def salir(ses, avisar=True):
    """El jugador deja el mapa (o se desconecta): se le borra de las demas
    pantallas."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None:
        liberar_entidad(ses)
        return
    ses._mapa_presencia = None
    lista = _POR_MAPA.get(stage) or []
    if ses in lista:
        lista.remove(ses)
    if avisar:
        fuera = _despawn(entidad_de(ses))
        for s in _vivas(stage):
            if s is not ses:
                _mandar(s, fuera)
    liberar_entidad(ses)


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


def notificar_invocacion_spawn(ses, inv, spawn_pkg, hp_pkg):
    """Avisa a todos los demas jugadores del mapa que aparecio una invocacion."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, spawn_pkg, hp_pkg)


def notificar_invocacion_movimiento(ses, entity_id, move_pkt):
    """Avisa a todos los demas jugadores del mapa que una invocacion se movio."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, move_pkt)


def notificar_invocacion_despawn(ses, entity_id):
    """Avisa a todos los demas jugadores del mapa que una invocacion murio o expiro."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    import combate as _cb
    pkt_despawn = _cb.despawn_monstruo(entity_id)
    pkt_hp = _cb.atributo(entity_id, 0, _cb.KIND_HP)
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, pkt_hp, pkt_despawn)


def notificar_mascota_spawn(ses, pet_eid, sprite, tx, ty):
    """Avisa a todos los demas jugadores del mapa que salio una mascota."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    import login as _lg
    pet_pkg = _lg._npc_spawn(pet_eid, 9999, "Pet", (tx, ty), sprite=sprite)
    ses.pet_sprite = sprite
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, pet_pkg)


def notificar_mascota_movimiento(ses, pet_eid, move_pkt):
    """Avisa a todos los demas jugadores del mapa que una mascota se movio."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, move_pkt)


def notificar_mascota_despawn(ses, pet_eid):
    """Avisa a todos los demas jugadores del mapa que se guardo la mascota."""
    stage = getattr(ses, '_mapa_presencia', None)
    if stage is None and getattr(ses, 'personaje', None):
        stage = getattr(ses.personaje, 'stage', None)
    if stage is None:
        return
    import combate as _cb
    pkt = _cb.atributo(pet_eid, 0, _cb.VIDA)
    pkt_despawn = _cb.despawn_monstruo(pet_eid)
    for s in _vivas(stage):
        if s is not ses:
            _mandar(s, pkt, pkt_despawn)

