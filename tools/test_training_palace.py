"""Training Palace (stage 44): monstruos, objetos, tornados y la mision 123.

El mapa se pobla desde el propio map044.mpc (no hay captura) y el usuario lo
reviso en el juego el 14-15/10/2026: solo los monstruos de su lista y en su
zona, nada en el borde de las plataformas, el altar de Qiuaner que se pueda
pulsar y los tornados que abran su menu. Esto lo comprueba sin entrar.
"""
import collections
import json
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import eventos as ev            # noqa: E402
import dialogos_mapa as dm      # noqa: E402
import eventos_mundo as em      # noqa: E402
import login                    # noqa: E402
import transitable as tr        # noqa: E402

PLANTILLA = json.loads((RAIZ / 'server' / 'plantillas' / 'training_palace.json')
                       .read_text(encoding='utf-8'))
PERMITIDOS = {'Wildwolf', 'Little Gebuer', 'Tree Spirit', 'Headless Armor',
              'Goat Demon', 'Brute Priest'}
NUCLEOS = (129, 130, 131, 132, 133, 134)


class Ctx(ev.Contexto):
    """Un jugador de mentira con la mision 123 y lo que se le diga en la bolsa."""
    sabe = em.SABE

    def __init__(self, paso=0, fichas=(), sorteo=1):
        self._paso, self._fichas, self._sorteo = paso, set(fichas), sorteo

    def paso_de_mision(self, q):
        return self._paso if q == 123 else -1

    def mision_terminada(self, q):
        return False

    def mision_en_curso(self, q):
        return q == 123

    def objeto_de_mision(self, item):
        return 1 if item in self._fichas else 0

    def en_bolsa(self, item):
        return self.objeto_de_mision(item)

    def sorteo100(self):
        return self._sorteo

    def vivos_del_generador(self, tag):
        return 0


def test_solo_los_monstruos_de_la_lista():
    c = collections.Counter(s['nombre'] for s in PLANTILLA['spawns'])
    assert set(c) == PERMITIDOS, c
    assert all(n == 10 for n in c.values()), c


def test_nadie_en_el_borde_ni_fuera_del_mapa():
    for s in PLANTILLA['spawns']:
        x, y = s['tile']
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                assert tr.se_pisa(44, x + dx, y + dy), (s['nombre'], s['tile'])


def test_cada_monstruo_cerca_de_su_generador():
    gen = {'Wildwolf': (94, 92), 'Little Gebuer': (27, 90), 'Tree Spirit': (177, 49),
           'Headless Armor': (175, 16), 'Goat Demon': (104, 55), 'Brute Priest': (34, 17)}
    for s in PLANTILLA['spawns']:
        g = gen[s['nombre']]
        d = max(abs(s['tile'][0] - g[0]), abs(s['tile'][1] - g[1]))
        assert d <= 20, (s['nombre'], s['tile'], d)


def test_los_objetos_con_evento_se_pueden_pulsar():
    """Marca 40 80 y el cursor del evento detras del sprite: sin eso el
    cliente toma el objeto por decorado y no manda el clic."""
    for r in PLANTILLA['recursos']:
        if not ev.evento_en(44, *r['tile']):
            continue
        b = bytes.fromhex(r['crudo'])
        # la marca va justo detras del sprite (+38) y el cursor en +40, como
        # en las antorchas capturadas: dc 06 | sprite | 40 80 | 14 | 00 00.
        # En +40 rompia el cuerpo y el cliente ni dibujaba el objeto.
        i = b.find(b'\x40\x80', 36)
        assert i == 38, (r['entity_id'], r['tile'], b[36:].hex())
        assert b[i + 2] == 20, (r['entity_id'], b[i + 2])


def test_el_altar_esta_y_abre_su_dialogo():
    altar = [r for r in PLANTILLA['recursos'] if r.get('sprite') == 60156]
    assert len(altar) == 1 and altar[0]['tile'] == [166, 86]
    assert ev.evento_en(44, 166, 86) == 123
    efs = ev.ejecutar(44, 123, ev.DISPAROS_AL_PULSAR, Ctx())
    assert ('dialogo', 12301) in efs, efs


def test_los_tornados_se_dibujan_y_abren_su_menu():
    assert len(login.portales_de(44)) == 2
    for evento, menu in ((1, 5801), (2, 5802)):
        efs = ev.ejecutar(44, evento, (ev.CHOCAR,), Ctx())
        assert ('dialogo', menu) in efs, (evento, efs)
    # la opcion lleva al Playground, al tag 2
    assert ev.traducir(37, [42, 0, 2]) == ('viajar', 42, 2)
    assert ev.casillas_de_tag(42, 2) and ev.casillas_de_tag(43, 2)


def test_al_matar_cae_un_nucleo_con_la_mision():
    tipos = (ev.del_stage(44) or {}).get('monstruos') or {}
    for npc, nucleo in ((8, 129), (9, 130), (10, 131), (11, 132), (12, 133), (13, 134)):
        evento = int(tipos[str(npc)])
        efs = ev.ejecutar(44, evento, ev.DISPAROS_AL_MORIR, Ctx(paso=0, sorteo=1))
        assert any(e[0] == 'dar' and e[1][0][0] == nucleo for e in efs), (npc, efs)
        # sin la mision en ese paso, nada
        assert not ev.ejecutar(44, evento, ev.DISPAROS_AL_MORIR, Ctx(paso=5, sorteo=1))


def test_con_los_seis_nucleos_el_altar_saca_a_qiuaner():
    arbol = dm._arbol(44)
    n = arbol['1000010']
    assert [31, [3, 0]] in n['a'], n
    assert ev.del_stage(44)['generadores']['3']['tipos'] == [14]     # Qiuaner
    rama = [r for r in arbol['1000007']['r'] if r['ir'] == 1000009][0]
    assert all(ev.evaluar(c[0], c[1], Ctx(fichas=NUCLEOS)) for c in rama['si'])
    assert not all(ev.evaluar(c[0], c[1], Ctx(fichas=NUCLEOS[:5])) for c in rama['si'])


def test_al_matar_a_qiuaner_avanza_la_mision():
    evento = int(ev.del_stage(44)['monstruos']['14'])
    efs = ev.ejecutar(44, evento, ev.DISPAROS_AL_MORIR, Ctx(paso=0))
    assert any(e[0] == 'dar' and e[1][0][0] == 135 for e in efs), efs
    assert ('paso', 123, 1) in efs, efs


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
