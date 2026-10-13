"""Elige que angel.dat arranca el launcher, sin perder el otro.

POR QUE. El launcher de Global ya corre con nuestro cliente (ver
docs/launcher_global.md), pero lanza siempre el fichero que se llame
`angel.dat` en la carpeta del juego: en el binario la ruta es `./%s` y el
nombre sale de ahi. Asi que para cambiar de cliente no hay que tocar el
launcher, hay que cambiar ese fichero de sitio -- y eso, hecho a mano, es
como se pierde el bueno.

Aqui se guardan los dos con nombre propio y se copia el elegido encima de
`angel.dat`. La primera vez que se corre, el `angel.dat` que haya se guarda
como `angel_igg.dat` si todavia no existe, que es lo que hay hoy.

    python tools/elegir_cliente.py                  dice cual esta puesto
    python tools/elegir_cliente.py --poner igg      el de IGG
    python tools/elegir_cliente.py --poner global   el de Global
    python tools/elegir_cliente.py --traer-global   copia el de Global

AVISO SOBRE EL DE GLOBAL. No vale solo con copiarlo, y conviene saberlo
antes de perder una tarde:

  * importa `steam_api.dll` de forma estatica, asi que sin esa DLL al lado
    el proceso NI ARRANCA, y aun con ella puede negarse si SteamAPI_Init
    falla;
  * es un binario distinto -- VS2022, Direct3D 11 -- asi que las direcciones
    que tiene anotadas el proyecto (el transporte, los 203 manejadores de
    docs/tabla_s2c.md) NO valen para el;
  * y sus .pak son otros: Global trae data1/2/3 + update/update2, y aqui hay
    data1 + update..update26. Un cliente leyendo los .pak del otro no es una
    mezcla que se pueda dar por buena sin probarla.

Lo unico que hay a favor, de momento: la constante 0x1357 de la cabecera de
trama aparece en los dos binarios, asi que el formato de red parece de la
misma familia. Es una señal, no una prueba.
"""
import argparse
import hashlib
import pathlib
import shutil
import sys

CARPETA = pathlib.Path('C:/AO/Angels Online')
GLOBAL = pathlib.Path('G:/SteamLibrary/steamapps/common/Angels Online Global')

ACTIVO = CARPETA / 'angel.dat'
COPIAS = {'igg': CARPETA / 'angel_igg.dat',
          'global': CARPETA / 'angel_global.dat'}


def _huella(ruta):
    if not ruta.exists():
        return None
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for trozo in iter(lambda: f.read(1 << 20), b''):
            h.update(trozo)
    return h.hexdigest()


def _guardar_el_de_ahora():
    """La primera vez, el angel.dat que hay se queda como el de IGG."""
    if ACTIVO.exists() and not COPIAS['igg'].exists():
        shutil.copy2(ACTIVO, COPIAS['igg'])
        print('guardado el que habia como %s' % COPIAS['igg'].name)


def traer_global():
    origen = GLOBAL / 'angel.dat'
    if not origen.exists():
        print('no esta %s' % origen)
        return False
    shutil.copy2(origen, COPIAS['global'])
    # Sin esta DLL el proceso no llega ni a main: la importa estaticamente.
    dll = GLOBAL / 'steam_api.dll'
    if dll.exists() and not (CARPETA / dll.name).exists():
        shutil.copy2(dll, CARPETA / dll.name)
        print('copiada %s, que el de Global importa de forma estatica' % dll.name)
    print('copiado %s -> %s' % (origen, COPIAS['global']))
    return True


def poner(cual):
    _guardar_el_de_ahora()
    origen = COPIAS.get(cual)
    if origen is None:
        print('no se que es %r; vale igg o global' % cual)
        return False
    if not origen.exists():
        print('falta %s' % origen)
        if cual == 'global':
            print('   corre antes:  python tools/elegir_cliente.py --traer-global')
        return False
    shutil.copy2(origen, ACTIVO)
    print('puesto el cliente de %s (%d KB)' % (cual, ACTIVO.stat().st_size // 1024))
    if cual == 'global':
        print('   ojo: lee el aviso de la cabecera de este fichero')
    return True


def estado():
    _guardar_el_de_ahora()
    ahora = _huella(ACTIVO)
    print('carpeta: %s' % CARPETA)
    if ahora is None:
        print('   NO HAY angel.dat')
        return False
    cual = 'desconocido (ni el de IGG ni el de Global que hay guardados)'
    for nombre, ruta in COPIAS.items():
        if _huella(ruta) == ahora:
            cual = nombre
            break
    print('   angel.dat    %8d KB   -> %s' % (ACTIVO.stat().st_size // 1024, cual))
    for nombre, ruta in COPIAS.items():
        if ruta.exists():
            print('   %-12s %8d KB' % (ruta.name, ruta.stat().st_size // 1024))
        else:
            print('   %-12s (no esta)' % ruta.name)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--poner', choices=sorted(COPIAS))
    ap.add_argument('--traer-global', action='store_true')
    a = ap.parse_args()
    if a.traer_global:
        raise SystemExit(0 if traer_global() else 1)
    if a.poner:
        raise SystemExit(0 if poner(a.poner) else 1)
    raise SystemExit(0 if estado() else 1)


if __name__ == '__main__':
    main()
