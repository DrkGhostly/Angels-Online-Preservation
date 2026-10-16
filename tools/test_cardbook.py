"""Isolated Card Book regression checks; never imports live accounts DB."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('AO_CARD_TEST_ROOT', str(Path(__file__).resolve().parents[1])))
STAGE = Path(__file__).parent / 'server'
if not STAGE.exists():
    STAGE = ROOT / 'server'
sys.path[:0] = [str(STAGE), str(ROOT / 'server'), str(ROOT / 'proto')]
import cartas
import inventario

# Load the changed accounts functions without its import-time _init_db call.
cuentas = ModuleType('cuentas')
cuentas.__file__ = str(STAGE / 'cuentas.py')
tree = ast.parse((STAGE / 'cuentas.py').read_text(encoding='utf-8'))
tree.body = [n for n in tree.body if not (
    isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
    and isinstance(n.value.func, ast.Name) and n.value.func.id == '_init_db')]
exec(compile(tree, str(STAGE / 'cuentas.py'), 'exec'), cuentas.__dict__)
sys.modules['cuentas'] = cuentas

# Exercise the actual inventory helpers, without app import/startup side effects.
tree_app = ast.parse((STAGE / 'app.py').read_text(encoding='utf-8'))
names = {'_meter', '_sacar', '_cantidades', '_cant_de', '_instancias'}
helpers = {n.name: n for n in tree_app.body if isinstance(n, ast.FunctionDef)
           and n.name in names}
ns = {'log': cartas.log, '_ranura_libre': lambda bolsa: next(
    (r for r in range(20, 80) if r not in bolsa), None)}
exec(compile(ast.Module(body=list(helpers.values()), type_ignores=[]),
             'actual_inventory_helpers', 'exec'), ns)

cartas.BASE = ROOT
cartas._TABLA = json.loads((ROOT / 'server/plantillas/cartas.json').read_text(
    encoding='utf-8'))['filas']
cartas._SETS = {s['id']: s for s in json.loads(
    (STAGE / 'plantillas/cardsets.json').read_text(encoding='utf-8'))['filas']}


class CardBook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cuentas.BASE = Path(self.tmp.name)
        cuentas.DB_PATH = cuentas.BASE / 'accounts.db'
        cuentas.BACKUPS_DIR = cuentas.BASE / 'backups'
        cuentas.ARCHIVO = cuentas.BASE / 'mirror.json'
        con = sqlite3.connect(cuentas.DB_PATH)
        con.execute('CREATE TABLE personajes(usuario TEXT, char_id INT, ranura INT, '
                    'nombre TEXT, datos TEXT, actualizado_en TEXT)')
        self.original = {'nombre': 'Test', 'cartas': [], 'cartas_canjes': [],
                         'quests': [[100, 3]], 'album': {'weapon': 42},
                         'inventario': {'276': 5346}, 'cantidades': {'276': 2}}
        con.execute('INSERT INTO personajes VALUES(?,?,?,?,?,NULL)',
                    ('tester', 123, 0, 'Test', json.dumps(self.original)))
        con.commit()
        con.close()
        self.persist = patch.object(cuentas, '_notificar_cambio')
        self.notify = self.persist.start()
        p = SimpleNamespace(entity_id=1123, char_id=123, cartas=[], cartas_canjes=[],
                            mejoras={}, mascota={}, mascotas={})
        self.sent = []
        self.ses = SimpleNamespace(usuario='tester', personaje=p,
                                   inventario={276: 5346}, cantidades={276: 2},
                                   instancias={}, enviar=lambda *pkts: self.sent.extend(pkts))
        self.refresh = lambda ses, slots: [struct.pack('<HH', 0x001B, r) for r in slots]

    def tearDown(self):
        self.persist.stop()
        self.tmp.cleanup()

    def saved(self):
        with sqlite3.connect(cuentas.DB_PATH) as c:
            return json.loads(c.execute('SELECT datos FROM personajes').fetchone()[0])

    def register(self, slot=276):
        return cartas.registrar(self.ses, slot, ns['_sacar'], self.refresh)

    def test_exact_item_lookup(self):
        self.assertEqual(cartas.carta_de_item(5346)['id'], 1)
        self.assertIsNone(cartas.carta_de_item(3460))  # Pet Double EXP Card
        self.assertIsNone(cartas.carta_de_item(1))

    def test_register_one_from_stack_and_native_packet(self):
        self.assertTrue(self.register())
        self.assertEqual(self.ses.personaje.cartas, [1])
        self.assertEqual(self.ses.cantidades[276], 1)
        self.assertEqual(self.saved()['cartas'], [1])
        self.assertEqual(self.saved()['cantidades']['276'], 1)
        self.assertEqual(self.saved()['quests'], self.original['quests'])
        self.assertEqual(self.saved()['album'], self.original['album'])
        self.assertEqual(struct.unpack('<HIBBII', self.sent[-1]),
                         (0x001D, 1123, 1, 27, 1, 1))
        self.notify.assert_called_once_with(inmediato=True)

    def test_duplicate_and_foreign_item_not_consumed(self):
        self.register()
        after = copy.deepcopy(self.saved())
        self.register()
        self.assertEqual(self.saved(), after)
        self.assertEqual(self.ses.cantidades[276], 1)
        self.ses.inventario[30] = 3460
        self.assertFalse(self.register(30))
        self.assertEqual(self.ses.inventario[30], 3460)

    def test_failed_save_does_not_consume(self):
        with patch.object(cuentas, 'guardar_cardbook', side_effect=OSError('disk full')):
            self.register()
        self.assertEqual(self.ses.cantidades[276], 2)
        self.assertEqual(self.ses.personaje.cartas, [])
        self.assertEqual(self.saved(), self.original)

    def test_wrong_character_fails_without_fallback(self):
        self.ses.personaje.char_id = 999
        self.register()
        self.assertEqual(self.ses.personaje.cartas, [])
        self.assertEqual(self.saved(), self.original)

    def test_all_rewards_one_time_and_reconnect(self):
        self.ses.personaje.cartas = [5, 6, 7, 8]
        cartas.canjear(self.ses, bytes([2, 255]), ns['_meter'], self.refresh)
        self.assertEqual(self.ses.personaje.cartas_canjes, [2])
        self.assertEqual(set(self.ses.inventario.values()), {5346, 3399, 3375, 7758})
        self.assertEqual(self.saved()['cartas_canjes'], [2])
        self.assertEqual(struct.unpack('<HIBBII', self.sent[-1]),
                         (0x001D, 1123, 1, 33, 2, 1))
        after = copy.deepcopy(self.saved())
        cartas.canjear(self.ses, bytes([2, 255]), ns['_meter'], self.refresh)
        self.assertEqual(self.saved(), after)
        p = SimpleNamespace(**self.saved())
        data = bytearray(b'\xff' * 4122)
        cartas.perfil(data, p)
        self.assertEqual(data[3959:4087], cartas.bitmap([5, 6, 7, 8], 1024))
        self.assertEqual(data[4087:4119], cartas.bitmap([2], 256))
        self.assertEqual(data[:3959], b'\xff' * 3959)
        self.assertEqual(data[4119:], b'\xff' * 3)

    def test_choice_validation(self):
        self.assertEqual(cartas.premios(13, 1, [49, 50, 51, 52], []), [(7345, 1)])
        for choice in (255, 2, 3):
            with self.assertRaises(ValueError):
                cartas.premios(13, choice, [49, 50, 51, 52], [])
        with self.assertRaises(ValueError):
            cartas.premios(2, 255, [5, 6, 7], [])

    def test_partial_room_no_partial_rewards(self):
        self.ses.personaje.cartas = [5, 6, 7, 8]
        # One free slot, three different rewards. The planned first reward
        # must not leak into live inventory when the second cannot fit.
        self.ses.inventario = {r: 1 for r in range(20, 79)}
        before = copy.deepcopy(self.ses.inventario)
        cartas.canjear(self.ses, bytes([2, 255]), ns['_meter'], self.refresh)
        self.assertEqual(self.ses.inventario, before)
        self.assertEqual(self.ses.personaje.cartas_canjes, [])
        self.assertEqual(self.saved(), self.original)

    def test_empty_profile_clears_capture(self):
        data = bytearray(b'\xff' * 4119)
        cartas.perfil(data, self.ses.personaje)
        self.assertEqual(data[3959:4119], bytes(160))

    def test_packet_routes_high_slot_and_exchange_not_inventory_swap(self):
        nodes = [n for n in ast.walk(tree_app) if isinstance(n, ast.If)
                 and isinstance(n.test, ast.BoolOp)
                 and isinstance(n.test.values[0], ast.Compare)
                 and isinstance(n.test.values[0].left, ast.Name)
                 and n.test.values[0].left.id == 'opcode'
                 and isinstance(n.test.values[0].comparators[0], ast.Constant)
                 and n.test.values[0].comparators[0].value in (0x0130, 0x0132)]
        self.assertEqual(len(nodes), 2)
        wrapper = ast.parse('def route(opcode, cuerpo, ses):\n pass')
        wrapper.body[0].body = nodes
        env = {'struct': struct, '_meter': ns['_meter'], '_sacar': ns['_sacar'],
               '_refrescar': self.refresh, 'addr': 'test', 'log': cartas.log}
        exec(compile(ast.fix_missing_locations(wrapper), 'actual_routes', 'exec'), env)
        self.ses.rol = 'mundo'
        env['route'](0x0132, struct.pack('<II', 276, 0), self.ses)
        self.assertEqual(self.ses.personaje.cartas, [1])
        self.assertEqual(self.ses.cantidades[276], 1)
        self.ses.inventario[2] = 99
        self.ses.inventario[255] = 98
        self.ses.personaje.cartas = [5, 6, 7, 8]
        env['route'](0x0130, bytes([2, 255]), self.ses)
        self.assertEqual(self.ses.inventario[2], 99)
        self.assertEqual(self.ses.inventario[255], 98)
        self.assertEqual(self.ses.personaje.cartas_canjes, [2])

    def test_profile_real_template(self):
        import login
        login.PLANTILLAS = ROOT / 'server/plantillas'
        seq = login._cargar_secuencia()
        raw = next(m['datos'] for m in seq if m['opcode'] == 2)
        p = login.Personaje(cartas=[1, 33, 459], cartas_canjes=[2, 106])
        result = login._ficha(p, raw)
        self.assertEqual(result[3959:4087], cartas.bitmap(p.cartas, 1024))
        self.assertEqual(result[4087:4119], cartas.bitmap(p.cartas_canjes, 256))


if __name__ == '__main__':
    unittest.main(verbosity=2)
