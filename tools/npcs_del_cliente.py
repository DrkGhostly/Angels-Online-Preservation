"""Los NPC que el cliente pone en cada mapa, y los que faltan en el servidor.

POR QUE. En Sandy Heights estaban los bichos y los dos NPC de siempre, pero
no estaba Leif, que es con quien sigue una mision. El cliente SI lo sabe: lo
dibuja en su mapa del mundo con su nombre. O sea que el dato estaba, como
siempre, dentro del .mpc.

DONDE. En el registro de 74 bytes de cada objeto, el **+22** es el id de NPC,
y el campo id del objeto (+0) es su SPRITE. Se encontro buscando a lo bruto
los ids de npc.xml dentro de los registros, y la prueba de que es ese campo y
no otro no es que salga: es que los NPC que YA estaban puestos a mano salen
clavados, misma casilla y mismo sprite.

    405  Amil           cliente (117,150) sprite 40263  plantilla igual
    405  Sage Oros      cliente (20,52)   sprite 40076  plantilla igual
    406  Analyst Harper cliente (215,96)  sprite 40069  plantilla igual
    406  Analyst Silrum cliente (127,120) sprite 40039  plantilla igual
    405  Leif           cliente (180,50)  sprite 40394  NO ESTABA
    406  Mr. Fleming    cliente (208,67)  sprite 40492  NO ESTABA

ESTO SOLO ANADE. Nunca toca ni quita lo que ya hay: las plantillas llevan
datos medidos con capturas y misiones montadas encima. Si un NPC ya esta, se
deja como esta aunque el cliente lo ponga en otro sitio, y se avisa.

    python tools/npcs_del_cliente.py                 que falta, en todos
    python tools/npcs_del_cliente.py --stage 405     en uno
    python tools/npcs_del_cliente.py --poner         anade los que falten
    python tools/npcs_del_cliente.py --poner --stage 405
"""
import argparse
import json
import pathlib
import shutil
import sqlite3
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))

import mapa_del_cliente as mc

PLANTILLAS = RAIZ / 'server' / 'plantillas'
BD = RAIZ / 'corpus' / 'content.db'

# El id del NPC dentro del registro de 74 bytes del objeto.
OFF_NPC = 22

# Base de entidad para los NPC que pone esta herramienta. Las bases que ya
# usa el proyecto: 50M monstruos, 60M objetos de mapa, 70M portales, 80M
# presencia. Esta es la siguiente libre, para que se vea de un vistazo quien
# puso cada entidad.
BASE_ENTIDAD = 90_000_000

_NPCS = None


def _npcs():
    """id -> (nombre, sprite) de npc.xml, via corpus/content.db."""
    global _NPCS
    if _NPCS is None:
        c = sqlite3.connect(BD)
        _NPCS = {}
        for i, nom, spr in c.execute('select id, name, sprite_id from npc'):
            if i and str(i).isdigit():
                _NPCS[int(i)] = (nom, int(spr) if spr and str(spr).isdigit() else 0)
        c.close()
    return _NPCS


def declarados(stage):
    """Los NPC que el .mpc del cliente pone en ese mapa."""
    rutas = mc.mapas_del_cliente()
    if stage not in rutas:
        return []
    ruta = rutas[stage]
    b = pathlib.Path(ruta).read_bytes()
    m = mc.Mapa(stage, ruta)
    tabla = _npcs()
    salida = []
    for ob in m.objetos:
        nid = struct.unpack_from('<H', b, m.off_objetos + ob['i'] * 74 + OFF_NPC)[0]
        if nid in tabla:
            nombre, sprite = tabla[nid]
            salida.append({'npc_type': nid, 'nombre': nombre,
                           'tile': list(ob['tile']),
                           'sprite': ob['id'] or sprite})
    return salida


# Los totems los pone el cliente como "Totem" a secas y el servidor los
# lleva aparte, con el id de cada ciudad sacado de capturas. No se tocan.
NO_SON_NPC = {'Totem'}


def _corto(nombre):
    """El nombre como lo guarda el servidor: CORTADO A 16 caracteres.

    Las plantillas salen de capturas y el mensaje del NPC lleva el nombre en
    16 bytes, asi que "Adventure Guild Admin" queda en "Adventure Guild " y
    "Bassil Archeologist" en "Bassil Archeolog". Sin cortar, un NPC que ya
    estaba en una casilla vecina salia como "falta" y se habria duplicado.
    """
    return (nombre or '')[:16].strip().lower()


def _plantillas_por_stage():
    """stage -> (ruta del json, datos). Solo las que declaran stage."""
    salida = {}
    for f in sorted(PLANTILLAS.glob('*.json')):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(d, dict) and 'stage' in d and 'spawns' in d:
            salida.setdefault(int(d['stage']), []).append((f, d))
    return salida


def _entidades_usadas():
    usadas = set()
    for f in PLANTILLAS.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for s in (d.get('spawns') or []) if isinstance(d, dict) else []:
            if isinstance(s, dict) and s.get('entity_id'):
                usadas.add(int(s['entity_id']))
    return usadas


def revisar(solo=None):
    """Que NPC faltan. Devuelve {stage: [npc, ...]}."""
    porstage = _plantillas_por_stage()
    faltan, movidos = {}, []
    for stage, ficheros in sorted(porstage.items()):
        if solo is not None and stage != solo:
            continue
        dice = declarados(stage)
        if not dice:
            continue
        # un stage puede tener varias plantillas (los cuartos de instancia);
        # un NPC puesto en cualquiera de ellas cuenta como puesto
        # SE COMPARA POR CASILLA, NO POR NOMBRE. El cliente llama "Totem" a
        # secas al que el servidor tiene como "Aurora Totem", "Iron Totem" y
        # demas, con el id de cada ciudad sacado de una captura. Comparando
        # por nombre salian 184 mapas "sin totem" cuando estaban todos
        # puestos, y meterlos otra vez habria duplicado uno por ciudad.
        por_casilla, por_nombre = {}, {}
        for _f, d in ficheros:
            for s in d.get('spawns') or []:
                if s.get('monstruo'):
                    continue
                if s.get('tile'):
                    por_casilla[tuple(s['tile'])] = s
                if s.get('nombre'):
                    por_nombre[_corto(s['nombre'])] = s
        pendientes = []
        for n in dice:
            if tuple(n['tile']) in por_casilla:
                continue                     # ya hay alguien ahi
            if n['nombre'] in NO_SON_NPC:
                continue
            p = por_nombre.get(_corto(n['nombre']))
            if p is None:
                pendientes.append(n)
            else:
                movidos.append((stage, n['nombre'], p.get('tile'), n['tile']))
        if pendientes:
            faltan[stage] = pendientes
    return faltan, movidos


def _klass_conocidos():
    """nombre -> klass de los NPC capturados: el mismo NPC lleva el mismo
    klass en todos los mapas, y es el dato bueno (sale del servidor real)."""
    k = {}
    for f in PLANTILLAS.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for s in (d.get('spawns') or []) if isinstance(d, dict) else []:
            if (isinstance(s, dict) and not s.get('monstruo') and s.get('nombre')
                    and s.get('puesto_por') != 'npcs_del_cliente'):
                k.setdefault(_corto(s['nombre']), s.get('klass'))
    return k


# klass por defecto: el de los NPC con dialogo, que son 1976 de los 2418
# capturados (docs/guia_analisis_dialogos_npcs.md).
KLASS_NPC = 199


def poner(solo=None):
    """Anade los NPC que faltan siguiendo las convenciones del proyecto:

      * id de entidad A CONTINUACION de los NPC que ya tiene ese mapa, que es
        el rango que usa el servidor para saber de que mapa es cada uno; solo
        si el mapa no tiene ninguno se usa la base propia, 90.000.000;
      * klass el de un NPC capturado con el mismo nombre, o 199;
      * nombre cortado a 16, como viaja en el mensaje.
    """
    faltan, _mov = revisar(solo)
    if not faltan:
        print('no falta ningun NPC')
        return True
    porstage = _plantillas_por_stage()
    usadas = _entidades_usadas()
    klass_de = _klass_conocidos()
    total = 0
    for stage, lista in sorted(faltan.items()):
        fichero, datos = porstage[stage][0]     # la principal del mapa
        copia = fichero.with_suffix('.json.antes_npcs.bak')
        if not copia.exists():
            shutil.copy2(fichero, copia)
        ids_npc = [int(s['entity_id']) for _f, d in porstage[stage]
                   for s in d.get('spawns') or []
                   if not s.get('monstruo') and s.get('entity_id')
                   and int(s['entity_id']) < BASE_ENTIDAD]
        siguiente = (max(ids_npc) + 1) if ids_npc else BASE_ENTIDAD + stage * 1000
        for n in lista:
            while siguiente in usadas:
                siguiente += 1
            eid = siguiente
            usadas.add(eid)
            datos['spawns'].append({
                'entity_id': eid,
                # cortado a 16 como los que vienen de capturas: asi
                # lo buscan los dialogos y asi va en el mensaje
                'nombre': n['nombre'][:16],
                'nombre_completo': n['nombre'],
                'npc_type': n['npc_type'],
                'sprite': n['sprite'],
                'klass': klass_de.get(_corto(n['nombre']), KLASS_NPC) or KLASS_NPC,
                'monstruo': False,
                'tile': n['tile'],
                'direccion': 6,
                'visible': 1,
                'puesto_por': 'npcs_del_cliente',
            })
            total += 1
        fichero.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                           encoding='utf-8')
    print('anadidos %d NPC en %d mapas' % (total, len(faltan)))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int)
    ap.add_argument('--poner', action='store_true')
    a = ap.parse_args()
    if a.poner:
        raise SystemExit(0 if poner(a.stage) else 1)
    faltan, movidos = revisar(a.stage)
    n = sum(len(v) for v in faltan.values())
    print('NPC que el cliente pone y el servidor no: %d, en %d mapas'
          % (n, len(faltan)))
    for stage, lista in sorted(faltan.items()):
        print('   stage %-5d %s' % (stage, ', '.join(
            '%s %s' % (x['nombre'], tuple(x['tile'])) for x in lista)))
    if movidos:
        print('\npuestos en otra casilla que la del cliente (NO se tocan): %d'
              % len(movidos))
        for stage, nom, hay, dice in movidos[:15]:
            print('   stage %-5d %-22s servidor %s   cliente %s'
                  % (stage, nom, tuple(hay or ()), tuple(dice)))
    raise SystemExit(0)


if __name__ == '__main__':
    main()
