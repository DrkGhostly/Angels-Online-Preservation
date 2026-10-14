"""Quita de la plantilla de una instancia los bichos que salen POR EVENTO.

POR QUE. Las plantillas de instancia salieron de capturas, y en la captura
estaba todo lo que el jugador habia hecho salir: las momias que guardan las
estatuas de la sala 1 de Gulp Room, los Rock Slarm de las oleadas de la sala
2 de la Magic Kichen Path... Metidos como fijos, estan desde el principio y la
mecanica no tiene nada que sacar. En la Magic Kichen Path se quitaron a mano;
esto lo hace para cualquier sala.

QUE QUITA. Las zonas de generador que nombra algun GENERATE / ENABLE_GENERATOR
(poblar_del_cliente.zonas_de_evento) y, de la plantilla, cada spawn de uno de
los tipos de esa zona que este a RADIO casillas o menos de uno de sus puntos.

    python tools/quitar_oleadas.py --stage 76              ver
    python tools/quitar_oleadas.py --stage 76 --poner      escribir
"""
import argparse
import collections
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
sys.path.insert(0, str(RAIZ / 'server'))

import poblar_del_cliente as pob
import eventos as ev
import login as lg

RADIO = 10   # poblar_del_cliente reparte los de una zona alrededor de su punto: en
             # Gulp Room dos Elite Fire Mummy de la zona 181 quedaron a 7


def de_evento(stage, spawns):
    """Los spawns de la plantilla que son de una zona que saca un evento."""
    zonas = pob.zonas_de_evento(stage)
    gen = (ev.del_stage(stage) or {}).get('generadores') or {}
    puntos = collections.defaultdict(list)      # npc_type -> [casillas]
    for tag, g in gen.items():
        if int(tag) in zonas:
            for t in g['tipos']:
                puntos[int(t)].extend(tuple(p) for p in g['puntos'])
    fuera = []
    for s in spawns:
        t, cas = s.get('npc_type'), s.get('tile')
        if t is None or not cas:
            continue
        if any(max(abs(cas[0] - x), abs(cas[1] - y)) <= RADIO for x, y in puntos.get(int(t), ())):
            fuera.append(s)
    return fuera


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, required=True)
    ap.add_argument('--poner', action='store_true')
    ap.add_argument('--conservar', default='',
                    help='nombres separados por comas que se dejan aunque salgan '
                         'por evento (NPC de salida, pilares...)')
    a = ap.parse_args()
    f = RAIZ / 'server' / 'plantillas' / lg.PLANTILLAS_POR_STAGE[a.stage]
    d = json.loads(f.read_text(encoding='utf-8'))
    conservar = {n.strip() for n in a.conservar.split(',') if n.strip()}
    fuera = [s for s in de_evento(a.stage, d.get('spawns') or [])
             if s.get('nombre') not in conservar]
    print('%s: %d spawns, %d salen por evento' % (f.name, len(d.get('spawns') or []), len(fuera)))
    for n, c in collections.Counter(s.get('nombre') for s in fuera).most_common():
        print('   %s x%d' % (n, c))
    if not a.poner or not fuera:
        return
    ids = {id(s) for s in fuera}
    d['spawns'] = [s for s in d['spawns'] if id(s) not in ids]
    d['_nota'] = (d.get('_nota', '') + ' OLEADAS: fuera %d bichos de la captura que '
                  'salen por evento (tools/quitar_oleadas.py).' % len(fuera)).strip()
    texto = json.dumps(d, ensure_ascii=False, indent=1)
    if f.read_text(encoding='utf-8').endswith('\n'):
        texto += '\n'
    f.write_text(texto, encoding='utf-8')
    print('escrito: quedan %d spawns' % len(d['spawns']))


if __name__ == '__main__':
    main()
