"""Que ninguna palabra de comando se quede fuera del filtro.

El cliente SE COME la barra: al escribir "/rama add Life" llega "rama add
Life" pelado. Asi que lo que de verdad decide si un comando existe es la
lista PALABRAS_GM, y si alguien anade un comando a _gm_parsear y se olvida
de la lista, ese comando no llega NUNCA y encima no deja rastro: el paquete
se descarta en silencio. Paso el 05/10/2026 con /rama, /estacion y /rango.
"""
import ast
import pathlib
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))
import app


def _palabras_del_parser():
    """Las cadenas que _gm_parsear compara contra `cmd`, leidas del AST."""
    arbol = ast.parse((RAIZ / 'server' / 'app.py').read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name == '_gm_parsear')
    palabras = set()
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.Compare) or not isinstance(nodo.left, ast.Name):
            continue
        if nodo.left.id != 'cmd':
            continue
        for comp in nodo.comparators:
            if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                palabras.add(comp.value)
            elif isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                for e in comp.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        palabras.add(e.value)
    return palabras


def test_el_parser_tiene_comandos():
    assert len(_palabras_del_parser()) >= 4, _palabras_del_parser()


def test_ninguna_palabra_se_queda_fuera_del_filtro():
    faltan = _palabras_del_parser() - set(app.PALABRAS_GM)
    assert not faltan, 'faltan en PALABRAS_GM: %s' % sorted(faltan)


def test_los_comandos_pasan_sin_barra():
    """Que es como llegan de verdad."""
    for texto in ('rama add Life', 'estacion normal', 'rango 7', 'help'):
        crudo = texto.encode('ascii') + b'\x00'
        assert app._gm_texto(crudo) == texto, texto
        assert app._gm_parsear(texto) is not None, texto


def test_el_chat_normal_no_se_cuela():
    for texto in ('hola que tal', 'vamos a matar bichos', 'gg'):
        assert app._gm_texto(texto.encode('ascii') + b'\x00') is None, texto


def test_la_venta_no_se_confunde_con_un_comando():
    """El 0x0028 nunca puede parecer un /item.

    Los ids de instancia salen correlativos desde 0x030000, asi que uno de
    cada 256 trae el byte 0x69 seguido de un 0x00 -- la cadena "i", que era
    atajo de /item. El husmeo se tragaba el paquete, no se vendia nada y en
    el chat salia "usage: /item <id> [qty]".
    """
    import struct
    for inst in (0x030069, 0x03486B, 0x030000, 0x030069 + 256 * 3):
        cuerpo = struct.pack('<IIII', 1, inst, 0x6AB2232E, 5)
        assert app._gm_texto(cuerpo) is None, hex(inst)


def test_una_letra_suelta_no_es_comando():
    for letra in ('i', 'a', 'gg'):
        assert app._gm_texto(letra.encode('ascii') + b'\x00') is None, letra
        assert app._gm_texto(b'/' + letra.encode('ascii') + b'\x00') is not None, letra


def test_rama_entiende_los_nombres_de_dos_palabras():
    """"Staff Hit" y "Eagle Eye" llevan espacio.

    El parser partia por espacios y cogia partes[1] y partes[2], asi que
    "rama Staff Hit Earth" intentaba cambiar "Staff" por "Hit" y
    "rama Earth" soltaba el cartel de uso aunque fuera correcto.
    """
    casos = {
        'rama Hit Meditate': ('rama', 'Hit', 'Meditate'),
        'rama Staff Hit Earth': ('rama', 'Staff Hit', 'Earth'),
        'rama Eagle Eye Staff Hit': ('rama', 'Eagle Eye', 'Staff Hit'),
        'rama add Eagle Eye': ('rama', 'add', 'Eagle Eye'),
        '/rama 34 4': ('rama', '34', '4'),
    }
    for texto, esperado in casos.items():
        assert app._gm_parsear(texto) == esperado, texto
    for malo in ('rama Earth', 'rama', 'rama vaya cosa'):
        assert app._gm_parsear(malo)[0] == 'err', malo


def test_el_panel_no_deja_filas_en_blanco():
    """Las ramas tienen que caer en filas 0..n-1, sin huecos ni repetidas.

    El cliente (0x646370 + 0x654F90) no dibuja el registro i en la fila i:
    desplaza segun QUE rama sea y segun cuales lleve el personaje. Mandando
    los registros en el orden en que el jugador eligio, dos caian en la
    misma fila y otra se quedaba sin nadie -- la fila en blanco al 100%.
    """
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / 'server'))
    import clases
    a = clases._arbol()
    todos = sorted(a['regs'])
    casos = [
        [9, 12, 13, 15, 16, 33],          # el Swordsman de la captura
        [36, 5, 1, 7, 8, 34],             # Karmav3 con sus seis
        [36, 5, 1, 6, 8, 34, 4],          # Karmav3 con la septima
        [35, 30, 34, 1, 5, 9],            # Avatar y Alchemy juntos
        [1, 4, 5, 6, 8, 34, 36, 20, 30],  # las nueve
    ]
    for ids in casos:
        resto = [i for i in todos if i not in ids]
        _, filas = clases.ordenar_para_el_panel(ids, resto)
        assert sorted(filas) == list(range(len(ids))), (ids, filas)


def test_el_orden_del_swordsman_es_el_de_la_captura():
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / 'server'))
    import clases
    a = clases._arbol()
    ids = [9, 12, 13, 15, 16, 33]
    resto = [i for i in sorted(a['regs']) if i not in ids]
    orden, filas = clases.ordenar_para_el_panel(ids, resto)
    assert orden == [9, 12, 13, 15, 16, 33], orden
    assert filas == [0, 1, 2, 3, 4, 5], filas


def _simular_panel(ids):
    """El bucle entero de 0x646370, con los candados de las filas 7, 8 y 9.

    Devuelve (visible, candado): que rama queda dibujada en cada fila y si
    el candado de las filas de arriba de la sexta quedo puesto. Se mira lo
    que de verdad sale del 0x001C, no lo que creemos que sale.
    """
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / 'server'))
    import clases
    a = clases._arbol()
    todos = sorted(a['regs'])
    cab = len(a['cabecera'])
    c = clases.arbol([(s, 100, 0) for s in ids])[2:]
    regs = [c[cab + i * 14:cab + (i + 1) * 14] for i in range((len(c) - cab) // 14)]
    sids = [r[0] for r in regs[:9]]
    llev = set(ids)
    visible, candado = {}, {}
    for i in range(9):
        sid, orden = regs[i][0], regs[i][13]
        fila = clases._fila_del_cliente(sids, i, llev)
        if fila >= 6:
            candado[fila] = 0 if (sid and orden >= 6) else 1
        if sid and 0 < orden <= 9:
            visible[fila] = sid
        else:
            visible.pop(fila, None)
    return visible, candado


def test_las_nueve_ranuras_se_ven_y_sin_candado():
    """Que no se rompa al desbloquear la octava y la novena.

    Tres cosas: que cada rama acabe dibujada, que ocupen las filas 0..n-1
    sin huecos, y que ninguna fila ocupada de la septima para arriba se
    quede con el candado "Reach Supreme Lv" encima.
    """
    import random
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / 'server'))
    import clases
    todos = sorted(clases._arbol()['regs'])
    random.seed(11)
    casos = [[36, 5, 1, 6, 8, 34, 4],
             [36, 5, 1, 6, 8, 34, 4, 20],
             [36, 5, 1, 6, 8, 34, 4, 20, 30]]
    for n in (6, 7, 8, 9):
        casos += [random.sample(todos, n) for _ in range(300)]
    for ids in casos:
        visible, candado = _simular_panel(ids)
        assert set(visible.values()) == set(ids), (ids, visible)
        assert sorted(visible) == list(range(len(ids))), (ids, sorted(visible))
        for fila in visible:
            if fila >= 6:
                assert candado.get(fila) == 0, (ids, fila, candado)


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK   %s' % nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA %s: %s' % (nombre, e))
    print('fallos:', fallos)
