"""Escribe server/plantillas/transitable.bin: que casillas se pueden pisar.

POR QUE. Los monstruos atravesaban paredes: el servidor no sabia donde hay
pared, asi que perseguian en linea recta y paseaban a cualquier casilla, y
el jugador tenia que pegarles con habilidades de rango desde el otro lado.

DE DONDE SALE. La capa de casillas del .mpc (tools/mapa_del_cliente.py: en
el +96, un registro por casilla, de 6 o 7 bytes segun la version del mapa).
tools/cobertura_mapa.py dio por hecho que ahi no estaba lo transitable; se
miro sin voltear la y, que el .mpc cuenta desde ABAJO. Volteada:

    6 bytes por casilla (73, 74...)   byte 1, bits 0-1
    7 bytes por casilla (41, 410...)  byte 2, bits 0-1
    a cero -> se pisa; cualquier otro valor -> pared, agua, vacio

Contrastado con las casillas a las que se movieron los jugadores en las
capturas (c2s 0x0004): en 30 mapas con 50 casillas o mas, el 99,93% cae en
transitable. En la sala 1 de la Magic Kichen Path, 3185 de 3188.

FORMATO. [u32 cuantos mapas] y por cada uno [u16 stage][u16 ancho][u16 alto]
y ancho*alto bits (fila a fila, y del servidor, bit 1 = se pisa).

    python tools/transitable.py
"""
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))

import mapa_del_cliente as mc

SALIDA = RAIZ / 'server' / 'plantillas' / 'transitable.bin'
CAMPOS_CABECERA = (24, 32, 52, 60, 68, 76)


def capa(ruta):
    """(ancho, alto, bytearray de bits) de un .mpc, o None."""
    b = ruta.read_bytes() if hasattr(ruta, 'read_bytes') else open(ruta, 'rb').read()
    if b[:3] != b'MAP':
        return None
    w, h = struct.unpack_from('<II', b, 4)
    offs = sorted(o for o in (struct.unpack_from('<I', b, k)[0] for k in CAMPOS_CABECERA) if o > 96)
    if not offs or not w or not h:
        return None
    tam = (offs[0] - 96) // (w * h)
    if tam not in (6, 7):
        return None
    k = 1 if tam == 6 else 2
    bits = bytearray((w * h + 7) // 8)
    for y in range(h):
        fila = (h - 1 - y) * w            # la y del .mpc va del reves
        for x in range(w):
            if b[96 + (fila + x) * tam + k] & 3 == 0:
                i = y * w + x
                bits[i >> 3] |= 1 << (i & 7)
    return w, h, bits


def main():
    salida, n = bytearray(), 0
    for stage, ruta in sorted(mc.mapas_del_cliente().items()):
        c = capa(ruta)
        if c is None:
            continue
        w, h, bits = c
        salida += struct.pack('<HHH', stage, w, h) + bits
        n += 1
    SALIDA.write_bytes(struct.pack('<I', n) + bytes(salida))
    print('%s: %d mapas, %d KB' % (SALIDA, n, SALIDA.stat().st_size // 1024))


if __name__ == '__main__':
    main()
