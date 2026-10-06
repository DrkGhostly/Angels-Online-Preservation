"""Saca las COLOCACIONES de NPC de los sp_*.xml del cliente.

Los paks traen una familia de archivos -- sp_hestia.xml, sp_gear_clerk.xml,
sp2017_06_08_agvoucher.xml, sp_v12_questnpc.xml ... sp_v28_questnpc.xml --
que colocan NPC en los mapas:

    <npc id="14334" msgid="507715" eventid="0" map="41" x="181" y="98"
         dir="左下" setid="0" subset="0"/>

Es lo unico del cliente que dice DONDE va cada NPC y con que linea habla:

    id      el npc_type, que cruza con npc.xml para el nombre y el sprite
    msgid   la linea de dialogo con la que abre
    map     el stage
    x, y    la casilla
    dir     la direccion, con el DEFINE que trae cada archivo

Hay que mirar los VEINTISEIS updates, no solo el ultimo: cada archivo vive
en el pak donde se publico y los de eventos viejos no se reeditan. Fortunia
(8814), por ejemplo, esta en npc.xml pero no la coloca ningun sp_*.xml: esa
viene de la tabla base del servidor y no se puede sacar de aqui.

Uso:
    python tools/npcs_de_sp_xml.py            # resumen por mapa
    python tools/npcs_de_sp_xml.py 41         # los de un mapa
    python tools/npcs_de_sp_xml.py --json     # a plantillas/npcs_sp.json
"""
import collections
import glob
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
DIRS = {'右': 0, '右上': 1, '上': 2, '左上': 3, '左': 4, '左下': 5, '下': 6, '右下': 7}
RE_NPC = re.compile(r'<npc\s+id="(\d+)"[^>]*>')


def _es_de_colocacion(nombre: str) -> bool:
    return (nombre.startswith('sp') or 'questnpc' in nombre
            or 'replace_npc' in nombre)


def tabla_npc() -> dict:
    """npc_type -> (nombre, sprite), de TODOS los npc.xml que haya."""
    out = {}
    for f in sorted(glob.glob(str(RAIZ / 'extracted_paks' / '*' / 'setting' / 'eng' / 'npc.xml'))):
        try:
            t = pathlib.Path(f).read_text(encoding='utf-8-sig', errors='ignore')
        except OSError:
            continue
        for m in re.finditer(r'<npc [^>]*>', t):
            g = m.group(0)
            i = re.search(r'編號="(\d+)"', g)
            n = re.search(r'名稱="([^"]*)"', g)
            s = re.search(r'圖號="(\d+)"', g)
            if i and n:
                out[int(i.group(1))] = (n.group(1), int(s.group(1)) if s else 0)
    return out


def colocaciones() -> list:
    """Todas las filas <npc .../> de los sp_*.xml, sin repetir."""
    npcs = tabla_npc()
    vistos = {}
    for f in glob.glob(str(RAIZ / 'extracted_paks' / '*' / 'setting' / 'eng' / '*.xml')):
        p = pathlib.Path(f)
        if not _es_de_colocacion(p.name):
            continue
        try:
            t = p.read_text(encoding='utf-8-sig', errors='ignore')
        except OSError:
            continue
        for m in RE_NPC.finditer(t):
            g = m.group(0)
            mp = re.search(r'map="(\d+)"', g)
            x = re.search(r'x="(\d+)"', g)
            y = re.search(r'y="(\d+)"', g)
            if not (mp and x and y):
                continue
            nid = int(m.group(1))
            mid = re.search(r'msgid="(\d+)"', g)
            dr = re.search(r'dir="([^"]*)"', g)
            nom, spr = npcs.get(nid, ('?', 0))
            clave = (nid, int(mp.group(1)), int(x.group(1)), int(y.group(1)))
            vistos[clave] = {
                'npc_type': nid, 'nombre': nom, 'sprite': spr,
                'stage': int(mp.group(1)),
                'x': int(x.group(1)), 'y': int(y.group(1)),
                'dir': DIRS.get(dr.group(1) if dr else '', 6),
                'msgid': int(mid.group(1)) if mid else 0,
                'origen': p.name,
            }
    return sorted(vistos.values(), key=lambda r: (r['stage'], r['nombre']))


def main():
    args = sys.argv[1:]
    filas = colocaciones()
    if '--json' in args:
        f = RAIZ / 'server' / 'plantillas' / 'npcs_sp.json'
        f.write_text(json.dumps(
            {'_nota': 'Colocaciones de NPC sacadas de los sp_*.xml de los 26 '
                      'updates. Ver tools/npcs_de_sp_xml.py.',
             'npcs': filas}, ensure_ascii=False, indent=1), encoding='utf-8')
        print('%d colocaciones -> %s' % (len(filas), f))
        return 0
    mapas = [a for a in args if a.isdigit()]
    if mapas:
        for r in filas:
            if str(r['stage']) in mapas:
                print('%-6d %-24s sprite %-7d (%3d,%3d) dir %d  msg %-8d %s'
                      % (r['npc_type'], r['nombre'][:24], r['sprite'],
                         r['x'], r['y'], r['dir'], r['msgid'], r['origen']))
        return 0
    c = collections.Counter(r['stage'] for r in filas)
    print('%d colocaciones en %d mapas' % (len(filas), len(c)))
    for st, n in c.most_common(20):
        print('   stage %-5d %4d NPC' % (st, n))
    return 0


if __name__ == '__main__':
    sys.exit(main())
