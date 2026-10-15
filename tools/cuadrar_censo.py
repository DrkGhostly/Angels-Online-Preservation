"""Cuadra los monstruos de una plantilla de instancia con lo que declara el cliente.

POR QUE. Entre quitar_oleadas.py (que quita lo que sale por evento a RADIO de
su punto) y mover los monstruos fuera del suelo a la casilla interior mas
cercana, quedaban sobrando bichos de zonas de evento -- los que el reparto
habia alejado de su punto -- y faltando otros normales que estaban junto a un
punto de evento. En Poker Castle: 30 Cursed Berry Killer y 28 Fruit Guardian
de mas, 6 Diamond y 3 Club Poker Spearman de menos.

QUE HACE, por tipo de monstruo:
  * sobran -> se quitan los mas cercanos a un punto de zona de evento de ese
    tipo (los que mas pinta tienen de ser de la oleada);
  * faltan -> se ponen junto a sus generadores normales, en suelo interior
    (la casilla y sus ocho vecinas se pisan), separados de los demas.

El censo esperado es el mismo que mira tools/test_instancias.py: generadores
del .mpc fuera de las zonas de evento, con el tope por generador, y lo que la
plantilla haya recortado a proposito ('recortados').

    python tools/cuadrar_censo.py --stage 158            ver
    python tools/cuadrar_censo.py --stage 158 --poner    escribir
"""
import argparse
import collections
import importlib.util
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
import mapa_del_cliente as cli          # noqa: E402
import poblar_del_cliente as pob        # noqa: E402

_sp = importlib.util.spec_from_file_location('login_servidor', RAIZ / 'server' / 'login.py')
sys.path.insert(1, str(RAIZ / 'server'))
import login as lg                      # noqa: E402
_st = importlib.util.spec_from_file_location('transitable_servidor',
                                             RAIZ / 'server' / 'transitable.py')
tr = importlib.util.module_from_spec(_st)
_st.loader.exec_module(tr)


def esperado(stage, d):
    cat = pob._catalogo()
    de_evento = pob.zonas_de_evento(stage) if 'OLEADAS' in d.get('_nota', '') else set()
    cuenta, gens, eventos = collections.Counter(), collections.defaultdict(list), collections.defaultdict(list)
    for g in cli.mapa(stage).generadores():
        if g['tipo'] not in cat:
            continue
        nombre = cat[g['tipo']][0]
        puntos = g['puntos'] or [g['tile']]
        if g.get('zona') in de_evento:
            eventos[nombre].extend(puntos)
            continue
        cuenta[nombre] += max(1, min(pob.TOPE_POR_GENERADOR, g['cantidad']))
        gens[nombre].append((g['tipo'], puntos))
    for nombre, n in (d.get('recortados') or {}).items():
        cuenta[nombre] = n
    return cuenta, gens, eventos


def cuadrar(stage):
    f = RAIZ / 'server' / 'plantillas' / lg.PLANTILLAS_POR_STAGE[stage]
    d = json.loads(f.read_text(encoding='utf-8'))
    quiere, gens, eventos = esperado(stage, d)
    propios = [e for e in d['spawns'] if e.get('puesto_por') != 'npcs_del_cliente']
    tiene = collections.Counter(e['nombre'] for e in propios)

    def interior(t):
        return all(tr.se_pisa(stage, t[0] + dx, t[1] + dy)
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    ocupadas = {tuple(e['tile']) for e in d['spawns']}
    quitar, nuevos, informe = set(), [], []
    for nombre in sorted(set(tiene) | set(quiere)):
        dif = tiene[nombre] - quiere[nombre]
        if dif > 0:
            cand = [e for e in propios if e['nombre'] == nombre]
            pts = eventos.get(nombre) or []
            cand.sort(key=lambda e: min((max(abs(e['tile'][0] - q[0]), abs(e['tile'][1] - q[1]))
                                         for q in pts), default=10 ** 6))
            for e in cand[:dif]:
                quitar.add(id(e))
                ocupadas.discard(tuple(e['tile']))
            informe.append('   - %s x%d' % (nombre, dif))
        elif dif < 0:
            modelo = next((e for e in d['spawns'] if e['nombre'] == nombre), None)
            if modelo is None:
                informe.append('   ? %s x%d (no hay modelo en la plantilla)' % (nombre, -dif))
                continue
            puestos = 0
            for tipo, pts in gens.get(nombre) or []:
                for base in pts:
                    if puestos >= -dif:
                        break
                    for r in range(0, 12):
                        hecho = False
                        for dx in range(-r, r + 1):
                            for dy in range(-r, r + 1):
                                t = (base[0] + dx, base[1] + dy)
                                if max(abs(dx), abs(dy)) != r or t in ocupadas or not interior(t):
                                    continue
                                if any((t[0] + a, t[1] + b) in ocupadas for a in (-1, 0, 1) for b in (-1, 0, 1)):
                                    continue
                                e = dict(modelo)
                                e['tile'] = [t[0], t[1]]
                                e['entity_id'] = max(x['entity_id'] for x in d['spawns'] + nuevos) + 1
                                e.pop('apagado', None)
                                nuevos.append(e)
                                ocupadas.add(t)
                                puestos += 1
                                hecho = True
                                break
                            if hecho:
                                break
                        if hecho:
                            break
            informe.append('   + %s x%d (puestos %d)' % (nombre, -dif, puestos))
    d['spawns'] = [e for e in d['spawns'] if id(e) not in quitar] + nuevos
    return d, f, informe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, required=True)
    ap.add_argument('--poner', action='store_true')
    a = ap.parse_args()
    d, f, informe = cuadrar(a.stage)
    print('%s: %s' % (f.name, 'ya cuadra' if not informe else 'ajustes'))
    for linea in informe:
        print(linea)
    if a.poner and informe:
        d['_nota'] = d.get('_nota', '') + (' CENSO (15/10/2026): cuadrado con lo que declara el '
                                           'cliente (tools/cuadrar_censo.py).')
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
        print('escrito: %d spawns' % len(d['spawns']))


if __name__ == '__main__':
    main()
