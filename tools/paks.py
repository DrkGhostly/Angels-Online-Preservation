"""Cual es el pak VIGENTE de cada archivo del cliente.

Los paks se aplican en cascada: el de numero mas alto que traiga un archivo
es el que ve el jugador. Ordenarlos por nombre NO vale, y cuesta caro:

    sorted(['UPDATE8','UPDATE10','update','update26'])
      -> ['UPDATE10', 'UPDATE8', 'update', 'update26']

Con eso, 'update' (el primero de todos) queda despues de 'UPDATE26', y se
acaba leyendo datos de hace diez anos. Nos paso dos veces el mismo dia:
primero con la linea de Fortunia -- que solo esta en UPDATE8 y quedo tapada
por UPDATE10 -- y despues con card.xml, quest.xml y treasuremap.xml.

Y ojo con algo peor: el MISMO id puede decir cosas distintas segun el pak.
El 504131 es un NPC del Huevo en UPDATE6, Fortunia en UPDATE8 y Pasqua de
UPDATE9 en adelante. Asi que no vale juntar los archivos en un diccionario:
hay que leer el vigente.
"""
import glob
import pathlib
import re

RAIZ = pathlib.Path(__file__).parent.parent


def pak_de(p) -> str:
    """El nombre del pak de esa ruta: el componente tras extracted_paks."""
    partes = pathlib.Path(p).parts
    for i, x in enumerate(partes):
        if x.lower() == 'extracted_paks' and i + 1 < len(partes):
            return partes[i + 1]
    return ''


def numero(p) -> int:
    """El orden real de un pak: data1 < update < update2 < ... < update26."""
    n = pak_de(p).lower()
    if n == 'data1':
        return -1
    if n == 'update':
        return 0
    m = re.search(r'(\d+)$', n)
    return int(m.group(1)) if m else 0


def versiones(nombre: str) -> list:
    """Todos los paks que traen ese archivo, del mas viejo al mas nuevo."""
    fs = (glob.glob(str(RAIZ / 'extracted_paks' / '*' / 'setting' / 'eng' / nombre))
          + glob.glob(str(RAIZ / 'extracted_paks' / '*' / 'setting' / nombre)))
    return sorted(fs, key=numero)


def vigente(nombre: str):
    """El pak que de verdad ve el jugador, o None."""
    fs = versiones(nombre)
    return pathlib.Path(fs[-1]) if fs else None


def texto(nombre: str) -> str:
    """El contenido del archivo vigente, ya descodificado."""
    f = vigente(nombre)
    if f is None:
        return ''
    if f.suffix.lower() == '.obd':
        return f.read_bytes().decode('big5', errors='ignore')
    return f.read_text(encoding='utf-8-sig', errors='ignore')


if __name__ == '__main__':
    import sys
    for n in (sys.argv[1:] or ['achievement.xml', 'card.xml', 'quest.xml',
                               'treasuremap.xml', 'star_client.xml',
                               'collection.xml', 'msg.xml', 'npc.xml']):
        f = vigente(n)
        vs = [pak_de(x) for x in versiones(n)]
        print('%-18s vigente: %-10s (en %d paks: %s%s)'
              % (n, pak_de(f) if f else 'NO ESTA', len(vs),
                 ', '.join(vs[:4]), '...' if len(vs) > 4 else ''))
