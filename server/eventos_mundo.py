"""Enchufa el interprete de eventos al mundo: estado del mapa y contexto.

QUE HACE FALTA PARA EJECUTAR UN EVENTO. server/eventos.py sabe leer la logica
pero no sabe nada del mundo: pregunta por un Contexto y devuelve efectos.
Aqui esta la mitad que mira: de donde sale cada respuesta y donde se apunta
lo que el mapa va cambiando.

LO QUE MAS CUESTA ES GENERATOR_ALIVE, y es justo el que abre las instancias.
En los mapas la mecanica es casi siempre la misma:

    mapa 73, evento 150:  si GENERATOR_ALIVE(218, =, 0)
                          entonces CHANGE_STATICOBJ(118, 60037)

o sea "cuando la zona 218 se queda sin bichos, pon el objeto 60037 en el TAG
118", que en el mapa 73 es la casilla (119,177): la puerta que se abre al
limpiar la sala. El problema es que las plantillas de monstruos no guardan a
que generador pertenece cada bicho -- se generaron a partir de ellos, pero el
dato no viajo --, y volver a generarlas pisaria las que vinieron de capturas.

Asi que la relacion se reconstruye por posicion, que es como se creo. El TAG
de la zona trae sus casillas, y poblar_del_cliente reparte los monstruos en
un anillo de radio 3 alrededor con 5 de separacion; con eso, un bicho es de
la zona cuya casilla mas cercana este a RADIO o menos de su casilla DE
APARICION. Se usa la de aparicion y no la actual a proposito: los monstruos
pasean, y uno que se haya alejado seguiria contando en su zona, que es lo que
el evento quiere saber.

EL ESTADO DEL MAPA NO ES DEL MAPA, ES DE LA SESION. Mientras los monstruos
sean por sesion -- cada jugador ve los suyos -- las variables, los
temporizadores y las puertas tambien tienen que serlo, o un jugador abriria
la puerta del otro. Cuando el mundo pase a ser compartido, esto se mueve a
una sola instancia por mapa y el resto no cambia.

LOS EVENTOS DE DISPARO 0 son los que nadie dispara: se comprueban solos. Son
53 y son los que llevan las mecanicas de instancia. Por eso hay
`pendientes()`, que los repasa, y una marca de los que ya saltaron para no
repetir la puerta en cada paso.
"""
import logging

import eventos as ev

log = logging.getLogger(__name__)

# Cuanto se aleja un monstruo de su zona al nacer. poblar_del_cliente usa un
# anillo de radio 3; se deja uno mas de margen y no mas, porque las zonas de
# una misma instancia estan a pocas casillas y pasarse mezclaria dos salas.
RADIO_ZONA = 4

# Las condiciones que este contexto puede contestar de verdad. Lo que no
# este aqui sale como "no se sabe" y su disparador no salta.
SABE = frozenset((
    2,      # QUEST_STEP
    6,      # BAGITEM
    7,      # QUESTITEM (ranuras ocultas 497..556)
    8,      # EMPTYSLOT_COUNT
    10,     # PROB100
    11,     # QUEST_FINISH
    12,     # ALIGNMENT
    13,     # QUEST_RUNNING
    14,     # GENERATOR_ALIVE
    17,     # MONEY
    29,     # MAPVAR
    39,     # GROUP
    56,     # IS_LIVE
    3,      # PROPERTY (solo nivel y rango)
))

# Las ranuras ocultas donde misiones.py ya pone los contadores de caceria.
# No ocupan mochila y el cliente las muestra en el HUD.
OCULTA_PRIMERA, OCULTA_ULTIMA = 497, 556

# La mochila empieza en la 20; de 0 a 19 va el equipo.
BOLSA_PRIMERA = 20
BOLSA_ULTIMA = 199

# Lo que contesta paso_de_mision cuando el personaje NO lleva esa mision.
# No puede ser 0, que es el primer paso en la numeracion del cliente.
PASO_SIN_MISION = -1

# Los codigos de ALIGNMENT del eventdef (1 聖光, 2 大地, 3 鋼鐵, 4 暗影, 5 天國)
# con los NOMBRES que guarda el servidor, que son los de la ficha
# (login.CODIGO_FACCION): Aurora, Beasts, Steel, Shadow, Heaven. Solo con
# Holy/Earth, un personaje de Aurora o de Beasts salia como faccion 0 y no
# cumplia ninguna condicion de faccion de los mapas.
_FACCIONES = {'Aurora': 1, 'Holy': 1, 'Beasts': 2, 'Earth': 2, 'Steel': 3,
              'Shadow': 4, 'Heaven': 5, 'Graduated': 5, 'Neutral': 5,
              'Neutrally': 5}


class EstadoDeMapa:
    """Lo que el mapa va cambiando mientras se juega.

    Vive colgado de la sesion y se tira al cambiar de mapa, que es lo que
    hace que entrar de nuevo en una instancia la encuentre cerrada otra vez.
    """

    def __init__(self, stage):
        self.stage = stage
        self.variables = {}          # (mapa, var) -> valor
        self.temporizadores = {}     # tag -> [activo, veces]
        self.objetos = {}            # tag -> id de objeto puesto
        self.ya_saltaron = set()     # eventos de disparo 0 que ya se hicieron
        self._zonas = None

    # -- a que zona de generador pertenece una casilla --------------------
    def _indice_de_zonas(self):
        """casilla -> TAG de la zona, construido una vez por mapa.

        Se guarda la zona MAS CERCANA, no la primera que toque, porque las
        zonas de una instancia estan pegadas y la primera que apareciera
        dependeria del orden del json.
        """
        if self._zonas is not None:
            return self._zonas
        self._zonas = {}
        d = ev.del_stage(self.stage) or {}
        mejor = {}
        for tag, g in (d.get('generadores') or {}).items():
            t = int(tag)
            for px, py in g['puntos']:
                for dx in range(-RADIO_ZONA, RADIO_ZONA + 1):
                    for dy in range(-RADIO_ZONA, RADIO_ZONA + 1):
                        dist = max(abs(dx), abs(dy))
                        c = (px + dx, py + dy)
                        if c not in mejor or dist < mejor[c][0]:
                            mejor[c] = (dist, t)
        self._zonas = {c: t for c, (_d, t) in mejor.items()}
        return self._zonas

    def zona_de(self, tile):
        return self._indice_de_zonas().get((int(tile[0]), int(tile[1])))

    def vivos_por_zona(self, monstruos):
        """TAG de zona -> cuantos bichos siguen vivos en ella."""
        cuenta = {}
        for m in (monstruos or {}).values():
            if not getattr(m, 'vivo', False):
                continue
            z = self.zona_de(getattr(m, 'spawn_tile', None)
                             or (getattr(m, 'spawn_x', 0), getattr(m, 'spawn_y', 0)))
            if z is not None:
                cuenta[z] = cuenta.get(z, 0) + 1
        return cuenta

    # -- variables de mapa ------------------------------------------------
    def variable(self, mapa, var):
        return int(self.variables.get((int(mapa), int(var)), 0))

    def poner_variable(self, mapa, var, valor):
        self.variables[(int(mapa), int(var))] = int(valor)

    def sumar_variable(self, mapa, var, valor):
        self.variables[(int(mapa), int(var))] = self.variable(mapa, var) + int(valor)

    # -- temporizadores ---------------------------------------------------
    def temporizador(self, tag):
        return self.temporizadores.setdefault(int(tag), [False, 0])


def estado_de(ses):
    """El estado del mapa en el que esta la sesion, creandolo si hace falta.

    Se rehace al cambiar de stage sin que nadie tenga que acordarse de
    limpiarlo: la comprobacion es el propio numero de mapa.
    """
    stage = getattr(getattr(ses, 'personaje', None), 'stage', 0) or 0
    e = getattr(ses, 'estado_mapa', None)
    if e is None or e.stage != stage:
        e = EstadoDeMapa(stage)
        ses.estado_mapa = e
    return e


class ContextoSesion(ev.Contexto):
    """Contesta las condiciones mirando la sesion de verdad."""

    sabe = SABE

    def __init__(self, ses, estado=None):
        self.ses = ses
        self.p = getattr(ses, 'personaje', None)
        self.estado = estado if estado is not None else estado_de(ses)
        self.stage = self.estado.stage
        self.casilla = (getattr(self.p, 'tile_x', 0) or 0,
                        getattr(self.p, 'tile_y', 0) or 0)
        self.es_alma = bool(getattr(ses, 'muerto', False))
        self._vivos = None

    # -- misiones ---------------------------------------------------------
    def paso_de_mision(self, quest):
        """El paso EN LA NUMERACION DEL CLIENTE, que no es la del servidor.

        Esto es un desajuste de los que rompen todo sin hacer ruido. El
        servidor guarda el primer paso como 1 y lo manda por red como 0:
        misiones.avanzar_paso hace `paso_red = nuevo_paso - 1` y lo dice en
        un comentario. Los eventos del cliente usan la numeracion DE RED:
        el drop del Mushroom de The Reivers pide QUEST_STEP(502, 0) y eso
        es el primer paso, el que el jugador ve como "1." en su diario.

        Si se compararan sin convertir, ninguna condicion de mision casaria
        nunca y los disparadores no saltarian jamas -- que es exactamente
        como se veia: la mision aceptada y el objeto sin caer.
        """
        if not self.p:
            return PASO_SIN_MISION
        for q, pa in (getattr(self.p, 'quests', None) or []):
            if q == quest:
                return max(0, int(pa) - 1)
        # No tenerla no es ir por el primer paso, asi que tiene que ser un
        # valor que no case con ningun QUEST_STEP.
        return PASO_SIN_MISION

    def mision_terminada(self, quest):
        try:
            import misiones as _mis
            return bool(_mis.mision_completada(self.p, quest))
        except Exception:
            return False

    def mision_en_curso(self, quest):
        return self.paso_de_mision(quest) >= 0 and not self.mision_terminada(quest)

    # -- objetos ----------------------------------------------------------
    def _contar(self, item, desde, hasta):
        if not self.p:
            return 0
        inv = getattr(self.p, 'inventario', None) or {}
        cant = getattr(self.p, 'cantidades', None) or {}
        total = 0
        for ranura, iid in inv.items():
            r = int(ranura)
            if desde <= r <= hasta and int(iid) == int(item):
                total += max(1, int(cant.get(r, cant.get(str(r), 1))))
        return total

    def en_bolsa(self, item):
        return self._contar(item, BOLSA_PRIMERA, BOLSA_ULTIMA)

    def objeto_de_mision(self, item):
        c = self._contar(item, OCULTA_PRIMERA, OCULTA_ULTIMA)
        if c > 0:
            return c
        if self.p:
            qk = getattr(self.p, 'quest_kills', None) or {}
            for q, pa in (getattr(self.p, 'quests', None) or []):
                k = f"{q}_{pa}"
                try:
                    import misiones as _mis
                    _mis._cargar_db()
                    c_data = getattr(_mis, '_CACERIAS', {}).get(k, {})
                    if c_data.get('token_id') == int(item) or (int(item) == 16075 and q == 142):
                        return int(qk.get(k, 0))
                except Exception:
                    pass
        return 0

    def huecos_libres(self):
        if not self.p:
            return 0
        inv = getattr(self.p, 'inventario', None) or {}
        usadas = sum(1 for r in inv if BOLSA_PRIMERA <= int(r) <= BOLSA_ULTIMA)
        return max(0, (BOLSA_ULTIMA - BOLSA_PRIMERA + 1) - usadas)

    def oro(self):
        return int(getattr(self.p, 'oro', 0) or 0)

    # -- personaje --------------------------------------------------------
    def nivel(self):
        return int(getattr(self.p, 'nivel', 0) or 0)

    def rango(self):
        return int(getattr(self.p, 'rango', 0) or 0)

    def faccion(self):
        f = getattr(self.p, 'faction', None)
        return _FACCIONES.get(f, 0) if isinstance(f, str) else int(f or 0)

    def vivo(self):
        return not self.es_alma

    # -- mapa -------------------------------------------------------------
    def vivos_del_generador(self, tag):
        if self._vivos is None:
            self._vivos = self.estado.vivos_por_zona(
                getattr(self.ses, 'monstruos', None))
        return int(self._vivos.get(int(tag), 0))

    def variable_de_mapa(self, mapa, var):
        return self.estado.variable(mapa, var)

    def temporizador_activo(self, tag):
        return bool(self.estado.temporizador(tag)[0])

    def veces_del_temporizador(self, tag):
        return int(self.estado.temporizador(tag)[1])

    # -- grupo ------------------------------------------------------------
    def miembros_del_grupo(self, que=0):
        if que != 0:
            return 0       # cuantos chicos o chicas: todavia no se sabe
        try:
            import equipos as _eq
            n = _eq.cuantos(self.ses)
            return max(1, int(n or 1))
        except Exception:
            return 1


def al_pisar(ses, tile):
    """Los efectos de pisar una casilla. Lista vacia si ahi no hay nada."""
    estado = estado_de(ses)
    evento = ev.evento_en(estado.stage, tile[0], tile[1])
    if not evento:
        return []
    ctx = ContextoSesion(ses, estado)
    disparo = ev.DISPAROS_AL_PASAR if not ctx.es_alma else (ev.ALMA_PISA,
                                                           ev.ALMA_CHOCA)
    return ev.ejecutar(estado.stage, evento, disparo, ctx)


def al_pulsar(ses, tile):
    """Los efectos de pulsar sobre lo que haya en una casilla."""
    estado = estado_de(ses)
    evento = ev.evento_en(estado.stage, tile[0], tile[1])
    if not evento:
        return []
    ctx = ContextoSesion(ses, estado)
    disparo = ev.DISPAROS_AL_PULSAR if not ctx.es_alma else (ev.ALMA_PULSA,)
    return ev.ejecutar(estado.stage, evento, disparo, ctx)


def evento_del_monstruo(stage, npc_type):
    """El evento que dispara ese tipo de bicho al morir, o None.

    NO es el evento del objeto de su casilla. Los disparadores de muerte
    citan eventos que ningun objeto del mapa referencia -- en Dense Forest
    los objetos solo nombran el 1, 2, 3, 4 y 1001, y los botines cuelgan del
    501 al 505 --, y el enlace esta en el registro del generador, en un
    campo que no se leia. Cada tipo de monstruo lleva uno y siempre el mismo.
    """
    d = ev.del_stage(stage)
    if not d:
        return None
    return (d.get('monstruos') or {}).get(str(int(npc_type)))


def al_morir_monstruo(ses, monstruo):
    """Los efectos de que muera un bicho: botines y pasos de mision."""
    estado = estado_de(ses)
    evento = evento_del_monstruo(estado.stage,
                                 getattr(monstruo, 'npc_type', 0) or 0)
    if not evento:
        return []
    ctx = ContextoSesion(ses, estado)
    return ev.ejecutar(estado.stage, evento, ev.DISPAROS_AL_MORIR, ctx)


def pendientes(ses):
    """Los eventos que se comprueban solos (disparo 0) y todavia no saltaron.

    Son 53 en todo el juego y son los que abren las instancias. Se repasan
    cuando algo pudo cambiar -- tipicamente al morir un bicho -- y el que
    salta queda marcado para que la puerta no se vuelva a poner en cada paso.
    """
    estado = estado_de(ses)
    ctx = ContextoSesion(ses, estado)
    efectos = []
    for d in ev.disparadores(estado.stage, disparo=ev.NINGUNO):
        if d['ev'] in estado.ya_saltaron:
            continue
        salen = ev.ejecutar(estado.stage, d['ev'], ev.NINGUNO, ctx)
        if salen:
            estado.ya_saltaron.add(d['ev'])
            efectos += salen
    return efectos
