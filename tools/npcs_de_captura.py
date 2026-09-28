"""Saca de una captura el codigo de los NPC de una ciudad, listo para pegar.

Para que sirve. Cada ciudad nueva son seis o siete NPC de servicio, y cargar
cada uno a mano es leer el 0x0012 que contesta al clic, apuntar el mensaje, el
retrato, las opciones y las acciones, y despues buscar que tienda abre cada
opcion. Son cuatro sitios distintos de dialogos.py por ciudad y se cuela un
numero con facilidad. Esto lo lee de la captura y lo escribe.

Lo que NO hace: decidir. Imprime, no toca dialogos.py. Lo que salga hay que
leerlo y pegarlo, porque quedan cosas que solo se saben mirando -- si un NPC
tiene varias paginas, si una opcion lleva a otra linea o si el nombre choca
con el de otra ciudad.

Que reconoce, que es lo aprendido en las seis ciudades que ya estan:

  - el clic (c2s 0x0005) y el 0x0012 que contesta
  - las PAGINAS: un c2s 0x000B por debajo de 10 no es elegir, es pedir la
    siguiente linea, asi que esa linea tambien sale del mismo propio()
  - la respuesta a una opcion: la tienda (0x0034), la ventana de reparar
    (0x004F), el almacen (0x004E) o simplemente otra linea de dialogo
  - el retrato: se calcula del sprite y solo se escribe si NO coincide, que
    hasta ahora no ha pasado nunca

    python tools/npcs_de_captura.py logs/proxy/mundo_200338_925837_orden.jsonl
    python tools/npcs_de_captura.py --stage 258 --zona Shuwa <captura>
"""
import argparse
import collections
import json
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ / 'proto'))

import dialogos  # noqa: E402


def _leer(f):
    """spawns, y por NPC lo que llego al clic y lo que llego al responder."""
    regs = [json.loads(l) for l in open(f, encoding='utf-8')]
    npcs = {}
    for r in regs:
        if r.get('dir') == 's2c' and r.get('opcode') == 8 and r.get('hex'):
            b = bytes.fromhex(r['hex'])
            if len(b) >= 46:
                npcs[struct.unpack_from('<I', b, 0)[0]] = (
                    b[16:32].split(b'\0')[0].decode('latin1', 'replace'),
                    struct.unpack_from('<H', b, 34)[0])
    lineas = collections.defaultdict(list)
    respuestas = collections.defaultdict(list)
    act, eligio, opcion = None, False, None
    for r in regs:
        h = r.get('hex') or ''
        op = r.get('opcode')
        if r.get('dir') == 'c2s' and op == 5 and len(h) >= 8:
            act = struct.unpack_from('<I', bytes.fromhex(h), 0)[0]
            eligio, opcion = False, None
        elif r.get('dir') == 'c2s' and op == 0x0b and h and act:
            v = int(h[:2], 16)
            if not dialogos.es_opcion(v):
                continue                  # pedir la siguiente pagina
            eligio = True
            prev = [b for b in lineas[act]] + [b for _, b in respuestas[act]
                                               if b[:1] != b'']
            todas = lineas[act] + [b for _, b in respuestas[act]]
            ops = dialogos.opciones_de(todas[-1]) if todas else []
            i = dialogos.indice_opcion(v)
            opcion = ops[i] if 0 <= i < len(ops) else None
        elif r.get('dir') == 's2c' and act and op in (0x12, 0x34, 0x4f, 0x4e):
            if op == 0x12 and len(h) < 18:
                continue                  # el cierre de nueve ceros
            b = bytes.fromhex(h)
            if eligio:
                respuestas[act].append((opcion, (op, b)))
            elif op == 0x12:
                lineas[act].append(b)
    return npcs, lineas, respuestas


def _trozos(b):
    """mid, val, opciones y acciones de una linea 0x0012."""
    mid, val = struct.unpack_from('<IH', b, 0)
    n = b[7]
    ops = [struct.unpack_from('<I', b, 9 + 4 * k)[0] for k in range(n)]
    acc = [struct.unpack_from('<I', b, 9 + 4 * n + 4 * k)[0]
           for k in range(n)] if len(b) >= 9 + 8 * n else []
    return mid, val, ops, acc


def _llamada(b, val_auto, sangria='    '):
    mid, val, ops, acc = _trozos(b)
    # El retrato casi siempre sale del sprite; solo se escribe si no cuadra.
    v = 'npc_val or %d' % val if val != val_auto else 'npc_val or %d' % val
    txt = '%sarmar_linea(%d, %s, %s' % (sangria, mid, v, ops or '[]')
    if any(acc):
        txt += ',\n%s            acciones=%s' % (sangria, acc)
    return txt + ')[2:]'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('captura')
    ap.add_argument('--stage', type=int, default=0)
    ap.add_argument('--zona', default='')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    npcs, lineas, respuestas = _leer(a.captura)
    if not lineas:
        print('en esa captura no se clico a ningun NPC')
        return 1

    cab = '    # --- %s ---' % (a.zona or 'ZONA')
    if a.stage:
        cab = '    # --- %s (Stage %d) ---' % (a.zona or 'ZONA', a.stage)
    print('# ====== para propio(), en dialogos.py ======')
    print(cab)
    print('    # Medido en %s.' % pathlib.Path(a.captura).name)
    tiendas, por_opcion = [], []
    for ent, ls in lineas.items():
        nom, spr = npcs.get(ent, ('?', 0))
        auto = dialogos.val_por_entidad(ent) or 0
        # el nombre llega cortado a 16 bytes; se compara tal cual
        clave = nom[:15] if nom.endswith(')') else nom
        print("    if '%s' in nombre:" % clave)
        if len(ls) == 1:
            print('        return [%s]' % _llamada(ls[0], auto, '').lstrip())
        else:
            print('        # %d paginas: el cliente las pide una a una.' % len(ls))
            print('        return [')
            for b in ls:
                print('            %s,' % _llamada(b, auto, '').lstrip())
            print('        ]')
        for opc, (op, b) in respuestas[ent]:
            if op == 0x34:
                sid = struct.unpack_from('<H', b, 0)[0]
                tiendas.append((ent, nom, opc, sid))
            elif op == 0x12:
                por_opcion.append((nom, opc, b))

    if tiendas:
        print('\n# ====== para TIENDAS_POR_ENTIDAD ======')
        for ent, nom, opc, sid in tiendas:
            print('    %d: %d, # %s (opcion %d)' % (ent, sid, nom, opc))
        print('\n# ====== para TIENDAS_POR_NOMBRE ======')
        for ent, nom, opc, sid in tiendas:
            print("    '%s': %d," % (nom.strip(), sid))
    if por_opcion:
        print('\n# ====== opciones que contestan OTRA LINEA, para respuesta_a ======')
        for nom, opc, b in por_opcion:
            mid, val, ops, acc = _trozos(b)
            print('    # %s' % nom)
            print('    if opcion_id == %d:' % opc)
            print('        return (armar_linea(%d, val, %s,' % (mid, ops or '[]'))
            print('                            acciones=%s),)' % acc)

    sueltas = sorted({o for ls in lineas.values() for b in ls
                      for o in dialogos.opciones_de(b)}
                     - {o for o, _ in
                        [(x[0], 0) for v in respuestas.values() for x in v]})
    if sueltas:
        print('\n# ====== opciones SIN medir (nadie las pulso) ======')
        print('#   %s' % sueltas)
    return 0


if __name__ == '__main__':
    sys.exit(main())
