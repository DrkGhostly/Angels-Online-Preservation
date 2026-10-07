"""Que mapas son instancias, sacado de la tabla stage de content.db.

stage.xml ya trae todo lo que hace falta para montarlas; no hay que
capturar nada ni decompilar nada para esta parte:

    平行空間      cuantas copias paralelas admite el mapa
    動態空間      si la copia se crea al entrar (instancia de verdad)
    分配類型      a quien se le asigna: 隊伍 al grupo, 個人 a cada uno
    人數          tope de gente dentro
    不可切換分流  no se puede cambiar de canal estando dentro

De los 445 mapas, 98 tienen copias paralelas y 46 son dinamicas.

Uso:
    python tools/instancias_de_stage.py           # la tabla
    python tools/instancias_de_stage.py --json    # a plantillas/instancias.json
"""
import json
import pathlib
import sqlite3
import sys

RAIZ = pathlib.Path(__file__).parent.parent
DB = RAIZ / 'corpus' / 'content.db'

ASIGNACION = {'隊伍': 'grupo', '個人': 'individual'}


def _n(x, d=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return d


def instancias() -> dict:
    if not DB.exists():
        return {}
    con = sqlite3.connect(DB)
    cols = [c[1] for c in con.execute('pragma table_info(stage)')]
    out = {}
    for r in con.execute('select * from stage'):
        d = dict(zip(cols, r))
        copias = _n(d.get('平行空間'))
        if copias <= 0:
            continue
        out[str(_n(d.get('id')))] = {
            'nombre': (d.get('name') or '').strip(),
            'copias': copias,
            'dinamica': d.get('動態空間') == '是',
            'asignacion': ASIGNACION.get(d.get('分配類型') or '', ''),
            'tope_personas': _n(d.get('人數')),
            'sin_cambio_de_canal': d.get('不可切換分流') == '是',
        }
    con.close()
    return out


def main():
    t = instancias()
    if not t:
        print('no esta %s' % DB)
        return
    if '--json' in sys.argv[1:]:
        f = RAIZ / 'server' / 'plantillas' / 'instancias.json'
        f.write_text(json.dumps(
            {'_nota': 'mapas con copias paralelas. '
                      'Ver tools/instancias_de_stage.py.',
             'mapas': dict(sorted(t.items(), key=lambda kv: int(kv[0])))},
            ensure_ascii=False, indent=1), encoding='utf-8')
        print('escrito %s (%d mapas)' % (f, len(t)))
        return
    din = {k: v for k, v in t.items() if v['dinamica']}
    print('%-6s %-30s %-7s %-11s %s' % ('id', 'nombre', 'copias', 'asignacion', 'tope'))
    for k, v in sorted(din.items(), key=lambda kv: int(kv[0])):
        print('%-6s %-30s %-7d %-11s %s' % (
            k, v['nombre'][:30], v['copias'], v['asignacion'] or '-',
            v['tope_personas'] or '-'))
    print('\n%d con copias paralelas, %d dinamicas' % (len(t), len(din)))


if __name__ == '__main__':
    main()
