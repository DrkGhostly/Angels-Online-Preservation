"""Correr Ghidra sobre el cliente sin abrir la interfaz.

POR QUE HACE FALTA. Hasta ahora lo unico que habia del binario era
Angel_unpacked.c, 17 MB de C descompilado con 21.179 funciones. Sirve para
buscar patrones -- de ahi salieron los 108 opcodes C->S, con el emisor
0x81D190 y el reservador 0x4C0EC0 -- pero es un volcado PLANO: no tiene
referencias cruzadas. Y sin ellas se cae en espejismos.

Pasó uno nada mas empezar, y conviene dejarlo escrito: buscando el
despachador de paquetes S->C por "la funcion cuyo switch tenga mas casos que
coincidan con opcodes conocidos", la ganadora fue sub_0042EE80, con LOS 25
opcodes conocidos entre sus 171 casos. Parecia definitivo. Era SQLite: su
maquina virtual tiene unos 170 opcodes y el cuerpo lleva dentro la cadena
"cannot commit transaction - SQL statements in progress". Con referencias
cruzadas eso no pasa, porque se puede preguntar QUIEN LLAMA a la funcion de
recibir del socket en vez de adivinar por la forma.

EL BINARIO BUENO ES G:/Angel.exe. No es ninguno de los que hay sueltos en la
carpeta del cliente:

    START.EXE    el lanzador: .text de 422 KB, sin empaquetar
    loader17.exe el cargador: .text de 153 KB
    angel.dat    EL JUEGO, pero empaquetado con UPX (UPX0 declara 5,7 MB)
    ANGLE.DAT    otro UPX, mas viejo
    G:/Angel.exe el juego YA DESEMPAQUETADO: 5,6 MB, .text de 4,9 MB
                 en 0x401000..0x8B2FFF

Que el bueno es el ultimo lo confirman las direcciones que el proyecto ya
tiene anotadas de antes -- sub_81E900 (el lector de tramas), sub_5EB130 (la
ficha) y 0x56e110 -- que caen todas dentro de ese .text.

MONTAJE. Ghidra 12.1.4 en G:/ghidra y un JDK 64 bits (vale el 25 de
Temurin). No hace falta interfaz ni ningun MCP: analyzeHeadless importa,
analiza y corre scripts de PyGhidra (Python 3).

    python tools/ghidra.py --analizar          una vez, tarda un buen rato
    python tools/ghidra.py --script red_despachador.py

El proyecto queda en G:/ghidra_proj y se reaprovecha entre sesiones: el
analisis solo se hace una vez.
"""
import argparse
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
GHIDRA = pathlib.Path('G:/ghidra')
PROYECTO = pathlib.Path('G:/ghidra_proj')
NOMBRE_PROYECTO = 'AO'
BINARIO = pathlib.Path('G:/Angel.exe')
SCRIPTS = RAIZ / 'tools' / 'ghidra_scripts'

HEADLESS = GHIDRA / 'support' / 'analyzeHeadless.bat'


def _correr(args, timeout=None):
    print('$ %s' % ' '.join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], timeout=timeout).returncode


def analizar():
    """Importa el binario y lo analiza entero. Se hace UNA vez."""
    PROYECTO.mkdir(parents=True, exist_ok=True)
    return _correr([HEADLESS, PROYECTO, NOMBRE_PROYECTO,
                    '-import', BINARIO, '-overwrite',
                    '-analysisTimeoutPerFile', '7200'])


def script(nombre, *extra):
    """Corre un script de tools/ghidra_scripts sobre lo ya analizado."""
    ruta = SCRIPTS / nombre
    if not ruta.exists():
        print('no existe %s' % ruta)
        return 2
    return _correr([HEADLESS, PROYECTO, NOMBRE_PROYECTO,
                    '-process', BINARIO.name, '-noanalysis',
                    '-scriptPath', SCRIPTS,
                    '-postScript', nombre, *extra])


def comprobar():
    """Que esta y que falta, antes de perder el tiempo."""
    ok = True
    for que, ruta in (('Ghidra', GHIDRA), ('analyzeHeadless', HEADLESS),
                      ('el binario desempaquetado', BINARIO)):
        hay = ruta.exists()
        ok &= hay
        print('   %-26s %s  %s' % (que, 'si' if hay else 'NO', ruta))
    print('   %-26s %s  %s' % ('proyecto analizado',
                               'si' if (PROYECTO / (NOMBRE_PROYECTO + '.rep')).exists()
                               else 'no', PROYECTO))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--comprobar', action='store_true')
    ap.add_argument('--analizar', action='store_true')
    ap.add_argument('--script')
    ap.add_argument('extra', nargs='*')
    a = ap.parse_args()
    if a.comprobar or not (a.analizar or a.script):
        raise SystemExit(0 if comprobar() else 1)
    if a.analizar:
        raise SystemExit(analizar())
    raise SystemExit(script(a.script, *a.extra))


if __name__ == '__main__':
    main()
