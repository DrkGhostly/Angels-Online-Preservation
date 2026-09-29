"""Las mejoras de equipo: morteros, martillos, piensos y gemas.

Lo que se comprueba es que las reglas salgan de los DATOS del cliente y no de
una tabla escrita a mano, y que las tres que el juego deja por escrito en las
descripciones se cumplan:

  - un objeto solo sirve hasta cierto nivel de equipo
  - una gema solo entra de su nivel HACIA ARRIBA
  - fallar un mortero no rompe nada, pero fallar un martillo se lleva el
    hueco anterior y la gema que tuviera dentro
"""
import pathlib
import random
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))

import mejoras as m         # noqa: E402

MORTERO_10 = 6904           # 10-star Lucky Enhanced Pestle, hasta nivel 109
MORTERO_11 = 12218          # 11-star, hasta 119, con los % escritos
MARTILLO = 6914             # 10-star Lucky Piercing Hammer, hasta 109


def test_clasifica_por_su_categoria():
    """La clase sale de 物品類別, no de una lista de ids."""
    assert m.clase_de(MORTERO_10) == 'mortero'
    assert m.clase_de(MORTERO_11) == 'mortero'
    assert m.clase_de(MARTILLO) == 'perforar'
    assert m.clase_de(10) == ''          # una espada no es objeto de mejora


def test_lee_el_tope_de_nivel_de_la_descripcion():
    """"Exclusively for enhancing gears under lvl 109" -> 109."""
    assert m.tope_nivel(MORTERO_10) == 109
    assert m.tope_nivel(MORTERO_11) == 119
    assert m.tope_nivel(MARTILLO) == 109


def test_lee_los_porcentajes_cuando_estan_escritos():
    """Los morteros de once estrellas para arriba los declaran."""
    b = m.bonos_de(MORTERO_11)
    assert b['arma'] == {'atk': 6, 'matk': 6}
    assert b['armadura'] == {'dfs': 3, 'mdef': 3}
    assert b['escudo'] == {'dfs': 3, 'mdef': 3}


def test_los_viejos_heredan_lo_de_sus_hermanos():
    """Los de diez estrellas para abajo no dicen nada: 85 de 92.

    Se les da lo que declaran los mayores, que es lo unico que los datos
    respaldan.
    """
    assert m.stats_de_mejora(MORTERO_10, 'arma', 3) == {'atk': 18, 'matk': 18}
    assert m.stats_de_mejora(MORTERO_10, 'armadura', 2) == {'dfs': 6,
                                                            'mdef': 6}


def test_no_pasa_del_tope_de_nivel():
    ok, motivo = m.puede_mejorar(MORTERO_10, 150, 'arma', 0)
    assert not ok and '109' in motivo, motivo
    assert m.puede_mejorar(MORTERO_10, 100, 'arma', 0)[0]


def test_el_tope_son_quince():
    assert m.puede_mejorar(MORTERO_10, 100, 'arma', 14)[0]
    ok, motivo = m.puede_mejorar(MORTERO_10, 100, 'arma', 15)
    assert not ok and '15' in motivo, motivo


def test_el_pienso_de_montura_no_vale_para_un_arma():
    """Y el de mascota tampoco: cada uno a lo suyo."""
    feeds = m.ids_de_clase('pienso_montura')
    if feeds:
        f = feeds[0]
        assert not m.puede_mejorar(f, 10, 'arma', 0)[0]
        assert m.puede_mejorar(f, 10, 'montura', 0)[0]


def test_la_gema_solo_entra_de_su_nivel_hacia_arriba():
    """La regla que se pidio explicitamente.

    Una gema de nivel 120 no entra en un arma de 110, aunque el arma sea peor:
    la restriccion mira el nivel de la GEMA.
    """
    gemas = [i for i in m.ids_de_clase('gema') if m.nivel_requerido(i)]
    assert gemas, 'no se encontro ninguna gema con nivel exigido'
    g = gemas[0]
    req = m.nivel_requerido(g)
    ok, motivo = m.puede_engarzar(g, req - 10, 'arma', 1)
    assert not ok and 'hacia arriba' in motivo, motivo
    assert m.puede_engarzar(g, req, 'arma', 1)[0]
    assert m.puede_engarzar(g, req + 50, 'arma', 1)[0]
    # Y sin hueco no entra ninguna.
    assert not m.puede_engarzar(g, req + 50, 'arma', 0)[0]


def test_fallar_el_mortero_baja_un_nivel():
    """No rompe la pieza, pero se pierde una mejora.

    Se leyo mal la descripcion la primera vez: "the number of times the gear
    has been enhanced decreases by 1" no son los intentos que quedan, es el
    +N. La captura lo confirma -- +6, fallo, +6 otra vez, +7, fallo -- porque
    si el fallo no restara, el segundo exito habria dado +7.
    """
    est = {}
    suerte = random.Random(1)
    suerte.random = lambda: 0.0              # siempre acierta
    for _ in range(6):
        m.aplicar(est, 20, MORTERO_10, 100, 'arma', rng=suerte)
    assert est[20]['veces'] == 6
    sin_suerte = random.Random(1)
    sin_suerte.random = lambda: 1.0          # siempre falla
    ok, motivo = m.aplicar(est, 20, MORTERO_10, 100, 'arma', rng=sin_suerte)
    assert not ok and est[20]['veces'] == 5, (motivo, est[20])
    assert est[20]['gemas'] == [], 'la pieza no se toca'
    # Y desde cero no baja a negativo.
    est2 = {}
    m.aplicar(est2, 21, MORTERO_10, 100, 'arma', rng=sin_suerte)
    assert est2[21]['veces'] == 0


def test_fallar_el_martillo_se_lleva_el_hueco_y_la_gema():
    """Lo dice su propia descripcion, y es lo que lo hace peligroso."""
    est = {20: {'veces': 0, 'gemas': [1234], 'extra': {}, 'huecos': 1}}
    sin_suerte = random.Random(1)
    sin_suerte.random = lambda: 1.0
    ok, motivo = m.perforar(est, 20, MARTILLO, 100, 'arma', rng=sin_suerte)
    assert not ok
    assert est[20]['huecos'] == 0, 'el hueco tenia que perderse'
    assert est[20]['gemas'] == [], 'la gema tenia que perderse'


def test_la_bandera_de_exito_seguro():
    est = {}
    sin_suerte = random.Random(1)
    sin_suerte.random = lambda: 1.0
    for _ in range(15):
        m.aplicar(est, 20, MORTERO_10, 100, 'arma', exito_seguro=True,
                  rng=sin_suerte)
    assert est[20]['veces'] == m.MAX_MEJORA


def test_la_bandera_tambien_vale_para_el_martillo():
    """El 100% se pidio para las perforaciones tambien, no solo morteros."""
    est = {20: {'veces': 0, 'gemas': [], 'extra': {}, 'huecos': 0}}
    sin_suerte = random.Random(1)
    sin_suerte.random = lambda: 1.0          # siempre fallaria
    # Entre hueco y hueco hay que meter una gema, asi que se alternan.
    gema = next(i for i in m.ids_de_clase('gema')
                if m.nivel_requerido(i) <= 100)
    for n in range(3):
        ok, _msg = m.perforar(est, 20, MARTILLO, 100, 'arma',
                              exito_seguro=True, rng=sin_suerte)
        assert ok, _msg
        assert m.engarzar(est, 20, gema, 100, 'arma')[0]
    assert est[20]['huecos'] == 3


def test_hay_que_engarzar_antes_de_abrir_otro_hueco():
    """Lo dijo el usuario: con un hueco vacio no se puede abrir el siguiente.

    Encaja con que fallar el martillo se lleve "el hueco anterior y la gema
    de dentro": si se pudieran acumular huecos vacios esa frase no tendria
    sentido.
    """
    est = {}
    ok, _ = m.perforar(est, 20, MARTILLO, 100, 'arma', exito_seguro=True)
    assert ok and est[20]['huecos'] == 1
    ok, motivo = m.perforar(est, 20, MARTILLO, 100, 'arma', exito_seguro=True)
    assert not ok and 'gema' in motivo, motivo
    # Con la gema puesta ya deja.
    gema = next(i for i in m.ids_de_clase('gema') if m.nivel_requerido(i) <= 100)
    assert m.engarzar(est, 20, gema, 100, 'arma')[0]
    assert m.perforar(est, 20, MARTILLO, 100, 'arma', exito_seguro=True)[0]
    assert est[20]['huecos'] == 2


def test_el_tope_de_huecos_son_cinco():
    est = {20: {'veces': 0, 'gemas': [1] * 5, 'extra': {}, 'huecos': 5}}
    ok, motivo = m.perforar(est, 20, MARTILLO, 100, 'arma',
                            exito_seguro=True)
    assert not ok and '5' in motivo, motivo


def test_el_pienso_de_mascota():
    """El 7094, que en Celestia no se vende y no se pudo medir."""
    assert m.clase_de(7094) == 'pienso_mascota'
    assert m.stats_de_mejora(7094, 'mascota', 3) == {'atk': 24}
    assert not m.puede_mejorar(7094, 10, 'arma', 0)[0]


def test_el_martillo_verde():
    """Sorteando sale dentro del rango; con la bandera, el maximo."""
    rangos = {'atk': (0, 210), 'dfs': (0, 210), 'rigor': (0, 54),
              'velocidad': (0, 40)}
    r = m.tirar_verde(rangos, todos=False, rng=random.Random(5))
    for k, (lo, hi) in rangos.items():
        assert lo <= r[k] <= hi, (k, r[k])
    todo = m.tirar_verde(rangos, todos=True)
    assert todo == {k: hi for k, (lo, hi) in rangos.items()}


def test_las_ranuras_de_equipo_que_faltaban():
    """Las insignias y el segundo trinket, que no se podian usar.

    Las insignias (categoria 徽章) no declaran ninguna columna de equipo, asi
    que se quedaban sin ranura: no se podian poner y sus bonos no llegaban
    nunca, aunque se leyeran bien. Van en la 175, medido al ponerse una
    Purple Seashell Badge en el servidor real.

    Y los accesorios tienen DOS ranuras, la 8 y la 9 -- los dos "Trinket" de
    la ventana --, no una: se vio un Stealth Ring en la 9.
    """
    import inventario as inv

    # La insignia tiene ranura, y esa ranura cuenta como equipo.
    assert inv.ranura_equipo_de(70792) == inv.RANURA_INSIGNIA == 175
    assert inv.es_equipo(175)
    assert not inv.es_equipo(176)

    # Y sus bonos llegan de verdad a los stats.
    bonos = inv._bonus(70792)
    assert bonos['hp'] == 6800 and bonos['atk'] == 3484
    sin_ella = inv.vida_maxima(280, [], bolsa={20: 10})
    con_ella = inv.vida_maxima(280, [], bolsa={20: 10, 175: 70792})
    assert con_ella == sin_ella + bonos['hp'], (sin_ella, con_ella)

    # El segundo trinket.
    assert inv.ranuras_posibles(24954) == [8, 9]
    assert inv.ranura_libre_equipo(24954, {}) == 8
    assert inv.ranura_libre_equipo(24954, {8: 1}) == 9


def test_el_mas_n_y_los_stats_verdes_viajan_en_la_entrada():
    """Los dos datos que el cliente necesita para pintar el tooltip.

    El "+N" va en el byte 83 de la entrada: se midio viendo ir y venir unas
    Boots Of Contempt -- 6 -> 5 al fallar, 5 -> 6 y 6 -> 7 al acertar.

    Los stats del martillo verde van desde el 13, en registros de cuatro
    bytes [u16 valor][u8 0][u8 id]. Los ids salieron comparando nueve
    tiradas contra los rangos que enseñaba el cuadro del juego, porque cada
    valor solo cabia en uno: HP 0-272, MP 0-184, Defense 0-824, Spell
    Defense 0-145, Agility 0-27. La tirada que dio "HP 53, MP 178" aparecio
    como dos registros, id 4 e id 12.
    """
    import inventario as inv

    linea = inv.actualizar_ranura(4794, 6, 32763, 1, None, 0x11e)
    assert linea[6 + inv.OFF_MEJORA] == 0

    con_mas = inv.marcar_mejora(linea, 7)
    assert con_mas[6 + inv.OFF_MEJORA] == 7
    # Y no toca nada mas.
    assert sum(1 for a, b in zip(linea, con_mas) if a != b) == 1

    con_verde = inv.marcar_extras(linea, {'hp': 53, 'mp': 178})
    assert inv.leer_extras(con_verde) == {'hp': 53, 'mp': 178}

    # Los dos a la vez conviven: van en sitios distintos.
    ambos = inv.marcar_extras(inv.marcar_mejora(linea, 7),
                              {'dfs': 681, 'agilidad': 21})
    assert ambos[6 + inv.OFF_MEJORA] == 7
    assert inv.leer_extras(ambos) == {'dfs': 681, 'agilidad': 21}

    # Los nueve stats que puede dar, ida y vuelta.
    todos = {'hp': 100, 'mp': 90, 'atk': 200, 'dfs': 192, 'matk': 105,
             'mdef': 137, 'rigor': 8, 'agilidad': 38, 'velocidad': 40}
    # Solo caben CINCO registros por entrada: el sexto empezaria en el byte
    # 33, que es donde va el contenedor de la pieza. Aqui ponia seis, y por
    # eso el martillo verde con todos los stats cerraba el cliente.
    cinco = dict(list(todos.items())[:5])
    assert inv.leer_extras(inv.marcar_extras(linea, cinco)) == cinco
    entera = inv.marcar_extras(linea, cinco)
    assert entera[6 + 33:6 + 37] == linea[6 + 33:6 + 37]


def test_el_verde_no_pisa_el_contenedor():
    """Cinco stats como mucho: el sexto caeria encima del contenedor.

    Con la bandera de "todos los stats" salian siete, se escribian seis, y el
    sexto borraba los bytes 33..36, que dicen si la pieza esta en la mochila
    o en el banco. El cliente se cerraba con "This program will be
    terminated becuase an error occur".
    """
    import sys as _s
    _s.path.insert(0, str(RAIZ / 'server'))
    import inventario as _inv
    rangos = {'atk': (0, 210), 'dfs': (0, 210), 'matk': (0, 210),
              'mdef': (0, 210), 'rigor': (0, 54), 'agilidad': (0, 54),
              'velocidad': (0, 40)}
    v = m.tirar_verde(rangos, todos=True)
    assert len(v) <= 5, v
    e = _inv._entrada(4794, 20, 5293, 1, None, 0x11e)
    marcada = _inv.marcar_extras(e, v)
    assert marcada[33:37] == e[33:37], 'el contenedor se piso'
    assert _inv.leer_extras(marcada) == v


def test_la_mascota_no_es_un_accesorio():
    """item.xml las manda a la ranura 9, que es el segundo Trinket."""
    import sys as _s
    _s.path.insert(0, str(RAIZ / 'server'))
    import inventario as _inv
    for r in (1, 8, 9, 175):
        assert not _inv.es_ranura_valida(20012, r), r
    assert _inv.es_ranura_valida(20012, 34), 'en la mochila si'
    assert _inv.es_ranura_valida(5293, 9), 'un accesorio normal sigue entrando'


def test_cada_pieza_reparte_lo_suyo():
    """Una espada no da defensa y unas botas no dan ataque.

    Contado en las entradas capturadas: en mas de 700 registros de armas no
    aparece dfs ni una vez, y en los de armadura no aparece atk. La tabla
    plana de antes daba los dos a todo.
    """
    arma = m.tirar_verde(m.rangos_verde(25670), todos=True)      # espada
    assert 'atk' in arma and 'dfs' not in arma, arma
    botas = m.tirar_verde(m.rangos_verde(32763), todos=True)
    assert 'dfs' in botas and 'atk' not in botas, botas
    # La velocidad es solo de las monturas, y no se puede quedar fuera por
    # el tope de cinco.
    montura = m.tirar_verde(m.rangos_verde(4159), todos=True)
    assert 'velocidad' in montura, montura
    for otra in (25670, 32763, 1869, 1873, 1784):
        assert 'velocidad' not in m.tirar_verde(m.rangos_verde(otra),
                                                todos=True), otra
    # La mochila solo da vida, mana y defensa.
    assert set(m.tirar_verde(m.rangos_verde(1869), todos=True)) == \
        {'hp', 'mp', 'dfs'}


def test_los_topes_salen_del_nivel_de_la_pieza():
    """Los dos cuadros que enseña el juego antes de usar el martillo.

    Nivel 22: Attack 0-50, Rigor 0-22, Agility 0-22, Speed 0-22.
    Nivel 70: Attack 0-290, Rigor 0-70, Agility 0-70, Speed 0-40.
    Antes el tope era fijo por tipo y una montura de nivel 22 ofrecia lo
    mismo que una de 70.
    """
    a = m._topes(22)
    assert (a['combate'], a['nivel'], a['velocidad']) == (50, 22, 22), a
    b = m._topes(70)
    assert (b['combate'], b['nivel'], b['velocidad']) == (290, 70, 40), b


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
