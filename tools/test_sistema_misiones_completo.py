import sys
import unittest

sys.path.insert(0, r'f:\Ao Proyect\AO 2\server')

import misiones
import dialogos


class MockPersonaje:
    def __init__(self, nombre='HeroePrueba', nivel=30):
        self.char_id = 12345
        self.nombre = nombre
        self.nivel = nivel
        self.rango = 2
        self.creditos = 100
        self.oro = 5000
        self.exp = 10000
        self.stage = 3
        self.tile_x = 100
        self.tile_y = 100
        self.faction = 'Aurora'
        self.quests = []


class MockSesion:
    def __init__(self, personaje=None):
        self.personaje = personaje or MockPersonaje()
        self.usuario = 'testuser'
        self.oro = self.personaje.oro
        self.inventario = {}
        self.cantidades = {}
        self.addr = ('127.0.0.1', 8888)
        self.enviados = []
        self.quest_kills = {}

    def enviar(self, *pkgs):
        self.enviados.extend(pkgs)


class TestSistemaMisionesCompleto(unittest.TestCase):
    def test_carga_catalogo_completo(self):
        """Verifica que el catalogo contenga las 1489 misiones y metadatos."""
        m_total = misiones._cargar_misiones()
        self.assertEqual(len(m_total), 1489)
        
        # Mision repetible
        self.assertTrue(misiones.es_repetible(104))
        self.assertTrue(misiones.es_repetible(1501))
        
        # Mision no repetible
        self.assertFalse(misiones.es_repetible(100))

    def test_caceria_dinamica_por_nombre_y_tipo(self):
        """Verifica que matar monstruos avance el paso de misiones dinamicamente."""
        ses = MockSesion()
        p = ses.personaje
        
        # Quest 115: 'Battle-Primary course' -> Defeat 10 Slarm
        misiones.aceptar_mision(ses, 115)
        self.assertTrue(misiones.tiene_mision(p, 115))
        
        # Matar 10 Slarms (npc_type 19, nombre 'Slarm')
        for i in range(10):
            act = misiones.registrar_baja_monstruo(ses, 19, 'Slarm')
            self.assertTrue(act)
        
        # Al llegar a 10 muertes, debe avanzar automaticamente al paso 2
        st, pa, comp = misiones.estado_mision(p, 115)
        self.assertEqual(pa, 2)

    def test_recoleccion_y_entrega_items(self):
        """Verifica recoleccion de items e interaccion con el NPC de entrega."""
        ses = MockSesion()
        p = ses.personaje
        
        # Quest 104: 'The Beautiful World' (Potty en Vine Front) -> Bring back 65 item 14251
        misiones.aceptar_mision(ses, 104)
        misiones.avanzar_paso(ses, 104, 1)
        
        # Intentar hablar con Potty SIN items
        proc, tipo, datos = misiones.interactuar_npc(ses, 'Potty')
        self.assertTrue(proc)
        self.assertEqual(tipo, 'recoleccion_incompleta')
        
        # Darle los 65 items en la casilla 20
        ses.inventario[20] = 14251
        ses.cantidades[20] = 65
        
        # Ahora hablar con Potty con los items
        proc, tipo, datos = misiones.interactuar_npc(ses, 'Potty')
        self.assertTrue(proc)
        # Debe haber consumido los items de la mochila
        self.assertEqual(ses.inventario.get(20, 0), 0)
        # Y completado o avanzado la mision
        self.assertIn(tipo, ('completada', 'avanzada'))

    def test_misiones_repetibles(self):
        """Verifica que una mision repetible se pueda volver a tomar tras completarse."""
        ses = MockSesion()
        p = ses.personaje
        
        # Quest 1501 es repetible
        self.assertTrue(misiones.es_repetible(1501))
        
        misiones.aceptar_mision(ses, 1501)
        self.assertTrue(misiones.tiene_mision(p, 1501))
        
        # Completar
        misiones.completar_mision(ses, 1501, exp=5000, oro=1000)
        self.assertTrue(misiones.mision_completada(p, 1501))
        
        # Como es repetible, debe estar disponible nuevamente
        disponibles = misiones.misiones_disponibles_npc(p, 'Manager Pete')
        self.assertIn(1501, disponibles)
        
        # Volver a aceptarla
        ok = misiones.aceptar_mision(ses, 1501)
        self.assertTrue(ok)
        st, pa, comp = misiones.estado_mision(p, 1501)
        self.assertFalse(comp)

    def test_guion_de_mision_dialogo(self):
        """Verifica que guion_de_mision genere paquetes validos de 0x0012 con opciones reales."""
        g = dialogos.guion_de_mision(1501, 'Manager Pete', 'HeroePrueba')
        self.assertIsNotNone(g)
        self.assertEqual(len(g), 1)
        ops = dialogos.opciones_de(g[0])
        self.assertIn(150102, ops)
        self.assertIn(150103, ops)

    def test_resolucion_mapa_instancia(self):
        """Verifica que quests con mapa especial devuelvan su stage_id correcto."""
        # Training Palace (stage 244)
        st123 = misiones.obtener_mapa_instancia(123, 1)
        self.assertEqual(st123, 244)
        
        # Poker Castle (stage 158)
        st162 = misiones.obtener_mapa_instancia(162, 1)
        self.assertEqual(st162, 158)


if __name__ == '__main__':
    unittest.main()
