"""Todos los opcodes C->S que arma el cliente, sacados de Angel_unpacked.c.

COMO SE ARMA UN PAQUETE EN EL CLIENTE. Siempre igual, y se ve clarisimo en
el decompilado:

    sub_4C0EC0((int)&v3, 6);        reserva un mensaje de 6 bytes
    *(_WORD *)v4 = 337;             EL OPCODE          (0x0151)
    *v3 = 6;                        el LE16 de largo que va delante
    *(_DWORD *)(v4 + 2) = v9;       el cuerpo, desde el byte 2
    return sub_81D190(..., v5);     y lo manda

O sea: 0x4C0EC0 reserva, 0x81D190 envia, y el largo CUENTA los dos bytes
del opcode -- un mensaje de largo 2 no lleva cuerpo.

Esto esta COMPROBADO contra un opcode que ya teniamos medido de una
captura: el 350 (0x015E), la ficha de la mascota, sale con este mismo
patron y con cuerpo de un solo byte, que es justo como lo trata el
servidor.

OJO: tools/opcodes_de_nativas.py busca OTRA cosa. Aquel solo sigue al
emisor 0x614DA0, que arma siempre un 0x0016 de 7 bytes, asi que lo que
saca son los SUBTIPOS de ese canal multiplexado, no opcodes sueltos. Este
busca el otro emisor, el de los mensajes normales.

Uso:
    python tools/opcodes_del_cliente.py            # la tabla
    python tools/opcodes_del_cliente.py --json     # a plantillas/opcodes_cliente.json
"""
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).parent.parent
FUENTE = RAIZ / 'Angel_unpacked.c'

# sub_4C0EC0(&buf, largo) ... *(_WORD *)cuerpo = opcode
PATRON = re.compile(
    r'sub_4C0EC0\(\(int\)&(\w+),\s*(\d+)\);'
    r'(?:[^;]*;){0,3}?\s*'
    r'\*(?:\(_WORD \*\))?(\w+)\s*=\s*(\d+);', re.S)

# El comentario que IDA deja delante de cada funcion.
CABECERA = re.compile(r'//-+ \(([0-9A-Fa-f]{6,8})\) -+')


def _funciones(texto):
    """[(posicion, direccion)] de cada funcion del archivo, en orden."""
    return [(m.start(), int(m.group(1), 16)) for m in CABECERA.finditer(texto)]


def _duena(funcs, pos):
    """La direccion de la funcion que contiene esa posicion."""
    izq, der = 0, len(funcs) - 1
    hallada = None
    while izq <= der:
        med = (izq + der) // 2
        if funcs[med][0] <= pos:
            hallada = funcs[med][1]
            izq = med + 1
        else:
            der = med - 1
    return hallada


def tabla() -> dict:
    if not FUENTE.exists():
        return {}
    t = FUENTE.read_text(encoding='utf-8', errors='replace')
    funcs = _funciones(t)
    # nativa -> direccion, para poder ponerle nombre a lo que se encuentre
    nombres = {}
    try:
        sys.path.insert(0, str(RAIZ / 'tools'))
        import nativas_lua
        for nom, v in nativas_lua.tabla().items():
            nombres[v['funcion']] = nom
    except Exception:
        pass

    out = {}
    for m in PATRON.finditer(t):
        largo = int(m.group(2))
        op = int(m.group(4))
        if op == largo:          # esa asignacion era el largo, no el opcode
            continue
        if not (0 < op <= 0x400) or largo < 2:
            continue
        dirc = _duena(funcs, m.start())
        e = out.setdefault(op, {'cuerpos': set(), 'funciones': set(),
                                'nativas': set()})
        e['cuerpos'].add(largo - 2)
        if dirc:
            e['funciones'].add(dirc)
            if dirc in nombres:
                e['nativas'].add(nombres[dirc])
    return out


def nativas_a_opcodes(t=None) -> dict:
    """{nombre de la nativa: [opcodes]} siguiendo UN salto de llamada.

    Hace falta el salto porque las nativas viven entre 0x588000 y 0x59Bxxx,
    que es justo el rango que Angel_unpacked.c NO cubre. Ahi solo hay un
    envoltorio: lee el argumento de Lua y llama a la funcion de verdad, que
    si esta decompilada y es la que arma el paquete. gotojumpmap (0x59ABA0)
    no escribe ningun opcode, llama a 0x673290, y ES ESA la que pone el 337.
    """
    import capstone
    sys.path.insert(0, str(RAIZ / 'tools'))
    import nativas_lua
    from opcodes_de_nativas import Pe

    t = t if t is not None else tabla()
    por_funcion = {}
    for op, v in t.items():
        for f in v['funciones']:
            por_funcion.setdefault(f, set()).add(op)

    exe = nativas_lua._exe()
    if not exe.exists():
        return {}
    b = exe.read_bytes()
    pe = Pe(b)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    res = {}
    for nom, v in nativas_lua.tabla().items():
        fo = pe.off(v['funcion'])
        if fo is None:
            continue
        ops = set()
        for i in md.disasm(b[fo:fo + 900], v['funcion']):
            if i.mnemonic == 'call' and i.op_str.startswith('0x'):
                d = int(i.op_str, 16)
                if d in por_funcion:
                    ops |= por_funcion[d]
            if i.mnemonic == 'ret':
                break
        if ops:
            res[nom] = sorted(ops)
    return res


def main():
    t = tabla()
    if not t:
        print('no esta %s' % FUENTE)
        return
    if '--json' in sys.argv[1:]:
        try:
            enlace = nativas_a_opcodes(t)
        except Exception as e:
            print('sin enlace a nativas (%s: %s)' % (type(e).__name__, e))
            enlace = {}
        for nom, ops in enlace.items():
            for op in ops:
                if op in t:
                    t[op]['nativas'].add(nom)
        d = {'_nota': 'opcodes C->S que arma el cliente. '
                      'Ver tools/opcodes_del_cliente.py.',
             'opcodes': {'0x%04X' % op: {
                 'bytes_de_cuerpo': sorted(v['cuerpos']),
                 'funciones': ['0x%X' % f for f in sorted(v['funciones'])],
                 'nativas': sorted(v['nativas']),
             } for op, v in sorted(t.items())}}
        f = RAIZ / 'server' / 'plantillas' / 'opcodes_cliente.json'
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                     encoding='utf-8')
        print('escrito %s (%d opcodes)' % (f, len(t)))
        return
    filtro = [a for a in sys.argv[1:] if not a.startswith('--')]
    print('%-8s %-14s %s' % ('opcode', 'cuerpo(bytes)', 'nativa / funcion'))
    for op, v in sorted(t.items()):
        quien = ', '.join(sorted(v['nativas'])) or ', '.join(
            '0x%X' % f for f in sorted(v['funciones']))
        if filtro and not any(f.lower() in quien.lower() for f in filtro):
            continue
        print('0x%04X   %-14s %s' % (op, ','.join(str(c) for c in sorted(v['cuerpos'])), quien))
    print('\n%d opcodes' % len(t))


if __name__ == '__main__':
    main()
