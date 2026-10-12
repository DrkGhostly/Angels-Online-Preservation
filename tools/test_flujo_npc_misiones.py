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
        """Verifica que Militia Chief (121962) ofrezca Quest 556 en Breeze Woods y Quest 506 en Dense Forest."""
        # 1. Dialogo propio
        dp = dialogos.propio('Militia Chief', entidad=121962)
        self.assertIsNotNone(dp)
        self.assertTrue(len(dp) > 0)
        # Portrait de Militia Chief debe ser 32 (sprite 40032)
        val = dialogos.val_por_entidad(121962)
        self.assertEqual(val, 32)

        # 2. Misiones disponibles en Breeze Woods (stage 29) -> Quest 556
        disp = misiones.misiones_disponibles_npc(self.p, 'Militia Chief', stage=29)
        self.assertIn(556, disp)
        self.assertEqual(disp[0], 556)

        # 3. Misiones disponibles en Dense Forest (stage 23) -> Quest 506
        disp_dense = misiones.misiones_disponibles_npc(self.p, 'Militia Chief', stage=23)
        self.assertEqual(disp_dense, [506])

        # 4. Flujo interactivo autentico para 556
        flujo = dialogos.info_flujo_mision(556)
        self.assertEqual(flujo['intro'], [55601])
        self.assertEqual(flujo['pregunta'], 55602)
        self.assertEqual(flujo['ops_preg'], [55603, 55604])
        self.assertEqual(flujo['propuesta'], 55605)
        self.assertEqual(flujo['ops_prop'], [55606, 55607])
        self.assertEqual(flujo['exito'], 55608)
        self.assertEqual(flujo['progreso'], 55609)
        self.assertEqual(flujo['completada'], [55610, 55611])

    def test_aceptar_y_rechazar_mision_ofrecida(self):
        """Verifica que rechazar no otorgue la mision y que aceptar la registre adecuadamente."""
        # Rechazar
        self.ses.dlg_quest_ofrecida = 556
        self.ses.dlg_quest_fase = 'propuesta'
        # Simular rechazo
        self.ses.dlg_quest_ofrecida = None
        self.ses.dlg_quest_fase = None
        self.assertFalse(misiones.tiene_mision(self.p, 556))

        # Aceptar
        res = misiones.aceptar_mision(self.ses, 556)
        self.assertTrue(res)
        self.assertTrue(misiones.tiene_mision(self.p, 556))
        self.assertEqual(misiones.obtener_paso_actual(self.p, 556), 1)

        # Ya no debe ofrecerse mientras este activa
        disp2 = misiones.misiones_disponibles_npc(self.p, 'Militia Chief', stage=29)
        self.assertNotIn(556, disp2)

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

