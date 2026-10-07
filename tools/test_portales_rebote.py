"""Que ningun portal devuelva al jugador nada mas llegar.

El bug: en Majestic Mansion se aparecia en (21,169), a dos casillas del
tornado de vuelta a Floral Alley, que esta en (19,171). Ese tornado DECLARA
radio 1 -- justo para que la llegada quede fuera -- pero el servidor hacia
`max(2, radio)` y lo subia a 2, con lo que el jugador aterrizaba dentro y
se iba de vuelta sin poder andar.

Y debajo habia un segundo defecto: la marca anti-rebote (portal_pisado)
caducaba a los 2 segundos de cambiar de mapa. Si la llegada caia dentro del
radio, pasados esos 2 segundos la marca se iba, el siguiente paso volvia a
encontrar el tornado y disparaba. O sea que el jugador tenia dos segundos
para salirse del radio.
"""
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import app


def _portales():
    return json.loads((RAIZ / 'server' / 'plantillas' / 'portales.json')
                      .read_text(encoding='utf-8'))['mapas']


def test_el_radio_declarado_manda():
    """Un portal que pide radio 1 tiene que valer 1, no 2."""
    por = [p for p in _portales()['399'] if p['tile'] == [19, 171]]
    assert por and por[0]['radio'] == 1, por
    # a dos casillas queda FUERA
    assert app._portal_en(399, 21, 171) is None
    assert app._portal_en(399, 19, 169) is None
    # encima y a una casilla, dentro
    assert app._portal_en(399, 19, 171) is not None
    assert app._portal_en(399, 20, 170) is not None


def test_majestic_no_devuelve_a_floral():
    """El caso reportado: la llegada no puede caer en un tornado."""
    for p in _portales()['398']:
        if p.get('destino') == 399:
            assert app._portal_en(399, *p['llegada']) is None, p['llegada']


def test_la_marca_antirebote_no_caduca():
    """No puede haber una ventana de tiempo: tiene que durar mientras se siga
    encima. Si vuelve el `> 2.0`, la llegada dentro del radio rebota otra vez."""
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    i = fuente.find('_antes = getattr(ses, ')
    assert i > 0
    trozo = fuente[max(0, i - 400):i]
    assert 'portal_pisado = None' not in trozo.split('mapa_cambiado_en')[-1], \
        'volvio la caducidad por tiempo de portal_pisado'


def test_ningun_portal_apunta_a_un_stage_que_no_existe():
    import sqlite3
    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    stages = {int(r[0]) for r in con.execute("select id from stage where id glob '[0-9]*'")}
    for s, lst in _portales().items():
        for p in lst:
            d = p.get('destino')
            if d is not None:
                assert int(d) in stages, (s, p['tile'], d)


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
