"""
Motor de misiones (Quest System) para Angels Online.
Carga datos desde server/plantillas/misiones_completas.json y coordina
la aceptacion, avance, cacerias, recolecciones, conversaciones,
guardado y entrega de recompensas para las 1,489 misiones del juego.
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

RUTA_MISIONES_COMPLETAS = pathlib.Path(__file__).parent / 'plantillas' / 'misiones_completas.json'
RUTA_MISIONES_JSON = pathlib.Path(__file__).parent / 'plantillas' / 'misiones.json'

_DB = None
_MISIONES = None
_CACERIAS = None
_RECOLECCIONES = None
_NPC_INICIO = None
_NPC_PASOS = None
_REPETIBLES = None

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

# Mapeo de misiones con objetivos de caceria clasicos (compatibilidad)
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

# Mapas de instancia/quest especiales conocidos
QUEST_MAPAS_INSTANCIA = {
    (123, 1): 244,  # Training Palace
    (124, 1): 244,  # Training Palace
    (125, 1): 244,  # Training Palace
    (126, 1): 244,  # Training Palace
    (162, 1): 158,  # Poker Castle
    (163, 1): 158,  # Poker Castle
}


def _cargar_db():
    global _DB, _MISIONES, _CACERIAS, _RECOLECCIONES, _NPC_INICIO, _NPC_PASOS, _REPETIBLES
    if _DB is not None:
        return
    _MISIONES = {}
    _CACERIAS = {}
    _RECOLECCIONES = {}
    _NPC_INICIO = {}
    _NPC_PASOS = {}
    _REPETIBLES = set()

    if RUTA_MISIONES_COMPLETAS.exists():
        try:
            _DB = json.loads(RUTA_MISIONES_COMPLETAS.read_text(encoding='utf-8'))
            for k, m in _DB.get('misiones', {}).items():
                _MISIONES[int(k)] = m
            _CACERIAS = _DB.get('cacerias', {})
            _RECOLECCIONES = _DB.get('recolecciones', {})
            _NPC_INICIO = _DB.get('npc_inicio', {})
            _NPC_PASOS = _DB.get('npc_pasos', {})
            _REPETIBLES = set(_DB.get('repetibles', []))
            log.info(f"Cargadas {len(_MISIONES)} misiones completas desde misiones_completas.json")
            return
        except Exception as e:
            log.warning(f"Error cargando {RUTA_MISIONES_COMPLETAS}: {e}")

    # Fallback al archivo basico si no existe el completo
    if RUTA_MISIONES_JSON.exists():
        try:
            raw = json.loads(RUTA_MISIONES_JSON.read_text(encoding='utf-8'))
            for f in raw.get('filas', []):
                qid = f.get('id')
                if qid is not None:
                    _MISIONES[int(qid)] = f
        except Exception as e:
            log.warning(f"Error cargando {RUTA_MISIONES_JSON}: {e}")


def _cargar_misiones() -> dict:
    _cargar_db()
    return _MISIONES or {}


def info_mision(qid: int) -> dict:
    return _cargar_misiones().get(int(qid), {})


def nombre_mision(qid: int) -> str:
    m = info_mision(qid)
    return m.get('nombre') or _cl.nombre_de_quest(qid)


def es_repetible(qid: int) -> bool:
    _cargar_db()
    if qid in _REPETIBLES:
        return True
    m = info_mision(qid)
    return bool(m.get('repetible', False))


def estado_mision(p, qid: int):
    """Devuelve (activo: bool, paso: int, completada: bool)"""
    if not p or not getattr(p, 'quests', None):
        return (False, 0, False)
    for q, pa in p.quests:
        if q == qid:
            m = info_mision(qid)
            pasos = m.get('pasos', [])
            total_pasos = len(pasos) if pasos else 1
            # Si pa >= 1 y es de 1 solo paso o pa > total_pasos: completada
            completada = (pa >= 1 and total_pasos <= 1) or (pa > total_pasos)
            return (True, pa, completada)
    return (False, 0, False)


def tiene_mision(p, qid: int) -> bool:
    if not p or not getattr(p, 'quests', None):
        return False
    return any(q == qid for q, _ in p.quests)


def mision_completada(p, qid: int) -> bool:
    if not p or not getattr(p, 'quests', None):
        return False
    for q, pa in p.quests:
        if q == qid:
            m = info_mision(qid)
            pasos = m.get('pasos', [])
            total_pasos = len(pasos) if pasos else 1
            if total_pasos <= 1:
                return pa >= 1
            return pa > total_pasos or pa == 999
    return False


def misiones_activas(p) -> list:
    """Devuelve lista de (qid, paso) que estan en progreso actualmente."""
    if not p or not getattr(p, 'quests', None):
        return []
    res = []
    for q, pa in p.quests:
        if not mision_completada(p, q):
            res.append((q, pa))
    return res


def obtener_paso_actual(p, qid: int) -> int:
    if not p or not getattr(p, 'quests', None):
        return 0
    for q, pa in p.quests:
        if q == qid:
            return pa
    return 0


def misiones_disponibles_npc(p, npc_nombre: str) -> list:
    """Devuelve la lista de IDs de misiones que este NPC puede ofrecer al personaje."""
    _cargar_db()
    if not npc_nombre:
        return []
    qids = _NPC_INICIO.get(npc_nombre.strip().lower(), [])
    disponibles = []
    for qid in qids:
        # Si ya la tiene activa, no se ofrece de nuevo
        st, pa, comp = estado_mision(p, qid)
        if st and not comp:
            continue
        # Si ya la completo: solo se ofrece si es repetible
        if comp and not es_repetible(qid):
            continue
        disponibles.append(qid)
    return disponibles


def aceptar_mision(ses, qid: int) -> bool:
    """Otorga la mision al jugador y la sincroniza con el cliente."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False
    
    st, pa, comp = estado_mision(p, qid)
    if st and not comp:
        return False  # Ya activa

    char_id = p.char_id
    nom = nombre_mision(qid)
    info = info_mision(qid)
    pasos = info.get('pasos', [])
    paso_inicial = 1 if len(pasos) > 1 else 0

    # Actualizar lista de quests del personaje
    nueva_lista = [item for item in (p.quests or []) if item[0] != qid]
    nueva_lista.append((qid, paso_inicial))
    p.quests = nueva_lista

    # 0x0022: alta de mision
    pkg_m = _cl.mision(char_id, qid, paso_inicial, 0)
    # 0x000D: cartel amarillo "You accept the quest [X]"
    pkg_av = _cl.aviso(nom, tipo=0, msg_id=_cl.MSG_QUEST)

    ses.enviar(pkg_m, pkg_av)
    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, char_id, p.quests)

    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} acepto mision {qid} '{nom}' (paso {paso_inicial})")
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
    """Marca la mision como completada, retira items requeridos, entrega recompensas y persiste."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False

    info = info_mision(qid)
    pasos = info.get('pasos', [])
    total_pasos = len(pasos) if pasos else 1
    # Marca de completado: 1 si es single step, o total_pasos + 1
    paso_completado = 1 if total_pasos <= 1 else (total_pasos + 1)

    sello = int(time.time())
    nueva_lista = []
    encontrada = False
    for q, pa in (p.quests or []):
        if q == qid:
            nueva_lista.append((q, paso_completado))
            encontrada = True
        else:
            nueva_lista.append((q, pa))

    if not encontrada:
        nueva_lista.append((qid, paso_completado))

    p.quests = nueva_lista
    char_id = p.char_id
    nom = nombre_mision(qid)

    # 1. Paquete de mision completada (0x0022 con paso completado y sello de tiempo)
    pkg_m = _cl.mision(char_id, qid, paso_completado, sello)

    # 2. Cartel de aviso
    pkg_av = _cl.aviso(f"Quest [{nom}] Completed!", tipo=0, msg_id=492)
    envios = [pkg_m, pkg_av]

    # 3. Eliminar items de quest segun borrar_items
    borrar_items = info.get('borrar_items', [])
    if borrar_items:
        import inventario as _inv
        inv = getattr(ses, 'inventario', {}) or {}
        cants = getattr(ses, 'cantidades', {}) or {}
        toco_inv = False
        for ranura, iid in list(inv.items()):
            if iid in borrar_items:
                _inv.vaciar_ranura(char_id, ranura)
                inv[ranura] = 0
                cants.pop(ranura, None)
                envios.append(struct.pack('<HII', 0x001B, ranura, 0))
                toco_inv = True
                log.info(f"Item de quest consumido: ID {iid} en ranura {ranura}")
        if toco_inv:
            ses.inventario = inv
            ses.cantidades = cants
            if getattr(ses, 'usuario', None):
                cuentas.guardar_inventario(ses.usuario, char_id, inv, cants)

    # 4. Recompensas por defecto si no vienen fijadas
    recomp = info.get('recompensa', {})
    if exp <= 0:
        exp = recomp.get('exp', 0)
    if oro <= 0:
        oro = recomp.get('oro', 0)
    if creditos_honor <= 0:
        creditos_honor = recomp.get('creditos', 0)

    # 5. Oro de recompensa
    if oro > 0:
        ses.oro = getattr(ses, 'oro', 0) + oro
        p.oro = ses.oro
        envios.append(struct.pack('<HII', 0x001B, 0, ses.oro))
        envios.append(_cl.aviso(str(oro), tipo=0, msg_id=_cl.MSG_PAGO))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_oro(ses.usuario, char_id, ses.oro)

    # 6. Experiencia de recompensa
    if exp > 0:
        p.exp = getattr(p, 'exp', 0) + exp
        exp_actual_ui, _ = _cb.exp_para_barra(getattr(p, 'nivel', 1), p.exp)
        eid = getattr(p, 'entity_id', char_id)
        envios.append(struct.pack('<HIBBQ', 0x001D, eid, 1, 32, max(0, int(exp_actual_ui))))
        envios.append(_cl.aviso(str(exp), tipo=0, msg_id=_cl.MSG_EXP))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_progreso(ses.usuario, char_id, p.nivel, p.exp)

    # 7. Creditos de Rango / Honor
    if creditos_honor > 0:
        nuevos_cred = getattr(p, 'creditos', 0) + creditos_honor
        p.creditos = nuevos_cred
        envios.append(struct.pack('<HIBBI', 0x0013, p.entity_id, 1, 0x3d, nuevos_cred))
        if getattr(ses, 'usuario', None):
            cuentas.guardar_rango(ses.usuario, char_id, getattr(p, 'rango', 1), nuevos_cred)

    # 8. Items de recompensa
    if items:
        import inventario as _inv
        inv = getattr(ses, 'inventario', {}) or {}
        for it in items:
            item_id = it if isinstance(it, int) else it[1]
            ranura_libre = None
            for r in range(20, 60):
                if r not in inv or inv[r] == 0:
                    ranura_libre = r
                    break
            if ranura_libre is not None:
                inv[ranura_libre] = item_id
                ses.inventario = inv
                pkg_item = struct.pack('<HII', 0x001B, ranura_libre, item_id)
                envios.append(pkg_item)
                log.info(f"Entregado item de recompensa {item_id} en casilla {ranura_libre}")
        if getattr(ses, 'usuario', None):
            cuentas.guardar_inventario(ses.usuario, char_id, getattr(ses, 'inventario', {}),
                                       getattr(ses, 'cantidades', {}))

    ses.enviar(*envios)

    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, char_id, p.quests)

    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} completo mision {qid} '{nom}'! (Exp +{exp}, Oro +{oro})")
    return True


def registrar_baja_monstruo(ses, npc_type: int, monster_name: str = None) -> bool:
    """Verifica si el monstruo derrotado suma para alguna mision activa del jugador."""
    _cargar_db()
    p = getattr(ses, 'personaje', None)
    if not p or not getattr(p, 'quests', None):
        return False

    actualizado = False
    if not hasattr(ses, 'quest_kills'):
        ses.quest_kills = {}

    m_nom_clean = monster_name.lower().strip() if monster_name else ''

    # 1. Comprobar diccionario clásico primero (compatibilidad)
    for (qid, paso), obj in OBJETIVOS_CACERIA.items():
        for q, pa in p.quests:
            if q == qid and pa == paso:
                if npc_type in obj['monstruos'] or (m_nom_clean and any(m in m_nom_clean for m in [obj['nombre_objetivo'].lower()])):
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

    # 2. Comprobar catálogo dinámico completo (_CACERIAS)
    for q, pa in p.quests:
        k_cac = f"{q}_{pa}"
        if k_cac in _CACERIAS:
            c_data = _CACERIAS[k_cac]
            req = c_data.get('cantidad', 1)
            token = c_data.get('token_id')
            m_ids = c_data.get('monstruo_ids', [])
            m_noms = c_data.get('monstruos', [])

            coincide = False
            if npc_type in m_ids or (token and npc_type == token):
                coincide = True
            elif m_nom_clean and any(mn in m_nom_clean or m_nom_clean in mn for mn in m_noms):
                coincide = True

            if coincide:
                clave = (q, pa)
                cnt = ses.quest_kills.get(clave, 0) + 1
                ses.quest_kills[clave] = cnt
                actualizado = True
                nom_obj = c_data.get('nombre_objetivo') or 'Target'
                if cnt % 10 == 0 or cnt == req:
                    ses.enviar(_cl.aviso(f"Defeated {nom_obj} ({cnt}/{req})", tipo=0, msg_id=_cl.MSG_QUEST))
                if cnt >= req:
                    sig = c_data.get('siguiente_paso', pa + 1)
                    avanzar_paso(ses, q, sig)
                    npc_ent = c_data.get('npc_entrega')
                    mapa_ent = c_data.get('mapa')
                    nom_q = nombre_mision(q)
                    if npc_ent:
                        ses.enviar(_cl.aviso(f"Quest [{nom_q}]: Report to {npc_ent} ({mapa_ent})!", tipo=0, msg_id=_cl.MSG_QUEST))
                    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} completo caceria de {nom_obj} ({cnt}/{req}) para mision {q}")

    return actualizado


def verificar_entrega_items(ses, qid: int, paso: int) -> bool:
    """Comprueba si el jugador tiene los items requeridos para el paso y los consume si es así."""
    _cargar_db()
    k_rec = f"{qid}_{paso}"
    if k_rec not in _RECOLECCIONES:
        return True

    r_data = _RECOLECCIONES[k_rec]
    req_items = r_data.get('items', [])
    if not req_items:
        return True

    inv = getattr(ses, 'inventario', {}) or {}
    cants = getattr(ses, 'cantidades', {}) or {}

    # 1. Verificar si cumple todos los requisitos
    for req in req_items:
        req_id = req.get('item_id')
        req_cnt = req.get('cantidad', 1)
        total_tenido = 0
        for r, iid in inv.items():
            if iid == req_id:
                total_tenido += cants.get(r, 1)
        if total_tenido < req_cnt:
            nom_q = nombre_mision(qid)
            ses.enviar(_cl.aviso(f"Quest [{nom_q}]: Missing items ({total_tenido}/{req_cnt})", tipo=0, msg_id=_cl.MSG_QUEST))
            return False

    # 2. Consumir los items
    import inventario as _inv
    for req in req_items:
        req_id = req.get('item_id')
        falta_quitar = req.get('cantidad', 1)
        for r in list(inv.keys()):
            if inv.get(r) == req_id and falta_quitar > 0:
                act = cants.get(r, 1)
                if act <= falta_quitar:
                    falta_quitar -= act
                    _inv.vaciar_ranura(getattr(ses.personaje, 'char_id', 0), r)
                    inv[r] = 0
                    cants.pop(r, None)
                    ses.enviar(struct.pack('<HII', 0x001B, r, 0))
                else:
                    cants[r] = act - falta_quitar
                    falta_quitar = 0

    ses.inventario = inv
    ses.cantidades = cants
    if getattr(ses, 'usuario', None):
        cuentas.guardar_inventario(ses.usuario, ses.personaje.char_id, inv, cants)

    return True


def interactuar_npc(ses, npc_nombre: str, entidad: int = 0) -> tuple:
    """
    Gestiona la conversacion o entrega de misiones con un NPC.
    Devuelve (procesado: bool, tipo: str, datos: dict)
    """
    _cargar_db()
    p = getattr(ses, 'personaje', None)
    if not p:
        return (False, 'sin_personaje', {})

    nom_clean = npc_nombre.strip().lower()

    # 1. Comprobar si el jugador tiene una misión activa que requiera hablar con este NPC
    for q, pa in (p.quests or []):
        if mision_completada(p, q):
            continue
        info = info_mision(q)
        pasos = info.get('pasos', [])
        idx_paso = pa - 1 if 0 < pa <= len(pasos) else 0
        paso_actual = pasos[idx_paso] if idx_paso < len(pasos) else None

        if paso_actual:
            npc_target = (paso_actual.get('npc_entrega') or paso_actual.get('npc') or '').strip().lower()
            if npc_target and (npc_target == nom_clean or nom_clean in npc_target or npc_target in nom_clean):
                tipo_obj = paso_actual.get('tipo', 'hablar')
                
                # Objetivo de recoleccion
                if tipo_obj == 'recolectar':
                    if not verificar_entrega_items(ses, q, pa):
                        return (True, 'recoleccion_incompleta', {'qid': q, 'paso': pa})

                # Objetivo de caceria
                if tipo_obj == 'matar':
                    req = paso_actual.get('cantidad', 1)
                    kills = (getattr(ses, 'quest_kills', {}) or {}).get((q, pa), 0)
                    if kills < req:
                        ses.enviar(_cl.aviso(f"Defeat targets first! ({kills}/{req})", tipo=0, msg_id=_cl.MSG_QUEST))
                        return (True, 'caceria_incompleta', {'qid': q, 'paso': pa})

                # Avanzar o completar
                es_ultimo = paso_actual.get('es_ultimo', False) or (pa >= len(pasos))
                if es_ultimo:
                    completar_mision(ses, q)
                    return (True, 'completada', {'qid': q})
                else:
                    sig = paso_actual.get('siguiente_paso', pa + 1)
                    avanzar_paso(ses, q, sig)
                    return (True, 'avanzada', {'qid': q, 'nuevo_paso': sig})

    # 2. Comprobar si el NPC tiene misiones para ofrecer
    disponibles = misiones_disponibles_npc(p, npc_nombre)
    if disponibles:
        # Si tiene misiones, retornar la primera o lista para que dialogos arme el menu
        return (True, 'ofrece_mision', {'disponibles': disponibles})

    return (False, 'sin_accion', {})


def obtener_mapa_instancia(qid: int, paso: int = 1) -> int:
    """Devuelve el stage_id si la mision requiere entrar a una instancia o mapa especial."""
    if (qid, paso) in QUEST_MAPAS_INSTANCIA:
        return QUEST_MAPAS_INSTANCIA[(qid, paso)]
    info = info_mision(qid)
    pasos = info.get('pasos', [])
    if 0 < paso <= len(pasos):
        st = pasos[paso - 1].get('stage_id')
        if st:
            return st
    return info.get('stage_id')
