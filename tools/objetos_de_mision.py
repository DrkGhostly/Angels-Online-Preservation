"""Pone en las plantillas los objetos de mapa que dan o continuan misiones.

POR QUE. Hay misiones que no empiezan ni siguen en un NPC sino en un objeto:
una estela, una tumba, un nido, una flor marchita... Se pulsan, y su evento
del mapa da la mision, la avanza, abre un dialogo o te lleva a otro mapa. El
servidor ya ejecuta esos eventos al pulsar (app.py, _recurso_con_entidad),
pero para poder pulsar un objeto el cliente tiene que haberlo recibido como
entidad, y muchas plantillas -- las que salieron de capturas -- solo traen
los objetos que se vieron al capturar: de los 83 objetos de mision que se
pulsan, 48 no estaban en su plantilla.

Se anaden igual que los genera poblar_del_cliente: con el cuerpo de 43 bytes
capturado de ese mismo tipo de objeto, cambiando entidad, capa y posicion.
Solo se anade lo que falta, y solo los objetos cuyo evento de pulsar depende
de una mision.

    python tools/objetos_de_mision.py           que falta
    python tools/objetos_de_mision.py --poner
"""
import argparse
import json
import pathlib
import shutil
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
sys.path.insert(0, str(RAIZ / 'server'))

import mapa_del_cliente as mc
import poblar_del_cliente as pob
import eventos as ev
import login as lg

PLANTILLAS = RAIZ / 'server' / 'plantillas'
BASE = 60_000_000          # la de los objetos de mapa de poblar_del_cliente
DESPLAZAMIENTO = 90_000    # dentro del hueco de cada mapa, lejos de los suyos

DISPAROS_PULSAR = (2, 6, 7)
COND_MISION = (2, 11, 13)          # QUEST_STEP, QUEST_FINISH, QUEST_RUNNING


def faltan():
    cuerpos = pob.objetos_que_se_mandan()
    salida, sin_cuerpo = {}, []
    for st_s, d in ev._datos()['stages'].items():
        st = int(st_s)
        evs = {x['ev'] for x in d['disparadores'] if x['d'] in DISPAROS_PULSAR
               and any(c[0] in COND_MISION for c in x['si'])}
        if not evs:
            continue
        f = lg.PLANTILLAS_POR_STAGE.get(st)
        if not f or not (PLANTILLAS / f).exists():
            continue
        plant = json.loads((PLANTILLAS / f).read_text(encoding='utf-8'))
        hay = {tuple(r['tile']) for r in plant.get('recursos') or [] if r.get('tile')}
        m = mc.mapa(st)
        for o in m.objetos:
            if o['evento'] not in evs or tuple(o['tile']) in hay:
                continue
            if o['id'] not in cuerpos:
                sin_cuerpo.append((st, o['tile'], o['id']))
                continue
            salida.setdefault(st, []).append(o)
    return salida, sin_cuerpo


def poner():
    cuerpos = pob.objetos_que_se_mandan()
    porponer, sin_cuerpo = faltan()
    usados = set()
    for f in PLANTILLAS.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(d, dict):
            for clave in ('recursos', 'spawns'):
                for r in d.get(clave) or []:
                    if isinstance(r, dict) and r.get('entity_id'):
                        usados.add(int(r['entity_id']))
    total = 0
    for st, objs in sorted(porponer.items()):
        f = PLANTILLAS / lg.PLANTILLAS_POR_STAGE[st]
        copia = f.with_suffix('.json.antes_objetos.bak')
        if not copia.exists():
            shutil.copy2(f, copia)
        d = json.loads(f.read_text(encoding='utf-8'))
        d.setdefault('recursos', [])
        eid = BASE + st * 100_000 + DESPLAZAMIENTO
        for o in objs:
            while eid in usados:
                eid += 1
            usados.add(eid)
            b = bytearray(cuerpos[o['id']])
            px = (o['px'][0], o['tile'][1] * 32 + 16)   # como poblar_del_cliente
            struct.pack_into('<I', b, 0, eid)
            struct.pack_into('<I', b, 4, o['capa'])
            struct.pack_into('<II', b, 8, px[0], px[1])
            d['recursos'].append({'entity_id': eid, 'sprite': o['id'], 'capa': o['capa'],
                                  'px': [px[0], px[1]], 'tile': list(o['tile']),
                                  'crudo': bytes(b).hex(),
                                  'puesto_por': 'objetos_de_mision'})
            total += 1
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    print('anadidos %d objetos de mision en %d mapas' % (total, len(porponer)))
    if sin_cuerpo:
        print('sin cuerpo capturado de su tipo, no se pueden mandar: %s' % sin_cuerpo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--poner', action='store_true')
    a = ap.parse_args()
    if a.poner:
        poner()
        return
    porponer, sin_cuerpo = faltan()
    print('objetos de mision que faltan: %d en %d mapas'
          % (sum(len(v) for v in porponer.values()), len(porponer)))
    for st, objs in sorted(porponer.items()):
        print('   stage %-4d %s' % (st, [(tuple(o['tile']), o['id']) for o in objs][:6]))
    if sin_cuerpo:
        print('sin cuerpo capturado: %s' % sin_cuerpo)


if __name__ == '__main__':
    main()
