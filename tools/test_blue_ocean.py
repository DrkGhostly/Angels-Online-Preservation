"""Las dos instancias de Atlantis: Lost Region y Horrible Lost Region.

Blue Ocean (stage 90) tiene TRES tornados. Dos estaban medidos cruzandolos --
a Wave Harbor y a Sunken Ruins -- y el tercero, el de (294,14), llevaba en
null desde entonces con la nota "quedan sin destino (18,4) y (294,14)".

Y es el raro de todos los que se han abierto hasta ahora: NO VIAJA. Su unica
accion es abrir el dialogo 3 del propio mapa, y es ese dialogo el que decide
a donde vas:

    dialogo 3  msg 65385 "Noises of fighting come from the front. You have
                          gotten very close to the Lost Region."
      opcion 65386 "I want to enter the Lost Region"
        -> 1000052 -> si EVENT_COND 22 (PARA_ENTER) de 98
                      -> 1000054 -> CHANGE_MAP(98, 1)
                      si no -> 1000055 -> aviso 1889
      opcion 65387 "I want to enter the Horrible Lost Region"
        -> 1000053 -> ... -> CHANGE_MAP(101, 1)

Los textos son del msg.xml del cliente y dicen exactamente lo que el usuario
describio: dos instancias dentro del mismo portal.

La condicion 22 es la que mira si cabe alguien en la copia de la instancia.
No se modela: aqui siempre se deja entrar.
"""
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ / 'tools'))
import app
import login
import mapa_del_cliente as cli
import propagar_portales as prop

BLUE_OCEAN = 90
LOST, HORRIBLE = 98, 101


def _portales(stage):
    return json.loads((RAIZ / 'server' / 'plantillas' / 'portales.json')
                      .read_text(encoding='utf-8'))['mapas'][str(stage)]


def _menu():
    m = [p for p in _portales(BLUE_OCEAN) if p.get('preguntar')]
    assert len(m) == 1, m
    return m[0]


def test_las_dos_medidas_de_blue_ocean_siguen_intactas():
    por = {tuple(p['tile']): p for p in _portales(BLUE_OCEAN)}
    assert por[(18, 4)]['destino'] == 91 and por[(18, 4)]['llegada'] == [272, 161]
    assert por[(285, 173)]['destino'] == 89 and por[(285, 173)]['llegada'] == [34, 39]


def test_el_tercer_tornado_ya_no_esta_en_null():
    """Era el unico que quedaba sin resolver en Blue Ocean."""
    p = [x for x in _portales(BLUE_OCEAN) if x['tile'] == [294, 14]]
    assert p, 'desaparecio el tornado de (294,14)'
    assert p[0]['preguntar'] is True, 'tiene que preguntar, no viajar'
    assert p[0]['destino'] is None, 'el destino lo decide la opcion'
    assert p[0]['destinos'], 'sin destinos por opcion'


def test_el_menu_es_el_del_cliente():
    """Mensaje y opciones salen del dialogo 3 de map090.mpc, no de una captura."""
    menu = cli.mapa(BLUE_OCEAN).menu_de(3)
    assert menu, 'el dialogo 3 ya no se resuelve como menu'
    p = _menu()
    assert p['msg'] == menu['msg'] == 65385, (p['msg'], menu['msg'])
    assert p['opciones'] == [o['msg'] for o in menu['opciones']] == [65386, 65387]
    assert p['acciones'] == [o['siguiente'] for o in menu['opciones']]


def test_cada_opcion_lleva_a_su_instancia():
    p = _menu()
    assert p['destinos']['65386']['destino'] == LOST
    assert p['destinos']['65387']['destino'] == HORRIBLE
    for op, d in p['destinos'].items():
        assert tuple(d['llegada']) in cli.llegada(d['destino'], 1), (op, d)


def test_pisar_el_tornado_abre_el_menu_y_no_viaja():
    """Un portal que pregunta NO se filtra por tener el destino en null: eso
    ya se rompio una vez y dejo sin funcionar los menus de Shuwa y Bayan."""
    por = app._portal_en(BLUE_OCEAN, 294, 14)
    assert por is not None, 'el tornado con menu no dispara al pisarlo'
    assert por.get('preguntar')


def test_las_dos_instancias_vuelven_a_blue_ocean():
    for st in (LOST, HORRIBLE):
        p = _portales(st)
        assert len(p) == 1, (st, len(p))
        assert p[0]['destino'] == BLUE_OCEAN
        assert p[0]['llegada'] == [289, 18], p[0]['llegada']


def test_jumpmap_confirma_la_vuelta():
    """Segunda fuente: la fila 85 de jumpmap.xml, de categoria 19 Instance."""
    jm = prop.jumpmap()
    assert (289, 18) in jm.get(BLUE_OCEAN, []), jm.get(BLUE_OCEAN)
    assert (289, 18) in cli.llegada(BLUE_OCEAN, 3)


def test_las_dos_instancias_estan_pobladas():
    esperado = {LOST: 278, HORRIBLE: 352}
    for st in (LOST, HORRIBLE):
        assert st in login.PLANTILLAS_POR_STAGE, st
        d = json.loads((RAIZ / 'server' / 'plantillas'
                        / login.PLANTILLAS_POR_STAGE[st])
                       .read_text(encoding='utf-8'))
        assert d['stage'] == st
        mobs = sum(1 for e in d['spawns'] if e.get('monstruo'))
        assert mobs == esperado[st], (st, mobs, esperado[st])
        m = cli.mapa(st)
        for e in d['spawns']:
            x, y = e['tile']
            assert 0 <= x < m.ancho and 0 <= y < m.alto, (st, e['tile'])


def test_la_horrible_es_la_version_dura():
    """Mismo mapa, bichos distintos: si salieran los mismos, algo se cruzo."""
    def clases(st):
        d = json.loads((RAIZ / 'server' / 'plantillas'
                        / login.PLANTILLAS_POR_STAGE[st])
                       .read_text(encoding='utf-8'))
        return {e['nombre'] for e in d['spawns']}
    a, b = clases(LOST), clases(HORRIBLE)
    assert cli.mapa(LOST).ancho == cli.mapa(HORRIBLE).ancho
    assert len(a & b) <= 2, sorted(a & b)
    assert 'Mermaid' in a and 'Scale Captain' in b, (sorted(a), sorted(b))


def test_ninguna_llegada_cae_en_un_tornado():
    for st in (BLUE_OCEAN, LOST, HORRIBLE):
        for p in _portales(st):
            for d in ([{'destino': p['destino'], 'llegada': p['llegada']}]
                      + list((p.get('destinos') or {}).values())):
                if d.get('destino') is None or not d.get('llegada'):
                    continue
                assert app._portal_en(d['destino'], *d['llegada']) is None, \
                    (st, p['tile'], d)


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
