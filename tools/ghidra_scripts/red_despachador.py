# Encuentra la capa de red del cliente y, desde ella, el despachador S->C.
#
# ESTO ES LO QUE EL FICHERO PLANO NO PUEDE HACER. Angel_unpacked.c no tiene
# referencias cruzadas, asi que para encontrar el despachador solo queda
# adivinar por la forma -- "la funcion con mas casos que parezcan opcodes" --
# y eso ya dio un falso positivo: salio SQLite, cuya maquina virtual tiene
# unos 170 opcodes.
#
# Aqui se va al reves y sin adivinar: se parte de las funciones de socket que
# el cliente IMPORTA de WS2_32 y se sube por quien las llama. El que reciba
# los bytes y los reparta tiene que estar en ese arbol.
#
# @category AO
# @runtime PyGhidra
import collections

OBJETIVOS = ('recv', 'WSARecv', 'recvfrom', 'WSARecvFrom', 'ReadFile')
NIVELES = 4


def nombre(f):
    return f.getName() if f is not None else '?'


def llamantes(fm, f):
    out = set()
    for ref in getReferencesTo(f.getEntryPoint()):
        g = fm.getFunctionContaining(ref.getFromAddress())
        if g is not None:
            out.add(g)
    return out


def casos_switch(f):
    """Cuantos destinos distintos tiene la tabla de saltos de esa funcion.

    Un despachador de paquetes reparte a muchos sitios desde un salto
    calculado; una funcion normal, no.
    """
    destinos = set()
    cuerpo = f.getBody()
    inst = currentProgram.getListing().getInstructions(cuerpo, True)
    for i in inst:
        fl = i.getFlowType()
        if fl is not None and fl.isComputed() and fl.isJump():
            for d in i.getFlows():
                destinos.add(d)
    return len(destinos)


def main():
    fm = currentProgram.getFunctionManager()
    # 1. las funciones importadas que nos interesan
    semillas = []
    for f in fm.getExternalFunctions():
        if f.getName() in OBJETIVOS:
            semillas.append(f)
    # los thunks locales tambien valen
    for f in fm.getFunctions(True):
        if f.getName() in OBJETIVOS:
            semillas.append(f)
    print('== funciones de socket encontradas: %d' % len(semillas))
    for f in semillas:
        print('   %-14s %s' % (nombre(f), f.getEntryPoint()))
    if not semillas:
        print('   ninguna: el cliente quiza use otra biblioteca')
        return

    # 2. subir por quien las llama, nivel a nivel
    vistos = set(semillas)
    frente = set(semillas)
    por_nivel = {}
    for n in range(1, NIVELES + 1):
        nuevo = set()
        for f in frente:
            for g in llamantes(fm, f):
                if g not in vistos:
                    nuevo.add(g)
        vistos |= nuevo
        por_nivel[n] = nuevo
        frente = nuevo
        print('== nivel %d: %d funciones que llaman' % (n, len(nuevo)))
        if not nuevo:
            break

    # 3. de todas ellas, las que reparten a muchos sitios
    candidatos = []
    for n, conj in por_nivel.items():
        for f in conj:
            c = casos_switch(f)
            if c >= 20:
                candidatos.append((c, n, f))
    candidatos.sort(reverse=True)
    print()
    print('== candidatos a DESPACHADOR (saltos calculados con muchos destinos)')
    if not candidatos:
        print('   ninguno con 20+ destinos; subir NIVELES o bajar el umbral')
    for c, n, f in candidatos[:12]:
        print('   %-10s %-34s %4d destinos   a %d saltos del socket'
              % (f.getEntryPoint(), nombre(f), c, n))


main()
