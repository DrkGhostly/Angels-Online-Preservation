import sys
import unittest
import types
import struct

sys.path.insert(0, r'f:\Ao Proyect\AO 2\server')

import misiones
import dialogos
import cuentas

class MockPersonaje:
    def __init__(self):
        self.char_id = 9999
        self.nombre = 'TestHero'
        self.nivel = 25
        self.rango = 2
        self.creditos = 100
        self.oro = 1000
        self.exp = 5000
        self.stage = 3
        self.tile_x = 100
        self.tile_y = 100
        self.faction = 'Aurora'
        self.quests = []
        self.inventario = {}
        self.cantidades = {}

class MockSesion:
    def __init__(self):
        self.personaje = MockPersonaje()
        self.usuario = None
        self.oro = 1000
        self.addr = ('127.0.0.1', 9999)
        self.enviados = []
        self.quest_kills = {}

    def enviar(self, *pkgs):
        self.enviados.extend(pkgs)

    def enviar_inmediato(self, *pkgs):
        self.enviados.extend(pkgs)

class TestMisionesEden(unittest.TestCase):
    def test_misiones_cargadas(self):
        q127 = misiones.info_mision(127)
        self.assertTrue(bool(q127))
        self.assertTrue('Aurora' in q127.get('nombre'))

        q142 = misiones.info_mision(142)
        self.assertTrue(bool(q142))
        self.assertEqual(q142.get('nombre'), 'Eden Needs Help')

    def test_flujo_mision_conocer(self):
        ses = MockSesion()
        # Aceptar mision 133 (Knowing Aurora City)
        ok = misiones.aceptar_mision(ses, 133)
        self.assertTrue(ok)
        self.assertTrue(misiones.tiene_mision(ses.personaje, 133))
        self.assertFalse(misiones.mision_completada(ses.personaje, 133))

        # Completar mision 133
        exp_antes = ses.personaje.exp
        oro_antes = ses.oro
        ok = misiones.completar_mision(ses, 133, exp=1500, oro=500)
        self.assertTrue(ok)
        self.assertTrue(misiones.mision_completada(ses.personaje, 133))
        self.assertEqual(ses.personaje.exp, exp_antes + 1500)
        self.assertEqual(ses.oro, oro_antes + 500)

    def test_caceria_quest_142(self):
        ses = MockSesion()
        # Aceptar Quest 142 y avanzar al paso 2 (Defeat 100 Young Witches or Crystal Envoys)
        misiones.aceptar_mision(ses, 142)
        misiones.avanzar_paso(ses, 142, 2)
        self.assertEqual(ses.personaje.quests[0], (142, 2))

        # Matar 99 Young Witches (npc_type 7007)
        for _ in range(99):
            act = misiones.registrar_baja_monstruo(ses, 7007)
            self.assertTrue(act)
        
        # Todavia debe estar en paso 2
        st, pa, comp = misiones.estado_mision(ses.personaje, 142)
        self.assertEqual(pa, 2)

        # Matar la 100 (Crystal Envoy, npc_type 7008)
        act = misiones.registrar_baja_monstruo(ses, 7008)
        self.assertTrue(act)

        # Debe haber avanzado al paso 3 automaticamente
        st, pa, comp = misiones.estado_mision(ses.personaje, 142)
        self.assertEqual(pa, 3)

    def test_dialogos_propio_guias_y_eden(self):
        # Explorer Lim (121633)
        dlg = dialogos.propio('Explorer Lim', entidad=121633)
        self.assertIsNotNone(dlg)
        mid_lim = struct.unpack_from('<I', dlg[0], 0)[0]
        self.assertEqual(mid_lim, 20010)

        # Paradise Angel (121671)
        dlg = dialogos.propio('Paradise Angel', entidad=121671)
        self.assertIsNotNone(dlg)
        ops = dialogos.opciones_de(dlg[0])
        self.assertIn(14202, ops)
        self.assertIn(5080, ops)

        # Block Envoy (122784)
        dlg = dialogos.propio('Block Envoy', entidad=122784)
        self.assertIsNotNone(dlg)
        ops = dialogos.opciones_de(dlg[0])
        self.assertIn(20002, ops)
        self.assertIn(5080, ops)

        # Guerrilla Leader Mola (122793)
        dlg = dialogos.propio('Guerrilla Leader', entidad=122793)
        self.assertIsNotNone(dlg)
        ops = dialogos.opciones_de(dlg[0])
        self.assertIn(20002, ops)
        self.assertIn(14303, ops)

        # Lord Kahn (122809)
        dlg = dialogos.propio('Lord Kahn', entidad=122809)
        self.assertIsNotNone(dlg)
        ops = dialogos.opciones_de(dlg[0])
        self.assertIn(20002, ops)
        self.assertIn(14402, ops)

    def test_respuestas_dialogos(self):
        # Opcion de registro en cualquier ciudad (ej. 20002 para Aurora)
        resp = dialogos.respuesta_a(20002)
        self.assertEqual(len(resp), 6)

        # Opcion de Paradise Angel 14202
        resp = dialogos.respuesta_a(14202)
        self.assertEqual(len(resp), 3)

if __name__ == '__main__':
    unittest.main()
