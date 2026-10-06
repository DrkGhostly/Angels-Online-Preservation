"""Las tablas de los sistemas del README de RE:Angels Online, a plantillas.

Saca a server/plantillas/ las tablas que el cliente trae y que hacen falta
para Logros, Cartas, Misiones, Mapas del tesoro y Star Blessing. El Album
va aparte, en tools/album_de_collection_xml.py.

Lee SIEMPRE el pak vigente (tools/paks.py). Eso no es un detalle: con el
orden alfabetico se leia card.xml de update3 en vez de update25 y
quest.xml de update3 en vez de update26, o sea 459 cartas contadas como
121 y 1.489 misiones contadas como 476.

Uso:
    python tools/tablas_sistemas.py          # resumen
    python tools/tablas_sistemas.py --json   # escribe las plantillas
"""
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
import paks

# archivo, etiqueta de fila, nombre de la plantilla, y como se llama cada
# columna que nos interesa.
TABLAS = {
    'logros': ('achievement.xml', '成就', {
        '編號': 'id', '主類別': 'categoria', '次類別': 'subcategoria',
        '名稱': 'nombre', '規則': 'regla', '參數1': 'param1', '參數2': 'param2',
        '積分': 'puntos', '封號': 'titulo', '說明': 'texto',
        '顯示': 'visible', '廣播': 'anuncia',
    }),
    'cartas': ('card.xml', 'card', {
        '編號': 'id', '圖號': 'sprite', '卡片名稱': 'nombre',
        '星等': 'estrellas', '類別': 'categoria',
        '卡片說明': 'texto', '卡片提示': 'pista',
    }),
    'misiones': ('quest.xml', '任務', {
        '編號': 'id', '任務名稱': 'nombre', '任務類型': 'tipo',
        '任務前言': 'intro', '承接人員': 'quien',
    }),
    'mapas_tesoro': ('treasuremap.xml', '藏寶圖', {
        '編號': 'id', '名稱': 'nombre', '掉寶資料': 'drop',
        '寶箱圖形': 'sprite_cofre',
    }),
    'estrellas': ('star_client.xml', '星牌資訊', {
        '編號': 'id', '階級': 'rango', '牌名': 'nombre', '等級': 'nivel',
        '主能力': 'stat', '主數值': 'valor', '副能力': 'stat2',
        '副數值': 'valor2', '轉化獲得': 'da_al_convertir',
        '升級所需': 'cuesta_subir', '群組': 'grupo',
    }),
}
# Columnas numeradas: 場景01.., 觸發點01.., 步驟01.., 地點01..
REPETIDAS = {
    'mapas_tesoro': {'場景': 'escenas', '觸發點': 'puntos'},
    'misiones': {'步驟': 'pasos', '地點': 'lugares', '承接': 'entrega'},
}


def extraer(clave: str) -> dict:
    archivo, tag, cols = TABLAS[clave]
    t = paks.texto(archivo)
    pak = paks.pak_de(paks.vigente(archivo)) if paks.vigente(archivo) else '?'
    filas = []
    for crudo in re.findall(r'<%s [^>]*>' % tag, t):
        fila = {}
        for chino, nom in cols.items():
            m = re.search(chino + r'="([^"]*)"', crudo)
            if m is None:
                continue
            v = m.group(1)
            fila[nom] = int(v) if v.isdigit() else v
        for prefijo, nom in REPETIDAS.get(clave, {}).items():
            vs = re.findall(prefijo + r'\d+="([^"]*)"', crudo)
            if vs:
                fila[nom] = [int(x) if x.isdigit() else x for x in vs]
        if fila:
            filas.append(fila)
    return {'_origen': '%s (%s)' % (archivo, pak), 'filas': filas}


def main():
    escribir = '--json' in sys.argv[1:]
    for clave in TABLAS:
        d = extraer(clave)
        print('%-14s %-28s %5d filas' % (clave, d['_origen'], len(d['filas'])))
        if d['filas']:
            ej = d['filas'][0]
            print('               ej: %s' % {k: ej[k] for k in list(ej)[:5]})
        if escribir:
            f = RAIZ / 'server' / 'plantillas' / ('%s.json' % clave)
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
            print('               -> %s' % f.name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
