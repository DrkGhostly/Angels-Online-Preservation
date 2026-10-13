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

        # 2. Misiones disponibles en Breeze Woods (stage 29) -> Quest 542
        disp = misiones.misiones_disponibles_npc(self.p, 'Militia Chief', stage=29)
        self.assertIn(542, disp)
        self.assertEqual(disp[0], 542)

        # 3. Misiones disponibles en Dense Forest (stage 23) -> Quest 506
        disp_dense = misiones.misiones_disponibles_npc(self.p, 'Militia Chief', stage=23)
        self.assertEqual(disp_dense, [506])

        # 4. Flujo interactivo autentico para 542
        flujo = dialogos.info_flujo_mision(542)
        self.assertEqual(flujo['pregunta'], 54202)
        self.assertEqual(flujo['ops_preg'], [54203, 54204])
        self.assertEqual(flujo['propuesta'], 54205)
        self.assertEqual(flujo['ops_prop'], [54206, 54207])

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
        """Comprueba que los NPCs con dialogo registrado devuelvan un paquete 0x0012 valido."""
        propios = dialogos._propios()
        self.assertGreater(len(propios), 500)

        for nom, data in list(propios.items())[:100]:
            if data.get('msgid') == 5006:
                continue
            dp = dialogos.propio(nom)
            self.assertIsNotNone(dp, f"NPC {nom} no tiene dialogo")
            self.assertTrue(len(dp) > 0)
            self.assertTrue(len(dp[0]) >= 6)

    def test_leif_y_fleming_dialogos(self):
        """Verifica los dialogos y flujos especificos de Leif (1566) y Mr. Fleming (1573)."""
        # Leif idle
        dp_leif = dialogos.propio('Leif')
        self.assertIsNotNone(dp_leif)
        self.assertEqual(struct.unpack_from('<I', dp_leif[0], 0)[0], 156616)

        # Leif paso 1 avanzada
        g1 = dialogos.guion_de_mision(1566, 'Leif', paso=1, tipo_evento='avanzada')
        self.assertEqual([struct.unpack_from('<I', m, 0)[0] for m in g1], [156617, 156618, 156619])

        # Leif paso 2 progreso
        g2 = dialogos.guion_de_mision(1566, 'Leif', paso=2, tipo_evento='recoleccion_incompleta')
        self.assertEqual([struct.unpack_from('<I', m, 0)[0] for m in g2], [156620])

        # Mr. Fleming idle
        dp_fl = dialogos.propio('Mr. Fleming')
        self.assertIsNotNone(dp_fl)
        self.assertEqual(struct.unpack_from('<I', dp_fl[0], 0)[0], 157311)

        # Mr. Fleming oferta quest 1573 en Wise Institute
        p_fl = Personaje(char_id=1, nombre='Heroe', stage=406, nivel=430)
        disp = misiones.misiones_disponibles_npc(p_fl, 'Mr. Fleming', stage=406)
        self.assertIn(1573, disp)

        # Mr. Fleming paso 1 progreso
        g_fl1 = dialogos.guion_de_mision(1573, 'Mr. Fleming', paso=1, tipo_evento='recoleccion_incompleta')
        self.assertEqual([struct.unpack_from('<I', m, 0)[0] for m in g_fl1], [157307])


if __name__ == '__main__':
    unittest.main()


