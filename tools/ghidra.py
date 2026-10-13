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
analiza y corre scripts. VAN EN JAVA Y NO EN PYTHON: los de PyGhidra piden
arrancar Ghidra con su lanzador propio, y los de Java corren tal cual sin
instalar nada.

    python tools/ghidra.py --analizar          una vez, tarda un buen rato
    python tools/ghidra.py --script descompilar.java 0081e900 300

Lo que hay en tools/ghidra_scripts, de mas util a mas especifico:

    descompilar.java            una funcion a C, mas quien la llama
    referencias.java            quien toca una direccion, y si lee o escribe
    saltos_grandes.java         los switch gordos del binario (despachadores)
    registro_de_manejadores.java  tablas que se llenan en ejecucion
    tablas_de_punteros.java     tablas de punteros ya escritas en el fichero
    red_despachador.java        sube desde los socket de WS2_32

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

# Otros binarios que interesa mirar, cada uno en su proyecto para no
# mezclarlos. El de Global es OTRO JUEGO compilado con VS2022: sus
# direcciones no tienen nada que ver con las del de IGG, asi que meterlos en
# el mismo proyecto solo serviria para confundirse.
OTROS = {
    'global': ('AO_GLOBAL',
               pathlib.Path('G:/SteamLibrary/steamapps/common/'
                            'Angels Online Global/angel.dat')),
}
SCRIPTS = RAIZ / 'tools' / 'ghidra_scripts'

HEADLESS = GHIDRA / 'support' / 'analyzeHeadless.bat'


def _correr(args, timeout=None):
    print('$ %s' % ' '.join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], timeout=timeout).returncode


def _cual(nombre):
    """(nombre del proyecto, binario) del que se pida."""
    if not nombre or nombre == 'igg':
        return NOMBRE_PROYECTO, BINARIO
    if nombre not in OTROS:
        raise SystemExit('no se que binario es %r; vale igg o %s'
                         % (nombre, ', '.join(OTROS)))
    return OTROS[nombre]


def analizar(cual=None):
    """Importa el binario y lo analiza entero. Se hace UNA vez."""
    proy, binario = _cual(cual)
    if not binario.exists():
        raise SystemExit('no esta %s' % binario)
    PROYECTO.mkdir(parents=True, exist_ok=True)
    return _correr([HEADLESS, PROYECTO, proy,
                    '-import', binario, '-overwrite',
                    '-analysisTimeoutPerFile', '7200'])


def script(nombre, *extra, cual=None):
    """Corre un script de tools/ghidra_scripts sobre lo ya analizado."""
    proy, binario = _cual(cual)
    ruta = SCRIPTS / nombre
    if not ruta.exists():
        print('no existe %s' % ruta)
        return 2
    return _correr([HEADLESS, PROYECTO, proy,
                    '-process', binario.name, '-noanalysis',
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
    ap.add_argument('--cual', default='igg',
                    help='que binario: igg (por defecto) o %s'
                         % ', '.join(OTROS))
    ap.add_argument('extra', nargs='*')
    a = ap.parse_args()
    if a.comprobar or not (a.analizar or a.script):
        raise SystemExit(0 if comprobar() else 1)
    if a.analizar:
        raise SystemExit(analizar(a.cual))
    raise SystemExit(script(a.script, *a.extra, cual=a.cual))


if __name__ == '__main__':
    main()
