"""El dano de las habilidades y la regeneracion, fijados con mediciones.

Las dos cosas estaban calibradas solo con numeros de nivel bajo y se hundian
arriba. Aqui quedan clavadas las mediciones de los dos extremos, para que un
cambio futuro no vuelva a romper una arreglando la otra.
"""
import pathlib
import random
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
sys.path.insert(0, str(RAIZ / 'proto'))

import combate          # noqa: E402
import configuracion    # noqa: E402


class _Blanco(combate.Monstruo):
    """Un monstruo del que solo importa su defensa."""

    def __init__(self, defensa):
        self._d = defensa
        self.hp = 10 ** 9
        self.debuffs = {}
        self.panico = False

    mdef_efectiva = property(lambda s: s._d)
    defensa_efectiva = property(lambda s: s._d)


def test_nivel_bajo_sigue_igual():
    """La medicion vieja, que es la que fijo el K=420.

    Death Mummy 3 (ATK 249) contra un Condor (DEF 329) pega 140-143 en
    Celestia. Restar la defensa daria un numero negativo, asi que aqui tiene
    que ganar la mitigacion suave.
    """
    random.seed(3)
    for _ in range(20):
        d = _Blanco(329).recibir(249, es_magico=False, mult=1.0)
        assert 125 <= d <= 155, d


def test_nivel_alto_no_se_hunde():
    """La medicion nueva, la que destapo el problema.

    Con Spl Atk 56.978 y un Forbidden Curse IV -- multiplicador 8,25, que
    sale de 1650/200 de magic.xml -- contra un bicho de Specter Village, que
    tiene 34.797 de MDEF. En el juego original ese golpe hace unos 568.000
    contando el 15% de la montura; sin ella tiene que quedar en el entorno de
    los 400.000.

    Con la formula vieja daban 5.606: cien veces menos.
    """
    random.seed(3)
    d = _Blanco(34797).recibir(56978, es_magico=True, mult=8.25)
    assert 380000 <= d <= 470000, d
    assert d > 5606 * 50, 'sigue hundiendose con la defensa alta'


def test_la_defensa_sigue_contando():
    """Mas defensa tiene que doler menos, y nunca bajar de uno."""
    flojo = _Blanco(1000).recibir(56978, es_magico=True, mult=8.25)
    duro = _Blanco(200000).recibir(56978, es_magico=True, mult=8.25)
    assert flojo > duro >= 1, (flojo, duro)


def test_regeneracion_sube_con_el_nivel():
    """El porcentaje crece, y sentado siempre es mas que de pie."""
    for nivel, maximo in ((1, 280), (100, 20000), (300, 121440)):
        pie = configuracion.regenera(maximo, nivel, False, False)
        sentado = configuracion.regenera(maximo, nivel, True, False)
        assert sentado > pie, (nivel, pie, sentado)
    # A nivel alto tiene que ser cuestion de minutos, no de horas: con los +6
    # planos de antes, llenar 121.440 de MP eran cinco horas y media.
    pie300 = configuracion.regenera(121440, 300, False, False)
    assert 121440 / pie300 * 2 < 300, 'de pie sigue tardando demasiado'
    sent300 = configuracion.regenera(121440, 300, True, False)
    assert 121440 / sent300 < 60, 'sentado sigue tardando demasiado'


def test_a_nivel_1_no_regenera_menos_que_antes():
    """El suelo plano: nadie puede salir perdiendo con el cambio."""
    assert configuracion.regenera(280, 1, False, True) >= 6
    assert configuracion.regenera(280, 1, True, True) >= 12
    assert configuracion.regenera(154, 1, False, False) >= 6
    assert configuracion.regenera(154, 1, True, False) >= 6


def test_la_montura_de_fashion_no_quita_velocidad():
    """El aspecto es aspecto: nunca puede dejarte andando.

    La Shamrock Goldfish (77099) es de categoria 紙娃娃 y su move_speed viene
    VACIO. El codigo miraba la ranura de fashion PRIMERO, asi que ponersela
    daba velocidad cero y el jugador se quedaba a pie; quitarsela la devolvia.

    Y las que SI dan velocidad suman con la montura de verdad, no la pisan.
    """
    import app

    class _S:
        def __init__(self, bolsa):
            self.inventario = bolsa

    a_pie = app._velocidad_de(_S({}))
    con_montura = app._velocidad_de(_S({app.RANURA_MONTURA: 367}))
    assert con_montura > a_pie

    # El aspecto sin velocidad no resta.
    assert app._velocidad_de(_S({174: 77099})) == a_pie
    assert app._velocidad_de(_S({app.RANURA_MONTURA: 367,
                                 174: 77099})) == con_montura

    # El que si la da, suma.
    solo_moda = app._velocidad_de(_S({174: 367}))
    assert solo_moda > a_pie
    assert app._velocidad_de(_S({app.RANURA_MONTURA: 367,
                                 174: 367})) > con_montura


def test_los_buffs_de_dano_cuentan():
    """Soul Corral IV dice "+10% spell damage" y ahora se aplica.

    El dato estaba en magic.xml desde siempre -- el campo 魔法傷害 -- y se
    guardaba en el buff, pero nadie lo leia de vuelta. Los anillos y las capas
    si contaban, porque van por el camino del equipo, asi que la diferencia
    solo se notaba con buffs puestos.
    """
    import time as _t
    futuro, pasado = _t.time() + 60, _t.time() - 60

    # Lo que declara el hechizo de verdad.
    assert combate.datos_magia(5284).get('mag_dmg_pct') == 10, 'Soul Corral IV'

    buffs = {1: {'fin': futuro, 'mag_dmg_pct': 10},
             2: {'fin': futuro, 'mag_dmg_pct': 12},
             3: {'fin': pasado, 'mag_dmg_pct': 50}}
    # Suman entre ellos y el caducado no.
    assert combate.pct_dano_buffs(buffs, True) == 22
    # Un buff de dano magico no toca el fisico.
    assert combate.pct_dano_buffs(buffs, False) == 0
    assert combate.pct_dano_buffs(None, True) == 0
    assert combate.pct_dano_buffs({}, True) == 0


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
