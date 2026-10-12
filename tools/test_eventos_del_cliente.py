"""El diccionario de acciones y condiciones de los eventos, clavado.

De que va esto. Los .mpc traen la logica de misiones e instancias entera,
pero con los codigos en crudo, y durante mucho tiempo solo habia tres
descifrados a mano porque la lista de eventdef.xml no casaba por posicion.
No casaba porque esa lista es el orden del editor de mapas: los numeros de
verdad estan mas abajo en el mismo fichero, en el bloque DEFINE.

Lo que se comprueba aqui es justo lo que haria falso todo lo que se monte
encima:

  * que las cinco anclas que ya estaban medidas por otro camino sigan
    valiendo lo mismo;
  * que los 27 paks no se contradigan en NINGUN numero, porque si la
    numeracion dependiera de la version habria que elegir pak por mapa;
  * y que el diccionario siga explicando los datos reales. Esto ultimo es lo
    que de verdad protege: setting/event.xml es una fuente distinta de los
    mapas, y leido con este diccionario tiene que seguir contando una
    historia coherente -- la misma mision avanzando de paso, una eleccion que
    sube y baja un atributo. Si alguien cambiara el diccionario por el de las
    posiciones, eso dejaria de encajar y este fichero se pondria rojo.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eventos_del_cliente as ec
import mapa_del_cliente as mc


class TestDiccionario(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.acc, cls.con = ec.diccionario()

    def test_las_anclas_medidas_siguen_valiendo(self):
        self.assertEqual(self.acc[3], 'CHANGE_MAP')
        self.assertEqual(self.acc[25], 'BEGIN_MESSAGE')
        self.assertEqual(self.acc[53], 'GOTO_TAG')
        self.assertEqual(self.con[14], 'GENERATOR_ALIVE')
        self.assertEqual(self.con[22], 'PARA_ENTER')

    def test_el_diccionario_esta_completo(self):
        # 103 acciones y 71 condiciones es lo que trae el pak mas nuevo.
        self.assertGreaterEqual(len(self.acc), 103)
        self.assertGreaterEqual(len(self.con), 71)

    def test_ningun_pak_contradice_a_otro(self):
        # diccionario() ya revienta si hay choque; esto lo deja escrito y
        # ademas comprueba que de verdad hay varios paks que comparar.
        import glob
        paks = glob.glob(str(ec.PAKS / '*' / 'setting' / 'eventdef.xml'))
        self.assertGreaterEqual(len(paks), 5)
        ec.diccionario()

    def test_no_es_la_lista_por_posicion(self):
        # La trampa que costo meses: si se numera por el orden en que salen
        # los <動作> del xml, CHANGE_MAP cae en el 2 y no en el 3.
        txt = open(ec.PAKS / 'UPDATE10' / 'setting' / 'eventdef.xml',
                   encoding='utf-8-sig').read()
        por_posicion = re.findall(r'<動作\s+Sequence="(\w+)"', txt)
        self.assertNotEqual(por_posicion.index('EVENT_ACT_CHANGE_MAP'), 3)


class TestContraDatosReales(unittest.TestCase):
    """La comprobacion que no depende de los mapas: setting/event.xml."""

    @classmethod
    def setUpClass(cls):
        cls.acc, cls.con = ec.diccionario()
        import xml.etree.ElementTree as ET
        txt = open(ec.PAKS / 'data1' / 'setting' / 'event.xml',
                   encoding='utf-8-sig', errors='replace').read()
        cls.raiz = ET.fromstring(txt)

    def _acciones_del_dialogo(self, num):
        for d in self.raiz.findall('對話'):
            if int(d.get('編號')) != num:
                continue
            return [(int(a.get('編號')),
                     tuple(int(p.get('數值')) for p in a.findall('參數')))
                    for tr in d.findall('觸發器') for a in tr.findall('動作')]
        self.fail('no hay dialogo %d' % num)

    def test_la_misma_mision_avanza_de_paso(self):
        # dialogo 1: arranca la mision 107 en el paso 0
        # dialogo 8: la misma mision 107, paso 3
        for dialogo, paso in ((1, 0), (8, 3)):
            (num, parms), = self._acciones_del_dialogo(dialogo)
            self.assertEqual(self.acc[num], 'SET_STEP')
            self.assertEqual(parms, (107, paso))

    def test_una_eleccion_que_sube_y_baja_el_mismo_atributo(self):
        # dialogos 5 y 6: ADD_PROPERTY(29, +1) y ADD_PROPERTY(29, -1)
        (a, pa), = self._acciones_del_dialogo(5)
        (b, pb), = self._acciones_del_dialogo(6)
        self.assertEqual(self.acc[a], 'ADD_PROPERTY')
        self.assertEqual(self.acc[b], 'ADD_PROPERTY')
        self.assertEqual((pa, pb), ((29, 1), (29, -1)))

    def test_el_premio_de_mision_va_en_pares(self):
        # dialogo 3: SELECT_QUEST_REWARD con pares (objeto, cantidad)
        (num, parms), = self._acciones_del_dialogo(3)
        self.assertEqual(self.acc[num], 'SELECT_QUEST_REWARD')
        self.assertEqual(len(parms) % 2, 0)
        self.assertTrue(all(c == 1 for c in parms[1::2]), parms)


class TestDisparadores(unittest.TestCase):
    """Que los disparadores salgan con sus condiciones, que es lo que el
    lector de mapas tiraba por el camino."""

    @classmethod
    def setUpClass(cls):
        cls.acc, cls.con = ec.diccionario()
        cls.rutas = mc.mapas_del_cliente()

    def test_las_condiciones_ya_no_se_pierden(self):
        total = sum(len(d['condiciones'])
                    for ruta in self.rutas.values()
                    for d in ec.disparadores_del_mapa(ruta))
        # 15.766 medidas sobre los 399 mapas del cliente.
        self.assertGreater(total, 15000)

    def test_casi_todo_lo_que_se_usa_tiene_nombre(self):
        acc, con, _ma, _mc = ec.uso_real()
        for cuenta, nombres, titulo in ((acc, self.acc, 'acciones'),
                                        (con, self.con, 'condiciones')):
            total = sum(cuenta.values())
            sin = sum(v for n, v in cuenta.items() if n not in nombres)
            self.assertLess(sin / total, 0.01,
                            'demasiados %s sin nombre: %d de %d'
                            % (titulo, sin, total))

    def test_el_drop_de_mision_de_un_mapa_concreto(self):
        # Un disparador real, de los que mueven una mision: al morir el bicho
        # en grupo (disparo 4), si la mision 221 va por el paso 0, cae el
        # objeto 315. Es el patron que repiten 531 KILLTO_NEXTSTEP y 4.117
        # QUEST_STEP, y si el diccionario se moviera dejaria de leerse asi.
        encontrado = False
        for ruta in self.rutas.values():
            for d in ec.disparadores_del_mapa(ruta):
                cond = [(self.con.get(n), p) for n, p in d['condiciones']]
                acci = [(self.acc.get(n), p) for n, p in d['acciones']]
                if ('QUEST_STEP', (221, 0)) in cond and any(
                        n == 'CREATE_ITEM' and p[:2] == (315, 1) for n, p in acci):
                    self.assertEqual(d['disparo'], 4)
                    encontrado = True
        self.assertTrue(encontrado, 'no esta el disparador de la mision 221')


if __name__ == '__main__':
    unittest.main(verbosity=2)
