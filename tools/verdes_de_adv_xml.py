"""Vuelca adv.xml de los paks: los rangos de los stats verdes.

Esta es la tabla que decide hasta cuanto puede dar el martillo verde en
cada pieza. Estuvo semanas sin encontrarse y se intentaron dos formulas a
ojo, las dos mal. No hay formula: es una tabla.

Cada fila es un <組合判斷> con:

    原型對應部位   la PARTE: 武器杖, 座騎, 背包, 衣服輕, 頭飾重...
    怪物等級       el nivel, de cinco en cinco
    <stat>下限 / <stat>上限   el minimo y el maximo de ese stat

Comprobado contra el juego y contra las capturas, sin una sola discrepancia:

    武器杖 nv300  HP 344, atk 2428, matk 697, agilidad 30
                  -- el cuadro del Glacier Wand enseñaba justo eso
    座騎 nv45     combate 17, rigor/agi 13, velocidad 14
                  -- 50 martillazos al Snow Evil Cat dieron 17,17,16,15,14,13,12
    座騎 nv90     combate 50, rigor/agi/velocidad 22
                  -- el cuadro del Little Seal enseñaba 0-50 y 0-22
    背包 nv45     defensa 24, peso 50-325, ranuras 10
                  -- la Green Beetle Bag dio 22 de defensa, 278 de peso y 9 casillas

Ojo con dos nombres: 精準 es el Rigor y 動態資料1 en una mochila son las
RANURAS. Y el minimo no siempre es 1: el peso de una mochila empieza en 50.

    python tools/verdes_de_adv_xml.py
"""
import collections
import json
import os
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
SALIDA = RAIZ / 'server' / 'plantillas' / 'verdes.json'

# Como se llama cada stat aqui y como lo llamamos nosotros.
STATS = {
    'HP': 'hp', 'MP': 'mp', '\u5e73\u5747\u653b\u64ca': 'atk',
    '\u9632\u79a6': 'dfs', '\u9b54\u653b': 'matk', '\u9b54\u9632': 'mdef',
    '\u7cbe\u6e96': 'rigor', '\u975c\u654f': 'agilidad',
    '\u9748\u654f': 'agilidad', '\u79fb\u52d5\u901f\u5ea6': 'velocidad',
    '\u6700\u5927\u8ca0\u91cd': 'peso', '\u52d5\u614b\u8cc7\u6599\uff11': 'ranuras',
    '\u52d5\u614b\u8cc7\u65991': 'ranuras',
    '\u63a1\u96c6\u901f\u5ea6': 'recoleccion',
    '\u88fd\u4f5c\u901f\u5ea6': 'fabricacion',
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
    """{parte: {nivel: {stat: [min, max]}}}, con la version nueva mandando."""
    raiz = pathlib.Path(raiz or RAIZ)
    # Igual que con pet.xml: todas las carpetas, no solo eng/.
    fs = (sorted(raiz.glob('extracted_paks/*/setting/*/adv.xml'), key=_orden)
          + sorted(raiz.glob('extracted_paks/*/setting/adv.xml'), key=_orden))
    crudo = {}
    for f in fs:
        txt = f.read_text(encoding='utf-8', errors='replace')
        for trozo in re.findall(r'<\u7d44\u5408\u5224\u65b7\s([^>]*?)/>', txt):
            a = dict(re.findall(r'(\S+?)="([^"]*)"', trozo))
            parte = a.get('\u539f\u578b\u5c0d\u61c9\u90e8\u4f4d')
            nivel = a.get('\u602a\u7269\u7b49\u7d1a')
            if not parte or not (nivel or '').isdigit():
                continue
            crudo[(parte, int(nivel))] = a
    out = {}
    for (parte, nivel), a in sorted(crudo.items()):
        fila = {}
        for k, v in a.items():
            for suf, i in (('\u4e0b\u9650', 0), ('\u4e0a\u9650', 1)):
                if not k.endswith(suf):
                    continue
                nom = STATS.get(k[:-len(suf)])
                if not nom or not (v or '').lstrip('-').isdigit():
                    continue
                fila.setdefault(nom, [0, 0])[i] = int(v)
        # Un stat sin tope no lo da esa pieza.
        fila = {k: v for k, v in fila.items() if v[1] > 0}
        if fila:
            out.setdefault(parte, {})[str(nivel)] = fila
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t = cargar()
    if not t:
        print('no encontre ningun adv.xml en extracted_paks/')
        return 1
    SALIDA.write_text(json.dumps(t, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    n = sum(len(v) for v in t.values())
    print('%d partes, %d filas -> %s'
          % (len(t), n, SALIDA.relative_to(RAIZ)))
    for parte in sorted(t):
        niveles = sorted(int(x) for x in t[parte])
        print('   %-10s niveles %d..%d  stats %s'
              % (parte, niveles[0], niveles[-1],
                 ','.join(sorted(t[parte][str(niveles[-1])]))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
