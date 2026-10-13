"""El puente entre el interprete de eventos y el mundo.

De que va esto. El interprete lee la logica de los .mpc, pero para ejecutarla
hay que contestarle preguntas sobre el personaje y el mapa, y ahi es donde
estaban los dos fallos que dejaban las misiones mudas:

  1. LOS PASOS NO SE NUMERAN IGUAL. El servidor guarda el primer paso como 1
     y lo manda por red como 0 -- misiones.avanzar_paso hace `paso - 1` --,
     y los eventos del cliente usan la numeracion DE RED. Comparando sin
     convertir, ninguna condicion de mision casa nunca: la mision sale
     aceptada en el diario y el objeto no cae jamas. No da error, no deja
     rastro en el log, simplemente no pasa nada.

  2. EL EVENTO DE MUERTE NO CUELGA DEL MAPA, CUELGA DEL BICHO. Los
     disparadores de muerte citan eventos que ningun objeto del mapa
     referencia: en Dense Forest los objetos solo nombran el 1, 2, 3, 4 y
     1001, y los botines cuelgan del 501 al 505 y del 542. El enlace estaba
     en un campo del registro del generador que no se leia.

El caso que se comprueba es el que lo destapo, The Reivers, tal como lo
escribe el mapa:

    monstruo tipo 114 en Dense Forest -> evento 502
    evento 502, al morir en grupo:
      si QUEST_STEP(502, 0) y BAGITEM(181, =, 0)
      y EMPTYSLOT_COUNT(>, 0) y PROB100(5)
      -> CREATE_ITEM(181, 1)

o sea el Mushroom al 5%, solo si no llevas ya uno y te queda hueco.
"""
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, 'server'))

import eventos as ev
import eventos_mundo as evm

MAPA = 23           # Dense Forest
BICHO = 114         # el que lleva el evento 502
MUSHROOM = 181
QUEST = 502


class Personaje:
    def __init__(self, quests=(), inventario=None, cantidades=None):
        self.quests = list(quests)
        self.inventario = dict(inventario or {})
        self.cantidades = dict(cantidades or {})
        self.oro = 0
        self.nivel = 1
        self.faction = 'Heaven'


class Sesion:
    def __init__(self, p):
        self.personaje = p
        self.monstruos = {}
        self.muerto = False


class Bicho:
    def __init__(self, npc_type, tile=(10, 10), vivo=True):
        self.npc_type = npc_type
        self.spawn_tile = list(tile)
        self.vivo = vivo


def _contexto(p, dado=1):
    ses = Sesion(p)
    estado = evm.EstadoDeMapa(MAPA)
    ses.estado_mapa = estado
    ctx = evm.ContextoSesion(ses, estado)
    ctx.sorteo100 = lambda: dado
    return ses, estado, ctx


class TestNumeracionDePasos(unittest.TestCase):

    def test_el_primer_paso_del_servidor_es_el_cero_del_cliente(self):
        _s, _e, ctx = _contexto(Personaje(quests=[(QUEST, 1)]))
        self.assertEqual(ctx.paso_de_mision(QUEST), 0)

    def test_no_tener_la_mision_no_es_ir_por_el_primer_paso(self):
        # Si esto devolviera 0, CUALQUIER QUEST_STEP(q, 0) del juego saltaria
        # para todo el mundo y se regalarian objetos de misiones sin aceptar.
        _s, _e, ctx = _contexto(Personaje())
        self.assertEqual(ctx.paso_de_mision(QUEST), evm.PASO_SIN_MISION)
        self.assertNotEqual(ctx.paso_de_mision(QUEST), 0)

    def test_los_pasos_siguientes_tambien_se_convierten(self):
        _s, _e, ctx = _contexto(Personaje(quests=[(QUEST, 4)]))
        self.assertEqual(ctx.paso_de_mision(QUEST), 3)


class TestEventoDelBicho(unittest.TestCase):

    def test_el_tipo_114_lleva_el_evento_502(self):
        self.assertEqual(evm.evento_del_monstruo(MAPA, BICHO), QUEST)

    def test_cada_bicho_de_dense_forest_lleva_uno_solo(self):
        d = ev.del_stage(MAPA)
        self.assertEqual(d['monstruos'].get('112'), 501)
        self.assertEqual(d['monstruos'].get('113'), 505)
        self.assertEqual(d['monstruos'].get('117'), 503)

    def test_un_bicho_sin_evento_no_dispara_nada(self):
        self.assertIsNone(evm.evento_del_monstruo(MAPA, 5))
        p = Personaje(quests=[(QUEST, 1)])
        ses, _e, _c = _contexto(p)
        self.assertEqual(evm.al_morir_monstruo(ses, Bicho(5)), [])


class TestElMushroomDeTheReivers(unittest.TestCase):

    def test_cae_con_la_mision_en_su_primer_paso(self):
        _s, _e, ctx = _contexto(Personaje(quests=[(QUEST, 1)]), dado=1)
        self.assertIn(('dar', [(MUSHROOM, 1)]),
                      ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, ctx))

    def test_no_cae_si_la_mision_va_por_otro_paso(self):
        _s, _e, ctx = _contexto(Personaje(quests=[(QUEST, 3)]), dado=1)
        self.assertEqual(ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, ctx), [])

    def test_no_cae_sin_la_mision(self):
        _s, _e, ctx = _contexto(Personaje(), dado=1)
        self.assertEqual(ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, ctx), [])

    def test_no_cae_un_segundo_si_ya_llevas_uno(self):
        p = Personaje(quests=[(QUEST, 1)], inventario={20: MUSHROOM})
        _s, _e, ctx = _contexto(p, dado=1)
        self.assertEqual(ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, ctx), [])

    def test_el_cinco_por_ciento_se_respeta(self):
        p = Personaje(quests=[(QUEST, 1)])
        _s, _e, flojo = _contexto(p, dado=6)      # 6 > 5: no toca
        self.assertEqual(ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, flojo), [])
        _s, _e, justo = _contexto(p, dado=5)      # 5 <= 5: toca
        self.assertIn(('dar', [(MUSHROOM, 1)]),
                      ev.ejecutar(MAPA, QUEST, ev.DISPAROS_AL_MORIR, justo))

    def test_la_cadena_entera_desde_el_bicho(self):
        p = Personaje(quests=[(QUEST, 1)])
        ses, estado, _c = _contexto(p)
        # al_morir_monstruo arma su propio contexto, asi que el azar se fija
        # dejando la probabilidad imposible de fallar no se puede; se
        # comprueba que al menos resuelve el evento y no revienta.
        self.assertEqual(evm.evento_del_monstruo(estado.stage, BICHO), QUEST)
        self.assertIsInstance(evm.al_morir_monstruo(ses, Bicho(BICHO)), list)


class TestInventario(unittest.TestCase):

    def test_los_objetos_de_mision_salen_de_las_ranuras_ocultas(self):
        # misiones.py guarda los contadores de caceria en la 497..556, que no
        # ocupan mochila. QUESTITEM tiene que mirar ahi y BAGITEM no.
        p = Personaje(inventario={497: 16075, 20: 181},
                      cantidades={497: 7})
        _s, _e, ctx = _contexto(p)
        self.assertEqual(ctx.objeto_de_mision(16075), 7)
        self.assertEqual(ctx.en_bolsa(16075), 0)
        self.assertEqual(ctx.en_bolsa(181), 1)
        self.assertEqual(ctx.objeto_de_mision(181), 0)


class TestZonasDeGenerador(unittest.TestCase):
    """GENERATOR_ALIVE es lo que abre las instancias, y para contestarlo hay
    que saber de que zona es cada bicho."""

    def test_un_bicho_cae_en_la_zona_de_su_generador(self):
        estado = evm.EstadoDeMapa(73)
        d = ev.del_stage(73)
        tag, g = next(iter(d['generadores'].items()))
        punto = g['puntos'][0]
        self.assertEqual(estado.zona_de(punto), int(tag))

    def test_un_bicho_lejos_no_es_de_ninguna_zona(self):
        estado = evm.EstadoDeMapa(73)
        self.assertIsNone(estado.zona_de((9999, 9999)))

    def test_solo_cuentan_los_vivos(self):
        estado = evm.EstadoDeMapa(73)
        d = ev.del_stage(73)
        tag, g = next(iter(d['generadores'].items()))
        punto = tuple(g['puntos'][0])
        vivos = {1: Bicho(1, punto, vivo=True), 2: Bicho(2, punto, vivo=False)}
        self.assertEqual(estado.vivos_por_zona(vivos), {int(tag): 1})


if __name__ == '__main__':
    unittest.main(verbosity=2)
