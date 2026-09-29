"""El bloque de estado de las mascotas, el s2c 0x0065.

El mapa de campos no se dedujo mirando bytes sueltos: se comparo el paquete
contra la ficha que el juego enseñaba en ese momento -- una Battlemaid de
nivel 246 con 12.100 de ataque, 15.755 de defensa, 3.137 de ataque magico,
4.431 de defensa magica, 1.947 de rigor, 1.127 de agilidad y 78 de intimidad.
Los siete numeros aparecieron en el paquete, y esos son los offsets.

Aqui se comprueba contra la captura entera, que trae seis mascotas distintas.
"""
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))

import mascotas as ms       # noqa: E402

CAPTURA = RAIZ / 'logs' / 'proxy' / 'mundo_010658_700672_orden.jsonl'


def _bloques():
    if not CAPTURA.exists():
        return []
    out = []
    for linea in CAPTURA.open(encoding='utf-8'):
        r = json.loads(linea)
        if r.get('dir') == 's2c' and r.get('opcode') == 0x65 and r.get('hex'):
            b = bytes.fromhex(r['hex'])
            if len(b) == ms.TAM:
                out.append(b)
    return out


def test_lee_la_captura_entera():
    """Las seis mascotas salen con nombre, nivel y stats coherentes."""
    bloques = _bloques()
    if not bloques:
        return                      # sin la captura no hay nada que probar
    nombres = set()
    for b in bloques:
        d = ms.leer(b)
        assert d, 'no se pudo leer un bloque de 200 bytes'
        assert d['nombre'], 'mascota sin nombre'
        assert 1 <= d['nivel'] <= 300, (d['nombre'], d['nivel'])
        assert d['hp'] <= d['hp_max'], (d['nombre'], d['hp'], d['hp_max'])
        assert d['atk'] >= 0 and d['dfs'] >= 0
        nombres.add(d['nombre'])
    assert 'Battlemaid' in nombres, nombres


def test_la_battlemaid_cuadra_con_su_ficha():
    """Los numeros que se leyeron en pantalla, uno a uno."""
    for b in _bloques():
        d = ms.leer(b)
        if d['nombre'] != 'Battlemaid':
            continue
        assert d['nivel'] == 246, d['nivel']
        assert d['atk'] == 12100, d['atk']
        assert d['dfs'] == 15755, d['dfs']
        assert d['matk'] == 3137, d['matk']
        assert d['mdef'] == 4431, d['mdef']
        assert d['rigor'] == 1947, d['rigor']
        assert d['agilidad'] == 1127, d['agilidad']
        assert d['intimidad'] == 78, d['intimidad']
        return
    # Sin captura no falla: solo no comprueba nada.


def test_ida_y_vuelta():
    """Lo que se arma se vuelve a leer igual."""
    original = {'entidad': 0x1050c6, 'tipo': 44181, 'nombre': 'Battlemaid',
                'nivel': 246, 'exp': 138901, 'exp_max': 138901,
                'hp': 18775, 'hp_max': 18775, 'mp_max': 18148,
                'atk': 12100, 'dfs': 15755, 'matk': 3137, 'mdef': 4431,
                'rigor': 1947, 'agilidad': 1127,
                'saciedad': 462, 'intimidad': 78}
    paquete = ms.armar(original)
    assert paquete[:2] == b'\x65\x00'
    assert len(paquete) == ms.TAM + 2
    vuelta = ms.leer(paquete[2:])
    for k, v in original.items():
        assert vuelta[k] == v, (k, v, vuelta[k])


def test_cada_stat_va_dos_veces():
    """El base y el efectivo, que es lo que la ventana pinta en dos columnas."""
    import struct
    b = ms.armar({'atk': 12100, 'dfs': 15755})[2:]
    for campo in ('atk', 'dfs'):
        off = ms.OFF[campo]
        uno = struct.unpack_from('<I', b, off)[0]
        dos = struct.unpack_from('<I', b, off + 4)[0]
        assert uno == dos, (campo, uno, dos)


def test_el_pienso_corriente_da_saciedad_no_stats():
    """Son dos cosas distintas y conviene no mezclarlas.

    El Pet Feed dice "Increases the satiation degree by 500" y que la mascota
    mejora cuando pasa de 100. El que sube stats es el Improved Pet Feed, que
    va por mejoras.py.
    """
    est = {'saciedad': 40, 'atk': 100}
    valor, puede = ms.alimentar(est)
    assert valor == 540 and puede
    assert est['atk'] == 100, 'el pienso corriente no toca los stats'
    # No pasa del tope.
    for _ in range(10):
        ms.alimentar(est)
    assert est['saciedad'] == ms.SACIEDAD_MAXIMA


def test_los_improved_suben_los_stats():
    """Tres piensos del 8% sobre 100 de ataque dan 124."""
    est = {'atk': 100, 'dfs': 200, 'nombre': 'X'}
    sub = ms.aplicar_mejoras(est, {'atk': 24})
    assert sub['atk'] == 124
    assert sub['dfs'] == 200, 'lo que no se toca se queda igual'
    assert est['atk'] == 100, 'la ficha guardada no se modifica'


def _entradas_reales():
    """Las entradas de 231 bytes que hay en las capturas."""
    import glob
    out = []
    for f in sorted(glob.glob(str(RAIZ / 'logs' / 'proxy' / '*.jsonl'))):
        for linea in open(f, encoding='utf-8'):
            try:
                r = json.loads(linea)
            except Exception:
                continue
            if (r.get('dir') == 's2c' and r.get('opcode') == 0x1B
                    and len(r.get('hex') or '') == 470):
                out.append(bytes.fromhex(r['hex'])[4:])
    return out


def test_la_entrada_se_reconstruye_byte_a_byte():
    """Se lee una entrada real, se vuelve a armar, y sale identica.

    Es la prueba que importa: si un offset estuviera mal, el byte saldria
    en otro sitio y esto lo cantaria. Son 63 entradas de nueve mascotas.
    """
    import struct
    reales = _entradas_reales()
    if not reales:
        return
    for real in reales:
        est = {}
        for campo, off in ms.OFF_ENTRADA.items():
            if campo == 'nombre':
                est[campo] = real[off:off + ms.LARGO_NOMBRE].split(b'\0')[0] \
                    .decode('latin1', 'replace')
            elif campo in ('sprite', 'saciedad'):
                est[campo] = struct.unpack_from('<H', real, off)[0]
            else:
                est[campo] = struct.unpack_from('<I', real, off)[0]
        assert ms.entrada(real, est) == real, est.get('nombre')


def test_el_nombre_usa_los_doce_bytes():
    """"Civet Guardi" y "Dragon's Egg" miden justo doce y no llevan cero."""
    e = ms.entrada(bytes(ms.TAM_ENTRADA), {'nombre': 'Civet Guardi'})
    off = ms.OFF_ENTRADA['nombre']
    assert e[off:off + 12] == b'Civet Guardi'


def test_la_entrada_mide_231():
    """Ni 86 ni 119: esos dos tamaños son los que cerraban el cliente."""
    e = ms.entrada(bytes(10), ms.recien_nacida('Battlemaid', 3200))
    assert len(e) == 231, len(e)


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK   ' + nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA ' + nombre + ': ' + str(e))
    print('fallos:', fallos)
    sys.exit(1 if fallos else 0)