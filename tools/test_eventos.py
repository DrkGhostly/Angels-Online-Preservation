"""El interprete de eventos: que ejecute la logica del cliente y no invente.

De que va esto. Las instancias estaban pobladas pero mudas y las misiones
iban a mano, una por una, en diccionarios de misiones.py. La logica estaba
escrita desde siempre en los .mpc; lo que faltaba era el diccionario de
codigos, y desde que esta (tools/eventos_del_cliente.py) server/eventos.py
la ejecuta.

Lo que se comprueba aqui son dos cosas distintas, y la segunda importa mas
que la primera:

  * QUE EJECUTE. Tres disparadores reales, sacados de los mapas, con el
    contexto puesto a mano, tienen que dar exactamente los efectos que dicen
    los datos. Uno es la puerta de una instancia, otro una caceria y otro un
    drop de mision.

  * QUE NO INVENTE. Un disparador cuya condicion no se sepa evaluar NO tiene
    que saltar. Esto es lo que protege de verdad: una condicion mal resuelta
    que salte de mas teletransporta a alguien o le regala objetos, y eso no
    se ve hasta que alguien lo cuenta. Que no salte solo deja las cosas como
    estaban.
"""
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, 'server'))

import eventos as ev


class Ctx(ev.Contexto):
    """Un contexto de mentira al que se le dice todo lo que tiene que saber."""

    def __init__(self, sabe=(), **estado):
        self.sabe = frozenset(sabe)
        self.estado = estado

    def paso_de_mision(self, quest):
        return self.estado.get('pasos', {}).get(quest, -1)

    def vivos_del_generador(self, tag):
        return self.estado.get('vivos', {}).get(tag, 99)

    def en_bolsa(self, item):
        return self.estado.get('bolsa', {}).get(item, 0)

    def objeto_de_mision(self, item):
        return self.estado.get('questitems', {}).get(item, 0)

    def variable_de_mapa(self, mapa, var):
        return self.estado.get('vars', {}).get((mapa, var), 0)

    def sorteo100(self):
        return self.estado.get('dado', 1)


class TestCobertura(unittest.TestCase):

    def test_cubre_casi_todo_lo_que_los_mapas_usan(self):
        c = ev.cobertura()
        acc_ok, acc = c['acciones']
        con_ok, con = c['condiciones']
        # Medido: 97.0% de las acciones y 94.6% de las condiciones. Se deja
        # margen para abajo, pero si alguien quita una traduccion grande esto
        # se pone rojo en vez de pasar desapercibido.
        self.assertGreater(acc_ok / acc, 0.95, '%d de %d acciones' % (acc_ok, acc))
        self.assertGreater(con_ok / con, 0.93, '%d de %d condiciones' % (con_ok, con))

    def test_la_plantilla_esta_generada(self):
        self.assertTrue(ev.RUTA.exists(),
                        'falta %s: corre tools/propagar_eventos.py' % ev.RUTA)
        self.assertGreater(len(ev._datos()['stages']), 300)


class TestComparadores(unittest.TestCase):
    """Los COMPARE_* del eventdef. Si se desordenan, todas las condiciones
    de tres parametros empiezan a contestar al reves."""

    def test_el_orden_es_el_del_eventdef(self):
        self.assertEqual(
            (ev.IGUAL, ev.MENOR, ev.MAYOR, ev.MENOR_IGUAL, ev.MAYOR_IGUAL,
             ev.DISTINTO), (0, 1, 2, 3, 4, 5))

    def test_cada_uno_compara_lo_que_dice(self):
        for modo, a, b, esperado in ((ev.IGUAL, 3, 3, True),
                                     (ev.IGUAL, 3, 4, False),
                                     (ev.MENOR, 3, 4, True),
                                     (ev.MAYOR, 4, 3, True),
                                     (ev.MENOR_IGUAL, 3, 3, True),
                                     (ev.MAYOR_IGUAL, 3, 4, False),
                                     (ev.DISTINTO, 3, 4, True)):
            self.assertIs(ev._cmp(modo, a, b), esperado, (modo, a, b))


class TestNoInventar(unittest.TestCase):

    def test_una_condicion_que_no_se_sabe_no_dispara(self):
        # El contexto no declara saber nada, asi que QUEST_STEP sale None.
        ctx = Ctx()
        self.assertIsNone(ev.evaluar(2, [221, 0], ctx))
        self.assertEqual(ev.ejecutar(2, 221, ev.MUERTE_GRUPO, ctx), [])

    def test_una_condicion_falsa_no_dispara(self):
        ctx = Ctx(sabe=(2,), pasos={221: 5})
        self.assertFalse(ev.evaluar(2, [221, 0], ctx))
        self.assertEqual(ev.ejecutar(2, 221, ev.MUERTE_GRUPO, ctx), [])

    def test_stop_corta_lo_que_venga_detras(self):
        # 'parar' sale de la accion 1 (STOP) y tiene que cortar ahi mismo.
        self.assertEqual(ev.traducir(1, []), ('parar',))

    def test_una_accion_que_no_se_traduce_se_salta_sin_romper(self):
        # 88 SCRIPT llama al interprete de scripts del cliente: no se traduce.
        self.assertIsNone(ev.traducir(88, [7]))

    def test_un_stage_que_no_existe_no_revienta(self):
        self.assertEqual(ev.disparadores(999999), [])
        self.assertIsNone(ev.evento_en(999999, 1, 1))
        self.assertEqual(ev.casillas_de_tag(999999, 1), [])


class TestDisparadoresReales(unittest.TestCase):
    """Tres casos sacados de los mapas, no inventados."""

    def test_la_puerta_de_la_instancia_se_abre_al_limpiar_la_sala(self):
        # mapa 73, evento 150: GENERATOR_ALIVE(218, IGUAL, 0) ->
        # CHANGE_STATICOBJ(118, 60037). Es justo lo que faltaba en las
        # instancias pobladas: la puerta que se abre al matar a todos.
        # El modo de disparo es 0, o sea que se comprueba sin que medie
        # ningun acto del jugador.
        con_bichos = Ctx(sabe=(14,), vivos={218: 4})
        self.assertEqual(ev.ejecutar(73, 150, ev.NINGUNO, con_bichos), [])

        sala_limpia = Ctx(sabe=(14,), vivos={218: 0})
        self.assertEqual(ev.ejecutar(73, 150, ev.NINGUNO, sala_limpia),
                         [('objeto_estatico', 118, 60037)])

    def test_el_drop_de_la_mision_221(self):
        # mapa 2, evento 221, al morir el bicho en grupo: si la mision 221 va
        # por el paso 0, cae el objeto 315.
        en_el_paso = Ctx(sabe=(2,), pasos={221: 0})
        efectos = ev.ejecutar(2, 221, ev.MUERTE_GRUPO, en_el_paso)
        self.assertIn(('dar', [(315, 1)]), efectos)

        otro_paso = Ctx(sabe=(2,), pasos={221: 1})
        self.assertEqual(ev.ejecutar(2, 221, ev.MUERTE_GRUPO, otro_paso), [])

    def test_la_caceria_del_mapa_8(self):
        # mapa 8, evento 801, sin condiciones:
        # KILLTO_NEXTSTEP(mision 801, paso 0, objeto oculto 3200, 1 por baja,
        # 100% de probabilidad, 40 para completar).
        efectos = ev.ejecutar(8, 801, ev.MUERTE_GRUPO, Ctx())
        self.assertIn(('matar_para_avanzar', 801, 0, 3200, 1, 100, 40), efectos)


class TestFirmas(unittest.TestCase):
    """Que los parametros se lean en el orden que documenta el eventdef."""

    def test_los_objetos_van_en_cinco_pares(self):
        # CREATE_ITEM(item1, cant1, ... item5, cant5)
        self.assertEqual(
            ev.traducir(10, [315, 2, 400, 1, 0, 0, 0, 0, 0, 0]),
            ('dar', [(315, 2), (400, 1)]))

    def test_cambiar_mapa_es_mapa_y_tag_en_ese_orden(self):
        self.assertEqual(ev.traducir(3, [73, 5]), ('viajar', 73, 5))

    def test_las_variables_de_mapa_llevan_mapa_variable_y_valor(self):
        self.assertEqual(ev.traducir(56, [73, 2, 1]),
                         ('variable', 'poner', 73, 2, 1))
        self.assertEqual(ev.traducir(57, [73, 2, 1]),
                         ('variable', 'sumar', 73, 2, 1))
        self.assertEqual(ev.traducir(104, [73, 2, 1]),
                         ('variable', 'restar', 73, 2, 1))

    def test_dar_y_quitar_no_se_confunden(self):
        # 10 es dar al jugador, 9 es quitarselo. Si se cruzan, una mision de
        # entrega se come el objeto dos veces o ninguna.
        self.assertEqual(ev.traducir(10, [315, 1])[0], 'dar')
        self.assertEqual(ev.traducir(9, [315, 1])[0], 'quitar')

    def test_el_sorteo_de_prob100_es_inclusivo(self):
        # PROB100(100) tiene que salir siempre, y PROB100(0) nunca.
        self.assertTrue(ev.evaluar(10, [100], Ctx(sabe=(10,), dado=100)))
        self.assertFalse(ev.evaluar(10, [0], Ctx(sabe=(10,), dado=1)))


class TestDatosDelMapa(unittest.TestCase):

    def test_las_casillas_que_disparan_estan(self):
        d = ev.del_stage(73)
        self.assertTrue(d['objetos'])
        casilla, (evento, _oid, _capa) = next(iter(d['objetos'].items()))
        tx, ty = (int(v) for v in casilla.split(','))
        self.assertEqual(ev.evento_en(73, tx, ty), evento)

    def test_los_tags_devuelven_casillas(self):
        d = ev.del_stage(73)
        tag = next(iter(d['tags']))
        self.assertTrue(all(len(c) == 2 for c in ev.casillas_de_tag(73, int(tag))))


if __name__ == '__main__':
    unittest.main(verbosity=2)
