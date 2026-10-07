"""Puebla un mapa desde una captura del cliente GLOBAL.

Hace falta aparte porque el Global manda el 0x0008 DISTINTO. En Celestia y
en Taiwan mide 62, 63 o 64 bytes y trae el nombre en ascii/big5 en los
offsets 16..31; en el Global mide 46 y NO trae nombre -- el cliente lo
resuelve solo a partir del tipo. tools/poblar_mapa.py exige len >= 47, asi
que descartaba los paquetes del Global uno por uno y devolvia cero spawns.

El layout del Global, medido sobre 493 entidades de Magic Kichen Path:

    +0   u32  entity_id
    +8   u32  tile x
    +12  u32  tile y
    +17  u16  sprite
    +28  u16  npc_type

Esos dos ultimos NO se dedujeron por su pinta: se buscaron probando TODOS
los offsets contra una restriccion conjunta -- que monster.id valga lo que
hay en +28 Y QUE ADEMAS monster.sprite_id valga lo que hay en +17. Eso dio
493 de 493 sin un solo fallo, y es algo que no se acierta por casualidad.

El nombre y el nivel salen de content.db por npc_type, que es mas fiable
que la cadena del paquete.

NO se guardan los objetos de mapa (0x000E). En el Global miden 26 bytes y
aqui se guardan CRUDOS para reenviarlos tal cual; mandarle a nuestro
cliente un cuerpo de otro formato lo rompe. Quedan para cuando se midan.

Uso:
    python tools/poblar_instancia_global.py --stage 73 --nombre magic_kichen_path \
        --sesiones logs/proxy/mundo_*_orden.jsonl
"""
import argparse
import collections
import json
import pathlib
import sqlite3
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent
LARGO = 46          # el 0x0008 del Global
OFF_EID, OFF_X, OFF_Y, OFF_SPRITE, OFF_TIPO = 0, 8, 12, 17, 28


def _catalogo():
    """npc_type -> (nombre, nivel, sprite, es_monstruo)."""
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    cat = {}
    for tabla, mob in (('npc', False), ('monster', True)):
        for i, s, n, l in con.execute(
                'select id, sprite_id, name, level from %s' % tabla):
            try:
                cat[int(i)] = (n, int(l or 0), int(s or 0), mob)
            except (TypeError, ValueError):
                continue
    con.close()
    return cat


def leer(sesiones, stage):
    """Las entidades distintas vistas MIENTRAS se estaba en ese mapa.

    Hay que seguir los 0x000C para saber donde esta el jugador: una misma
    captura pasa por decenas de mapas y el 0x0008 no dice a cual pertenece.
    """
    ents = {}
    for f in sesiones:
        actual = None
        for linea in open(f, encoding='utf-8', errors='replace'):
            try:
                x = json.loads(linea)
            except ValueError:
                continue
            if x.get('dir') != 's2c':
                continue
            if x.get('opcode') == 0x000C and x.get('len', 0) >= 4:
                actual = struct.unpack_from('<I', bytes.fromhex(x['hex']), 0)[0]
            elif (x.get('opcode') == 0x0008 and actual == stage
                  and x.get('len') == LARGO):
                b = bytes.fromhex(x['hex'])
                ents.setdefault(struct.unpack_from('<I', b, OFF_EID)[0], b)
    return ents


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, required=True)
    ap.add_argument('--nombre', required=True)
    ap.add_argument('--sesiones', nargs='+', required=True)
    a = ap.parse_args()

    cat = _catalogo()
    ents = leer(a.sesiones, a.stage)
    spawns, sin_catalogo = [], collections.Counter()
    for eid, b in sorted(ents.items()):
        spr = struct.unpack_from('<H', b, OFF_SPRITE)[0]
        tipo = struct.unpack_from('<H', b, OFF_TIPO)[0]
        info = cat.get(tipo)
        if not info or info[2] != spr:
            # El sprite no casa con el del catalogo: o el offset no es ese
            # para esta entidad o es algo que no esta en content.db. No se
            # inventa nada, se cuenta y se deja fuera.
            sin_catalogo[(tipo, spr)] += 1
            continue
        nom, nivel, _s, mob = info
        e = {'entity_id': eid, 'nombre': nom, 'npc_type': tipo,
             'sprite': spr, 'klass': 1 if mob else 200,
             'monstruo': mob,
             'tile': [struct.unpack_from('<I', b, OFF_X)[0],
                      struct.unpack_from('<I', b, OFF_Y)[0]],
             'direccion': 2, 'visible': 0}
        if mob:
            e['nivel'] = nivel
        spawns.append(e)

    mobs = sum(1 for e in spawns if e['monstruo'])
    dest = RAIZ / 'server' / 'plantillas' / (a.nombre + '.json')
    dest.write_text(json.dumps({
        '_nota': ('%s (stage %d). Poblado desde una captura del cliente '
                  'GLOBAL, cuyo 0x0008 mide 46 bytes y no trae nombre: el '
                  'nombre y el nivel salen de content.db por npc_type. Sin '
                  'objetos de mapa: los 0x000E del Global miden 26 bytes y '
                  'aqui se guardan crudos, asi que reenviarlos romperia '
                  'nuestro cliente. Ver tools/poblar_instancia_global.py.'
                  % (a.nombre, a.stage)),
        'stage': a.stage,
        'spawns': spawns,
        'recursos': [],
    }, ensure_ascii=False, indent=1), encoding='utf-8')

    print('%s.json: %d spawns (%d monstruos, %d NPC)'
          % (a.nombre, len(spawns), mobs, len(spawns) - mobs))
    if sin_catalogo:
        print('   descartados por no casar con content.db: %d'
              % sum(sin_catalogo.values()))
        for (t, s), c in sin_catalogo.most_common(8):
            print('      npc_type=%-7s sprite=%-7s x%d' % (t, s, c))
    cuenta = collections.Counter((e['nombre'], e.get('nivel')) for e in spawns)
    for (n, lv), c in cuenta.most_common():
        print('   %-30s nv %-5s x%d' % (n, lv, c))


if __name__ == '__main__':
    main()
