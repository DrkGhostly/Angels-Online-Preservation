"""La cadencia del golpe basico: perdonar al cliente sin regalar daño.

El cliente pide el siguiente basico con su propio reloj y llega adelantado
por poco. Tirarle el golpe costaba carisimo, porque no reintenta enseguida
sino a los ~1,5 s. Ahora se le perdona un margen, pero apuntando la deuda:
el siguiente espera lo que no espero este.

Lo que se comprueba aqui es lo unico que de verdad importa: que el ritmo
medio NUNCA quede por debajo de la cadencia, o seria subir el daño por la
puerta de atras.
"""
import random
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'server'))
import app

CAD = 1.15
REINTENTO = 1.5


def _simular(periodo, jitter, margen, n=400, semilla=7):
    """Devuelve los segundos medios entre golpes que de verdad salen."""
    rnd = random.Random(semilla)
    ultimo, prox, golpes, t0, t = -99.0, 0.0, 0, None, 0.0
    while golpes < n:
        t = prox
        espera = t - ultimo
        if espera < CAD - CAD * margen:
            prox = t + REINTENTO
            continue
        ultimo = t + (CAD - espera) if espera < CAD else t
        if t0 is None:
            t0 = t
        golpes += 1
        prox = t + max(0.05, periodo + rnd.uniform(-jitter, jitter))
    return (t - t0) / (golpes - 1)


def test_el_margen_existe_y_es_moderado():
    assert 0 < app.MARGEN_CADENCIA <= 0.25, app.MARGEN_CADENCIA


def test_nunca_pega_mas_rapido_que_la_cadencia():
    """Ni con jitter ni con un cliente que pida siempre adelantado."""
    for periodo, jitter in ((CAD, 0.12), (1.03, 0.0), (0.90, 0.05), (0.5, 0.0)):
        medio = _simular(periodo, jitter, app.MARGEN_CADENCIA)
        assert medio >= CAD, (periodo, jitter, medio)


def test_con_el_margen_se_pega_mas_seguido_que_sin_el():
    """Que sirva para algo: con jitter normal tiene que mejorar."""
    sin = _simular(CAD, 0.12, 0.0)
    con = _simular(CAD, 0.12, app.MARGEN_CADENCIA)
    assert con < sin, (con, sin)


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK   %s' % nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA %s: %s' % (nombre, e))
    print('fallos:', fallos)
