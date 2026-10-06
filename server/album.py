"""El Album de equipo (Ctrl+B): valor de coleccion y sus bonos.

Metes piezas en el album, se CONSUMEN, y a cambio cada categoria acumula
valor. Al pasar de cada umbral se gana un bono pasivo permanente.

La tabla sale de setting/eng/collection.xml, que solo trae UPDATE8: 90
filas, nueve categorias por diez niveles, cada una con su umbral y su bono.
La novena, `total`, mira la suma de las otras ocho.

    arma  nv 1  umbral    704  ->  atk +140, matk +70
    arma  nv 10 umbral  46900  ->  atk +460, matk +230
    total nv 10 umbral 113300  ->  hp +1%, mp +1%, exp +3

Lo que el cliente NO dice es cuanto vale cada objeto al meterlo: no esta
en item.xml, ni en doll.xml, ni en itemset.xml -- lo comprobamos, y el
equipo de RE:Angels Online llego a la misma conclusion. Aqui se usa
VALOR_POR_NIVEL por el nivel del objeto, que es una suposicion nuestra y
esta marcada como tal.
"""
import json
import pathlib

# Cuanto valor de coleccion aporta un objeto por cada punto de su nivel.
# SUPOSICION: el cliente no trae este numero. Cambiarlo aqui si algun dia
# se mide.
VALOR_POR_NIVEL = 1.0

CATEGORIAS = ('arma', 'tocado', 'ropa', 'guantes', 'zapatos',
              'montura', 'accesorio', 'apariencia')

# De la categoria de item.xml a la del album.
POR_CATEGORIA_ITEM = {
    '劍': 'arma', '刀': 'arma', '斧': 'arma', '錘': 'arma', '槍': 'arma',
    '杖': 'arma', '弓箭': 'arma', '彈弓': 'arma', '影刃': 'arma',
    '頭飾': 'tocado', '衣服': 'ropa', '手套': 'guantes', '鞋子': 'zapatos',
    '座騎': 'montura', '機甲': 'montura',
    '飾品': 'accesorio', '披風': 'accesorio', '盾': 'accesorio',
    '紙娃娃': 'apariencia',
}

_TABLA = None


def tabla() -> list:
    """Las 90 filas de collection.xml, de plantillas/album.json."""
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'album.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def categoria_de(item_id: int) -> str:
    """En que pagina del album entra ese objeto, o '' si no entra."""
    try:
        import inventario as _iv
        cat = _iv.categoria_de(item_id) or ''
    except Exception:
        return ''
    for chino, nom in POR_CATEGORIA_ITEM.items():
        if chino in cat:
            return nom
    return ''


def valor_de(item_id: int) -> int:
    """Lo que aporta meter ese objeto. SUPOSICION, ver la nota de arriba."""
    try:
        import inventario as _iv
        nivel = _iv.nivel_de_item(item_id) if hasattr(_iv, 'nivel_de_item') else 0
    except Exception:
        nivel = 0
    return max(1, int(round((nivel or 1) * VALOR_POR_NIVEL)))


def nivel_alcanzado(categoria: str, valor: int) -> int:
    """El nivel mas alto de esa categoria cuyo umbral ya se paso."""
    nv = 0
    for f in tabla():
        if f['categoria'] == categoria and valor >= f['valor']:
            nv = max(nv, f['nivel'])
    return nv


def bonos(valores: dict) -> dict:
    """Los bonos que dan esos valores por categoria.

    `valores` es {categoria: valor}. Se suma el bono de la categoria y, al
    final, el de `total` con la suma de las ocho. Se acumulan los de todos
    los niveles alcanzados, no solo el ultimo.
    """
    fuera = {}

    def _sumar(b):
        for k, v in b.items():
            if isinstance(v, dict):          # {'pct': n}
                prev = fuera.get(k)
                if isinstance(prev, dict):
                    prev['pct'] = prev.get('pct', 0) + v.get('pct', 0)
                else:
                    fuera[k] = dict(v)
            else:
                prev = fuera.get(k)
                fuera[k] = (prev + v) if isinstance(prev, int) else v

    for cat in CATEGORIAS:
        val = int(valores.get(cat, 0) or 0)
        for f in tabla():
            if f['categoria'] == cat and val >= f['valor']:
                _sumar(f['bonos'])
    total = sum(int(valores.get(c, 0) or 0) for c in CATEGORIAS)
    for f in tabla():
        if f['categoria'] == 'total' and total >= f['valor']:
            _sumar(f['bonos'])
    return fuera


def resumen(valores: dict) -> dict:
    """Lo que necesita la ventana: valor y nivel de cada pagina."""
    out = {c: {'valor': int(valores.get(c, 0) or 0),
               'nivel': nivel_alcanzado(c, int(valores.get(c, 0) or 0))}
           for c in CATEGORIAS}
    total = sum(v['valor'] for v in out.values())
    out['total'] = {'valor': total, 'nivel': nivel_alcanzado('total', total)}
    return out
