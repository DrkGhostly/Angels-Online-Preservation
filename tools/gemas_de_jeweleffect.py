"""Vuelca jeweleffect.xml: que stat da cada gema segun donde se engarce.

Una gema no da lo mismo en todas partes. El Broken Purple Lunar Rune (item
54573) lo dice en su propia descripcion:

    Weapon: Spell Attack +1320
    Armor:  Spell Defense +260
    Shield: Spell Defense +260

El REPARTO esta aqui, en jeweleffect.xml, y el VALOR en el item:

    影響武器      que stat da puesta en un arma      -> 魔攻
    影響盾        puesta en un escudo                -> 魔防
    影響裝備2..8  puesta en cada pieza de armadura   -> 魔防
    最低等級 / 等級上限   para que piezas vale

Cada sitio puede dar hasta TRES stats (影響武器, 影響武器2, 影響武器3).

    python tools/gemas_de_jeweleffect.py
"""
import collections
import json
import os
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
SALIDA = RAIZ / 'server' / 'plantillas' / 'gemas.json'

# Como llama el cliente a cada stat y como lo llamamos nosotros. Lo que no
# esta aqui -- resistencias, daño elemental, velocidades -- se deja con su
# nombre original: se guarda igual y ya se usara cuando toque.
STATS = {
    '\u9632\u79a6\u529b': 'dfs', 'HP': 'hp', '\u9b54\u9632': 'mdef',
    'MP': 'mp', '\u653b\u64ca\u529b': 'atk', '\u7cbe\u6e96': 'rigor',
    '\u9748\u654f': 'agilidad', '\u9b54\u653b': 'matk',
    '\u6700\u5927\u8ca0\u91cd': 'peso', '\u79fb\u52d5\u901f\u5ea6': 'velocidad',
}


def _orden(p):
    n = str(p).split(os.sep)[-4]
    if n == 'data1':
        return (0, 0)
    if n == 'update':
        return (1, 0)
    m = re.search(r'(\d+)', n)
    return (2, int(m.group(1)) if m else 0)


def cargar(raiz=None):
    """{id: {'arma': [stats], 'escudo': [...], 'equipo': {n: [...]}, ...}}."""
    raiz = pathlib.Path(raiz or RAIZ)
    crudo = {}
    for pat in ('extracted_paks/*/setting/*/jeweleffect.xml',
                'extracted_paks/*/setting/jeweleffect.xml'):
        for f in sorted(raiz.glob(pat), key=_orden):
            txt = f.read_text(encoding='utf-8', errors='replace')
            for trozo in re.findall(r'<\u5bf6\u77f3\u6548\u679c\s([^>]*?)/>',
                                    txt):
                a = dict(re.findall(r'(\S+?)="([^"]*)"', trozo))
                if a.get('\u7de8\u865f', '').isdigit():
                    crudo[int(a['\u7de8\u865f'])] = a
    out = {}
    for n, a in sorted(crudo.items()):
        def _lista(base):
            r = []
            for suf in ('', '2', '3'):
                v = a.get(base + suf)
                if v and v not in ('0', ''):
                    r.append(STATS.get(v, v))
            return r
        equipo = {}
        for k in range(2, 9):
            l = _lista('\u5f71\u97ff\u88dd\u5099%d' % k)
            if l:
                equipo[str(k)] = l
        d = {'nombre': a.get('\u540d\u7a31', ''),
             'arma': _lista('\u5f71\u97ff\u6b66\u5668'),
             'escudo': _lista('\u5f71\u97ff\u76fe'),
             'equipo': equipo}
        for campo, nom in (('\u6700\u4f4e\u7b49\u7d1a', 'nivel_min'),
                           ('\u7b49\u7d1a\u4e0a\u9650', 'nivel_max')):
            v = a.get(campo)
            if v and v.isdigit():
                d[nom] = int(v)
        if d['arma'] or d['escudo'] or d['equipo']:
            out[str(n)] = d
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t = cargar()
    if not t:
        print('no encontre ningun jeweleffect.xml en extracted_paks/')
        return 1
    SALIDA.write_text(json.dumps(t, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    c = collections.Counter()
    for d in t.values():
        for s in d['arma'] + d['escudo']:
            c[s] += 1
    print('%d gemas -> %s' % (len(t), SALIDA.relative_to(RAIZ)))
    print('stats mas dados:', dict(c.most_common(8)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
