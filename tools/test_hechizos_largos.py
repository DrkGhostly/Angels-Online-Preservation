"""Que no se pierda ningun hechizo cuando el personaje tiene muchos.

Gnash III y V se perdian una y otra vez. Son dos cosas encadenadas:

  1. La cantidad del 0x001D es un U8, asi que con mas de 255 hechizos hace
     falta mas de un mensaje.
  2. Cada cosa que se le pasa a ses.enviar() lleva delante SU PROPIO LE16 de
     largo (proto.framing.pack_submessages). Devolviendo los dos mensajes
     pegados viajaban como uno solo, y el cliente (sub_5F0EF0) lee la
     cantidad del byte +6, procesa esos 255 y tira lo que venga detras
     dentro del mismo sub-mensaje.

Asi que otorgar_hechizos tiene que devolver una LISTA y los que la llaman
tienen que desparramarla.
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ))

import clases
from proto.framing import pack_submessages, submessages


def _lo_que_lee_el_cliente(envio):
    """Los hechizos que de verdad registraria el cliente."""
    subs, _ = submessages(pack_submessages(envio))
    vistos = []
    for _op, cuerpo in subs:
        if _op != 0x001D:
            continue
        cuantos = cuerpo[4]
        for i in range(cuantos):
            vistos.append(struct.unpack_from('<I', cuerpo, 5 + i * 9 + 1)[0])
    return vistos


def test_devuelve_una_lista_de_mensajes():
    msgs = clases.otorgar_hechizos(100, list(range(1, 300)))
    assert isinstance(msgs, list), type(msgs)
    assert len(msgs) == 2, len(msgs)
    for m in msgs:
        assert m[:2] == struct.pack('<H', 0x001D)
        assert m[6] <= 255


def test_no_se_pierde_ninguno_con_mas_de_255():
    numeros = list(range(1, 285))
    leidos = _lo_que_lee_el_cliente(clases.otorgar_hechizos(100, numeros))
    assert leidos == numeros, (len(leidos), len(numeros))


def test_pegados_en_uno_se_perderian():
    """La prueba de que el fallo era el enmarcado, no el troceo."""
    numeros = list(range(1, 285))
    msgs = clases.otorgar_hechizos(100, numeros)
    leidos = _lo_que_lee_el_cliente([b''.join(msgs)])
    assert len(leidos) == 255, len(leidos)


def test_gnash_sobrevive():
    """El caso de verdad: 284 hechizos con Gnash III y V al final."""
    numeros = sorted(set(range(1, 283)) | {13123, 13125})
    leidos = _lo_que_lee_el_cliente(clases.otorgar_hechizos(100, numeros))
    assert 13123 in leidos, 'Gnash III se perdio'
    assert 13125 in leidos, 'Gnash V se perdio'
    assert len(leidos) == len(numeros)


def test_pocos_hechizos_siguen_en_un_solo_mensaje():
    msgs = clases.otorgar_hechizos(100, [1, 2, 3])
    assert len(msgs) == 1
    assert _lo_que_lee_el_cliente(msgs) == [1, 2, 3]


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
