"""
Compilador del Sistema de Misiones (Quest System) para Angels Online.
Lee setting/eng/quest.xml, stage.xml y monster.xml y genera
server/plantillas/misiones_completas.json con todos los metadatos estructurados:
- Objetivos de cacería (matar N monstruos, con mapeo de nombres e IDs)
- Objetivos de recolección (conseguir/entregar items y cantidades)
- Objetivos de conversación (hablar con NPC en mapas específicos)
- Quests repetibles y pools por NPC (misiones diarias/semanales/rotativas)
- Puntos de teletransporte / mapas de instancia asociados a quests.
"""
import json
import pathlib
import re
import xml.etree.ElementTree as ET

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
QUEST_XML = BASE_DIR / 'extracted_paks' / 'update26' / 'setting' / 'eng' / 'quest.xml'
STAGE_XML = BASE_DIR / 'extracted_paks' / 'update26' / 'setting' / 'eng' / 'stage.xml'
MONSTER_XML = BASE_DIR / 'extracted_paks' / 'update26' / 'setting' / 'eng' / 'monster.xml'
DEST_JSON = BASE_DIR / 'server' / 'plantillas' / 'misiones_completas.json'

RE_TOKEN = re.compile(r'/c\$9%(\d+)%/c\*\s*(?:/|credit hours|cans|pieces)?\s*(\d+)?')
RE_CANTIDAD = re.compile(r'/(\d+)\b')


def cargar_stages():
    stages = {}
    if not STAGE_XML.exists():
        return stages
    tree = ET.parse(STAGE_XML)
    for c in tree.getroot().findall('場景'):
        sid = c.attrib.get('編號')
        nom = c.attrib.get('名稱')
        if sid and nom:
            try:
                stages[nom.strip().lower()] = int(sid)
            except ValueError:
                pass
    return stages


def cargar_monstruos():
    nombre_a_tipos = {}
    if not MONSTER_XML.exists():
        return nombre_a_tipos
    tree = ET.parse(MONSTER_XML)
    for m in tree.getroot().findall('npc'):
        nid = m.attrib.get('編號')
        nom = m.attrib.get('名稱')
        if nid and nom:
            try:
                ntype = int(nid)
                key = nom.strip().lower()
                nombre_a_tipos.setdefault(key, set()).add(ntype)
            except ValueError:
                pass
    return {k: sorted(list(v)) for k, v in nombre_a_tipos.items()}


def limpiar_nombre_npc(nom: str) -> str:
    if not nom:
        return ''
    return re.sub(r'^Lvl\s*\d+\s*-\s*', '', nom.strip(), flags=re.IGNORECASE).strip()


def parsear_objetivo(texto_paso, npc_paso, mapa_paso, monstruos_dict, stages_dict):
    """Clasifica el objetivo de un paso y extrae sus requisitos."""
    tl = texto_paso.lower()
    tokens = RE_TOKEN.findall(texto_paso)
    
    # 1. Cacería (Kill objective)
    palabras_matar = ('defeat', 'kill', 'drive ', 'punish', 'eliminate', 'slay', 'send troops against')
    es_caceria = any(w in tl for w in palabras_matar)
    
    # Comprobar si el texto inicial antes de dos puntos es un monstruo conocido (ej. 1.Pumpkin:)
    m0 = re.search(r'^\d+\.\s*(.*?)(?::|/c|\.\s*$|$)', texto_paso)
    if m0:
        cand0 = m0.group(1).strip().lower()
        if cand0 in monstruos_dict or cand0.rstrip('s') in monstruos_dict:
            es_caceria = True

    # Cantidad requerida
    cant = 1
    m_cant = RE_CANTIDAD.search(texto_paso)
    if tokens:
        for tid, tcnt in tokens:
            if tcnt:
                cant = max(cant, int(tcnt))
    elif m_cant:
        cant = int(m_cant.group(1))

    if es_caceria:
        matched_mobs = []
        matched_ids = []
        candidatos = []

        # Caso 0: nombre al inicio antes de dos puntos (ej. 1.Pumpkin:)
        if m0 and m0.group(1).strip():
            candidatos.append(m0.group(1).strip())
        
        # Caso 1: nombre entre verbo y dos puntos o /c
        m1 = re.search(r'(?:defeat|kill|drive|punish|eliminate|slay)\s+(.*?)(?::|/c|\.\s*$|$)', texto_paso, re.IGNORECASE)
        if m1 and m1.group(1).strip():
            raw_cands = re.split(r'\s+(?:or|and)\s+|,', m1.group(1).strip())
            candidatos.extend(c.strip() for c in raw_cands if c.strip())
        
        # Caso 2: nombre despues del token (ej. /c* /60 Rainbow Birds)
        m2 = re.search(r'/c\*[\s/\d]*(.*?)(?:\.|$)', texto_paso, re.IGNORECASE)
        if m2 and m2.group(1).strip():
            raw_cands = re.split(r'\s+(?:or|and)\s+|,', m2.group(1).strip())
            candidatos.extend(c.strip() for c in raw_cands if c.strip())

        for c in candidatos:
            c_low = c.lower().strip()
            variants = [
                c_low,
                c_low.rstrip('s'),
                c_low + 's',
                c_low.replace('mice', 'mouse'),
                c_low.replace('wolves', 'wolf'),
                c_low.replace('thieves', 'thief'),
            ]
            encontrado = False
            for var in variants:
                if var in monstruos_dict:
                    matched_mobs.append(var)
                    matched_ids.extend(monstruos_dict[var])
                    encontrado = True
                    break
            if not encontrado and len(c_low) >= 3:
                matched_mobs.append(c_low)

        return {
            'tipo': 'matar',
            'cantidad': cant,
            'monstruos': list(dict.fromkeys(matched_mobs)),
            'monstruo_ids': sorted(list(set(matched_ids))),
            'token_id': int(tokens[0][0]) if tokens else None,
            'npc_entrega': limpiar_nombre_npc(npc_paso),
            'mapa': mapa_paso,
            'stage_id': stages_dict.get(mapa_paso.lower()) if mapa_paso else None
        }

    # 2. Recolección de Items
    palabras_recolectar = ('collect', 'bring', 'obtain', 'catch', 'gather', 'borrow', 'ingredient', 'mine', 'wood', 'root')
    es_recoleccion = any(w in tl for w in palabras_recolectar) or (tokens and not any(w in tl for w in ('talk', 'meet', 'report', 'sign')))

    if es_recoleccion and tokens:
        items_req = []
        for tid_str, tcnt_str in tokens:
            try:
                iid = int(tid_str)
                icnt = int(tcnt_str) if tcnt_str else cant
                items_req.append({'item_id': iid, 'cantidad': icnt})
            except ValueError:
                pass
        return {
            'tipo': 'recolectar',
            'items': items_req,
            'cantidad': cant,
            'token_id': int(tokens[0][0]) if tokens else None,
            'npc_entrega': limpiar_nombre_npc(npc_paso),
            'mapa': mapa_paso,
            'stage_id': stages_dict.get(mapa_paso.lower()) if mapa_paso else None
        }

    # 3. Conversación (Talk / Meet / Report)
    return {
        'tipo': 'hablar',
        'cantidad': 1,
        'npc_entrega': limpiar_nombre_npc(npc_paso),
        'mapa': mapa_paso,
        'stage_id': stages_dict.get(mapa_paso.lower()) if mapa_paso else None
    }


def compilar():
    print(f"Leyendo quest.xml: {QUEST_XML}")
    stages_dict = cargar_stages()
    monstruos_dict = cargar_monstruos()
    print(f"Cargados {len(stages_dict)} mapas y {len(monstruos_dict)} tipos de monstruos.")

    tree = ET.parse(QUEST_XML)
    root = tree.getroot()

    misiones = {}
    npc_inicio_map = {}
    npc_paso_map = {}
    cacerias_map = {}
    recoleccion_map = {}
    repetibles_set = set()

    for q in root.findall('任務'):
        qid_str = q.attrib.get('編號')
        if not qid_str:
            continue
        try:
            qid = int(qid_str)
        except ValueError:
            continue

        nombre = q.attrib.get('任務名稱', f'Quest {qid}').strip()
        tipo = q.attrib.get('任務類型', 'General').strip()
        intro = q.attrib.get('任務前言', '').strip()
        repetible = (q.attrib.get('可否重接') == '可重接')
        if repetible:
            repetibles_set.add(qid)

        mapa_inicio = q.attrib.get('地點') or q.attrib.get('地點01') or ''
        npc_inicio = limpiar_nombre_npc(q.attrib.get('承接') or q.attrib.get('承接01') or '')

        # Items a borrar al terminar
        borrar_items = []
        for k, v in q.attrib.items():
            if k.startswith('刪除道具'):
                try:
                    borrar_items.append(int(v))
                except ValueError:
                    pass

        # Parsear pasos (步驟01..99)
        pasos = []
        idx = 1
        while True:
            k_paso = f'步驟{idx:02d}'
            if k_paso not in q.attrib:
                break
            texto_p = q.attrib[k_paso]
            mapa_p = q.attrib.get(f'地點{idx:02d}', mapa_inicio)
            npc_p = limpiar_nombre_npc(q.attrib.get(f'承接{idx:02d}', npc_inicio))

            obj = parsear_objetivo(texto_p, npc_p, mapa_p, monstruos_dict, stages_dict)
            obj['paso'] = idx
            obj['texto'] = texto_p
            obj['siguiente_paso'] = idx + 1
            pasos.append(obj)

            # Indexar cacerias
            if obj['tipo'] == 'matar':
                cacerias_map[f"{qid}_{idx}"] = {
                    'qid': qid,
                    'paso': idx,
                    'siguiente_paso': idx + 1,
                    'cantidad': obj['cantidad'],
                    'monstruo_ids': obj['monstruo_ids'],
                    'monstruos': obj['monstruos'],
                    'token_id': obj.get('token_id'),
                    'nombre_objetivo': ' / '.join(obj['monstruos']) if obj['monstruos'] else f"Monsters ({obj['cantidad']})",
                    'npc_entrega': npc_p,
                    'mapa': mapa_p,
                }
            elif obj['tipo'] == 'recolectar':
                recoleccion_map[f"{qid}_{idx}"] = {
                    'qid': qid,
                    'paso': idx,
                    'siguiente_paso': idx + 1,
                    'cantidad': obj['cantidad'],
                    'items': obj['items'],
                    'npc_entrega': npc_p,
                    'mapa': mapa_p,
                }

            if npc_p:
                npc_paso_map.setdefault(npc_p.lower(), []).append({'qid': qid, 'paso': idx})

            idx += 1

        # Si el último paso termina la misión, marcarlo
        if pasos:
            pasos[-1]['es_ultimo'] = True

        # Estimación de recompensas base
        exp_base = 500 + qid * 80
        oro_base = 200 + qid * 30

        # Creditos de honor / contribución para subir rango
        tipo_l = tipo.lower()
        if 'city' in tipo_l or 'breeze' in tipo_l or 'aurora' in tipo_l or 'dark' in tipo_l or 'iron' in tipo_l:
            cred_base = 20 + min(60, (qid // 100) * 5)
        elif 'angel' in tipo_l or 'heaven' in tipo_l or 'eden' in tipo_l:
            cred_base = 25 + min(75, (qid // 100) * 5)
        elif repetible:
            cred_base = 15
        else:
            cred_base = max(10, min(50, int(exp_base // 2000)))

        # Determinación de facción si la misión pertenece a una ciudad o facción exclusiva
        fac_q = None
        texto_comb = (nombre + ' ' + tipo + ' ' + mapa_inicio + ' ' + intro).lower()
        if qid in (127, 133, 137) or 'aurora' in texto_comb:
            fac_q = 'Aurora'
        elif qid in (128, 134, 138) or 'dark city' in texto_comb or 'shadow' in texto_comb:
            fac_q = 'Shadow'
        elif qid in (129, 135, 139) or 'iron castle' in texto_comb or 'steel' in texto_comb:
            fac_q = 'Steel'
        elif qid in (130, 136, 140) or 'breeze wood' in texto_comb or 'beast' in texto_comb:
            fac_q = 'Beasts'

        misiones[qid] = {
            'id': qid,
            'nombre': nombre,
            'tipo': tipo,
            'faccion': fac_q,
            'intro': intro,
            'repetible': repetible,
            'npc_inicio': npc_inicio,
            'mapa_inicio': mapa_inicio,
            'stage_id': stages_dict.get(mapa_inicio.lower()) if mapa_inicio else None,
            'borrar_items': borrar_items,
            'pasos': pasos,
            'recompensa': {
                'exp': exp_base,
                'oro': oro_base,
                'creditos': cred_base
            }
        }

        if npc_inicio:
            npc_inicio_map.setdefault(npc_inicio.lower(), []).append(qid)

    resultado = {
        '_info': 'Base de datos completa de misiones para Angels Online',
        'total_misiones': len(misiones),
        'total_repetibles': len(repetibles_set),
        'misiones': misiones,
        'npc_inicio': npc_inicio_map,
        'npc_pasos': npc_paso_map,
        'cacerias': cacerias_map,
        'recolecciones': recoleccion_map,
        'repetibles': sorted(list(repetibles_set))
    }

    DEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(DEST_JSON, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)

    print(f"Compilacion completada: {len(misiones)} misiones ({len(repetibles_set)} repetibles). Guardado en {DEST_JSON}")


if __name__ == '__main__':
    compilar()
