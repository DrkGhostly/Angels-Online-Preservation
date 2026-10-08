"""El Skill Angel: la segunda opcion contesta, no abre una pantalla.

Su 0x0012 esta capturado y dice exactamente que opciones ofrece:

    9f130000 04 000003 00 a0130000 bc160000 a1160000
    msg 5023    val      opc 5024  opc 5820  opc 5793

    5024  "I wish to change my skill."
    5820  "The limit of changing skill."
    5793  "Quit."

La 5820 es una PREGUNTA -- pregunta por el limite para cambiar de
habilidad -- y el servidor le abria la ventana de seleccion de profesion,
asi que al jugador le saltaba una pantalla de elegir clase que no habia
pedido. Lo que toca es contestarla con el 5821, que es la explicacion.
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import dialogos

MSG_ANGEL = 5023
OPC_CAMBIAR, OPC_LIMITE, OPC_SALIR = 5024, 5820, 5793
MSG_EXPLICACION = 5821
VENTANA_PROFESION = 12


def _respuesta(opcion):
    return dialogos.respuesta_a(opcion, entidad=1, val=4,
                                nombre='Skill Angel', stage=51, nivel=10)


def test_las_opciones_son_las_de_la_captura():
    import json
    d = json.loads((RAIZ / 'server' / 'plantillas' / 'dialogos_npc.json')
                   .read_text(encoding='utf-8'))
    ang = d['npcs']['Skill Angel']
    assert ang['msgid'] == MSG_ANGEL
    b = bytes.fromhex(ang['hex'])
    assert struct.unpack_from('<I', b, 0)[0] == MSG_ANGEL
    # La cabecera del 0x0012 son NUEVE bytes: el msg en el 0, el val en el
    # 4 y cuantas opciones en el 7. Las opciones empiezan en el 9.
    assert b[7] == 3, b[7]
    opciones = [struct.unpack_from('<I', b, 9 + 4 * i)[0] for i in range(3)]
    assert opciones == [OPC_CAMBIAR, OPC_LIMITE, OPC_SALIR], opciones


def test_preguntar_por_el_limite_contesta_con_la_explicacion():
    r = _respuesta(OPC_LIMITE)
    assert r, 'no contesta nada'
    primero = r[0]
    assert struct.unpack_from('<H', primero, 0)[0] == 0x0012, 'no es un dialogo'
    assert struct.unpack_from('<I', primero, 2)[0] == MSG_EXPLICACION, \
        'no contesta con el 5821'


def test_preguntar_por_el_limite_ya_no_abre_la_pantalla_de_clase():
    """El fallo que vio el usuario."""
    for b in _respuesta(OPC_LIMITE):
        if struct.unpack_from('<H', b, 0)[0] == 0x001D and len(b) >= 9:
            assert b[7] != VENTANA_PROFESION, \
                'sigue abriendo la ventana de seleccion de profesion'


def test_la_primera_opcion_sigue_abriendo_la_redistribucion():
    """Esa si es un boton y no hay que tocarla."""
    r = _respuesta(OPC_CAMBIAR)
    kinds = [b[7] for b in r
             if struct.unpack_from('<H', b, 0)[0] == 0x001D and len(b) >= 9]
    assert 10 in kinds, kinds


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
