"""Equipos: invitar, aceptar y la lista, contra la captura de verdad.

Los tres ficheros mundo_141825, mundo_141841 y mundo_144108 son una sesion
del Global con tres cuentas montando un grupo: Yuki (que invita), KarmaSilk
y KarmaWeapon. De ahi sale todo el protocolo, porque de las 1.230 sesiones
anteriores del proyecto ninguna tiene un solo paquete de grupo -- quien
capturaba iba siempre solo.

El flujo, leido paquete a paquete:

    c2s 0x0017  el lider manda el NOMBRE del invitado
    s2c 0x0023  al invitado le llega el id y el nombre del lider (el cartel)
    c2s 0x0018  el invitado contesta [01][u32 0]
    s2c 0x0024  a todos les llega la lista entera

Y los tamanos del 0x0024 cuadran solos: 108, 206 y 304 bytes segun el grupo
tenia uno, dos o tres miembros, o sea 10 de cabecera y 98 por miembro.

OJO: "Moonlights" NO es un personaje, es la GUILD. Sale en el 0x0055 de esa
misma captura, con su cartel en el 0x0054.
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import equipos
import login

# Los tres de la captura, con su char_id real.
YUKI, KARMASILK, KARMAWEAPON = 877, 16591, 17068


class Falsa:
    def __init__(self, nombre, char_id, nivel=69):
        self.personaje = login.Personaje(nombre=nombre, char_id=char_id,
                                         nivel=nivel)
        self.enviados = []

    def enviar(self, *p):
        self.enviados.extend(p)

    def opcodes(self):
        return [struct.unpack_from('<H', b, 0)[0] for b in self.enviados]

    def limpiar(self):
        self.enviados = []


def _mundo(*sesiones):
    def buscar(n):
        for s in sesiones:
            if s.personaje.nombre == n:
                return s
        return None
    return buscar


def _trio():
    equipos.olvidar_todo()
    a = Falsa('Yuki', YUKI)
    b = Falsa('KarmaSilk', KARMASILK)
    c = Falsa('KarmaWeapon', KARMAWEAPON)
    return a, b, c


def test_el_cartel_lleva_el_id_y_el_nombre_del_lider():
    a, b, _ = _trio()
    ok, _ = equipos.invitar(a, 'KarmaSilk', _mundo(a, b))
    assert ok
    assert b.opcodes() == [equipos.CARTEL], b.opcodes()
    cuerpo = b.enviados[0][2:]
    assert len(cuerpo) == 38, len(cuerpo)
    assert struct.unpack_from('<I', cuerpo, 0)[0] == YUKI
    assert cuerpo[4:8] == b'Yuki'


def test_la_lista_crece_de_98_en_98_como_en_la_captura():
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    assert len(a.enviados[-1]) - 2 == 206, len(a.enviados[-1]) - 2
    equipos.invitar(a, 'KarmaWeapon', buscar)
    equipos.aceptar(c)
    assert len(a.enviados[-1]) - 2 == 304, len(a.enviados[-1]) - 2
    # y la de un solo miembro
    assert len(equipos.lista_del_grupo(YUKI)) - 2 == 304


def test_la_lista_trae_a_los_tres_con_su_id_y_su_nombre():
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    equipos.invitar(a, 'KarmaWeapon', buscar)
    equipos.aceptar(c)
    cuerpo = equipos.lista_del_grupo(YUKI)[2:]
    assert struct.unpack_from('<I', cuerpo, 5)[0] == YUKI, 'el lider'
    assert cuerpo[9] == 3, 'cuantos miembros'
    esperado = [(YUKI, b'Yuki'), (KARMASILK, b'KarmaSilk'),
                (KARMAWEAPON, b'KarmaWeapon')]
    for i, (cid, nom) in enumerate(esperado):
        o = equipos.CABECERA + i * equipos.TAM_MIEMBRO
        assert struct.unpack_from('<I', cuerpo, o)[0] == cid, (i, cid)
        assert cuerpo[o + 8:o + 8 + len(nom)] == nom, (i, nom)


def test_todos_los_miembros_reciben_la_lista():
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    a.limpiar()
    b.limpiar()
    equipos.invitar(a, 'KarmaWeapon', buscar)
    equipos.aceptar(c)
    for s, quien in ((a, 'el lider'), (b, 'el primero'), (c, 'el nuevo')):
        assert equipos.LISTA in s.opcodes(), quien + ' no recibio la lista'


def test_no_se_puede_robar_a_alguien_de_otro_grupo():
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    ok, por_que = equipos.invitar(c, 'KarmaSilk', buscar)
    assert not ok and 'grupo' in por_que, (ok, por_que)


def test_aceptar_sin_que_te_hayan_invitado_no_hace_nada():
    a, b, _ = _trio()
    assert equipos.aceptar(b) is False
    assert not equipos.grupo_de(b)


def test_si_se_va_el_lider_el_grupo_se_deshace():
    """No se sabe que paquete pasa el mando -- grouppromote va por el mismo
    0x0018 y no se capturo -- y un grupo sin lider es peor."""
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    equipos.invitar(a, 'KarmaWeapon', buscar)
    equipos.aceptar(c)
    equipos.salir(a)
    assert not equipos.grupo_de(b) and not equipos.grupo_de(c)


def test_si_se_va_un_miembro_el_grupo_sigue():
    a, b, c = _trio()
    buscar = _mundo(a, b, c)
    equipos.invitar(a, 'KarmaSilk', buscar)
    equipos.aceptar(b)
    equipos.invitar(a, 'KarmaWeapon', buscar)
    equipos.aceptar(c)
    equipos.salir(c)
    assert len(equipos.grupo_de(a)) == 2
    assert not equipos.grupo_de(c)


def test_la_accion_1_es_aceptar_y_el_resto_salir():
    a, b, _ = _trio()
    equipos.invitar(a, 'KarmaSilk', _mundo(a, b))
    assert equipos.accion(b, equipos.ACEPTAR) == 'aceptar'
    assert equipos.accion(b, 4) == 'salir'


def test_el_servidor_atiende_los_dos_opcodes():
    fuente = (RAIZ / 'server' / 'app.py').read_text(encoding='utf-8')
    assert 'opcode == 0x0017' in fuente, 'no se atiende la invitacion'
    assert 'opcode == 0x0018' in fuente, 'no se atiende la accion de grupo'
    assert '_eq.salir(ses)' in fuente, 'no se sale del grupo al desconectar'


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
