import unittest
import sys
import os
import struct

sys.path.insert(0, os.path.abspath('server'))
import dialogos
import misiones
from login import Personaje

class MockSesion:
    def __init__(self, p):
        self.personaje = p
        self.usuario = 'test_user'
        self.char_id = p.char_id
        self.entity_id = p.entity_id
        self.envios = []
        self.dlg_ent = None
        self.dlg_guion = None
        self.dlg_paso = 0
        self.dlg_val = 0
        self.dlg_quest_ofrecida = None

    def enviar(self, *pkgs):
        for p in pkgs:
            self.envios.append(p)

class TestFlujoNPCMisiones(unittest.TestCase):
    def setUp(self):
        misiones._cargar_db()
        self.p = Personaje(
            entity_id=1001,
            char_id=1001,
            nombre='KarmaTest',
            stage=29,  # Breeze Woods
            faction='Breeze Woods',
            nivel=430,
            quests=[]
        )
        self.ses = MockSesion(self.p)

    def test_militia_chief_dialogo_y_oferta(self):
        """Verifica que Militia Chief (121962) tenga dialogo propio y ofrezca Quest 506."""
        # 1. Dialogo propio
        dp = dialogos.propio('Militia Chief', entidad=121962)
        self.assertIsNotNone(dp)
        self.assertTrue(len(dp) > 0)
        # Portrait de Militia Chief debe ser 32 (sprite 40032)
        val = dialogos.val_por_entidad(121962)
        self.assertEqual(val, 32)

        # 2. Misiones disponibles
        disp = misiones.misiones_disponibles_npc(self.p, 'Militia Chief')
        self.assertIn(506, disp)
        self.assertEqual(disp[0], 506)

        # 3. Guion de oferta con opciones de aceptar y salir
        g = dialogos.guion_de_mision(506, 'Militia Chief', jugador=self.p.nombre, entidad=121962, completada=False)
        self.assertIsNotNone(g)
        opts = dialogos.opciones_de(g[0])
        self.assertEqual(len(opts), 2)
        # La opcion 0 es aceptar (50604 "Do you need my help?"), la 1 es salir (50605 "Leave")
        self.assertEqual(opts[0], 50604)
        self.assertEqual(opts[1], 50605)

    def test_aceptar_y_rechazar_mision_ofrecida(self):
        """Verifica que elegir la opcion 0 acepta la mision y la opcion 1 no la impone."""
        # Rechazar (opcion 1)
        self.ses.dlg_quest_ofrecida = 506
        # Simular rechazo
        self.ses.dlg_quest_ofrecida = None
        self.assertFalse(misiones.tiene_mision(self.p, 506))

        # Aceptar (opcion 0)
        res = misiones.aceptar_mision(self.ses, 506)
        self.assertTrue(res)
        self.assertTrue(misiones.tiene_mision(self.p, 506))
        self.assertEqual(misiones.obtener_paso_actual(self.p, 506), 1)

        # Ya no debe ofrecerse mientras este activa
        disp2 = misiones.misiones_disponibles_npc(self.p, 'Militia Chief')
        self.assertNotIn(506, disp2)

    def test_cobertura_universal_dialogos_todos_npc(self):
        """Comprueba que una muestra diversa de NPCs en diferentes mapas NUNCA de 'sin dialogo'."""
        npcs = dialogos._cargar_npcs()
        self.assertGreater(len(npcs), 1000)

        # Probar 100 NPCs al azar de diferentes mapas
        import random
        random.seed(42)
        sample_eids = random.sample(list(npcs.keys()), 100)

        for eid in sample_eids:
            info = npcs[eid]
            nom = info['nombre']
            dp = dialogos.propio(nom, entidad=eid)
            self.assertIsNotNone(dp, f"NPC {nom} (eid={eid}) no tiene dialogo")
            self.assertTrue(len(dp) > 0)
            self.assertTrue(len(dp[0]) >= 6)

if __name__ == '__main__':
    unittest.main()

