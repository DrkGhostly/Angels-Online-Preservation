"""Verifica que cada entrada del 0x001A cumpla la formula del cliente:
len(entrada) == 1 + 85 + WORD(e[51:53])  (sub_5F9650: v19 += *(WORD*)(v19+50) + 85)."""
import json, struct, sqlite3, sys
sys.path.insert(0, 'server')
import inventario as inv

con = sqlite3.connect('data/cuentas.db')
malos = 0
total = 0
for u, cid, nom, raw in con.execute("SELECT usuario, char_id, nombre, datos FROM personajes"):
    d = json.loads(raw)
    bolsa = d.get('inventario', {}) or {}
    mej = {int(k): v for k, v in (d.get('mejoras') or {}).items()}
    items = [(int(r), int(i), 1) for r, i in bolsa.items()]
    pkt = inv.completo(cid, items, cid + 50000, mejoras=mej,
                       mascota=d.get('mascota'), mascotas=d.get('mascotas'))
    n = struct.unpack_from('<I', pkt, 2)[0]
    off = 6
    for k in range(n):
        extra = struct.unpack_from('<H', pkt, off + 51)[0]
        largo = 86 + extra
        item = struct.unpack_from('<I', pkt, off + 9)[0]
        total += 1
        if off + largo > len(pkt):
            print('DESBORDE', nom, item); malos += 1; break
        off += largo
    if off != len(pkt):
        print(f'DESINCRONIZADO {nom}: parse termino en {off}, paquete mide {len(pkt)}')
        malos += 1
print('entradas:', total, 'personajes con error:', malos)

