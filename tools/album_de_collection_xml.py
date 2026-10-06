"""La tabla del Album (collection.xml) a plantilla.

El Album -- "Equipment album", Ctrl+B -- da bonos pasivos segun cuanto
valor de coleccion lleves acumulado en cada categoria. La tabla esta en
setting/eng/collection.xml y SOLO la trae UPDATE8: ningun pak posterior la
reedita, asi que esa es la vigente.

Son 90 filas de verdad, 9 categorias x 10 niveles, mas 90 <collection />
vacias de relleno que hay que saltar. Cada fila lleva:

    編號      el numero de fila
    等級      el nivel, de 1 a 10
    種類      la categoria
    收藏值    el valor de coleccion que hace falta para ese nivel
    說明      el texto del bono, ya desglosado
    y las columnas del bono (攻擊, 防禦, HP, MP, 精準...)

Las categorias son ocho mas el total:

    武器 arma, 頭飾 tocado, 衣服 ropa, 手套 guantes, 鞋子 zapatos,
    座騎機甲 montura/robot, 飾品披風 accesorio/capa, 紙娃娃 apariencia,
    y 總收藏值, que es la suma de las ocho.

HP y MP llevan ademas un 定義 que dice si el numero es absoluto
("最大值") o un porcentaje del maximo ("最大值百分比").

Uso:
    python tools/album_de_collection_xml.py          # resumen
    python tools/album_de_collection_xml.py --json   # a plantillas/album.json
"""
import glob
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent

CATEGORIAS = {
    '武器': 'arma', '頭飾': 'tocado', '衣服': 'ropa', '手套': 'guantes',
    '鞋子': 'zapatos', '座騎機甲': 'montura', '飾品披風': 'accesorio',
    '紙娃娃': 'apariencia', '總收藏值': 'total',
}
BONOS = {
    '攻擊': 'atk', '魔攻': 'matk', '防禦': 'dfs', '魔防': 'mdef',
    '體質抵抗': 'res_con', '心靈抵抗': 'res_spr', '雷電防禦': 'res_rayo',
    '火焰防禦': 'res_fuego', '寒冰防禦': 'res_hielo', '腐蝕防禦': 'res_corrosion',
    '重擊機率': 'critico', '精準': 'rigor', '靈敏': 'agilidad',
    '移動速度': 'velocidad', '採集速度': 'vel_recoleccion',
    '製作速度': 'vel_fabricacion', '負重': 'peso', '經驗加ubleX': 'exp',
    '經驗加倍': 'exp', 'HP': 'hp', 'MP': 'mp',
}


def _origen() -> pathlib.Path:
    f = sorted(glob.glob(str(RAIZ / 'extracted_paks' / '*' / 'setting' / 'eng' / 'collection.xml')))
    return pathlib.Path(f[-1]) if f else None


def filas() -> list:
    f = _origen()
    if f is None:
        return []
    t = f.read_text(encoding='utf-8-sig', errors='ignore')
    out = []
    for crudo in re.findall(r'<collection [^>]*>', t):
        cat = re.search(r'種類="([^"]*)"', crudo)
        if not cat:
            continue                      # las <collection /> de relleno
        fila = {
            'id': int(re.search(r'編號="(\d+)"', crudo).group(1)),
            'nivel': int(re.search(r'等級="(\d+)"', crudo).group(1)),
            'categoria': CATEGORIAS.get(cat.group(1), cat.group(1)),
            'valor': int(re.search(r'收藏值="(\d+)"', crudo).group(1)),
            'bonos': {},
        }
        for chino, nom in BONOS.items():
            m = re.search(chino + r'="(-?\d+)"', crudo)
            if not m:
                continue
            v = int(m.group(1))
            d = re.search(chino + r'定義="([^"]*)"', crudo)
            # El 最大值百分比 es por ciento del maximo; el 最大值, absoluto.
            fila['bonos'][nom] = ({'pct': v} if d and '百分比' in d.group(1)
                                  else v)
        txt = re.search(r'說明="([^"]*)"', crudo)
        fila['texto'] = txt.group(1) if txt else ''
        out.append(fila)
    return sorted(out, key=lambda r: (r['categoria'], r['nivel']))


def main():
    f = filas()
    if '--json' in sys.argv[1:]:
        d = RAIZ / 'server' / 'plantillas' / 'album.json'
        d.write_text(json.dumps(
            {'_nota': 'Tabla del Album, de setting/eng/collection.xml '
                      '(solo UPDATE8 lo trae). Ver '
                      'tools/album_de_collection_xml.py.',
             'filas': f}, ensure_ascii=False, indent=1), encoding='utf-8')
        print('%d filas -> %s' % (len(f), d))
        return 0
    print('origen: %s' % _origen())
    print('%d filas' % len(f))
    for cat in ('arma', 'apariencia', 'total'):
        g = [r for r in f if r['categoria'] == cat]
        if not g:
            continue
        print('\n  %s: niveles %d..%d, valor %d..%d'
              % (cat, g[0]['nivel'], g[-1]['nivel'], g[0]['valor'], g[-1]['valor']))
        for r in (g[0], g[-1]):
            print('     nv %-3d valor %-7d %s' % (r['nivel'], r['valor'], r['texto'][:52]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
