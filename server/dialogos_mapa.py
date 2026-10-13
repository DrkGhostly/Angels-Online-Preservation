"""Los arboles de dialogo de los mapas: que dice cada NPC segun la mision.

Lo genera tools/propagar_dialogos_mapa.py en plantillas/dialogos_mapa.json. Aqui se recorre: se busca el nodo raiz del NPC
por su RETRATO, se elige la rama cuyas condiciones cumple el personaje -- con
el mismo evaluador que los eventos, que ya sabe pasar los pasos de mision de
la numeracion del servidor a la del cliente --, y se devuelve la cadena de
mensajes que toca.

POR QUE. Para los recordatorios de mision el servidor adivinaba la linea
dentro del bloque de mensajes de la mision, y en la 1590 le salia a Bella
Bulu la frase de Matia mandandote a buscarla (159013). El arbol de Clink
Harbor dice cual es: con la mision en el paso 3, el nodo 1000011, mensaje
159031, "consigue 20 Microcoins de los Transport Workers y daselos a Meow".

DE MOMENTO SOLO SE USA PARA LINEAS QUE NO HACEN NADA. Si el camino elegido
lleva acciones (dar objetos, cambiar de paso...), se devuelve None y sigue
mandando misiones.py, que es quien lleva el avance: ejecutar tambien las del
arbol avanzaria la mision dos veces.
"""
import json
import logging
import pathlib

import eventos as ev

log = logging.getLogger(__name__)

RUTA = pathlib.Path(__file__).parent / 'plantillas' / 'dialogos_mapa.json'
MAX_LINEAS = 8

_TODO = None


def _arbol(stage):
    global _TODO
    if _TODO is None:
        try:
            _TODO = json.loads(RUTA.read_text(encoding='utf-8'))
        except Exception:
            _TODO = {}
    return _TODO.get(str(int(stage)), {})


def _raices(arbol):
    """Los nodos a los que no lleva ningun otro: los de entrada de cada NPC."""
    destinos = set()
    for n in arbol.values():
        if n.get('s'):
            destinos.add(n['s'])
        for _m, s in n.get('o', ()):
            destinos.add(s)
        for r in n.get('r', ()):
            destinos.add(r.get('ir'))
    return [k for k in arbol if int(k) not in destinos]


def raiz_del_npc(stage, retrato):
    """El nodo de entrada del NPC con ese retrato, o None.

    Solo cuenta si hay uno y con ramas: dos raices con el mismo retrato no
    se pueden distinguir y entonces no se arriesga.
    """
    arbol = _arbol(stage)
    if not arbol or not retrato:
        return None
    cands = [k for k in _raices(arbol)
             if arbol[k].get('c') == int(retrato) and arbol[k].get('r')]
    return cands[0] if len(cands) == 1 else None


def _cumple(rama, ctx):
    resultados = []
    for n, p, negada in rama.get('si', ()):
        r = ev.evaluar(n, p, ctx)
        if r is None:
            return False              # no se sabe: no se arriesga
        resultados.append((not r) if negada else bool(r))
    if not resultados:
        return False
    return any(resultados) if rama.get('o') else all(resultados)


def _elegir(arbol, k, ctx, profundidad=0):
    """Baja por las ramas hasta un nodo sin ramas que cumplir."""
    n = arbol.get(str(k))
    if n is None or profundidad > 6:
        return None
    for rama in n.get('r', ()):
        if _cumple(rama, ctx):
            return _elegir(arbol, rama['ir'], ctx, profundidad + 1)
    return str(k)


def lineas_sin_accion(stage, retrato, ctx):
    """(retrato, [mensajes]) de lo que el NPC dice ahora, o None.

    None si el NPC no tiene arbol, si no se reconoce su raiz, si la rama
    elegida es la de entrada (no depende de la mision) o si por el camino hay
    alguna accion o alguna pregunta con opciones.
    """
    arbol = _arbol(stage)
    raiz = raiz_del_npc(stage, retrato)
    if raiz is None:
        return None
    k = _elegir(arbol, raiz, ctx)
    if k is None or k == raiz:
        return None
    mensajes = []
    cara = None
    visto = set()
    while k and k not in visto and len(mensajes) < MAX_LINEAS:
        visto.add(k)
        n = arbol.get(str(k))
        if n is None:
            break
        if n.get('a') or n.get('o') or n.get('r'):
            return None               # hace algo o pregunta: no es solo texto
        if n.get('m'):
            mensajes.append(n['m'])
            cara = cara or n.get('c')
        k = str(n['s']) if n.get('s') else None
    if not mensajes:
        return None
    return (cara or int(retrato), mensajes)


def lineas_del_nodo(stage, nodo, ctx=None):
    """(retrato, [mensajes]) a partir de un nodo concreto: el que abre un
    evento con BEGIN_MESSAGE (la estatua del mono de la 262 abre el 26201).

    Si el nodo ramifica, se elige la rama con el estado del personaje. Se
    sigue la cadena de "siguiente" y se para en el primer nodo con opciones
    -- su texto se muestra, sus opciones todavia no se atienden -- o con
    acciones, que ya las ha ejecutado el evento que abrio el dialogo.
    """
    arbol = _arbol(stage)
    k = str(int(nodo))
    if k not in arbol:
        return None
    if ctx is not None and arbol[k].get('r'):
        k = _elegir(arbol, k, ctx) or k
    mensajes, cara, visto = [], None, set()
    while k and k not in visto and len(mensajes) < MAX_LINEAS:
        visto.add(k)
        n = arbol.get(str(k))
        if n is None:
            break
        if n.get('m'):
            mensajes.append(n['m'])
            cara = cara or n.get('c')
        if n.get('o') or n.get('r'):
            break
        k = str(n['s']) if n.get('s') else None
    return (cara, mensajes) if mensajes else None
