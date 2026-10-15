"""Pone en la plantilla de una instancia sus objetos de mapa: barreras, sellos...

POR QUE. Dentro de la Magic Kichen Path (stage 73) no habia ni una barrera y
se podia entrar a todas las salas. La plantilla salio de una captura del
cliente Global, cuyos 0x000E (26 bytes) no casan con los de nuestro cliente
(43), asi que se dejaron fuera; y poblar_del_cliente.recursos_de() tampoco
los pone, porque solo conoce los objetos que se vieron en capturas del IGG, y
a ninguna instancia del IGG se pudo entrar.

LO QUE DICE EL GLOBAL. Sus capturas de la instancia SI traen los objetos, y
el sprite esta en el +17 del cuerpo, igual que en su 0x0008. Cruzados con el
.mpc del mapa:

  * todo lo que manda el servidor esta en el .mpc, y en la misma casilla
    (la y va volteada, como en el resto de mapas);
  * entre lo que manda estan las 21 barreras 60308 de las salas, que el
    cliente NO dibuja por su cuenta: comprobado en el juego, en la casilla
    (119,177) no se ve nada sin el objeto;
  * y lo que el servidor no manda es decorado (60735, 60701, 60975...) que el
    cliente pinta solo.

Asi que aqui se pone, para cada objeto del .mpc, el que tenga un sprite que
el servidor manda: los que ya se sabian del IGG (objetos_que_se_mandan) mas
los vistos en las capturas Global de ESTE mapa.

EL CUERPO. Si el sprite tiene un 0x000E capturado en el IGG, se copia ese. Si
no -- la barrera y otros diez --, se copia el del 60157, que es un objeto
quieto con la cola (+36..+42) a ceros, que es justo como llegan esos sprites
en el Global, y se le cambia el sprite.

Los tornados (60001) no se ponen: los dibuja login.portales_de().

    python tools/objetos_de_instancia.py --stage 73              ver
    python tools/objetos_de_instancia.py --stage 73 --poner      escribir
"""
import argparse
import collections
import glob
import json
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
sys.path.insert(0, str(RAIZ / 'server'))

import mapa_del_cliente as mc
import poblar_del_cliente as pob
import login as lg

PLANTILLAS = RAIZ / 'server' / 'plantillas'
CAPTURAS = str(RAIZ / 'logs' / 'proxy' / 'mundo_*_orden.jsonl')
MOLDE = 60157          # objeto quieto, cola a ceros: ver el docstring
PULSABLE_MOLDE = 60094 # brasero: objeto con evento que se pulsa
VETA_MOLDE = 60011     # 物產-01中型礦 (veta mediana de estano), capturada en el IGG
TORNADO = 60001
OFF_SPRITE_GLOBAL = 17


def sprites_global(stage):
    """Los sprites de los 0x000E que el servidor Global mando en ese mapa."""
    vistos = collections.Counter()
    for f in sorted(glob.glob(CAPTURAS)):
        actual = None
        for linea in open(f, encoding='utf-8', errors='replace'):
            try:
                x = json.loads(linea)
            except ValueError:
                continue
            if x.get('dir') != 's2c':
                continue
            op = x.get('opcode')
            if op == 0x000C and x.get('len', 0) >= 4:
                actual = struct.unpack_from('<I', bytes.fromhex(x['hex']), 0)[0]
            elif op == 0x000E and actual == stage:
                b = bytes.fromhex(x['hex'])
                if len(b) >= OFF_SPRITE_GLOBAL + 2:
                    vistos[struct.unpack_from('<H', b, OFF_SPRITE_GLOBAL)[0]] += 1
    return vistos


def _nombre_material(mid):
    f = PLANTILLAS / 'materiales.json'
    if not f.exists():
        return ''
    return (json.loads(f.read_text(encoding='utf-8'))['materiales']
            .get(str(mid), {}).get('nombre', ''))


def _vetas():
    """Los ids de objeto que son vetas (SERV_CLASS_MATOBJ), de materiales.json."""
    f = PLANTILLAS / 'materiales.json'
    if not f.exists():
        return set()
    return {int(k) for k in json.loads(f.read_text(encoding='utf-8'))['objetos_material']}


def objetos(stage):
    ruta = mc.mapas_del_cliente()[stage]
    m = mc.Mapa(stage, ruta)
    crudo_mpc = ruta.read_bytes() if hasattr(ruta, 'read_bytes') else open(ruta, 'rb').read()
    cuerpos = pob.objetos_que_se_mandan()
    vetas = _vetas()
    mandados = set(cuerpos) | set(sprites_global(stage)) | vetas
    # Y los que se PULSAN: un objeto con un disparador de clic (modo 2) tiene
    # que existir como entidad, o el cliente no manda el clic. En la sala 1
    # de Gulp Room dos de las ocho estatuas de la cadena (60042 y 60040) y la
    # antorcha giratoria de la pared (60307/60299, evento 151) no se mandaban
    # porque su sprite no salio en ninguna captura, y sin ellas la cadena de
    # estatuas no se podia terminar.
    import eventos as _ev
    _d = _ev.del_stage(stage) or {}
    con_clic = {t['ev'] for t in _d.get('disparadores') or [] if t.get('d') == 2}
    # Y lo que algun evento o dialogo CAMBIA (CHANGE_STATICOBJ, accion 52):
    # las puertas que se abren al girar una antorcha o al matar a las momias
    # de Gulp Room (pasan a 60273/60275). Si la cerrada no se manda, no hay
    # nada que cambiar y la puerta "abierta" sale de la nada.
    sys.path.insert(0, str(RAIZ / 'server'))
    import dialogos_mapa as _dm
    tags = {p[0] for t in _d.get('disparadores') or [] for a, p in t['haz'] if a == 52}
    tags |= {ac[1][0] for n in _dm._arbol(stage).values() for ac in (n.get('a') or [])
             if ac[0] == 52 and ac[1]}
    cambiables = {tuple(c) for tg in tags for c in (_ev.casillas_de_tag(stage, tg) or [])}
    molde = cuerpos[MOLDE]
    salida, por_sprite = [], collections.Counter()
    for o in m.objetos:
        if o['id'] == TORNADO or (o['id'] not in mandados and o['evento'] not in con_clic
                                  and tuple(o['tile']) not in cambiables):
            continue
        # LAS VETAS. En un objeto MATOBJ el u16 del +22 es el id de
        # material.xml (en la sala 1, el 153 = Flint Ore). Sin material no
        # es una veta de verdad y no se pone.
        material = 0
        if o['id'] in vetas:
            material = struct.unpack_from('<H', crudo_mpc, m.off_objetos + o['i'] * 74 + 22)[0]
            if not material:
                continue
        # EL CUERPO. El del propio sprite si se capturo en el IGG. Si no:
        #   veta      -> el de una veta capturada (VETA_MOLDE). El de un
        #                objeto de suelo no le sirve al cliente para
        #                tratarla como veta;
        #   con evento-> el del brasero 60094, que lleva en la cola (+36..+42)
        #                la marca de "se pulsa" (40 80 14 00; en el Global,
        #                02 80 14 00, la misma que traen alli las tablillas
        #                60300). Con la cola a ceros el cliente no manda el
        #                clic: las tablillas de la sala 1 no decian nada;
        #   el resto  -> el del 60157, quieto y sin marca.
        if o['id'] in cuerpos:
            base = cuerpos[o['id']]
        elif material:
            base = cuerpos.get(VETA_MOLDE, molde)
        elif o['evento']:
            base = cuerpos.get(PULSABLE_MOLDE, molde)
        else:
            base = molde
        b = bytearray(base)
        # Con evento y la cola a ceros (el cuerpo capturado era de un mapa
        # donde ese objeto no se pulsaba, como la tablilla 60300): se le pone
        # la marca del brasero para que el cliente mande el clic.
        if o['evento'] and not material and not any(b[36:43]):
            b[36:43] = cuerpos[PULSABLE_MOLDE][36:43]
        eid = pob.BASE_OBJETO + stage * 100_000 + len(salida)
        # Igual que poblar_del_cliente.recursos_de(): la x tal cual y la y
        # desde la casilla, centrada.
        px = (o['px'][0], o['tile'][1] * 32 + 16)
        struct.pack_into('<I', b, 0, eid)
        struct.pack_into('<I', b, 4, o['capa'])
        struct.pack_into('<II', b, 8, px[0], px[1])
        struct.pack_into('<H', b, 34, o['id'])

        # Objeto con evento: marca 40 80 justo detras del sprite (+38) y el
        # cursor del evento en +40, como las antorchas capturadas
        # (dc 06 | sprite | 40 80 | 14 | 00 00). Sin eso el cliente toma el
        # objeto por decorado y no deja pulsarlo (ver Mapa.cursores).
        if o.get('evento') and len(b) >= 43 and b[38:41] == b'\0\0\0':
            _cu = getattr(m, 'cursores', {}).get(o['evento'])
            if _cu is not None:
                b[38], b[39], b[40] = 0x40, 0x80, _cu
        salida.append({'entity_id': eid, 'sprite': o['id'], 'capa': o['capa'],
                       'px': list(px), 'tile': list(o['tile']),
                       # El evento del .mpc. CHANGE_STATICOBJ cambia el objeto
                       # SIN evento de la casilla: en la Global, en (102,10)
                       # el 60094 (evento 110) sigue y la barrera de al lado
                       # pasa de 60308 a 60302.
                       'evento': o['evento'],
                       **({'material': material,
                           'nombre_visible': _nombre_material(material)}
                          if material else {}),
                       'crudo': bytes(b).hex(),
                       'copiado_de': ('cuerpo de una captura del objeto %d' % o['id']
                                      if o['id'] in cuerpos else
                                      'cuerpo de otro objeto con el sprite cambiado'),
                       'puesto_por': 'objetos_de_instancia'})
        por_sprite[o['id']] += 1
    return salida, por_sprite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, required=True)
    ap.add_argument('--poner', action='store_true')
    a = ap.parse_args()
    fichero = lg.PLANTILLAS_POR_STAGE.get(a.stage)
    if not fichero:
        raise SystemExit('el stage %d no tiene plantilla' % a.stage)
    rec, por_sprite = objetos(a.stage)
    print('%s: %d objetos de mapa' % (fichero, len(rec)))
    for s, n in sorted(por_sprite.items()):
        print('   %d x%d' % (s, n))
    if not a.poner:
        return
    f = PLANTILLAS / fichero
    d = json.loads(f.read_text(encoding='utf-8'))
    # Fuera los de antes que ya vienen aqui (mismo sprite en la misma
    # casilla): si no, salen dos veces -- le paso a la sala 2 de Gulp Room
    # con sus dos 60157.
    nuevos = {(r['sprite'], tuple(r['tile'])) for r in rec}
    viejos = [r for r in d.get('recursos') or []
              if r.get('puesto_por') != 'objetos_de_instancia'
              and (r.get('sprite'), tuple(r.get('tile') or ())) not in nuevos]
    d['recursos'] = viejos + rec
    texto = json.dumps(d, ensure_ascii=False, indent=1)
    if f.read_text(encoding='utf-8').endswith('\n'):
        texto += '\n'
    f.write_text(texto, encoding='utf-8')
    print('escrito: %d objetos (%d que ya habia)' % (len(d['recursos']), len(viejos)))


if __name__ == '__main__':
    main()
