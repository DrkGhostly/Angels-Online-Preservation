"""El bloque de estado de las mascotas, el s2c 0x0065.

El mapa de campos no se dedujo mirando bytes sueltos: se comparo el paquete
contra la ficha que el juego enseñaba en ese momento -- una Battlemaid de
nivel 246 con 12.100 de ataque, 15.755 de defensa, 3.137 de ataque magico,
4.431 de defensa magica, 1.947 de rigor, 1.127 de agilidad y 78 de intimidad.
Los siete numeros aparecieron en el paquete, y esos son los offsets.

Aqui se comprueba contra la captura entera, que trae seis mascotas distintas.
"""
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / 'server'))

import mascotas as ms       # noqa: E402

CAPTURA = RAIZ / 'logs' / 'proxy' / 'mundo_010658_700672_orden.jsonl'


def _bloques():
    if not CAPTURA.exists():
        return []
    out = []
    for linea in CAPTURA.open(encoding='utf-8'):
        r = json.loads(linea)
        if r.get('dir') == 's2c' and r.get('opcode') == 0x65 and r.get('hex'):
            b = bytes.fromhex(r['hex'])
            if len(b) == ms.TAM:
                out.append(b)
    return out


def test_lee_la_captura_entera():
    """Las seis mascotas salen con nombre, nivel y stats coherentes."""
    bloques = _bloques()
    if not bloques:
        return                      # sin la captura no hay nada que probar
    nombres = set()
    for b in bloques:
        d = ms.leer(b)
        assert d, 'no se pudo leer un bloque de 200 bytes'
        assert d['nombre'], 'mascota sin nombre'
        assert 1 <= d['nivel'] <= 300, (d['nombre'], d['nivel'])
        assert d['hp'] <= d['hp_max'], (d['nombre'], d['hp'], d['hp_max'])
        assert d['atk'] >= 0 and d['dfs'] >= 0
        nombres.add(d['nombre'])
    assert 'Battlemaid' in nombres, nombres


def test_la_battlemaid_cuadra_con_su_ficha():
    """Los numeros que se leyeron en pantalla, uno a uno."""
    for b in _bloques():
        d = ms.leer(b)
        if d['nombre'] != 'Battlemaid':
            continue
        assert d['nivel'] == 246, d['nivel']
        assert d['atk'] == 12100, d['atk']
        assert d['dfs'] == 15755, d['dfs']
        assert d['matk'] == 3137, d['matk']
        assert d['mdef'] == 4431, d['mdef']
        assert d['rigor'] == 1947, d['rigor']
        assert d['agilidad'] == 1127, d['agilidad']
        assert d['intimidad'] == 78, d['intimidad']
        return
    # Sin captura no falla: solo no comprueba nada.


def test_ida_y_vuelta():
    """Lo que se arma se vuelve a leer igual."""
    original = {'entidad': 0x1050c6, 'tipo': 44181, 'nombre': 'Battlemaid',
                'nivel': 246, 'exp': 138901, 'exp_max': 138901,
                'hp': 18775, 'hp_max': 18775, 'mp_max': 18148,
                'atk': 12100, 'dfs': 15755, 'matk': 3137, 'mdef': 4431,
                'rigor': 1947, 'agilidad': 1127,
                'saciedad': 462, 'intimidad': 78}
    paquete = ms.armar(original)
    assert paquete[:2] == b'\x65\x00'
    assert len(paquete) == ms.TAM + 2
    vuelta = ms.leer(paquete[2:])
    for k, v in original.items():
        assert vuelta[k] == v, (k, v, vuelta[k])


def test_cada_stat_va_dos_veces():
    """El base y el efectivo, que es lo que la ventana pinta en dos columnas."""
    import struct
    b = ms.armar({'atk': 12100, 'dfs': 15755})[2:]
    for campo in ('atk', 'dfs'):
        off = ms.OFF[campo]
        uno = struct.unpack_from('<I', b, off)[0]
        dos = struct.unpack_from('<I', b, off + 4)[0]
        assert uno == dos, (campo, uno, dos)


def test_el_pienso_corriente_da_saciedad_no_stats():
    """Son dos cosas distintas y conviene no mezclarlas.

    El Pet Feed dice "Increases the satiation degree by 500" y que la mascota
    mejora cuando pasa de 100. El que sube stats es el Improved Pet Feed, que
    va por mejoras.py.
    """
    est = {'saciedad': 40, 'atk': 100}
    valor, puede = ms.alimentar(est)
    assert valor == 540 and puede
    assert est['atk'] == 100, 'el pienso corriente no toca los stats'
    # No pasa del tope.
    for _ in range(10):
        ms.alimentar(est)
    assert est['saciedad'] == ms.SACIEDAD_MAXIMA


def test_los_improved_suben_los_stats():
    """Tres piensos del 8% sobre 100 de ataque dan 124."""
    est = {'atk': 100, 'dfs': 200, 'nombre': 'X'}
    sub = ms.aplicar_mejoras(est, {'atk': 24})
    assert sub['atk'] == 124
    assert sub['dfs'] == 200, 'lo que no se toca se queda igual'
    assert est['atk'] == 100, 'la ficha guardada no se modifica'


def _entradas_reales():
    """Las entradas de 231 bytes que hay en las capturas."""
    import glob
    out = []
    for f in sorted(glob.glob(str(RAIZ / 'logs' / 'proxy' / '*.jsonl'))):
        for linea in open(f, encoding='utf-8'):
            try:
                r = json.loads(linea)
            except Exception:
                continue
            if (r.get('dir') == 's2c' and r.get('opcode') == 0x1B
                    and len(r.get('hex') or '') == 470):
                out.append(bytes.fromhex(r['hex'])[4:])
    return out


def test_la_entrada_se_reconstruye_byte_a_byte():
    """Se lee una entrada real, se vuelve a armar, y sale identica.

    Es la prueba que importa: si un offset estuviera mal, el byte saldria
    en otro sitio y esto lo cantaria. Son 63 entradas de nueve mascotas.
    """
    import struct
    reales = _entradas_reales()
    if not reales:
        return
    for real in reales:
        est = {}
        for campo, off in ms.OFF_ENTRADA.items():
            if campo == 'nombre':
                est[campo] = real[off:off + ms.LARGO_NOMBRE].split(b'\0')[0] \
                    .decode('latin1', 'replace')
            elif campo in ('sprite', 'saciedad'):
                est[campo] = struct.unpack_from('<H', real, off)[0]
            else:
                est[campo] = struct.unpack_from('<I', real, off)[0]
        assert ms.entrada(real, est) == real, est.get('nombre')


def test_el_nombre_usa_los_doce_bytes():
    """"Civet Guardi" y "Dragon's Egg" miden justo doce y no llevan cero."""
    e = ms.entrada(bytes(ms.TAM_ENTRADA), {'nombre': 'Civet Guardi'})
    off = ms.OFF_ENTRADA['nombre']
    assert e[off:off + 12] == b'Civet Guardi'


def test_la_entrada_mide_231():
    """Ni 86 ni 119: esos dos tamaños son los que cerraban el cliente."""
    e = ms.entrada(bytes(10), ms.recien_nacida('Battlemaid', 3200))
    assert len(e) == 231, len(e)


def test_los_stats_salen_de_petattrib():
    """Los ocho numeros del Elf Egg, contra la ventana del juego.

    La captura del Elf Egg a nivel 1 enseña Atk 28, Dfs 10, M.Atk 18,
    M.Dfs 19, Rig 15 y Agi 15, con 100 de vida y 105 de mana. Los ocho
    salen de petattrib, tipo 輔助回復型. Se creia que el cliente los
    calculaba solo: no lo hace, y por eso la ventana salia en blanco.
    """
    # El Elf Egg de la captura es el sprite 3181. El 3049 es el FireElf
    # Egg, que es de otra clase: se habian confundido cuando la tabla se
    # escribia a mano, y pet.xml lo deja claro.
    d = ms.stats_de(3181, 1)
    if not d:
        return                      # sin content.db no hay nada que probar
    assert d['hp_max'] == 100 and d['mp_max'] == 105, d
    assert d['atk'] == 28 and d['dfs'] == 10, d
    assert d['matk'] == 18 and d['mdef'] == 19, d
    assert d['rigor'] == 15 and d['agilidad'] == 15, d
    # Y la Battlemaid de nivel 217, que se midio en el proxy.
    b = ms.stats_de(3200, 217)
    assert b['hp_max'] == 16057 and b['mp_max'] == 7772, b


def test_el_arbol_del_elfo_cuadra_con_la_tabla():
    """El arbol de la wiki, siguiendo las ramas que trae pet.xml.

    Cada mascota lleva sus dos evoluciones en 升階變化1 (la "mean") y
    升階變化2 (la "nice"). Del Elf Egg salen Naughty Elf y Flying Guy, y de
    ahi a Fiend Lily / Incubus y a Night Queen / Night Devil. Los stats de
    cada escalon salen de petattrib con la clase de la nueva forma.
    """
    if not ms.stats_de(3181, 1):
        return                      # sin los paks no hay nada que probar
    esperado = {('mean', 15): ('Naughty Elf', 408, 304, 99, 111),
                ('nice', 15): ('Flying Guy', 375, 304, 95, 85),
                ('mean', 55): ('Night Queen', 1696, 1204, 402, 503),
                ('nice', 55): ('Elf Queen', 1558, 1204, 388, 458)}
    for (rama, nivel), (nombre, hp, mp, atk, dfs) in esperado.items():
        f = ms.recien_nacida('', 3181)
        # Una rama por etapa hasta llegar al escalon que toca.
        pasos = 1 if nivel == 15 else 3
        for _ in range(pasos):
            f['nivel'] = nivel
            f = ms.evolucionar(f, rama)
        assert f['nombre'] == nombre, (rama, nivel, f['nombre'])
        assert (f['hp_max'], f['mp_max'], f['atk'], f['dfs']) ==             (hp, mp, atk, dfs), (rama, nivel, f)


def test_la_tabla_de_pet_xml_cuadra_con_el_proxy():
    """Los trece pares sprite/tipo que se vieron en las capturas.

    El 'tipo' es el 圖號1 de pet.xml y viaja en el +4 del 0x0065. Se dejaba
    en cero, y sin el el cliente no sabe que mascota es: la ventana salia
    sin nivel y sin dibujo.
    """
    medido = {3200: 44181, 3358: 44171, 3097: 44073, 3192: 44115,
              3183: 44055, 3181: 44072, 3145: 44069, 3146: 42056,
              3148: 44021, 3152: 44082, 3187: 44057, 3099: 44060,
              3474: 42411}
    if not ms.ficha_de_sprite(3200):
        return
    for sprite, tipo in medido.items():
        assert ms.ficha_de_sprite(sprite).get('tipo') == tipo, sprite
    # Y la ficha que armamos lo lleva dentro.
    import struct
    b = ms.armar(ms.recien_nacida('', 3200))[2:]
    assert struct.unpack_from('<I', b, ms.OFF['tipo'])[0] == 44181


def test_guardar_la_mascota_la_quita_del_mundo():
    """Al guardarla hay que mandar el 0x0007 con SU entidad.

    Antes solo se remandaba la entrada del inventario y la criatura se
    quedaba pegada en pantalla: no habia forma de guardarla. El 0x0007 es
    el mismo mensaje que usa el juego para cualquier criatura que se va --
    de las seis entidades que lo recibieron en la captura, tres habian
    salido antes con un 0x0008.
    """
    import struct
    import sys as _s
    _s.path.insert(0, str(RAIZ / 'server'))
    _s.path.insert(0, str(RAIZ / 'proto'))
    import app

    class Ses:
        rol = 'mundo'
        usuario = None

        def __init__(self):
            self.inventario = {34: 20012}
            self.cantidades = {}
            self.instancias = {}
            self.personaje = type('P', (), {
                'char_id': 4794, 'entity_id': 286, 'mejoras': {},
                'nombre': 'Karma', 'x': 100, 'y': 50, 'mascota': None})()
            self.sal = []

        def enviar(self, *m):
            self.sal.extend(m)

    ses = Ses()
    app._pet_alternar(ses, 't', 34)
    ops = [struct.unpack_from('<H', m, 0)[0] for m in ses.sal]
    # Sacarla: enlace, ficha, entrada e criatura, en ese orden.
    assert ops == [0x001D, 0x0065, 0x001B, 0x0050], [hex(o) for o in ops]
    entidad = ses.personaje.mascota['entidad']
    assert entidad

    ses.sal = []
    app._pet_alternar(ses, 't', 34)
    ops = [struct.unpack_from('<H', m, 0)[0] for m in ses.sal]
    assert 0x0007 in ops, [hex(o) for o in ops]
    quita = [m for m in ses.sal if m[:2] == bytes((7, 0))][0]
    assert struct.unpack_from('<I', quita, 2)[0] == entidad
    assert struct.unpack_from('<I', quita, 2)[0] == entidad
    assert ses.personaje.mascota['fuera'] is False
    assert ses.personaje.mascota['entidad'] is None


def test_la_experiencia_cuadra_con_las_23_fichas():
    """exp_max = 36 * nivel^1.5, contra las 23 fichas capturadas.

    De nivel 1 a 246, y da los 23 numeros exactos. NO es la tabla
    寵物A/B/C/D de level.xml: esa pide billones por nivel y no cuadra con
    ninguna ficha. Se probo y se descarto.
    """
    medido = {1: 36, 2: 102, 66: 19303, 86: 28711, 102: 37085, 114: 43819,
              125: 50312, 134: 55842, 143: 61561, 150: 66136, 158: 71497,
              211: 110338, 216: 114283, 217: 115078, 222: 119078,
              228: 123938, 232: 127214, 236: 130518, 239: 133015,
              243: 136368, 244: 137210, 245: 138055, 246: 138901}
    for nivel, esperado in medido.items():
        assert ms.exp_para_subir(nivel) == esperado, (nivel, esperado,
                                                      ms.exp_para_subir(nivel))


def test_la_mascota_sube_de_nivel_y_le_crecen_los_stats():
    """Al subir, los stats se vuelven a sacar de petattrib con el nivel nuevo."""
    f = ms.recien_nacida('', 3200)
    if not f.get('atk'):
        return
    atk1 = f['atk']
    assert ms.dar_exp(f, 36) == 1 and f['nivel'] == 2
    assert f['exp'] == 0 and f['exp_max'] == 102
    assert f['atk'] > atk1, (atk1, f['atk'])
    # Un golpe de experiencia sube varios niveles de una vez.
    n = ms.dar_exp(f, 50000)
    assert n > 10 and f['nivel'] == 2 + n
    # Y lo que sobra se queda por debajo del siguiente tope.
    assert f['exp'] < f['exp_max']


def test_los_vales_de_experiencia_salen_del_item():
    """188 vales en el cliente, cada uno con destino y cantidad dentro.

    動態資料1 es a quien va -- 1 personaje, 2 habilidad, 3 honor, 4 mascota --
    y 動態資料2 cuanto da. El 28939 que se probo en el juego es del 4 con
    100.000.000, y su descripcion dice "increase the current pet's exp by
    100,000,000".
    """
    import sys as _s
    _s.path.insert(0, str(RAIZ / 'server'))
    import inventario as inv
    if inv.vale_de_exp(28939) is None:
        return                      # sin content.db no hay nada que probar
    assert inv.vale_de_exp(28939) == (inv.VALE_MASCOTA, 100000000)
    assert inv.vale_de_exp(18628) == (inv.VALE_MASCOTA, 1000000)
    assert inv.vale_de_exp(12771) == (inv.VALE_PERSONAJE, 230000)
    assert inv.vale_de_exp(12772) == (inv.VALE_HABILIDAD, 50)
    assert inv.vale_de_exp(10) is None, 'una espada no es un vale'


def test_un_vale_grande_no_pasa_del_tope_de_la_tabla():
    """Con 100 millones se iba al nivel 545, que no existe en petattrib.

    Al no existir, stats_de() devolvia vacio y la mascota marcaba nivel 545
    con los stats de nivel 1.

    De paso esto comprueba la curva contra la ficha real: 10 millones dejan
    a la Battlemaid en el nivel 217, y ahi la captura enseñaba 9492 de
    ataque, 12345 de defensa y 16057 de vida.
    """
    f = ms.recien_nacida('', 3200)
    if not f.get('atk'):
        return
    tope = ms.nivel_maximo(3200)
    g = ms.recien_nacida('', 3200)
    ms.dar_exp(g, 10000000)
    assert g['nivel'] == 217, g['nivel']
    assert (g['atk'], g['dfs'], g['hp_max']) == (9492, 12345, 16057), g

    h = ms.recien_nacida('', 3200)
    ms.dar_exp(h, 100000000)
    assert h['nivel'] == tope, (h['nivel'], tope)
    assert h['atk'] > 0, 'al tope se quedaba con los stats de nivel 1'


def test_la_evolucion_medida_en_el_proxy():
    """Un huevo de sprite 15828 evoluciono al 15830 al llegar a nivel 15.

    15830 es su 升階變化2, asi que la rama 2 es la que sale criando en
    positivo. Y su umbral era 2, no 10: el 條件成長值 varia por mascota.
    """
    if not ms.ficha_de_sprite(15828):
        return
    mean, nice = ms.ramas_de(15828)
    assert nice == 15830, (mean, nice)
    assert ms.crianza_necesaria(15828) == 2
    f = ms.recien_nacida('', 15828)
    f['nivel'] = 15
    ms.criar(f, 2)
    assert ms.rama_por_crianza(f) == 'nice'
    # El umbral NO es siempre 10: en lo medido salieron 2, 0, 6 y -4.
    assert ms.crianza_necesaria(13591) == -4
    assert ms.crianza_necesaria(13594) == 6
    ms.evolucionar(f, 'nice')
    assert f['sprite'] == 15830

    # Y la cadena entera, que se capturo de principio a fin:
    #   15828 (原型) -> 15830 (初階) -> 15834 (中階) -> 15839 (高階)
    # Las tres veces por la rama 2, y pet.xml acierta las tres.
    for destino in (15834, 15839):
        ms.evolucionar(f, 'nice')
        assert f['sprite'] == destino, (destino, f['sprite'])
    assert ms.ficha_de_sprite(15839).get('etapa') == '高階'
    # El ultimo escalon ya no tiene a donde ir.
    assert ms.ramas_de(15839) == (None, None)


def test_el_porcino_alterna_de_rama():
    """13590 -> 13591 (rama1) -> 13594 (rama2) -> 13598 (rama1).

    Las tres capturadas seguidas, y pet.xml acierta las tres. Importa
    porque demuestra que la rama se ELIGE: el otro huevo del mismo dia se
    fue tres veces por la rama 2, y este alterna.
    """
    if not ms.ficha_de_sprite(13590):
        return
    cadena = [(13590, 13591, 0), (13591, 13594, 1), (13594, 13598, 0)]
    for origen, destino, cual in cadena:
        assert ms.ramas_de(origen)[cual] == destino, (origen, destino)


def test_la_rama_1_es_la_mean_del_arbol_de_la_wiki():
    """3085 Elf Egg -> Naughty Elf -> Fiend Lily -> Night Queen, por rama 1.

    Es la cadena "mean" de la wiki, capturada entera. Y la rama 2 del mismo
    huevo son Flying Guy, Incubus y Succubus, que es la "nice". Esto es lo
    que fija el sentido de las dos ramas.
    """
    if not ms.ficha_de_sprite(3085):
        return
    mean = [(3085, 3087), (3087, 3091), (3091, 3096)]
    for origen, destino in mean:
        assert ms.ramas_de(origen)[0] == destino, (origen, destino)
    nice = {3085: 3086, 3087: 3090, 3091: 3095}
    for origen, destino in nice.items():
        assert ms.ramas_de(origen)[1] == destino, (origen, destino)
    assert ms.ficha_de_sprite(3086).get('nombre') == 'Flying Guy'


def test_hay_mascotas_que_no_evolucionan():
    """Las 頂階 -- fusion y de monstruo -- nacen ya en su forma final.

    Contado sobre las 1751 de pet.xml: las etapas 原型, 初階 y 中階 llevan
    siempre dos ramas, y las 高階 y 頂階 ninguna. La Battlemaid es 頂階.
    """
    if not ms.ficha_de_sprite(3200):
        return
    assert ms.es_unica(3200), 'la Battlemaid es una fusion'
    assert not ms.evoluciona(3200)
    # Un huevo normal si evoluciona.
    assert ms.evoluciona(3085) and not ms.es_unica(3085)
    # Y ninguna 高階 ni 頂階 tiene ramas.
    for sprite, d in ms._tabla().items():
        if d.get('etapa') in (ms.ETAPA_FINAL, ms.ETAPA_UNICA):
            assert not ms.evoluciona(sprite), sprite


def test_la_pet_de_agua_tambien_alterna():
    """3133 WaterElf Egg -> 3134 (rama1) -> 3137 (rama2) -> 3142 (rama2)."""
    if not ms.ficha_de_sprite(3133):
        return
    for origen, destino, cual in ((3133, 3134, 0), (3134, 3137, 1),
                                  (3137, 3142, 1)):
        assert ms.ramas_de(origen)[cual] == destino, (origen, destino)


def test_la_escena_de_crianza_capturada():
    """La escena 5, comparada palabra por palabra con la del juego.

    El cuadro que salio en pantalla decia:

        Dragon's Egg put it's head out when its owner wasn't watching it.
        (Your act affects Pet's growth)
          Pretend to turn around casually.
          Can't stand watching it.
          Whistle and pretend to see nothing.

    Y en petaspect.xml es la 5, con valores 0, -1 y +1 EN ESE ORDEN. Las
    opciones no van ordenadas por valor, asi que elegir siempre la primera
    o la segunda no da un resultado fijo.
    """
    todas = ms.situaciones()
    if not todas:
        return
    e = todas.get('5')
    assert e, 'falta la escena 5'
    assert [o['valor'] for o in e['opciones']] == [0, -1, 1], e
    assert e['opciones'][2]['texto'].startswith('Whistle and pretend')
    # Las 107 tienen exactamente tres opciones.
    for n, d in todas.items():
        assert len(d['opciones']) == 3, (n, d)


def test_el_0x003E_hace_dos_cosas():
    """Ordenes con 0-2 y respuesta al cuadro de crianza con 4-6.

    Medido en una captura casi vacia: se respondio al cuadro dos veces y
    aparecieron un 6 y un 5, uno por respuesta. En el total de capturas
    salen 3, 20 y 3 para las ordenes y 24, 18 y 8 para las opciones.
    """
    for v in (0, 1, 2):
        assert not ms.es_respuesta_crianza(v), v
    for v in (4, 5, 6):
        assert ms.es_respuesta_crianza(v), v
    assert [ms.opcion_de(v) for v in (4, 5, 6)] == [0, 1, 2]

    escena = ms.situaciones().get('5')
    if not escena:
        return
    # La escena 5 vale 0, -1 y +1 EN ESE ORDEN.
    f = ms.recien_nacida('', 3085)
    assert ms.responder_crianza(dict(f), escena, 4)[0] == 0
    assert ms.responder_crianza(dict(f), escena, 5)[0] == -1
    assert ms.responder_crianza(dict(f), escena, 6)[0] == 1
    # Y la crianza se acumula.
    g = ms.recien_nacida('', 3085)
    ms.responder_crianza(g, escena, 6)
    ms.responder_crianza(g, escena, 6)
    assert g['crianza'] == 2


def test_la_estrellita_de_la_crianza():
    """El 0x000A que sale al responder, byte a byte como el capturado."""
    p = ms.efecto(0x105100, 0x0f78e8)
    assert p == bytes.fromhex('0a0000511000e8780f0001009a02'), p.hex()


if __name__ == '__main__':
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith('test_') and callable(fn):
            try:
                fn()
                print('  OK   ' + nombre)
            except AssertionError as e:
                fallos += 1
                print('  FALLA ' + nombre + ': ' + str(e))
    print('fallos:', fallos)
    sys.exit(1 if fallos else 0)
