"""Que dos jugadores se vean.

El servidor no tenia NADA de online, y no era cosa de las instancias: lo
estaban todos los mapas. Se comprobo buscando cualquier envio de una sesion
a otra -- no habia ni uno -- y mirando la lista de sesiones de mundo, que
solo se usaba para que la consola de GM supiera a quien darle un item.

Esto prueba la primera capa: verse, verse moverse y verse desaparecer.
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import login
import presencia


class Falsa:
    """Una sesion de mentira que solo apunta lo que se le manda."""

    def __init__(self, nombre, tile=(10, 10)):
        self.personaje = login.Personaje(nombre=nombre,
                                         tile_x=tile[0], tile_y=tile[1])
        self.enviados = []
        self.cerrada = False

    def enviar(self, *paquetes):
        self.enviados.extend(paquetes)

    def opcodes(self):
        return [struct.unpack_from('<H', b, 0)[0] for b in self.enviados]

    def limpiar(self):
        self.enviados = []


def _limpiar_registro():
    presencia._POR_MAPA.clear()


def test_el_jugador_se_manda_con_el_0x0001_y_no_con_el_0x0008():
    """El primer intento uso el 0x0008, el de los NPC, y no funciono: dos
    clientes en casillas pegadas no se veian. El bueno es el 0x0001, que
    salio de la captura del Global con tres cuentas."""
    _limpiar_registro()
    a = Falsa('Ana', (40, 50))
    paquete = presencia._spawn(a)
    assert struct.unpack_from('<H', paquete, 0)[0] == 0x0001
    cuerpo = paquete[2:]
    assert len(cuerpo) == 184, len(cuerpo)
    assert struct.unpack_from('<I', cuerpo, presencia.OFF_ENTIDAD)[0] == presencia.entidad_de(a)
    assert struct.unpack_from('<I', cuerpo, presencia.OFF_X)[0] == 40
    assert struct.unpack_from('<I', cuerpo, presencia.OFF_Y)[0] == 50
    assert cuerpo[16:19] == b'Ana', cuerpo[16:32]
    # la guild del jugador capturado no puede colarse
    assert b'Moonlights' not in cuerpo


def test_el_segundo_en_llegar_ve_al_primero_y_viceversa():
    _limpiar_registro()
    a, b = Falsa('Ana'), Falsa('Beto')
    presencia.entrar(a, 100)
    assert not a.enviados, 'al primero no hay nadie que presentarle'
    presencia.entrar(b, 100)
    assert presencia.APARECE in b.opcodes(), 'Beto no ve a Ana'
    assert presencia.APARECE in a.opcodes(), 'Ana no ve llegar a Beto'
    assert presencia.cuantos(100) == 2


def test_cada_jugador_tiene_una_entidad_distinta():
    """Los entity_id de las sesiones se repiten -- todas arrancan del mismo
    Personaje por defecto -- asi que reenviarlos tal cual haria que un
    jugador borrase al otro de la pantalla de un tercero."""
    _limpiar_registro()
    a, b = Falsa('Ana'), Falsa('Beto')
    assert a.personaje.entity_id == b.personaje.entity_id
    assert presencia.entidad_de(a) != presencia.entidad_de(b)
    assert presencia.entidad_de(a) >= presencia.BASE_ENTIDAD


def test_el_paso_de_uno_llega_al_otro_y_no_a_si_mismo():
    _limpiar_registro()
    a, b = Falsa('Ana'), Falsa('Beto')
    presencia.entrar(a, 100)
    presencia.entrar(b, 100)
    a.limpiar()
    b.limpiar()
    presencia.mover(a, 320, 320, 352, 320, 50)
    assert 0x0005 in b.opcodes(), 'Beto no ve moverse a Ana'
    assert not a.enviados, 'a Ana se le reenvio su propio paso'
    # y con la entidad publica de Ana, no con la suya
    paso = [x for x in b.enviados if struct.unpack_from('<H', x, 0)[0] == 0x0005][0]
    assert struct.unpack_from('<I', paso, 2)[0] == presencia.entidad_de(a)




def test_al_irse_se_le_borra_de_la_pantalla_del_otro():
    _limpiar_registro()
    a, b = Falsa('Ana'), Falsa('Beto')
    presencia.entrar(a, 100)
    presencia.entrar(b, 100)
    b.limpiar()
    presencia.salir(a)
    assert b.enviados, 'Beto no se entero de que Ana se fue'
    assert presencia.cuantos(100) == 1


def test_cambiar_de_mapa_te_saca_del_anterior():
    _limpiar_registro()
    a, b = Falsa('Ana'), Falsa('Beto')
    presencia.entrar(a, 100)
    presencia.entrar(b, 100)
    presencia.entrar(a, 200)          # Ana se va a otro mapa
    assert presencia.cuantos(100) == 1
    assert presencia.cuantos(200) == 1
    b.limpiar()
    presencia.mover(a, 0, 0, 32, 0)
    assert not b.enviados, 'Beto sigue viendo a Ana desde otro mapa'


def test_una_sesion_rota_no_tumba_a_las_demas():
    """Si a uno se le cae la conexion a mitad de un reenvio, el resto tiene
    que seguir viendose."""
    _limpiar_registro()

    class Rota(Falsa):
        def enviar(self, *paquetes):
            raise ConnectionResetError('se fue')

    a, mala, c = Falsa('Ana'), Rota('Mala'), Falsa('Ceci')
    presencia.entrar(a, 100)
    presencia.entrar(mala, 100)
    presencia.entrar(c, 100)
    c.limpiar()
    presencia.mover(a, 0, 0, 32, 0)
    assert 0x0005 in c.opcodes(), 'Ceci dejo de ver por culpa de la sesion rota'


def test_el_servidor_engancha_la_presencia_en_los_tres_sitios():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert '_pres.entrar(ses, p.stage)' in fuente, 'no se entra al mapa'
    assert '_pres.salir(ses)' in fuente, 'no se sale al desconectar'
    assert '_pres.mover(ses' in fuente, 'no se reenvia el movimiento'


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
