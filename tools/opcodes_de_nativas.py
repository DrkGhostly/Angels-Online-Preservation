"""Que OPCODE manda cada `game.*` de los Lua.

Encadena lo que saca tools/nativas_lua.py. Con la direccion de cada nativa
se desensambla su codigo y se busca la llamada al emisor de paquetes: el
opcode es la constante que se empuja justo antes.

Los emisores salieron de mirar `sendcollect`, que acaba asi:

    push ecx          ; un u16
    push 0x33         ; EL OPCODE
    call 0x614DA0     ; el emisor
    add  esp, 8

Hay dos, con firmas distintas:

    0x614DA0   (opcode, u16)
    0x6792C0   (opcode, ...)   lo usan blacklistadd (0xCA) y
                               blacklistremove (0xCB), consecutivos, que
                               es la pinta que tienen los opcodes de verdad

Se descartan a proposito 0x52E9F0, 0x51C210 y 0x4970B0: reciben tambien
constantes pequenas pero son los lectores de argumentos de Lua (el numero
es el indice del argumento, no un opcode).

Uso:
    python tools/opcodes_de_nativas.py            # todas
    python tools/opcodes_de_nativas.py banco      # las que casen con eso
    python tools/opcodes_de_nativas.py --json     # a plantillas/opcodes_nativas.json
"""
import json
import pathlib
import struct
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))

EMISORES = (0x614DA0, 0x6792C0)
# Lectores de argumentos de Lua: reciben el indice del argumento, no opcodes.
NO_EMISORES = (0x52E9F0, 0x51C210, 0x4970B0, 0x698A90, 0x52EB20, 0x52EA90)


class Pe:
    def __init__(self, datos):
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

    def off(self, v):
        for va, vsz, raw, rsz in self.secs:
            if self.base + va <= v < self.base + va + rsz:
                return raw + (v - self.base - va)
        return None


def opcodes() -> dict:
    import capstone
    import nativas_lua
    exe = nativas_lua._exe()
    if not exe.exists():
        return {}
    b = exe.read_bytes()
    pe = Pe(b)
    nat = nativas_lua.tabla()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = {}
    for nom, v in nat.items():
        a = v['funcion']
        fo = pe.off(a)
        if fo is None:
            continue
        ins = list(md.disasm(b[fo:fo + 1600], a))
        ops = []
        for k, i in enumerate(ins):
            if i.mnemonic != 'call' or not i.op_str.startswith('0x'):
                if i.mnemonic == 'ret':
                    break
                continue
            destino = int(i.op_str, 16)
            if destino not in EMISORES:
                continue
            for j in range(k - 1, max(-1, k - 9), -1):
                if ins[j].mnemonic != 'push':
                    continue
                o = ins[j].op_str
                val = (int(o, 16) if o.startswith('0x')
                       else int(o) if o.isdigit() else None)
                if val is not None and 0 < val < 0x400:
                    ops.append(val)
                break
        if ops:
            out[nom] = {'funcion': a, 'opcodes': sorted(set(ops))}
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    t = opcodes()
    if '--json' in sys.argv[1:]:
        f = RAIZ / 'server' / 'plantillas' / 'opcodes_nativas.json'
        f.write_text(json.dumps(
            {'_nota': 'game.* de los Lua -> opcode que manda. '
                      'Ver tools/opcodes_de_nativas.py.',
             'nativas': {k: {'funcion': '0x%X' % v['funcion'],
                             'opcodes': ['0x%04X' % o for o in v['opcodes']]}
                         for k, v in sorted(t.items())}},
            ensure_ascii=False, indent=1), encoding='utf-8')
        print('%d nativas con opcode -> %s' % (len(t), f))
        return 0
    filtro = args[0].lower() if args else None
    n = 0
    for nom, v in sorted(t.items()):
        if filtro and filtro not in nom.lower():
            continue
        print('  %-28s 0x%06X  ->  %s'
              % (nom, v['funcion'], ', '.join('0x%04X' % o for o in v['opcodes'])))
        n += 1
    print('\n%d de %d nativas mandan un opcode identificable' % (n, len(t)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
