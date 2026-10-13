import sys
import unittest

sys.path.insert(0, r'f:\Ao Proyect\AO 2\server')

import misiones
import dialogos
import clases


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

    def test_caceria_paso_a_paso_sin_salto_prematuro(self):
        """Verifica que las bajas se registren y la entrega requiera hablar con el NPC sin saltar solo."""
        ses = MockSesion()
        p = ses.personaje
        
        # Quest 1: 'Quest for test' -> Defeat 5 Slarm, turn in to Angels' Tutor
        # Usamos quest 202: 20 Pumpkins
        misiones.aceptar_mision(ses, 202)
        self.assertTrue(misiones.tiene_mision(p, 202))
        st, pa, comp = misiones.estado_mision(p, 202)
        self.assertEqual(pa, 1)
        self.assertFalse(comp)

        # Matar 10 Pumpkins (menos de los 20 requeridos)
        for _ in range(10):
            misiones.registrar_baja_monstruo(ses, 21, 'Pumpkin')

        # No debe haber avanzado de paso todavia
        st, pa, comp = misiones.estado_mision(p, 202)
        self.assertEqual(pa, 1)
        self.assertFalse(comp)

        # Hablar con Spike Farmer antes de tiempo: caceria_incompleta
        proc, tipo, datos = misiones.interactuar_npc(ses, 'Spike Farmer')
        self.assertTrue(proc)
        self.assertEqual(tipo, 'caceria_incompleta')

        # Matar los 10 restantes para llegar a 20/20
        for _ in range(10):
            misiones.registrar_baja_monstruo(ses, 21, 'Pumpkin')

        # Las bajas estan listas (20/20), y la mision avanza al paso 2 (reportar/entregar)
        self.assertEqual(ses.quest_kills.get((202, 1)), 20)
        self.assertEqual(p.quests[0][1], 2)

        # Ahora el jugador va donde Spike Farmer y habla con el (encadena el reporte y la entrega)
        proc, tipo, datos = misiones.interactuar_npc(ses, 'Spike Farmer')
        self.assertTrue(proc)
        self.assertIn(tipo, ('avanzada', 'completada'))
        st, pa, comp = misiones.estado_mision(p, 202)
        self.assertTrue(comp or pa >= 2)

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

    def test_abandonar_mision(self):
        """Verifica que el jugador pueda abandonar/quitar misiones tomadas (0x0016 accion 8 / 0x0022 modo 2)."""
        ses = MockSesion()
        p = ses.personaje

        # Aceptar quest normal
        misiones.aceptar_mision(ses, 1501)
        self.assertTrue(misiones.tiene_mision(p, 1501))

        # Abandonar mision
        ok = misiones.abandonar_mision(ses, 1501)
        self.assertTrue(ok)
        self.assertFalse(misiones.tiene_mision(p, 1501))

        # Verificar paquete 0x0022 de borrado enviado
        encontro_paquete_borrado = False
        for pkg in ses.enviados:
            if len(pkg) >= 24 and pkg[:2] == b'\x22\x00':
                # El byte 17 de la estructura de mision (offset 23 del paquete) debe ser modo 2
                if pkg[23] == 2:
                    encontro_paquete_borrado = True
                    break
        self.assertTrue(encontro_paquete_borrado, "Debe enviar paquete 0x0022 con modo=2 para borrar en cliente")

        # Proteger misiones del tutorial: no deben poder ser abandonadas
        p.quests.append((101, 1))
        ok_tut = misiones.abandonar_mision(ses, 101)
        self.assertFalse(ok_tut, "Las misiones de tutorial no se deben poder abandonar")
        self.assertTrue(misiones.tiene_mision(p, 101))

    def test_sin_teletransporte_automatico(self):
        """Verifica que no se teletransporte al jugador al aceptar o completar misiones normales."""
        ses = MockSesion()
        p = ses.personaje
        stage_original = p.stage

        # Aceptar mision normal
        misiones.aceptar_mision(ses, 201)
        # El stage no debe cambiar
        self.assertEqual(p.stage, stage_original)

        # obtener_mapa_instancia debe devolver None para misiones normales de mundo abierto
        self.assertIsNone(misiones.obtener_mapa_instancia(201, 1))
        self.assertIsNone(misiones.obtener_mapa_instancia(1000, 1))

    def test_proteccion_tutorial_y_faccion(self):
        """Verifica que interactuar_npc no toque a los NPCs de tutorial ni de eleccion de faccion."""
        ses = MockSesion()
        p = ses.personaje

        # Angel Raphael
        proc, tipo, _ = misiones.interactuar_npc(ses, 'Angel Raphael')
        self.assertFalse(proc)
        self.assertEqual(tipo, 'tutorial')

        # Director Wolay
        proc, tipo, _ = misiones.interactuar_npc(ses, 'Director Wolay')
        self.assertFalse(proc)
        self.assertEqual(tipo, 'tutorial')

        # Angeles de faccion
        proc, tipo, _ = misiones.interactuar_npc(ses, 'Angel of Aurora')
        self.assertFalse(proc)
        self.assertEqual(tipo, 'tutorial')

        # Si el personaje esta en stage 51 o 57 (palacios del tutorial)
        p.stage = 51
        proc, tipo, _ = misiones.interactuar_npc(ses, 'Spike Farmer')
        self.assertFalse(proc)
        self.assertEqual(tipo, 'tutorial')

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
        self.assertTrue(len(g) >= 1)
        ops = dialogos.opciones_de(g[-1])
        self.assertIn(150102, ops)
        self.assertIn(150103, ops)

    def test_resolucion_mapa_instancia_especiales(self):
        """Verifica que instancias reales sigan en QUEST_MAPAS_INSTANCIA."""
        # Training Palace (stage 244)
        st123 = misiones.obtener_mapa_instancia(123, 1)
        self.assertEqual(st123, 244)
        
        # Poker Castle (stage 158)
        st162 = misiones.obtener_mapa_instancia(162, 1)
        self.assertEqual(st162, 158)

    def test_filtrado_faccion(self):
        """Verifica que las misiones de faccion solo se ofrezcan a su faccion."""
        p_aurora = MockPersonaje()
        p_aurora.faction = 'Aurora'
        p_shadow = MockPersonaje()
        p_shadow.faction = 'Shadow'

        # Quest 127 es de Aurora, 128 es de Shadow
        disp_aurora = misiones.misiones_disponibles_npc(p_aurora, 'Aurora Angel')
        disp_shadow = misiones.misiones_disponibles_npc(p_shadow, 'Aurora Angel')
        self.assertNotIn(128, disp_aurora)
        self.assertNotIn(127, disp_shadow)

    def test_dialogos_angeles_ciudad_y_residentes(self):
        """Verifica opciones 2, 3, 4, 18 de los Angeles y retratos de residentes."""
        import struct
        for base in (20000, 30000, 40000, 50000):
            r2 = dialogos.respuesta_a(base + 2, val=112)
            self.assertEqual(len(r2), 6)
            r3 = dialogos.respuesta_a(base + 3, val=112)
            self.assertEqual(len(r3), 3)
            self.assertEqual(struct.unpack_from('<I', r3[0], 2)[0], base + 11)
            r4 = dialogos.respuesta_a(base + 4, val=112)
            self.assertEqual(len(r4), 3)
            r18 = dialogos.respuesta_a(base + 18, val=112)
            self.assertEqual(len(r18), 1)
            self.assertEqual(struct.unpack_from('<I', r18[0], 2)[0], base + 19)

        # Explorer Gulin (Breeze Woods)
        gulin_dlg = dialogos.propio("Explorer Gulin")
        self.assertIsNotNone(gulin_dlg)
        mid_gulin = struct.unpack_from('<I', gulin_dlg[0], 0)[0]
        val_gulin = struct.unpack_from('<H', gulin_dlg[0], 4)[0]
        self.assertEqual(mid_gulin, 50010)
        self.assertEqual(val_gulin, 200)

        # Explorer Lim (Aurora City)
        lim_dlg = dialogos.propio("Explorer Lim")
        self.assertIsNotNone(lim_dlg)
        mid_lim = struct.unpack_from('<I', lim_dlg[0], 0)[0]
        val_lim = struct.unpack_from('<H', lim_dlg[0], 4)[0]
        self.assertEqual(mid_lim, 20010)
        self.assertEqual(val_lim, 108)

    def test_completar_mision_paquetes_validos(self):
        """Verifica que completar_mision no genere paquetes 0x001B corruptos ni desborde el cliente."""
        import inventario, struct
        ses = MockSesion()
        p = MockPersonaje()
        p.quests = [[502, 2]]
        p.nivel = 430
        p.exp = 12405849063849440
        ses.personaje = p
        ses.inventario = {20: 181, 21: 200}
        ses.cantidades = {20: 1, 21: 1}
        ses.oro = 50000

        ok = misiones.completar_mision(ses, 502, exp=1000, oro=500, creditos_honor=20)
        self.assertTrue(ok)
        for pkg in ses.enviados:
            op = struct.unpack_from('<H', pkg, 0)[0]
            if op == 0x001B:
                # Cada 0x001B valido debe medir al menos 12 bytes
                self.assertGreaterEqual(len(pkg), 12, f"0x001B corrupto con len {len(pkg)}")

    def test_items_ocultos_no_entran_en_bolsa(self):
        """Verifica que tokens de caceria como 969, 956, 16075 no entren en mochila visible."""
        import inventario, app
        self.assertTrue(inventario.es_item_oculto(969))
        self.assertTrue(inventario.es_item_oculto(956))
        self.assertTrue(inventario.es_item_oculto(16075))
        self.assertTrue(inventario.es_item_oculto(78179))
        self.assertTrue(inventario.es_item_oculto(78180))
        self.assertFalse(inventario.es_item_oculto(181)) # Mushroom normal

        ses = MockSesion()
        ses.inventario = {}
        ses.cantidades = {}
        res = app._meter(ses, 969, 1)
        self.assertIsNone(res, "Item oculto 969 no debe poder entrar en la mochila")

    def test_tokens_mision_inventario_oculto(self):
        """Verifica que los tokens de mision (cat 5001) se enruten a ranuras ocultas 497..556."""
        import inventario
        ses = MockSesion()
        p = MockPersonaje()
        p.quests = [[1590, 2]]
        ses.personaje = p
        ses.inventario = {}
        ses.cantidades = {}

        slot = misiones.slot_oculto_para_item(ses, 78179, qid=1590)
        self.assertTrue(497 <= slot <= 556, f"Slot {slot} debe estar en el rango 497..556")
        self.assertEqual(slot, 527)

        # vaciar_ranura debe permitir ranuras 497..556
        pkg_vac = inventario.vaciar_ranura(1001, 527)
        self.assertGreater(len(pkg_vac), 0)

        # actualizar_ranura debe generar entrada valida para el cliente
        pkg_act = inventario.actualizar_ranura(1001, 527, 78179, 1)
        self.assertGreater(len(pkg_act), 0)


if __name__ == '__main__':
    unittest.main()


