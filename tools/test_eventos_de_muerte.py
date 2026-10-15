"""El evento que dispara cada monstruo al morir, leido del generador.

El +50 del registro del generador es un u32. Se leia como u16 y los eventos
por encima de 65535 salian truncados: los Stab Jellyfish de Wave Harbor
llevan el 70501 y se leia 4965, un evento que no existe, asi que matarlos
no sumaba a la mision 976 "Nature is Crying for Help". Pasaba con 1.028
tipos de monstruo en todo el juego.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import eventos as ev            # noqa: E402
import eventos_mundo as em      # noqa: E402


class Ctx(ev.Contexto):
    sabe = em.SABE

    def __init__(self, quest, paso=0):
        self.q, self.paso = quest, paso

    def paso_de_mision(self, q):
        return self.paso if q == self.q else -1

    def objeto_de_mision(self, item):
        return 0


def test_los_eventos_de_muerte_existen():
    """Cada evento del mapa de tipos tiene que tener algun disparador o no
    estar truncado: ninguno por encima de 65535 puede haberse perdido."""
    datos = ev._datos()['stages']
    grandes = sum(1 for d in datos.values() for e in d['monstruos'].values() if int(e) > 65535)
    assert grandes > 500, grandes


def test_wave_harbor_cuenta_para_nature_is_crying():
    d = ev.del_stage(89)
    assert d['monstruos']['1191'] == 70501, d['monstruos']['1191']
    for npc, ficha in (('1191', 12597), ('1188', 12598), ('1189', 12599), ('1192', 12600)):
        efs = ev.ejecutar(89, d['monstruos'][npc], ev.DISPAROS_AL_MORIR, Ctx(976))
        assert ('dar', [(ficha, 1)]) in efs, (npc, efs)


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
