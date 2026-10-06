"""La tabla que une cada `game.*` de los Lua con su funcion en Angel.exe.

Los scripts del cliente (extracted_luas/*.lua) llaman a nativas:
`game.sendcollect`, `game.dropbankitem`, `game.getmoney`... Cada una es
codigo dentro de Angel.exe, y es ahi donde se arma el paquete que viaja al
servidor. Saber que funcion corresponde a cada nombre es el primer paso
para leer esos paquetes sin tener que capturarlos.

Angel.exe registra las nativas con una tabla de pares
{const char *nombre; funcion}, que es lo que esto lee:

  1. se parsea el PE para poder pasar de offset de archivo a direccion
  2. se busca cada nombre como cadena y se calcula su direccion
  3. se busca esa direccion como PUNTERO dentro del binario: ahi esta la
     entrada de la tabla, y el DWORD siguiente es la funcion

OJO con Angel_unpacked.c: tiene 11.190 funciones y sirve para mucho, pero
NO cubre el rango 0x588000-0x59Bxxx, que es justo donde caen casi todas
las nativas. Para esas hay que desensamblar a mano desde el .exe.

Uso:
    python tools/nativas_lua.py                 # todas las que usan los lua
    python tools/nativas_lua.py sendcollect     # una
    python tools/nativas_lua.py --json          # a plantillas/nativas_lua.json
"""
import glob
import json
import pathlib
import re
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent


def _exe() -> pathlib.Path:
    try:
        sys.path.insert(0, str(RAIZ / 'server'))
        import cliente_local
        p = cliente_local.ruta_cliente() / 'Angel.exe'
        if p.exists():
            return p
    except Exception:
        pass
    return pathlib.Path(r'C:\AO\Angels Online\Angel.exe')


class Pe:
    def __init__(self, datos: bytes):
        self.b = datos
        pe = struct.unpack_from('<I', datos, 0x3C)[0]
        nsec = struct.unpack_from('<H', datos, pe + 6)[0]
        optsz = struct.unpack_from('<H', datos, pe + 20)[0]
        self.base = struct.unpack_from('<I', datos, pe + 24 + 28)[0]
        self.secs = []
        off = pe + 24 + optsz
        for _ in range(nsec):
            vsz, va, rsz, raw = struct.unpack_from('<IIII', datos, off + 8)
            self.secs.append((va, vsz, raw, rsz))
            off += 40

    def va(self, fo):
        for va, vsz, raw, rsz in self.secs:
            if raw <= fo < raw + rsz:
                return self.base + va + (fo - raw)
        return None


def nombres_de_los_lua() -> set:
    """Los `game.*` que de verdad usan los scripts del cliente."""
    out = set()
    for f in glob.glob(str(RAIZ / 'extracted_luas' / '*.lua')):
        try:
            t = pathlib.Path(f).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        out.update(re.findall(r'game\.([a-zA-Z_][a-zA-Z0-9_]*)', t))
    return out


def tabla(nombres=None) -> dict:
    exe = _exe()
    if not exe.exists():
        return {}
    b = exe.read_bytes()
    pe = Pe(b)
    out = {}
    for nom in sorted(nombres or nombres_de_los_lua()):
        cruda = nom.encode('ascii') + b'\x00'
        fo = b.find(cruda)
        if fo < 0:
            continue
        v = pe.va(fo)
        if v is None:
            continue
        refs = [m.start() for m in re.finditer(re.escape(struct.pack('<I', v)), b)]
        for r in refs:
            fn = struct.unpack_from('<I', b, r + 4)[0]
            # La funcion tiene que caer dentro de .text para ser creible.
            if 0x401000 <= fn < pe.base + pe.secs[0][0] + pe.secs[0][1]:
                out[nom] = {'cadena': v, 'funcion': fn, 'entrada': pe.va(r)}
                break
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    t = tabla(set(args) if args else None)
    if '--json' in sys.argv[1:]:
        f = RAIZ / 'server' / 'plantillas' / 'nativas_lua.json'
        f.write_text(json.dumps(
            {'_nota': 'game.* de los Lua -> funcion en Angel.exe. '
                      'Ver tools/nativas_lua.py.',
             'nativas': {k: {kk: ('0x%X' % vv) for kk, vv in v.items()}
                         for k, v in sorted(t.items())}},
            ensure_ascii=False, indent=1), encoding='utf-8')
        print('%d nativas -> %s' % (len(t), f))
        return 0
    print('%d nativas localizadas en %s' % (len(t), _exe()))
    for nom, v in sorted(t.items()):
        print('  %-26s funcion 0x%06X   (cadena 0x%X)'
              % (nom, v['funcion'], v['cadena']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
