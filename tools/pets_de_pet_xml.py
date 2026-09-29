"""Vuelca pet.xml de los paks a un JSON que el servidor pueda leer.

pet.xml es la tabla que faltaba para las mascotas. Trae, por cada una:

    編號        el sprite, que es el numero que viaja en la entrada del
                inventario (+131) y en el 0x0065 (+16)
    圖號1       el TIPO, que va en el +4 del 0x0065. Dejandolo en cero el
                cliente no sabe que mascota es: la ventana salia sin nivel
                y sin dibujo
    名稱        el nombre por defecto, el de su clase
    寵物類型     con que fila de petattrib se sacan sus stats
    階段        原型 / 初階 / 中階 / 高階 / 頂階, la etapa de evolucion
    升階變化1/2  las DOS ramas a las que puede evolucionar. La 1 es la
                "mean" y la 2 la "nice" del arbol de la wiki: el Elf Egg
                (3181) va a Naughty Elf (3183) o a Flying Guy (3182)
    條件成長值   el valor de crianza que hace falta para pasar de etapa

Hay 25 versiones del fichero en los paks y ganan las nuevas, asi que se
leen en orden: data1, update, update3, UPDATE4..UPDATE21, update22 y las
siguientes. Con ese orden los trece pares sprite/tipo medidos en el proxy
cuadran los trece.

    python tools/pets_de_pet_xml.py
"""
import collections
import json
import os
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
SALIDA = RAIZ / 'server' / 'plantillas' / 'mascotas.json'

CAMPOS = {'編號': 'sprite', '圖號1': 'tipo', '名稱': 'nombre',
          '寵物類型': 'clase', '階段': 'etapa',
          '升階變化1': 'rama1', '升階變化2': 'rama2',
          '條件成長值': 'crianza', '移動速度': 'velocidad',
          '頭像編號': 'retrato'}


def _orden(p):
    """data1 primero y los update numerados despues, de menor a mayor."""
    n = str(p).split(os.sep)[-4]
    if n == 'data1':
        return (0, 0)
    if n == 'update':
        return (1, 0)
    m = re.search(r'(\d+)', n)
    return (2, int(m.group(1)) if m else 0)


def cargar(raiz=None):
    """{sprite: {...}} con todas las mascotas, la version nueva mandando."""
    raiz = pathlib.Path(raiz or RAIZ)
    # petex.xml trae doce mas con el mismo esquema (los lobos 3001+). Va
    # PRIMERO para que pet.xml pueda pisarlas si las repite.
    # TODAS las carpetas, no solo eng/: hay paks que dejan el fichero en
    # setting/ a secas o en big5/, y ganan siempre los updates mas nuevos.
    fs = []
    for pat in ('extracted_paks/*/setting/*/petex.xml',
                'extracted_paks/*/setting/petex.xml',
                'extracted_paks/*/setting/*/pet.xml',
                'extracted_paks/*/setting/pet.xml'):
        fs += sorted(raiz.glob(pat), key=_orden)
    idx = {}
    for f in fs:
        txt = f.read_text(encoding='utf-8', errors='replace')
        for trozo in re.findall(r'<pet\s([^>]*?)/>', txt):
            a = dict(re.findall(r'(\S+?)="([^"]*)"', trozo))
            if not a.get('編號', '').isdigit():
                continue
            d = {}
            for k, v in CAMPOS.items():
                val = a.get(k)
                if val is None or val == '':
                    continue
                d[v] = int(val) if val.lstrip('-').isdigit() else val
            idx[int(a['編號'])] = d
    return idx


ASPECTOS = RAIZ / 'server' / 'plantillas' / 'crianza.json'


def _mezclar(raiz, patron, etiqueta):
    """Todos los <etiqueta> de ese patron, con la version nueva mandando."""
    fs = sorted(pathlib.Path(raiz).glob(patron), key=_orden)
    idx = {}
    for f in fs:
        txt = f.read_text(encoding='utf-8', errors='replace')
        for trozo in re.findall(r'<%s\s([^>]*?)/>' % etiqueta, txt):
            a = dict(re.findall(r'(\S+?)="([^"]*)"', trozo))
            if a.get('編號', '').isdigit():
                idx[int(a['編號'])] = a
    return idx


def crianza(raiz=None):
    """Las situaciones de petaspect.xml: el sistema de crianza.

    Cada una trae una escena y TRES opciones, y cada opcion suma un
    "valor de reaccion" que va de -3 a +3. El propio texto lo dice: "las
    acciones del dueño afectaran la direccion de crecimiento del pet". Ese
    acumulado es lo que decide a cual de las dos ramas evoluciona, y el
    umbral es el 條件成長值 de cada mascota, que vale 10.

    Positivo tira de una rama y negativo de la otra; cual es cual todavia
    hay que medirlo criando una y viendo a donde sale.
    """
    raiz = pathlib.Path(raiz or RAIZ)
    idx = {}
    for pat in ('extracted_paks/*/setting/*/petaspect.xml',
                'extracted_paks/*/setting/petaspect.xml'):
        idx.update(_mezclar(raiz, pat, 'petaspect'))
    out = {}
    for n, a in sorted(idx.items()):
        out[str(n)] = {
            'tipo': int(a.get('類型') or 0),
            'texto': a.get('敘述句', ''),
            'opciones': [
                {'texto': a.get('選項%d' % k, ''),
                 'valor': int(a.get('反應值%d' % k) or 0)}
                for k in (1, 2, 3)
                if a.get('選項%d' % k)],
        }
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    idx = cargar()
    if not idx:
        print('no encontre ningun pet.xml en extracted_paks/')
        return 1
    SALIDA.write_text(json.dumps({str(k): v for k, v in sorted(idx.items())},
                                 ensure_ascii=False, indent=1),
                      encoding='utf-8')
    asp = crianza()
    ASPECTOS.write_text(json.dumps(asp, ensure_ascii=False, indent=1),
                        encoding='utf-8')
    print('%d situaciones de crianza -> %s'
          % (len(asp), ASPECTOS.relative_to(RAIZ)))
    etapas = collections.Counter(d.get('etapa') for d in idx.values())
    print('%d mascotas -> %s' % (len(idx), SALIDA.relative_to(RAIZ)))
    print('etapas:', dict(etapas))
    print('clases distintas:', len({d.get('clase') for d in idx.values()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
