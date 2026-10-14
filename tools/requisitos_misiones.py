"""Que hace falta para que un NPC ofrezca cada mision, sacado de los mapas.

POR QUE. quest.xml no trae ni requisitos ni faccion: solo los pasos. El
compilador de misiones relleno la faccion a ojo, y con eso se equivoco: la
902 "The Return Plan" salio como solo-Beasts cuando la cadena del bosque es
igual para todas las facciones, y como no habia orden, Camp Leader Messi
ofrecia la 905 y la 910 a quien acababa de terminar la 901.

Lo que decide que mision ofrece un NPC y cuando esta en el XML de DIALOGOS
de cada .mpc. El de Messi, en Waterfall Camp, lo dice tal cual:

    si QUEST_FINISH(901) y NO QUEST_FINISH(902) y NO QUEST_RUNNING(902)
        -> la linea que ofrece la 902
    si QUEST_FINISH(904) y NO ... (905)   -> ofrece la 905
    si QUEST_FINISH(908) y NO ... (910)   -> ofrece la 910

(反向="1" es la condicion negada.) Ese patron -- terminada P, y ni terminada
ni en curso Q -- es el de "Q se ofrece a quien termino P", y P es su
requisito. Si el mismo ramal pide ALIGNMENT, esa es la faccion de verdad.

Los ramales con 旗標 "一項成立算成立" (basta una) no se usan: ahi las
condiciones son alternativas y no requisitos.

    python tools/requisitos_misiones.py           escribe la plantilla
    python tools/requisitos_misiones.py --ver 902
"""
import argparse
import collections
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
import mapa_del_cliente as mc

SALIDA = RAIZ / 'server' / 'plantillas' / 'requisitos_misiones.json'

COND_QUEST_FINISH, COND_QUEST_RUNNING, COND_ALIGNMENT, COND_PROPERTY = 11, 13, 12, 3


def _condiciones(tr):
    salida = []
    for c in tr.findall('條件'):
        n = int(c.get('編號') or 0)
        p = [int(x.get('數值') or 0) for x in c.findall('參數')]
        salida.append((n, p, c.get('反向') == '1'))
    return salida


def _dialogos(xml):
    """Los nodos <對話> de un XML de dialogos, aunque el documento entero no
    parsee: se trocea por nodo, que es como lo lee tambien mapa_del_cliente."""
    try:
        return ET.fromstring(xml).iter('對話')
    except ET.ParseError:
        nodos = []
        for trozo in re.findall(r'<對話 .*?</對話>', xml, re.S):
            try:
                nodos.append(ET.fromstring(trozo))
            except ET.ParseError:
                pass
        return nodos


def extraer():
    # Cada ramal es un CAMINO: la 910 se ofrece en Waterfall Camp a quien
    # termino la 908 y en otro mapa a quien termino la 909. Juntandolos en un
    # solo conjunto pediria las dos a la vez; se guardan como alternativas.
    req = collections.defaultdict(lambda: {'caminos': set(), 'faccion': set(),
                                           'nivel': 0, 'mapas': set()})
    for stage, ruta in sorted(mc.mapas_del_cliente().items()):
        try:
            m = mc.Mapa(stage, ruta)
        except Exception:
            continue
        if not m.dialogos_xml:
            continue
        for nodo in _dialogos(m.dialogos_xml):
            for tr in nodo.findall('觸發器'):
                if tr.find('旗標') is not None:
                    continue            # condiciones alternativas, no requisitos
                cs = _condiciones(tr)
                negadas_fin = {p[0] for n, p, neg in cs if n == COND_QUEST_FINISH and neg and p}
                negadas_run = {p[0] for n, p, neg in cs if n == COND_QUEST_RUNNING and neg and p}
                for q in negadas_fin & negadas_run:   # "Q aun no la tiene"
                    r = req[q]
                    r['mapas'].add(stage)
                    camino = frozenset(p[0] for n, p, neg in cs
                                       if n == COND_QUEST_FINISH and not neg and p and p[0] != q)
                    r['caminos'].add(camino)
                    for n, p, neg in cs:
                        if neg or not p:
                            continue
                        if n == COND_ALIGNMENT:
                            r['faccion'].add(p[0])
                        elif n == COND_PROPERTY and len(p) > 2 and p[0] == 29:
                            r['nivel'] = max(r['nivel'], p[2])
    return req


def escribir():
    """Junta las dos fuentes. Los MAPAS mandan: dicen el requisito y si la
    oferta pide faccion. El RELEVO solo rellena donde los mapas callan, y
    nunca dice nada de faccion."""
    mapas = extraer()
    relevo = por_relevo()
    misiones = {}
    for q, r in mapas.items():
        misiones[str(q)] = {
            'caminos': sorted(sorted(c) for c in r['caminos']),
            'faccion': sorted(r['faccion']),
            # FACCION LIBRE solo si es CONTINUACION de una cadena (pide una
            # previa) y el dialogo no pide faccion: la hace quien hizo la
            # anterior, diga lo que diga la faccion que puso el compilador.
            # Asi la 902, que salio solo-Beasts. Las puertas de entrada sin
            # previa -- como la 127, el registro en Aurora -- se quedan con
            # la suya: alli la faccion no la decide el dialogo, y quitarsela
            # se la ofrecia a uno de Shadow.
            'faccion_libre': (not r['faccion']
                              and any(len(c) > 0 for c in r['caminos'])),
            'nivel': r['nivel'],
            'fuente': 'mapas %s' % sorted(r['mapas'])}
    for q, previa in relevo.items():
        if str(q) in misiones:
            continue
        misiones[str(q)] = {'caminos': [[previa]], 'faccion': [],
                            'faccion_libre': False, 'nivel': 0,
                            'fuente': 'relevo'}
    datos = {'comentario': ('Generado por tools/requisitos_misiones.py desde '
                            'los dialogos de los .mpc y quest.xml. No editar '
                            'a mano.'),
             'misiones': dict(sorted(misiones.items(), key=lambda kv: int(kv[0])))}
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding='utf-8')
    print('%s: %d misiones con requisito (%d de los mapas, %d por relevo)'
          % (SALIDA.name, len(misiones), len(mapas), len(misiones) - len(mapas)))
    return datos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ver', type=int)
    a = ap.parse_args()
    if a.ver:
        r = extraer().get(a.ver)
        print(a.ver, r and {k: sorted(v) if isinstance(v, set) else v for k, v in r.items()})
        return
    escribir()



# ---------------------------------------------------------------------------
# EL RELEVO. Para las misiones que no tienen la oferta en los dialogos de los
# mapas -- la cadena del desierto, 852..861, no sale en ninguno --, quest.xml
# deja ver la cadena de otra forma: ids seguidos, del mismo tipo, y el NPC que
# DA la siguiente es el que nombra el ultimo paso de la anterior. La 855
# termina "entrega a Lord Adrian al Evil Collector" y la 856 la da el Evil
# Collector; la 902 termina "habla con Leader Alonso" y la 903 la da Alonso.
#
# Se usa solo donde los mapas no dicen nada, y antes se mide contra los que
# si lo dicen (validar_relevo).
def _norm(n):
    n = (n or '').strip().lower()
    n = re.sub(r'^(?:level|lvl)\s*\d+\s*[-:]\s*', '', n).strip()
    return n[:16].strip()


def por_relevo():
    import sqlite3
    c = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    cols = [r[1] for r in c.execute('pragma table_info(quest)')]
    filas = {}
    for r in c.execute('select * from quest'):
        d = dict(zip(cols, r))
        if str(d['id']).isdigit():
            filas[int(d['id'])] = d
    salida = {}
    for q, d in filas.items():
        prev = filas.get(q - 1)
        if not prev or prev.get('任務類型') != d.get('任務類型'):
            continue
        quien = _norm(d.get('承接'))
        if len(quien) < 3:
            continue
        # el ultimo paso de la anterior: su NPC y su texto
        ultimo = max((k for k in range(1, 9) if prev.get('步驟%02d' % k)), default=0)
        if not ultimo:
            continue
        npc_ult = _norm(prev.get('承接%02d' % ultimo))
        txt_ult = (prev.get('步驟%02d' % ultimo) or '').lower()
        if quien == npc_ult or quien in txt_ult:
            salida[q] = q - 1
    return salida


def validar_relevo():
    """Cuanto acierta el relevo donde los mapas dan la respuesta buena."""
    mapas = extraer()
    relevo = por_relevo()
    ok = mal = sin = 0
    fallos = []
    for q, r in mapas.items():
        verdad = {p for cam in r['caminos'] for p in cam}
        if not verdad:
            continue
        if q not in relevo:
            sin += 1
        elif relevo[q] in verdad:
            ok += 1
        else:
            mal += 1
            fallos.append((q, relevo[q], sorted(verdad)))
    print('relevo contra los mapas: %d aciertos, %d errores, %d sin prediccion'
          % (ok, mal, sin))
    for f in fallos[:10]:
        print('   fallo: mision %d, relevo dice %d, mapas dicen %s' % f)
    return ok, mal, sin


if __name__ == '__main__':
    main()
