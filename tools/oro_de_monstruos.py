"""Cuanto oro suelta cada monstruo, de serv_drop.xml.

El servidor daba `random.randint(3, 8)` para TODO bicho, sin mirar cual era
ni de que nivel: por eso un monstruo de Bearscape soltaba lo mismo que un
Slarm del Lyceum.

El dato real esta en serv_drop.xml, en dos columnas por tabla de drop:

    平均金錢   el oro medio
    金錢變數   cuanto varia arriba y abajo

Lo trae UPDATE9, que es el ultimo pak con ese archivo, y cubre 1.968
tablas. Para los monstruos sin dato -- casi todo por encima del nivel 200 --
se usa la MEDIANA de su tramo de diez niveles, sacada de los que si lo
tienen; y por encima del ultimo tramo con muestras suficientes se
extrapola, porque la serie crece de forma limpia:

    180: 849    190: 1019    200: 1175    210: 1410

que es casi 1,2 por cada diez niveles. El tramo 220 se descarta a
proposito: da 25.866 con tres muestras y rompe la progresion.

Uso:
    python tools/oro_de_monstruos.py          # resumen
    python tools/oro_de_monstruos.py --json   # a plantillas/oro_monstruos.json
"""
import json
import pathlib
import re
import sqlite3
import statistics
import sys

RAIZ = pathlib.Path(__file__).parent.parent
MUESTRAS_MIN = 3          # tramos con menos muestras no son de fiar
FACTOR_TRAMO = 1.2        # lo que crece el oro cada diez niveles


def _de_serv_drop() -> dict:
    """drop_id -> [oro medio, variacion], de serv_drop.xml."""
    f = RAIZ / 'extracted_paks' / 'UPDATE9' / 'setting' / 'eng' / 'serv_drop.xml'
    if not f.exists():
        return {}
    t = f.read_text(encoding='utf-8-sig', errors='ignore')
    out = {}
    for m in re.finditer(r'<drop [^>]*>', t):
        g = m.group(0)
        i = re.search(r'編號="(\d+)"', g)
        a = re.search(r'平均金錢="(\d+)"', g)
        v = re.search(r'金錢變數="(\d+)"', g)
        if i and a and int(a.group(1)) > 0:
            out[i.group(1)] = [int(a.group(1)), int(v.group(1)) if v else 0]
    return out


def _monstruos() -> list:
    db = RAIZ / 'corpus' / 'content.db'
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    fuera = []
    for lvl, did, mid in con.execute(
            'select level, drop_id, id from monster '
            'where drop_id is not null and level is not null'):
        if str(lvl).isdigit() and str(did).isdigit():
            fuera.append((int(lvl), str(did), str(mid)))
    return fuera


def tabla() -> dict:
    oro = _de_serv_drop()
    mons = _monstruos()

    # Mediana por tramo de diez niveles, con los que tienen dato.
    bandas = {}
    for nv, did, _mid in mons:
        if did in oro:
            bandas.setdefault((nv // 10) * 10, []).append(oro[did][0])
    med = {b: int(statistics.median(v))
           for b, v in bandas.items() if len(v) >= MUESTRAS_MIN}

    # Donde se acaban las muestras de fiar, se extrapola.
    if med:
        tope = max(med)
        # El ultimo tramo puede ser un valor suelto: se corta donde la serie
        # deja de crecer con sensatez.
        anteriores = sorted(b for b in med if b < tope)
        if anteriores and med[tope] > med[anteriores[-1]] * 5:
            del med[tope]
            tope = max(med)
        v = med[tope]
        for b in range(tope + 10, 510, 10):
            v = int(round(v * FACTOR_TRAMO))
            med[b] = v

    por_monstruo = {}
    for nv, did, mid in mons:
        if did in oro:
            por_monstruo[mid] = oro[did]
    return {'por_monstruo': por_monstruo,
            'por_tramo': {str(k): med[k] for k in sorted(med)}}


def main():
    t = tabla()
    if '--json' in sys.argv[1:]:
        f = RAIZ / 'server' / 'plantillas' / 'oro_monstruos.json'
        f.write_text(json.dumps(
            {'_nota': 'Oro por monstruo, de serv_drop.xml (UPDATE9). '
                      'Ver tools/oro_de_monstruos.py.',
             **t}, ensure_ascii=False, indent=1), encoding='utf-8')
        print('%d monstruos con dato, %d tramos -> %s'
              % (len(t['por_monstruo']), len(t['por_tramo']), f))
        return 0
    print('monstruos con oro propio: %d' % len(t['por_monstruo']))
    print('tramos de nivel: %d' % len(t['por_tramo']))
    for b in sorted(t['por_tramo'], key=int):
        if int(b) % 50 == 0 or int(b) in (210, 220):
            print('   nivel %-4s %8d de oro' % (b, t['por_tramo'][b]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
