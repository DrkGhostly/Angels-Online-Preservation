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
