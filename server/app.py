"""
Servidor Angels Online -- capa de transporte.

Estado: el TRANSPORTE funciona y esta validado contra capturas reales.
La LOGICA DE JUEGO no existe todavia (ver docs/05_SERVIDOR.md).

Uso:
    python server/app.py [--host 127.0.0.1] [--port 16768]
"""
import asyncio
import argparse
import os
import logging
import random
import sys
import pathlib
import collections
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'proto'))

from session import Session
from login import Personaje, secuencia
from grabador import Grabador
import cuentas
import login_server
from codec import Msg
import messages  # noqa
import struct

log = logging.getLogger('app')

# Angel Raphael. Es el unico NPC tras cuyo dialogo el servidor real manda el
# atributo que habilita la eleccion de clase.
ENTIDAD_MAESTRO_CLASE = 19
MAPA_DEL_TUTORIAL = 51      # los entity_id del tutorial solo valen aqui
# Donde revive quien muere sin checkpoint: el Angel Lyceum, junto a los NPC.
# Medido en Celestia: al elegir "Return to Angel Lyceum" aparece en (173,91).
# Con checkpoint de Cupido el punto cambia y queda al lado de Cupido.
REVIVIR_LYCEUM = (173, 91)


_PORTALES = None


def critico_jugador(ses) -> int:
    """El Critical del personaje (en %), de su hoja de stats."""
    try:
        import struct as _s
        return _s.unpack_from('<H', _stats_ses(ses), 66 + 2)[0]
    except Exception:
        return 5


def defensa_jugador(ses) -> int:
    """El Dfs del personaje, leido de su hoja de stats."""
    try:
        import struct as _s
        return _s.unpack_from('<I', _stats_ses(ses), 38)[0]
    except Exception:
        return 0


def skills_arma_ses(ses):
    """Las habilidades de arma de lo equipado."""
    import clases as _cl
    return _cl.skills_de_equipo(getattr(ses, 'inventario', None))


def lleva_duales_ses(ses):
    """Si el personaje pelea con DOS armas de mano (el escudo no cuenta)."""
    import clases as _cl
    return _cl.lleva_duales(getattr(ses, 'inventario', None))


def _portales():
    """La tabla de tornados de plantillas/portales.json."""
    global _PORTALES
    import json
    if _PORTALES is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'portales.json'
        _PORTALES = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {
            'msg': 5801, 'opciones': [], 'radio': 2, 'mapas': {}}
    return _PORTALES


# LOS MAPAS QUE TIENEN PLANTILLA. Es login.PLANTILLAS_POR_STAGE mas los dos
# que se tratan aparte. Estaba escrito a mano en tres sitios distintos y ya
# se pago caro una vez: cada copia que se olvidaba dejaba un mapa entero sin
# IA. Aqui esta una sola vez.
MAPAS_APARTE = {41: 'lyceum.json', 57: 'fighting_palace.json'}
# DONDE APARECE EL JUGADOR al entrar a cada Training Area por el dialogo del
# Terra Keeper. La casilla es (136,72) en las cuatro, leida del minimapa en el
# cliente oficial. Estaba en (202,109), que es la casilla de VUELTA -- donde
# se aparece en Mysterious Garden al salir -- y por eso el jugador entraba en
# el sitio equivocado.
DESTINOS_ENTRENAMIENTO = {
    7505: (135, (136, 72), 'Training Area C'),
    7506: (136, (136, 72), 'Training Area D'),
    7507: (118, (136, 72), 'Training Area A'),
    7508: (134, (136, 72), 'Training Area B'),
}
ETAPAS_ENTRENAMIENTO = frozenset(destino[0]
                                 for destino in DESTINOS_ENTRENAMIENTO.values())
ENTIDAD_SALIDA_ENTRENAMIENTO_B = 0x06380409
EVENTO_SALIDA_ENTRENAMIENTO_A = bytes.fromhex('ef020a5003')
RETORNO_ENTRENAMIENTO = (22, (201, 108), 'Mysterious Garden')


def mapas_poblados():
    import login as _lgp
    return {**_lgp.PLANTILLAS_POR_STAGE, **MAPAS_APARTE}


ITEM_SUPERWING = 25832
_ANGELS_GO = None


def _angels_go():
    """La tabla de destinos del Angels GO!, de plantillas/angels_go.json.

    Es el 編號 de jumpmap.xml del cliente. Medido tres veces en Celestia --
    los ids 120, 119 y 109 -- y las tres la casilla de llegada fue
    exactamente la que declara esa tabla, asi que vale entera sin medir
    destino por destino.
    """
    global _ANGELS_GO
    import json
    if _ANGELS_GO is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'angels_go.json'
        _ANGELS_GO = (json.loads(f.read_text(encoding='utf-8')).get('destinos', {})
                      if f.exists() else {})
    return _ANGELS_GO


# Las CUATRO facciones de verdad, por su codigo en la ficha. El 5 es
# "Heaven", que es con lo que se sale del Lyceum antes de elegir, y el 0 es
# "Neutrally": ninguno de los dos es una faccion, son el estado de no tener.
FACCIONES_REALES = (1, 2, 3, 4)   # Aurora, Beasts, Steel, Shadow


def tiene_faccion(p) -> bool:
    """Si el personaje pertenece a una de las cuatro facciones.

    Medido en Celestia: un personaje de nivel 12 con la ficha en "Heaven"
    NO puede usar las Superwing. Hay que elegir faccion en el Graduation
    Palace primero.
    """
    import login as _lgf
    if p is None:
        return False
    return (_lgf.CODIGO_FACCION.get(getattr(p, 'faction', ''), 5)
            in FACCIONES_REALES)


def _ranura_de_item(ses, item_id: int):
    """La primera casilla de la mochila que lleva ese item, o None."""
    for r, iid in sorted(getattr(ses, 'inventario', {}).items()):
        if int(iid) == int(item_id) and int(r) >= 20:
            return int(r)
    return None



def _estatuas(stage):
    """Las estatuas que teletransportan de plantillas/portales.json.

    Mecanismo medido en Seaside Grotto, y distinto de todo lo demas. No es el
    0x0016 de los portales internos de Lost Trail ni el menu de los de
    Bearscape: aqui hay que HABLARLE al objeto.

        c2s 0x0005 [u32 entidad][u16 0]   <- clic sobre la estatua
        s2c 0x0012 con el mensaje y dos opciones, Yes y No
        c2s 0x000B [0a]                   <- se elige la primera, Yes
        s2c 0x0003 [u32 yo][u32 x][u32 y] <- y aparece al otro lado

    El 0x0a es 10, que es PRIMERA_OPCION, o sea el indice 0: la opcion "Yes".
    Se confirmo contando: el 0x000B aparece en las cinco veces que hubo salto
    y falta en las tres que no. Antes se habia mirado el 0x000F, que resulta
    ser un latido -- sale 95 veces por sesion -- y no tenia nada que ver.

    El mensaje avisa de que forzar la barrera cuesta vida, y el usuario lo
    confirmo en el juego.
    """
    return (_portales().get('teletransportes_por_dialogo') or {}).get(str(stage)) or []


def _estatua_con_entidad(stage, ent):
    """La estatua cuyo id coincide, o None. Compara por ENTIDAD y no por
    casilla, porque el clic llega con la entidad y nuestro servidor reenvia
    los objetos con su id original."""
    for e in _estatuas(stage):
        if ent in ((e.get('estatuas') or {}).get('entidades') or []):
            return e
    return None


def _dialogo_de_estatua(e):
    """El 0x0012 tal como lo manda el servidor real: cabecera de nueve bytes,
    luego los ids de opcion y luego las acciones."""
    ops = list(e.get('opciones') or [])
    acc = list(e.get('acciones') or [0] * len(ops))
    b = bytearray(9)
    struct.pack_into('<I', b, 0, int(e['msg']))
    b[7] = len(ops)
    for o in ops:
        b += struct.pack('<I', int(o))
    for a in acc[:len(ops)]:
        b += struct.pack('<I', int(a))
    return struct.pack('<H', 0x0012) + bytes(b)


def _portal_en(stage, tx, ty):
    """El tornado que se esta pisando, o None."""
    cfg = _portales()
    for por in cfg.get('mapas', {}).get(str(stage), []):
        # TORNADO ANOTADO PERO SIN MEDIR. Los que llevan a una instancia estan
        # en el json para no perder su casilla y su entidad, pero con destino
        # en null. Devolverlos haria que el servidor intentara viajar al stage
        # None. Se saltan hasta que alguien capture el cruce.
        if por.get('destino') is None:
            continue
        # Radio propio si lo trae. El radio 1 global pide estar justo encima,
        # y eso no vale para todos: el tornado de Mushroom hacia Jade Vale
        # dispara desde dos casillas antes -- medido, el jugador se quedo en
        # (6,238) y el tornado esta en (5,240).
        r = max(2, por.get('radio', cfg.get('radio', 2)))
        if abs(por['tile'][0] - tx) <= r and abs(por['tile'][1] - ty) <= r:
            return por
    return None


def _nombre_entidad(ses, entity_id: int) -> str:
    """El nombre del NPC del mapa, para buscarle su dialogo."""
    totems_lyceum = {
        41: 'Aurora Totem', 150: 'Aurora Totem',
        43: 'Iron Totem', 121: 'Iron Totem',
        44: 'Dark City Totem', 122: 'Dark City Totem',
        45: 'Breeze Totem', 120: 'Breeze Totem',
    }
    if entity_id in totems_lyceum:
        return totems_lyceum[entity_id]
    # Los totems del Fighting Palace se mandan como objetos de mapa y su
    # entity_id lo asigna poblar(), asi que no puede ir escrito a mano.
    import login as _lg
    if entity_id in _lg.TOTEMS_PUESTOS:
        return _lg.TOTEMS_PUESTOS[entity_id]

    import dialogos as _dlg
    info = _dlg.info_npc(entity_id)
    if info and info.get('nombre'):
        return info['nombre']

    # Si es un NPC de quest de los xmls (entity_id >= 900)
    f_mapas = pathlib.Path(__file__).parent / 'plantillas' / 'npc_por_mapa.json'
    if f_mapas.exists() and entity_id >= 900 and getattr(ses, 'personaje', None):
        import json
        d_mapas = json.loads(f_mapas.read_text(encoding='utf-8')).get('mapas', {})
        st_npcs = d_mapas.get(str(ses.personaje.stage), [])
        idx = entity_id - 900
        if 0 <= idx < len(st_npcs):
            return st_npcs[idx].get('nombre', '')
    return ''


def _monstruos_de(stage: int):
    """Los monstruos vivos del mapa, por entity_id."""
    import json
    import combate
    import login as _lg
    plantillas = pathlib.Path(__file__).parent / 'plantillas'
    # Cada mapa poblado tiene su plantilla. El West Playground trae 150
    # monstruos de seis clases, asi que su IA sale de aqui igual que la del
    # Lyceum: pasean, persiguen, pegan y reaparecen.
    por_stage = mapas_poblados()
    nombre = por_stage.get(stage)
    if not nombre:
        # Los mapas que aun no tienen plantilla usan la lista escrita a mano.
        if stage in _lg.PLAYGROUND_MONSTERS:
            return {eid: combate.Monstruo(eid, ntype, nom, tile)
                    for eid, ntype, nom, tile in _lg.PLAYGROUND_MONSTERS[stage]}
        return {}
    f = plantillas / nombre
    if not f.exists():
        return {}
    d = json.loads(f.read_text(encoding='utf-8'))
    return {e['entity_id']: combate.Monstruo(e['entity_id'], e['npc_type'],
                                             e['nombre'], e['tile'],
                                             e.get('sprite', 0))
            for e in d['spawns'] if e.get('monstruo')}


def _precio_item(item_id: int) -> int:
    """Precio de compra, de la columna price de item.xml."""
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    try:
        r = sqlite3.connect(db).execute(
            'select price from item where id=?', (str(item_id),)).fetchone()
        return int(float(r[0])) if r and r[0] else 0
    except Exception:
        return 0


# Lo que descuenta la tienda sobre el precio de lista al comprar. La Red
# Potion 1 tiene price 40 en item.xml; el cliente la enseña a 35 en la
# ventana de compra (40 * 7/8) y Celestia cobro 34 en las dos capturas
# (476 por catorce, 680 por veinte). Se usa el 7/8 que muestra el cliente
# para que la cuenta le cuadre al jugador.
DESCUENTO_COMPRA = 7 / 8


def _precio_compra(item_id: int) -> int:
    """Lo que cuesta comprar ese item en una tienda."""
    import configuracion as _conf
    if getattr(_conf, 'COMPRAS_1_DE_ORO', False):
        return 1
    return max(1, int(_precio_item(item_id) * DESCUENTO_COMPRA))


def _precio_venta(item_id: int) -> int:
    """Lo que paga la tienda por ese item.

    item.xml trae su propia columna de precio de venta, distinta de price:
    la Red Potion 1 vale 40 de compra y 12 de venta, y son justo los numeros
    de la captura (11 pociones dieron 132 de oro). Antes se usaba price // 2,
    que habria dado 20. El nombre de esa columna quedo ilegible al montar la
    base, asi que se lee por posicion; el equipo la trae vacia y para eso se
    sigue usando la mitad del precio de compra.
    """
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    try:
        r = sqlite3.connect(db).execute(
            'select * from item where id=?', (str(item_id),)).fetchone()
        if r and len(r) > 4 and r[4]:
            return max(1, int(float(r[4])))
    except Exception:
        pass
    return max(1, _precio_item(item_id) // 2)


# Ultima casilla utilizable de la mochila. Sin mochila puesta son 20..39; con
# ella llega hasta la 44. Poner algo mas alla del tope no da error: el objeto
# entra en el inventario pero el cliente no lo dibuja, asi que queda invisible
# hasta que el jugador consigue una mochila y de golpe le aparecen cosas que
# no sabia que tenia.
TOPE_SIN_MOCHILA = 39
TOPE_CON_MOCHILA = 44


def _tope_bolsa(bolsa) -> int:
    """Hasta que casilla se puede guardar, segun si hay mochila puesta."""
    b = bolsa or {}
    hay = b.get(7) is not None or b.get(8) is not None
    return TOPE_CON_MOCHILA if hay else TOPE_SIN_MOCHILA


def _ranura_libre(bolsa, desde=20):
    """Primera casilla vacia de la mochila, o None si esta llena."""
    for r in range(desde, _tope_bolsa(bolsa) + 1):
        if r not in bolsa:
            return r
    return None


def _final_tutorial(ses, addr):
    """Ultimo paso: entrega el set y las cajas, y manda al Angel Lyceum."""
    import clases
    import inventario as inv
    bolsa = getattr(ses, 'inventario', None)
    if bolsa is None or not ses.personaje.habilidades:
        return
    cid = ses.personaje.char_id
    ids = [h[0] for h in ses.personaje.habilidades]
    for ranura, item_id in clases.premio_final(ids):
        if ranura in bolsa:
            ranura = _ranura_libre(bolsa)
        bolsa[ranura] = item_id
        ses.enviar(clases.aviso(_nombre_item(item_id), tipo=0,
                                msg_id=clases.MSG_ITEM))
        ses.enviar(*inv.entregar(cid, item_id, ranura))
    ses.enviar(inv.stats(bolsa))
    # Y al Lyceum.
    ses.personaje.stage = clases.STAGE_LYCEUM
    ses.personaje.tile_x, ses.personaje.tile_y = clases.TILE_LYCEUM
    ses.monstruos = _monstruos_de(clases.STAGE_LYCEUM)
    ses.enviar(clases.cambiar_mapa(clases.STAGE_LYCEUM))
    if getattr(ses, 'usuario', None):
        cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
        cuentas.guardar_mapa(ses.usuario, cid, clases.STAGE_LYCEUM,
                             *clases.TILE_LYCEUM)
    log.info(f"[{addr}] tutorial terminado: set completo, "
             f"{len(clases.cajas_de(ids)) + 1} cajas y al Angel Lyceum")


def _premio(srv, ses, addr, etapa):
    """Entrega lo que da ese tramo del tutorial: items y oro."""
    import clases
    import inventario as inv
    r = clases.RECOMPENSAS.get(etapa)
    if not r or getattr(ses, 'inventario', None) is None:
        return
    cid = ses.personaje.char_id
    nuevos = False
    for ranura, item_id in r['items']:
        if ranura not in ses.inventario:
            ses.inventario[ranura] = item_id
            ses.enviar(clases.aviso(_nombre_item(item_id), tipo=0,
                                    msg_id=clases.MSG_ITEM))
            ses.enviar(*inv.entregar(cid, item_id, ranura))
            nuevos = True
    if r['oro']:
        ses.oro = getattr(ses, 'oro', 0) + r['oro']
        if ses.personaje:
            ses.personaje.oro = ses.oro
        nuevos = True
        log.info(f"[{addr}] tutorial: +{r['oro']} de oro (total {ses.oro})")
    if nuevos:
        # El oro si necesita el inventario entero: su cantidad vive en la
        # entrada de la ranura 0 y no hay un mensaje de "cambio de oro"
        # identificado.
        if r['oro']:
            ses.enviar(inv.completo(cid, _con_oro(ses), _dueno(ses)))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_inventario(ses.usuario, cid, ses.inventario,
                                   _cantidades(ses))
        log.info(f"[{addr}] tutorial: entregado el premio de la etapa {etapa}")


def _cantidades(ses) -> dict:
    """Cuantas unidades hay en cada casilla. La casilla que no esta aqui
    lleva una sola."""
    c = getattr(ses, 'cantidades', None)
    if c is None:
        c = {}
        ses.cantidades = c
    return c


def _cant_de(ses, ranura: int) -> int:
    return max(1, int(_cantidades(ses).get(int(ranura), 1)))


def _instancias(ses) -> dict:
    """El id de instancia de ocho bytes de cada casilla ocupada."""
    m = getattr(ses, 'instancias', None)
    if m is None:
        m = {}
        ses.instancias = m
    return m


def _inst(ses, ranura: int) -> bytes:
    """La instancia de esa casilla, creandola la primera vez."""
    import inventario as inv
    m = _instancias(ses)
    r = int(ranura)
    if r not in m:
        m[r] = inv.instancia_nueva()
    return m[r]


def _mover_inst(ses, origen: int, destino: int):
    """La instancia viaja con el item cuando cambia de casilla."""
    m = _instancias(ses)
    v = m.pop(int(origen), None)
    if v is not None:
        m[int(destino)] = v


def _meter(ses, item_id: int, n: int = 1) -> int:
    """Mete n unidades en la mochila y devuelve la casilla que las lleva.

    Si el item se apila y ya hay un monton suyo, se suma ahi en vez de
    ocupar una casilla nueva: es lo que hace el juego real y lo que faltaba
    para que las galletas y el pasto no llenaran el inventario.
    """
    import inventario as inv
    bolsa = ses.inventario
    item_id = int(item_id)
    n = max(1, int(n))
    if inv.es_apilable(item_id):
        for ranura, it in bolsa.items():
            r = int(ranura)
            if r == inv.RANURA_ORO or int(it) != item_id:
                continue
            if inv.es_equipo(r):
                continue
            _cantidades(ses)[r] = _cant_de(ses, r) + n
            return r
    r = _ranura_libre(bolsa)
    if r is None:
        return None
    bolsa[r] = item_id
    _instancias(ses)[r] = inv.instancia_nueva()
    if n > 1:
        _cantidades(ses)[r] = n
    return r


def _sacar(ses, ranura: int, n: int = 1) -> int:
    """Quita n unidades de esa casilla y devuelve cuantas quito de verdad."""
    ranura = int(ranura)
    bolsa = ses.inventario
    if ranura not in bolsa:
        return 0
    hay = _cant_de(ses, ranura)
    quita = min(hay, max(1, int(n)))
    if quita >= hay:
        del bolsa[ranura]
        _cantidades(ses).pop(ranura, None)
        _instancias(ses).pop(ranura, None)
    else:
        _cantidades(ses)[ranura] = hay - quita
    return quita


def _con_oro(ses):
    """El inventario con la cantidad de cada casilla."""
    import inventario as inv
    out = []
    for ranura, item_id in ses.inventario.items():
        r = int(ranura)
        if r == inv.RANURA_ORO:
            out.append((r, int(item_id), getattr(ses, 'oro', 0), _inst(ses, r)))
        else:
            out.append((r, int(item_id), _cant_de(ses, r), _inst(ses, r)))
    return out


def _dueno(ses):
    """La entidad del personaje, que es lo que va en los mensajes de
    inventario; no es lo mismo que su char_id."""
    p = getattr(ses, 'personaje', None)
    return getattr(p, 'entity_id', None) or getattr(ses, 'entity_id', None)


def _refrescar(ses, ranuras, con_oro=False):
    """Los 0x001B de las casillas que cambiaron.

    El servidor real no reenvia el inventario entero tras comprar, vender o
    usar algo: manda una linea por casilla tocada. Con el 0x001A completo el
    cliente se quedaba con lo que ya tenia pintado y los items vendidos
    seguian apareciendo en la mochila.
    """
    import inventario as inv
    cid = ses.personaje.char_id if ses.personaje else 4980
    fuera = []
    if con_oro:
        fuera.append(inv.actualizar_ranura(cid, inv.RANURA_ORO, 1,
                                           getattr(ses, 'oro', 0),
                                           _inst(ses, inv.RANURA_ORO),
                                           _dueno(ses)))
    for r in sorted(set(int(x) for x in ranuras if x is not None)):
        if r in ses.inventario:
            fuera.append(inv.actualizar_ranura(cid, r, int(ses.inventario[r]),
                                               _cant_de(ses, r), _inst(ses, r),
                                               _dueno(ses)))
        else:
            dueno = ses.personaje.entity_id if ses.personaje else cid
            fuera.append(inv.vaciar_ranura(dueno, r))
    return fuera


def _guardar_bolsa(ses, cid):
    """Guarda inventario y cantidades juntos."""
    if getattr(ses, 'usuario', None):
        cuentas.guardar_inventario(ses.usuario, cid, ses.inventario,
                                   _cantidades(ses))


def _nombre_item(item_id: int) -> str:
    """Nombre del item para el cartel de 'obtuviste X'."""
    if item_id == 10:
        return "FreshmanSabre"
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    try:
        con = sqlite3.connect(db)
        import inventario as _iv
        r = _iv.fila_item(con, '"基本名稱"', item_id)
        con.close()
        return r[0] if r and r[0] else f'Item{item_id}'
    except Exception:
        return f'Item{item_id}'


def _max_sp_info(p):
    """Devuelve (barras_sp, max_puntos_sp). Por defecto 2 barras (2000 puntos).
    La habilidad pasiva Reserve (15) otorga +1 barra cada 25 niveles."""
    res_rank = 1
    if p and getattr(p, 'habilidades', None):
        for h in p.habilidades:
            sid = h[0] if isinstance(h, (list, tuple)) else h
            if sid == 15:
                res_rank = h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else 1
                break
    bars = 2 + (res_rank // 25)
    return bars, bars * 1000


def _procesar_muerte_monstruo(ses, m, yo, addr, espera=0.0):
    """Procesa respawn, EXP, subida de nivel, oro y drops cuando un monstruo es derrotado."""
    import combate as _cb
    import clases as _cl
    import inventario as _iv
    import struct
    import asyncio
    objetivo = m.entity_id

    if ses.personaje and ses.personaje.stage == 57 and m.npc_type == 224:
        ses.slarm_kills = getattr(ses, 'slarm_kills', 0) + 1
        log.info(f"[{addr}] Little Slarm derrotado en Fighting Palace ({ses.slarm_kills}/2)")

    if getattr(m, 'encantado', False):
        m.encantado = False
        m.charmed_objetivo = None
        if getattr(ses, 'monstruo_encantado', None) == m:
            ses.monstruo_encantado = None
        ses.enviar(
            struct.pack('<HIBBII', 0x001D, objetivo, 1, 4, 303, 0),
            struct.pack('<HIBBI', 0x0013, objetivo, 1, 0x3c, 0)
        )

    if getattr(m, 'efectos_activos', None):
        for emid in list(m.efectos_activos.keys()):
            ses.enviar(struct.pack('<HIBBII', 0x001D, objetivo, 1, 4, emid, 0))
        m.efectos_activos.clear()

    _muerte = (_cb.atributo(objetivo, 0, _cb.VIDA),
               _cb.muerte_monstruo(objetivo, yo),
               _cb.ataque(yo, 0, 0, 0))
    _espera_muerte = espera
    try:
        _bucle = asyncio.get_event_loop()
        _bucle.call_later(_espera_muerte,
                          lambda p=_muerte: ses.enviar_inmediato(*p))
        _bucle.call_later(_espera_muerte + 2.5,
                          lambda: ses.enviar_inmediato(_cb.despawn_monstruo(objetivo)))
    except Exception:
        ses.enviar(*_muerte)

    def _respawn():
        if not getattr(m, 'vivo', False):
            m.revivir()
            import login as _lg
            ses.enviar_inmediato(_lg._npc_spawn(
                objetivo, m.npc_type, m.nombre, (m.tile_x, m.tile_y),
                sprite=getattr(m, 'sprite', 0), klass=1))
            log.info(f"[{addr}] monstruo {m.nombre} (entidad {objetivo}) reaparecio")

    try:
        asyncio.get_event_loop().call_later(_cb.SEGUNDOS_REAPARICION, _respawn)
    except Exception:
        pass

    buffs = ses.personaje.buffs if ses.personaje else {}
    exp_ganada = _cb.calcular_exp(m.npc_type, buffs)
    sk_exp_ganada = _cb.calcular_skill_exp(buffs)

    oro = _cb.botin()
    ses.oro = getattr(ses, 'oro', 0) + oro
    if ses.personaje:
        ses.personaje.oro = ses.oro

    salida_combate = []
    cid = ses.personaje.char_id if ses.personaje else 4980

    if ses.personaje:
        p = ses.personaje
        p.exp += exp_ganada
        subio_nivel = False
        while True:
            exp_siguiente = _cb.exp_para_nivel(p.nivel + 1)
            if exp_siguiente > 0 and p.exp >= exp_siguiente:
                p.nivel += 1
                p.hp_max += 25
                p.mp_max += 15
                subio_nivel = True
            else:
                break
        if subio_nivel:
            p.hp = _vida_max(p)
            p.mp = p.mp_max
            salida_combate.append(_cl.aviso(f"Level Up! Reached Level {p.nivel}!", tipo=0, msg_id=_cl.MSG_ITEM))
            salida_combate.append(_cb.atributo(yo, p.hp, _cb.KIND_HP))
            salida_combate.append(_cb.atributo(yo, p.mp, _cb.KIND_MP))
            exp_sig = _cb.exp_para_nivel(p.nivel + 1)
            salida_combate.append(
                struct.pack('<HIB', 0x001D, yo, 4) +
                struct.pack('<BII', 29, p.nivel, 0) +
                struct.pack('<BII', 30, p.exp, 0) +
                struct.pack('<BII', 31, exp_sig, 0) +
                struct.pack('<BII', 32, p.exp, 0)
            )
            salida_combate.append(_cb.efecto_level_up(yo, es_skill=False))
            salida_combate.append(_stats_ses(ses))
            log.info(f"[{addr}] {p.nombre} SUBIO A NIVEL {p.nivel} (enviado 0x001D y efecto 0x0020 red banner)!")

        salida_combate.append(_cl.aviso_doble(_cl.MSG_EXP,
                                              str(exp_ganada),
                                              str(exp_ganada), tipo=0))
        salida_combate.append(struct.pack('<HIBBII', 0x001D, yo, 1, 32, p.exp, 0))

        if getattr(ses, 'usuario', None):
            cuentas.guardar_progreso(ses.usuario, p.char_id, p.nivel, p.exp,
                                     p.hp, p.mp, p.habilidades,
                                     hp_max=p.hp_max, mp_max=p.mp_max)
            cuentas.guardar_oro(ses.usuario, p.char_id, ses.oro)

    salida_combate.append(_cl.aviso(f'{oro} Gold', tipo=0, msg_id=_cl.MSG_ITEM))

    drops = _cb.botin_items(m.npc_type)
    bolsa = getattr(ses, 'inventario', {})
    max_ranura = _tope_bolsa(bolsa)

    tocadas_botin = []
    for item_drop, cant in drops:
        cant = max(1, int(cant))
        apila = None
        if _iv.es_apilable(item_drop):
            for s_r, it_id in bolsa.items():
                if 20 <= s_r <= max_ranura and it_id == item_drop:
                    apila = s_r
                    break
        if apila is None and not any(r not in bolsa for r in range(20, max_ranura + 1)):
            log.info(f"[{addr}] inventario lleno (limite={max_ranura}), drop {item_drop} ignorado silenciosamente")
            continue

        tocadas_botin.append(_meter(ses, item_drop, cant))
        salida_combate.append(_cl.aviso(_nombre_item(item_drop), tipo=0, msg_id=_cl.MSG_ITEM))

    salida_combate.extend(_refrescar(ses, tocadas_botin, con_oro=True))
    try:
        asyncio.get_event_loop().call_later(
            _espera_muerte,
            lambda p=tuple(salida_combate): ses.enviar_inmediato(*p))
    except Exception:
        ses.enviar(*salida_combate)
    if ses.personaje and getattr(ses, 'usuario', None):
        cuentas.guardar_inventario(ses.usuario, cid, bolsa, _cantidades(ses))

    log.info(f"[{addr}] mato un {m.nombre} (entidad {objetivo}); +{exp_ganada} exp, +{oro} oro, {len(drops)} items")



# La salida del Lyceum. "Quit the training" con Angels' Tutor lleva al
# Graduation Palace, y alli cada Angel de faccion manda a su ciudad. Los dos
# puntos estan MEDIDOS en la ficha 0x0002 que llega tras cada cambio de mapa:
# Graduation Palace (26,7) y Breeze Woods (321,97), que es el (321,98) que se
# ve en el minimapa.
# Velocidad a la que camina el personaje, en el campo 'speed' del 0x0005.
# Estaba escrita a mano en 110 dentro del manejador de movimiento. Se puede
# subir con AO_VELOCIDAD mientras no haya monturas; el valor original del
# juego es 110, y los monstruos caminan a 75.
VELOCIDAD_JUGADOR = int(os.environ.get('AO_VELOCIDAD', '110'))

# La montura va en la ranura 10 y sube la velocidad del 0x0005. Medido en
# Celestia con el mismo personaje, quitandola y volviendola a poner:
#
#   sin montura              122
#   con Earthy Piglet (36400) 226
#   con "MAX 200"    (40441)  212
#
# OJO, la columna move_speed de item.xml NO basta: las dos monturas de arriba
# la tienen en 60 y dan velocidades distintas, y la que mas agility declara es
# la mas LENTA. Ademas, al quitar la 40441 los stats bajaron 2400 de HP y 2000
# de MP, cuando su fila dice hp=1720 y mp=1540. O sea que lo que aporta una
# montura depende de SU INSTANCIA -- son mascotas con nivel propio -- y eso no
# esta en item.xml, asi que con los datos del cliente no se puede reproducir el
# numero exacto.
#
# Aqui se aplica el move_speed como porcentaje, que es lo unico sostenible con
# lo que hay: es la forma correcta, aunque el numero no salga clavado al de
# Celestia hasta que sepamos modelar el nivel de la montura.
RANURA_MONTURA = 10

# Bono de montura, en por ciento, que PISA el move_speed del item. A peticion
# del usuario: el Gryphon declara 50 y aqui se usa 150. Poner 0 para respetar
# lo que diga item.xml.
#
# El campo del 0x0005 es U16, no un byte: en las capturas hay jugadores de
# Celestia moviendose a 260 y a 283, asi que 275 (110 x 2,5) entra de sobra en
# lo que el cliente maneja de verdad. El tope de 1000 es solo para que una
# variable de entorno mal puesta no mande un numero absurdo.
BONO_MONTURA = int(os.environ.get('AO_MONTURA_BONO', '150'))


def _velocidad_de(ses) -> int:
    """La velocidad del 0x0005: la de a pie, o con el bono de la montura."""
    base = VELOCIDAD_JUGADOR
    try:
        import inventario as _inv
        bolsa = getattr(ses, 'inventario', None) or {}
        item = bolsa.get(174) or bolsa.get(RANURA_MONTURA)
        if not item:
            return base
        ms = _inv.velocidad_de_montura(item)
        if not ms:
            return base
        if BONO_MONTURA:
            ms = BONO_MONTURA
        return max(1, min(1000, int(round(base * (100 + ms) / 100.0))))
    except Exception:
        return base

# Donde deja el Angel de una ciudad al mandarte de vuelta: al lado de
# Director Wolay, en el Angel Lyceum. La casilla la midio el usuario.
TILE_VUELTA_LYCEUM = (128, 62)

STAGE_GRADUACION = 58
TILE_GRADUACION = (26, 7)

# Las otras tres ciudades salen del "Birth Place" de jumpmap.xml, que es el
# punto analogo; solo el de Breeze Woods esta medido en el juego.
# El nombre que el cliente ENSEÑA en el campo Faction no es el de la ciudad.
# En stage.xml cada ciudad trae su faccion en chino: Aurora 光明 (luz), Dark
# City 黑暗 (oscuridad), Breeze Woods 大地 (tierra) e Iron Castle 渾沌 (caos).
# El unico confirmado en el juego es el de Breeze Woods, que sale como
# "Beasts"; los otros tres son la traduccion mas probable y hay que
# comprobarlos eligiendo esas facciones.
# Que faccion da cada ciudad. YA NO SE ADIVINA: sale de los datos del
# cliente. jumpmap.xml mete cada ciudad en su "territorio de faccion"
# (jumpmapclass.xml: 14 Aurora, 15 Shadow, 16 Beasts, 17 Steel) y ahi no hay
# ambiguedad posible.
#
#   stage  3 Aurora City    categoria 14  -> Aurora
#   stage 26 Dark City      categoria 15  -> Shadow
#   stage 29 Breeze Woods   categoria 16  -> Beasts   <- coincide con lo medido
#   stage 38 Iron Castle    categoria 17  -> Steel
#
# Antes aqui habia 'Holy', 'Evil' y 'Chaos', que nos inventamos: esos nombres
# NO EXISTEN en el cliente. Los suyos son los de string.xml 1031..1035.
NOMBRE_DE_FACCION = {
    'Breeze Woods': 'Beasts',
    'Aurora': 'Aurora',
    'Dark City': 'Shadow',
    'Iron Castle': 'Steel',
}

# Donde deja el Angel del Graduation Palace al elegir faccion: AL LADO del
# Angel de la ciudad, no en la entrada. Comprobado en las dos que tenemos
# capturadas:
#
#   Breeze Woods   BreezeWood Angel en (325,97)  -> deja en (321,97)   4 casillas
#   Aurora City    Aurora Angel     en (188,183) -> deja en (191,182)   3 casillas
#   Iron Castle    IronCastle Angel en (64,161)  -> deja en (68,163)    4 casillas
#   Dark City      Dark City Angel  en (313,69)  -> deja en (309,69)    4 casillas
#
# Las dos caen a tres o cuatro casillas del angel y en su misma fila. Aurora
# City es el stage 3, confirmado por captura el 23/09/2026; su casilla la dio
# el usuario probando en el juego.
#
# LAS CUATRO ESTAN MEDIDAS (23/09/2026). Los dos stage que quedaban a ojo, el
# 38 de Iron Castle y el 26 de Dark City, resultaron correctos; las casillas
# las dio el usuario probando en el juego. La regla se cumple en las cuatro:
# te dejan AL LADO del Angel de la ciudad, a tres o cuatro casillas y en su
# misma fila. Cuando se capturen, la casilla se saca buscando a su
# Angel en la plantilla y poniendose a su lado, que es la pauta de las otras
# dos.
CIUDAD_DE_FACCION = {
    "Breeze Woods": (29, (321, 97)),
    "Aurora": (3, (191, 182)),
    "Iron Castle": (38, (68, 163)),
    "Dark City": (26, (309, 69)),
}


def _ya_registrado(ses) -> bool:
    """Si el personaje ya se registro con el Angel de su ciudad.

    Se sabe porque la mision de registro (130 en Breeze Woods) ya no esta
    pendiente: al registrarse se marca completada y se dan las dos
    siguientes.
    """
    import dialogos as _dlg
    p = getattr(ses, 'personaje', None)
    if not p:
        return False
    cfg = _dlg.ANGEL_DE_CIUDAD.get(getattr(p, 'stage', 0))
    if not cfg:
        return False
    q = cfg['mision_registro']
    for qid, paso in (p.quests or []):
        if qid == q:
            return paso > 0
    return True


# Las ranuras de equipo cuyo contenido se le anuncia al cliente para que
# dibuje al personaje. Medido: el servidor real manda una linea por cada una
# de la 1 a la 7 y la 10, con el item o con 0 si esta vacia.
RANURAS_VISIBLES = (1, 2, 3, 4, 5, 6, 7, 10)


def _apariencia(ses):
    """Los 0x001D code 1 que le dicen al cliente que lleva puesto en cada ranura.
    No cruza las ranuras de Gear con las de Fashion para evitar glitches visuales en la UI.
    """
    import combate as _cb
    p = getattr(ses, 'personaje', None)
    if not p:
        return []
    bolsa = getattr(ses, 'inventario', None) or {}
    ent = p.entity_id
    out = []
    # 1. Ranuras de equipo regular (1..7, 10)
    for r in RANURAS_VISIBLES:
        out.append(_cb.equipar_visual(ent, r, int(bolsa.get(r, 0) or 0)))
    # 2. Ranuras de Fashion (167..174) si estan equipadas
    for r in range(167, 175):
        if r in bolsa:
            out.append(_cb.equipar_visual(ent, r, int(bolsa.get(r, 0) or 0)))
    return out


def _viajar_dentro_del_mapa(ses, addr, por, motivo=''):
    """Un portal que lleva a OTRO punto del MISMO mapa.

    Medido en Forbidden Sector el 24/09/2026, seis cruces entre sus dos
    tubos de teletransporte, el 116703 en (226,143) y el 116707 en (197,75).
    En 1401 segundos de sesion no viajo NI UN 0x000C: el mapa no se recarga.
    Lo que manda el servidor real es:

        s2c 0x0016  [u32 entidad][u8 direccion]   hacia donde queda mirando
        s2c 0x0012  siete bytes a cero            cierra el cuadro
        s2c 0x0003  [u32 entidad][u32 x][u32 y]   lo recoloca

    Ojo con el 0x0012: aqui son SIETE ceros, no los nueve de dialogos.FIN.

    La direccion salio 5 al aparecer en el extremo norte y 1 en el sur, asi
    que va por portal en el campo 'direccion'; si no lo trae, no se manda.
    """
    lleg = por['llegada']
    yo = ses.personaje.entity_id
    fuera = []
    # NO TODOS LOS SALTOS INTERNOS MANDAN LO MISMO. Los de Forbidden Sector y
    # Lost Trail traen el 0x0016 y el 0x0012; el de vuelta de las estatuas de
    # Seaside Grotto no trae ninguno de los dos -- se busco en toda la sesion
    # y no hay ni un 0x0016 -- y lo unico que llega es el 0x0003. Los portales
    # asi se marcan con solo_0003.
    if not por.get('solo_0003'):
        d = por.get('direccion')
        if d is not None:
            fuera.append(struct.pack('<HIB', 0x0016, yo, int(d)))
        fuera.append(struct.pack('<H', 0x0012) + bytes(7))
    fuera.append(struct.pack('<HIII', 0x0003, yo, lleg[0], lleg[1]))
    ses.personaje.tile_x, ses.personaje.tile_y = lleg
    ses.enviar(*fuera)
    # Si la casilla de llegada cae dentro del radio de OTRO portal del mismo
    # mapa, se marca como pisada: si no, el jugador rebotaria al primer paso.
    _en = _portal_en(ses.personaje.stage, *lleg)
    ses.portal_pisado = tuple(_en['tile']) if _en else None
    if getattr(ses, 'usuario', None):
        cuentas.guardar_mapa(ses.usuario, ses.personaje.char_id,
                             ses.personaje.stage, *lleg)
    log.info(f"[{addr}] portal interno: sigue en stage "
             f"{ses.personaje.stage}, ahora en {lleg} {motivo}")


def _sincronizar_cambio_mapa(ses, stage_id: int, x: int = None, y: int = None):
    """Actualiza el estado del servidor y manda solo 0x000C (cambiar mapa).

    Todo lo demas (poblar, habilidades, stats) lo hace el handler de 0x0009
    cuando el cliente contesta que ya cargo el mapa. Antes se mandaba TODO
    aqui y luego otra vez en 0x0009, duplicando cientos de paquetes y
    crasheando al cliente en mapas pesados como Raging Reefs (400+ spawns).
    """
    p = getattr(ses, 'personaje', None)
    if not p:
        return
    import clases as _cl
    p.stage = stage_id
    if x is not None and y is not None:
        p.tile_x, p.tile_y = x, y
    ses.monstruos = _monstruos_de(stage_id)
    ses.mapa_cambiado_en = time.time()

    # Unico paquete: decirle al cliente "carga este mapa"
    ses.enviar(_cl.cambiar_mapa(stage_id))

    if getattr(ses, 'usuario', None):
        cuentas.guardar_mapa(ses.usuario, p.char_id, stage_id, p.tile_x, p.tile_y)


def _viajar_por_portal(ses, addr, por, motivo=''):
    """Manda al jugador por un tornado que no pregunta."""
    dst, lleg = por['destino'], por['llegada']
    # MISMO MAPA: no se recarga nada, solo se recoloca al personaje.
    if dst == getattr(ses.personaje, 'stage', None):
        _viajar_dentro_del_mapa(ses, addr, por, motivo)
        return
    _en_llegada = _portal_en(dst, *lleg)
    ses.portal_pisado = tuple(_en_llegada['tile']) if _en_llegada else None
    _sincronizar_cambio_mapa(ses, dst, lleg[0], lleg[1])
    log.info(f"[{addr}] portal directo: stage {dst} tile {lleg} {motivo}")


def _armar_portal_al_llegar(ses, addr, destino_tile, casillas):
    """Dispara el portal cuando el paso TERMINA encima de un tornado.

    El servidor solo mira la casilla que el cliente dice ocupar, y eso deja un
    agujero: si el ultimo tramo de la ruta acaba justo sobre el tornado, el
    cliente camina hasta alli, se queda quieto y NO vuelve a mandar nada, asi
    que nunca llegamos a verlo encima y el portal no dispara.

    Medido en Celestia, saliendo de Sunshine Palace: el ultimo MOVE_REQ vino
    desde (19,10), a SIETE casillas del tornado, con destino (13,6), que esta a
    una. Despues no mando nada mas y el cambio de mapa llego 0,9 s despues.

    No vale con mirar el destino del paso y viajar en el acto: el primer
    waypoint llega a estar a 21 casillas, asi que el jugador se teletransportaria
    desde media pantalla. Lo que se hace es ARMAR el viaje para dentro de lo
    que tarde en andar ese tramo; cualquier movimiento nuevo lo cancela, asi
    que si cambia de idea a mitad de camino no viaja.
    """
    import asyncio
    _cancelar_portal_armado(ses)
    por = _portal_en(ses.personaje.stage, *destino_tile)
    if por is None:
        return
    if getattr(ses, 'portal_pisado', None) == tuple(por['tile']) and (time.time() - getattr(ses, 'mapa_cambiado_en', 0) < 3.0):
        return
    vel = max(1, _velocidad_de(ses))
    espera = min(5.0, max(0.2, casillas * 25.0 / vel))

    def _saltar():
        ses.portal_armado = None
        try:
            if ses.personaje:
                p_act = _portal_en(ses.personaje.stage, *destino_tile)
                if p_act:
                    if p_act.get('preguntar'):
                        import dialogos as _dlg
                        _cfg = _portales()
                        _ops = p_act.get('opciones') or _cfg['opciones']
                        sub = _dlg.armar_linea(p_act.get('msg') or _cfg['msg'], 0, _ops)
                        ses.dlg_ent = p_act.get('entity', 0)
                        ses.dlg_guion = [sub[2:]]
                        ses.dlg_paso = 1
                        ses.dlg_val = 0
                        ses.dlg_portal = p_act
                        ses.enviar(sub)
                    else:
                        _viajar_por_portal(ses, addr, p_act, '(al terminar el paso)')
        except Exception:
            log.exception('fallo el portal armado')

    try:
        ses.portal_armado = asyncio.get_event_loop().call_later(espera, _saltar)
    except Exception:
        ses.portal_armado = None


def _cancelar_portal_armado(ses):
    h = getattr(ses, 'portal_armado', None)
    if h is not None:
        try:
            h.cancel()
        except Exception:
            pass
        ses.portal_armado = None


def _cerrar_viaje(ses, addr, stage, tile, nombre_dest):
    """Ejecuta lo que dejo pendiente un dialogo al cerrarse el cuadro.

    Medido en la captura: al confirmar la faccion quedan DOS lineas mas de
    dialogo, y solo cuando se cierra el cuadro llegan las misiones y el
    cambio de mapa. Todo eso va junto y en este orden.
    """
    import clases as _cl, time as _tm
    p = ses.personaje
    if not p:
        return
    paquetes = []

    # Las misiones: primero la de registro de la ciudad y despues la 103
    # marcada como completada.
    fac = getattr(ses, 'misiones_al_llegar', None)
    if fac:
        ses.misiones_al_llegar = None
        qreg = _cl.QUEST_POR_FACCION.get(fac)
        if qreg:
            if qreg not in [x[0] for x in (p.quests or [])]:
                p.quests = list(p.quests or []) + [(qreg, 0)]
            paquetes += [_cl.mision(p.char_id, qreg, 0),
                         _cl.aviso(_cl.nombre_de_quest(qreg), tipo=0,
                                   msg_id=_cl.MSG_QUEST)]
        paquetes.append(_cl.mision(p.char_id, _cl.QUEST_ELEGIR_PAIS, 1,
                                   int(_tm.time())))

    # La faccion se aplica al llegar, que es cuando el cliente la cambia.
    nueva = getattr(ses, 'faccion_al_llegar', None)
    if nueva:
        ses.faccion_al_llegar = None
        p.faction = nueva
        if getattr(ses, 'usuario', None):
            cuentas.guardar_faccion(ses.usuario, p.char_id, nueva)
        log.info(f"[{addr}] faccion al llegar: {nueva}")

    if paquetes:
        ses.enviar(*paquetes)
    _sincronizar_cambio_mapa(ses, stage, tile[0], tile[1])
    log.info(f"[{addr}] al cerrarse el dialogo: {nombre_dest} "
             f"(stage {stage}) casilla {tile}")


def _vida_max(p, bolsa=None) -> int:
    """El tope de vida que el cliente enseña: el guardado mas lo que dan las
    pasivas y el equipo (gear y fashion)."""
    import inventario as inv
    b = bolsa
    if b is None:
        b = getattr(p, 'inventario', None)
    if b is None and hasattr(p, 'ses'):
        b = getattr(p.ses, 'inventario', None)
    return inv.vida_maxima(getattr(p, 'hp_max', 0), getattr(p, 'habilidades', None), bolsa=b)


def _mana_max(p, bolsa=None) -> int:
    """El tope de mana que el cliente enseña: el guardado mas lo que dan las
    pasivas y el equipo (gear y fashion)."""
    import inventario as inv
    b = bolsa
    if b is None:
        b = getattr(p, 'inventario', None)
    if b is None and hasattr(p, 'ses'):
        b = getattr(p.ses, 'inventario', None)
    return inv.mana_maximo(getattr(p, 'mp_max', 0), getattr(p, 'habilidades', None), bolsa=b)


def _cb_alcance(ses) -> int:
    """Desde cuantas casillas llega el arma que se lleva puesta."""
    import combate as _cb
    arma = ses.inventario.get(3, 0) if getattr(ses, 'inventario', None) else 0
    return _cb.alcance_arma(arma)


def _stats_ses(ses):
    """Genera el paquete 0x0042 con stats completos del personaje."""
    import inventario as inv
    p = getattr(ses, 'personaje', None)
    bolsa = getattr(ses, 'inventario', None)
    habs = p.habilidades if p else None
    hp = p.hp if p else None
    hp_max = p.hp_max if p else None
    mp = p.mp if p else None
    mp_max = p.mp_max if p else None
    oro = getattr(ses, 'oro', 0)
    buffs = getattr(p, 'buffs', None)
    bars, max_pts = _max_sp_info(p)
    sp = getattr(ses, 'sp', None)
    return inv.stats(bolsa, habs, hp=hp, hp_max=hp_max, mp=mp, mp_max=mp_max, oro=oro, buffs=buffs, sp=sp, sp_max=bars)


def _otorgar_skill_exp(ses, p, yo, arma_puesta=0, magic_id=0, accion=None):
    """Otorga Skill EXP en cada impacto de ataque o uso de habilidad activa (buff/cura/spell)."""
    if not p or not getattr(p, 'habilidades', None):
        return []
    import configuracion, cuentas, clases as _cl, combate as _cb, inventario as _iv
    pkgs = []
    mult = configuracion.multiplicador_skill_exp()
    exp_ganada = max(1, int(round(1 * mult)))

    SKILLS_PRODUCTOR = {20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31}

    # Las habilidades de arma de TODO lo equipado, no solo de la ranura del
    # arma: un Protector con hacha y escudo entrena Axe y Shield, y asi sale
    # en las capturas de Celestia.
    skills_arma = _cl.skills_de_equipo(getattr(ses, 'inventario', None))
    if not skills_arma and arma_puesta:
        sid_a = _cl.skill_de_item(arma_puesta)
        if sid_a:
            skills_arma = {sid_a}

    nuevas_habs = []
    subio_alguna = False
    # Suben TODAS las habilidades del personaje, no solo la del arma. En las
    # capturas de Celestia aparecen Reserve, Finesse, Grapple, Garment,
    # Enhance y Sword con recuentos parecidos (23, 23, 23, 21, 20, 19 sobre
    # 2824 golpes), asi que cada una tira su propia probabilidad por golpe.
    # El valor base es 1: los "100 Exp" de la captura son el multiplicador de
    # ese servidor.
    # Que habilidades pueden subir con esta accion. Un espadachin no sube
    # Cook ni Fishing por pegarle a un monstruo: cada habilidad tiene su
    # actividad, declarada en skill.xml (ver clases.ACCION_POR_SKILL).
    mag_branch = _cl.skill_de_magia(magic_id) if magic_id else None
    if accion is None:
        if mag_branch in (1, 2, 3, 4, 5, 6, 7, 8, 34, 35, 36) or (8 in skills_arma) or (magic_id and not skills_arma):
            accion = 'magia'
        elif 17 in skills_arma or mag_branch == 17:
            accion = 'distancia'      # con arco
        else:
            accion = 'melee'
    # skills_arma va adentro: es lo que arrastra Shield con espada o hacha,
    # y Snipe y Eagle Eye con arco.
    candidatas = _cl.skills_que_suben(accion, skills_arma)
    if mag_branch:
        candidatas.add(mag_branch)
    for h in p.habilidades:
        sid, slv, sexp = h[0], h[1], h[2]
        if sid not in candidatas or random.random() >= _cb.PROB_SKILL_EXP:
            nuevas_habs.append((sid, slv, sexp))
            continue
        sexp += exp_ganada
        max_lv = (p.nivel + 11) if sid in SKILLS_PRODUCTOR else p.nivel
        # La experiencia que pide cada nivel sale de la tabla medida en las
        # capturas (3, 6, 8, 12, 16, 30...), no de nivel*100: con esa formula
        # dos puntos de exp daban 0% y la habilidad no subia nunca.
        req = max(1, _cl.exp_requerida_skill(slv))
        while sexp >= req and slv < max_lv:
            sexp -= req
            slv += 1
            req = max(1, _cl.exp_requerida_skill(slv))
            subio_alguna = True
            pkgs.append(_cb.efecto_level_up(yo, es_skill=True))
            pkgs.append(_cl.aviso_doble(_cl.MSG_SKILL_SUBE, _cl.nombre(sid)))
        if slv >= max_lv:
            sexp = min(sexp, req)
        pct_exp = min(100, int(round(100.0 * sexp / req)))
        # La skill exp va como TEXTO en un 0x000D de dos cadenas, no como
        # 0x000B: ese mensaje dibuja un numero flotante, y mandandolo con el
        # numero de la habilidad aparecia un "9" verde junto al dano.
        pkgs.append(_cl.aviso_doble(_cl.MSG_SKILL_EXP, _cl.nombre(sid),
                                    str(exp_ganada)))
        # 0x001D kind=53: la barra porcentual de esa habilidad en la UI
        pkgs.append(struct.pack('<HIBBII', 0x001D, yo, 1, 53, sid, pct_exp))
        nuevas_habs.append((sid, slv, sexp))

    p.habilidades = nuevas_habs
    if pkgs:
        # El arbol va en CADA ganancia, no solo al subir: es el mensaje que
        # lleva la experiencia de cada habilidad y por lo tanto el porcentaje
        # que muestra el panel.
        pkgs.append(_cl.arbol(p.habilidades))
    if subio_alguna:
        pkgs.append(_stats_ses(ses))

    if getattr(ses, 'usuario', None):
        cuentas.guardar_progreso(ses.usuario, p.char_id, p.nivel, p.exp,
                                 p.hp, p.mp, p.habilidades,
                                 hp_max=p.hp_max, mp_max=p.mp_max)
    return pkgs


class Servidor:
    def __init__(self, host, port, fport=21238, wport=None):
        self.host, self.port, self.fport = host, port, fport
        # puerto del servidor de MUNDO, al que se redirige tras el login
        self.wport = wport or (port + 1)
        self.desconocidos = collections.Counter()
        self.sesiones = 0
        # Traspaso login -> mundo. Son dos conexiones TCP distintas: cuando
        # el cliente pide entrar (0x0006) anotamos aca que personaje eligio,
        # y la conexion de mundo que llega despues lo levanta. Se indexa por
        # IP porque el puerto de origen cambia entre las dos conexiones.
        self.pendientes = {}

    async def _patrulla_lyceum(self, ses):
        """Mueve a los House Pickets periodicamente para que patrullen el Angel Lyceum,
        y gestiona el respawn de monstruos y movimiento de la mascota."""
        rutas = [
            (5, [(94, 55), (94, 61)]),
            (6, [(123, 53), (128, 53)]),
            (7, [(145, 81), (150, 81)]),
            (12, [(145, 71), (145, 77)]),
            (16, [(217, 75), (211, 75)]),
        ]
        estado = {eid: 0 for eid, _ in rutas}
        MOVE = Msg.registry[(0x0005, 's2c', '*')]
        try:
            while True:
                await asyncio.sleep(5)
                if not getattr(ses, 'personaje', None):
                    continue

                # 1. Patrulla de House Pickets en Angel Lyceum
                if ses.personaje.stage == 41:
                    for eid, pts in rutas:
                        idx = estado[eid]
                        nxt = 1 - idx
                        cur_t = pts[idx]
                        dst_t = pts[nxt]
                        estado[eid] = nxt
                        msg = MOVE.build(
                            entity_id=eid,
                            cur_x=cur_t[0] * 32,
                            cur_y=cur_t[1] * 32,
                            dst_x=dst_t[0] * 32,
                            dst_y=dst_t[1] * 32,
                            speed=50
                        )
                        ses.enviar(msg)

                # 2. Respawn de monstruos caidos
                monstruos = getattr(ses, 'monstruos', {})
                import login as _lg
                for mid, m in list(monstruos.items()):
                    if m.toca_reaparecer():
                        m.revivir()
                        ses.enviar(_lg._npc_spawn(m.entity_id, m.npc_type, m.nombre, m.spawn_tile, klass=1))
                        log.info(f"monstruo {m.nombre} (eid={m.entity_id}) reaparecio en {m.spawn_tile}")

                # 3. Seguimiento de mascota al jugador
                pet_id = getattr(ses, 'pet_entity_id', None)
                if pet_id and ses.personaje:
                    px, py = ses.personaje.tile_x, ses.personaje.tile_y
                    msg_pet = MOVE.build(
                        entity_id=pet_id,
                        cur_x=(px + 1) * 32,
                        cur_y=py * 32,
                        dst_x=px * 32,
                        dst_y=py * 32,
                        speed=100
                    )
                    ses.enviar(msg_pet)

                out = ses.drenar()
                if out and getattr(ses, 'writer', None):
                    try:
                        if getattr(ses, 'grab', None):
                            ses.grab.salida(out)
                        ses.writer.write(out)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"patrulla lyceum detenida: {e}")

    async def _bucle_regeneracion(self, ses):
        """Regeneracion pasiva de HP y MP:
        - Sentado (tecla Insert): cada 1 segundo recupera +6 MP y +12 HP.
        - Quieto de pie (al menos 2s quieto y sin combate): cada 2 segundos recupera +6 MP y +6 HP.
        """
        import combate as _cb
        try:
            while getattr(ses, 'conectado', True):
                await asyncio.sleep(1.0)
                p = getattr(ses, 'personaje', None)
                if not p:
                    continue

                yo = p.entity_id
                sentado = getattr(ses, 'sentado', False)
                ahora = time.time()
                ultimo_mov = getattr(ses, 'ultimo_movimiento', 0)
                ultimo_comb = getattr(ses, 'ultimo_combate', 0)
                en_combate = (ahora - ultimo_comb) < 4.0

                toca_regen = False
                if sentado:
                    toca_regen = True
                    rec_mp = 6
                    rec_hp = 12
                else:
                    if (ahora - ultimo_mov) >= 2.0 and not en_combate:
                        ultimo_tick = getattr(ses, 'ultimo_regen_tick', 0)
                        if (ahora - ultimo_tick) >= 2.0:
                            toca_regen = True
                            ses.ultimo_regen_tick = ahora
                            rec_mp = 6
                            rec_hp = 6

                if toca_regen:
                    pkgs = []
                    bolsa_pj = getattr(ses, 'inventario', None)
                    eff_hp_max = _vida_max(p, bolsa=bolsa_pj)
                    eff_mp_max = _mana_max(p, bolsa=bolsa_pj)
                    if p.mp < eff_mp_max:
                        p.mp = min(eff_mp_max, p.mp + rec_mp)
                        pkgs.append(_cb.atributo(yo, p.mp, _cb.KIND_MP))
                    if p.hp < eff_hp_max:
                        p.hp = min(eff_hp_max, p.hp + rec_hp)
                        pkgs.append(_cb.atributo(yo, p.hp, _cb.KIND_HP))

                    if pkgs:
                        ses.enviar_inmediato(*pkgs)
                        if getattr(ses, 'usuario', None):
                            cuentas.guardar_progreso(ses.usuario, p.char_id, p.nivel, p.exp,
                                                     p.hp, p.mp, p.habilidades,
                                                     hp_max=p.hp_max, mp_max=p.mp_max)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"bucle de regeneracion detenido: {e}")

    async def cliente(self, reader, writer, rol='mundo'):
        addr = writer.get_extra_info('peername')
        self.sesiones += 1
        ses = Session(addr)
        ses.rol = rol
        ses.puerto = self.port if rol == 'login' else self.wport
        ses.writer = writer
        grab = Grabador(addr, self.port if rol == 'login' else self.wport, ses.key)
        ses.grab = grab
        ses.patrulla_task = asyncio.create_task(self._patrulla_lyceum(ses)) if rol == 'mundo' else None
        ses.regen_task = asyncio.create_task(self._bucle_regeneracion(ses)) if rol == 'mundo' else None
        log.info(f"[{addr}] conectado ({rol})  clave={ses.key.hex(' ')}")
        log.info(f"[{addr}] grabando sesion -> logs/sesiones/{ses.grab.base}_*.bin")
        ses.enviar_hello()
        primero = ses.drenar()
        ses.grab.salida(primero)
        writer.write(primero)
        await writer.drain()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                grab.entrada(data)
                for opcode, cuerpo in ses.alimentar(data):
                    ses.vistos[opcode] += 1
                    grab.submensaje('c2s', opcode, cuerpo)
                    m, d = ses.parsear(opcode, cuerpo)
                    if m is None:
                        self.desconocidos[opcode] += 1
                        log.debug(f"[{addr}] 0x{opcode:04X} sin esquema "
                                  f"({len(cuerpo)}B): {cuerpo[:24].hex(' ')}")
                    else:
                        log.debug(f"[{addr}] {m.name} {d if d else '(no parsea)'}")
                    # el dispatcher corre igual: un opcode sin esquema puede
                    # necesitar respuesta (la autenticacion es el caso tipico)
                    self.manejar(ses, opcode, m, d, addr, cuerpo)
                salida = ses.drenar()
                if salida:
                    grab.salida(salida)
                    writer.write(salida)
                    await writer.drain()

        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            if getattr(ses, 'patrulla_task', None):
                ses.patrulla_task.cancel()
            if getattr(ses, 'regen_task', None):
                ses.regen_task.cancel()
            # Guardar donde quedo el personaje, para que al volver a entrar
            # aparezca ahi y no en el punto de aparicion.
            if getattr(ses, 'personaje', None) and getattr(ses, 'usuario', None):
                try:
                    cuentas.guardar_posicion(ses.usuario, ses.personaje.char_id,
                                             ses.personaje.tile_x,
                                             ses.personaje.tile_y)
                    log.info(f"[{addr}] posicion guardada: "
                             f"({ses.personaje.tile_x},{ses.personaje.tile_y})")
                except Exception as e:
                    log.warning(f"[{addr}] no se pudo guardar la posicion: {e}")
            base, nc, ns = grab.cerrar()
            log.info(f"[{addr}] desconectado. opcodes vistos: "
                     f"{dict(ses.vistos.most_common(8))}")
            log.info(f"[{addr}] sesion grabada: {nc} B del cliente, "
                     f"{ns} B del servidor -> logs/sesiones/{base}_*.bin")
            if self.desconocidos:
                log.warning(f"[{addr}] opcodes SIN ESQUEMA que mando el cliente: "
                            f"{ {f'0x{k:04X}': v for k, v in self.desconocidos.items()} }")
            writer.close()

    def manejar(self, ses, opcode, m, d, addr, cuerpo=b''):
        """Login: responde MOTD + personajes + redirect. Mundo: entra al juego."""
        if opcode == 0x0002 and ses.rol == 'login':
            usuario = login_server.usuario_de_auth(cuerpo)
            ses.usuario = usuario
            cuentas.guardar_muestra_auth(cuerpo, f"usuario='{usuario}' desde {addr}")
            cuenta, motivo = cuentas.validar(usuario, cuerpo)
            if cuenta is None:
                log.warning(f"[{addr}] LOGIN RECHAZADO usuario='{usuario}': {motivo}")
                ses.enviar_crudo(login_server.respuesta_error())
                return
            log.info(f"[{addr}] LOGIN usuario='{usuario}' aceptado ({motivo})")
            # Solo lo que este guardado de verdad. Nada inventado.
            lista = list(cuenta.get('personajes', []))[:3]
            import os as _o
            # Ajustables para bisecar: los tres unicos campos que todavia
            # difieren del bloque real (ranuras=1, subcanal=3, clase=5).
            _ran = int(_o.environ.get('AO_RANURAS', 3))
            _sub = int(_o.environ.get('AO_SUBCANAL', 2))
            _cls = _o.environ.get('AO_CLASE')
            # El cliente se CONGELA sin intentar ninguna conexion, asi que el
            # bloqueo es local -- muy probablemente la carga del mapa. Con
            # AO_MAPA se puede probar otro stage_id sin recrear el personaje.
            _mapa = _o.environ.get('AO_MAPA')
            if _mapa is not None:
                for _p in lista:
                    _p['stage_id'] = int(_mapa)
            if _cls is not None:
                for _p in lista:
                    _p['class_id'] = int(_cls)
            if _o.environ.get('AO_BLOQUE_REAL'):
                # Manda el bloque de cuenta CAPTURADO tal cual, sin generar
                # nada. Si con los bytes literales de un servidor que
                # funcionaba el cliente tampoco entra, el bloque queda
                # descartado de forma concluyente.
                import struct as _s
                _b = (pathlib.Path(__file__).parent / 'plantillas'
                      / 'login_bloque_real.bin').read_bytes()
                ses.enviar_crudo(_s.pack('<HH', len(_b) + 2, 0x0000) + _b)
                log.warning(f"[{addr}] usando el BLOQUE REAL capturado "
                            f"({len(_b)} B), no el generado")
            else:
                ses.enviar_crudo(login_server.respuesta_login(
                    lista, cuenta=usuario, ranuras=_ran, subcanal=_sub))
            log.info(f"[{addr}] ranuras={_ran} subcanal={_sub} "
                     f"clase={_cls or 'la del pj'} mapa={_mapa or 'el del pj'}")
            log.info(f"[{addr}] ranuras: {len(lista)} con personaje, "
                     f"{3 - len(lista)} libres")
            import os as _os
            # Diagnostico: con AO_REDIRECT_AL_LOGIN=1 el redirect apunta al
            # MISMO puerto del login. Si aparece una SEGUNDA conexion, el
            # cliente si actua sobre el redirect y el problema esta en la
            # sesion de mundo. Si no aparece, lo esta ignorando.
            # El redirect NO va aca. Se manda como respuesta a 0x0006, que es
            # el pedido de ENTRAR AL MUNDO. Mandarlo apenas llega el AUTH hace
            # que el cliente lo reciba antes de pedir entrar, lo descarte, y
            # despues quede esperando una respuesta que nunca llega -- que es
            # exactamente el congelamiento que veniamos persiguiendo.
            log.info(f"[{addr}] lista enviada; esperando 0x0006 para entrar")
            # NO cerrar la conexion de login aca. Se probo y el cliente
            # muestra "The connection with the server has been interrupted":
            # trata el cierre como caida. La nota del proyecto anterior sobre
            # "cerrar el socket de login" describia un cierre PREMATURO como
            # causa de aborto, no un cierre necesario. Mal interpretada.
            return

        if opcode == 0x0003 and ses.rol == 'login':
            import personajes, pathlib as _pl
            d = personajes.parsear_creacion(cuerpo)
            if not d['nombre']:
                log.warning(f"[{addr}] CREAR: nombre vacio, se ignora")
                return
            cta = cuentas.cargar()['cuentas'].get(ses.usuario) or {'personajes': []}
            usados = {x.get('char_id', 0) for x in cta.get('personajes', [])}
            nuevo = personajes.personaje_nuevo(
                d['nombre'], d['ranura'], max(usados or [1000]) + 1)
            personajes.guardar(ses.usuario, nuevo, cuentas.ARCHIVO)
            ses.enviar(personajes.respuesta_creacion(d['ranura'], nuevo))
            log.info(f"[{addr}] PERSONAJE CREADO '{nuevo['nombre']}' "
                     f"ranura={d['ranura']} id={nuevo['char_id']} "
                     f"nivel={nuevo['nivel']} mapa={nuevo['stage_id']} -> guardado")
            return

        if opcode == 0x0004 and ses.rol == 'login':
            # BORRAR PERSONAJE. Medido en Celestia (login_032338_580015):
            #   C2S 0x0004  [u8 unk][PIN de 33 bytes]
            #   S2C 0x0002  [2 bytes][LE32 char_id]
            #   y la lista de personajes otra vez
            # Alli el borrado queda en espera ocho horas (28799 s en la
            # lista); aqui se borra en el acto, que es lo util para probar.
            import login_server as _ls
            ranura = cuerpo[0] if cuerpo else 0
            char_id = cuentas.borrar_personaje(ses.usuario, ranura)
            if char_id is None:
                log.warning(f"[{addr}] BORRAR: no hay personaje en la ranura {ranura}")
                return
            ses.enviar(struct.pack('<HHI', 0x0002, 0, char_id))
            cta = cuentas.cargar()['cuentas'].get(ses.usuario) or {'personajes': []}
            ses.enviar(_ls.respuesta_login(cta.get('personajes', []),
                                           cuenta=ses.usuario))
            log.info(f"[{addr}] PERSONAJE BORRADO: ranura {ranura} "
                     f"char_id {char_id} (sin espera)")
            return

        if opcode == 0x0006 and ses.rol == 'login':
            # ENTRAR AL MUNDO. El cuerpo trae la ruta del sprite del personaje
            # elegido, por ejemplo "\chr\i263g\20263_Wait.spr".
            import os as _o2
            _pt = self.port if _o2.environ.get('AO_REDIRECT_AL_LOGIN') else self.wport
            ranura = cuerpo[0] if cuerpo else 0
            txt = bytes(c if 32 <= c < 127 else 46 for c in cuerpo[:40]).decode()
            cta = cuentas.cargar()['cuentas'].get(ses.usuario) or {}
            elegidos = list(cta.get('personajes', []))
            nombre = elegidos[ranura]['nombre'] if ranura < len(elegidos) else '?'
            self.pendientes[addr[0]] = (ses.usuario, ranura)
            log.info(f"[{addr}] ENTRAR AL MUNDO ranura={ranura} -> '{nombre}'")
            log.info(f"[{addr}] 0x0006 sprite: {txt}")
            ses.enviar(login_server.redirect(self.host, _pt))
            log.info(f"[{addr}] redirigido a {self.host}:{_pt}")
            return

        if opcode == 0x0002 and not ses.entity_id:
            # El cliente se autentico. Entra al mundo.
            # No se validan credenciales: el bloque de 16 B no esta descifrado.
            # Se guarda el AUTH crudo para poder deducir su formato despues.
            if d and d.get('credenciales'):
                cuentas.guardar_muestra_auth(d['credenciales'], f"desde {addr}")
            usuario, ranura = self.pendientes.get(addr[0], (None, 0))
            if usuario is None:
                log.warning(f"[{addr}] conexion de mundo sin 0x0006 previo; "
                            f"no se sabe que personaje cargar")
                return
            cuenta = cuentas.cargar()['cuentas'].get(usuario) or {}
            p = cuentas.personaje_de(cuenta, ranura)
            # La sesion de MUNDO es otra conexion TCP: no paso por el handler
            # de login, asi que no tiene ses.usuario. Sin esto, guardar el
            # inventario fallaba en silencio y todo volvia a su sitio al
            # reconectar.
            ses.usuario = usuario
            if p is None:
                log.warning(f"[{addr}] la ranura {ranura} de '{usuario}' "
                            f"esta vacia")
                return
            ses.entity_id = p.entity_id
            ses.personaje = p
            for sub in secuencia(p):
                ses.enviar(sub)
            # El inventario va dentro de la secuencia de entrada: el 0x001A
            # se arma con el del personaje, asi que cada item ya sale en su
            # ranura y no hay que corregir nada despues.
            import inventario as inv
            # La MISMA referencia, no una copia: con dict(p.inventario) se
            # trabajaba sobre una copia y al recargar el mapa la secuencia
            # volvia a leer p.inventario, que seguia sin los items entregados.
            # De ahi que los regalos solo aparecieran al reconectar.
            ses.inventario = p.inventario
            ses.cantidades = p.cantidades
            ses.oro = p.oro
            ses.monstruos = _monstruos_de(p.stage)
            bars, max_pts = _max_sp_info(p)
            ses.sp = getattr(ses, 'sp', None) or max_pts
            ses.enviar(inv.stats(ses.inventario, p.habilidades,
                                 hp=p.hp, hp_max=p.hp_max,
                                 mp=p.mp, mp_max=p.mp_max,
                                 oro=p.oro, sp=ses.sp, sp_max=bars))
            import combate as _cb
            ses.enviar(_cb.atributo(p.entity_id, ses.sp, _cb.KIND_SP))
            # El arbol de habilidades tambien al entrar, no solo al elegir
            # clase: si no, al reconectar el panel vuelve a salir lleno de
            # interrogantes.
            if p.habilidades:
                import clases as _cl
                ses.enviar(_cl.arbol(p.habilidades, banco=getattr(p, 'banco_habilidades', None)))
                _ids = [h[0] for h in p.habilidades]
                _hech = _cl.hechizos_iniciales(_ids)
                _todos_hech = [n for n, _ in _hech]
                if getattr(p, 'hechizos_aprendidos', None):
                    _todos_hech = list(set(_todos_hech) | set(p.hechizos_aprendidos))
                if _todos_hech:
                    ses.enviar(_cl.otorgar_hechizos(
                        p.entity_id, _todos_hech))
            # Y que el cliente dibuje al personaje con lo que lleva puesto.
            ses.enviar(*_apariencia(ses))
            # Iniciar tarea asincrona de IA para que los monstruos paseen por el mapa y ataquen
            async def _ia_monstruos():
                import random, time
                import combate as _cb
                TICK_IA = 0.1
                # La probabilidad de pasear sale del tick: un paso cada 5.6 s
                # de mediana, que es lo medido en el Lyceum de Celestia.
                PROB_PASO = TICK_IA / _cb.SEGUNDOS_ENTRE_PASEOS
                MOVE = Msg.registry[(0x0005, 's2c', '*')]
                try:
                    while getattr(ses, 'personaje', None):
                        # Cada 100 ms. Las cadencias de los monstruos van de
                        # 672 a 1120 ms: con un bucle de 300 ms un bicho de
                        # 1.0 s acababa pegando cada 1.2 s y a saltos, que es
                        # lo que se veia con las Lilys (lentas y no fluidas).
                        await asyncio.sleep(TICK_IA)
                        p = getattr(ses, 'personaje', None)
                        if not p:
                            continue
                        ahora = time.time()
                        yo = p.entity_id

                        if getattr(ses, 'muerto', False):
                            # Un jugador muerto no recibe mas golpes: si no,
                            # la IA lo seguia matando y la ventana de muerte
                            # se reabria una y otra vez.
                            continue

                        # --- Invocacion del jugador (Wraith summon) ---
                        inv = getattr(ses, 'invocacion', None)
                        if inv:
                            if ahora >= inv.get('expira', 0) or inv.get('hp', 0) <= 0:
                                ses.enviar(_cb.atributo(inv['entity_id'], 0, _cb.KIND_HP),
                                           _cb.despawn_monstruo(inv['entity_id']),
                                           struct.pack('<HIBBI', 0x0013, yo, 1, 0x3d, 0))
                                ses.invocacion = None
                                log.info(f"[{addr}] invocacion {inv.get('nombre')} expirada/despawned")
                            else:
                                targ = inv.get('objetivo')
                                if targ and (not getattr(targ, 'vivo', False) or targ.hp <= 0 or getattr(targ, 'encantado', False)):
                                    inv['objetivo'] = None
                                    targ = None

                                if targ:
                                    dist_tx = abs(inv['tile_x'] - targ.tile_x)
                                    dist_ty = abs(inv['tile_y'] - targ.tile_y)
                                    dist_t = max(dist_tx, dist_ty)
                                    r_inv = max(1, inv.get('atk_range', 1))
                                    if dist_t > 15:
                                        inv['objetivo'] = None
                                    elif dist_t <= r_inv:
                                        cad_inv = max(0.65, min(1.0, 1.264 - 0.00477 * inv.get('atk_speed', 80)))
                                        if ahora - inv.get('ultimo_ataque', 0) >= cad_inv:
                                            inv['ultimo_ataque'] = ahora
                                            skills_inv = inv.get('skills', [])
                                            usa_skill = skills_inv and (random.random() < 0.45)
                                            crit_rate = inv.get('crit_rate', 5)
                                            es_crit = (random.randint(1, 100) <= crit_rate)
                                            mult_inv = 1.5 if es_crit else 1.0

                                            if usa_skill:
                                                atk_magic = random.choice(skills_inv)
                                                atk_efecto = _cb.efecto_de_ataque(atk_magic) or 148
                                                pow_atk = max(inv['atk'], inv.get('matk', 0))
                                                dano_base = pow_atk + int(round(_cb.stance_de(atk_magic) * _cb.PESO_STANCE))
                                                mult_inv *= 1.2
                                                es_mag = True
                                            else:
                                                atk_magic = 656
                                                atk_efecto = 0
                                                dano_base = inv['atk']
                                                es_mag = False

                                            dano_inv = targ.recibir(dano_base, es_magico=es_mag, mult=mult_inv)
                                            anim_inv = _cb.anim_de_monstruo(inv.get('nombre', '')) or 832
                                            tipo_dmg = _cb.TIPO_DANO_CRITICO if es_crit else _cb.TIPO_DANO
                                            if getattr(targ, 'en_combate_con', None) is None:
                                                targ.en_combate_con = yo

                                            pkgs_inv_hit = [_cb.ataque(inv['entity_id'], targ.entity_id, anim_inv)]
                                            if usa_skill:
                                                pkgs_inv_hit.extend([
                                                    _cb.numero_de_dano(inv['entity_id'], targ.entity_id, dano_inv, ataque=atk_magic, efecto=atk_efecto),
                                                    _cb.cierre_de_dano(inv['entity_id'], targ.entity_id, ataque=atk_magic, efecto=atk_efecto),
                                                ])
                                            pkgs_inv_hit.append(_cb.numero_flotante(targ.entity_id, dano_inv, tipo=tipo_dmg))

                                            if targ.hp <= 0:
                                                targ.hp = 0
                                                inv['objetivo'] = None
                                                pkgs_inv_hit.append(_cb.atributo(targ.entity_id, 0, _cb.VIDA))
                                                ses.enviar_inmediato(*pkgs_inv_hit)
                                                _procesar_muerte_monstruo(ses, targ, yo, addr, espera=0.1)
                                            else:
                                                pkgs_inv_hit.append(_cb.atributo(targ.entity_id, targ.porcentaje))
                                                ses.enviar_inmediato(*pkgs_inv_hit)
                                    else:
                                        if ahora >= inv.get('proximo_paso', 0):
                                            dx = targ.tile_x - inv['tile_x']
                                            dy = targ.tile_y - inv['tile_y']
                                            dist_t = max(abs(dx), abs(dy))
                                            r_inv = inv.get('atk_range', 1)
                                            pasos_dar = min(max(1, dist_t - r_inv), 3)
                                            stx = (1 if dx > 0 else (-1 if dx < 0 else 0)) * pasos_dar
                                            sty = (1 if dy > 0 else (-1 if dy < 0 else 0)) * pasos_dar
                                            cur_x, cur_y = inv['tile_x'] * 32, inv['tile_y'] * 32
                                            inv['tile_x'] += stx
                                            inv['tile_y'] += sty
                                            dst_x, dst_y = inv['tile_x'] * 32, inv['tile_y'] * 32
                                            _pasos = max(abs(stx), abs(sty)) or 1
                                            spd = inv.get('move_speed', 50) or 50
                                            inv['proximo_paso'] = ahora + (_pasos * 32.0 / spd)
                                            ses.enviar(MOVE.build(entity_id=inv['entity_id'],
                                                                  cur_x=cur_x, cur_y=cur_y,
                                                                  dst_x=dst_x, dst_y=dst_y,
                                                                  speed=spd))
                                else:
                                    # Seguir al jugador si no tiene objetivo
                                    p_dx = p.tile_x - inv['tile_x']
                                    p_dy = p.tile_y - inv['tile_y']
                                    p_dist = max(abs(p_dx), abs(p_dy))
                                    if p_dist > 15:
                                        inv['tile_x'] = p.tile_x + 1
                                        inv['tile_y'] = p.tile_y
                                        cur_x, cur_y = inv['tile_x'] * 32, inv['tile_y'] * 32
                                        ses.enviar(MOVE.build(entity_id=inv['entity_id'],
                                                              cur_x=cur_x, cur_y=cur_y,
                                                              dst_x=cur_x, dst_y=cur_y,
                                                              speed=inv.get('move_speed', 50) or 50))
                                    elif p_dist > 2 and ahora >= inv.get('proximo_paso', 0):
                                        pasos_dar = min(p_dist - 2, 3)
                                        stx = (1 if p_dx > 0 else (-1 if p_dx < 0 else 0)) * pasos_dar
                                        sty = (1 if p_dy > 0 else (-1 if p_dy < 0 else 0)) * pasos_dar
                                        cur_x, cur_y = inv['tile_x'] * 32, inv['tile_y'] * 32
                                        inv['tile_x'] += stx
                                        inv['tile_y'] += sty
                                        dst_x, dst_y = inv['tile_x'] * 32, inv['tile_y'] * 32
                                        _pasos = max(abs(stx), abs(sty)) or 1
                                        spd = inv.get('move_speed', 50) or 50
                                        inv['proximo_paso'] = ahora + (_pasos * 32.0 / spd)
                                        ses.enviar(MOVE.build(entity_id=inv['entity_id'],
                                                              cur_x=cur_x, cur_y=cur_y,
                                                              dst_x=dst_x, dst_y=dst_y,
                                                              speed=spd))

                        for m in list((ses.monstruos or {}).values()):

                            if not getattr(m, 'vivo', True):
                                continue

                            # Monstruo encantado (Charmed / Shining Charm de Earth): aliado del jugador
                            if getattr(m, 'encantado', False):
                                if ahora >= getattr(m, 'encantado_expira', 0):
                                    m.encantado = False
                                    m.charmed_objetivo = None
                                    if getattr(ses, 'monstruo_encantado', None) == m:
                                        ses.monstruo_encantado = None
                                    ses.enviar(
                                        struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, 303, 0),
                                        struct.pack('<HIBBI', 0x0013, m.entity_id, 1, 0x3c, 0)
                                    )
                                    log.info(f"[{addr}] encanto sobre {m.nombre} expirado")
                                else:
                                    ch_targ = getattr(m, 'charmed_objetivo', None)
                                    if ch_targ and (not getattr(ch_targ, 'vivo', False) or ch_targ.hp <= 0 or getattr(ch_targ, 'encantado', False)):
                                        m.charmed_objetivo = None
                                        ch_targ = None

                                    if ch_targ:
                                        dtx = abs(m.tile_x - ch_targ.tile_x)
                                        dty = abs(m.tile_y - ch_targ.tile_y)
                                        dt = max(dtx, dty)
                                        r_m = max(1, getattr(m, 'atk_range', 1))
                                        if dt <= r_m:
                                            if ahora - getattr(m, 'ultimo_ataque', 0) >= _cb.cadencia_monstruo(m):
                                                m.ultimo_ataque = ahora
                                                dano_ch = max(5, m.pegar() - getattr(ch_targ, 'defensa', 0) // 2)
                                                ch_targ.hp = max(0, ch_targ.hp - dano_ch)
                                                anim_m = _cb.anim_de_monstruo(m.nombre)
                                                if ch_targ.hp <= 0:
                                                    ch_targ.hp = 0
                                                    m.charmed_objetivo = None
                                                    ses.enviar_inmediato(
                                                        _cb.ataque(m.entity_id, ch_targ.entity_id, anim_m),
                                                        _cb.numero_de_dano(m.entity_id, ch_targ.entity_id, dano_ch, ataque=656, efecto=148),
                                                        _cb.cierre_de_dano(m.entity_id, ch_targ.entity_id, ataque=656, efecto=148),
                                                        _cb.numero_flotante(ch_targ.entity_id, dano_ch),
                                                        _cb.atributo(ch_targ.entity_id, 0, _cb.VIDA)
                                                    )
                                                    _procesar_muerte_monstruo(ses, ch_targ, yo, addr, espera=0.1)
                                                else:
                                                    ses.enviar_inmediato(
                                                        _cb.ataque(m.entity_id, ch_targ.entity_id, anim_m),
                                                        _cb.numero_de_dano(m.entity_id, ch_targ.entity_id, dano_ch, ataque=656, efecto=148),
                                                        _cb.cierre_de_dano(m.entity_id, ch_targ.entity_id, ataque=656, efecto=148),
                                                        _cb.numero_flotante(ch_targ.entity_id, dano_ch),
                                                        _cb.atributo(ch_targ.entity_id, ch_targ.porcentaje)
                                                    )
                                        else:
                                            if ahora >= getattr(m, 'proximo_paso', 0):
                                                dx = ch_targ.tile_x - m.tile_x
                                                dy = ch_targ.tile_y - m.tile_y
                                                dist_t = max(abs(dx), abs(dy))
                                                pasos_dar = min(max(1, dist_t - r_m), 3)
                                                stx = (1 if dx > 0 else (-1 if dx < 0 else 0)) * pasos_dar
                                                sty = (1 if dy > 0 else (-1 if dy < 0 else 0)) * pasos_dar
                                                cur_x, cur_y = m.tile_x * 32, m.tile_y * 32
                                                m.tile_x += stx
                                                m.tile_y += sty
                                                m.tile[0], m.tile[1] = m.tile_x, m.tile_y
                                                dst_x, dst_y = m.tile_x * 32, m.tile_y * 32
                                                _pasos = max(abs(stx), abs(sty)) or 1
                                                spd = m.move_speed or _cb.VELOCIDAD_PASEO
                                                m.proximo_paso = ahora + (_pasos * 32.0 / spd)
                                                ses.enviar(MOVE.build(entity_id=m.entity_id,
                                                                      cur_x=cur_x, cur_y=cur_y,
                                                                      dst_x=dst_x, dst_y=dst_y,
                                                                      speed=spd))
                                    else:
                                        p_dx = p.tile_x - m.tile_x
                                        p_dy = p.tile_y - m.tile_y
                                        p_dist = max(abs(p_dx), abs(p_dy))
                                        if p_dist > 2 and ahora >= getattr(m, 'proximo_paso', 0):
                                            pasos_dar = min(p_dist - 2, 3)
                                            stx = (1 if p_dx > 0 else (-1 if p_dx < 0 else 0)) * pasos_dar
                                            sty = (1 if p_dy > 0 else (-1 if p_dy < 0 else 0)) * pasos_dar
                                            cur_x, cur_y = m.tile_x * 32, m.tile_y * 32
                                            m.tile_x += stx
                                            m.tile_y += sty
                                            m.tile[0], m.tile[1] = m.tile_x, m.tile_y
                                            dst_x, dst_y = m.tile_x * 32, m.tile_y * 32
                                            _pasos = max(abs(stx), abs(sty)) or 1
                                            spd = m.move_speed or _cb.VELOCIDAD_PASEO
                                            m.proximo_paso = ahora + (_pasos * 32.0 / spd)
                                            ses.enviar(MOVE.build(entity_id=m.entity_id,
                                                                  cur_x=cur_x, cur_y=cur_y,
                                                                  dst_x=dst_x, dst_y=dst_y,
                                                                  speed=spd))
                                continue

                            # El sangrado / veneno le resta vida aunque nadie lo toque,
                            # y un monstruo aturdido no se mueve ni ataca.
                            _sang = m.tick_sangrado()
                            if _sang:
                                ses.enviar(_cb.numero_flotante(m.entity_id, _sang, tipo=_cb.TIPO_DANO),
                                           _cb.atributo(m.entity_id, m.porcentaje))
                                if not m.vivo:
                                    if getattr(m, 'efectos_activos', None):
                                        for emid in list(m.efectos_activos.keys()):
                                            ses.enviar(struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, emid, 0))
                                        m.efectos_activos.clear()
                                    ses.enviar(_cb.muerte_monstruo(m.entity_id, yo),
                                               _cb.despawn_monstruo(m.entity_id))
                                    continue
                            if m.aturdido:
                                continue

                            if getattr(m, 'panico', False):
                                if ahora >= getattr(m, 'panico_hasta', 0):
                                    m.panico = False
                                else:
                                    m.en_combate_con = None
                                    if ahora >= getattr(m, 'proximo_paso', 0):
                                        p_dx = m.tile_x - p.tile_x
                                        p_dy = m.tile_y - p.tile_y
                                        stride = random.randint(2, 4)
                                        dir_x = 1 if p_dx > 0 else (-1 if p_dx < 0 else random.choice([-1, 1]))
                                        dir_y = 1 if p_dy > 0 else (-1 if p_dy < 0 else random.choice([-1, 1]))
                                        new_x = max(0, m.tile_x + dir_x * stride)
                                        new_y = max(0, m.tile_y + dir_y * stride)
                                        cur_x, cur_y = m.tile_x * 32, m.tile_y * 32
                                        _pasos = max(abs(new_x - m.tile_x), abs(new_y - m.tile_y)) or 1
                                        m.tile_x = new_x
                                        m.tile_y = new_y
                                        m.tile[0], m.tile[1] = new_x, new_y
                                        dst_x, dst_y = new_x * 32, new_y * 32
                                        spd = int((m.move_speed or 50) * 1.25)
                                        m.proximo_paso = ahora + (_pasos * 32.0 / spd)
                                        ses.enviar(MOVE.build(entity_id=m.entity_id,
                                                              cur_x=cur_x, cur_y=cur_y,
                                                              dst_x=dst_x, dst_y=dst_y,
                                                              speed=spd))
                                    continue

                            dist_x = abs(m.tile_x - p.tile_x)
                            dist_y = abs(m.tile_y - p.tile_y)
                            dist = max(dist_x, dist_y)

                            # Los monstruos son PASIVOS: no atacan hasta que
                            # el jugador les pega. Se probo agro por cercania
                            # y esta mal: en el juego real se puede caminar
                            # entre ellos sin que reaccionen.

                            # 1. Monstruo en combate con el jugador
                            if getattr(m, 'en_combate_con', None) == yo:
                                if dist > _cb.RANGO_PERDER_AGRO:
                                    m.en_combate_con = None
                                    log.debug(f"[{addr}] {m.nombre} pierde el "
                                              f"agro a {dist} casillas")
                                    continue

                                r_atk = max(1, getattr(m, 'atk_range', 1))
                                if dist <= r_atk:
                                    # Atacar al jugador si paso el cooldown (2.0s)
                                    if ahora - getattr(m, 'ultimo_ataque', 0) >= _cb.cadencia_monstruo(m):
                                        _prev = getattr(m, 'ultimo_ataque', 0)
                                        m.ultimo_ataque = ahora
                                        if _prev:
                                            log.info(
                                                f"[{addr}] {m.nombre} pega: "
                                                f"pasaron {ahora - _prev:.3f}s "
                                                f"(ciclo configurado "
                                                f"{_cb.cadencia_monstruo(m):.3f}s)")
                                        suyo = _cb.dano_recibido(m.pegar(),
                                                                 defensa_jugador(ses))
                                        import inventario as _iv
                                        bolsa_yo = getattr(ses, 'inventario', None)
                                        if bolsa_yo:
                                            mods_eq = _iv.modificadores_porcentuales_equipo(bolsa_yo)
                                            mult_mit = mods_eq.get('phys_mit_mult', 1.0)
                                            if mult_mit < 1.0:
                                                suyo = max(1, int(round(suyo * mult_mit)))
                                        if ses.personaje and getattr(ses.personaje, 'buffs', None):
                                            for b_data in ses.personaje.buffs.values():
                                                if isinstance(b_data, dict) and b_data.get('fin', 0) > ahora and 'mit' in b_data:
                                                    suyo = max(1, int(round(suyo * (1.0 - b_data['mit'] / 100.0))))
                                        ef_atk = m.proj_ef if m.proj_ef > 0 else 148

                                        # El golpe sale ya y el dano espera a
                                        # que la animacion termine. El campo de
                                        # animacion del 0x000A es su duracion
                                        # en milisegundos: en Celestia un bicho
                                        # con animacion 951 manda su numero a
                                        # los 951 ms y uno con 774 a los 784.
                                        # Antes el dano se descontaba en el
                                        # acto, con el cliente aun levantando
                                        # el arma, y no cuadraba nada.
                                        ses.enviar(_cb.ataque(
                                            m.entity_id, yo,
                                            _cb.anim_de_monstruo(m.nombre)))
                                        if getattr(ses, 'invocacion', None) and not ses.invocacion.get('objetivo'):
                                            if not getattr(m, 'encantado', False):
                                                ses.invocacion['objetivo'] = m
                                        if getattr(ses, 'monstruo_encantado', None) and getattr(ses.monstruo_encantado, 'vivo', False) and not getattr(ses.monstruo_encantado, 'charmed_objetivo', None):
                                            if not getattr(m, 'encantado', False):
                                                ses.monstruo_encantado.charmed_objetivo = m

                                        def _impacto(m=m, suyo=suyo, ef_atk=ef_atk):
                                            # Si el bicho se murio durante su
                                            # propia animacion, el golpe no
                                            # llega. Esto es lo que hacia que
                                            # siguiera bajando vida despues de
                                            # matarlo.
                                            if not getattr(m, 'vivo', False):
                                                return
                                            pj = getattr(ses, 'personaje', None)
                                            if not pj or getattr(ses, 'muerto', False):
                                                return
                                            if getattr(m, 'en_combate_con', None) != yo:
                                                return
                                            pj.hp = max(0, pj.hp - suyo)
                                            ses.enviar_inmediato(
                                                _cb.numero_de_dano(m.entity_id, yo, suyo,
                                                                   ataque=656, efecto=ef_atk),
                                                _cb.numero_flotante(yo, suyo),
                                                # HP ABSOLUTO, no el porcentaje:
                                                # VIDA y KIND_HP son el mismo
                                                # campo, y aqui se mandaba 0..100.
                                                # La barra saltaba a "80" y
                                                # parecia que el golpe quitaba 300.
                                                _cb.atributo(yo, pj.hp, _cb.KIND_HP))
                                            if pj.hp > 0:
                                                return
                                            # Muerte del jugador: el 0x000A con
                                            # tipo 7 y la vida en cero, y se
                                            # espera a que elija en la ventana
                                            # del cliente.
                                            ses.enviar_inmediato(
                                                _cb.ataque(yo, m.entity_id, 0, _cb.TIPO_MUERTE),
                                                _cb.atributo(yo, 0, _cb.KIND_HP))
                                            ses.muerto = True
                                            m.en_combate_con = None
                                            if getattr(ses, 'usuario', None):
                                                cuentas.guardar_progreso(
                                                    ses.usuario, pj.char_id,
                                                    pj.nivel, pj.exp, 0, pj.mp,
                                                    pj.habilidades,
                                                    hp_max=pj.hp_max,
                                                    mp_max=pj.mp_max)
                                            log.info(f"[{addr}] jugador muerto "
                                                     f"por {m.nombre} (IA)")

                                        try:
                                            asyncio.get_event_loop().call_later(
                                                _cb.retraso_golpe_monstruo(m), _impacto)
                                        except Exception:
                                            _impacto()
                                else:
                                    # Fuera de rango: avanzar hacia el jugador solo si NO es estatico (como Lily)
                                    if not getattr(m, 'es_estatico', False):
                                        # No encadenar trayectorias cada tick: el cliente
                                        # aun esta interpolando el paso anterior.
                                        if ahora < getattr(m, 'proximo_paso', 0):
                                            continue
                                        dx = p.tile_x - m.tile_x
                                        dy = p.tile_y - m.tile_y
                                        dist_p = max(abs(dx), abs(dy))
                                        pasos_dar = min(max(1, dist_p - r_atk), 3)
                                        step_x = (1 if dx > 0 else (-1 if dx < 0 else 0)) * pasos_dar
                                        step_y = (1 if dy > 0 else (-1 if dy < 0 else 0)) * pasos_dar
                                        cur_x, cur_y = m.tile_x * 32, m.tile_y * 32
                                        m.tile_x += step_x
                                        m.tile_y += step_y
                                        m.tile[0], m.tile[1] = m.tile_x, m.tile_y
                                        dst_x, dst_y = m.tile_x * 32, m.tile_y * 32
                                        _pasos = max(abs(step_x), abs(step_y)) or 1
                                        spd = m.move_speed or _cb.VELOCIDAD_PASEO
                                        if getattr(m, 'debuffs', None):
                                            for deb in m.debuffs.values():
                                                if deb.get('vel_mov_mod'):
                                                    spd = max(10, spd + deb['vel_mov_mod'])
                                        m.proximo_paso = ahora + (_pasos * 32.0 / spd)
                                        ses.enviar(MOVE.build(entity_id=m.entity_id,
                                                              cur_x=cur_x, cur_y=cur_y,
                                                              dst_x=dst_x, dst_y=dst_y,
                                                              speed=spd))
                            else:
                                # 2. Monstruo libre: pasear, salvo los
                                # estaticos. Las Lily son plantas: no se
                                # mueven ni para pasear ni para perseguir.
                                #
                                # Cada bicho lleva su propio reloj en vez de
                                # una probabilidad por tick. Con la
                                # probabilidad se movian a tirones: un paso,
                                # una pausa larga y otro paso. Ahora, en
                                # cuanto termina de recorrer el tramo
                                # anterior, sale de nuevo tras una pausa
                                # corta, y el paseo se ve continuo.
                                if getattr(m, 'es_estatico', False):
                                    continue
                                if ahora < getattr(m, 'proximo_paso', 0):
                                    continue
                                # El paso es de una a tres casillas por eje:
                                # en Celestia los desplazamientos mas
                                # repetidos son (1,2), (1,1), (1,3), (2,1) y
                                # (3,1).
                                _n = _cb.PASO_PASEO_MAX
                                dx = random.randint(-_n, _n)
                                dy = random.randint(-_n, _n)
                                if dx == 0 and dy == 0:
                                    dx = random.choice((-1, 1))
                                new_x = m.tile_x + dx
                                new_y = m.tile_y + dy
                                _rango = max(m.move_range, _cb.RANGO_PASEO_MIN)
                                if (abs(new_x - m.spawn_x) > _rango
                                        or abs(new_y - m.spawn_y) > _rango):
                                    # Se paso del radio: da media vuelta en
                                    # vez de quedarse parado esperando.
                                    new_x = m.spawn_x + random.randint(-_rango, _rango)
                                    new_y = m.spawn_y + random.randint(-_rango, _rango)
                                # Nunca fuera del mapa: con el bicho cerca
                                # del borde, el paso al azar daba casillas
                                # negativas y el constructor del 0x0005
                                # reventaba con "dst_x=-32 fuera de rango",
                                # lo que tiraba la IA entera del mapa.
                                new_x = max(0, new_x)
                                new_y = max(0, new_y)
                                _pasos = max(abs(new_x - m.tile_x),
                                             abs(new_y - m.tile_y)) or 1
                                m.proximo_paso = (ahora
                                                  + _pasos * _cb.SEGUNDOS_POR_CASILLA
                                                  + random.uniform(_cb.PAUSA_PASEO_MIN,
                                                                   _cb.PAUSA_PASEO_MAX))
                                cur_x, cur_y = m.tile_x * 32, m.tile_y * 32
                                m.tile_x = new_x
                                m.tile_y = new_y
                                m.tile[0], m.tile[1] = new_x, new_y
                                dst_x, dst_y = new_x * 32, new_y * 32
                                ses.enviar(MOVE.build(entity_id=m.entity_id,
                                                      cur_x=cur_x, cur_y=cur_y,
                                                      dst_x=dst_x, dst_y=dst_y,
                                                      speed=m.move_speed or _cb.VELOCIDAD_PASEO))
                        # AL FINAL DE CADA TICK, A LA RED. Sin esto el paseo
                        # se quedaba en el buffer hasta que el cliente mandaba
                        # algo, o sea que los monstruos solo se movian cuando
                        # se movia el jugador. Los golpes si se veian porque
                        # usan enviar_inmediato, que ya volcaba.
                        ses.volcar()
                except Exception:
                    # Estaba en 'pass': si algo fallaba UNA vez la tarea
                    # moria en silencio y todos los monstruos del mapa se
                    # quedaban quietos para siempre, sin dejar rastro en el
                    # log. Ahora se anota y la IA se vuelve a levantar.
                    log.exception(f"[{addr}] la IA de monstruos fallo, "
                                  f"se reinicia")
                    if getattr(ses, 'personaje', None):
                        asyncio.get_event_loop().call_later(
                            1.0, lambda: asyncio.create_task(_ia_monstruos()))

            asyncio.create_task(_ia_monstruos())
            log.info(f"[{addr}] entro al mundo: '{p.nombre}' entidad={p.entity_id} "
                     f"char_id={p.char_id} tile=({p.tile_x},{p.tile_y})")
            log.info(f"[{addr}] (credenciales NO validadas: formato aun sin descifrar)")
            return

        if opcode == 0x0002 and ses.entity_id:
            # El cliente cargo la escena del mapa nuevo y avisa que esta listo
            p = getattr(ses, 'personaje', None)
            if p:
                import login as _lg, clases as _cl, inventario as inv, combate as _cb
                ses.monstruos = _monstruos_de(p.stage)
                ses.enviar(*_lg.poblar(p.stage))
                if getattr(p, 'habilidades', None):
                    ses.enviar(_cl.arbol(p.habilidades, banco=getattr(p, 'banco_habilidades', None)))
                    _ids = [h[0] for h in p.habilidades]
                    _hech = _cl.hechizos_iniciales(_ids)
                    _todos_hech = [n for n, _ in _hech]
                    if getattr(p, 'hechizos_aprendidos', None):
                        _todos_hech = list(set(_todos_hech) | set(p.hechizos_aprendidos))
                    if _todos_hech:
                        ses.enviar(_cl.otorgar_hechizos(p.entity_id, _todos_hech))
                bars, max_pts = _max_sp_info(p)
                ses.sp = getattr(ses, 'sp', None) or max_pts
                b = getattr(ses, 'inventario', None) or getattr(p, 'inventario', None) or {}
                eff_hp_max = _vida_max(p, bolsa=b)
                eff_mp_max = _mana_max(p, bolsa=b)
                p.hp = min(eff_hp_max, max(1, p.hp))
                p.mp = min(eff_mp_max, max(0, p.mp))
                exp_sig = min(0xFFFFFFFF, _cb.exp_para_nivel(p.nivel + 1))
                yo = p.entity_id
                salida = [
                    _cb.atributo(yo, p.hp, _cb.KIND_HP),
                    _cb.atributo(yo, p.mp, _cb.KIND_MP),
                    _cb.atributo(yo, ses.sp, _cb.KIND_SP),
                    struct.pack('<HIB', 0x001D, yo, 4) +
                    struct.pack('<BII', 29, p.nivel, 0) +
                    struct.pack('<BII', 30, min(0xFFFFFFFF, p.exp), 0) +
                    struct.pack('<BII', 31, exp_sig, 0) +
                    struct.pack('<BII', 32, min(0xFFFFFFFF, p.exp), 0),
                    inv.stats(b, p.habilidades,
                              hp=p.hp, hp_max=p.hp_max,
                              mp=p.mp, mp_max=p.mp_max,
                              oro=getattr(ses, 'oro', p.oro), sp=ses.sp, sp_max=bars),
                    *_apariencia(ses)
                ]
                ses.enviar(*salida)
                log.info(f"[{addr}] 0x0002 mapa {p.stage} sincronizado para {p.nombre}")
            return

        # --- combate -----------------------------------------------------
        if opcode == 0x0006 and ses.rol == 'mundo' and cuerpo:
            import combate as _cb
            # Un muerto no pega ni recibe. El cliente sigue repitiendo el
            # ataque con la ventana de muerte abierta, y cada uno hacia que
            # el monstruo contraatacara: por eso seguian saliendo numeros de
            # dano sobre el cadaver.
            if getattr(ses, 'muerto', False):
                return
            d3 = _cb.parsear_ataque(cuerpo)
            if not d3:
                return
            tipo, objetivo = d3
            tx = getattr(d3, 'tx', 0)
            ty = getattr(d3, 'ty', 0)
            yo = ses.entity_id or 1001

            bichos = getattr(ses, 'monstruos', None) or {}
            m = bichos.get(objetivo)
            arma_puesta = ses.inventario.get(3, 0) if ses.inventario else 0

            mag = _cb.datos_magia(tipo) if tipo != _cb.ATAQUE_NORMAL else {}
            es_invocacion = bool(mag.get('es_invocacion'))
            es_terreno = (bool(mag.get('es_terreno')) or (objetivo == 0 and tipo != _cb.ATAQUE_NORMAL)) and not es_invocacion
            es_self_aoe = bool(mag.get('es_self_aoe')) and not es_invocacion
            es_aoe = (es_terreno or es_self_aoe or bool(mag.get('es_aoe'))) and not es_invocacion

            # Comprobacion de alcance
            if es_terreno and ses.personaje:
                _rango_aoe = max(1, mag.get('rango', 12))
                _d = max(abs(tx - ses.personaje.tile_x), abs(ty - ses.personaje.tile_y))
                if _d > _rango_aoe + 2:
                    log.info(f"[{addr}] AOE TERRENO RECHAZADO por alcance: {_d} casillas y el hechizo llega a {_rango_aoe}. "
                             f"jugador ({ses.personaje.tile_x},{ses.personaje.tile_y}) target ({tx},{ty})")
                    return
            elif not es_self_aoe and m is not None and ses.personaje:
                # La invocacion y el aliado encantado fijan el objetivo de inmediato si no es un aliado
                if not getattr(m, 'encantado', False):
                    if getattr(ses, 'invocacion', None):
                        ses.invocacion['objetivo'] = m
                    if getattr(ses, 'monstruo_encantado', None) and getattr(ses.monstruo_encantado, 'vivo', False):
                        ses.monstruo_encantado.charmed_objetivo = m

                # El alcance sale del arma o de la habilidad, no es 1 fijo:
                # con sable es 1 casilla, con lanza 2 y con arco 12.
                if tipo != _cb.ATAQUE_NORMAL:
                    _rango_arma = max(1, mag.get('rango', 1))
                else:
                    _rango_arma = _cb.alcance_arma(arma_puesta)
                _d = max(abs(m.tile_x - ses.personaje.tile_x),
                         abs(m.tile_y - ses.personaje.tile_y))
                if _d > _rango_arma + 1:
                    log.info(f"[{addr}] GOLPE RECHAZADO por alcance: {_d} "
                             f"casillas y el arma llega a {_rango_arma}. "
                             f"jugador ({ses.personaje.tile_x},"
                             f"{ses.personaje.tile_y}) bicho "
                             f"({m.tile_x},{m.tile_y})")
                    return

            # Ya en rango: cadencia y cooldown
            if m is not None and not es_aoe:
                _obj_act = getattr(ses, 'objetivo_actual', None)
                if _obj_act is None and tipo == _cb.ATAQUE_NORMAL:
                    log.info(f"[{addr}] GOLPE RECHAZADO: no hay objetivo "
                             f"fijado (te alejaste del {m.nombre})")
                    return
                if _obj_act != objetivo:
                    ses.objetivo_actual = objetivo
                    ses.ultimo_golpe = 0

            _ahora_atk = time.time()
            if tipo != _cb.ATAQUE_NORMAL:
                _cd = max(0.0, mag.get('cd_ms', 0) / 1000.0)
                _usos = getattr(ses, 'ultimo_uso', None)
                if _usos is None:
                    _usos = {}
                    ses.ultimo_uso = _usos
                _espera = _ahora_atk - _usos.get(tipo, 0)
                if _espera < _cd:
                    log.info(f"[{addr}] HABILIDAD {tipo} RECHAZADA: pidio a "
                             f"los {_espera:.3f}s y su cooldown es {_cd:.3f}s")
                    return
                _usos[tipo] = _ahora_atk
            else:
                _cad = _cb.cadencia_ataque(
                    getattr(ses.personaje, 'buffs', None) if ses.personaje else None,
                    getattr(ses.personaje, 'habilidades', None) if ses.personaje else None,
                    duales=lleva_duales_ses(ses),
                    item_id=arma_puesta)
                _espera = _ahora_atk - getattr(ses, 'ultimo_golpe', 0)
                if _espera < _cad:
                    log.info(f"[{addr}] GOLPE RECHAZADO por cadencia: pidio a "
                             f"los {_espera:.3f}s y el minimo es {_cad:.3f}s")
                    return
                ses.ultimo_golpe = _ahora_atk

            # Si es Invocacion (Summon Skeleton, Mummy, Leech, Azrael, Demon, etc.)
            if es_invocacion:
                if getattr(ses, 'sentado', False):
                    ses.sentado = False
                    ses.enviar(struct.pack('<HIII', 0x000A, yo, 0, 0))

                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para invocacion {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))

                cost_sp = mag.get('cost_sp', 0)
                if cost_sp > 0:
                    if getattr(ses, 'sp', 0) < cost_sp:
                        log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para invocacion {tipo}")
                        return
                    ses.sp -= cost_sp
                    ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                cd_ms = mag.get('cd_ms', 2000)
                cast_time = _cb.calcular_cast_time(
                    mag.get('cast_time', 2000),
                    buffs=getattr(ses.personaje, 'buffs', {}),
                    habilidades=getattr(ses.personaje, 'habilidades', None),
                    es_magia=True
                )
                ef = _cb.efecto_de_ataque(tipo) or mag.get('efecto', 9)

                # Despawnear invocacion anterior si ya tenia una
                if getattr(ses, 'invocacion', None):
                    old_eid = ses.invocacion['entity_id']
                    ses.enviar(_cb.atributo(old_eid, 0, _cb.KIND_HP),
                               _cb.despawn_monstruo(old_eid),
                               struct.pack('<HIBBI', 0x0013, yo, 1, 0x3d, 0))
                    ses.invocacion = None

                npc_t = mag.get('invoca_npc')
                info_inv = _cb.datos_invocacion(npc_t)
                summon_eid = yo + 8000

                # Coordenadas donde se invoca: si el cliente mando tx, ty validas cerca, usarlas; sino al lado del personaje
                if tx > 0 and ty > 0 and ses.personaje and max(abs(tx - ses.personaje.tile_x), abs(ty - ses.personaje.tile_y)) <= 14:
                    stx, sty = tx, ty
                else:
                    stx = (ses.personaje.tile_x + 1) if ses.personaje else tx
                    sty = ses.personaje.tile_y if ses.personaje else ty

                dur_s = mag.get('dur_invoca', 3600)
                ses.invocacion = {
                    'entity_id': summon_eid,
                    'npc_type': npc_t,
                    'nombre': info_inv['nombre'],
                    'sprite': info_inv['sprite'],
                    'hp': info_inv['hp'],
                    'hp_max': info_inv['hp'],
                    'atk': info_inv['atk'],
                    'defensa': info_inv['def'],
                    'matk': info_inv.get('matk', 0),
                    'mdef': info_inv.get('mdef', 0),
                    'level': info_inv.get('level', 1),
                    'accuracy': info_inv.get('accuracy', 50),
                    'agility': info_inv.get('agility', 50),
                    'crit_rate': info_inv.get('crit_rate', 5),
                    'atk_range': info_inv.get('atk_range', 1),
                    'move_speed': info_inv.get('move_speed', 70),
                    'atk_speed': info_inv.get('atk_speed', 70),
                    'skills': info_inv.get('skills', []),
                    'tile_x': stx,
                    'tile_y': sty,
                    'expira': time.time() + dur_s,
                    'objetivo': None,
                    'ultimo_ataque': 0.0,
                    'proximo_paso': 0.0,
                }

                import login as _lg
                spawn_pkg = _lg.spawn_invocacion(summon_eid, npc_t, info_inv['nombre'], (stx, sty), sprite=info_inv['sprite'])
                hp_pkg = _cb.atributo(summon_eid, 100, _cb.KIND_HP)
                # Confirmar cast sobre el suelo (target=0, stx, sty) para que el ataud NO salga sobre la cabeza del jugador
                atk_confirm = _cb.confirmar_cast(0, stx, sty)

                # Paquetes iniciales: confirmacion al suelo, efecto del ataud unicamente en (stx, sty), GCD
                ses.enviar(
                    atk_confirm,
                    _cb.numero_de_dano(yo, 0, 0, ataque=tipo, efecto=ef, cast_time=cast_time, es_magia=True, tile_x=stx, tile_y=sty),
                    _cb.gcd_paquete()
                )

                def _fin_invoca():
                    if not ses.personaje or getattr(ses, 'muerto', False):
                        return
                    pkgs_inv = [
                        _cb.cierre_de_dano(yo, 0, ataque=tipo, efecto=ef, es_magia=True, tile_x=stx, tile_y=sty),
                        struct.pack('<HIBBI', 0x0013, yo, 1, 0x3d, summon_eid),
                        struct.pack('<HIBBII', 0x001D, yo, 1, 0x2a, summon_eid, 0),
                        spawn_pkg,
                        hp_pkg,
                    ]
                    if cd_ms > 0:
                        _sk_ids_copia = _cb.grupo_de(tipo)
                        for sk_id in _sk_ids_copia:
                            pkgs_inv.append(struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms))
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0, lambda: ses.enviar_inmediato(*[
                            struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0) for sk_id in _sk_ids_copia
                        ]))

                    pkgs_inv.extend(_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))
                    ses.enviar_inmediato(*pkgs_inv)

                _ret_inv = max(0.14, min(2.5, cast_time / 1000.0))
                asyncio.get_event_loop().call_later(_ret_inv, _fin_invoca)

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                             ses.personaje.nivel, ses.personaje.exp,
                                             ses.personaje.hp, ses.personaje.mp,
                                             ses.personaje.habilidades,
                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                log.info(f"[{addr}] invocacion {info_inv['nombre']} (npc_type {npc_t}, sprite {info_inv['sprite']}) invocada para jugador {yo} en ({stx},{sty})")
                return

            # Si es AOE (Ground AOE o Self AOE), ejecutarlo directamente
            if es_aoe:
                if getattr(ses, 'sentado', False):
                    ses.sentado = False
                    ses.enviar(struct.pack('<HIII', 0x000A, yo, 0, 0))

                cost_sp = mag.get('cost_sp', 0)
                if cost_sp > 0:
                    if getattr(ses, 'sp', 0) < cost_sp:
                        log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para AOE {tipo}")
                        return
                    ses.sp -= cost_sp
                    ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para AOE {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))

                cd_ms = mag.get('cd_ms', 1000)
                if cd_ms > 0 and ses.personaje:
                    _sk_ids_copia = _cb.grupo_de(tipo)
                    cd_pkgs = [struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms)
                               for sk_id in _sk_ids_copia]
                    ses.enviar(*cd_pkgs, _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0,
                            lambda ids=_sk_ids_copia: ses.enviar_inmediato(*[
                                struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0)
                                for sk_id in ids
                            ]))
                    except Exception:
                        pass

                import skills as _sk_mod
                import inventario as _iv
                is_magic_skill = bool(_sk_mod.skill_de_magia(tipo) in (1, 2, 3, 4))
                ef = _cb.efecto_de_ataque(tipo)
                cast_time = _cb.calcular_cast_time(
                    mag.get('cast_time', 100),
                    buffs=getattr(ses.personaje, 'buffs', {}),
                    habilidades=getattr(ses.personaje, 'habilidades', None),
                    es_magia=is_magic_skill
                )

                if es_self_aoe:
                    target_ent = yo
                    cx = ses.personaje.tile_x if ses.personaje else 0
                    cy = ses.personaje.tile_y if ses.personaje else 0
                    tile_ef_x = 0
                    tile_ef_y = 0
                elif m is not None:
                    target_ent = m.entity_id
                    cx = m.tile_x
                    cy = m.tile_y
                    tile_ef_x = 0
                    tile_ef_y = 0
                else:
                    target_ent = 0
                    cx = tx
                    cy = ty
                    tile_ef_x = tx
                    tile_ef_y = ty

                area = max(1, mag.get('area', 1))
                _ef2 = _cb.efecto_secundario(tipo)

                def _fin_aoe(enviar_cierre=True):
                    if not ses.personaje or getattr(ses, 'muerto', False):
                        return
                    if enviar_cierre:
                        ses.enviar_inmediato(
                            _cb.cierre_de_dano(yo, target_ent, ataque=tipo, efecto=ef,
                                               es_magia=is_magic_skill, tile_x=tile_ef_x, tile_y=tile_ef_y)
                        )

                    blancos = [b for b in bichos.values() if b.vivo and max(abs(b.tile_x - cx), abs(b.tile_y - cy)) <= area]

                    if blancos:
                        habs = ses.personaje.habilidades if ses.personaje else None
                        buffs_activos = getattr(ses.personaje, 'buffs', None)
                        st = _iv.stats(ses.inventario, habs, buffs=buffs_activos)
                        if is_magic_skill:
                            ataque = struct.unpack_from('<I', st, 2 + 44)[0]
                            dano_base = mag.get('dano_base', 0)
                            denom = mag.get('base_denom', 200) or 200
                            mult_spell = (dano_base / float(denom)) if dano_base > 0 else 1.0
                            coef = mag.get('dano_coef', 0)
                            if coef > 0:
                                mult_spell *= (coef / 100.0)
                            dano_var = mag.get('dano_var', 0)
                            var_pct = min(0.15, max(0.02, dano_var / float(denom))) if dano_var > 0 else 0.05
                        else:
                            ataque = struct.unpack_from('<I', st, 2 + 20 + 4)[0]
                            stance = _cb.stance_de(tipo)
                            denom = mag.get('base_denom', 300) or 300
                            mult_spell = 1.0 + (stance / float(denom))
                            var_pct = 0.03

                        extra_crit = 0
                        if buffs_activos:
                            now = time.time()
                            for b_id, b_data in list(buffs_activos.items()):
                                if isinstance(b_data, dict) and b_data.get('fin', 0) > now and 'crit' in b_data:
                                    extra_crit += b_data['crit']
                        crit_prob = min(0.90, (critico_jugador(ses) + extra_crit) / 100.0)

                        for b in blancos:
                            if not b.vivo:
                                continue
                            es_crit = (random.random() < crit_prob)
                            mult_crit = 1.5 if es_crit else 1.0
                            dano = b.recibir(ataque, es_magico=is_magic_skill, mult=mult_spell * mult_crit, var_pct=var_pct)

                            pkg_debuff = []
                            if _ef2 and random.randint(1, 100) <= _ef2.get('prob', 100):
                                b.aplicar_efecto(_ef2)
                                if _ef2.get('magia') and _ef2.get('dur_ms'):
                                    pkg_debuff.append(struct.pack('<HIBBII', 0x001D, b.entity_id, 1, 4, _ef2['magia'], _ef2['dur_ms']))

                            _tipo_num = _cb.TIPO_DANO_CRITICO if es_crit else _cb.TIPO_DANO
                            ses.enviar_inmediato(
                                _cb.atributo(b.entity_id, b.porcentaje),
                                _cb.numero_flotante(b.entity_id, dano, _tipo_num),
                                *pkg_debuff
                            )

                            if not b.vivo:
                                _procesar_muerte_monstruo(ses, b, yo, addr, espera=0.0)
                            else:
                                if b.en_combate_con != yo:
                                    b.en_combate_con = yo

                    ses.enviar_inmediato(*_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))

                    if getattr(ses, 'usuario', None):
                        cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                                 ses.personaje.nivel, ses.personaje.exp,
                                                 ses.personaje.hp, ses.personaje.mp,
                                                 ses.personaje.habilidades,
                                                 hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)

                if cast_time <= 0:
                    ses.enviar(
                        _cb.confirmar_cast(target_ent, cx, cy),
                        _cb.numero_de_dano(yo, target_ent, dano=0, ataque=tipo, efecto=ef,
                                           cast_time=0, es_magia=is_magic_skill,
                                           tile_x=tile_ef_x, tile_y=tile_ef_y),
                        _cb.cierre_de_dano(yo, target_ent, ataque=tipo, efecto=ef,
                                           es_magia=is_magic_skill, tile_x=tile_ef_x, tile_y=tile_ef_y)
                    )
                    _fin_aoe(enviar_cierre=False)
                else:
                    ses.enviar(
                        _cb.confirmar_cast(target_ent, cx, cy),
                        _cb.numero_de_dano(yo, target_ent, dano=0, ataque=tipo, efecto=ef,
                                           cast_time=cast_time, es_magia=is_magic_skill,
                                           tile_x=tile_ef_x, tile_y=tile_ef_y)
                    )
                    ret_aoe = max(0.1, cast_time / 1000.0)
                    try:
                        asyncio.get_event_loop().call_later(ret_aoe, _fin_aoe)
                    except Exception:
                        _fin_aoe()

                log.info(f"[{addr}] AOE {tipo} ({mag.get('nombre')}) ejecutado en ({cx},{cy}) radio={area} cast_time={cast_time}ms")
                return

            # Si se uso una habilidad de ataque sin objetivo fijado y NO es AOE, auto-fijar el monstruo mas cercano
            if m is None and not es_aoe and tipo != _cb.ATAQUE_NORMAL and ses.personaje:
                mag_check = _cb.datos_magia(tipo)
                if mag_check.get('es_ataque'):
                    r_max = max(2, mag_check.get('rango', 1))
                    cands = [b for b in bichos.values() if b.vivo and max(abs(b.tile_x - ses.personaje.tile_x), abs(b.tile_y - ses.personaje.tile_y)) <= r_max]
                    if cands:
                        m = min(cands, key=lambda b: max(abs(b.tile_x - ses.personaje.tile_x), abs(b.tile_y - ses.personaje.tile_y)))
                        objetivo = m.entity_id

            if m is None:
                # Habilidad activa sobre uno mismo (F1, F2, F3, buffs o curaciones)
                if tipo != _cb.ATAQUE_NORMAL or objetivo == yo:
                    mag = _cb.datos_magia(tipo)
                    # Si es una habilidad pasiva, ignorar (no se castea activamente en la barra)
                    if mag.get('es_pasiva'):
                        return
                    # Si es una habilidad de ataque, no se puede autocastear
                    if mag.get('es_ataque'):
                        log.info(f"[{addr}] HABILIDAD {tipo} SIN OBJETIVO: el "
                                 f"cliente pidio '{mag.get('nombre')}' con "
                                 f"objetivo {objetivo}, que no es ningun "
                                 f"monstruo de este mapa, y no hay ninguno a "
                                 f"tiro. No se hace nada.")
                        return

                    # Si estaba sentado, levantarse antes de ejecutar habilidad
                    if getattr(ses, 'sentado', False):
                        ses.sentado = False
                        ses.enviar(struct.pack('<HIII', 0x000A, yo, 0, 0))

                    cost_sp = mag.get('cost_sp', 0)
                    if cost_sp > 0:
                        if getattr(ses, 'sp', 0) < cost_sp:
                            log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para habilidad {tipo}")
                            return
                        ses.sp -= cost_sp
                        ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                    mp_coste = mag.get('mp', 0)
                    if ses.personaje and mp_coste > 0:
                        if ses.personaje.mp < mp_coste:
                            log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para habilidad {tipo}")
                            return
                        ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)

                    ef = _cb.efecto_de_ataque(tipo)
                    cd_ms = mag.get('cd_ms', 2000)
                    dur_ms = mag.get('dur_ms', 0)
                    cast_time = _cb.calcular_cast_time(
                        mag.get('cast_time', 100),
                        buffs=getattr(ses.personaje, 'buffs', {}),
                        habilidades=getattr(ses.personaje, 'habilidades', None),
                        es_magia=True
                    )
                    import clases as _cl
                    import inventario as _iv

                    # 1a. Curacion POR TICS (Injury Cure: 15 HP cada 5 s
                    # durante 11). datos_magia la marcaba como buff y no
                    # curaba nada: solo miraba el HP y no el intervalo.
                    _tic = _cb.cura_por_tics(tipo)
                    if _tic and ses.personaje:
                        def _curar_tic(n=0):
                            if not ses.personaje or getattr(ses, 'muerto', False):
                                return
                            antes = ses.personaje.hp
                            ses.personaje.hp = min(_vida_max(ses.personaje),
                                                   ses.personaje.hp + _tic['hp'])
                            sanado = ses.personaje.hp - antes
                            if sanado > 0:
                                ses.enviar_inmediato(
                                    _cb.numero_flotante(yo, sanado, 1),
                                    _cb.atributo(yo, ses.personaje.hp, _cb.KIND_HP))
                            if n + 1 < _tic['tics']:
                                try:
                                    asyncio.get_event_loop().call_later(
                                        _tic['intervalo'],
                                        lambda: _curar_tic(n + 1))
                                except Exception:
                                    pass
                        _curar_tic()
                        log.info(f"[{addr}] {mag.get('nombre')}: cura {_tic['hp']} "
                                 f"HP x{_tic['tics']} cada {_tic['intervalo']}s")

                    # 2. Habilidad de curacion real (Cure Spell de mago, etc.)
                    if mag.get('es_cura') and ses.personaje:
                        cura = max(10, abs(mag.get('hp', 0)))
                        ses.personaje.hp = min(_vida_max(ses.personaje), ses.personaje.hp + cura)
                        ses.enviar(_cb.efecto_curacion_inicio(yo, yo, cura, efecto=ef), _cb.gcd_paquete())

                        def _fin_cura():
                            if ses.personaje:
                                pkgs_fin = [
                                    _cb.efecto_curacion_fin(yo, yo, efecto=ef),
                                    _cb.atributo(yo, ses.personaje.hp, _cb.KIND_HP),
                                    _cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP),
                                ]
                                if cd_ms > 0:
                                    pkgs_fin.append(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, cd_ms))
                                    asyncio.get_event_loop().call_later(cd_ms / 1000.0, lambda: ses.enviar_inmediato(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, 0)))
                                pkgs_fin.extend(_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))
                                ses.enviar_inmediato(*pkgs_fin)
                                if getattr(ses, 'usuario', None):
                                    cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                                             ses.personaje.nivel, ses.personaje.exp,
                                                             ses.personaje.hp, ses.personaje.mp,
                                                             ses.personaje.habilidades,
                                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                        asyncio.get_event_loop().call_later(max(0.1, cast_time / 1000.0), _fin_cura)
                        log.info(f"[{addr}] habilidad curativa {tipo} curó {cura} HP ({ses.personaje.hp}/{ses.personaje.hp_max})")
                    else:
                        # 2. Buff activo / habilidad sobre si mismo (Ferocious Song, Fighting Shield, Swiftness Song, Charming Blessing, etc.)
                        # Medido en Celestia: el servidor manda de inmediato:
                        # 0x0013 MP -> 0x0006 confirm -> 0x0011 (fase 0x00)
                        # Y tras ~140ms (cast): 0x0011 (fase 0x80) -> 0x001D CD -> 0x0042 stats -> 0x001D duracion -> Skill EXP
                        atk_confirm = _cb.confirmar_cast(yo, ses.personaje.tile_x, ses.personaje.tile_y)
                        ses.enviar(
                            _cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP),
                            atk_confirm,
                            _cb.efecto_magia_self_inicio(yo, ef, tipo, cast_time=cast_time),
                        )

                        # Si es transformacion y ya la tenia activa, re-castear reinstaura su forma humana
                        if mag.get('es_transformacion') and tipo in getattr(ses.personaje, 'buffs', {}):
                            ses.personaje.buffs.pop(tipo, None)
                            ses.enviar(
                                struct.pack('<HIBBII', 0x001D, yo, 1, 4, tipo, 0),
                                _stats_ses(ses)
                            )
                            log.info(f"[{addr}] transformacion {tipo} ({mag.get('nombre')}) cancelada / reinstaurada")
                            return

                        # Si habia otra transformacion activa, limpiarla
                        if mag.get('es_transformacion') and getattr(ses.personaje, 'buffs', None):
                            for prev_bid, prev_bdata in list(ses.personaje.buffs.items()):
                                if prev_bdata.get('es_transform'):
                                    ses.personaje.buffs.pop(prev_bid, None)
                                    ses.enviar(struct.pack('<HIBBII', 0x001D, yo, 1, 4, prev_bid, 0))

                        # Registrar buff en el personaje (duracion, bono de critico, % mitigacion de dano, stats de transformacion)
                        if ses.personaje:
                            if not hasattr(ses.personaje, 'buffs') or ses.personaje.buffs is None:
                                ses.personaje.buffs = {}
                            buff_dur_s = (dur_ms / 1000.0) if dur_ms > 0 else 300.0
                            buff_entry = {
                                'fin': time.time() + buff_dur_s,
                                'mag': mag,
                                'es_transform': mag.get('es_transformacion', False)
                            }
                            if mag.get('crit_rate'):
                                buff_entry['crit'] = mag.get('crit_rate')
                            if mag.get('phys_mit'):
                                buff_entry['mit'] = mag.get('phys_mit')
                            if mag.get('mag_mit'):
                                buff_entry['mag_mit'] = mag.get('mag_mit')
                            if mag.get('def_bonus'):
                                buff_entry['def'] = mag.get('def_bonus')
                            if mag.get('atk_bonus'):
                                buff_entry['atk'] = mag.get('atk_bonus')
                            if mag.get('matk_bonus'):
                                buff_entry['matk'] = mag.get('matk_bonus')
                            if mag.get('mdef_bonus'):
                                buff_entry['mdef'] = mag.get('mdef_bonus')
                            if mag.get('hp_bonus'):
                                buff_entry['hp'] = mag.get('hp_bonus')
                            if mag.get('mp_bonus'):
                                buff_entry['mp'] = mag.get('mp_bonus')
                            if mag.get('cast_redux'):
                                buff_entry['cast_redux'] = mag.get('cast_redux')
                            ses.personaje.buffs[tipo] = buff_entry

                        def _fin_buff():
                            if not ses.personaje or getattr(ses, 'muerto', False):
                                return
                            pkgs_buff = [
                                _cb.efecto_magia_self_fin(yo, ef, tipo),
                            ]
                            if cd_ms > 0:
                                pkgs_buff.append(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, cd_ms))
                                asyncio.get_event_loop().call_later(cd_ms / 1000.0, lambda: ses.enviar_inmediato(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, 0)))

                            pkgs_buff.append(_stats_ses(ses))

                            if dur_ms > 0:
                                pkgs_buff.append(struct.pack('<HIBBII', 0x001D, yo, 1, 4, tipo, dur_ms))
                                def _expirar_buff(sk_id=tipo):
                                    if ses.personaje and getattr(ses.personaje, 'buffs', None):
                                        ses.personaje.buffs.pop(sk_id, None)
                                        ses.enviar_inmediato(
                                            struct.pack('<HIBBII', 0x001D, yo, 1, 4, sk_id, 0),
                                            _stats_ses(ses)
                                        )
                                asyncio.get_event_loop().call_later(dur_ms / 1000.0, _expirar_buff)

                            pkgs_buff.extend(_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))
                            ses.enviar_inmediato(*pkgs_buff)

                        _ret_buff = max(0.14, min(1.0, cast_time / 1000.0))
                        asyncio.get_event_loop().call_later(_ret_buff, _fin_buff)

                        if getattr(ses, 'usuario', None):
                            cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                                     ses.personaje.nivel, ses.personaje.exp,
                                                     ses.personaje.hp, ses.personaje.mp,
                                                     ses.personaje.habilidades,
                                                     hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                        log.info(f"[{addr}] buff {tipo} ({mag.get('nombre')}) ejecutado (efecto {ef}, dur={dur_ms}ms, cd={cd_ms}ms)")
                    return
                log.debug(f"[{addr}] ataque a la entidad {objetivo}: no es un monstruo conocido")
                return

            if not m.vivo:
                return

            mag = _cb.datos_magia(tipo) if tipo != _cb.ATAQUE_NORMAL else {}

            # Si el objetivo es un monstruo encantado (aliado), no se le ataca ni con golpe basico ni magia hostil
            if getattr(m, 'encantado', False):
                if tipo == _cb.ATAQUE_NORMAL or not mag.get('es_encanto'):
                    log.info(f"[{addr}] ataque rechazado: {m.nombre} es un aliado encantado")
                    return

            # Hechizo de encanto (Shining Charm I..V de Earth)
            if tipo != _cb.ATAQUE_NORMAL and mag.get('es_encanto'):
                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para encanto {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))

                cd_ms = mag.get('cd_ms', 1000)
                if cd_ms > 0 and ses.personaje:
                    _sk_ids_copia = _cb.grupo_de(tipo)
                    cd_pkgs = [struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms)
                               for sk_id in _sk_ids_copia]
                    ses.enviar(*cd_pkgs, _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0,
                            lambda ids=_sk_ids_copia: ses.enviar_inmediato(*[
                                struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0)
                                for sk_id in ids
                            ]))
                    except Exception:
                        pass

                dur_s = max(10, mag.get('dur_ms', 600000) // 1000)
                dur_ms = dur_s * 1000
                m.encantado = True
                m.encantado_expira = time.time() + dur_s
                m.en_combate_con = None
                m.charmed_objetivo = None
                ses.monstruo_encantado = m

                if getattr(ses, 'invocacion', None) and ses.invocacion.get('objetivo') == m:
                    ses.invocacion['objetivo'] = None
                for _ob in (ses.monstruos or {}).values():
                    if getattr(_ob, 'charmed_objetivo', None) == m:
                        _ob.charmed_objetivo = None

                ef = mag.get('efecto', 64)
                cast_time = _cb.calcular_cast_time(
                    mag.get('cast_time', 1000),
                    buffs=getattr(ses.personaje, 'buffs', {}),
                    habilidades=getattr(ses.personaje, 'habilidades', None),
                    es_magia=True
                )

                ses.enviar(
                    _cb.confirmar_cast(objetivo, m.tile_x, m.tile_y),
                    _cb.numero_de_dano(yo, objetivo, dano=0, ataque=tipo, efecto=ef, cast_time=cast_time),
                )
                def _fin_encanto():
                    ses.enviar_inmediato(
                        _cb.cierre_de_dano(yo, objetivo, ataque=tipo, efecto=ef),
                        struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, tipo, dur_ms),
                        struct.pack('<HIBBI', 0x0013, m.entity_id, 1, 0x3c, yo),
                        _cb.efecto_aura_objetivo(yo, objetivo, m.tile_x, m.tile_y, tipo),
                    )
                asyncio.get_event_loop().call_later(max(0.14, cast_time / 1000.0), _fin_encanto)
                ses.enviar(*_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                             ses.personaje.nivel, ses.personaje.exp,
                                             ses.personaje.hp, ses.personaje.mp,
                                             ses.personaje.habilidades,
                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                log.info(f"[{addr}] encanto {tipo} ({mag.get('nombre')}) exitoso sobre {m.nombre} (dur={dur_s}s)")
                return

            # Hechizo de control de masas por miedo / panico (Soul Entangle, Crazy Roar, etc.)
            if tipo != _cb.ATAQUE_NORMAL and mag.get('es_panico'):
                cost_sp = mag.get('cost_sp', 0)
                if cost_sp > 0:
                    if getattr(ses, 'sp', 0) < cost_sp:
                        log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para panico {tipo}")
                        return
                    ses.sp -= cost_sp
                    ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para panico {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))

                cd_ms = mag.get('cd_ms', 1000)
                if cd_ms > 0 and ses.personaje:
                    _sk_ids_copia = _cb.grupo_de(tipo)
                    cd_pkgs = [struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms)
                               for sk_id in _sk_ids_copia]
                    ses.enviar(*cd_pkgs, _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0,
                            lambda ids=_sk_ids_copia: ses.enviar_inmediato(*[
                                struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0)
                                for sk_id in ids
                            ]))
                    except Exception:
                        pass

                dur_s = max(2, mag.get('dur_ms', 6000) // 1000)
                dur_ms = dur_s * 1000
                m.panico = True
                m.panico_hasta = time.time() + dur_s
                m.en_combate_con = None
                m.charmed_objetivo = None

                ef = mag.get('efecto', 10)
                cast_time = _cb.calcular_cast_time(
                    mag.get('cast_time', 2000),
                    buffs=getattr(ses.personaje, 'buffs', {}),
                    habilidades=getattr(ses.personaje, 'habilidades', None),
                    es_magia=True
                )

                ses.enviar(
                    _cb.confirmar_cast(objetivo, m.tile_x, m.tile_y),
                    _cb.numero_de_dano(yo, objetivo, dano=0, ataque=tipo, efecto=ef, cast_time=cast_time),
                )
                def _fin_panico():
                    ses.enviar_inmediato(
                        _cb.cierre_de_dano(yo, objetivo, ataque=tipo, efecto=ef),
                        struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, tipo, dur_ms),
                        _cb.efecto_aura_objetivo(yo, objetivo, m.tile_x, m.tile_y, tipo),
                    )
                asyncio.get_event_loop().call_later(max(0.14, cast_time / 1000.0), _fin_panico)
                ses.enviar(*_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                             ses.personaje.nivel, ses.personaje.exp,
                                             ses.personaje.hp, ses.personaje.mp,
                                             ses.personaje.habilidades,
                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                log.info(f"[{addr}] panico {tipo} ({mag.get('nombre')}) exitoso sobre {m.nombre} (dur={dur_s}s)")
                return

            # Hechizo de maldicion / debuff a enemigo (Exhaustion Curse, Weak Curse, Slow Curse, etc.)
            if tipo != _cb.ATAQUE_NORMAL and mag.get('es_debuff'):
                cost_sp = mag.get('cost_sp', 0)
                if cost_sp > 0:
                    if getattr(ses, 'sp', 0) < cost_sp:
                        log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para maldicion {tipo}")
                        return
                    ses.sp -= cost_sp
                    ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para maldicion {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))

                cd_ms = mag.get('cd_ms', 1000)
                if cd_ms > 0 and ses.personaje:
                    _sk_ids_copia = _cb.grupo_de(tipo)
                    cd_pkgs = [struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms)
                               for sk_id in _sk_ids_copia]
                    ses.enviar(*cd_pkgs, _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0,
                            lambda ids=_sk_ids_copia: ses.enviar_inmediato(*[
                                struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0)
                                for sk_id in ids
                            ]))
                    except Exception:
                        pass

                dur_s = max(5, mag.get('dur_ms', 20000) // 1000)
                dur_ms = dur_s * 1000
                if not hasattr(m, 'debuffs') or m.debuffs is None:
                    m.debuffs = {}
                m.debuffs[tipo] = {
                    'fin': time.time() + dur_s,
                    'atk_mod': mag.get('atk_mod', 0),
                    'phys_dmg_pct': mag.get('phys_dmg_pct', 0),
                    'def_mod': mag.get('def_mod', 0),
                    'phys_mit_pct': mag.get('phys_mit_pct', 0),
                    'vel_mov_mod': mag.get('vel_mov_mod', 0),
                }
                if getattr(m, 'en_combate_con', None) is None:
                    m.en_combate_con = yo

                ef = mag.get('efecto', 73)
                import clases as _c
                cast_time = _cb.calcular_cast_time(
                    mag.get('cast_time', 800),
                    buffs=getattr(ses.personaje, 'buffs', {}),
                    habilidades=getattr(ses.personaje, 'habilidades', None),
                    es_magia=True
                )

                ses.enviar(
                    _cb.confirmar_cast(objetivo, m.tile_x, m.tile_y),
                    _cb.numero_de_dano(yo, objetivo, dano=0, ataque=tipo, efecto=ef, cast_time=cast_time),
                )
                def _fin_curse():
                    ses.enviar_inmediato(
                        _cb.cierre_de_dano(yo, objetivo, ataque=tipo, efecto=ef),
                        struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, tipo, dur_ms),
                        _cb.efecto_aura_objetivo(yo, objetivo, m.tile_x, m.tile_y, tipo),
                    )
                asyncio.get_event_loop().call_later(max(0.14, cast_time / 1000.0), _fin_curse)
                ses.enviar(*_otorgar_skill_exp(ses, ses.personaje, yo, magic_id=tipo))

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, ses.personaje.char_id,
                                             ses.personaje.nivel, ses.personaje.exp,
                                             ses.personaje.hp, ses.personaje.mp,
                                             ses.personaje.habilidades,
                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                log.info(f"[{addr}] maldicion {tipo} ({mag.get('nombre')}) exitosa sobre {m.nombre} (dur={dur_s}s)")
                return

            # El dano sale del ataque del jugador mas bonos pasivos menos defensa del bicho
            import inventario as _iv
            import skills as _sk_mod
            habs = ses.personaje.habilidades if ses.personaje else None
            buffs_activos = getattr(ses.personaje, 'buffs', None)
            st = _iv.stats(ses.inventario, habs, buffs=buffs_activos)
            is_magic_skill = bool(tipo != _cb.ATAQUE_NORMAL and (_sk_mod.skill_de_magia(tipo) in (1, 2, 3, 4)))
            if is_magic_skill:
                ataque = struct.unpack_from('<I', st, 2 + 44)[0]
            else:
                ataque = struct.unpack_from('<I', st, 2 + 20 + 4)[0]

            # Si se usa una habilidad activa (ej. Slicing Hit, Basic Beating, etc.)
            dano_extra = 0
            if tipo != _cb.ATAQUE_NORMAL:
                mag = _cb.datos_magia(tipo)
                cost_sp = mag.get('cost_sp', 0)
                if cost_sp > 0:
                    if getattr(ses, 'sp', 0) < cost_sp:
                        log.info(f"[{addr}] SP insuficiente ({getattr(ses, 'sp', 0)}/{cost_sp}) para habilidad {tipo}")
                        return
                    ses.sp -= cost_sp
                    ses.enviar(_cb.atributo(yo, ses.sp, _cb.KIND_SP))

                mp_coste = mag.get('mp', 0)
                if ses.personaje and mp_coste > 0:
                    if ses.personaje.mp < mp_coste:
                        log.info(f"[{addr}] MP insuficiente ({ses.personaje.mp}/{mp_coste}) para habilidad {tipo}")
                        return
                    ses.personaje.mp = max(0, ses.personaje.mp - mp_coste)
                    ses.enviar(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))
                # El Stance power de la habilidad, ponderado por
                # PESO_STANCE (ver combate.py: la medicion dice que se suma
                # tal cual, sin multiplicador).
                dano_extra = int(round(_cb.stance_de(tipo) * _cb.PESO_STANCE))
                atk_magic = tipo
                atk_efecto = _cb.efecto_de_ataque(tipo)
                # Enviar cooldown de TODAS las habilidades (kind=3) igual que el servidor real
                # El servidor real manda kind=3 con cd_ms para cada skill al usar una habilidad
                cd_ms = mag.get('cd_ms', 1000)
                if cd_ms > 0 and ses.personaje:
                    # El cooldown NO va por habilidad de clase (Sword, Enhance,
                    # Grapple...) sino por GRUPO de hechizo: al usar Slicing
                    # Hit I el servidor real manda 601, 612, 623, 634, 645 y
                    # la familia Mangle, que comparten el 群組編號 1201.
                    # Mandarlo con los ids de clase no hacia nada porque esos
                    # ids no estan en la barra.
                    _sk_ids_copia = _cb.grupo_de(tipo)
                    cd_pkgs = [struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, cd_ms)
                               for sk_id in _sk_ids_copia]
                    ses.enviar(*cd_pkgs, _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0,
                            lambda ids=_sk_ids_copia: ses.enviar_inmediato(*[
                                struct.pack('<HIBBII', 0x001D, yo, 1, 3, sk_id, 0)
                                for sk_id in ids
                            ]))
                    except Exception:
                        pass
                elif cd_ms > 0:
                    ses.enviar(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, cd_ms), _cb.gcd_paquete())
                    try:
                        asyncio.get_event_loop().call_later(cd_ms / 1000.0, lambda: ses.enviar_inmediato(struct.pack('<HIBBII', 0x001D, yo, 1, 3, tipo, 0)))
                    except Exception:
                        pass

            else:
                atk_magic, atk_efecto = _cb.ataque_estandar_arma(arma_puesta)

            # Probabilidad de golpe critico (base 5% + bonus de Ferocious Song / buffs)
            extra_crit = 0
            if buffs_activos:
                now = time.time()
                for b_id, b_data in list(buffs_activos.items()):
                    if isinstance(b_data, dict) and b_data.get('fin', 0) > now and 'crit' in b_data:
                        extra_crit += b_data['crit']
            # El Critical del personaje, no un 5 fijo: con Critical 11 la
            # probabilidad es 11%, no 5%.
            crit_prob = min(0.90, (critico_jugador(ses) + extra_crit) / 100.0)
            es_crit = (random.random() < crit_prob)
            mult_spell = 1.0
            var_pct = 0.05
            if is_magic_skill:
                # Daño Magico oficial de AO: (SA - SD) * (平均傷害 / 高權位)
                dano_base = mag.get('dano_base', 0)
                denom = mag.get('base_denom', 200) or 200
                if dano_base > 0:
                    mult_spell = dano_base / float(denom)
                else:
                    mult_spell = 1.0
                dano_var = mag.get('dano_var', 0)
                if dano_var > 0:
                    var_pct = min(0.15, max(0.02, dano_var / float(denom)))
                coef = mag.get('dano_coef', 0)
                if coef > 0:
                    mult_spell *= (coef / 100.0)
            else:
                # Daño Fisico de AO: (R.Atk * Multiplicador) - DEF
                if tipo != _cb.ATAQUE_NORMAL:
                    stance = _cb.stance_de(tipo)
                    denom = mag.get('base_denom', 300) or 300
                    mult_spell = 1.0 + (stance / float(denom))
                else:
                    mult_spell = 1.0
                var_pct = 0.03

            if es_crit:
                mult_spell *= 1.5

            # Modificadores porcentuales del equipo (ej. +30% spell damage de Snow Queen's Cufflink)
            mods_eq = _iv.modificadores_porcentuales_equipo(ses.inventario)
            if is_magic_skill:
                if mods_eq.get('mag_dmg_pct', 0) > 0:
                    mult_spell *= (1.0 + mods_eq['mag_dmg_pct'] / 100.0)
            else:
                if mods_eq.get('phys_dmg_pct', 0) > 0:
                    mult_spell *= (1.0 + mods_eq['phys_dmg_pct'] / 100.0)

            total_atk = ataque
            dano = m.recibir(total_atk, es_magico=is_magic_skill, mult=mult_spell, var_pct=var_pct)
            if tipo != _cb.ATAQUE_NORMAL:
                log.info(f"[{addr}] habilidad {tipo} ({'magica' if is_magic_skill else 'fisica'}): "
                         f"{'Spl Atk' if is_magic_skill else 'R.Atk'} {ataque} * mult {mult_spell:.3f}"
                         f"{' (critico)' if es_crit else ''} -> {dano} de dano "
                         f"al {m.nombre} ({m.hp}/{m.hp_max})")
            # El ataque puede encadenar otro hechizo (轉嫁法術): Slicing Hit
            # sangra al 100%, Poison Hit envenena al 100%, Basic Beating aturde,
            # Tendon Chop ralentiza.
            _ef2 = _cb.efecto_secundario(tipo) if tipo != _cb.ATAQUE_NORMAL else None
            _pkg_debuff_m = []
            if _ef2 and random.random() * 100 < _ef2.get('prob', 0):
                _aplicado = m.aplicar_efecto(_ef2)
                if _aplicado:
                    dur_ms = _ef2.get('dur_ms', 10000)
                    mid = _ef2.get('magia', tipo)
                    _pkg_debuff_m.append(struct.pack('<HIBBII', 0x001D, m.entity_id, 1, 4, mid, dur_ms))
                    _pkg_debuff_m.append(_cb.efecto_aura_objetivo(yo, objetivo, m.tile_x, m.tile_y, mid))
                    def _expirar_debuff_m(eid=m.entity_id, deb_id=mid):
                        if getattr(m, 'efectos_activos', None):
                            m.efectos_activos.pop(deb_id, None)
                        ses.enviar_inmediato(struct.pack('<HIBBII', 0x001D, eid, 1, 4, deb_id, 0))
                    try:
                        asyncio.get_event_loop().call_later(dur_ms / 1000.0, _expirar_debuff_m)
                    except Exception:
                        pass
                    log.info(f"[{addr}] {m.nombre}: {_aplicado} por "
                             f"{_ef2.get('nombre')} (mid={mid}, {dur_ms}ms)")
            # Marcar al monstruo en combate con el jugador
            # Forbidden Curse: absorber HP y MP del daño infligido
            _pkgs_drain = []
            if tipo != _cb.ATAQUE_NORMAL and dano > 0 and ses.personaje:
                _hp_drain = mag.get('drain_hp_pct', 0)
                _mp_drain = mag.get('drain_mp_pct', 0)
                if _hp_drain > 0:
                    _hp_gain = max(1, int(round(dano * (_hp_drain / 100.0))))
                    ses.personaje.hp = min(_vida_max(ses.personaje),
                                          ses.personaje.hp + _hp_gain)
                    _pkgs_drain.append(_cb.atributo(yo, ses.personaje.hp, _cb.KIND_HP))
                    _pkgs_drain.append(_cb.numero_flotante(yo, _hp_gain, 1))
                if _mp_drain > 0:
                    _mp_gain = max(1, int(round(dano * (_mp_drain / 100.0))))
                    ses.personaje.mp = min(_mana_max(ses.personaje),
                                          ses.personaje.mp + _mp_gain)
                    _pkgs_drain.append(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))
            m.en_combate_con = yo
            m.ultimo_ataque = time.time()
            if not getattr(m, 'encantado', False):
                if getattr(ses, 'invocacion', None):
                    ses.invocacion['objetivo'] = m
                if getattr(ses, 'monstruo_encantado', None) and getattr(ses.monstruo_encantado, 'vivo', False):
                    ses.monstruo_encantado.charmed_objetivo = m

            # Acumulacion de SP (303 puntos base + bono de Reserve)
            bars, max_pts = _max_sp_info(ses.personaje)
            res_rank = 1
            if ses.personaje and getattr(ses.personaje, 'habilidades', None):
                for h in ses.personaje.habilidades:
                    if (h[0] if isinstance(h, (list, tuple)) else h) == 15:
                        res_rank = h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else 1
                        break
            sp_gain = 303 + res_rank * 5
            ant_bars = getattr(ses, 'sp', 0) // 1000
            ses.sp = min(max_pts, getattr(ses, 'sp', 0) + sp_gain)
            curr_bars = ses.sp // 1000
            pkgs_sp = [_cb.atributo(yo, ses.sp, _cb.KIND_SP)]
            if curr_bars != ant_bars:
                pkgs_sp.append(_iv.stats(ses.inventario, ses.personaje.habilidades,
                                         hp=ses.personaje.hp, hp_max=ses.personaje.hp_max,
                                         mp=ses.personaje.mp, mp_max=ses.personaje.mp_max,
                                         oro=ses.personaje.oro, buffs=buffs_activos,
                                         sp=ses.sp, sp_max=bars))

            ses.esfuerzo = max(0, getattr(ses, 'esfuerzo', 900) - _cb.COSTE_GOLPE)
            pkgs_sk = _otorgar_skill_exp(ses, ses.personaje, yo, arma_puesta=arma_puesta,
                                         magic_id=tipo if tipo != _cb.ATAQUE_NORMAL else 0)

            # Enviar animacion de ataque 0x000A + confirmacion 0x0006 + dano visual 0x0011 + vida monstruo 0x0013 + SP
            # Orden medido en Celestia (mundo_204956_255129 t=8.001 a 8.175):
            #   0x0006 confirmacion del cast (tipo, objetivo, x, y)
            #   0x0011 fase 0x00, el efecto arranca
            #   ...~170 ms...
            #   0x0011 fase 0x80 (cierre), 0x0013 (vida), 0x000B (dano) y 0x001D (debuff)
            _tipo_golpe, _anim_golpe = _cb.golpe_de_arma(
                arma_puesta, duales=lleva_duales_ses(ses))
            _cierre_skill = None
            cast_time = _cb.calcular_cast_time(
                max(100, mag.get('cast_time', 100)),
                buffs=buffs_activos,
                habilidades=getattr(ses.personaje, 'habilidades', None),
                es_magia=is_magic_skill
            )
            if tipo != _cb.ATAQUE_NORMAL:
                if is_magic_skill:
                    # Hechizo mágico: NUNCA enviar 0x000A (ataque físico de arma).
                    # Solo mandar 0x0006 y 0x0011 con cast_time para que el cliente
                    # reproduzca la animación de casteo de manos y círculo mágico.
                    salida_golpe = [
                        _cb.confirmar_cast(objetivo, m.tile_x, m.tile_y),
                        _cb.numero_de_dano(yo, objetivo, dano, tipo, efecto=atk_efecto,
                                           cast_time=cast_time, es_magia=True),
                    ]
                    _cierre_skill = _cb.cierre_de_dano(yo, objetivo, tipo,
                                                       efecto=atk_efecto, es_magia=True)
                else:
                    # Habilidad física (guerrero): confirmacion + efecto + golpe físico
                    salida_golpe = [
                        _cb.confirmar_cast(objetivo, m.tile_x, m.tile_y),
                        _cb.numero_de_dano(yo, objetivo, dano, tipo, efecto=atk_efecto,
                                           cast_time=cast_time, es_magia=False),
                        _cb.ataque(yo, objetivo, _anim_golpe, _tipo_golpe),
                    ]
                    _cierre_skill = _cb.cierre_de_dano(yo, objetivo, tipo,
                                                       efecto=atk_efecto, es_magia=False)
            else:
                salida_golpe = [
                    _cb.ataque(yo, objetivo, _anim_golpe, _tipo_golpe),
                ]
            ses.enviar(*salida_golpe)
            _tipo_num = _cb.TIPO_DANO_CRITICO if es_crit else _cb.TIPO_DANO
            _duales = lleva_duales_ses(ses)
            if _duales and tipo == _cb.ATAQUE_NORMAL:
                _d2 = m.recibir(total_atk) if m.vivo else 0
                _crit2 = random.random() < crit_prob
                if _crit2:
                    _d2 = int(round(_d2 * 1.5))
                _tipo2 = _cb.TIPO_DANO_CRITICO if _crit2 else _cb.TIPO_DANO
                _pkgs_dano = (*( (_cierre_skill,) if _cierre_skill else () ),
                              _cb.atributo(objetivo, m.porcentaje),
                              _cb.numero_flotante(objetivo, dano, _tipo_num),
                              *_pkg_debuff_m,
                              *_pkgs_drain,
                              *pkgs_sk, *pkgs_sp)
                _pkgs_dano2 = ((_cb.atributo(objetivo, m.porcentaje),
                                _cb.numero_flotante(objetivo, _d2, _tipo2))
                               if _d2 else
                               (_cb.atributo(objetivo, m.porcentaje),))
            else:
                _pkgs_dano = (*( (_cierre_skill,) if _cierre_skill else () ),
                              _cb.atributo(objetivo, m.porcentaje),
                              _cb.numero_flotante(objetivo, dano, _tipo_num),
                              *_pkg_debuff_m,
                              *_pkgs_drain,
                              *pkgs_sk, *pkgs_sp)
                _pkgs_dano2 = None
            _ret = 0.0
            try:
                bucle = asyncio.get_event_loop()
                if tipo != _cb.ATAQUE_NORMAL:
                    _ret = max(0.1, cast_time / 1000.0)
                else:
                    _ret = _cb.retraso_golpe(buffs_activos,
                                             getattr(ses.personaje, 'habilidades', None))
                bucle.call_later(_ret,
                                 lambda p=_pkgs_dano: ses.enviar_inmediato(*p))
                if _pkgs_dano2:
                    bucle.call_later(
                        _ret + _cb.RETRASO_SEGUNDA_MANO,
                        lambda p=_pkgs_dano2: ses.enviar_inmediato(*p))
            except Exception:
                ses.enviar(*_pkgs_dano)
                if _pkgs_dano2:
                    ses.enviar(*_pkgs_dano2)
            # Chain Lightning: rebote a objetivos cercanos
            _chain_jumps = mag.get('chain_jumps', 0) if tipo != _cb.ATAQUE_NORMAL else 0
            if _chain_jumps > 0 and ses.monstruos:
                _sub_spell_id = mag.get('sub_spell', 0)
                _sub_mag = _cb.datos_magia(_sub_spell_id) if _sub_spell_id else {}
                _sub_efecto = _cb.efecto_de_ataque(_sub_spell_id) if _sub_spell_id else 305
                _sub_dano_base = _sub_mag.get('dano_base', 0)
                _sub_denom = _sub_mag.get('base_denom', 200) or 200
                _sub_rango = max(6, _sub_mag.get('rango', 6))
                _crit_prob_chain = crit_prob

                def _hacer_chain_bounce(prev_eid=m.entity_id,
                                        prev_x=m.tile_x, prev_y=m.tile_y):
                    if not ses.personaje or getattr(ses, 'muerto', False):
                        return
                    blancos_usados = {prev_eid}
                    _prev_x, _prev_y = prev_x, prev_y
                    _prev_eid = prev_eid
                    habs = ses.personaje.habilidades if ses.personaje else None
                    buffs_act = getattr(ses.personaje, 'buffs', None)
                    st = _iv.stats(ses.inventario, habs, buffs=buffs_act)
                    ataque_j = struct.unpack_from('<I', st, 2 + 44)[0]
                    _sub_mult = ((_sub_dano_base / float(_sub_denom))
                                 if _sub_dano_base > 0 else 1.0)
                    for _salto in range(_chain_jumps):
                        mejor = None
                        mejor_dist = 999
                        for mb in (ses.monstruos or {}).values():
                            if mb.entity_id in blancos_usados or not mb.vivo:
                                continue
                            dist = max(abs(mb.tile_x - _prev_x),
                                       abs(mb.tile_y - _prev_y))
                            if dist <= _sub_rango and dist < mejor_dist:
                                mejor = mb
                                mejor_dist = dist
                        if mejor is None:
                            break
                        blancos_usados.add(mejor.entity_id)
                        _crit_j = random.random() < _crit_prob_chain
                        _mult_j = 1.5 if _crit_j else 1.0
                        dano_j = mejor.recibir(ataque_j, es_magico=True,
                                               mult=_sub_mult * _mult_j,
                                               var_pct=0.05)
                        _tipo_j = (_cb.TIPO_DANO_CRITICO if _crit_j
                                   else _cb.TIPO_DANO)
                        ses.enviar_inmediato(
                            _cb.numero_de_dano(
                                _prev_eid, mejor.entity_id, dano_j,
                                _sub_spell_id or tipo, efecto=_sub_efecto,
                                cast_time=0, es_magia=True),
                            _cb.cierre_de_dano(
                                _prev_eid, mejor.entity_id,
                                ataque=_sub_spell_id or tipo,
                                efecto=_sub_efecto, es_magia=True),
                            _cb.atributo(mejor.entity_id, mejor.porcentaje),
                            _cb.numero_flotante(mejor.entity_id, dano_j,
                                                _tipo_j),
                        )
                        if not mejor.vivo:
                            _procesar_muerte_monstruo(ses, mejor, yo, addr,
                                                      espera=0.0)
                        else:
                            if mejor.en_combate_con != yo:
                                mejor.en_combate_con = yo
                                mejor.ultimo_ataque = 0
                        _prev_eid = mejor.entity_id
                        _prev_x = mejor.tile_x
                        _prev_y = mejor.tile_y
                    log.info(f"[{addr}] Chain Lightning: "
                             f"{len(blancos_usados) - 1} rebotes")

                try:
                    _chain_delay = _ret + 0.3
                    asyncio.get_event_loop().call_later(
                        _chain_delay, _hacer_chain_bounce)
                except Exception:
                    _hacer_chain_bounce()
            if m.vivo:
                # El monstruo no contraataca desde aqui. Solo se lo marca en
                # combate y la IA le da el turno cuando le toca segun su
                # cadencia. Antes habia DOS caminos que le hacian pegar -- este
                # y la IA -- y cuando coincidian soltaba dos golpes casi al
                # mismo tiempo, que es lo que se veia con las Lilys.
                if m.en_combate_con != yo:
                    m.en_combate_con = yo
                    # Que conteste en el tick siguiente, no dentro de un
                    # ciclo entero. El golpe sale ya y el dano llega cuando
                    # termina la animacion, asi que no pega instantaneo: lo
                    # que se quitaba era la espera muerta de antes.
                    m.ultimo_ataque = 0
                log.debug(f"[{addr}] pego {dano} al {m.nombre} "
                          f"({m.porcentaje}%), contraataque procesado")
                return


            # --- Monstruo Muerto: Avisar muerte, Despawn con animacion, Respawn, EXP y Botin ---
            _procesar_muerte_monstruo(ses, m, yo, addr, espera=_ret)
            return

        # --- el cliente pide el mapa nuevo -------------------------------
        # Tras un 0x000C el cliente contesta con un 0x0009 vacio y espera la
        # secuencia de entrada otra vez, ya con la ficha en el mapa nuevo.
        if opcode == 0x0009 and ses.rol == 'mundo' and ses.personaje:
            import inventario as _iv2
            import clases as _cl2
            import combate as _cb2
            import login as _lg2
            p = ses.personaje
            ses.monstruos = _monstruos_de(p.stage)
            # Cargar la secuencia completa oficial del nuevo mapa (aparicion, capas, barra, stats, spawns y atributos)
            for sub in _lg2.secuencia(p):
                ses.enviar(sub)
            ses.enviar(_stats_ses(ses))
            if p.habilidades:
                _ids = [h[0] for h in p.habilidades]
                # OJO: el arbol lleva nivel y experiencia de cada
                # habilidad, asi que hay que pasarle p.habilidades entero.
                # Pasando solo los ids, arbol() pone nivel 1 y exp 0 y el
                # panel salia reseteado a 0.00% despues de cada cambio de
                # mapa o de revivir.
                ses.enviar(_cl2.arbol(p.habilidades))
                _hech = _cl2.hechizos_iniciales(_ids)
                _todos_hech = [n for n, _ in _hech]
                if getattr(p, 'hechizos_aprendidos', None):
                    _todos_hech = list(set(_todos_hech) | set(p.hechizos_aprendidos))
                if _todos_hech:
                    ses.enviar(_cl2.otorgar_hechizos(p.entity_id, _todos_hech))
            if getattr(ses, 'invocacion', None):
                inv = ses.invocacion
                inv['tile_x'] = p.tile_x + 1
                inv['tile_y'] = p.tile_y
                inv['objetivo'] = None
                ses.enviar(
                    struct.pack('<HIBBI', 0x0013, p.entity_id, 1, 0x3d, inv['entity_id']),
                    struct.pack('<HIBBII', 0x001D, p.entity_id, 1, 0x2a, inv['entity_id'], 0),
                    _lg2.spawn_invocacion(inv['entity_id'], inv['npc_type'], inv['nombre'], (inv['tile_x'], inv['tile_y']), sprite=inv['sprite']),
                    _cb2.atributo(inv['entity_id'], 100, _cb2.KIND_HP),
                    struct.pack('<HIBBI', 0x0013, inv['entity_id'], 1, 0x3c, p.entity_id)
                )
            log.info(f"[{addr}] mapa cargado exitosamente: stage {p.stage} "
                     f"tile ({p.tile_x},{p.tile_y})")
            return

        # --- comprar en una tienda ---------------------------------------
        # La ventana la abre el cliente solo; aqui solo se atiende la compra.
        # --- compra en tienda NPC ---------------------------------------
        # Medido en Celestia al comprar diez pociones rojas y diez azules de
        # una sola vez:
        #     02000000 | 42000000 0a000000 | 43000000 0a000000
        # o sea [u32 n] y luego n veces [u32 item_id][u32 cantidad]. Antes se
        # leia UN solo item por mensaje, por eso no se podia comprar mas de
        # una cosa a la vez ni llevarse varias unidades.
        if opcode == 0x0027 and ses.rol == 'mundo' and cuerpo and len(cuerpo) >= 4:
            import clases as _c
            import inventario as _iv
            if getattr(ses, 'inventario', None) is None:
                return
            n_items = struct.unpack_from('<I', cuerpo, 0)[0]
            pedido = []
            off = 4
            for _ in range(min(n_items, 64)):
                if off + 8 > len(cuerpo):
                    break
                item_id, cant = struct.unpack_from('<II', cuerpo, off)
                off += 8
                if item_id and cant:
                    pedido.append((item_id, min(int(cant), 9999)))
            if not pedido:
                return

            total = sum(_precio_compra(i) * c for i, c in pedido)
            if getattr(ses, 'oro', 0) < total:
                log.warning(f"[{addr}] compra rechazada: cuesta {total} y hay "
                            f"{getattr(ses, 'oro', 0)}")
                return
            ses.oro -= total
            if ses.personaje:
                ses.personaje.oro = ses.oro
            cid = ses.personaje.char_id if ses.personaje else 4980

            # El cartel del oro va primero y luego uno por item, igual que en
            # la captura: "680Gold" y despues cada nombre.
            tocadas = []
            avisos = []
            for item_id, cant in pedido:
                _r = _meter(ses, item_id, cant)
                if _r is None:
                    log.warning(f"[{addr}] compra: no entra {item_id} x{cant}, "
                                f"la mochila esta llena")
                    continue
                tocadas.append(_r)
                avisos.append(_c.aviso(_nombre_item(item_id), tipo=0,
                                       msg_id=_c.MSG_ITEM))
            ses.enviar(*_refrescar(ses, tocadas, con_oro=True),
                       _c.aviso(f'{total} Gold', tipo=0, msg_id=_c.MSG_PAGO),
                       *avisos)
            _guardar_bolsa(ses, cid)
            if getattr(ses, 'usuario', None):
                cuentas.guardar_oro(ses.usuario, cid, ses.oro)
            log.info(f"[{addr}] compra: {pedido} por {total}; "
                     f"quedan {ses.oro} de oro")
            return

        # --- venta a tienda NPC ------------------------------------------
        # Medido al vender 5 de una pila y 6 de otra:
        #     02000000 | 6b480300 2e23b26a 05000000 | 6c480300 2e23b26a 06000000
        # o sea [u32 n] y luego n veces [u32 instancia][u32 sello][u32 cant].
        # Los OCHO primeros bytes son el id de instancia del item, no el
        # numero de casilla: leerlos como casilla no casaba nunca, no se
        # sacaba nada del inventario y la venta pagaba 0.
        if opcode == 0x0028 and ses.rol == 'mundo' and cuerpo and ses.personaje:
            import clases as _c
            import inventario as _iv
            bolsa = getattr(ses, 'inventario', {})
            cid = ses.personaje.char_id
            if len(cuerpo) < 4:
                return
            n_items = struct.unpack_from('<I', cuerpo, 0)[0]
            oro_ganado = 0
            tocadas = []
            off = 4
            for _ in range(min(n_items, 64)):
                if off + 12 > len(cuerpo):
                    break
                inst = cuerpo[off:off + 8]
                cant = struct.unpack_from('<I', cuerpo, off + 8)[0]
                off += 12
                ranura = _iv.ranura_de_instancia(_instancias(ses), inst,
                                                 bolsa, cid)
                if ranura is None or _iv.es_equipo(ranura):
                    log.warning(f"[{addr}] venta: instancia {inst.hex()} "
                                f"no esta en la mochila")
                    continue
                it_id = bolsa[ranura]
                vendidas = _sacar(ses, ranura, cant)
                if not vendidas:
                    continue
                ganancia = _precio_venta(it_id) * vendidas
                oro_ganado += ganancia
                tocadas.append(ranura)
                log.info(f"[{addr}] vendio {it_id} x{vendidas} de la casilla "
                         f"{ranura} por {ganancia} de oro")
            if not oro_ganado:
                return
            ses.oro = getattr(ses, 'oro', 0) + oro_ganado
            ses.personaje.oro = ses.oro
            ses.enviar(*_refrescar(ses, tocadas, con_oro=True),
                       _c.aviso(f"{oro_ganado} Gold", tipo=0, msg_id=_c.MSG_ITEM))
            _guardar_bolsa(ses, cid)
            if getattr(ses, 'usuario', None):
                cuentas.guardar_oro(ses.usuario, cid, ses.oro)
            return

        # --- separar un monton en dos -------------------------------------
        # Medido al sacar una pocion de una pila de seis:
        #     0b | 2b00 | 2900 | 01000000
        # o sea [u8 contenedor][u16 casilla destino][u16 casilla origen]
        # [u32 cantidad]. La pila nueva estrena id de instancia: en la
        # captura la de origen sigue con 215293 y la nueva sale con 215300.
        if opcode == 0x002F and ses.rol == 'mundo' and ses.personaje and len(cuerpo) >= 9:
            import inventario as _iv
            # El primer byte es el CONTENEDOR, y el mismo mensaje sirve para
            # cosas distintas:
            #   11 = la mochila, y entonces esto parte un monton en dos
            #   10 = el panel de hechizos del mago: equipar una rama y
            #        descargar otra. Medido: el cliente manda
            #        0a 0600 0000 03000000 y el servidor contesta con el
            #        aviso 424 ("Chaos" equipado), el 423 ("Meditate"
            #        descargado), los stats, el arbol de habilidades y un
            #        0x001D codigo 9 por cada hechizo nuevo, con su aviso
            #        425. Eso todavia no esta implementado aqui.
            # No mirabamos este byte, asi que un cambio de hechizo entraba
            # por el camino de partir pilas del inventario.
            _contenedor = cuerpo[0]
            if _contenedor == 10:
                # Cambio de rama de habilidad (Skill Angel). Medido: [u8 10][u32 la que se
                # descarga][u32 la que se equipa].
                import clases as _cl2
                import skills as _sk
                _fuera, _dentro = struct.unpack_from('<II', cuerpo, 1)
                _p = ses.personaje
                _habs = list(_p.habilidades or [])
                _pos = next((k for k, h in enumerate(_habs) if h[0] == _fuera), None)
                if _pos is None:
                    log.warning(f"[{addr}] cambio de rama: no se lleva la "
                                f"{_fuera} ({_sk.nombre_rama(_fuera)})")
                    return

                # Guardar el progreso de la rama que sale en el banco de habilidades
                if not hasattr(_p, 'banco_habilidades') or _p.banco_habilidades is None:
                    _p.banco_habilidades = {}
                _p.banco_habilidades[_fuera] = [_habs[_pos][1], _habs[_pos][2]]

                # Recuperar progreso previo de la rama que entra si ya la habia entrenado
                _nv_rec, _exp_rec = _p.banco_habilidades.get(_dentro, (1, 0))
                _habs[_pos] = (_dentro, _nv_rec, _exp_rec)
                _p.habilidades = _habs
                _p.class_id = _sk.calcular_class_id([h[0] for h in _p.habilidades])

                # El orden es el del servidor real: primero aviso de la que entra,
                # luego la que sale, stats, arbol, y 0x001D + aviso por cada hechizo nuevo.
                _salida = [
                    _cl2.aviso(_sk.nombre_rama(_dentro), tipo=7, msg_id=424),
                    _cl2.aviso(_sk.nombre_rama(_fuera), tipo=7, msg_id=423),
                    _stats_ses(ses),
                    _cl2.arbol(_p.habilidades, banco=_p.banco_habilidades),
                ]
                _nuevos = _sk.hechizos_de_rama(_dentro)
                if _nuevos:
                    for _nid, _nom in _nuevos:
                        _salida.append(struct.pack('<HIB', 0x001D, _p.entity_id, 1) + struct.pack('<BII', _cl2.KIND_HECHIZO, _nid, 1))
                        _salida.append(_cl2.aviso(_nom, tipo=7, msg_id=_cl2.MSG_HECHIZO))

                ses.enviar(*_salida)
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_habilidades(ses.usuario, _p.char_id, _p.habilidades)
                    cuentas.guardar_clase(ses.usuario, _p.char_id, _p.class_id)
                    cuentas.guardar_banco_habilidades(ses.usuario, _p.char_id, _p.banco_habilidades)
                log.info(f"[{addr}] cambio de rama: fuera "
                         f"{_sk.nombre_rama(_fuera)}, dentro "
                         f"{_sk.nombre_rama(_dentro)} (Lv {_nv_rec}) "
                         f"-> clase={_p.class_id} ({len(_nuevos)} hechizos iniciales)")
                return
            if _contenedor != 11:
                log.info(f"[{addr}] 0x002F con contenedor {_contenedor}: no es "
                         f"la mochila ni el panel de hechizos, se ignora "
                         f"(cuerpo {cuerpo.hex()})")
                return
            destino, origen = struct.unpack_from('<HH', cuerpo, 1)
            cuantas = struct.unpack_from('<I', cuerpo, 5)[0]
            bolsa = getattr(ses, 'inventario', {})
            if origen not in bolsa or destino in bolsa or cuantas < 1:
                log.warning(f"[{addr}] separar invalido: {origen} -> {destino} "
                            f"x{cuantas}")
                return
            hay = _cant_de(ses, origen)
            if cuantas >= hay:
                log.warning(f"[{addr}] separar: piden {cuantas} y hay {hay}")
                return
            item_id = bolsa[origen]
            _cantidades(ses)[origen] = hay - cuantas
            bolsa[destino] = item_id
            _instancias(ses)[destino] = _iv.instancia_nueva()
            if cuantas > 1:
                _cantidades(ses)[destino] = cuantas
            cid = ses.personaje.char_id
            ses.enviar(*_refrescar(ses, [origen, destino]))
            _guardar_bolsa(ses, cid)
            log.info(f"[{addr}] separadas {cuantas} de {item_id}: casilla "
                     f"{origen} ({hay} -> {hay - cuantas}) y casilla {destino}")
            return

        # --- destruir un monton entero (papelera) ------------------------
        # Medido: c2s 0x0013 = [u16 casilla][u32 item_id], y el servidor
        # contesta con el 0x001B corto que deja la casilla vacia. Nuestro
        # codigo escuchaba el 0x004C, que el cliente no manda nunca.
        if opcode == 0x0013 and ses.rol == 'mundo' and ses.personaje and len(cuerpo) >= 6:
            import inventario as _iv
            ranura, item_id = struct.unpack_from('<HI', cuerpo, 0)
            bolsa = getattr(ses, 'inventario', {})
            if ranura not in bolsa or int(bolsa[ranura]) != int(item_id):
                log.warning(f"[{addr}] destruir: la casilla {ranura} no tiene "
                            f"el item {item_id}")
                return
            cuantas = _cant_de(ses, ranura)
            _sacar(ses, ranura, cuantas)
            cid = ses.personaje.char_id
            ses.enviar(_iv.vaciar_ranura(ses.personaje.entity_id, ranura))
            _guardar_bolsa(ses, cid)
            log.info(f"[{addr}] destruido: item {item_id} x{cuantas} de la "
                     f"casilla {ranura}")
            return

        # --- Descartar / Destruir item del inventario (papelera) ---------
        if opcode == 0x004C and ses.rol == 'mundo' and ses.personaje and cuerpo:
            import inventario as _iv
            import clases as _c
            slot = cuerpo[0]
            bolsa = getattr(ses, 'inventario', {})
            cid = ses.personaje.char_id
            if slot in bolsa:
                item_del = bolsa[slot]
                del bolsa[slot]
                nom_it = _nombre_item(item_del)
                ses.enviar(_iv.completo(cid, _con_oro(ses), _dueno(ses)),
                           _c.aviso(f"Destroyed {nom_it}", tipo=0, msg_id=_c.MSG_ITEM))
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] item destruido en ranura {slot}: {item_del} ({nom_it})")
            return

        # --- Mover / Intercambiar item entre ranuras (drag & drop) -------
        if opcode == 0x0130 and ses.rol == 'mundo' and ses.personaje and cuerpo:
            import inventario as _iv
            if len(cuerpo) >= 2:
                s1, s2 = cuerpo[0], cuerpo[1]
                bolsa = getattr(ses, 'inventario', {})
                cid = ses.personaje.char_id
                it1 = bolsa.pop(s1, None)
                it2 = bolsa.pop(s2, None)
                if it1 is not None:
                    bolsa[s2] = it1
                if it2 is not None:
                    bolsa[s1] = it2
                ses.enviar(_iv.completo(cid, _con_oro(ses), _dueno(ses)))
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] intercambio ranuras inventario: {s1} <-> {s2}")
            return

        # --- eleccion de clase -----------------------------------------
        # La ventana la abre el cliente solo; lo unico que llega es esto.
        if opcode == 0x003A and ses.rol == 'mundo' and cuerpo:
            import clases
            ids = clases.parsear_eleccion(cuerpo)
            if not ids:
                return
            # La clase se elige UNA vez. Sin esto se le puede volver a hablar
            # al NPC y cambiarla cuantas veces se quiera.
            if ses.personaje and ses.personaje.habilidades:
                actual = ', '.join(clases.nombre(h[0])
                                   for h in ses.personaje.habilidades)
                log.warning(f"[{addr}] ya tiene clase ({actual}); se ignora el "
                            f"intento de cambiarla")
                return
            salida = []
            for sid in ids:
                salida.append(clases.aviso(clases.nombre(sid)))
            # El arbol completo. Sin el, el panel de habilidades del cliente
            # sale lleno de interrogantes: no conoce las otras treinta.
            salida.append(clases.arbol(ids))
            # Los tres hechizos de nivel 1 del arma, que son los que el
            # cliente pone en F1..F3. En la captura llegan justo despues del
            # arbol, tres 0x000D seguidos con id de mensaje 425.
            hechizos = clases.hechizos_iniciales(ids)
            for _, nom in hechizos:
                salida.append(clases.aviso(nom, tipo=7,
                                           msg_id=clases.MSG_HECHIZO))
            # El 0x000D de arriba solo escribe "Learn X" en el chat. Los
            # iconos no salen hasta que llega este 0x001D.
            if hechizos and ses.personaje:
                salida.append(clases.otorgar_hechizos(
                    ses.personaje.entity_id, [n for n, _ in hechizos]))

            # Entregar lo que da la clase y anotar el class_id. Ambas cosas
            # estan medidas del servidor real AngelWar, no deducidas.
            import inventario as _iv
            regalo = clases.regalo(ids)
            cid = ses.personaje.char_id if ses.personaje else 4980
            if regalo and getattr(ses, 'inventario', None) is not None:
                for ranura, item_id in regalo:
                    ses.inventario[int(ranura)] = int(item_id)
                items_vistos = set()
                for ranura, item_id in regalo:
                    if item_id not in items_vistos:
                        items_vistos.add(item_id)
                        salida.append(clases.aviso(_nombre_item(item_id), tipo=0, msg_id=clases.MSG_ITEM))
                salida.append(_iv.completo(cid, _con_oro(ses), _dueno(ses)))

            # Actualizar stats para Swordsman: Max HP = 304, MP = 154
            if ses.personaje:
                if 9 in ids:  # Swordsman
                    ses.personaje.hp_max = 304
                    ses.personaje.hp = 304
                bars, max_pts = _max_sp_info(ses.personaje)
                ses.sp = max_pts
                salida.append(_iv.stats(
                    ses.inventario, [(sid, 1, 0) for sid in ids],
                    hp=ses.personaje.hp, hp_max=ses.personaje.hp_max,
                    mp=ses.personaje.mp, mp_max=ses.personaje.mp_max,
                    oro=ses.personaje.oro,
                    sp=ses.sp, sp_max=bars
                ))
                import combate as _cb
                salida.append(_cb.atributo(ses.personaje.entity_id, ses.sp, _cb.KIND_SP))

            ses.enviar(*salida)

            if ses.personaje:
                ses.personaje.habilidades = [(sid, 1, 0) for sid in ids]
                if hechizos:
                    ses.personaje.barra = [n for n, _ in hechizos]
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_habilidades(
                        ses.usuario, ses.personaje.char_id,
                        ses.personaje.habilidades)
                    cuentas.guardar_oro(ses.usuario, cid, ses.personaje.oro)
                    cuentas.guardar_inventario(ses.usuario, cid, ses.inventario,
                                   _cantidades(ses))
                    cuentas.guardar_barra(ses.usuario, cid, ses.personaje.barra)
                    cuentas.guardar_progreso(
                        ses.usuario, cid, ses.personaje.nivel, ses.personaje.exp,
                        ses.personaje.hp, ses.personaje.mp, ses.personaje.habilidades,
                        ses.personaje.hp_max, ses.personaje.mp_max)

            log.info(f"[{addr}] CLASE ELEGIDA: "
                     + ', '.join(f'{clases.nombre(i)}({i})' for i in ids)
                     + (f" | hechizos: {', '.join(n for _, n in hechizos)}"
                        if hechizos
                        else " | SIN hechizos de nivel 1 para esa rama"))

            _cid = clases.class_id(ids[0])
            if _cid is not None and ses.personaje and getattr(ses, 'usuario', None):
                cuentas.guardar_clase(ses.usuario, ses.personaje.char_id, _cid)
                log.info(f"[{addr}] class_id {_cid} guardado")
            return

        if opcode == 0x0044 and ses.rol == 'mundo' and len(cuerpo) >= 7:
            # Asignacion de hotkey en la barra (F1..F8, 1..8)
            slot = cuerpo[1]
            mid = struct.unpack_from('<I', cuerpo, 3)[0]
            if ses.personaje:
                while len(ses.personaje.barra) <= slot:
                    ses.personaje.barra.append(0)
                ses.personaje.barra[slot] = mid
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_barra(ses.usuario, ses.personaje.char_id, ses.personaje.barra)
            log.info(f"[{addr}] barra slot {slot} asignada a magic/item {mid}")
            return

        # --- equipar y desequipar --------------------------------------
        # 0x0012 del cliente es MOVER UN ITEM, no hablar con un NPC: eso se
        # confundio al principio porque el cuerpo "02 00 14 00" aparecia
        # despues de hacer clic cerca de un NPC. Con marca de tiempo quedo
        # claro: lo que contesta el servidor es el contenido del contenedor
        # (0x001B) y los stats recalculados (0x0042), no un dialogo.
        if opcode == 0x0012 and ses.rol == 'mundo' and len(cuerpo) >= 4:
            import inventario as inv
            org, dst = struct.unpack_from('<HH', cuerpo, 0)
            bolsa = getattr(ses, 'inventario', None)
            if bolsa is None:
                return
            if org not in bolsa:
                log.warning(f"[{addr}] mover {org} -> {dst}: la ranura {org} esta vacia")
                return
            it_org = bolsa[org]
            if not inv.es_ranura_valida(it_org, dst):
                log.warning(f"[{addr}] mover {org} -> {dst}: ranura no valida para item {it_org}")
                ses.enviar(*_refrescar(ses, [org]))
                return
            cid = ses.personaje.char_id if ses.personaje else 4980
            if dst in bolsa:
                it_dst = bolsa[dst]
                if not inv.es_ranura_valida(it_dst, org):
                    log.warning(f"[{addr}] swap {org} <-> {dst}: ranura {org} no valida para item {it_dst}")
                    ses.enviar(*_refrescar(ses, [org, dst]))
                    return
                # Intercambio (swap) entre ranuras ocupadas
                bolsa[org] = it_dst
                bolsa[dst] = it_org
                _c_org = _cant_de(ses, org)
                _c_dst = _cant_de(ses, dst)
                _cantidades(ses)[org] = _c_dst
                _cantidades(ses)[dst] = _c_org
                _mover_inst(ses, org, 0xFFFF)
                _mover_inst(ses, dst, org)
                _mover_inst(ses, 0xFFFF, dst)
                # Las dos casillas en UN solo mensaje, con el estado de
                # puesto de cada una, que es lo que hace el servidor real.
                salida = [inv.acuse_movimiento(org),
                          inv.actualizar_ranuras(cid, [
                    (dst, it_org, _c_org, _inst(ses, dst)),
                    (org, it_dst, _c_dst, _inst(ses, org)),
                ], _dueno(ses))]
                if inv.es_equipo(org) or inv.es_equipo(dst):
                    if ses.personaje:
                        import combate as _cb
                        _max_h = _vida_max(ses.personaje, bolsa=bolsa)
                        if ses.personaje.hp > _max_h:
                            ses.personaje.hp = _max_h
                        _max_m = _mana_max(ses.personaje, bolsa=bolsa)
                        if ses.personaje.mp > _max_m:
                            ses.personaje.mp = _max_m
                        salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.hp, _cb.KIND_HP))
                        salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.mp, _cb.KIND_MP))
                    salida.append(_stats_ses(ses))
                    salida.extend(_apariencia(ses))
                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, ses.personaje.char_id, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] swap ranuras {org} ({it_org}) <-> {dst} ({it_dst})")
                return

            it = bolsa.pop(org)
            bolsa[dst] = it
            _mover_inst(ses, org, dst)
            salida = [inv.acuse_movimiento(org)]
            salida.extend(_refrescar(ses, [org, dst]))
            if inv.es_equipo(org) or inv.es_equipo(dst):
                if ses.personaje:
                    import combate as _cb
                    _max_h = _vida_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.hp > _max_h:
                        ses.personaje.hp = _max_h
                    _max_m = _mana_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.mp > _max_m:
                        ses.personaje.mp = _max_m
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.hp, _cb.KIND_HP))
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.mp, _cb.KIND_MP))
                salida.append(_stats_ses(ses))
                salida.extend(_apariencia(ses))
            # Gestion de mascota en ranura 9
            if dst == 9:
                sp = inv.sprite_de_mascota(it)
                pet_eid = (ses.personaje.entity_id if ses.personaje else 1001) + 5000
                ses.pet_entity_id = pet_eid
                import login as _lg
                salida.append(_lg._npc_spawn(pet_eid, 9999, "Pet", (ses.personaje.tile_x + 1, ses.personaje.tile_y), sprite=sp))
            elif org == 9 and dst != 9:
                pet_eid = getattr(ses, 'pet_entity_id', None)
                if pet_eid:
                    import combate as _cb
                    salida.append(_cb.atributo(pet_eid, 0, _cb.VIDA))
                    ses.pet_entity_id = None
            ses.enviar(*salida)
            if ses.personaje and getattr(ses, 'usuario', None):
                cuentas.guardar_inventario(ses.usuario, ses.personaje.char_id, bolsa,
                                   _cantidades(ses))
            log.info(f"[{addr}] item {it}: ranura {org} -> {dst}"
                     + ("  (cambia el equipo)"
                        if inv.es_equipo(org) or inv.es_equipo(dst) else ""))
            return

        # --- usar item (clic derecho) --------------------------------
        # C -> S 0x002E [U8 ranura][LE32 target]
        # Usar / equipar lo que hay en una casilla. Medido: [u32 casilla][u8 0].
        # ANGELS GO! -- el teletransporte de las Superwing.
        #   C -> S 0x0151 [u32 id]
        # El id es el 編號 de jumpmap.xml, NO un stage: la tabla trae 355
        # destinos con su escenario y su casilla. Medido tres veces en
        # Celestia (ids 120, 119 y 109) y las tres la llegada fue la que
        # declara esa tabla.
        #
        # La respuesta se bifurca, y las dos ramas estan medidas:
        #   mismo mapa  0x0012, 0x001B, 0x0042, 0x0013, 0x0003  (sin 0x000C)
        #   otro mapa   0x0012, 0x001B, 0x0042, 0x0013, 0x0007, 0x000C
        if opcode == 0x0151 and ses.rol == 'mundo' and len(cuerpo) >= 4:
            import clases as _cgo
            if not ses.personaje:
                return
            ido = struct.unpack_from('<I', cuerpo, 0)[0]
            d = _angels_go().get(str(ido))
            if d is None:
                log.warning(f"[{addr}] Angels GO! a un destino que no esta "
                            f"en jumpmap.xml: {ido}")
                return
            dst, lleg = int(d['stage']), list(d['tile'])
            ranura = _ranura_de_item(ses, ITEM_SUPERWING)
            if ranura is None:
                log.info(f"[{addr}] Angels GO! sin Superwing en la mochila")
                return
            _sacar(ses, ranura, 1)
            yo = ses.personaje.entity_id
            salida = [struct.pack('<H', 0x0012) + bytes(7)]
            salida += _refrescar(ses, [ranura])
            salida.append(_stats_ses(ses))
            ses.personaje.tile_x, ses.personaje.tile_y = lleg
            if dst == ses.personaje.stage:
                # MISMO MAPA: el salto se hace entero con el 0x0003 y el
                # cliente no recarga nada.
                salida.append(struct.pack('<HIII', 0x0003, yo, lleg[0], lleg[1]))
                ses.enviar(*salida)
                # Si cae dentro de un tornado, se marca pisado para no viajar
                # al primer paso, igual que al llegar por portal.
                _en = _portal_en(dst, *lleg)
                ses.portal_pisado = tuple(_en['tile']) if _en else None
            else:
                # OTRO MAPA: se cierra como un tornado.
                salida.append(struct.pack('<HIB', 0x0007, yo, 1))
                ses.personaje.stage = dst
                ses.monstruos = _monstruos_de(dst)
                _en = _portal_en(dst, *lleg)
                ses.portal_pisado = tuple(_en['tile']) if _en else None
                ses.mapa_cambiado_en = time.time()
                salida.append(_cgo.cambiar_mapa(dst))
                ses.enviar(*salida)
            cid = ses.personaje.char_id
            _guardar_bolsa(ses, cid)
            if getattr(ses, 'usuario', None):
                cuentas.guardar_mapa(ses.usuario, cid, dst, *lleg)
            log.info(f"[{addr}] Angels GO! id {ido} -> stage {dst} tile "
                     f"{lleg} ({d.get('punto') or 'sin nombre'}), "
                     f"Superwing de la casilla {ranura}")
            return

        if opcode == 0x002E and ses.rol == 'mundo' and len(cuerpo) >= 4:
            import inventario as inv
            import clases as _c
            ranura = struct.unpack_from('<I', cuerpo, 0)[0]
            bolsa = getattr(ses, 'inventario', None)
            if bolsa is None or ranura not in bolsa:
                return
            item_id = bolsa[ranura]
            cid = ses.personaje.char_id if ses.personaje else 4980

            # Caso 1: Item equipable (clic derecho)
            if inv.es_equipo(ranura):
                # Ya esta puesto -> desequipar a la bolsa
                dst = _ranura_libre(bolsa, desde=20)
                it = bolsa.pop(ranura)
                bolsa[dst] = it
                _mover_inst(ses, ranura, dst)
                # Sin acuse: en la captura el 0x002E (usar) no recibe
                # ninguno, solo el 0x0012 de arrastrar.
                salida = list(_refrescar(ses, [ranura, dst]))
                salida.append(_stats_ses(ses))
                salida.extend(_apariencia(ses))
                if ses.personaje:
                    import combate as _cb
                    _max_h = _vida_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.hp > _max_h:
                        ses.personaje.hp = _max_h
                    _max_m = _mana_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.mp > _max_m:
                        ses.personaje.mp = _max_m
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.hp, _cb.KIND_HP))
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.mp, _cb.KIND_MP))
                if ranura == 9 and getattr(ses, 'pet_entity_id', None):
                    import combate as _cb
                    salida.append(_cb.atributo(ses.pet_entity_id, 0, _cb.VIDA))
                    ses.pet_entity_id = None
                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] desequipar: item {it} ({ranura}) -> bolsa ({dst})")
                return

            eq_slot = inv.ranura_equipo_de(item_id)
            if eq_slot is not None:
                # Si es un arma dual de fashion y 169 ya esta ocupado pero 170 esta libre:
                if eq_slot == 169 and (169 in bolsa) and (170 not in bolsa) and inv.es_arma_dual(item_id):
                    dst = 170
                else:
                    dst = eq_slot
                # Si se equipa un arma a dos manos (Lanza, Arco, etc.) en mano derecha (3):
                # Desequipar la mano izquierda (4) si habia algo puesto
                if dst == 3 and inv.es_arma_dos_manos(item_id) and 4 in bolsa:
                    it_lhand = bolsa.pop(4)
                    libre = _ranura_libre(bolsa, desde=20)
                    bolsa[libre] = it_lhand
                    log.info(f"[{addr}] arma a dos manos: desequipando mano izquierda {it_lhand} -> bolsa {libre}")
                elif dst == 4 and 3 in bolsa and inv.es_arma_dos_manos(bolsa[3]):
                    # Si intenta equipar mano izquierda y tiene lanza a 2 manos puesta, desequipar la lanza
                    it_rhand = bolsa.pop(3)
                    libre = _ranura_libre(bolsa, desde=20)
                    bolsa[libre] = it_rhand
                    log.info(f"[{addr}] equipando mano izquierda: desequipando arma a dos manos {it_rhand} -> bolsa {libre}")

                if dst in bolsa:
                    # Reemplazar equipo actual (swap con lo puesto)
                    it_eq = bolsa[dst]
                    bolsa[ranura] = it_eq
                    bolsa[dst] = item_id
                    log.info(f"[{addr}] reemplazar equipo: item {item_id} -> {dst}, sacando {it_eq} -> {ranura}")
                else:
                    it = bolsa.pop(ranura)
                    bolsa[dst] = it
                    _mover_inst(ses, ranura, dst)
                    log.info(f"[{addr}] equipar directo: item {it} -> ranura {dst}")

                # Sin acuse: en la captura el 0x002E (usar) no recibe
                # ninguno, solo el 0x0012 de arrastrar.
                salida = list(_refrescar(ses, [ranura, dst]))
                salida.append(_stats_ses(ses))
                salida.extend(_apariencia(ses))
                if ses.personaje:
                    import combate as _cb
                    _max_h = _vida_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.hp > _max_h:
                        ses.personaje.hp = _max_h
                    _max_m = _mana_max(ses.personaje, bolsa=bolsa)
                    if ses.personaje.mp > _max_m:
                        ses.personaje.mp = _max_m
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.hp, _cb.KIND_HP))
                    salida.append(_cb.atributo(ses.personaje.entity_id, ses.personaje.mp, _cb.KIND_MP))

                if dst == 9:
                    # Spawn de la mascota invocada
                    sp = inv.sprite_de_mascota(item_id)
                    pet_eid = (ses.personaje.entity_id if ses.personaje else 1001) + 5000
                    ses.pet_entity_id = pet_eid
                    import login as _lg
                    salida.append(_lg._npc_spawn(pet_eid, 9999, "Pet", (ses.personaje.tile_x + 1, ses.personaje.tile_y), sprite=sp))

                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                return

            # Caso 2: Comida de mascota (Pet Cookies, Pet Can, Pet Feed) - Solo si hay mascota activa
            if inv.es_comida_mascota(item_id) and (9 in bolsa):
                _sacar(ses, ranura, 1)
                salida = [
                    _c.aviso("Fed pet! Hunger satiated (up to 500/100 buffer).", tipo=0, msg_id=_c.MSG_ITEM),
                    *_refrescar(ses, [ranura]),
                ]
                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] comida de mascota usada: {item_id} (ranura {ranura})")
                return

            # Caso 3: Cajas de regalo / Growth Boxes (drop_table)
            recompensas = inv.recompensas_caja(item_id)
            if recompensas:
                # Se gasta UNA caja, no la pila entera, y lo que sale se
                # apila con lo que ya hubiera.
                _sacar(ses, ranura, 1)
                log.info(f"[{addr}] abriendo caja {item_id} de ranura {ranura}: "
                         f"{len(recompensas)} tipos de items")
                salida = []
                tocadas = [ranura]
                for rew_id, cant in recompensas:
                    tocadas.append(_meter(ses, rew_id, max(1, int(cant))))
                    salida.append(_c.aviso(_nombre_item(rew_id), tipo=0, msg_id=_c.MSG_ITEM))
                salida.extend(_refrescar(ses, tocadas))
                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                return

            # Caso 4: Pergaminos de habilidad / Libros de hechizo (Scrolls)
            try:
                scroll_info = _c.info_pergamino(item_id)
            except Exception:
                scroll_info = None

            if scroll_info and ses.personaje:
                req_skills = scroll_info.get('req_skills') or ([scroll_info['req_skill']] if scroll_info.get('req_skill') else [])
                req_lv = scroll_info.get('req_level', 1)
                mid = scroll_info.get('magic_id')
                mnombre = scroll_info.get('magic_name', 'Spell')
                mlv = scroll_info.get('magic_level', 1)

                # Verificar si el personaje tiene alguna de las ramas requeridas (equipadas o en banco)
                habs_pj = list(ses.personaje.habilidades or [])
                banco = getattr(ses.personaje, 'banco_habilidades', {}) or {}
                for bh_id, bh_val in banco.items():
                    bh_lv = bh_val[0] if isinstance(bh_val, (list, tuple)) else bh_val
                    habs_pj.append((int(bh_id), int(bh_lv), 0))

                hab_encontrada = None
                if req_skills:
                    for h in habs_pj:
                        hid = h[0] if isinstance(h, (list, tuple)) else h
                        hlv = h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else 1
                        if hid in req_skills:
                            if hlv >= req_lv or ses.personaje.nivel >= req_lv:
                                hab_encontrada = h
                                break
                            elif hab_encontrada is None:
                                hab_encontrada = False
                else:
                    hab_encontrada = True

                if hab_encontrada is None:
                    nombres_req = [_c.nombre_de_rama(s) for s in req_skills]
                    ses.enviar(_c.aviso(f"You must learn/equip {', '.join(nombres_req[:3])} to learn this.", tipo=0, msg_id=_c.MSG_ITEM))
                    return

                if hab_encontrada is False:
                    ses.enviar(_c.aviso(f"Skill Lv {req_lv} required to learn {mnombre}.", tipo=0, msg_id=_c.MSG_ITEM))
                    return

                # Si ya lo conoce
                if not hasattr(ses.personaje, 'hechizos_aprendidos') or ses.personaje.hechizos_aprendidos is None:
                    ses.personaje.hechizos_aprendidos = set()
                if mid in ses.personaje.hechizos_aprendidos:
                    ses.enviar(
                        _c.aviso(f"You have already learned {mnombre}.", tipo=0, msg_id=_c.MSG_ITEM),
                        struct.pack('<HIB', 0x001D, ses.personaje.entity_id, 1) + struct.pack('<BII', _c.KIND_HECHIZO, mid, mlv)
                    )
                    return

                # Consumir 1 pergamino
                _sacar(ses, ranura, 1)
                yo = ses.personaje.entity_id

                salida = [
                    struct.pack('<HIB', 0x001D, yo, 1) + struct.pack('<BII', _c.KIND_HECHIZO, mid, mlv),
                    _c.aviso(mnombre, tipo=7, msg_id=_c.MSG_HECHIZO),
                    *_refrescar(ses, [ranura])
                ]
                ses.enviar(*salida)
                ses.personaje.hechizos_aprendidos.add(mid)

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_hechizos(ses.usuario, cid, list(ses.personaje.hechizos_aprendidos))
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa, _cantidades(ses))
                log.info(f"[{addr}] pergamino usado: {item_id} -> aprendio {mid} ({mnombre} Lv {mlv})")
                return

            # Caso 4.5: Ring of Angel Wings (Item 1905) - Regresa al checkpoint de Cupido
            if item_id == 1905 and ses.personaje:
                _sacar(ses, ranura, 1)
                _pj = ses.personaje
                dst = getattr(_pj, 'checkpoint_stage', None) or _pj.stage
                cx = getattr(_pj, 'checkpoint_x', None) or _pj.tile_x
                cy = getattr(_pj, 'checkpoint_y', None) or _pj.tile_y
                lleg = [cx, cy]
                yo = _pj.entity_id
                salida = [struct.pack('<H', 0x0012) + bytes(7)]
                salida += list(_refrescar(ses, [ranura]))
                salida.append(_stats_ses(ses))
                _pj.tile_x, _pj.tile_y = lleg
                import clases as _cgo
                if dst == _pj.stage:
                    salida.append(struct.pack('<HIII', 0x0003, yo, lleg[0], lleg[1]))
                    ses.enviar(*salida)
                else:
                    salida.append(struct.pack('<HIB', 0x0007, yo, 1))
                    _pj.stage = dst
                    ses.monstruos = _monstruos_de(dst)
                    ses.mapa_cambiado_en = time.time()
                    salida.append(_cgo.cambiar_mapa(dst))
                    ses.enviar(*salida)
                cid = _pj.char_id
                _guardar_bolsa(ses, cid)
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_mapa(ses.usuario, cid, dst, *lleg)
                log.info(f"[{addr}] Ring of Angel Wings usado: teletransporte al checkpoint stage {dst} tile {lleg}")
                return

            # Caso 5: Consumibles (Pociones HP/MP, Hierba Magica 1228, Biscuits 2, etc.)
            ef_con = inv.efecto_consumible(item_id)
            if ef_con and ses.personaje:
                # Una unidad del monton. Antes se borraba la casilla entera:
                # con una sola galleta daba igual, pero con una pila de diez
                # desaparecian las diez de un mordisco.
                _sacar(ses, ranura, 1)
                salida = []
                yo = ses.personaje.entity_id
                import combate as _cb
                bolsa_p = getattr(ses, 'inventario', None)
                if 'hp' in ef_con:
                    curado = ef_con['hp']
                    ses.personaje.hp = min(_vida_max(ses.personaje, bolsa=bolsa_p), ses.personaje.hp + curado)
                    salida.append(_cb.atributo(yo, ses.personaje.hp, _cb.KIND_HP))
                    salida.extend(_cb.efecto_curacion(yo, yo, curado, efecto=165))
                if 'mp' in ef_con:
                    rec_mp = ef_con['mp']
                    ses.personaje.mp = min(_mana_max(ses.personaje, bolsa=bolsa_p), ses.personaje.mp + rec_mp)
                    salida.append(_cb.atributo(yo, ses.personaje.mp, _cb.KIND_MP))
                    salida.extend(_cb.efecto_recuperacion_mp(yo, yo, rec_mp, efecto=69))
                salida.extend(_refrescar(ses, [ranura]))
                # Y los stats, que es lo que refresca las barras del panel.
                salida.append(_stats_ses(ses))
                ses.enviar(*salida)
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, cid, ses.personaje.nivel, ses.personaje.exp,
                                             ses.personaje.hp, ses.personaje.mp,
                                             hp_max=ses.personaje.hp_max, mp_max=ses.personaje.mp_max)
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] consumible usado: {item_id} (ranura {ranura}) -> {ef_con}")
                return

            # Caso 6: Tarjetas de Monstruo / Coleccionables
            if inv.es_tarjeta_coleccion(item_id):
                _sacar(ses, ranura, 1)
                nom_it = _nombre_item(item_id)
                salida = [
                    _c.aviso(f"Registered {nom_it} to Card Collection!", tipo=0, msg_id=_c.MSG_ITEM),
                    *_refrescar(ses, [ranura]),
                ]
                ses.enviar(*salida)
                if ses.personaje and getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa,
                                   _cantidades(ses))
                log.info(f"[{addr}] tarjeta usada: {nom_it} (ranura {ranura})")
                return

            # Caso 7: Advancement Stone (subir nivel del personaje instantaneamente)
            target_lv = inv.es_advancement_stone(item_id)
            if target_lv and ses.personaje:
                p = ses.personaje
                yo = p.entity_id
                import combate as _cb, clases as _cl
                if p.nivel >= target_lv:
                    ses.enviar(_cl.aviso(f"Your level ({p.nivel}) is already at or above Level {target_lv}.", tipo=0, msg_id=_cl.MSG_ITEM))
                    return
                _sacar(ses, ranura, 1)
                p.nivel = target_lv
                p.exp = 0
                p.hp_max = max(p.hp_max, 500 + p.nivel * 25)
                p.mp_max = max(p.mp_max, 300 + p.nivel * 15)
                p.hp = _vida_max(p)
                p.mp = _mana_max(p)
                exp_sig = min(0xFFFFFFFF, _cb.exp_para_nivel(p.nivel + 1))

                salida = [
                    _cl.aviso(f"Level Up! Advanced to Level {p.nivel}!", tipo=0, msg_id=_cl.MSG_ITEM),
                    _cb.atributo(yo, p.hp, _cb.KIND_HP),
                    _cb.atributo(yo, p.mp, _cb.KIND_MP),
                    struct.pack('<HIB', 0x001D, yo, 4) +
                    struct.pack('<BII', 29, p.nivel, 0) +
                    struct.pack('<BII', 30, min(0xFFFFFFFF, p.exp), 0) +
                    struct.pack('<BII', 31, exp_sig, 0) +
                    struct.pack('<BII', 32, min(0xFFFFFFFF, p.exp), 0),
                    _cb.efecto_level_up(yo, es_skill=False),
                    *_refrescar(ses, [ranura]),
                    _stats_ses(ses)
                ]
                ses.enviar(*salida)
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, cid, p.nivel, p.exp,
                                             p.hp, p.mp, p.habilidades,
                                             hp_max=p.hp_max, mp_max=p.mp_max)
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa, _cantidades(ses))
                log.info(f"[{addr}] {p.nombre} uso Advancement Stone {item_id} -> SUBIO A NIVEL {p.nivel}!")
                return

            # Caso 8: Skill Leveling Stone (subir todas las habilidades a X nivel)
            target_sk_lv = inv.es_skill_leveling_stone(item_id)
            if target_sk_lv and ses.personaje:
                p = ses.personaje
                yo = p.entity_id
                import clases as _cl
                _sacar(ses, ranura, 1)
                nuevas_habs = []
                for h in (p.habilidades or []):
                    sid = h[0] if isinstance(h, (list, tuple)) else h
                    slv = h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else 1
                    nuevo_slv = max(slv, target_sk_lv)
                    nuevas_habs.append((sid, nuevo_slv, 0))
                p.habilidades = nuevas_habs

                if hasattr(p, 'banco_habilidades') and p.banco_habilidades:
                    for bh_id, bh_val in list(p.banco_habilidades.items()):
                        bh_lv = bh_val[0] if isinstance(bh_val, (list, tuple)) else bh_val
                        p.banco_habilidades[bh_id] = (max(bh_lv, target_sk_lv), 0)

                salida = [
                    _cl.aviso(f"All skills raised to Level {target_sk_lv}!", tipo=0, msg_id=_cl.MSG_ITEM),
                    _cl.arbol(p.habilidades, banco=getattr(p, 'banco_habilidades', None)),
                ]
                _ids = [h[0] for h in p.habilidades]
                _hech = _cl.hechizos_iniciales(_ids)
                _todos_hech = [n for n, _ in _hech]
                if getattr(p, 'hechizos_aprendidos', None):
                    _todos_hech = list(set(_todos_hech) | set(p.hechizos_aprendidos))
                if _todos_hech:
                    salida.append(_cl.otorgar_hechizos(yo, _todos_hech))
                for h in p.habilidades:
                    salida.append(struct.pack('<HIBBII', 0x001D, yo, 1, 53, h[0], 0))
                salida.extend(_refrescar(ses, [ranura]))
                salida.append(_stats_ses(ses))
                ses.enviar(*salida)

                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, cid, p.nivel, p.exp,
                                             p.hp, p.mp, p.habilidades,
                                             hp_max=p.hp_max, mp_max=p.mp_max)
                    cuentas.guardar_inventario(ses.usuario, cid, bolsa, _cantidades(ses))
                log.info(f"[{addr}] {p.nombre} uso Skill Leveling Stone {item_id} -> HABILIDADES SUBIDAS A NIVEL {target_sk_lv}!")
                return

            log.info(f"[{addr}] usar item {item_id} (ranura {ranura}): sin accion")
            return

        # --- escena / mapa de radar (Scene Map) -------------------------
        # 0x012D C2S: el cliente abre la ventana de mini-mapa/escena.
        # El servidor responde con una cabecera 0x0062 (entidad de zona) y
        # luego entradas 0x0061 para cada NPC/entidad de interes, terminando
        # con un 0x0061 de un solo byte 0x00.
        if opcode == 0x012D and ses.rol == 'mundo':
            # Usar un entity_id de zona generico basado en el stage del jugador
            stage_z = getattr(ses.personaje, 'stage', 41) if ses.personaje else 41
            zona_eid = 0x000F3000 + stage_z  # entidad de zona ficticia por mapa
            ses.enviar(struct.pack('<HI', 0x0062, zona_eid),
                       struct.pack('<HB', 0x0061, 0x00))
            log.debug(f"[{addr}] escena (0x012D) respondida para stage {stage_z}")
            return

        # 0x012B C2S: radar de NPCs cercanos (5 bytes: 02 00 00 00 00).
        # El servidor responde con 0x0062 + lista de entidades 0x0061 + 0x00.
        # Cada entrada 0x0061 tiene: [U8 kind=1][LE32 eid][LE32 v1][LE32 v2][24 bytes cero]
        if opcode == 0x012B and ses.rol == 'mundo':
            stage_z = getattr(ses.personaje, 'stage', 41) if ses.personaje else 41
            zona_eid = 0x000F3000 + stage_z
            pkgs_radar = [struct.pack('<HI', 0x0062, zona_eid)]
            # Agregar al jugador como entidad del radar
            if ses.personaje:
                yo = ses.personaje.entity_id
                radar_entry = (
                    struct.pack('<H', 0x0061) +
                    struct.pack('<B', 0x01) +  # kind=1 (jugador)
                    struct.pack('<I', yo) +
                    struct.pack('<I', ses.personaje.nivel) +
                    struct.pack('<I', 100) +  # HP%
                    b'\x00' * 24
                )
                pkgs_radar.append(radar_entry)
            # Terminador
            pkgs_radar.append(struct.pack('<HB', 0x0061, 0x00))
            ses.enviar(*pkgs_radar)
            log.debug(f"[{addr}] radar (0x012B) respondido para stage {stage_z}")
            return

        # --- salida de Training Area A -------------------------------
        if (opcode == 0x000D and ses.rol == 'mundo' and ses.personaje
                and ses.personaje.stage == 118 and len(cuerpo) == 9
            and struct.unpack_from('<I', cuerpo, 0)[0] == ses.personaje.entity_id
            and cuerpo[4:] == EVENTO_SALIDA_ENTRENAMIENTO_A):
            _st_retorno, _tile_retorno, _nombre_retorno = RETORNO_ENTRENAMIENTO
            _cerrar_viaje(ses, addr, _st_retorno, _tile_retorno, _nombre_retorno)
            return

        # --- dialogo con los NPC -------------------------------------
        # Secuencia establecida con una captura con marca de tiempo:
        #   0x0005 [LE32 entity] clic   ->  0x0012 primera linea
        #   0x000B [01] siguiente       ->  0x0012 linea siguiente
        #   ... y al terminar, un 0x0012 de nueve ceros que cierra el cuadro.
        if opcode == 0x0005 and ses.rol == 'mundo' and len(cuerpo) >= 4:
            import dialogos
            ent = struct.unpack_from('<I', cuerpo, 0)[0]
            if (ses.personaje
                    and ses.personaje.stage in ETAPAS_ENTRENAMIENTO
                    and ent == ENTIDAD_SALIDA_ENTRENAMIENTO_B):
                _st_retorno, _tile_retorno, _nombre_retorno = RETORNO_ENTRENAMIENTO
                _cerrar_viaje(ses, addr, _st_retorno, _tile_retorno,
                              _nombre_retorno)
                return
            # ESTATUA QUE TELETRANSPORTA. Va lo primero porque no es un NPC ni
            # un monstruo: es un objeto de mapa, y el resto del manejador ni
            # lo reconoceria.
            if ses.personaje:
                _est = _estatua_con_entidad(ses.personaje.stage, ent)
                if _est is not None:
                    ses.dlg_estatua = _est
                    ses.dlg_ent = None
                    ses.enviar(_dialogo_de_estatua(_est))
                    log.info(f"[{addr}] estatua {ent}: se ofrece el salto a "
                             f"{_est.get('llegada')}")
                    return
            # Si ya se cumplio lo que pedia el tramo actual, se avanza ANTES
            # de hablar: en el juego, en cuanto llevas el examen encima
            # Raphael te suelta el "Good for you!" y no repite lo anterior.
            if ses.personaje and ses.personaje.stage == MAPA_DEL_TUTORIAL and ent in dialogos.NOMBRE_POR_ENTIDAD:
                import clases as _c
                _sig = ses.personaje.tutorial + 1
                _req = _c.REQUISITO_ETAPA.get(_sig)
                if (_req and _sig < dialogos.etapas(ent)
                        and _req in (getattr(ses, 'inventario', {}) or {}).values()):
                    ses.personaje.tutorial = _sig
                    if getattr(ses, 'usuario', None):
                        cuentas.guardar_tutorial(ses.usuario,
                                                 ses.personaje.char_id, _sig)
                    log.info(f"[{addr}] tutorial: cumplido el requisito, "
                             f"pasa a la etapa {_sig}")
            # Clic en un MONSTRUO: hay que contestar con su vida. Eso es lo
            # que hace el servidor real y lo que le dice al cliente que ese
            # objetivo se puede atacar; sin la respuesta el cliente ni siquiera
            # llega a mandar el 0x0006 y parecia que "no deja atacar".
            import combate as _cb0
            _m = (getattr(ses, 'monstruos', None) or {}).get(ent)
            if _m is not None:
                # El clic sobre un monstruo ES el ataque basico: el cliente no
                # manda ningun 0x0006 para pegar sin habilidad. Medido en
                # mundo_154337_948959, t=3.08:
                #   C2S 0x0005 [target][00 00]
                #   S2C 0x0013 [monstruo] vida actual
                #   S2C 0x000A [yo][monstruo] tipo=3 anim=1480
                #   S2C 0x0013 + 0x000B con el numero
                # Antes se contestaba fijando el objetivo y se esperaba un
                # 0x0006 que nunca llegaba, asi que el golpe basico no existia.
                # El clic SOLO selecciona: se contesta con la vida del
                # monstruo y nada mas. El golpe lo pide el cliente aparte,
                # con el 0x0016 accion 0x0c, y lo repite solo cada ~1,5 s.
                # Atacar tambien aqui hacia que cada clic disparara DOS
                # golpes con 15 ms de diferencia, y por eso el personaje
                # pegaba al doble de velocidad.
                # Objetivo nuevo: se limpia el cooldown para que el primer
                # golpe salga enseguida. Si no, el clic cae dentro de la
                # cadencia del objetivo anterior y el personaje "lo piensa"
                # antes de empezar a pegar.
                if getattr(ses, 'objetivo_actual', None) != ent:
                    ses.objetivo_actual = ent
                    ses.ultimo_golpe = 0
                if not getattr(_m, 'encantado', False):
                    if getattr(ses, 'invocacion', None):
                        ses.invocacion['objetivo'] = _m
                    if getattr(ses, 'monstruo_encantado', None) and getattr(ses.monstruo_encantado, 'vivo', False):
                        ses.monstruo_encantado.charmed_objetivo = _m
                ses.enviar(_cb0.atributo(ent, _m.porcentaje))
                return



            # Los dialogos del tutorial van por entity_id (19 Raphael, 20
            # Interface Tutor, 21 Angel Aide) y esos numeros SE REPITEN en
            # otros mapas: en el Lyceum la 19 es el Magic Seller, la 20 el Bao
            # Clerk y la 21 Michael, y les salia el dialogo del tutorial. Solo
            # valen en Guide Palace.
            # En Fighting Palace (stage 57):
            if ses.personaje and ses.personaje.stage == 57:
                # Por NOMBRE: los entity_id los asigna poblar() y ya no son
                # el 500 fijo de antes.
                _nom_ent = _nombre_entidad(ses, ent)
                if _nom_ent == 'Angel Raphael':
                    kills = getattr(ses, 'slarm_kills', 0)
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    g_fp = dialogos.guion_fighting_palace(kills, nom)
                    ses.dlg_ent, ses.dlg_guion, ses.dlg_paso = ent, g_fp, 0
                    ses.dlg_val = 5
                    ses.enviar(dialogos.linea_de(g_fp, 0, nom))
                    ses.dlg_paso = 1
                    log.info(f"[{addr}] Angel Raphael (Fighting Palace, kills={kills}): linea 1 de {len(g_fp)}")
                    return
                # Totems de facciones en Fighting Palace:
                totems_fp = {'Iron Totem': 5138, 'Dark City Totem': 5137,
                             'Aurora Totem': 5136, 'Breeze Totem': 5139}
                if _nom_ent in totems_fp:
                    sub_totem = dialogos.armar_linea(totems_fp[_nom_ent], 4, [])
                    ses.dlg_ent, ses.dlg_guion, ses.dlg_paso = ent, [sub_totem[2:]], 1
                    ses.dlg_val = 4
                    ses.enviar(sub_totem)
                    log.info(f"[{addr}] Totem {_nom_ent} ({ent}) en Fighting Palace")
                    return
                log.debug(f"[{addr}] clic en la entidad {ent} en stage 57: sin dialogo")
                return

            if ses.personaje and ses.personaje.stage != MAPA_DEL_TUTORIAL:
                # Fuera del tutorial, cada NPC tiene su propia linea, sacada
                # de msg.xml por su nombre.
                faccion = ses.personaje.faction if ses.personaje else "Heaven"
                if 121600 <= ent <= 121699: _st_ent = 3     # Aurora City
                elif 121700 <= ent <= 121725: _st_ent = 5   # Cherry Village
                elif 121765 <= ent <= 121775: _st_ent = 15  # Mysterious Wetland
                elif 121799 <= ent <= 121811: _st_ent = 21  # Dragon Graveyard
                elif 121812 <= ent <= 121835: _st_ent = 22  # Mysterious Garden
                elif 121850 <= ent <= 121919: _st_ent = 26  # Dark City
                elif 121920 <= ent <= 121999: _st_ent = 29  # Breeze Woods
                elif 122040 <= ent <= 122063: _st_ent = 35  # Memory Cave
                elif 122064 <= ent <= 122085: _st_ent = 36  # Gebuer Vale
                elif 122086 <= ent <= 122199: _st_ent = 38  # Iron Castle
                elif 122295 <= ent <= 122305: _st_ent = 69  # Lava Cave
                elif 122306 <= ent <= 122315: _st_ent = 70  # Flaming Door
                elif 122355 <= ent <= 122404 or (30080 <= ent <= 30083): _st_ent = 88  # Palm Base
                elif 122408 <= ent <= 122415 or (30112 <= ent <= 30115): _st_ent = 90  # Blue Ocean
                elif 122460 <= ent <= 122495 or (30336 <= ent <= 30339): _st_ent = 104  # Waterfall Camp
                elif 122585 <= ent <= 122610 or (30608 <= ent <= 30611): _st_ent = 121  # Desert Racetrack
                elif 122730 <= ent <= 122760 or (31008 <= ent <= 31011): _st_ent = 146  # Airship Station
                elif 122800 <= ent <= 122820 or (31120 <= ent <= 31123): _st_ent = 153  # Building Blocks City
                elif 122890 <= ent <= 122925 or (31280 <= ent <= 31283): _st_ent = 163  # Hoca Village
                elif 123000 <= ent <= 123030 or (31392 <= ent <= 31395): _st_ent = 170  # Pharaoh Village
                else: _st_ent = None

                if _st_ent and ses.personaje and (not getattr(ses.personaje, 'stage', 0) or ses.personaje.stage != _st_ent):
                    ses.personaje.stage = _st_ent

                g2 = dialogos.propio(
                    _nombre_entidad(ses, ent), faccion=faccion,
                    jugador=getattr(ses.personaje, 'nombre', '') if ses.personaje else '',
                    visto_michael=bool(getattr(ses.personaje, 'hablo_michael', False)
                                       if ses.personaje else False),
                    stage=getattr(ses.personaje, 'stage', 0) if ses.personaje else 0,
                    registrado=_ya_registrado(ses),
                    entidad=ent)
                if g2:
                    nom2 = ses.personaje.nombre if ses.personaje else 'Jugador'
                    ses.dlg_ent, ses.dlg_guion, ses.dlg_paso = ent, g2, 1
                    ses.dlg_val = struct.unpack_from('<H', g2[0], 4)[0] if len(g2[0]) >= 6 else 4
                    ses.enviar(dialogos.linea_de(g2, 0, nom2))
                    log.info(f"[{addr}] dialogo de {_nombre_entidad(ses, ent)} (val={ses.dlg_val})")
                    return
                log.debug(f"[{addr}] clic en la entidad {ent}: sin dialogo")
                return
            # En Guide Palace (stage 51):
            inv_items = list((getattr(ses, 'inventario', {}) or {}).values())
            has_exam = (1386 in inv_items)
            bolsa = getattr(ses, 'inventario', {}) or {}
            # Guantes (5) o Zapatos (6) que Raphael ensena a equiparse en la etapa 1:
            has_gloves_or_shoes = bool(bolsa.get(5) or bolsa.get(6))

            if ent == 19:  # Raphael
                if has_exam:
                    etapa = 3
                elif ses.personaje and ses.personaje.tutorial >= 2:
                    etapa = 2
                elif ses.personaje and ses.personaje.tutorial >= 1 and has_gloves_or_shoes:
                    etapa = 2
                elif (ses.personaje and ses.personaje.habilidades):
                    etapa = 1
                else:
                    etapa = 0
            elif ent == 21:  # Angel Aide
                if has_exam:
                    etapa = 2  # 5047 (Good for you!)
                elif (ses.personaje and (ses.personaje.tutorial >= 2 or getattr(ses, 'oro', 0) >= 10)):
                    etapa = 1  # 5022 con menu: 5045 Buy / 5046 Quit
                else:
                    etapa = 0  # 5022 sin menu (0 opciones)
            else:  # 20 Interface Tutor
                etapa = 0

            g = dialogos.guion_etapa(ent, etapa)
            if not g:
                log.debug(f"[{addr}] clic en la entidad {ent}: sin dialogo conocido")
                return
            nom = ses.personaje.nombre if ses.personaje else 'Jugador'
            ses.dlg_ent, ses.dlg_guion, ses.dlg_paso = ent, g, 0
            ses.dlg_val = 3 if ent == 19 else (2 if ent == 20 else 52)
            ses.enviar(dialogos.linea_de(g, 0, nom))
            ses.dlg_paso = 1
            log.info(f"[{addr}] dialogo con la entidad {ent} (etapa {etapa}): "
                     f"linea 1 de {len(g)}")
            return

        if opcode == 0x000B and ses.rol == 'mundo' and getattr(ses, 'dlg_estatua', None):
            import dialogos as _dlg_e
            _est = ses.dlg_estatua
            ses.dlg_estatua = None
            _v = d.get('valor', 0) if d else 0
            _i = _dlg_e.indice_opcion(_v) if _dlg_e.es_opcion(_v) else -1
            ses.enviar(struct.pack('<H', 0x0012) + _dlg_e.FIN)
            if _i != 0 or not ses.personaje or not _est.get('llegada'):
                log.info(f"[{addr}] estatua: se responde que no (opcion {_i})")
                return
            _x, _y = _est['llegada']
            ses.personaje.tile_x, ses.personaje.tile_y = _x, _y
            ses.enviar(struct.pack('<HIII', 0x0003,
                                   ses.personaje.entity_id, _x, _y))
            log.info(f"[{addr}] estatua: aceptado, salta a ({_x},{_y})")
            return

        if opcode == 0x000B and ses.rol == 'mundo' and getattr(ses, 'dlg_ent', None):
            import dialogos
            ent, paso = ses.dlg_ent, getattr(ses, 'dlg_paso', 0)
            g = getattr(ses, 'dlg_guion', None) or []
            # Elegir una opcion del cuadro, no pasar de linea.
            _v = d.get('valor', 1) if d else 1
            if dialogos.es_opcion(_v):
                # Se buscan las opciones en la ULTIMA linea del guion que
                # tenga, no en la de 'paso - 1'. Una respuesta puede ser
                # varias lineas -- la de dejar el entrenamiento son dos, el
                # 10123 suelto y el 10124 con las opciones -- y mirando solo
                # una caia en la que no tiene ninguna.
                _ops = []
                for _l in reversed(g[:paso] if 0 < paso <= len(g) else g):
                    _ops = dialogos.opciones_de(_l)
                    if _ops:
                        break
                _i = dialogos.indice_opcion(_v)
                import dialogos as _dlg_mod
                _el = _ops[_i] if 0 <= _i < len(_ops) else None
                val = getattr(ses, 'dlg_val', 4)
                if _el is None:
                    # Sin opcion que corresponda no hay nada que hacer: se
                    # cierra el cuadro. Antes se seguia de largo y el
                    # servidor reventaba comparando None con un numero, lo
                    # que tiraba la conexion del jugador.
                    log.warning(f"[{addr}] opcion {_v} sin correspondencia "
                                f"(hay {len(_ops)} opciones); se cierra el "
                                f"dialogo")
                    ses.dlg_ent = None
                    ses.enviar(struct.pack('<H', 0x0012) + dialogos.FIN)
                    return

                # Casos especiales de opciones en Guide Palace:
                # 1. Interface Tutor: 5241 ("OK") -> Inicia explicacion paso a paso
                if _el == 5241:
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    ses.dlg_ent = ent
                    ses.dlg_guion = g
                    ses.dlg_paso = 2
                    ses.enviar(dialogos.linea_de(g, 1, nom))
                    log.info(f"[{addr}] Interface Tutor: explicacion iniciada (linea 5243)")
                    return

                # 2. Raphael: 5008 ("I'm ready") -> Inicia fase de equipamiento
                if _el == 5008:
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    ses.dlg_ent = ent
                    ses.dlg_guion = g
                    ses.dlg_paso = 3
                    ses.enviar(dialogos.linea_de(g, 2, nom))
                    log.info(f"[{addr}] Raphael: jugador listo, inicia fase de equipo (linea 5014)")
                    return

                # 3. Raphael: 5011 ("Yes." confirmar abandono del tutorial)
                if _el == 5011:
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    submsg_5013 = dialogos.armar_linea(5013, 3, [], strings=[nom])
                    submsg_fin = struct.pack('<H', 0x0012) + dialogos.FIN
                    ses.enviar(submsg_5013, submsg_fin)
                    ses.dlg_ent = None
                    import clases as _cl3
                    ses.personaje.stage = 41
                    ses.personaje.tile_x, ses.personaje.tile_y = (152, 74)
                    ses.monstruos = _monstruos_de(41)
                    ses.enviar(_cl3.cambiar_mapa(41))
                    if getattr(ses, 'usuario', None):
                        cuentas.guardar_mapa(ses.usuario, ses.personaje.char_id, 41, 152, 74)
                    log.info(f"[{addr}] Raphael: abandono tutorial -> enviado a Angel Lyceum (41)")
                    return

                if 121600 <= ent <= 121699: _st_ent = 3     # Aurora City
                elif 121700 <= ent <= 121799: _st_ent = 5   # Cherry Village
                elif 121800 <= ent <= 121849: _st_ent = 22  # Mysterious Garden
                elif 121850 <= ent <= 121919: _st_ent = 26  # Dark City
                elif 121920 <= ent <= 121999: _st_ent = 29  # Breeze Woods
                elif 122040 <= ent <= 122063: _st_ent = 35  # Memory Cave
                elif 122064 <= ent <= 122085: _st_ent = 36  # Gebuer Vale
                elif 122086 <= ent <= 122199: _st_ent = 38  # Iron Castle
                elif 122295 <= ent <= 122305: _st_ent = 69  # Lava Cave
                elif 122306 <= ent <= 122315: _st_ent = 70  # Flaming Door
                elif 122355 <= ent <= 122404 or (30080 <= ent <= 30083): _st_ent = 88  # Palm Base
                elif 122408 <= ent <= 122415 or (30112 <= ent <= 30115): _st_ent = 90  # Blue Ocean
                elif 122460 <= ent <= 122495 or (30336 <= ent <= 30339): _st_ent = 104  # Waterfall Camp
                elif 122585 <= ent <= 122610 or (30608 <= ent <= 30611): _st_ent = 121  # Desert Racetrack
                elif 122730 <= ent <= 122760 or (31008 <= ent <= 31011): _st_ent = 146  # Airship Station
                elif 122800 <= ent <= 122820 or (31120 <= ent <= 31123): _st_ent = 153  # Building Blocks City
                elif 122890 <= ent <= 122925 or (31280 <= ent <= 31283): _st_ent = 163  # Hoca Village
                elif 123000 <= ent <= 123030 or (31392 <= ent <= 31395): _st_ent = 170  # Pharaoh Village
                else: _st_ent = None

                if _st_ent and ses.personaje and (not getattr(ses.personaje, 'stage', 0) or ses.personaje.stage != _st_ent):
                    ses.personaje.stage = _st_ent

                submsgs = dialogos.respuesta_a(
                    _el, entidad=ent, val=val,
                    nombre=_nombre_entidad(ses, ent),
                    stage=getattr(ses.personaje, 'stage', 0)
                    if ses.personaje else 0,
                    nivel=getattr(ses.personaje, 'nivel', 0)
                    if ses.personaje else 0) if _el else (struct.pack('<H', 0x0012) + dialogos.FIN,)
                # Solo la PRIMERA linea de dialogo. El cliente espera una,
                # pide "siguiente" con 0x000B valor 1, y recien entonces le
                # llega la que sigue. Medido: al elegir "Quit the training"
                # el servidor manda el 10123, el cliente contesta 01, y
                # despues llega el 10124 con las opciones. Mandando las dos
                # de golpe el cuadro se quedaba sin hacer nada.
                _dialogo_visto = False
                _envio = []
                for _p in submsgs:
                    _es_dlg = len(_p) > 2 and _p[:2] == struct.pack('<H', 0x0012)
                    if _es_dlg and _dialogo_visto:
                        continue
                    if _es_dlg:
                        _dialogo_visto = True
                    _envio.append(_p)
                ses.enviar(*_envio)



                # Elecciones especiales
                if _el in DESTINOS_ENTRENAMIENTO and ses.personaje:
                    _st_area, _tile_area, _nombre_area = DESTINOS_ENTRENAMIENTO[_el]
                    ses.viaje_pendiente = (_st_area, _tile_area, _nombre_area)
                elif _el == 10125 and ses.personaje:
                    # "Quit the training": el traslado NO va aqui. Medido:
                    # al decir que si el servidor manda el 10127, el cliente
                    # pide la linea siguiente, llega el cierre del cuadro y
                    # RECIEN ENTONCES el cambio de mapa. Mandandolo en este
                    # momento el traslado caia en mitad del dialogo y el
                    # cuadro se quedaba colgado.
                    ses.viaje_pendiente = (STAGE_GRADUACION, TILE_GRADUACION,
                                           'Graduation Palace')
                    ses.personaje.faction = "Graduated"
                    if getattr(ses, 'usuario', None):
                        cuentas.guardar_faccion(ses.usuario,
                                                ses.personaje.char_id, "Graduated")
                    log.info(f"[{addr}] {ses.personaje.nombre} confirmo dejar "
                             f"el entrenamiento; viaja al cerrarse el dialogo")
                elif _el == 10235 and ses.personaje:
                    # Confirmar la faccion. Se decide por el NOMBRE del NPC,
                    # no por su id: antes habia una lista de ids de totems
                    # escrita a mano y los cuatro Angeles del Graduation
                    # Palace no estaban en ella, asi que confirmar con
                    # cualquiera de ellos asignaba Aurora por defecto.
                    _nom_npc = _nombre_entidad(ses, ent) or ''
                    FACCION_POR_NOMBRE = {
                        'Aurora': "Aurora",
                        'Dark City': "Dark City",
                        'Iron': "Iron Castle",
                        'Breeze': "Breeze Woods",
                    }
                    nueva_fac = "Aurora"
                    for _clave, _fac in FACCION_POR_NOMBRE.items():
                        if _clave.lower() in _nom_npc.lower():
                            nueva_fac = _fac
                            break
                    else:
                        log.warning(f"[{addr}] confirmar faccion con "
                                    f"'{_nom_npc}': no se reconoce, se usa "
                                    f"Aurora")
                    import clases as _cl5
                    _pj = ses.personaje
                    _pj.faction = nueva_fac
                    # Y al aceptar te lleva a la ciudad de esa faccion. El
                    # traslado faltaba: se quedaba en el Graduation Palace.
                    _dst, _tile = CIUDAD_DE_FACCION.get(nueva_fac,
                                                        CIUDAD_DE_FACCION["Aurora"])
                    # El viaje espera a que se cierre el cuadro, igual que el
                    # del Graduation Palace. Medido: se elige "Yes", pasan
                    # dos lineas mas, llegan las misiones y RECIEN ENTONCES
                    # el cambio de mapa.
                    # La faccion se aplica AL LLEGAR a la ciudad, que es
                    # cuando el cliente la cambia de "Heaven" a la suya. Y lo
                    # que se guarda es el nombre de la FACCION, no el de la
                    # ciudad: el campo pasa a decir "Beasts", no "Breeze
                    # Woods".
                    _fac_nombre = NOMBRE_DE_FACCION.get(nueva_fac, nueva_fac)
                    ses.viaje_pendiente = (_dst, _tile, _fac_nombre)
                    ses.faccion_al_llegar = _fac_nombre
                    # Se completa "Choosing country" y se da la de registro
                    # de esa ciudad, como en la captura: primero el 0x0022 de
                    # la nueva mision y despues el de la 103 con el paso 1 y
                    # el sello de la hora.
                    # Las misiones se mandan JUNTO CON EL VIAJE, al
                    # cerrarse el cuadro; aqui todavia quedan dos lineas de
                    # dialogo por delante.
                    ses.misiones_al_llegar = nueva_fac
                    log.info(f"[{addr}] {_pj.nombre} eligio {nueva_fac}: "
                             f"viaja al stage {_dst} casilla {_tile} cuando "
                             f"se cierre el dialogo")
                elif _el == 5747 and ses.personaje:
                    # Cupid: fija donde se revive.
                    #
                    # Dos cosas estaban mal. Se guardaba en spawn_stage/
                    # spawn_x/spawn_y y al revivir se leia checkpoint_stage/
                    # checkpoint_x/checkpoint_y, o sea otros campos: el
                    # checkpoint no hacia nada. Y ademas fijaba siempre el
                    # Lyceum en (138,60) aunque hablaras con el Cupid del
                    # East o del West. Ahora queda donde estas parado, que es
                    # justo al lado del Cupid con el que hablaste.
                    _pj = ses.personaje
                    _pj.checkpoint_stage = _pj.stage
                    _pj.checkpoint_x, _pj.checkpoint_y = _pj.tile_x, _pj.tile_y
                    if getattr(ses, 'usuario', None):
                        cuentas.guardar_checkpoint(ses.usuario, _pj.char_id,
                                                   _pj.stage, _pj.tile_x, _pj.tile_y)
                    log.info(f"[{addr}] {_pj.nombre} fijo el punto de revivir "
                             f"con Cupid: mapa {_pj.stage} casilla "
                             f"({_pj.tile_x},{_pj.tile_y})")
                elif _el == 20001 and ses.personaje:
                    # Teleporter Jack: East Field A1 (stage 42)
                    _sincronizar_cambio_mapa(ses, 42, 11, 113)
                    log.info(f"[{addr}] Teleporter Jack: al East Playground (stage 42)")
                elif _el == 20003 and ses.personaje:
                    # Teleporter Shiva: West Field A1 (stage 43)
                    _sincronizar_cambio_mapa(ses, 43, 189, 24)
                    log.info(f"[{addr}] Teleporter Shiva: al West Playground (stage 43)")
                elif 5802 <= _el <= 5806 and ses.personaje:
                    # East Playground A1..A5
                    _sincronizar_cambio_mapa(ses, 42, 11, 113)
                    log.info(f"[{addr}] East Portal: al East Playground (stage 42)")
                elif (getattr(ses, 'dlg_portal', None)
                      and str(_el) in (ses.dlg_portal.get('destinos') or {})
                      and ses.personaje):
                    # DESTINO PROPIO DEL PORTAL. Antes cada menu de portal
                    # habia que escribirlo a mano aqui con su rango de ids;
                    # asi el nudo de Teddy Amusement, que manda a dos puntos
                    # del MISMO mapa, no se podia expresar. Ahora el portal
                    # trae {'destinos': {'<id de opcion>': {...}}} y se
                    # resuelve solo.
                    _d = ses.dlg_portal['destinos'][str(_el)]
                    _falso = dict(ses.dlg_portal)
                    _falso['destino'] = _d.get('destino', ses.personaje.stage)
                    _falso['llegada'] = _d['llegada']
                    _falso['direccion'] = _d.get('direccion')
                    _viajar_por_portal(ses, addr, _falso,
                                       'por la opcion %d' % _el)
                elif 5807 <= _el <= 5811 and ses.personaje:
                    # West Playground A1..A5
                    _sincronizar_cambio_mapa(ses, 43, 186, 27)
                    log.info(f"[{addr}] West Portal: al West Playground (stage 43)")
                elif (_el in _dlg_mod.CIUDAD_POR_OPCION
                      and _el % 10000 == 2 and ses.personaje):
                    # "I have come here to register!": completa la mision de
                    # registro y da las dos siguientes. Medido con el Angel
                    # de Breeze Woods: llegan la 136 "Knowing Breeze Woods",
                    # la 140 "Reaching higher level" y la 130 con el paso 1.
                    # LAS QUESTS SON LAS DE SU CIUDAD, no las de Breeze
                    # Woods. Antes estaban escritas a mano (136, 140 y 130),
                    # asi que registrarse en Aurora completaba la quest de
                    # Breeze y daba las suyas.
                    import clases as _clr, time as _tmr
                    _pjr = ses.personaje
                    _cfgr = _dlg_mod.ANGEL_DE_CIUDAD[
                        _dlg_mod.CIUDAD_POR_OPCION[_el]]
                    _q_reg = _cfgr['mision_registro']
                    _nuevas_q = (_cfgr['mision_conocer'], _cfgr['mision_nivel'])
                    _paqr = []
                    for _q in _nuevas_q:
                        if _q not in [x[0] for x in (_pjr.quests or [])]:
                            _pjr.quests = list(_pjr.quests or []) + [(_q, 0)]
                        _paqr += [_clr.mision(_pjr.char_id, _q, 0),
                                  _clr.aviso(_clr.nombre_de_quest(_q), tipo=0,
                                             msg_id=_clr.MSG_QUEST)]
                    _pjr.quests = [(q, 1 if q == _q_reg else pa)
                                   for q, pa in (_pjr.quests or [])]
                    _paqr.append(_clr.mision(_pjr.char_id, _q_reg, 1,
                                             int(_tmr.time())))
                    ses.enviar(*_paqr)
                    log.info(f"[{addr}] {_pjr.nombre} se registro con el Angel "
                             f"de su ciudad: misiones {_nuevas_q}, la "
                             f"{_q_reg} completada")
                elif (_el in _dlg_mod.CIUDAD_POR_OPCION
                      and _el % 10000 == 18 and ses.personaje):
                    # "Send me back to the Angel Lyceum" del Angel de una
                    # ciudad. Medido: contesta con el 50019 y el cambio de
                    # mapa llega al cerrarse el cuadro, no en el acto.
                    ses.viaje_pendiente = (41, TILE_VUELTA_LYCEUM,
                                           'Angel Lyceum')
                    log.info(f"[{addr}] {ses.personaje.nombre} vuelve al "
                             f"Angel Lyceum cuando se cierre el dialogo")
                elif _el == 5080 and ses.personaje:
                    # Director Wolay: retorno a la ciudad de faccion elegida
                    # La faccion guardada ya no es el nombre de la ciudad
                    # ("Breeze Woods") sino el de la faccion ("Beasts"), asi
                    # que esta tabla, que iba por el nombre viejo, no
                    # encontraba ninguna y mandaba a todos a Aurora. Se usa
                    # el mismo destino que al elegirla con el Angel.
                    CIUDAD_POR_FACCION = {
                        NOMBRE_DE_FACCION[c]: CIUDAD_DE_FACCION[c]
                        for c in CIUDAD_DE_FACCION if c in NOMBRE_DE_FACCION
                    }
                    st_dest, tile_dest = CIUDAD_POR_FACCION.get(
                        ses.personaje.faction, CIUDAD_DE_FACCION["Aurora"])
                    _sincronizar_cambio_mapa(ses, st_dest, tile_dest[0], tile_dest[1])
                    log.info(f"[{addr}] Director Wolay: retorno a {ses.personaje.faction} (stage {st_dest})")
                elif _el == 5058 and ses.personaje:
                    # Raphael (Fighting Palace): Repetir explicacion
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    g_rep = dialogos.guion_fighting_palace(0, nom)
                    ses.dlg_ent = ent
                    ses.dlg_guion = g_rep
                    ses.dlg_paso = 1
                    ses.dlg_val = 5
                    ses.enviar(dialogos.linea_de(g_rep, 0, nom))
                    log.info(f"[{addr}] Raphael (Fighting Palace): repitiendo explicacion de combate")
                    return
                elif _el == 5063 and ses.personaje:
                    # Raphael (Fighting Palace): "I'm ready to go to the Angel Lyceum."
                    # Manda la linea 5065 y luego teletransporta a Angel Lyceum (stage 41)
                    nom = ses.personaje.nombre if ses.personaje else 'Jugador'
                    submsg_5065 = dialogos.armar_linea(5065, 5, [])
                    submsg_fin = struct.pack('<H', 0x0012) + dialogos.FIN
                    ses.enviar(submsg_5065, submsg_fin)
                    ses.dlg_ent = None
                    _sincronizar_cambio_mapa(ses, 41, 152, 74)
                    log.info(f"[{addr}] Raphael (Fighting Palace): combate completado -> teletransportado a Angel Lyceum (41)")
                    return

                termina = any(
                    m.endswith(dialogos.FIN) or struct.unpack_from('<H', m, 0)[0] in (0x0034, 0x002B, 0x001D)
                    for m in submsgs if len(m) >= 2
                )
                if termina:
                    ses.dlg_ent = None
                    # El cuadro se cierra aqui mismo, asi que lo que dejo
                    # pedido la opcion -- el viaje, la faccion y las misiones
                    # -- se hace ahora. Antes quedaba apuntado para un cierre
                    # que ya habia pasado y el personaje no se movia.
                    _v2 = getattr(ses, 'viaje_pendiente', None)
                    if _v2 and ses.personaje:
                        ses.viaje_pendiente = None
                        _st2, _tile2, _nom2 = _v2
                        _cerrar_viaje(ses, addr, _st2, _tile2, _nom2)
                else:
                    ses.dlg_ent = ent
                    # TODAS las lineas de dialogo de la respuesta, no solo la
                    # primera. Guardando una sola, una respuesta de varias
                    # lineas se quedaba trunca: al elegir "Quit the training"
                    # el guion quedaba en [10123] y el "siguiente" cerraba el
                    # cuadro en vez de mandar el 10124 con las opciones.
                    ses.dlg_guion = [m[2:] for m in submsgs
                                     if len(m) > 2
                                     and struct.unpack_from('<H', m, 0)[0] == 0x0012]
                    ses.dlg_paso = 1
                    if len(submsgs[0]) >= 8:
                        ses.dlg_val = struct.unpack_from('<H', submsgs[0], 6)[0]
                log.info(f"[{addr}] eligio la opcion {_i + 1}"
                         + (f" (dialogo {_el})" if _el else ""))
                return
            nom = ses.personaje.nombre if ses.personaje else 'Jugador'
            # Entrega de guantes y zapatos en Raphael antes de mostrar la linea 5015 (paso == 3 en tramo 1):
            if ent == 19 and paso == 3 and len(g) >= 7 and struct.unpack_from('<I', g[3], 0)[0] == 5015:
                cid = ses.personaje.char_id if ses.personaje else 4980
                ses.inventario = getattr(ses, 'inventario', {}) or {}
                import inventario as _iv
                import clases as _cls
                s_glov = _ranura_libre(ses.inventario, desde=20)
                ses.inventario[s_glov] = 28
                s_shoe = _ranura_libre(ses.inventario, desde=s_glov + 1)
                ses.inventario[s_shoe] = 30
                ses.enviar(*_iv.entregar(cid, 28, s_glov),
                           *_iv.entregar(cid, 30, s_shoe),
                           _iv.completo(cid, _con_oro(ses), _dueno(ses)),
                           _cls.aviso("Students' Gloves\x00Students' shoes", tipo=0, msg_id=493))
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_inventario(ses.usuario, cid, ses.inventario,
                                   _cantidades(ses))
                log.info(f"[{addr}] Raphael: entregados guantes (slot {s_glov}) y zapatos (slot {s_shoe})")

            # El cliente manda el 0x000B repetido -- en la captura llegan dos
            # seguidos con 210 ms de diferencia -- y el servidor REAL contesta
            # al primero con la linea y al segundo cerrando el cuadro. Se
            # probo ignorar el repetido cuando la linea tiene opciones y fue
            # un invento: aqui se reproduce lo medido, que es cerrar.
            # Michael da la mision "Choosing country" JUSTO ANTES de su
            # ultima linea, no al cerrarse el cuadro. Medido: el 0x0022 llega
            # a los 53.05 y el 10134 a los 53.23, y el cierre recien a los
            # 54.29.
            if (ses.personaje and paso == len(g) - 1
                    and _nombre_entidad(ses, ent) == 'Michael'
                    and not getattr(ses.personaje, 'hablo_michael', False)):
                import clases as _cl7
                ses.personaje.hablo_michael = True
                _q = _cl7.QUEST_ELEGIR_PAIS
                if _q not in [x[0] for x in (ses.personaje.quests or [])]:
                    ses.personaje.quests = list(ses.personaje.quests or []) + [(_q, 0)]
                ses.enviar(_cl7.mision(ses.personaje.char_id, _q, 0),
                           _cl7.aviso(_cl7.nombre_de_quest(_q), tipo=0,
                                      msg_id=_cl7.MSG_QUEST))
                log.info(f"[{addr}] Michael: mision {_q} "
                         f"'{_cl7.nombre_de_quest(_q)}'; los Angeles de "
                         f"faccion pasan a su segundo dialogo")

            ses.enviar(dialogos.linea_de(g, paso, nom))
            if paso < len(g):
                ses.dlg_paso = paso + 1
                log.debug(f"[{addr}] dialogo {ent}: linea {paso + 1}")
            else:
                ses.dlg_ent = None
                # Viaje aplazado: el traslado que dejo pedido una opcion del
                # dialogo se hace AHORA, cuando el cuadro se cierra. Es el
                # orden del servidor real: 10127, cierre, y despues el
                # cambio de mapa.
                # Hablar con Michael desbloquea el segundo dialogo de los
                # cuatro Angeles de faccion.
                _viaje = getattr(ses, 'viaje_pendiente', None)
                if _viaje and ses.personaje:
                    ses.viaje_pendiente = None
                    _st, _tile, _nom_dest = _viaje
                    _cerrar_viaje(ses, addr, _st, _tile, _nom_dest)
                    return
                # Fin de dialogo en Guide Palace (stage 51):
                if ses.personaje and ses.personaje.stage == MAPA_DEL_TUTORIAL:
                    if ent == 19:
                        ultimo_id = struct.unpack_from('<I', g[-1], 0)[0] if g else 0
                        if ultimo_id == 5005:
                            # Fin de tramo 0 -> abrir ventana de seleccion de clase (0x001D kind=12)
                            pkg_prof = struct.pack('<HIBBII', 0x001D, ent, 1, 12, 0, 0)
                            ses.enviar(pkg_prof)
                            log.info(f"[{addr}] Raphael: fin tramo 0 -> abierta ventana de seleccion de clase")
                        elif ultimo_id == 5018:
                            # Fin de fase de equipo
                            ses.personaje.tutorial = 1
                            if getattr(ses, 'usuario', None):
                                cuentas.guardar_tutorial(ses.usuario, ses.personaje.char_id, 1)
                            log.info(f"[{addr}] Raphael: fin fase de equipo (etapa 1)")
                        elif ultimo_id == 5043:
                            # Fin de fase de compra de bienes -> dar 10 de oro
                            ses.personaje.tutorial = 2
                            if getattr(ses, 'usuario', None):
                                cuentas.guardar_tutorial(ses.usuario, ses.personaje.char_id, 2)
                            if getattr(ses, 'oro', 0) < 10:
                                ses.oro = 10
                                ses.personaje.oro = 10
                                import clases as _cls
                                import inventario as _iv
                                bars, max_pts = _max_sp_info(ses.personaje)
                                ses.enviar(struct.pack('<HIBBI', 0x0013, ses.personaje.entity_id, 1, 6, 10),
                                           _cls.aviso("10 Gold", tipo=0, msg_id=_cls.MSG_PAGO),
                                           _iv.completo(ses.personaje.char_id, _con_oro(ses)),
                                           _iv.stats(ses.inventario, ses.personaje.habilidades,
                                                     hp=ses.personaje.hp, hp_max=ses.personaje.hp_max,
                                                     mp=ses.personaje.mp, mp_max=ses.personaje.mp_max,
                                                     oro=10, sp=getattr(ses, 'sp', None), sp_max=bars))
                                if getattr(ses, 'usuario', None):
                                    cuentas.guardar_oro(ses.usuario, ses.personaje.char_id, 10)
                            log.info(f"[{addr}] Raphael: fin etapa 2 -> 10 de oro otorgados")
                        elif ultimo_id in (5047, 5054):
                            # Fin de tramo 3 (examen completado) -> consumir examen y teletransportar a Fighting Palace (57)
                            slot_1386 = next((s for s, it in ses.inventario.items() if it == 1386), None)
                            if slot_1386 is not None:
                                del ses.inventario[slot_1386]
                            import inventario as _iv
                            import clases as _cls
                            ses.enviar(_iv.completo(ses.personaje.char_id, _con_oro(ses)))
                            ses.personaje.tutorial = 3
                            if getattr(ses, 'usuario', None):
                                cuentas.guardar_inventario(ses.usuario, ses.personaje.char_id, ses.inventario,
                                   _cantidades(ses))
                                cuentas.guardar_tutorial(ses.usuario, ses.personaje.char_id, 3)
                            _sincronizar_cambio_mapa(ses, 57, 216, 37)
                            log.info(f"[{addr}] Raphael: examen completado -> teletransportado a Fighting Palace (57)")
                        else:
                            log.info(f"[{addr}] Raphael: dialogo terminado (ultimo_id={ultimo_id})")
                    else:
                        log.info(f"[{addr}] dialogo con la entidad {ent} terminado")
                else:
                    log.info(f"[{addr}] dialogo con la entidad {ent} terminado")
            return

        if opcode == 0x0007 and ses.rol == 'mundo' and cuerpo:
            log.debug(f"[{addr}] se gira hacia la direccion {cuerpo[0]}")
            return

        # --- Acciones de personaje: Sentarse / Levantarse con tecla Insert (0x0016) ---
        if opcode == 0x0016 and ses.rol == 'mundo' and len(cuerpo) >= 5:
            # [u1 accion][u4 parametro]. Antes se leia un u32 desde el offset
            # 0, que da bien para las acciones chicas (2 revivir, 4 sentarse)
            # porque los bytes altos son cero, pero rompe la 0x0c.
            accion = cuerpo[0]
            parametro = struct.unpack_from('<I', cuerpo, 1)[0]
            if accion == 0x0C and ses.personaje and not getattr(ses, 'muerto', False):
                # ATAQUE BASICO. El cliente NO manda 0x0006 para pegar sin
                # habilidad ni espera a que se le conteste un clic: manda este
                # 0x0016 y lo repite solo cada ~1,5 s mientras dure el combate.
                # Medido en Celestia, mundo_201655_173169 t=40.4.
                import combate as _cb5
                self.manejar(ses, 0x0006, m, d, addr,
                             struct.pack('<HI', _cb5.ATAQUE_NORMAL, parametro))
                return
            if accion == 2 and ses.personaje and getattr(ses, 'muerto', False):
                # "Return to Angel Lyceum to revive". La ventana la abre el
                # cliente al morir y contesta con este 0x0016 [02 00 00 00 00];
                # el servidor solo tiene que revivir y cambiar el mapa.
                # Medido en Celestia, mundo_190339_977913 t=684.51.
                p2 = ses.personaje
                rev_x = getattr(p2, 'checkpoint_x', 0) or REVIVIR_LYCEUM[0]
                rev_y = getattr(p2, 'checkpoint_y', 0) or REVIVIR_LYCEUM[1]
                p2.hp = _vida_max(p2)
                p2.mp = _mana_max(p2)
                p2.stage = getattr(p2, 'checkpoint_stage', 0) or 41
                p2.tile_x, p2.tile_y = rev_x, rev_y
                ses.muerto = False
                _sincronizar_cambio_mapa(ses, p2.stage, rev_x, rev_y)
                if getattr(ses, 'usuario', None):
                    cuentas.guardar_progreso(ses.usuario, p2.char_id,
                                             p2.nivel, p2.exp, p2.hp, p2.mp)
                log.info(f"[{addr}] revive en stage {p2.stage} ({rev_x},{rev_y})")
                return
            if accion == 4 and ses.personaje:
                yo = ses.personaje.entity_id
                ses.sentado = not getattr(ses, 'sentado', False)
                act_code = 8 if ses.sentado else 0
                ses.enviar(struct.pack('<HIII', 0x000A, yo, 0, act_code))
                log.info(f"[{addr}] personaje {'se sento' if ses.sentado else 'se levanto'} (accion={act_code})")
                return

        if opcode == 0x0004 and d:
            ses.ultimo_movimiento = time.time()
            if getattr(ses, 'sentado', False):
                ses.sentado = False
                if ses.personaje:
                    ses.enviar(struct.pack('<HIII', 0x000A, ses.personaje.entity_id, 0, 0))
            MOVE = Msg.registry[(0x0005, 's2c', '*')]
            ACK = Msg.registry[(0x006D, 's2c', '*')]
            # RUTA VACIA: el cliente avisa de que esta parado y no tiene por
            # donde salir. Antes se salia de aqui sin contestar nada y el
            # cliente se quedaba esperando el acuse para siempre: eso era el
            # "stuck" que solo se arreglaba reconectando. El acuse va igual.
            if not d.get('path'):
                ses.enviar(ACK.build())
                if ses.personaje:
                    ses.personaje.tile_x = d['cur_x'] // 32
                    ses.personaje.tile_y = d['cur_y'] // 32
                log.warning(f"[{addr}] el cliente dice que no puede moverse "
                            f"desde ({d['cur_x'] // 32},{d['cur_y'] // 32})")
                return
            # EL PRIMER TRAMO, NO EL ULTIMO. El cliente manda la ruta entera
            # ya esquivada -- con sus curvas para rodear agua y acantilados --
            # y espera que se le confirme tramo a tramo. Confirmando el ultimo
            # se le mandaba en LINEA RECTA hasta el final, cortando por encima
            # del agua y del vacio; al terminar quedaba dentro de una zona
            # intransitable, desde donde su buscador de rutas ya no encontraba
            # salida y empezaba a mandar rutas vacias. Por eso se trababa
            # siempre en los puentes y en las orillas.
            # Medido en Celestia: de 325 rutas de dos o mas tramos, en 291 el
            # servidor devuelve el PRIMER waypoint y en NINGUNA el ultimo.
            dst = d['path'][0]
            ses.enviar(ACK.build(),
                       MOVE.build(entity_id=ses.entity_id or 1001,
                                  cur_x=d['cur_x'], cur_y=d['cur_y'],
                                  dst_x=dst['x'], dst_y=dst['y'],
                                  speed=_velocidad_de(ses)))
            # Anotar donde queda. Las coordenadas del cliente van en pixeles y
            # el tile mide 32: 2640 -> 82 y 2672 -> 83, que es justo el punto
            # de aparicion de Guide Palace. Se guarda al desconectar, no en
            # cada paso, para no escribir en disco varias veces por segundo.
            if ses.personaje:
                _ox, _oy = d['cur_x'] // 32, d['cur_y'] // 32
                # MOVIMIENTO EN VUELO DEL MAPA ANTERIOR. El viaje puede
                # dispararse por temporizador -- el portal que se arma al
                # terminar el paso --, no solo al contestar un paquete, asi
                # que los movimientos que el cliente ya tenia mandados llegan
                # DESPUES del cambio de mapa y traen casillas del mapa viejo.
                # Aceptandolos se pisaba la posicion recien puesta: el
                # personaje acababa en el stage nuevo con la casilla del
                # anterior. Asi es como quedo en Jade Vale (stage 13) con la
                # (6,241), que es el tornado de Mushroom Forest, fuera de la
                # zona jugable y sin poder moverse.
                _dt = time.time() - getattr(ses, 'mapa_cambiado_en', 0)
                _lejos = max(abs(_ox - (ses.personaje.tile_x or 0)),
                             abs(_oy - (ses.personaje.tile_y or 0)))
                if _dt < 3.0 and _lejos > 15:
                    log.info(f"[{addr}] descartado un movimiento del mapa "
                             f"anterior: dice estar en ({_ox},{_oy}) y acaba "
                             f"de llegar a ({ses.personaje.tile_x},"
                             f"{ses.personaje.tile_y})")
                    return
                ses.personaje.tile_x = dst['x'] // 32
                ses.personaje.tile_y = dst['y'] // 32
                _armar_portal_al_llegar(
                    ses, addr, (ses.personaje.tile_x, ses.personaje.tile_y),
                    max(abs(ses.personaje.tile_x - _ox),
                        abs(ses.personaje.tile_y - _oy)))

                # Si el movimiento termina LEJOS del objetivo, se lo suelta:
                # atacabas, te ibas, y al pararte el personaje seguia pegandole
                # al bicho. Caminar HACIA el no lo suelta, que es lo que pasa
                # cuando uno clica un enemigo lejano y se acerca.
                _obj = getattr(ses, 'objetivo_actual', None)
                if _obj:
                    _bi = (getattr(ses, 'monstruos', None) or {}).get(_obj)
                    if _bi is not None:
                        _alc = _cb_alcance(ses)
                        _dd = max(abs(_bi.tile_x - ses.personaje.tile_x),
                                  abs(_bi.tile_y - ses.personaje.tile_y))
                        if _dd > _alc + 1:
                            ses.objetivo_actual = None
                            log.info(f"[{addr}] objetivo soltado: te alejaste a "
                                     f"{_dd} casillas del {_bi.nombre}")
                import clases as _cl3
                # Portales: un solo camino, el de plantillas/portales.json.
                # Antes habia otro bloque con areas enormes (tx<=32 y ty>=126
                # es un cuadrante entero del Lyceum) que abria el dialogo con
                # val=4, o sea CON retrato de NPC, y que ademas teletransportaba
                # sin preguntar desde media pantalla de distancia.
                # Se evalua con la posicion ACTUAL que informa el cliente,
                # no con el destino del movimiento: si no, al hacer clic hacia
                # el tornado el dialogo saltaba de inmediato, con el personaje
                # todavia a media pantalla.
                # Se mira el portal en la casilla DE LLEGADA y, si ahi no
                # hay, en la de salida. Antes solo se miraba la de salida:
                # si hacias clic directo encima del tornado no pasaba nada
                # hasta que te movieras otra vez. Mirar solo la de llegada
                # tampoco sirve -- por eso estaba asi -- porque al clicar
                # hacia el tornado desde lejos el dialogo saltaba de
                # inmediato, con el personaje todavia a media pantalla; eso
                # lo cubre el radio 1, que exige estar encima.
                # SOLO la casilla donde el cliente dice que esta AHORA. Se
                # probo mirar tambien la de destino para que funcionara
                # clicando encima del tornado, y fue un error: al clicarlo
                # desde lejos el viaje salia en el acto, sin caminar. El
                # cliente informa su posicion mientras camina, asi que al
                # pisarlo de verdad llega igual.
                cur_tx, cur_ty = d['cur_x'] // 32, d['cur_y'] // 32
                dst_tx, dst_ty = dst['x'] // 32, dst['y'] // 32
                _por = _portal_en(ses.personaje.stage, cur_tx, cur_ty)
                if not _por:
                    dist_to_dst = max(abs(cur_tx - dst_tx), abs(cur_ty - dst_ty))
                    if dist_to_dst <= 3:
                        _por = _portal_en(ses.personaje.stage, dst_tx, dst_ty)

                if time.time() - getattr(ses, 'mapa_cambiado_en', 0) > 2.0:
                    ses.portal_pisado = None
                _antes = getattr(ses, 'portal_pisado', None)
                _ahora = tuple(_por['tile']) if _por else None
                ses.portal_pisado = _ahora
                if _ahora is not None and _ahora == _antes:
                    _por = None       # ya estaba encima: no reabrir
                if _por is not None and not _por.get('preguntar'):
                    # Vuelta directa: acercarse y listo, sin menu.
                    _cancelar_portal_armado(ses)
                    _viajar_por_portal(ses, addr, _por)
                    return
                if _por is not None:
                    import dialogos as _dlg
                    _cfg = _portales()
                    # Cada tornado puede traer su propio menu: el del
                    # Lyceum al West ofrece A1..A5 del West y el del
                    # East los suyos.
                    _ops = _por.get('opciones') or _cfg['opciones']
                    # El mensaje tambien puede ser propio del portal: el
                    # del Lyceum usa el 5801 global, pero el nudo de
                    # Teddy Amusement trae el suyo, el 513008.
                    sub = _dlg.armar_linea(_por.get('msg') or _cfg['msg'],
                                           0, _ops)
                    ses.dlg_ent = _por['entity']
                    ses.dlg_guion = [sub[2:]]
                    ses.dlg_paso = 1
                    ses.dlg_val = 0
                    ses.dlg_portal = _por
                    ses.enviar(sub)
                    log.info(f"[{addr}] portal en {_por['tile']}: pregunta destino")
            log.debug(f"[{addr}] movimiento ({d['cur_x']},{d['cur_y']}) -> "
                      f"({dst['x']},{dst['y']}) via {d['n']} waypoints")

    async def archivos(self, reader, writer):
        """File server (fport en server.xml). Todavia no responde: graba lo que
        el cliente pide, que es justo lo que hace falta para implementarlo."""
        addr = writer.get_extra_info('peername')
        log.info(f"[archivos {addr}] conectado")
        grab = Grabador(addr, self.fport, bytes(16))
        import archivos
        from framing import HDR, decode_header, submessages, build_frame, pack_submessages, SEQ_HELLO
        # El servidor de archivos tambien manda HELLO al conectar. Se comprobo
        # contra una captura real: frame 0 con seq=0xFFFF y 134 bytes, igual
        # que login y mundo. El mio no mandaba nada hasta que le pedian algo,
        # asi que el cliente esperaba un handshake que nunca llegaba.
        _ph = pathlib.Path(__file__).parent / 'plantillas' / 'hello_archivos.bin'
        if _ph.exists():
            _hf = build_frame(_ph.read_bytes(), SEQ_HELLO)
            grab.salida(_hf)
            writer.write(_hf)
            await writer.drain()
            log.info("[archivos %s] HELLO enviado (%s B)", addr, len(_hf))
        buf, seq = bytearray(), 1
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                grab.entrada(data)
                buf.extend(data)
                while len(buf) >= HDR:
                    h = decode_header(buf, 0)
                    if h['length'] == 0 or h['length'] > 0x10000:
                        del buf[0]; continue
                    if len(buf) < h['wire']:
                        break
                    cuerpo = bytes(buf[HDR:h['wire']]); del buf[:h['wire']]
                    for op, b in submessages(cuerpo[:h['length']])[0]:
                        nom = archivos.nombre_pedido(b)
                        if not nom:
                            # El binario dice que la direccion del MUNDO sale
                            # de +96/+112 de la entrada de servidor, que es el
                            # par fip/fport del server.xml -- o sea ESTE puerto.
                            # Si llega algo que no es un pedido de archivo,
                            # probablemente sea la sesion de mundo.
                            log.warning(f"[archivos {addr}] 0x{op:04X} {len(b)}B "
                                        f"NO es pedido de archivo: {b[:32].hex(' ')}")
                            log.warning(f"[archivos {addr}] ¿es la sesion de MUNDO "
                                        f"llegando por fport?")
                            continue
                        log.info(f"[archivos {addr}] 0x{op:04X} pide '{nom}'")
                        resp = build_frame(
                            pack_submessages([archivos.respuesta_avatar(b)]), seq)
                        seq = 1 if seq >= 0x7FFE else seq + 1
                        grab.salida(resp)
                        writer.write(resp)
                        await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            base, nc, ns = grab.cerrar()
            log.info(f"[archivos {addr}] desconectado -> logs/sesiones/{base}_*.bin")
            writer.close()

    async def correr(self):
        import functools
        srv = await asyncio.start_server(
            functools.partial(self.cliente, rol='login'), self.host, self.port)
        log.info(f"servidor de LOGIN en {self.host}:{self.port}")
        wsrv = await asyncio.start_server(
            functools.partial(self.cliente, rol='mundo'), self.host, self.wport)
        log.info(f"servidor de MUNDO en {self.host}:{self.wport}")
        tareas = [srv.serve_forever(), wsrv.serve_forever()]
        try:
            fsrv = await asyncio.start_server(self.archivos, self.host, self.fport)
            log.info(f"servidor de archivos en {self.host}:{self.fport}")
            tareas.append(fsrv.serve_forever())
        except OSError as e:
            log.warning(f"no se pudo abrir el puerto de archivos {self.fport}: {e}")
        log.info("server.xml del cliente ya apunta aca (ip=127.0.0.1 port=16768)")

        # SEÑUELOS: el binario muestra que la ip y el puerto del mundo NO
        # salen del redirect sino de la lista de servidores (sub_51A370 los
        # lee de +64 y +80 de una entrada de 372 bytes). Para saber a donde
        # intenta ir el cliente de verdad, se abren los puertos vecinos y se
        # registra cualquier conexion.
        async def senuelo(r, w, p):
            a = w.get_extra_info('peername')
            log.warning("*** EL CLIENTE CONECTO AL PUERTO %s (desde %s) ***", p, a)
            try:
                d = await asyncio.wait_for(r.read(4096), 3)
                log.warning("    mando %s bytes: %s", len(d), d[:48].hex(' ') if d else '(nada)')
            except asyncio.TimeoutError:
                log.warning("    se quedo esperando respuesta")
            w.close()

        usados = {self.port, self.wport, self.fport}
        # Se agregan los valores POR DEFECTO que trae el binario
        #   dword_91AA6C = 6768   y   dword_91AA80 = 1234
        # mas los puertos de mundo vistos en capturas reales.
        for pu in (list(range(16760, 16790)) + [1234, 6768, 21237, 21239]
                   + list(range(24125, 24160)) + list(range(29995, 30012))):
            if pu in usados:
                continue
            try:
                # Escuchar en TODAS las interfaces, no solo loopback: si el
                # cliente intenta conectar a la IP de red en vez de a
                # 127.0.0.1, un senuelo atado solo a loopback no lo ve y el
                # cliente se queda colgado esperando (que es lo que pasa).
                sx = await asyncio.start_server(
                    functools.partial(senuelo, p=pu), '0.0.0.0', pu)
                tareas.append(sx.serve_forever())
            except OSError:
                pass
        log.info("senuelos abiertos en los puertos vecinos")
        log.info("las sesiones se graban en logs/sesiones/ para poder analizarlas")
        await asyncio.gather(*tareas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=16768)
    ap.add_argument('--wport', type=int, default=16769,
                    help='puerto del servidor de mundo (destino del redirect)')
    ap.add_argument('--fport', type=int, default=21238,
                    help='puerto del servidor de archivos (fport en server.xml)')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    try:
        asyncio.run(Servidor(a.host, a.port, a.fport, a.wport).correr())
    except KeyboardInterrupt:
        log.info("detenido")


if __name__ == '__main__':
    main()
