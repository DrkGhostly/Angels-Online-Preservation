"""Compara, NPC por NPC, lo que contesta nuestro servidor con lo que contesto
el real en una captura.

Para que sirve. Los vendedores de cada ciudad se cargan a mano leyendo la
captura: el mensaje del dialogo, el retrato, las opciones y la tienda que abre
cada una. Copiar todo eso a ojo sale mal, y lo que falla no se ve hasta que
alguien clica al NPC en el juego. Esto lo compara byte a byte.

Mira los DOS momentos por separado, que es donde estaba el error que le
costo el banco a Steam Town:

  - lo que llega tras el CLIC (c2s 0x0005), que es lo que devuelve propio()
  - lo que llega tras RESPONDER una opcion (c2s 0x000B), que es lo que
    devuelve respuesta_a()

Juntarlos hacia parecer que el clic del banquero devolvia dos lineas, y por
eso se implemento asi; en realidad la segunda solo llega al elegir la opcion
del medio. Con las dos mezcladas el servidor mandaba las dos de golpe, el
cliente se quedaba con la primera y al contestar no pasaba nada.

    python tools/verificar_dialogos_npc.py logs/proxy/mundo_165425_372653_orden.jsonl
    python tools/verificar_dialogos_npc.py            # las capturas de hoy
"""
import glob
import json
import os
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ / 'proto'))

import dialogos  # noqa: E402

# Los que abren una ventana en vez de contestar texto.
VENTANAS = {0x34: 'tienda', 0x4f: 'reparar', 0x2b: 'almacen'}


def _nombres(regs):
    """entity_id -> nombre, sacados de los 0x0008 de la propia captura."""
    out = {}
    for r in regs:
        if r.get('dir') == 's2c' and r.get('opcode') == 8 and r.get('hex'):
            b = bytes.fromhex(r['hex'])
            if len(b) >= 36:
                out[struct.unpack_from('<I', b, 0)[0]] = \
                    b[16:32].split(b'\0')[0].decode('latin1')
    return out


def _repartir(regs):
    """Separa, por NPC, lo que vino tras el clic y lo que vino tras responder."""
    clic, tras = {}, {}
    act, respondido, opcion = None, False, None
    for r in regs:
        h = r.get('hex') or ''
        op = r.get('opcode')
        if r.get('dir') == 'c2s' and op == 5 and len(h) >= 8:
            act = struct.unpack_from('<I', bytes.fromhex(h), 0)[0]
            respondido, opcion = False, None
        elif r.get('dir') == 'c2s' and op == 4:
            # SE MOVIO. Lo que llegue a partir de aqui ya no es de este NPC:
            # puede ser un tornado de los que preguntan al pisarlos. Paso de
            # verdad -- el menu de Siam Square se tomo por la segunda pagina
            # del dialogo de Brin, y era del tornado que el jugador piso
            # despues de hablarle.
            act = None
        elif r.get('dir') == 'c2s' and op == 0x0b and h and act:
            # Valor por debajo de PRIMERA_OPCION no es elegir: es pedir la
            # SIGUIENTE pagina. Los NPC de varias lineas, como el guardia de
            # Bayan, mandan tres sueltas antes de la que trae opciones, y el
            # cliente las va pidiendo una a una. Todas salen de propio(), asi
            # que siguen contando como respuesta al clic.
            if not dialogos.es_opcion(int(h[:2], 16)):
                continue
            respondido = True
            # que opcion se eligio: el indice va sobre la ULTIMA linea mandada
            previas = [b for o, b, _ in clic.get(act, []) + tras.get(act, [])
                       if o == 0x12 and len(b) >= 9]
            ops = dialogos.opciones_de(previas[-1]) if previas else []
            i = dialogos.indice_opcion(int(h[:2], 16))
            opcion = ops[i] if 0 <= i < len(ops) else None
        elif r.get('dir') == 's2c' and op in (0x12, 0x34, 0x4f, 0x2b) and act:
            if op == 0x12 and len(h) < 18:
                continue                      # el cierre de nueve ceros
            (tras if respondido else clic).setdefault(act, []).append(
                (op, bytes.fromhex(h), opcion))
    return clic, tras


def verificar(f):
    regs = [json.loads(l) for l in open(f, encoding='utf-8')]
    npcs = _nombres(regs)
    clic, tras = _repartir(regs)
    print('==', os.path.basename(f))
    mal = 0

    for ent, ps in clic.items():
        nom = npcs.get(ent, '?')
        real = list(dict.fromkeys(b for o, b, _ in ps if o == 0x12))
        mio = list(dialogos.propio(nom, entidad=ent) or [])
        ok = (mio == real)
        mal += 0 if ok else 1
        print(('  OK   ' if ok else '  MAL  ')
              + 'clic  %-20r %d linea(s)' % (nom, len(real)))
        if not ok:
            print('        real:', [b.hex() for b in real])
            print('        mio :', [b.hex() for b in mio])

    for ent, ps in tras.items():
        nom = npcs.get(ent, '?')
        val = dialogos.val_por_entidad(ent) or 4
        ya = set()
        # Una opcion puede contestarse con VARIAS lineas seguidas -- el
        # banquero de Galaxia manda cinco. Se agrupan los paquetes seguidos
        # de una misma opcion y se comparan en orden contra la respuesta,
        # que si no solo se miraba la primera linea y las demas no casaban.
        grupos = []
        for op, b, opc in dict.fromkeys(ps):
            # Un mismo paquete puede quedar apuntado a dos opciones cuando se
            # contesta dos veces seguidas y el servidor no manda nada nuevo:
            # la segunda respuesta se queda mirando la linea anterior. Se
            # cuenta solo la primera, que es la que de verdad lo provoco.
            if opc is None or (op, b) in ya:
                continue
            ya.add((op, b))
            if grupos and grupos[-1][0] == opc:
                grupos[-1][1].append((op, b))
            else:
                grupos.append((opc, [(op, b)]))

        for opc, paquetes in grupos:
            r = list(dialogos.respuesta_a(opc, entidad=ent, val=val,
                                          nombre=nom) or ())
            j = 0
            for op, b in paquetes:
                cab = struct.pack('<H', op)
                while j < len(r) and r[j][:2] != cab:
                    j += 1
                mio = r[j] if j < len(r) else None
                j += 1
                esperado = cab + b
                ok = (mio == esperado)
                mal += 0 if ok else 1
                print(('  OK   ' if ok else '  MAL  ')
                      + 'op %-7d %-20r %-8s %s'
                      % (opc, nom, VENTANAS.get(op, 'dialogo'), b.hex()))
                if not ok:
                    print('        mio :', mio.hex() if mio else None)

    print('  fallos:', mal)
    return mal


def main():
    fs = sys.argv[1:]
    if not fs:
        fs = sorted(glob.glob(str(RAIZ / 'logs' / 'proxy' / 'mundo_*_orden.jsonl')),
                    key=os.path.getmtime)[-3:]
    sys.stdout.reconfigure(encoding='utf-8')
    total = sum(verificar(f) for f in fs)
    print('\nTOTAL fallos:', total)
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
