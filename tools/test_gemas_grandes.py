"""Las gemas con id por encima de 65535 se veian como otro item.

El caso que lo destapo: un arma con cinco Purple Spar Rune engarzadas salia
en el juego con cinco renglones que decian "530 Quest Item".

    Purple Spar Rune = item 66354
    66354 & 0xFFFF   = 818
    el item 818 se llama, literalmente, "530 Quest Item"

El hueco de la entrada del inventario mide CUATRO bytes -- se midio al
perforar: las gemas caen en 62, 66 y 70, y 62 + 5*4 = 82, que es justo donde
esta el contador de huecos -- pero el id se escribia en u16. Con las tres
gemas de aquella medida (3113, 3118, 3093) daba igual porque todas caben en
dos bytes; con las modernas, no.

El id guardado en la cuenta siempre fue el bueno, asi que el BONO si se
aplicaba: era un fallo de lo que ve el jugador, no de lo que tiene.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import inventario as inv

PURPLE_SPAR_RUNE = 66354
SAPPHIRE = 3113          # una de las tres de la medida original


def test_una_gema_grande_sobrevive_al_paquete():
    e = inv.marcar_huecos(bytes(120), 5, [PURPLE_SPAR_RUNE] * 5)
    n, g = inv.leer_huecos(e)
    assert n == 5, n
    assert g == [PURPLE_SPAR_RUNE] * 5, g


def test_las_gemas_de_la_medida_original_siguen_igual():
    """La correccion no puede cambiar lo que ya funcionaba."""
    e = inv.marcar_huecos(bytes(120), 3, [3113, 3118, 3093])
    n, g = inv.leer_huecos(e)
    assert n == 3 and g == [3113, 3118, 3093], (n, g)


def test_el_hueco_mide_cuatro_bytes():
    assert inv.TAM_GEMA == 4
    assert inv.OFF_GEMAS + inv.MAX_HUECOS_ENTRADA * inv.TAM_GEMA == inv.OFF_HUECOS


def test_no_se_escribe_en_u16():
    fuente = (RAIZ / 'server' / 'inventario.py').read_text(encoding='utf-8')
    i = fuente.index('def marcar_huecos')
    trozo = fuente[i:i + 1200]
    assert "struct.pack_into('<I', b, o" in trozo, 'volvio el u16 en marcar_huecos'
    assert "'<H', b, o" not in trozo, 'volvio el u16 en marcar_huecos'


def test_los_huecos_vacios_quedan_en_cero():
    e = inv.marcar_huecos(b'\xff' * 120, 2, [PURPLE_SPAR_RUNE])
    n, g = inv.leer_huecos(e)
    assert n == 2, n
    assert g == [PURPLE_SPAR_RUNE, 0], g


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK    %s' % nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA %s: %s' % (nombre, e))
    print('fallos:', fallos)
    raise SystemExit(1 if fallos else 0)
