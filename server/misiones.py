"""
Motor de misiones (Quest System) para Angels Online.
Carga datos desde server/plantillas/misiones.json y coordina
la aceptacion, avance, guardado y entrega de recompensas.
"""
import json
import logging
import pathlib
import time
import struct

import clases as _cl
import cuentas
import combate as _cb

log = logging.getLogger('misiones')

RUTA_MISIONES_JSON = pathlib.Path(__file__).parent / 'plantillas' / 'misiones.json'
_MISIONES = None

# Mapeo de misiones clave de las 4 ciudades
QUEST_REGISTRO = {
    3: 127,    # Aurora City
    26: 128,   # Dark City
    38: 129,   # Iron Castle
    29: 130,   # Breeze Woods
}

QUEST_CONOCER = {
    3: 133,    # Knowing Aurora City (Explorer Lim)
    26: 134,   # Knowing Dark City (Risker Zalfer)
    38: 135,   # Knowing Iron Castle (Pioneer Ocadon)
    29: 136,   # Knowing Breeze Woods (Explorer Gulin)
}

QUEST_NIVEL = {
    3: 137,    # Reaching higher level (Aurora)
    26: 138,   # Reaching higher level (Dark City)
    38: 139,   # Reaching higher level (Iron Castle)
    29: 140,   # Reaching higher level (Breeze Woods)
}

# NPCs guias de ciudad (entity_id exacto en los mapas 3, 26, 38, 29)
GUIAS_CIUDAD = {
    121633: (3,  133, 'Explorer Lim',    20010),
    121914: (26, 134, 'Risker Zalfer',   30010),
    122110: (38, 135, 'Pioneer Ocadon',  40010),
    121967: (29, 136, 'Explorer Gulin',  50010),
}

# Paradise Angels en las 4 ciudades (dan inicio a la cadena de Eden, Quest 142)
PARADISE_ANGELS = {
    121671: 3,   # Aurora City
    121905: 26,  # Dark City
    122154: 38,  # Iron Castle
    121990: 29,  # Breeze Woods
}

QUEST_EDEN_NEEDS_HELP = 142
QUEST_FINAL_LINE = 143

# Mapeo de misiones con objetivos de caceria:
# (qid, paso): dict con monstruos, cantidad, siguiente_paso, etc.
OBJETIVOS_CACERIA = {
    (142, 2): {
        'monstruos': (7007, 7008),  # Young Witch, Crystal Envoy
        'cantidad': 100,
        'siguiente_paso': 3,
        'nombre_objetivo': 'Young Witch / Crystal Envoy',
        'aviso_fin': 'Quest [Eden Needs Help]: Report to Blocks Envoy in Mushroom Village.',
    },
    (143, 1): {
        'monstruos': (7016, 7017),  # Fire Ball Baby, Flower Thorn Baby
        'cantidad': 100,
        'siguiente_paso': 2,
        'nombre_objetivo': 'Fire Ball Baby / Flower Thorn Baby',
        'aviso_fin': 'Quest [The Final Line]: Report to Guerrilla Leader Mola.',
    },
    (143, 3): {
        'monstruos': (7020,),        # Dog Fighter
        'cantidad': 100,
        'siguiente_paso': 4,
        'nombre_objetivo': 'Dog Fighter',
        'aviso_fin': 'Quest [The Final Line]: Report to Guerrilla Leader Mola.',
    },
}


def _cargar_misiones() -> dict:
    global _MISIONES
    if _MISIONES is not None:
        return _MISIONES
    _MISIONES = {}
    if RUTA_MISIONES_JSON.exists():
        try:
            raw = json.loads(RUTA_MISIONES_JSON.read_text(encoding='utf-8'))
            for f in raw.get('filas', []):
                qid = f.get('id')
                if qid is not None:
                    _MISIONES[int(qid)] = f
        except Exception as e:
            log.warning(f"Error cargando {RUTA_MISIONES_JSON}: {e}")
    return _MISIONES


def info_mision(qid: int) -> dict:
    return _cargar_misiones().get(int(qid), {})


def nombre_mision(qid: int) -> str:
    m = info_mision(qid)
    return m.get('nombre') or _cl.nombre_de_quest(qid)


def estado_mision(p, qid: int):
    """Devuelve (activo: bool, paso: int, completada: bool)"""
    if not p or not getattr(p, 'quests', None):
        return (False, 0, False)
    for q, pa in p.quests:
        if q == qid:
            # En AO: paso >= 1 tras cumplir entrega indica completada,
            # pero algunas misiones multinivel usan paso como progreso.
            return (True, pa, pa >= 1)
    return (False, 0, False)


def tiene_mision(p, qid: int) -> bool:
    if not p or not getattr(p, 'quests', None):
        return False
    return any(q == qid for q, _ in p.quests)


def mision_completada(p, qid: int) -> bool:
    if not p or not getattr(p, 'quests', None):
        return False
    for q, pa in p.quests:
        if q == qid and pa >= 1:
            return True
    return False


def aceptar_mision(ses, qid: int) -> bool:
    """Otorga la mision al jugador y la sincroniza con el cliente."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False
    if tiene_mision(p, qid):
        return False

    p.quests = list(p.quests or []) + [(qid, 0)]
    char_id = p.char_id
    nom = nombre_mision(qid)

    # 0x0022: alta de mision en paso 0
    pkg_m = _cl.mision(char_id, qid, 0, 0)
    # 0x000D: cartel amarillo "You accept the quest [X]"
    pkg_av = _cl.aviso(nom, tipo=0, msg_id=_cl.MSG_QUEST)

    ses.enviar(pkg_m, pkg_av)
    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, char_id, p.quests)

    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} acepto mision {qid} '{nom}'")
    return True


def avanzar_paso(ses, qid: int, nuevo_paso: int) -> bool:
    """Actualiza el paso de la mision y lo sincroniza con el cliente."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False

    nueva_lista = []
    encontrada = False
    for q, pa in (p.quests or []):
        if q == qid:
            nueva_lista.append((q, nuevo_paso))
            encontrada = True
        else:
            nueva_lista.append((q, pa))

    if not encontrada:
        nueva_lista.append((qid, nuevo_paso))

    p.quests = nueva_lista
    char_id = p.char_id
    nom = nombre_mision(qid)

    pkg_m = _cl.mision(char_id, qid, nuevo_paso, 0)
    pkg_av = _cl.aviso(f"{nom} ({nuevo_paso})", tipo=0, msg_id=_cl.MSG_QUEST)

    ses.enviar(pkg_m, pkg_av)
    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, char_id, p.quests)

    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} avanzo mision {qid} '{nom}' al paso {nuevo_paso}")
    return True


def completar_mision(ses, qid: int, exp: int = 0, oro: int = 0,
                     items: list = None, creditos_honor: int = 0) -> bool:
    """Marca la mision como completada, entrega recompensas y persiste."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False

    sello = int(time.time())
    nueva_lista = []
    encontrada = False
    for q, pa in (p.quests or []):
        if q == qid:
            nueva_lista.append((q, 1))
            encontrada = True
        else:
            nueva_lista.append((q, pa))

    if not encontrada:
        nueva_lista.append((qid, 1))

    p.quests = nueva_lista
    char_id = p.char_id
    nom = nombre_mision(qid)

    # 1. Paquete de mision completada (0x0022 con paso=1 y sello de tiempo)
    pkg_m = _cl.mision(char_id, qid, 1, sello)

    # 2. Cartel de aviso
    pkg_av = _cl.aviso(f"Quest [{nom}] Completed!", tipo=0, msg_id=492)
    envios = [pkg_m, pkg_av]

    # 3. Oro de recompensa
    if oro > 0:
        ses.oro = getattr(ses, 'oro', 0) + oro
        p.oro = ses.oro
        # 0x001B de oro
        envios.append(struct.pack('<HII', 0x001B, 0, ses.oro))
        envios.append(_cl.aviso(str(oro), tipo=0, msg_id=_cl.MSG_PAGO))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_oro(ses.usuario, char_id, ses.oro)

    # 4. Experiencia de recompensa
    if exp > 0:
        p.exp = getattr(p, 'exp', 0) + exp
        exp_actual_ui, _ = _cb.exp_para_barra(getattr(p, 'nivel', 1), p.exp)
        eid = getattr(p, 'entity_id', char_id)
        envios.append(struct.pack('<HIBBQ', 0x001D, eid, 1, 32, max(0, int(exp_actual_ui))))
        envios.append(_cl.aviso(str(exp), tipo=0, msg_id=_cl.MSG_EXP))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_progreso(ses.usuario, char_id, p.nivel, p.exp)

    # 5. Creditos de Rango / Honor
    if creditos_honor > 0:
        nuevos_cred = getattr(p, 'creditos', 0) + creditos_honor
        p.creditos = nuevos_cred
        envios.append(struct.pack('<HIBBI', 0x0013, p.entity_id, 1, 0x3d, nuevos_cred))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_rango(ses.usuario, char_id, getattr(p, 'rango', 1), nuevos_cred)

    # 6. Items de recompensa (si vienen como lista de item_ids o (ranura, item_id))
    if items:
        import inventario as _inv
        for it in items:
            item_id = it if isinstance(it, int) else it[1]
            # Buscar primera casilla libre en inventario
            ranura_libre = None
            inv = getattr(ses, 'inventario', {}) or {}
            for r in range(20, 60):
                if r not in inv or inv[r] == 0:
                    ranura_libre = r
                    break
            if ranura_libre is not None:
                inv[ranura_libre] = item_id
                ses.inventario = inv
                pkg_item = struct.pack('<HII', 0x001B, ranura_libre, item_id)
                envios.append(pkg_item)
                log.info(f"Entregado item de quest {item_id} en casilla {ranura_libre}")
        if getattr(ses, 'usuario', None):
            cuentas.guardar_inventario(ses.usuario, char_id, getattr(ses, 'inventario', {}),
                                       getattr(ses, 'cantidades', {}))

    ses.enviar(*envios)

    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, char_id, p.quests)

    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} completo mision {qid} '{nom}'! (Exp +{exp}, Oro +{oro})")
    return True


def registrar_baja_monstruo(ses, npc_type: int) -> bool:
    """Verifica si el monstruo derrotado suma para alguna mision activa del jugador."""
    p = getattr(ses, 'personaje', None)
    if not p or not getattr(p, 'quests', None):
        return False

    actualizado = False
    if not hasattr(ses, 'quest_kills'):
        ses.quest_kills = {}

    for (qid, paso), obj in OBJETIVOS_CACERIA.items():
        for q, pa in p.quests:
            if q == qid and pa == paso:
                if npc_type in obj['monstruos']:
                    clave = (qid, paso)
                    cnt = ses.quest_kills.get(clave, 0) + 1
                    ses.quest_kills[clave] = cnt
                    actualizado = True
                    nom_obj = obj['nombre_objetivo']
                    req = obj['cantidad']
                    if cnt % 10 == 0 or cnt == req:
                        ses.enviar(_cl.aviso(f"Defeated {nom_obj} ({cnt}/{req})", tipo=0, msg_id=_cl.MSG_QUEST))
                    if cnt >= req:
                        avanzar_paso(ses, qid, obj['siguiente_paso'])
                        if obj.get('aviso_fin'):
                            ses.enviar(_cl.aviso(obj['aviso_fin'], tipo=0, msg_id=_cl.MSG_QUEST))
                        log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} completo caceria de {nom_obj} ({cnt}/{req}) para mision {qid}")
    return actualizado
