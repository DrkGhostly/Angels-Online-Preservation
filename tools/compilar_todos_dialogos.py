import sys
sys.stdout.reconfigure(encoding='utf-8')
import xml.etree.ElementTree as ET
import json
import struct
import pathlib
import re

print("Iniciando compilador optimizado de dialogos de TODOS los NPCs...")

# 1. Cargar todas las entidades y nombres de NPCs desde plantillas
from dialogos import _cargar_npcs, val_por_entidad
npcs_ent = _cargar_npcs()

# Agrupar por nombre normalizado
npcs_por_nombre = {}
for eid, data in npcs_ent.items():
    nom = (data.get('nombre') or '').strip()
    if nom and nom not in npcs_por_nombre:
        npcs_por_nombre[nom] = {
            'entidad': eid,
            'sprite': data.get('sprite', 0),
            'stage': data.get('stage', 0),
            'val': val_por_entidad(eid)
        }

print(f"Total NPCs unicos encontrados: {len(npcs_por_nombre)}")

# 2. Cargar msg.xml e indexar intros en UNA sola pasada
tree = ET.parse('extracted_paks/update26/setting/eng/msg.xml')
root = tree.getroot()
msgs = {}
intros_por_nombre = {}
re_intro = re.compile(r"(?:i am|i'm|my name is)\s+(?:the\s+)?([A-Za-z0-9 '\-\.]{2,35})", re.IGNORECASE)

for e in root:
    vals = list(e.attrib.values())
    if len(vals) >= 2 and vals[0].isdigit():
        mid = int(vals[0])
        txt = vals[1].strip()
        msgs[mid] = txt
        m = re_intro.search(txt)
        if m:
            cand = m.group(1).lower().strip()
            # Si el texto coincide con algun nombre de NPC
            if cand in npcs_por_nombre and cand not in intros_por_nombre:
                intros_por_nombre[cand] = mid

print(f"Total mensajes en msg.xml: {len(msgs)}")

# 3. Cargar misiones
mis_data = json.load(open('server/plantillas/misiones_completas.json', encoding='utf-8'))
npc_ini = mis_data.get('npc_inicio', {})
npc_pasos = mis_data.get('npc_pasos', {})

# 4. Cargar dialogos_npc.json existente para preservar los 33 originales afinados a mano
dlg_path = pathlib.Path('server/plantillas/dialogos_npc.json')
dlg_existente = json.load(open(dlg_path, encoding='utf-8')) if dlg_path.exists() else {'npcs': {}}
nuevos_npcs = dict(dlg_existente.get('npcs', {}))

def armar_hex(mid, val, opts=[]):
    hdr = struct.pack('<IHBBB', mid, val, 0, len(opts), 0)
    body = b''.join(struct.pack('<I', o) for o in opts)
    return (hdr + body).hex()

# 5. Para cada NPC único, encontrar su mejor mensaje (instantaneo)
for nom, info in npcs_por_nombre.items():
    if nom in nuevos_npcs:
        continue

    nom_l = nom.lower()
    val = info['val']
    mid_elegido = None

    # Estrategia A: Si es NPC de inicio de mision, su intro natural es qid * 100 + 1 (o + 5 o + 10)
    if nom_l in npc_ini and npc_ini[nom_l]:
        qid_p = npc_ini[nom_l][0]
        base_q = qid_p * 100
        for cand_m in (base_q + 1, base_q + 5, base_q + 10, base_q + 12):
            if cand_m in msgs:
                mid_elegido = cand_m
                break

    # Estrategia B: Si es NPC de paso de mision
    if not mid_elegido and nom_l in npc_pasos and npc_pasos[nom_l]:
        q_item = npc_pasos[nom_l][0]
        qid_p = q_item.get('qid') if isinstance(q_item, dict) else (q_item[0] if isinstance(q_item, (list, tuple)) else q_item)
        if qid_p:
            base_q = int(qid_p) * 100
            for cand_m in (base_q + 1, base_q + 5, base_q + 10, base_q + 15):
                if cand_m in msgs:
                    mid_elegido = cand_m
                    break

    # Estrategia C: Intro indexada
    if not mid_elegido and nom_l in intros_por_nombre:
        mid_elegido = intros_por_nombre[nom_l]

    # Estrategia D: Saludo estándar seguro de Angels Online (5006: "Greetings, Angel!" o 5001)
    if not mid_elegido:
        mid_elegido = 5006 if 5006 in msgs else 5001

    txt_final = msgs.get(mid_elegido, "Greetings, Angel!")
    nuevos_npcs[nom] = {
        'msgid': mid_elegido,
        'val': val,
        'hex': armar_hex(mid_elegido, val, []),
        'texto': txt_final
    }

print(f"Total NPCs compilados en dialogos_npc.json: {len(nuevos_npcs)} (100% de cobertura)")

# Guardar
dlg_existente['npcs'] = nuevos_npcs
with open(dlg_path, 'w', encoding='utf-8') as f:
    json.dump(dlg_existente, f, indent=2, ensure_ascii=False)

print("dialogos_npc.json actualizado exitosamente con TODOS los NPCs!")

