"""El diccionario de acciones y condiciones de los eventos del cliente.

POR QUE EXISTE. Los mapas .mpc traen la logica de misiones e instancias
entera, pero con los codigos en crudo, y hasta ahora solo habia tres
descifrados a mano -- 3 cambiar mapa, 25 abrir dialogo, 53 ir a tag --
porque la lista de setting/eventdef.xml no casaba por posicion. Y no casa:
esa lista es el orden del EDITOR de mapas. Los numeros de verdad estan en el
mismo fichero, mas abajo, en el bloque DEFINE:

    <DEFINE EVENT_ACT_CHANGE_MAP="3"/>
    <DEFINE EVENT_ACT_BEGIN_MESSAGE="25"/>
    <DEFINE EVENT_ACT_GOTO_TAG="53"/>
    <DEFINE EVENT_COND_GENERATOR_ALIVE="14"/>
    <DEFINE EVENT_COND_PARA_ENTER="22"/>

Las cinco salen clavadas contra lo que ya estaba medido, asi que el bloque
DEFINE es la fuente buena. Y no hay que elegir version: el eventdef aparece
en 7 de los 27 paks y entre ellos no hay UN SOLO choque de numero, solo
nombres nuevos que se van anadiendo, asi que vale el mas completo.

SEGUNDA COMPROBACION, independiente de los mapas. setting/event.xml trae los
dialogos globales con sus acciones, y leidos con este diccionario cuentan algo
coherente: el dialogo 1 hace SET_STEP(107, 0) y el 8 SET_STEP(107, 3) -- la
misma mision, dos pasos; el 3 hace SELECT_QUEST_REWARD con pares de objeto y
cantidad; el 5 y el 6 hacen ADD_PROPERTY(29, +1) y ADD_PROPERTY(29, -1), que
es una eleccion que sube o baja un atributo. Si la numeracion estuviera
desplazada, nada de eso encajaria.

LO QUE FALTA POR NOMBRE. De lo que los 399 mapas usan de verdad quedan sin
nombre cinco acciones (0, 107, 111, 112, 117) y dos condiciones (0 y 72).
Son anadidos posteriores al eventdef mas nuevo que trae el cliente y suman
57 usos de 15.842, asi que no bloquean nada.

    python tools/eventos_del_cliente.py            el diccionario y el uso real
"""
import collections
import glob
import os
import re
import struct
import pathlib
import xml.etree.ElementTree as ET

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAKS = RAIZ / 'extracted_paks'

PRE_ACC = 'EVENT_ACT_'
PRE_CON = 'EVENT_COND_'

# Las cinco que ya estaban medidas por otro camino. Si alguna dejara de
# casar, el diccionario que se este leyendo no es el bueno.
ANCLAS = {PRE_ACC + 'CHANGE_MAP': 3,
          PRE_ACC + 'BEGIN_MESSAGE': 25,
          PRE_ACC + 'GOTO_TAG': 53,
          PRE_CON + 'GENERATOR_ALIVE': 14,
          PRE_CON + 'PARA_ENTER': 22}


def _defines(ruta):
    txt = pathlib.Path(ruta).read_text(encoding='utf-8-sig', errors='replace')
    return {n: int(v) for n, v in
            re.findall(r'<DEFINE\s+(\w+)="(\d+)"\s*/>', txt)}


def diccionario():
    """(acciones, condiciones) numero -> nombre corto, ya sin el prefijo.

    Junta los DEFINE de todos los paks y revienta si dos se contradicen,
    porque entonces la numeracion dependeria de la version y nada de lo que
    hay montado encima valdria.
    """
    junto, de_donde = {}, {}
    for ruta in sorted(glob.glob(str(PAKS / '*' / 'setting' / 'eventdef.xml'))):
        for nombre, valor in _defines(ruta).items():
            if junto.get(nombre, valor) != valor:
                raise ValueError(
                    '%s vale %d en %s y %d en %s'
                    % (nombre, junto[nombre], de_donde[nombre], valor, ruta))
            junto[nombre] = valor
            de_donde.setdefault(nombre, ruta)
    for nombre, valor in ANCLAS.items():
        if junto.get(nombre) != valor:
            raise ValueError('el ancla %s deberia ser %d y sale %r'
                             % (nombre, valor, junto.get(nombre)))
    acc = {v: k[len(PRE_ACC):] for k, v in junto.items() if k.startswith(PRE_ACC)}
    con = {v: k[len(PRE_CON):] for k, v in junto.items() if k.startswith(PRE_CON)}
    return acc, con


def disparadores_del_mapa(ruta):
    """Los disparadores de un .mpc, con sus condiciones, que es lo que el
    lector de mapas tira por el camino.

    Devuelve dicts con el numero de evento, el modo de disparo (觸發: 1
    pisar, 2 pulsar, 3 chocar, 4 muerte en grupo, 11 muerte individual...),
    cuantas veces se puede, y las listas de condiciones y acciones ya como
    (numero, parametros).
    """
    b = pathlib.Path(ruta).read_bytes()
    if b[:4] != b'MAP\0':
        raise ValueError('%s no empieza por MAP\0' % ruta)
    cab = struct.unpack_from('<24I', b, 12)
    off, largo = cab[5], cab[6]
    if largo <= 4:
        return []
    n = struct.unpack_from('<I', b, off)[0]
    txt = b[off + 4:off + 4 + n].decode('utf-8', 'replace')
    try:
        raiz = ET.fromstring(txt)
    except ET.ParseError:
        return []
    salida = []
    for ev in raiz.findall('事件'):
        num = int(ev.get('編號') or 0)
        for tr in ev.findall('觸發器'):
            salida.append({
                'evento': num,
                'disparo': int(tr.get('觸發') or 0),
                'veces': int(tr.get('次數') or 0),
                'condiciones': [_cod(c) for c in tr.findall('條件')],
                # 反向="1": la condicion va NEGADA ("si NO llevas la mision").
                # Se perdia al extraer y el interprete evaluaba al reves las
                # 566 condiciones negadas de los mapas.
                'negadas': [c.get('反向') == '1' for c in tr.findall('條件')],
                # <旗標 一項成立算成立=""/>: "si una se cumple, se cumple" --
                # las condiciones van con O, no con Y. Se perdia y el permiso
                # del Training Palace (mision 123 terminada O en curso) no se
                # cumplia nunca.
                'basta_una': any(f.get('一項成立算成立') is not None
                                 for f in tr.findall('旗標')),
                'acciones': [_cod(a) for a in tr.findall('動作')]})
    return salida


def _cod(n):
    return (int(n.get('編號') or 0),
            tuple(int(p.get('數值') or 0) for p in n.findall('參數')))


def uso_real():
    """Cuanto se usa cada accion y cada condicion en los 399 mapas.

    Es lo que dice donde esta el trabajo: de las 103 acciones del
    diccionario solo 48 aparecen, y las doce primeras se comen la mayoria.
    """
    import mapa_del_cliente as mc
    acc, con = collections.Counter(), collections.Counter()
    macc = collections.defaultdict(set)
    mcon = collections.defaultdict(set)
    for stage, ruta in sorted(mc.mapas_del_cliente().items()):
        for d in disparadores_del_mapa(ruta):
            for n, _p in d['acciones']:
                acc[n] += 1
                macc[n].add(stage)
            for n, _p in d['condiciones']:
                con[n] += 1
                mcon[n].add(stage)
    return acc, con, macc, mcon


def validar():
    acciones, condiciones = diccionario()
    print('diccionario: %d acciones, %d condiciones, anclas correctas'
          % (len(acciones), len(condiciones)))
    acc, con, macc, mcon = uso_real()
    for titulo, cuenta, nombres, mapas in (
            ('ACCIONES', acc, acciones, macc),
            ('CONDICIONES', con, condiciones, mcon)):
        total = sum(cuenta.values())
        print('\n== %s usadas: %d distintas, %d usos' % (titulo, len(cuenta), total))
        acumulado = 0
        for i, (n, veces) in enumerate(cuenta.most_common()):
            acumulado += veces
            print('   %5d %-28s %6d usos  %4d mapas   acumulado %5.1f%%'
                  % (n, nombres.get(n, '??? SIN NOMBRE'), veces,
                     len(mapas[n]), 100.0 * acumulado / total))
        sin = [n for n in cuenta if n not in nombres]
        print('   sin nombre: %s (%d usos de %d)'
              % (sorted(sin), sum(cuenta[n] for n in sin), total))
    return True


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(RAIZ / 'tools'))
    raise SystemExit(0 if validar() else 1)
