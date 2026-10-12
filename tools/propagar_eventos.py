"""Escribe server/plantillas/eventos.json con los eventos de los 399 mapas.

POR QUE. Los .mpc traen la logica de misiones e instancias entera -- 11.020
disparadores, 15.842 acciones y 15.766 condiciones -- y desde que se descifro
la numeracion (tools/eventos_del_cliente.py) se puede leer. Lo que falta es
ponerla donde el servidor la alcance: server/ lee plantillas y no importa
tools/, que es la linea que separa "sacar datos del cliente" de "servir".

QUE SE GUARDA, Y POR QUE ESO Y NO MAS. Para ejecutar un evento hacen falta
cuatro cosas, y las cuatro estan en el .mpc:

    disparadores  que condiciones y que acciones, con sus parametros
    objetos       que casilla dispara que evento, y en que capa esta
    tags          a que casillas corresponde cada TAG, que es como las
                  acciones se refieren a un sitio (GOTO_TAG, GENERATE,
                  CHANGE_STATICOBJ, MAKE_TREASURE...)
    dialogos      el numero de dialogo que abre BEGIN_MESSAGE

Los dialogos NO se copian aqui: ya hay un xml de dialogos por mapa que lee
tools/mapa_del_cliente.py y un server/dialogos.py que los sirve. Aqui solo
viaja el numero.

LO QUE NO SE TOCA. portales.json sigue mandando en los portales. Los eventos
3 CHANGE_MAP y 53 GOTO_TAG estan aqui tambien porque son parte de la logica
-- un evento puede dar un objeto Y mover -- pero el que resuelve un portal
pisado sigue siendo el de siempre, medido y con sus radios ajustados. Esto
suma, no sustituye.

    python tools/propagar_eventos.py            escribe la plantilla
    python tools/propagar_eventos.py --ver 73   que hay en un mapa
"""
import argparse
import collections
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))

import eventos_del_cliente as ec
import mapa_del_cliente as mc

SALIDA = RAIZ / 'server' / 'plantillas' / 'eventos.json'


def _del_mapa(stage, ruta):
    """Lo que hace falta de un mapa, ya en la forma que lee el servidor."""
    m = mc.Mapa(stage, ruta)

    disparadores = []
    for d in ec.disparadores_del_mapa(ruta):
        if not d['acciones']:
            continue        # un disparador sin acciones no hace nada
        disparadores.append({
            'ev': d['evento'],
            'd': d['disparo'],
            'n': d['veces'],
            'si': [[n, list(p)] for n, p in d['condiciones']],
            'haz': [[n, list(p)] for n, p in d['acciones']]})

    # casilla -> evento. Solo los objetos que disparan algo; los demas son
    # decorado y hay mapas con 3.168 objetos.
    objetos = {}
    for o in m.objetos:
        if not o['evento']:
            continue
        objetos['%d,%d' % o['tile']] = [o['evento'], o['id'], o['capa']]

    tags = {str(n): [list(t) for t in pts] for n, pts in m.tags.items()}

    return {'disparadores': disparadores, 'objetos': objetos, 'tags': tags,
            'ancho': m.ancho, 'alto': m.alto}


def propagar(verboso=True):
    acciones, condiciones = ec.diccionario()
    rutas = mc.mapas_del_cliente()
    stages, fallos = {}, []
    for stage, ruta in sorted(rutas.items()):
        try:
            d = _del_mapa(stage, ruta)
        except Exception as e:                      # un mapa roto no para el resto
            fallos.append((stage, '%s: %s' % (type(e).__name__, e)))
            continue
        if d['disparadores'] or d['objetos']:
            stages[str(stage)] = d

    datos = {
        'comentario': ('Generado por tools/propagar_eventos.py desde los .mpc '
                       'del cliente. No editar a mano.'),
        'acciones': {str(k): v for k, v in sorted(acciones.items())},
        'condiciones': {str(k): v for k, v in sorted(condiciones.items())},
        'stages': stages}

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, separators=(',', ':')),
                      encoding='utf-8')

    if verboso:
        n_disp = sum(len(s['disparadores']) for s in stages.values())
        n_obj = sum(len(s['objetos']) for s in stages.values())
        n_acc = sum(len(d['haz']) for s in stages.values() for d in s['disparadores'])
        n_con = sum(len(d['si']) for s in stages.values() for d in s['disparadores'])
        print('%s   %.1f MB' % (SALIDA, SALIDA.stat().st_size / 1e6))
        print('   %d mapas, %d disparadores, %d objetos que disparan'
              % (len(stages), n_disp, n_obj))
        print('   %d acciones, %d condiciones' % (n_acc, n_con))
        por_disparo = collections.Counter(
            d['d'] for s in stages.values() for d in s['disparadores'])
        print('   por modo de disparo: %s'
              % ', '.join('%d:%d' % x for x in sorted(por_disparo.items())))
        for stage, por in fallos:
            print('   FALLO en el mapa %d: %s' % (stage, por))
    return datos


def ver(stage):
    acciones, condiciones = ec.diccionario()
    rutas = mc.mapas_del_cliente()
    if stage not in rutas:
        print('el cliente no trae el mapa %d' % stage)
        return False
    d = _del_mapa(stage, rutas[stage])
    print('mapa %d: %d disparadores, %d objetos que disparan, %d tags'
          % (stage, len(d['disparadores']), len(d['objetos']), len(d['tags'])))
    for x in d['disparadores'][:40]:
        si = ', '.join('%s%s' % (condiciones.get(n, '?%d' % n), tuple(p))
                       for n, p in x['si'])
        haz = '; '.join('%s%s' % (acciones.get(n, '?%d' % n), tuple(p))
                        for n, p in x['haz'])
        print('   ev %-6d disparo %-3d %s' % (x['ev'], x['d'],
                                              ('si ' + si) if si else ''))
        print('        -> %s' % haz)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ver', type=int)
    a = ap.parse_args()
    if a.ver is not None:
        raise SystemExit(0 if ver(a.ver) else 1)
    propagar()
    raise SystemExit(0)


if __name__ == '__main__':
    main()
