"""El comando de GM que da objetos: /item <id> [cantidad].

Los ids salen de items.html, el catalogo que lleva el repo. Lo que se
comprueba aqui es que el comando no se invente nada: que use el mismo camino
que el botin -- _meter, _refrescar y el cartel de clases.aviso -- y que no
cree una casilla cuando el id no existe.

Hay tres maneras de mandarlo y las tres pasan por _gm_parsear: dentro del
juego, por la consola del servidor y por data/gm.txt.
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ / 'proto'))

import app          # noqa: E402
import clases       # noqa: E402


class _Ses:
    """Lo minimo que toca el comando de una sesion de verdad."""

    def __init__(self):
        self.rol = 'mundo'
        self.inventario = {}
        self.cantidades = {}
        self.enviado = []
        self.usuario = None
        self.instancias = {}
        self.personaje = type('P', (), {
            'char_id': 4794, 'entity_id': 0x11e, 'nombre': 'Prueba',
            'inventario': self.inventario, 'cantidades': self.cantidades,
            'stage': 258, 'nivel': 1, 'oro': 0})()

    def enviar(self, *m):
        self.enviado += list(m)


def test_parseo():
    """Las formas que acepta y las que no."""
    assert app._gm_parsear('/item 19826 10') == ('item', 19826, 10)
    assert app._gm_parsear('item 19826') == ('item', 19826, 1)
    assert app._gm_parsear('/give 10 3') == ('item', 10, 3)
    assert app._gm_parsear('/i 10') == ('item', 10, 1)
    assert app._gm_parsear('/help') == ('help',)
    assert app._gm_parsear('hola') is None
    assert app._gm_parsear('/item')[0] == 'err'
    assert app._gm_parsear('/item abc')[0] == 'err'


def test_no_confunde_paquetes_binarios():
    """Husmear el cuerpo no puede tragarse paquetes que no son texto.

    El opcode del chat no se conoce, asi que el comando mira cuatro offsets
    buscando ASCII. Si eso fuera laxo, un movimiento o un ataque acabarian
    tratados como comando y el paquete se perderia.
    """
    assert app._gm_texto(b'') is None
    assert app._gm_texto(bytes([1, 2, 3, 0xff, 0x80])) is None
    assert app._gm_texto(struct.pack('<HHH', 5200, 2383, 50)) is None
    # Y el texto sale este donde este dentro del cuerpo.
    assert app._gm_texto(b'/item 10\x00') == '/item 10'
    assert app._gm_texto(b'\x00\x00/item 10\x00') == '/item 10'


def test_da_el_item_y_avisa():
    """Un id bueno entra en la mochila, con su cartel y su 0x001B."""
    ses = _Ses()
    msg = app._gm_dar_item(ses, 10, 1)          # FreshmanSabre
    assert msg.startswith('dado '), msg
    assert 10 in ses.inventario.values(), ses.inventario
    ranura = [r for r, i in ses.inventario.items() if i == 10][0]
    assert ranura >= 20, 'la mochila empieza en la 20, no en el equipo'
    ops = [struct.unpack_from('<H', m, 0)[0] for m in ses.enviado]
    assert 0x000D in ops, 'falta el cartel de "obtuviste"'
    assert 0x001B in ops, 'falta el refresco de la casilla'
    assert 0x001A not in ops, 'no hay que reenviar el inventario entero'


def test_cantidad_y_tope():
    """La cantidad se respeta y se corta en 9999."""
    ses = _Ses()
    app._gm_dar_item(ses, 19826, 25)
    assert 25 in ses.cantidades.values(), ses.cantidades
    ses2 = _Ses()
    app._gm_dar_item(ses2, 19826, 99999)
    assert max(ses2.cantidades.values()) == 9999


def test_id_que_no_existe_no_toca_nada():
    """Lo que motivo la comprobacion: un id inventado no puede crear casilla."""
    ses = _Ses()
    msg = app._gm_dar_item(ses, 999999, 1)
    assert not msg.startswith('dado '), msg
    assert ses.inventario == {}, ses.inventario
    assert ses.enviado == []


def test_sin_personaje():
    """Antes de entrar al mundo no se da nada."""
    ses = _Ses()
    ses.personaje = None
    assert not app._gm_dar_item(ses, 10, 1).startswith('dado ')


def test_la_linea_de_consola_elige_la_sesion():
    """La de consola y la de gm.txt van a la ultima sesion con personaje."""
    srv = app.Servidor.__new__(app.Servidor)
    srv.mundos = []
    assert 'no hay personaje' in srv._gm_ejecutar_linea('item 10')
    vacia = _Ses()
    vacia.personaje = None
    buena = _Ses()
    srv.mundos = [vacia, buena]
    assert srv._sesion_mundo() is buena
    assert srv._gm_ejecutar_linea('item 10').startswith('GM dado ')
    assert 10 in buena.inventario.values()


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
