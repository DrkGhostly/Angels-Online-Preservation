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

# Alias y sinonimos conocidos de nombres de monstruos entre textos de quests y tablas de cliente
MONSTER_NAME_ALIASES = {
    'trainee witch': ['young witch', 'junior witch'],
    'young witch': ['trainee witch', 'junior witch'],
    'trainee witches': ['young witch', 'young witches'],
    'young witches': ['trainee witch', 'trainee witches'],
    'junior witch': ['young witch', 'trainee witch'],
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
            completada = (pa > total_pasos) or (pa == 999)
            return (True, pa, completada)
    return (False, 0, False)


def total_pasos_mision(qid: int) -> int:
    m = info_mision(qid)
    pasos = m.get('pasos', [])
    return len(pasos) if pasos else 1


def mision_completada_raw(qid: int, pa: int) -> bool:
    tot = total_pasos_mision(qid)
    return (pa > tot) or (pa == 999)


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
            return (pa > total_pasos) or (pa == 999)
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


def misiones_disponibles_npc(p, npc_nombre: str, stage: int = 0) -> list:
    """Devuelve la lista de IDs de misiones que este NPC puede ofrecer al personaje."""
    _cargar_db()
    if not npc_nombre:
        return []
    nom_l = npc_nombre.strip().lower()
    qids = list(_NPC_INICIO.get(nom_l, []))
    disponibles = []

    # Si el personaje ya tiene UNA misión activa de este NPC, no se ofrece otra
    for q_act, pa_act in list(getattr(p, 'quests', []) or []):
        if not mision_completada(p, q_act):
            q_info = info_mision(q_act)
            if (q_info.get('npc_inicio') or '').strip().lower() == nom_l:
                return []
            pasos = q_info.get('pasos', [])
            idx_p = pa_act - 1 if 0 < pa_act <= len(pasos) else 0
            if idx_p < len(pasos):
                p_npc = (pasos[idx_p].get('npc_entrega') or pasos[idx_p].get('npc') or '').strip().lower()
                if p_npc == nom_l:
                    return []

    # Faccion del personaje normalizada
    p_fac = getattr(p, 'faction', 'Heaven') or 'Heaven'
    p_fac_l = p_fac.strip().lower()
    p_norm = 'aurora' if 'aurora' in p_fac_l else ('shadow' if ('shadow' in p_fac_l or 'dark' in p_fac_l) else ('steel' if ('steel' in p_fac_l or 'iron' in p_fac_l) else ('beasts' if ('beast' in p_fac_l or 'breeze' in p_fac_l) else 'heaven')))

    # Orden especial para jefes de milicia / ciudad
    if nom_l == 'militia chief' and stage == 29:
        # Cadena de Breeze Woods: Mysterious Garden (556, 555, 554) primero, luego las siguientes
        cadena_orden = [556, 555, 554, 553, 552, 551, 550, 549, 548, 547, 546, 545, 544, 543, 542]
        qids = [q for q in cadena_orden if q in qids] + [q for q in qids if q not in cadena_orden]

    for qid in qids:
        info = info_mision(qid)
        # 1. Filtro por mapa / stage
        q_stage = info.get('stage_id')
        if q_stage and stage and q_stage != stage:
            continue

        # 2. Si ya la tiene activa, no se ofrece de nuevo
        st, pa, comp = estado_mision(p, qid)
        if st and not comp:
            continue
        # 3. Si ya la completo: solo se ofrece si es repetible
        if comp and not es_repetible(qid):
            continue

        # 4. Comprobar faccion de la mision
        q_fac = info.get('faccion')
        if q_fac:
            q_fac_l = q_fac.strip().lower()
            q_norm = 'aurora' if 'aurora' in q_fac_l else ('shadow' if ('shadow' in q_fac_l or 'dark' in q_fac_l) else ('steel' if ('steel' in q_fac_l or 'iron' in q_fac_l) else ('beasts' if ('beast' in q_fac_l or 'breeze' in q_fac_l) else '')))
            if q_norm and p_norm != 'heaven' and p_norm != q_norm:
                continue

        disponibles.append(qid)

    # Si hay misiones sin completar, darles prioridad sobre repetibles ya hechas
    sin_completar = [q for q in disponibles if not mision_completada(p, q)]
    if sin_completar:
        return sin_completar

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
    paso_inicial = 1

    # Actualizar lista de quests del personaje (1-based internamente)
    nueva_lista = [item for item in (p.quests or []) if item[0] != qid]
    nueva_lista.append((qid, paso_inicial))
    p.quests = nueva_lista

    # 0x0022: alta de mision en cliente (paso de red 0 = primer paso activo)
    pkg_m = _cl.mision(char_id, qid, 0, 0)
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

    # En red el paso activo es 0-indexed: paso 1 = 0, paso 2 = 1, etc.
    paso_red = max(0, nuevo_paso - 1)
    pkg_m = _cl.mision(char_id, qid, paso_red, 0)
    pkg_av = _cl.aviso(f"{nom} ({nuevo_paso})", tipo=0, msg_id=_cl.MSG_QUEST)

    ses.enviar(pkg_m, pkg_av)
    try:
        import inventario as _inv_av
        dueno = getattr(ses, 'entity_id', char_id)
        ses.enviar(_inv_av.vaciar_ranura(dueno, 497 + (qid % 60)))
    except Exception:
        pass
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
    paso_completado = total_pasos + 1

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

    # 1. Paquete de mision completada (0x0022 con total_pasos y sello de tiempo)
    pkg_m = _cl.mision(char_id, qid, total_pasos, sello)

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


def abandonar_mision(ses, qid: int) -> bool:
    """Elimina una mision activa del registro del jugador y sincroniza con el cliente."""
    p = getattr(ses, 'personaje', None)
    if not p:
        return False

    # Proteger tutorial del Guide Palace (101, 102) y etapas 1..9
    if qid in (101, 102) or qid in range(1, 10):
        log.warning(f"Intento de abandonar mision protegida {qid}")
        return False

    tiene = False
    nueva_lista = []
    for q, pa in (p.quests or []):
        if q == qid:
            tiene = True
        else:
            nueva_lista.append((q, pa))

    if not tiene:
        return False

    p.quests = nueva_lista

    # Limpiar contadores de caceria de esta mision
    if hasattr(ses, 'quest_kills'):
        for k in list(ses.quest_kills.keys()):
            if isinstance(k, tuple) and k[0] == qid:
                del ses.quest_kills[k]

    # Guardar en base de datos
    if getattr(ses, 'usuario', None):
        cuentas.guardar_quests(ses.usuario, p.char_id, p.quests)

    # Sincronizar de forma 100% segura con el cliente:
    # 1. Enviar 0x0021 QUEST_LOG con la lista actualizada (limpia y reconstruye el registro en el cliente)
    pkg_log = _cl.paquete_quest_log(p.char_id, p.quests)
    # 2. Enviar 0x0022 con modo 2 (borrado puntual)
    pkg_del = _cl.borrar_mision(p.char_id, qid)
    ses.enviar(pkg_log, pkg_del)

    nom = nombre_mision(qid)
    try:
        import inventario as _inv_ab
        dueno = getattr(ses, 'entity_id', p.char_id)
        ses.enviar(_inv_ab.vaciar_ranura(dueno, 497 + (qid % 60)))
    except Exception:
        pass
    ses.enviar(_cl.aviso(f"Quest [{nom}] abandoned.", tipo=0, msg_id=_cl.MSG_QUEST))
    log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} abandono la mision {qid} '{nom}'")
    return True


def registrar_baja_monstruo(ses, npc_type: int, monster_name: str = None) -> bool:
    """Verifica si el monstruo derrotado suma para alguna mision activa del jugador."""
    _cargar_db()
    p = getattr(ses, 'personaje', None)
    if not p or not getattr(p, 'quests', None):
        return False

    if not hasattr(p, 'quest_kills') or p.quest_kills is None:
        p.quest_kills = {}
    if not hasattr(ses, 'quest_kills') or ses.quest_kills is None:
        ses.quest_kills = p.quest_kills

    m_nom_clean = monster_name.lower().strip() if monster_name else ''
    actualizado = False

    # Revisar cada mision activa una sola vez (evita duplicar conteos)
    for q, pa in list(p.quests):
        k_cac = f"{q}_{pa}"
        clave_tupla = (q, pa)

        c_data = None
        if clave_tupla in OBJETIVOS_CACERIA:
            c_data = OBJETIVOS_CACERIA[clave_tupla]
        elif k_cac in _CACERIAS:
            c_data = _CACERIAS[k_cac]

        if not c_data:
            continue

        req = c_data.get('cantidad', 1)
        token = c_data.get('token_id')
        m_ids = (c_data.get('monstruos', ()) if ('monstruos' in c_data and isinstance(c_data['monstruos'], (list, tuple))
                 and (not c_data['monstruos'] or isinstance(c_data['monstruos'][0], int)))
                 else c_data.get('monstruo_ids', []))
        m_noms = (c_data.get('monstruos', []) if ('monstruos' in c_data and isinstance(c_data['monstruos'], (list, tuple))
                  and c_data['monstruos'] and isinstance(c_data['monstruos'][0], str))
                  else [])

        nom_obj = c_data.get('nombre_objetivo') or 'Target'
        if 'defeat trainee witch' in nom_obj.lower():
            nom_obj = 'Young Witch / Crystal Envoy'

        coincide = False
        if npc_type in m_ids or (token and npc_type == token):
            coincide = True
        elif m_nom_clean:
            cand_noms = [m_nom_clean] + MONSTER_NAME_ALIASES.get(m_nom_clean, [])
            for cn in cand_noms:
                if any(mn in cn or cn in mn for mn in m_noms):
                    coincide = True
                    break
                for mn in m_noms:
                    if any(al in cn or cn in al for al in MONSTER_NAME_ALIASES.get(mn, [])):
                        coincide = True
                        break
                if coincide:
                    break

        if coincide:
            cnt = int(p.quest_kills.get(k_cac, 0)) + 1
            p.quest_kills[k_cac] = cnt
            ses.quest_kills[k_cac] = cnt
            ses.quest_kills[clave_tupla] = cnt
            actualizado = True

            # 1. Notificar en pantalla/chat EN CADA BAJA para que el jugador sepa de inmediato que cuenta
            ses.enviar(_cl.aviso(f"Defeated {nom_obj} ({cnt}/{req})", tipo=0, msg_id=_cl.MSG_QUEST))

            # 2. Sincronizar token oculto en ranura 497..556 (no ocupa mochila, actualiza HUD en cliente)
            token_id = token or (16075 if q == 142 else None)
            slot_oculta = 497 + (int(q) % 60)
            if token_id:
                try:
                    import inventario as _inv
                    dueno = getattr(ses, 'entity_id', p.char_id)
                    entrada = _inv.entrada_recuperada(p.char_id, slot_oculta, token_id, cant=cnt, dueno=dueno)
                    pkg_item = struct.pack('<H', 0x001B) + struct.pack('<I', 1) + entrada
                    ses.enviar(pkg_item)
                except Exception as _e_tok:
                    log.warning(f"Error sincronizando token oculto de mision {q}: {_e_tok}")

            # 3. Guardar conteo en base de datos inmediatamente
            if getattr(ses, 'usuario', None):
                cuentas.guardar_quest_kills(ses.usuario, p.char_id, p.quest_kills)

            # 4. Al completar el total requerido
            if cnt >= req:
                p.quest_kills[k_cac] = req
                ses.quest_kills[k_cac] = req
                ses.quest_kills[clave_tupla] = req

                # Vaciar la ranura oculta del token
                if token_id:
                    try:
                        import inventario as _inv
                        ses.enviar(_inv.vaciar_ranura(getattr(ses, 'entity_id', p.char_id), slot_oculta))
                    except Exception:
                        pass

                auto_avanzar = (clave_tupla in OBJETIVOS_CACERIA) or (not c_data.get('npc_entrega'))
                if auto_avanzar:
                    sig_paso = c_data.get('siguiente_paso') or (pa + 1)
                    avanzar_paso(ses, q, sig_paso)

                nom_q = nombre_mision(q)
                npc_ent = c_data.get('npc_entrega') or ('Blocks Envoy' if q == 142 else '')
                mapa_ent = c_data.get('mapa') or ('Mushroom Village' if q == 142 else '')
                aviso_fin = c_data.get('aviso_fin')
                if not aviso_fin:
                    aviso_fin = f"Quest [{nom_q}]: Defeated {nom_obj} ({req}/{req})!"
                    if npc_ent:
                        aviso_fin += f" Report to {npc_ent}"
                    if mapa_ent:
                        aviso_fin += f" ({mapa_ent})"
                ses.enviar(_cl.aviso(aviso_fin, tipo=0, msg_id=_cl.MSG_QUEST))
                log.info(f"[{getattr(ses, 'addr', '')}] {p.nombre} completo caceria de {nom_obj} ({req}/{req}) para mision {q}")

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

    # 0. Proteger tutorial de Guide Palace (51), Fighting Palace (57) y eleccion de faccion
    stage = getattr(p, 'stage', 0)
    if stage in (51, 57) or nom_clean in (
        'angel raphael', "angels' tutor", 'director wolay', 'michael',
        'angel of aurora', 'angel of beast', 'angel of iron', 'angel of shadow',
        'battle professor', 'magic professor', 'mine professor', 'guardian angel',
        'aurora angel', 'dark city angel', 'ironcastle angel', 'breezewood angel',
    ):
        return (False, 'tutorial', {})

    # 1. Comprobar si el jugador tiene una misión activa que requiera hablar con este NPC
    for q, pa in list(p.quests or []):
        if mision_completada(p, q):
            continue
        info = info_mision(q)
        pasos = info.get('pasos', [])
        idx_paso = pa - 1 if 0 < pa <= len(pasos) else 0
        paso_actual = pasos[idx_paso] if idx_paso < len(pasos) else None

        if paso_actual:
            npc_target = (paso_actual.get('npc_entrega') or paso_actual.get('npc') or '').strip().lower()
            if not npc_target:
                npc_target = (info.get('npc_inicio') or '').strip().lower()

            if npc_target and (npc_target == nom_clean or nom_clean in npc_target or npc_target in nom_clean):
                tipo_obj = paso_actual.get('tipo', 'hablar')
                
                # Objetivo de recoleccion
                if tipo_obj == 'recolectar':
                    if not verificar_entrega_items(ses, q, pa):
                        return (True, 'incompleta', {'qid': q, 'paso': pa, 'nom_npc': npc_nombre})

                # Objetivo de caceria
                if tipo_obj == 'matar':
                    req = paso_actual.get('cantidad', 1)
                    kills = (getattr(ses, 'quest_kills', {}) or {}).get((q, pa), 0)
                    if kills < req:
                        ses.enviar(_cl.aviso(f"Defeat targets first! ({kills}/{req})", tipo=0, msg_id=_cl.MSG_QUEST))
                        return (True, 'incompleta', {'qid': q, 'paso': pa, 'nom_npc': npc_nombre})
                    if hasattr(ses, 'quest_kills') and (q, pa) in ses.quest_kills:
                        del ses.quest_kills[(q, pa)]

                # Avanzar o completar (encadenando pasos consecutivos de 'hablar' con este mismo NPC)
                cur_pa = pa
                while True:
                    idx_cur = cur_pa - 1
                    if idx_cur >= len(pasos):
                        completar_mision(ses, q)
                        return (True, 'completada', {'qid': q, 'nom_npc': npc_nombre})
                    p_cur = pasos[idx_cur]
                    es_ult = p_cur.get('es_ultimo', False) or (cur_pa >= len(pasos))
                    if es_ult:
                        completar_mision(ses, q)
                        return (True, 'completada', {'qid': q, 'nom_npc': npc_nombre})

                    sig = p_cur.get('siguiente_paso', cur_pa + 1)
                    sig_idx = sig - 1
                    if sig_idx < len(pasos):
                        sig_p = pasos[sig_idx]
                        sig_npc = (sig_p.get('npc_entrega') or sig_p.get('npc') or '').strip().lower()
                        sig_tipo = sig_p.get('tipo', 'hablar')
                        if sig_tipo == 'hablar' and (not sig_npc or sig_npc == nom_clean or nom_clean in sig_npc or sig_npc in nom_clean):
                            # El paso siguiente es hablar con este mismo NPC: avanzamos internamente y seguimos la cadena
                            avanzar_paso(ses, q, sig)
                            cur_pa = sig
                            continue

                    avanzar_paso(ses, q, sig)
                    return (True, 'avanzada', {'qid': q, 'nuevo_paso': sig, 'nom_npc': npc_nombre})

    return (False, 'sin_accion', {})


def obtener_mapa_instancia(qid: int, paso: int = 1) -> int:
    """Devuelve el stage_id si la mision requiere entrar a una instancia o mapa especial."""
    if (qid, paso) in QUEST_MAPAS_INSTANCIA:
        return QUEST_MAPAS_INSTANCIA[(qid, paso)]
    return None
