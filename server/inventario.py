"""
Inventario: mover items entre ranuras, equipar y desequipar.

Protocolo, establecido con capturas del servidor privado que llevan marca de
tiempo en los dos sentidos:

    C -> S  0x0012  [LE16 ranura_origen][LE16 ranura_destino]
    S -> C  0x001B  131 B, describe el movimiento
    S -> C  0x0042  105 B, los stats recalculados   (solo si cambia el equipo)

El 0x001B lleva tres bloques:

    [U8 01][8 bytes id de instancia][LE32 item_id]   el item que se movio
    [U8 01][LE32 char_id][LE16 ranura]               la ranura que lo recibe
    [U8 02][U8 01][LE32 char_id][LE16 ranura]        la ranura que queda vacia

Y los ordena por NUMERO DE RANURA ascendente, no por origen/destino. Por eso
hay dos disposiciones y los offsets cambian segun el caso:

    origen < destino:   vacia@4    item@12   recibe@45
    origen > destino:   item@4     recibe@37  vacia@123

Verificado reconstruyendo los 26 movimientos de una captura en la que el
jugador paseo la misma prenda por todo el inventario: los 26 salen byte a
byte identicos al mensaje real.

La ranura 2 es el cuerpo. Mover algo a la 2 lo equipa y sacarlo lo desequipa;
en ese caso hay que mandar tambien el 0x0042 con los stats. Se comprueba en el
quinto stat, que el cliente muestra como Dfs: 5 sin la ropa y 15 con ella.
"""
import json
import pathlib
import re
import struct
import time

PLANTILLA = pathlib.Path(__file__).parent / 'plantillas' / 'inventario.json'
RANURA_CUERPO = 2           # la unica ranura de equipo MEDIDA en el trafico

# Primera ranura de la mochila. El cliente numera asi: el jugador saco la ropa
# del cuerpo (2) y el cliente pidio ponerla en la 20, que es la primera casilla
# del panel Prop; de ahi en adelante fue usando 21, 22... hasta la 44.
#
# Que todo lo menor a 20 sea equipo es INFERENCIA, no medicion: solo se vio la
# ranura 2. Se deja asi y no cableado al 2 porque el juego tiene mochilas
# equipables (y podria tener capas con ranuras), de modo que el equipo son
# varias casillas y la mochila puede crecer. Nada de esto supone un tamano
# maximo: el inventario es un diccionario de ranura a item.
PRIMERA_RANURA_BOLSA = 20

# El cliente reparte sus items en item, item2 ... item9, una por update.
# Consultando solo `item`, todo lo que vino en un update posterior quedaba
# como si no existiera: sin ranura, sin peso y sin bonos.
TABLAS_ITEM = ('item', 'item2', 'item3', 'item4', 'item5', 'item6',
               'item7', 'item8', 'item9')
_P = None


_PESOS = None


def peso_de(item_id: int) -> int:
    """El peso de un item, de la columna weight de item.xml."""
    global _PESOS
    if _PESOS is None:
        import sqlite3
        _PESOS = {}
        db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
        if db.exists():
            try:
                con = sqlite3.connect(db)
                filas = []
                for _t in TABLAS_ITEM:
                    try:
                        filas += list(con.execute('select id, weight from %s' % _t))
                    except Exception:
                        continue
                for iid, w in filas:
                    try:
                        _PESOS[int(iid)] = int(float(w or 0))
                    except (TypeError, ValueError):
                        continue
                con.close()
            except Exception:
                pass
    return _PESOS.get(int(item_id or 0), 0)


def peso_total(bolsa) -> int:
    """Lo que pesa todo lo que se lleva encima."""
    return sum(peso_de(i) for r, i in (bolsa or {}).items()
               if r != RANURA_ORO)


_CORRELATIVO = [0x030000]


def instancia_nueva() -> bytes:
    """Un id de instancia de ocho bytes para un monton recien creado.

    En la captura son [u32 correlativo][u32 sello de tiempo]: al comprar dos
    cosas a la vez salen 215293 y 215294 con el MISMO sello, y al separar un
    monton la pila nueva se lleva 215300 con un sello posterior. O sea el
    numero es un contador global del servidor y el sello es el momento.
    """
    _CORRELATIVO[0] += 1
    return struct.pack('<II', _CORRELATIVO[0], int(time.time()))


def es_apilable(item_id: int) -> bool:
    """Si varias unidades de ese item comparten una sola casilla.

    Todo lo que no se equipa se apila: pociones, galletas, pasto magico. En
    la captura de Celestia se compran diez pociones rojas y ocupan UNA
    casilla con cantidad diez; nuestro inventario era {ranura: item_id} sin
    cantidades, asi que cada unidad pedia su propia casilla y al usar una se
    borraba el monton entero.
    """
    return not es_equipable(item_id)


# Que contenedor se esta tocando. Es el byte que va delante del id en el
# sub-mensaje que vacia una casilla, y lo destapo la captura de Edo City del
# 28/09/2026 al guardar en el banco: hasta entonces valia siempre 1 y se creia
# fijo.
#   1 + la ENTIDAD del personaje -> la mochila
#   2 + 252                      -> el almacen del banco
CONT_MOCHILA = 1
CONT_BANCO = 2
ID_BANCO = 252


def vaciar_ranura(dueno: int, ranura: int,
                  contenedor: int = CONT_MOCHILA) -> bytes:
    """0x001B que deja una casilla vacia.

    Medido al destruir un monton de pociones:
        01000000 | 02 | 01 | 1e010000 | 2900
    es decir [u32 n=1][u8 02 = vaciar][u8 contenedor][u32 dueno][u16 ranura].

    El byte del contenedor se creia fijo en 1. Al guardar algo en el banco el
    servidor real manda 02 y de dueno el 252 en vez de la entidad.
    """
    return struct.pack('<HIBBIH', 0x001B, 1, 2, contenedor, dueno, ranura)


def ranura_de_instancia(instancias, instancia: bytes, bolsa=None,
                        char_id: int = 0):
    """A que casilla corresponde ese id de instancia de ocho bytes.

    Al vender, el cliente NO manda la casilla: manda el id de instancia del
    monton, el mismo que le dimos en el 0x001A. Antes se leian esos bytes
    como si fueran el numero de casilla, nunca casaban con nada y la venta
    no sacaba nada del inventario ni pagaba: por eso daba 0.

    Tampoco sirve deducirlo del item: al separar un monton la pila nueva se
    lleva una instancia distinta, asi que dos casillas con el mismo item
    tienen ids diferentes. Hay que llevar el mapa casilla -> instancia.
    """
    for ranura, inst in (instancias or {}).items():
        if bytes(inst)[:8] == instancia[:8]:
            return int(ranura)
    # Respaldo: la derivacion vieja, instancia_de(char_id, item_id).
    #
    # La secuencia de entrada al mundo manda el inventario SIN instancias, y
    # entonces cada entrada cae en esa derivacion. El cliente se queda con
    # esos ocho bytes y los devuelve al vender, mientras que aqui se buscaba
    # solo en el mapa de instancias nuevas: no casaba ninguna y no se vendia
    # nada. Se reconocio comparando: el cliente mandaba ...5af6ad6a y
    # instancia_de(char, 2) termina exactamente en 5af6ad6a.
    if bolsa and char_id:
        for ranura, item_id in bolsa.items():
            if instancia_de(char_id, int(item_id)) == instancia[:8]:
                return int(ranura)
    return None


def es_equipo(ranura) -> bool:
    """Si esa ranura es del personaje (equipo regular 1..19 o Fashion 167..174) y no de la mochila."""
    try:
        r = int(ranura)
    except (ValueError, TypeError):
        return False
    return (r < PRIMERA_RANURA_BOLSA) or (167 <= r <= 174)


def es_fashion(ranura) -> bool:
    """Si esa ranura corresponde a la pestaña de Fashion (167..174)."""
    try:
        r = int(ranura)
    except (ValueError, TypeError):
        return False
    return 167 <= r <= 174



def _plantillas():
    global _P
    if _P is None:
        _P = json.loads(PLANTILLA.read_text(encoding='utf-8'))
    return _P


def instancia_de(char_id: int, ranura_item: int) -> bytes:
    """Id de instancia de un item. Cada item que existe tiene el suyo.

    El servidor real usa 8 bytes que no sabemos como genera; lo unico que
    importa es que sea estable para un mismo item, porque el cliente lo usa
    para seguirle el rastro mientras se mueve. Se deriva de char_id y del
    item para que no cambie entre sesiones.
    """
    return struct.pack('<II', (char_id * 2654435761) & 0xFFFFFFFF,
                       (ranura_item * 40503 + 0x6AACB9EC) & 0xFFFFFFFF)


def movimiento(origen: int, destino: int, char_id: int, item_id: int,
               instancia: bytes) -> bytes:
    """Sub-mensaje 0x001B que describe mover un item de una ranura a otra."""
    p = _plantillas()
    sube = origen < destino
    caso = 'asc' if sube else 'desc'
    b = bytearray(bytes.fromhex(p[caso]))
    o = p['campos'][caso]
    struct.pack_into('<I', b, o['char1'], char_id)
    struct.pack_into('<H', b, o['ran1'], origen)
    b[o['inst']:o['inst'] + 8] = instancia[:8].ljust(8, b'\x00')
    struct.pack_into('<I', b, o['item'], item_id)
    struct.pack_into('<I', b, o['char2'], char_id)
    struct.pack_into('<H', b, o['ran2'], destino)
    # La durabilidad va tambien aqui. Sin esto, al mover un arma el cliente
    # la recibia con 0 y la mostraba rota en el acto, aunque siguiera
    # pegando igual: el dano lo calcula el servidor y la barra es cosa del
    # cliente. Va en el mismo sitio relativo que en el 0x001A, +45 del
    # bloque del item.
    if 'dur' in o:
        struct.pack_into('<I', b, o['dur'], durabilidad(item_id))
    if es_mascota(item_id):
        nombres_elfos = {3396: b"Water Elf\x00", 3397: b"Fire Elf\x00", 3398: b"Wind Elf\x00", 3399: b"Earth Elf\x00"}
        nom_pet = nombres_elfos.get(item_id, b"Pet\x00")
        it_pos = o['item']
        b[it_pos + 4:it_pos + 4 + len(nom_pet)] = nom_pet
    return struct.pack('<H', 0x001B) + bytes(b)


def _bonus(item_id: int) -> dict:
    """Lo que suma un item, leido de item.xml."""
    global _BON
    if _BON is None:
        import sqlite3
        db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
        _BON = {}
        if db.exists():
            con = sqlite3.connect(db)
            _filas_b = []
            for _t in TABLAS_ITEM:
                try:
                    cols = [r[1] for r in con.execute('pragma table_info(%s)' % _t)]
                    has_hp = 'hp' in cols
                    has_mp = 'mp' in cols
                    hp_col = 'hp' if has_hp else '0'
                    mp_col = 'mp' if has_mp else '0'
                    _filas_b += list(con.execute(
                        f"select id, def, accuracy, agility, atk_avg, matk, mdef, {hp_col}, {mp_col} from {_t} "
                        "where id glob '[0-9]*'"))
                except Exception:
                    continue
            for i, d, ac, ag, av, ma, md, _hp, _mp in _filas_b:
                # Algunos valores vienen con decimales en item.xml.
                def _n(x):
                    try:
                        return int(float(x))
                    except (TypeError, ValueError):
                        return 0
                _BON[int(i)] = {'def': _n(d), 'accuracy': _n(ac),
                                'agility': _n(ag), 'atk': _n(av),
                                'matk': _n(ma), 'mdef': _n(md),
                                'hp': _n(_hp), 'mp': _n(_mp)}
    return _BON.get(item_id, {'def': 0, 'accuracy': 0, 'agility': 0, 'atk': 0, 'matk': 0, 'mdef': 0, 'hp': 0, 'mp': 0})


def bonos_de_habilidades(habilidades):
    """Lo que suman las habilidades: vida, mana, carga, barras de SP y stats.

    OJO: esta tabla esta escrita a mano, no sale de los datos del cliente.
    En `content.db` no hay ninguna tabla de habilidades -- la tabla `level`
    solo trae la experiencia que pide cada nivel de cada rama -- asi que
    estos numeros no estan verificados contra nada. El HP no lo da el arma
    (Sword no sube vida, cura): lo dan las pasivas, Enhance y Grapple.

    Se saco de dentro de stats() porque el tope de vida hacia falta en dos
    sitios y solo se calculaba en uno: el 0x0042 mandaba el maximo CON el
    bono y la ficha 0x0002 lo mandaba sin el. La ID Card decia 529/529
    mientras el HUD decia 529/1009, y como el servidor se quedaba con el
    529 se creia lleno y las pociones no curaban nada hasta que te pegaban.
    """
    base_atk = 7
    base_def = 6
    base_rigor = 7
    base_agi = 6
    base_matk = 5
    base_mdef = 5
    base_crit = 5
    crit_eff = 5
    load_max = 2000
    sp_max_bars = 2

    hp_bonus = 0
    mp_bonus = 0
    sk_atk = 0
    sk_def = 0
    sk_rigor = 0
    sk_agi = 0
    sk_matk = 0
    sk_mdef = 0

    if habilidades:
        for h in habilidades:
            sid = h[0] if isinstance(h, (list, tuple)) else h
            slv = h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else 1
            extra = max(0, slv - 1)

            if sid == 9:      # Sword: +4 atk base, +1 atk y +1 rigor por nivel arriba de 1
                sk_atk += 4 + extra
                sk_rigor += extra
            elif sid == 10:   # Axe: +4 atk base, +1 atk por nivel, +8 rigor cada 10 niveles
                sk_atk += 4 + extra
                sk_rigor += 8 * (slv // 10)
            elif sid == 11:   # Spear: +4 atk base, +1 atk por nivel, +8 rigor cada 10 niveles
                sk_atk += 4 + extra
                sk_rigor += 8 * (slv // 10)
            elif sid == 12:   # Enhance: +2 def base, +24 hp (con=2), +1 def y +12 hp por nivel
                sk_def += 2 + extra
                hp_bonus += extra * 12
            elif sid == 13:   # Grapple: +4 rigor base, +1 atk, +1 rigor y +12 hp por nivel
                sk_rigor += 4 + extra
                sk_atk += extra
                hp_bonus += extra * 12
            elif sid == 14:   # Shield: +4 def base, +3 def por nivel
                sk_def += 4 + extra * 3
            elif sid == 15:   # Reserve: +2 atk base, +1 atk por nivel, +1 barra SP cada 25 niveles
                sk_atk += 2 + extra
                sp_max_bars += (slv // 25)
            elif sid == 16:   # Finesse: +4 agi base, +1 agi por nivel
                sk_agi += 4 + extra
            elif sid == 17:   # Longbow: +4 atk base, +1 atk por nivel, +8 rigor cada 10 niveles
                sk_atk += 4 + extra
                sk_rigor += 8 * (slv // 10)
            elif sid == 18:   # Snipe: +2 atk base, +1 atk por nivel
                sk_atk += 2 + extra
            elif sid == 19:   # Eagle Eye: +2 rigor, +2 agi base, +1 rigor y +1 agi por nivel
                sk_rigor += 2 + extra
                sk_agi += 2 + extra
            elif sid == 32:   # Mantle: +3 def, +1 agi, +60 carga
                sk_def += 3
                sk_agi += 1
                load_max += 60 + extra * 60
            elif sid == 33:   # Garment: +4 def, +72 carga
                sk_def += 4
                load_max += 72 + extra * 72
            elif sid == 34:   # Vestment: +2 def, +2 mdef, +48 carga
                sk_def += 2
                sk_mdef += 2
                load_max += 48 + extra * 48
            elif sid in (20, 21, 22, 23): # Collect, Fishing, Dig, Lumber: +2 atk
                sk_atk += 2
            elif sid in (1, 2, 3, 4):     # Magic elemental: +4 matk
                sk_matk += 4
            elif sid == 5:    # Curse: +2 matk, +1 matk por nivel
                sk_matk += 2 + extra
            elif sid == 6:    # Meditate: +2 mdef, +30 mp, +1 mdef y +15 mp por nivel
                sk_mdef += 2 + extra
                mp_bonus += 30 + extra * 15
            elif sid == 7:    # Hit: +2 matk, +1 matk y +5 mp por nivel
                sk_matk += 2 + extra
                mp_bonus += extra * 5
            elif sid == 8:    # Staff Hit: +2 atk, +1 matk, +1 mdef base, +1 atk/matk/rigor por nivel
                sk_atk += 2 + extra
                sk_matk += 1 + extra
                sk_mdef += 1
                sk_rigor += extra

    return {
        'atk': sk_atk, 'def': sk_def, 'rigor': sk_rigor, 'agi': sk_agi,
        'matk': sk_matk, 'mdef': sk_mdef,
        'hp': hp_bonus, 'mp': mp_bonus,
        'carga': load_max, 'barras_sp': sp_max_bars,
    }


def bonos_de_equipo(bolsa) -> dict:
    """Calcula la suma de atributos que otorgan los items equipados en la bolsa (Gear 1..10 y Fashion 167..174)."""
    eq = {'def': 0, 'accuracy': 0, 'agility': 0, 'atk_r': 0, 'atk_l': 0, 'matk': 0, 'mdef': 0, 'hp': 0, 'mp': 0}
    if not bolsa:
        return eq

    r_weap_atk = 0
    l_weap_atk = 0
    gen_atk = 0

    for ranura, item_id in bolsa.items():
        try:
            r = int(ranura)
            iid = int(item_id)
        except (ValueError, TypeError):
            continue
        if not es_equipo(r) or r == RANURA_ORO:
            continue
        x = _bonus(iid)
        eq['def'] += x.get('def', 0)
        eq['accuracy'] += x.get('accuracy', 0)
        eq['agility'] += x.get('agility', 0)
        eq['matk'] += x.get('matk', 0)
        eq['mdef'] += x.get('mdef', 0)
        eq['hp'] += x.get('hp', 0)
        eq['mp'] += x.get('mp', 0)

        item_atk = x.get('atk', 0)

        if r == RANURA_DERECHA: # 3 (Arma Gear mano derecha)
            r_weap_atk += item_atk + x.get('accuracy', 0)
        elif r == RANURA_IZQUIERDA: # 4 (Escudo / Arma Gear mano izquierda)
            l_weap_atk += item_atk + x.get('accuracy', 0)
        elif r == 169: # Arma Fashion (derecha / principal)
            r_weap_atk += item_atk
            if es_arma_dual(iid):
                l_weap_atk += item_atk
        elif r == 170: # Arma/Escudo Fashion (izquierda)
            l_weap_atk += item_atk
        else:
            # Armaduras Gear (1, 2, 5, 6, 7, 8) y Prendas Fashion (167, 168, 171, 172, 173)
            # Si dan ataque, se suma a AMBOS (R.Atk y L.Atk)
            gen_atk += item_atk

    eq['atk_r'] = r_weap_atk + gen_atk
    eq['atk_l'] = l_weap_atk + gen_atk
    return eq


def vida_maxima(hp_max, habilidades, bolsa=None):
    """El tope de vida de verdad: el guardado mas lo que dan las pasivas y el equipo."""
    eq_hp = bonos_de_equipo(bolsa)['hp'] if bolsa else 0
    return int(hp_max or 0) + bonos_de_habilidades(habilidades)['hp'] + eq_hp


def mana_maximo(mp_max, habilidades, bolsa=None):
    """El tope de mana de verdad: el guardado mas lo que dan las pasivas y el equipo."""
    eq_mp = bonos_de_equipo(bolsa)['mp'] if bolsa else 0
    return int(mp_max or 0) + bonos_de_habilidades(habilidades)['mp'] + eq_mp


_RESIDENT_MAGIC_CACHE = {}
_MAGIC_DATA_CACHE = {}


def resident_magic_de(item_id: int):
    """Devuelve el magic_id de la magia residente (常駐法術) de un item, o None."""
    global _RESIDENT_MAGIC_CACHE
    if not item_id:
        return None
    try:
        iid = int(item_id)
    except (ValueError, TypeError):
        return None
    if iid in _RESIDENT_MAGIC_CACHE:
        return _RESIDENT_MAGIC_CACHE[iid]
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return None
    mid = None
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        for t in ['item', 'item2', 'item3', 'item4', 'item5', 'item6', 'item7', 'item8', 'item9']:
            cur.execute(f'PRAGMA table_info({t})')
            cols = [c[1] for c in cur.fetchall()]
            col_res = next((c for c in cols if '常駐' in c), None)
            if col_res:
                row = cur.execute(f'SELECT "{col_res}" FROM {t} WHERE id=?', (str(iid),)).fetchone()
                if row and row[0]:
                    try:
                        mid = int(row[0])
                        break
                    except ValueError:
                        pass
    except Exception:
        pass
    _RESIDENT_MAGIC_CACHE[iid] = mid
    return mid


def datos_magia_residente(magic_id: int) -> dict:
    """Devuelve los atributos numericos (% dano, % mitigacion, prioridades) de un magic_id."""
    global _MAGIC_DATA_CACHE
    if not magic_id:
        return {}
    try:
        mid = int(magic_id)
    except (ValueError, TypeError):
        return {}
    if mid in _MAGIC_DATA_CACHE:
        return _MAGIC_DATA_CACHE[mid]
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    res = {}
    if db.exists():
        try:
            con = sqlite3.connect(db)
            cur = con.cursor()
            cur.execute('PRAGMA table_info(magic)')
            cols = [c[1] for c in cur.fetchall()]
            row = cur.execute('SELECT * FROM magic WHERE id=?', (str(mid),)).fetchone()
            if row:
                d = dict(zip(cols, row))
                def _to_int(k):
                    val = d.get(k)
                    if val is not None and str(val).isdigit():
                        return int(val)
                    return 0
                res = {
                    'id': mid,
                    'name': d.get('name', ''),
                    'high_pri': _to_int('高權位'),
                    'low_pri': _to_int('低權位'),
                    'mag_dmg': _to_int('魔法傷害'),
                    'phys_dmg': _to_int('物理傷害'),
                    'phys_mit': _to_int('物理傷害抵銷'),
                    'mag_mit': _to_int('魔法傷害抵銷'),
                    'res_ice': _to_int('res_ice'),
                    'res_fire': _to_int('res_fire'),
                    'res_elec': _to_int('res_elec'),
                    'res_poison': _to_int('res_poison'),
                }
        except Exception:
            pass
    _MAGIC_DATA_CACHE[mid] = res
    return res


def modificadores_porcentuales_equipo(bolsa) -> dict:
    """Calcula los modificadores porcentuales activos segun los items equipados en la bolsa.
    Aplica la regla de no acumulacion ('Cannot be stacked with similar effects'):
    - Si dos o mas items tienen el mismo grupo de prioridad (high_pri / 高權位),
      prevalece el mayor.
    - Entre fuentes distintas, las mitigaciones se calculan de manera compuesta multiplicativa.
    """
    res = {
        'mag_dmg_pct': 0,     # % extra a daño magico (+30% etc)
        'phys_dmg_pct': 0,    # % extra a daño fisico (+14% etc)
        'phys_mit_pct': 0,    # % total de mitigacion de daño fisico
        'mag_mit_pct': 0,     # % total de mitigacion de daño magico
        'phys_mit_mult': 1.0, # Multiplicador de dano fisico recibido (ej 0.7695)
        'mag_mit_mult': 1.0,  # Multiplicador de dano magico recibido (ej 0.81)
        'res_ice': 0,
        'res_fire': 0,
        'res_elec': 0,
        'res_poison': 0,
    }
    if not bolsa:
        return res

    grupos = {}
    for ranura, item_id in bolsa.items():
        if not es_equipo(ranura) or ranura == RANURA_ORO:
            continue
        try:
            iid = int(item_id)
        except (ValueError, TypeError):
            continue
        mid = resident_magic_de(iid)
        if not mid:
            continue
        md = datos_magia_residente(mid)
        if not md:
            continue

        hpri = md.get('high_pri') or mid
        if hpri not in grupos:
            grupos[hpri] = {
                'mag_dmg': 0, 'phys_dmg': 0,
                'phys_mit': 0, 'mag_mit': 0,
                'res_ice': 0, 'res_fire': 0, 'res_elec': 0, 'res_poison': 0
            }
        for k in ['mag_dmg', 'phys_dmg', 'phys_mit', 'mag_mit', 'res_ice', 'res_fire', 'res_elec', 'res_poison']:
            grupos[hpri][k] = max(grupos[hpri][k], md.get(k, 0))

    mult_phys = 1.0
    mult_mag = 1.0

    for g in grupos.values():
        res['mag_dmg_pct'] += g['mag_dmg']
        res['phys_dmg_pct'] += g['phys_dmg']
        res['res_ice'] += g['res_ice']
        res['res_fire'] += g['res_fire']
        res['res_elec'] += g['res_elec']
        res['res_poison'] += g['res_poison']

        if g['phys_mit'] > 0:
            mult_phys *= (1.0 - min(0.95, g['phys_mit'] / 100.0))
        if g['mag_mit'] > 0:
            mult_mag *= (1.0 - min(0.95, g['mag_mit'] / 100.0))

    res['phys_mit_mult'] = max(0.05, mult_phys)
    res['mag_mit_mult'] = max(0.05, mult_mag)
    res['phys_mit_pct'] = int(round((1.0 - res['phys_mit_mult']) * 100.0))
    res['mag_mit_pct'] = int(round((1.0 - res['mag_mit_mult']) * 100.0))
    return res



def stats(bolsa=None, habilidades: list = None,
          hp: int = None, hp_max: int = None,
          mp: int = None, mp_max: int = None,
          oro: int = None,
          buffs: dict = None,
          sp: int = None, sp_max: int = None) -> bytes:
    """Sub-mensaje 0x0042 con los stats del personaje segun lo que lleva puesto y habilidades pasivas.

    El array que empieza en +20 alterna valor base y valor efectivo:
        idx 0  ataque base      idx 1  R.Atk     idx 2  L.Atk
        idx 3  defensa base     idx 4  Dfs
        idx 5  Spl Atk base     idx 6  Spl Atk
        idx 7  Spl Dfs base     idx 8  Spl Dfs
        +56    Rigor (Acc) base / eff
        +60    Agility (Dodge) base / eff
        +64    Critical base / eff
        +68    SP bars current / max (1 barra = 1000 puntos)

    El efectivo es el base mas lo que suma cada pieza puesta y los bonus de
    habilidades pasivas segun el nivel de cada habilidad.
    """
    p = _plantillas()
    b = bytearray(bytes.fromhex(p['stats_sin_ropa']))

    _b = bonos_de_habilidades(habilidades)
    base_atk, base_def, base_rigor = 7, 6, 7
    base_agi, base_matk, base_mdef = 6, 5, 5
    base_crit = 5
    crit_eff = 5
    load_max = _b['carga']
    sp_max_bars = _b['barras_sp']
    hp_bonus, mp_bonus = _b['hp'], _b['mp']
    sk_atk, sk_def, sk_rigor = _b['atk'], _b['def'], _b['rigor']
    sk_agi, sk_matk, sk_mdef = _b['agi'], _b['matk'], _b['mdef']

    c_atk_base = base_atk + sk_atk
    c_def_base = base_def + sk_def
    c_rigor_base = base_rigor + sk_rigor
    c_agi_base = base_agi + sk_agi
    c_matk_base = base_matk + sk_matk
    c_mdef_base = base_mdef + sk_mdef

    if sp_max is not None:
        sp_max_bars = max(sp_max_bars, sp_max)
    if sp is not None:
        sp_bars_current = min(sp_max_bars, max(0, sp // 1000))
    else:
        sp_bars_current = sp_max_bars

    eq = bonos_de_equipo(bolsa)
    eq_def = eq['def']
    eq_r_atk = eq['atk_r']
    eq_l_atk = eq['atk_l']
    eq_rigor = eq['accuracy']
    eq_agi = eq['agility']
    eq_load = 0
    eq_matk = eq['matk']
    eq_mdef = eq['mdef']
    eq_hp = eq['hp']
    eq_mp = eq['mp']

    r_atk_eff = c_atk_base + eq_r_atk
    l_atk_eff = c_atk_base + eq_l_atk
    dfs_eff = c_def_base + eq_def
    matk_eff = c_matk_base + eq_matk
    mdef_eff = c_mdef_base + eq_mdef
    rigor_eff = c_rigor_base + eq_rigor
    agi_eff = c_agi_base + eq_agi

    hp_eff = hp if hp is not None else struct.unpack_from('<I', b, 0)[0]
    hp_max_eff = (hp_max + hp_bonus + eq_hp) if hp_max is not None else (struct.unpack_from('<I', b, 4)[0] + hp_bonus + eq_hp)
    mp_eff = mp if mp is not None else struct.unpack_from('<I', b, 8)[0]
    mp_max_eff = (mp_max + mp_bonus + eq_mp) if mp_max is not None else (struct.unpack_from('<I', b, 12)[0] + mp_bonus + eq_mp)

    if buffs:
        now = time.time()
        for b_id, b_data in buffs.items():
            if isinstance(b_data, dict) and b_data.get('fin', 0) > now:
                if 'crit' in b_data:
                    crit_eff += b_data['crit']
                if 'def' in b_data:
                    dfs_eff += b_data['def']
                if 'atk' in b_data:
                    r_atk_eff += b_data['atk']
                    l_atk_eff += b_data['atk']
                if 'matk' in b_data:
                    matk_eff += b_data['matk']
                if 'mdef' in b_data:
                    mdef_eff += b_data['mdef']
                if 'hp' in b_data:
                    hp_max_eff += b_data['hp']
                if 'mp' in b_data:
                    mp_max_eff += b_data['mp']

    struct.pack_into('<I', b, 0, hp_eff)
    struct.pack_into('<I', b, 4, hp_max_eff)
    struct.pack_into('<I', b, 8, mp_eff)
    struct.pack_into('<I', b, 12, mp_max_eff)
    struct.pack_into('<HH', b, 16, eq_load, load_max)
    struct.pack_into('<I', b, 20, c_atk_base)
    struct.pack_into('<I', b, 24, r_atk_eff)
    struct.pack_into('<I', b, 28, l_atk_eff)
    struct.pack_into('<I', b, 32, c_def_base)
    struct.pack_into('<I', b, 36, dfs_eff)
    struct.pack_into('<I', b, 40, c_matk_base)
    struct.pack_into('<I', b, 44, matk_eff)
    struct.pack_into('<I', b, 48, c_mdef_base)
    struct.pack_into('<I', b, 52, mdef_eff)
    struct.pack_into('<HH', b, 56, c_rigor_base, rigor_eff)
    struct.pack_into('<HH', b, 60, c_agi_base, agi_eff)
    struct.pack_into('<HH', b, 64, base_crit, crit_eff)
    struct.pack_into('<HH', b, 68, sp_bars_current, sp_max_bars)
    # Peso. El orden no es el que parecia: en la captura de Celestia los
    # offsets 92 y 96 llevan los dos el tope y el 100 lleva lo que se carga
    # ahora (sube de a uno segun se recoge botin). Antes escribiamos el oro
    # en el 100 y el cliente lo leia como peso, por eso la barra aparecia
    # llena. El oro no va aqui: viaja en la ranura 0 del inventario.
    tope = max(1, load_max)
    struct.pack_into('<III', b, 92, tope, tope, min(peso_total(bolsa), 0xFFFFFFFF))

    return struct.pack('<H', 0x0042) + bytes(b)


def dfs(sub: bytes) -> int:
    """El quinto stat del 0x0042, que el cliente muestra como Dfs."""
    return struct.unpack_from('<I', sub, 2 + 20 + 16)[0]


# --------------------------------------------------------------- 0x001A
# El inventario COMPLETO, que el servidor manda al entrar al mundo. Es el
# mensaje que permite ENTREGAR items; el 0x001B solo los mueve.
#
#     +0   LE32  CUANTAS ENTRADAS VIENEN
#     +4   las entradas, uno detras de otro, de tamano variable
#
# Cada entrada:
#     +0   U8    01
#     +1   8 B   id de instancia
#     +9   LE32  item_id
#     +33  U8    01
#     +34  LE32  char_id
#     +38  LE16  ranura
#     +40  LE32  cantidad
#
# Un item corriente ocupa 86 bytes y uno equipable 119, treinta y tres mas.
# No hay cola.
#
# Comprobado con los dos inventarios capturados:
#     2 items:  4 + 86 + 119                 = 209
#     8 items:  4 + 86 + 119*5 + 86*2        = 857
#
# Aqui se equivoco el primer intento: se tomo la cabecera por un "id de
# contenedor" porque valia 2 y habia dos items, y se dieron todas las entradas
# por iguales de 86 bytes, con lo que los 33 bytes de mas de la prenda pasaron
# por ser una cola del mensaje. Con dos items las cuentas cuadraban igual. Al
# entregar cinco, el cliente dejo de leer donde no debia y quedaron ranuras
# vacias en pantalla que el servidor creia ocupadas.

PLANTILLA_INI = pathlib.Path(__file__).parent / 'plantillas' / 'inventario_inicial.json'
RANURA_ORO = 0
ITEM_ORO = 1
RANURA_DERECHA = 3
RANURA_IZQUIERDA = 4
_BON = None
# Un item se lleva puesto si item.xml le marca alguna ranura de equipo. Antes
# se miraba la CATEGORIA contra una lista escrita a mano y se quedaba corta:
# Stick, Spear, Catapult, Cask y Sharp Knife no estaban, el tamano de sus
# entradas salia mal y el mensaje entero se desalineaba.
COLUMNAS_EQUIPO = ('右手裝備', '左手裝備', '頭部裝備', '飾品裝備', '身體裝備',
                   '手部裝備', '腳部裝備', '背部裝備', '寵物座騎裝備')
OFF_DURABILIDAD = 45   # dentro de la entrada; en item.xml la columna es 耐久
_PI = None
_CAT = None


def _plantilla_inicial():
    global _PI
    if _PI is None:
        _PI = json.loads(PLANTILLA_INI.read_text(encoding='utf-8'))
    return _PI


def _tabla():
    """{item_id: (se_lleva_puesto, durabilidad_maxima)} desde item.xml."""
    global _CAT
    if _CAT is None:
        import sqlite3
        db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
        _CAT = {}
        if db.exists():
            con = sqlite3.connect(db)
            campos = ','.join(f'"{c}"' for c in COLUMNAS_EQUIPO)
            _filas_e = []
            for _t in TABLAS_ITEM:
                try:
                    _filas_e += list(con.execute(
                        f'select id,"耐久","物品類別",{campos} from {_t} '
                        "where id glob '[0-9]*'"))
                except Exception:
                    continue
            for fila in _filas_e:
                try:
                    d = int(fila[1]) if fila[1] else 0
                except ValueError:
                    d = 0
                es_eq = any(v == '是' for v in fila[3:]) or (fila[2] in ('寵物', '座騎', '紙娃娃', '機甲'))
                _CAT[int(fila[0])] = (es_eq, d, fila[2])
    return _CAT


def categoria_item(item_id: int) -> str:
    """Devuelve la categoria del item desde item.xml (ej. '寵物', '機甲', '座騎')."""
    info = _tabla().get(int(item_id or 0))
    return info[2] if info and len(info) > 2 else ''


def es_equipable(item_id: int) -> bool:
    """Si el item va en alguna de las casillas de equipo (0..10 o 167..174)."""
    if es_mascota(item_id):
        return True
    if ranura_equipo_de(item_id) is not None:
        return True
    return _tabla().get(item_id, (False, 0))[0]


def es_apilable(item_id: int) -> bool:
    """Si el item se puede acumular en una misma casilla (pociones, hojas, galletas, materiales)."""
    if not item_id or es_equipable(item_id):
        return False
    return True


def es_mascota(item_id: int) -> bool:
    """Si el item es una mascota o huevo de mascota (categoria '寵物').
    
    NO confundir con '機甲' (armaduras/partes de robot como Shark Armor 5293)
    ni '座騎' (monturas como Gryphon 21404), que van en la ranura 9/10 pero
    tienen estructura de equipo normal y durabilidad."""
    if item_id in (3396, 3397, 3398, 3399):
        return True
    return categoria_item(item_id) == '寵物'


_SLOT_CACHE = None
_PET_SPRITE_CACHE = {}

def fila_item(con, columnas: str, item_id: int):
    """Busca un item en TODAS las tablas de items, no solo en la primera.

    El cliente reparte sus items en item, item2 ... item9, una por update.
    Consultando solo `item`, cualquier cosa de un update posterior quedaba
    como si no existiera: sin ranura, sin peso y sin bonos.
    """
    for tabla in TABLAS_ITEM:
        try:
            fila = con.execute(
                'select %s from %s where id=?' % (columnas, tabla),
                (str(item_id),)).fetchone()
        except Exception:
            continue
        if fila:
            return fila
    return None


_VEL_MONTURA = {}


def velocidad_de_montura(item_id: int) -> int:
    """El move_speed de una montura, en por ciento, o 0 si no lo es.

    Medido en Celestia quitando y poniendo la montura al mismo personaje: a
    pie 122, con la Earthy Piglet 226 y con la 40441 212. Las DOS declaran
    move_speed=60, asi que con esta columna sola no salen esos numeros: lo que
    aporta una montura depende de su propia instancia -- son mascotas con
    nivel --, y eso no viaja en item.xml. Se usa el porcentaje porque es lo
    unico que los datos del cliente sostienen; ver la nota de app.py.
    """
    if item_id in _VEL_MONTURA:
        return _VEL_MONTURA[item_id]
    v = 0
    if ranura_equipo_de(item_id) in (10, 174):
        import sqlite3
        db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
        if db.exists():
            try:
                con = sqlite3.connect(db)
                fila = fila_item(con, 'move_speed', item_id)
                if fila and fila[0]:
                    v = int(float(fila[0]))
            except Exception:
                v = 0
    _VEL_MONTURA[item_id] = v
    return v


_DUAL_CACHE = {}
_FASHION_CACHE = {}


def es_item_fashion(item_id: int) -> bool:
    """Si el item pertenece a la categoria Fashion / Paper Doll (167..174)."""
    ranura_equipo_de(item_id)
    return _FASHION_CACHE.get(item_id, False)


def es_arma_dual(item_id: int) -> bool:
    """Si el arma se puede equipar en ambas manos (derecha e izquierda)."""
    ranura_equipo_de(item_id)
    return _DUAL_CACHE.get(item_id, False)


def es_ranura_valida(item_id: int, ranura: int) -> bool:
    """Verifica si un item puede colocarse en esa ranura especifica para evitar pisar armadura real con fashion."""
    if ranura >= PRIMERA_RANURA_BOLSA: # >= 20 (mochila siempre valida)
        return True
    target = ranura_equipo_de(item_id)
    if target is None:
        return False
    # Pestaña Fashion (167..174):
    if es_fashion(ranura):
        if not es_item_fashion(item_id):
            return False
        if target == 169 and ranura in (169, 170) and es_arma_dual(item_id):
            return True
        return ranura == target
    # Pestaña Gear regular (1..10):
    else:
        if es_item_fashion(item_id):
            return False # Un item de Fashion NUNCA va en la pestaña de Gear!
        if target == 3 and ranura in (3, 4) and not es_arma_dos_manos(item_id):
            return True
        return ranura == target


def ranura_equipo_de(item_id: int):
    """Devuelve la ranura de equipamiento donde se coloca el item, o None si no es equipable."""
    global _SLOT_CACHE, _DUAL_CACHE, _FASHION_CACHE
    if _SLOT_CACHE is None:
        import sqlite3
        db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
        _SLOT_CACHE = {}
        _DUAL_CACHE = {}
        _FASHION_CACHE = {}
        if db.exists():
            con = sqlite3.connect(db)
            campos = ','.join(f'"{c}"' for c in COLUMNAS_EQUIPO)
            # Los items estan repartidos en item, item2 ... item9, una por
            # update del cliente. Mirando solo la primera, todo lo que vino
            # en un update posterior quedaba sin ranura y no se podia
            # equipar: la montura Galactic Moped, por ejemplo, vive en item5.
            filas = []
            for _tabla in ('item', 'item2', 'item3', 'item4', 'item5',
                           'item6', 'item7', 'item8', 'item9'):
                try:
                    filas += list(con.execute(
                        f'select id,"物品類別",{campos} from {_tabla} '
                        "where id glob '[0-9]*'"))
                except Exception:
                    continue
            for fila in filas:
                iid = int(fila[0])
                cat = fila[1]
                rhand, lhand, head, acc, body, hands, feet, back, pet = [v == '是' for v in fila[2:]]
                if rhand and lhand:
                    _DUAL_CACHE[iid] = True
                if cat == '紙娃娃':
                    _FASHION_CACHE[iid] = True
                    # Items de Fashion (Paper Doll) se equipan en las ranuras de la pestaña Fashion (167..174)
                    if head:
                        _SLOT_CACHE[iid] = 167
                    elif body:
                        _SLOT_CACHE[iid] = 168
                    elif rhand:
                        _SLOT_CACHE[iid] = 169
                    elif lhand:
                        _SLOT_CACHE[iid] = 170
                    elif hands:
                        _SLOT_CACHE[iid] = 171
                    elif feet:
                        _SLOT_CACHE[iid] = 172
                    elif back:
                        _SLOT_CACHE[iid] = 173
                    elif pet or cat == '座騎':
                        _SLOT_CACHE[iid] = 174
                elif cat == '座騎':
                    _SLOT_CACHE[iid] = 10
                elif cat == '寵物' or (pet and not (body or head or hands or feet or back or rhand or lhand)):
                    _SLOT_CACHE[iid] = 9
                elif rhand:
                    _SLOT_CACHE[iid] = 3
                elif lhand:
                    _SLOT_CACHE[iid] = 4
                elif body:
                    _SLOT_CACHE[iid] = 2
                elif head:
                    _SLOT_CACHE[iid] = 1
                elif hands:
                    _SLOT_CACHE[iid] = 5
                elif feet:
                    _SLOT_CACHE[iid] = 6
                elif back:
                    _SLOT_CACHE[iid] = 7
                elif acc:
                    _SLOT_CACHE[iid] = 8
    return _SLOT_CACHE.get(item_id)

_TWO_HAND_CACHE = {}

def es_arma_dos_manos(item_id: int) -> bool:
    """Si el arma requiere ambas manos (Lanza, Arco, etc.)."""
    global _TWO_HAND_CACHE
    if not item_id:
        return False
    if item_id in _TWO_HAND_CACHE:
        return _TWO_HAND_CACHE[item_id]
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    res = False
    if db.exists():
        try:
            con = sqlite3.connect(db)
            row = fila_item(con, '"物品類別"', item_id)
            if row and row[0]:
                cat = str(row[0])
                res = any(k in cat for k in ('槍', '弓', '雙手'))
        except Exception:
            pass
    _TWO_HAND_CACHE[item_id] = res
    return res



def sprite_de_mascota(item_id: int) -> int:
    """Devuelve el ID de sprite (圖號1) de la mascota/huevo para invocarla."""
    global _PET_SPRITE_CACHE
    if item_id in _PET_SPRITE_CACHE:
        return _PET_SPRITE_CACHE[item_id]
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    sprite = 44069   # Default: Fire Elf Egg sprite
    if db.exists():
        try:
            con = sqlite3.connect(db)
            row = fila_item(con, '"動態資料1"', item_id)
            if row and row[0]:
                pet_id = str(row[0]).strip()
                import xml.etree.ElementTree as ET
                p_xml = pathlib.Path('f:/Ao Proyect/AO/data/game_xml/setting_full/setting/eng/pet.xml')
                if p_xml.exists():
                    tree = ET.parse(p_xml)
                    for elem in tree.getroot():
                        if elem.attrib.get('編號') == pet_id:
                            sp = elem.attrib.get('圖號1')
                            if sp and sp.isdigit():
                                sprite = int(sp)
                                break
        except Exception:
            pass
    _PET_SPRITE_CACHE[item_id] = sprite
    return sprite


def es_comida_mascota(item_id: int) -> bool:
    """Si el item es comida o suplemento exclusivo de mascota (Pet Cookies, Pet Can, Pet Feed)."""
    return item_id in (3374, 3375, 3376)


_RECOMPENSAS_CACHE = {}

def recompensas_caja(item_id: int):
    """Si el item es una caja de regalo o bolsa de la suerte (Elf Lucky Bag, Growth Boxes, etc.),
    devuelve lista de (item_id, cantidad) a entregar. Si no, devuelve None."""
    if es_comida_mascota(item_id):
        return None
    import sqlite3, random
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(db)
        row = fila_item(con, '"動態資料1", "物品類別", "基本名稱"', item_id)
        if not row:
            return None
        drop_id = str(row[0]).strip() if row[0] else None
        cat = str(row[1] or '')
        name = str(row[2] or '')

        # Caso especial: Elf Lucky Bag / Elf Egg / 妖精蛋
        # Da una de las 4 mascotas elfos elementales
        if ('elf' in name.lower() and any(k in name.lower() for k in ('bag', 'lucky', 'egg'))) or '妖精' in name:
            mascotas_elfo = [3396, 3397, 3398, 3399]  # Water, Fire, Wind, Earth Elf Egg
            return [(random.choice(mascotas_elfo), 1)]

        # Solo procesar categorias de cajas / bolsas / huevos
        categorias_validas = ('紅包', '扭蛋', '禮物', '禮盒', '寶箱')
        es_bolsa = any(k in name.lower() for k in ('bag', 'lucky', 'egg', 'box', 'gift', 'chest', 'package', 'combine', 'set')) or cat in categorias_validas or any(k in name for k in ('福袋', '禮包', '蛋'))
        if not es_bolsa or not drop_id:
            return None

        dt = con.execute('select * from drop_table where id=?', (drop_id,)).fetchone()
        if not dt:
            return None
        cols = [c[1] for c in con.execute('pragma table_info(drop_table)').fetchall()]
        row_dict = dict(zip(cols, dt))
        rewards = []
        for i in range(1, 21):
            it = row_dict.get(f'item{i}')
            cnt = row_dict.get(f'count{i}')
            if it and str(it).strip() and str(it).isdigit():
                rewards.append((int(it), int(cnt) if cnt and str(cnt).isdigit() else 1))
        if not rewards:
            return None

        # Si incluye mascotas elfo, dar una de las 4 mascotas elfo
        mascotas_elfo = [3396, 3397, 3398, 3399]
        if any(r[0] in mascotas_elfo for r in rewards):
            return [(random.choice(mascotas_elfo), 1)]

        # Lucky Bags / Red Envelopes / Eggs dan 1 item aleatorio
        if cat in ('紅包', '扭蛋') or any(k in name.lower() for k in ('lucky', 'bag', 'egg')) or any(k in name for k in ('福袋', '蛋')):
            return [random.choice(rewards)]

        # Cajas de regalo (Growth Boxes, Combines, Sets) dan todo el contenido
        return rewards
    except Exception:
        return None


def durabilidad(item_id: int) -> int:
    """Durabilidad maxima que trae un item nuevo, de item.xml."""
    base = _tabla().get(item_id, (False, 0))[1]
    if not base:
        if es_mascota(item_id):
            return 100
        return 0
    import os
    try:
        factor = float(os.environ.get('AO_DURABILIDAD', '1'))
    except ValueError:
        factor = 1.0
    return max(0, min(int(base * factor), 0xFFFFFFFF))


def _entrada(char_id: int, ranura: int, item_id: int, cant: int,
             inst: bytes = None, dueno: int = None) -> bytes:
    """Los bytes que describen lo que hay en una casilla.

    Son 86 para lo que no se equipa y 119 para lo que si. 'dueno' es la
    ENTIDAD del personaje, no su char_id: en la captura los dos numeros son
    distintos (286 y 282) y el que viaja aqui es el de la entidad. Si no se
    pasa se usa el char_id, que es lo que se hacia antes.
    """
    if dueno is None:
        dueno = char_id
    p = _plantilla_inicial()
    es_eq = es_equipable(item_id)
    e = bytearray(bytes.fromhex(p['equipable'] if es_eq else p['normal']))
    # El cuarto dato es el id de instancia del monton. Si no viene se deriva
    # del item, que es lo que se hacia siempre; pero dos montones del mismo
    # item comparten esa derivacion y el cliente los confunde al venderlos,
    # asi que quien lleve el mapa debe pasarlo.
    e[1:9] = (bytes(inst)[:8] if inst else instancia_de(char_id, item_id))
    struct.pack_into('<I', e, 9, item_id)
    struct.pack_into('<I', e, 34, dueno)
    struct.pack_into('<H', e, 38, ranura)
    struct.pack_into('<I', e, 40, cant)
    if es_mascota(item_id) and not es_eq:
        # Formatear datos de huevo de mascota para que no crashee el tooltip y no se vea muerta
        nombres_elfos = {3396: b"Water Elf\x00", 3397: b"Fire Elf\x00",
                         3398: b"Wind Elf\x00", 3399: b"Earth Elf\x00"}
        nom_pet = nombres_elfos.get(item_id, b"Pet\x00")
        e[13:13 + len(nom_pet)] = nom_pet
        struct.pack_into('<I', e, OFF_DURABILIDAD, 100)
        struct.pack_into('<I', e, OFF_DURABILIDAD + 4, 100)
        struct.pack_into('<I', e, OFF_DURABILIDAD + 8, 100)
        struct.pack_into('<I', e, OFF_DURABILIDAD + 12, 1)
    else:
        struct.pack_into('<I', e, OFF_DURABILIDAD, durabilidad(item_id))
    if es_eq:
        # Donde esta puesta la prenda. Comparando el mismo NewbieHeavy
        # Costume en la mochila y en el cuerpo, lo unico que cambia ademas
        # de la casilla es esto:
        #     off 53  la entidad que la lleva, o cero si esta guardada
        #     off 57  el contenedor: 3 mochila, 2 cuerpo
        # Nosotros dejabamos los dos en cero, asi que el cliente nunca se
        # enteraba de que la prenda estaba PUESTA y seguia dibujando al
        # personaje en ropa interior.
        puesta = es_equipo(ranura)
        struct.pack_into('<I', e, 53, dueno if puesta else 0)
        e[57] = 2 if puesta else 3
        e[58] = 1
        # Offset 51 (0x33) es el campo que le indica al cliente que esta entrada
        # mide 119 bytes (86 + 33 extra). NUNCA debe alterarse en un equipable.
        e[51] = 0x21
        # Y el servidor repite ahi los dieciseis bits bajos del numero de
        # instancia.
        struct.pack_into('<I', e, 84,
                         struct.unpack_from('<I', e, 1)[0] & 0xFFFF)
    return bytes(e)


def completo(char_id: int, items, dueno: int = None) -> bytes:
    """Sub-mensaje 0x001A con todo el inventario.

    items: iterable de (ranura, item_id[, cantidad[, instancia]]).
    """
    lista = []
    for it in sorted(items, key=lambda x: int(x[0])):
        lista.append(_entrada(char_id, int(it[0]), int(it[1]),
                              int(it[2]) if len(it) > 2 else 1,
                              it[3] if len(it) > 3 else None, dueno))
    fuera = struct.pack('<I', len(lista)) + b''.join(lista)
    return struct.pack('<H', 0x001A) + fuera


def almacen(char_id: int, items, dueno: int = None,
            tipo: int = 2) -> bytes:
    """Sub-mensaje 0x004E con el almacen del banco.

    El cuerpo es EL MISMO que el del 0x001A: un LE32 con el numero de
    entradas y detras esas entradas, de 86 bytes las corrientes y 119 las
    equipables. Se comprobo contra la captura de Edo City del 28/09/2026, en
    la que el servidor real contesta 824 bytes al elegir "I wish to use my own
    warehouse": ocho entradas, cuatro de 86 y cuatro de 119, que suman 820
    mas los cuatro de la cabecera.

    Antes se mandaba un 0x002B, que es otro mensaje: el cliente no abria nada
    y soltaba un aviso de la lista de amigos.

    El LE32 de la cabecera NO es solo la cuenta: lleva el tipo multiplicado
    por mil y la cuenta en las unidades. Las dos funciones del cliente que
    crean la ventana del banco -- las dos llaman a CreateBankWnd -- hacen
    `tipo = n / 1000` y `cuenta = n % 1000`, y solo abren cuando el tipo es 2
    o 3. Con tipo 0 rellenan la lista y nada mas.

    Por eso va TIPO 2. Mandandolo como cuenta pelada la ventana no se abria,
    ni vacia ni con un objeto dentro. En la captura del servidor real ese
    numero valia 8, o sea tipo 0: ahi la ventana ya debia estar creada por
    otro camino que no se ha llegado a ver.
    """
    lista = []
    for it in sorted(items, key=lambda x: int(x[0])):
        lista.append(entrada_banco(char_id, int(it[0]), int(it[1]),
                                   int(it[2]) if len(it) > 2 else 1,
                                   it[3] if len(it) > 3 else None, dueno))
    return (struct.pack('<HI', 0x004E, tipo * 1000 + len(lista))
            + b''.join(lista))


def banco_vaciar_ranura(ranura: int) -> bytes:
    """Sub-mensaje 0x001B que dice que una casilla del banco quedo vacia.

    Medido en la captura de Edo City: al arrastrar dentro del almacen el
    servidor real contesta SIEMPRE dos sub-mensajes, y este es el primero.
    Son doce bytes: la cuenta, un 02 de accion, los cinco del marcador
    02fc000000 que tambien llevan las entradas del almacen, y la casilla que
    se vacia.
    """
    return vaciar_ranura(ID_BANCO, ranura, CONT_BANCO)


def banco_poner(char_id: int, ranura: int, item_id: int, cant: int = 1,
                inst: bytes = None, dueno: int = None) -> bytes:
    """Sub-mensaje 0x001B con lo que queda en una casilla del banco.

    Es el segundo de los dos que contesta el servidor real al mover: la
    cuenta y detras la entrada, con el mismo formato de 86 o 119 bytes que
    usa el inventario. Los tamanos de la captura cuadran: 90 bytes cuando lo
    movido no se equipa y 123 cuando si.
    """
    return (struct.pack('<H', 0x001B) + struct.pack('<I', 1)
            + entrada_banco(char_id, ranura, item_id, cant, inst, dueno))


def entrada_banco(char_id: int, ranura: int, item_id: int, cant: int = 1,
                  inst: bytes = None, dueno: int = None) -> bytes:
    """Una entrada del almacen: la del inventario con tres campos cambiados.

    Comparando byte a byte una entrada nuestra con una de la captura, las
    unicas diferencias reales son estas tres (la cuarta es el numero de
    instancia, que el servidor real genera a su manera y nosotros derivamos):

      +33  el contenedor. En la mochila va 01 y la ENTIDAD del personaje; en
           el almacen va 02 y el 252, el mismo par que usa el sub-mensaje que
           vacia una casilla.
      +40  las unidades del monton. Se comprobo con las ocho entradas de la
           captura: 14, 1, 174, 1, 1, 1, 59 y 252, que son las cantidades que
           se ven en la ventana del almacen.
      +84  los dieciseis bits bajos del numero de instancia. En la mochila
           solo los lleva lo equipable; en el almacen los llevan todas.
    """
    return _entrada_marcada(char_id, ranura, item_id, cant, inst, dueno,
                            CONT_BANCO, ID_BANCO)


def entrada_recuperada(char_id: int, ranura: int, item_id: int, cant: int = 1,
                       inst: bytes = None, dueno: int = None) -> bytes:
    """La entrada de lo que vuelve del almacen a la mochila.

    Es una entrada de mochila normal, pero el servidor real le pone las
    unidades en el +40 y el eco de la instancia en el +84, que en las
    entradas corrientes de la bolsa no van. Medido en el 0x001B de 90 bytes
    con el que contesta al sacar algo del banco.
    """
    return _entrada_marcada(char_id, ranura, item_id, cant, inst, dueno,
                            CONT_MOCHILA, dueno if dueno else char_id)


def _entrada_marcada(char_id, ranura, item_id, cant, inst, dueno,
                     contenedor, ident) -> bytes:
    """La entrada de siempre con el contenedor, las unidades y el eco."""
    e = bytearray(_entrada(char_id, ranura, item_id, cant, inst, dueno))
    struct.pack_into('<BI', e, 33, contenedor, ident)
    e[40] = min(int(cant), 255)
    struct.pack_into('<H', e, 84, struct.unpack_from('<H', e, 1)[0])
    return bytes(e)


def banco_sacar(char_id: int, ranura: int, item_id: int, cant: int = 1,
                inst: bytes = None, dueno: int = None) -> bytes:
    """Sub-mensaje 0x001B con lo que llega a la mochila desde el almacen."""
    return (struct.pack('<H', 0x001B) + struct.pack('<I', 1)
            + entrada_recuperada(char_id, ranura, item_id, cant, inst, dueno))


def acuse_movimiento(ranura: int, accion: int = 0x0012) -> bytes:
    """0x0006 s2c: "hecho lo que pediste con esa casilla".

    Medido al equipar: el cliente manda 0x0012 [41][2] y lo primero que le
    llega de vuelta es 0x0006 con 12 00 29 00, o sea el opcode que se
    confirma y la casilla de origen; despues vienen el 0x001B y el 0x0042.
    Sin este acuse el cliente apunta el cambio en el panel de equipo y en
    los stats pero no redibuja al personaje: el equipo queda invisible.
    """
    return struct.pack('<HHH', 0x0006, accion, ranura)


def actualizar_ranuras(char_id: int, entradas, dueno: int = None) -> bytes:
    """0x001B con varias casillas de una vez.

    Es lo que manda el servidor al equipar: en la captura, mover la prenda
    de la casilla 41 al cuerpo devuelve UN 0x001B con dos entradas -- la
    prenda ya en la casilla 2 y la que llevaba puesta de vuelta en la 41 --
    y despues el 0x0042 con los stats. Antes se mandaban dos mensajes de
    movimiento con un formato antiguo que no lleva el estado de puesto.

    entradas: iterable de (ranura, item_id, cantidad, instancia).
    """
    lista = [_entrada(char_id, int(r), int(i), int(c), ins, dueno)
             for r, i, c, ins in entradas]
    return (struct.pack('<HI', 0x001B, len(lista)) + b''.join(lista))


def actualizar_ranura(char_id: int, ranura: int, item_id: int, cant: int,
                      inst: bytes = None, dueno: int = None) -> bytes:
    """0x001B de 90 bytes: como queda UNA casilla.

    Es lo que manda el servidor real despues de comprar, vender, usar o
    separar: una linea por casilla tocada, no el inventario entero. Al
    reenviar el 0x001A completo el cliente se quedaba con lo que ya tenia
    pintado y los items vendidos seguian viendose en la mochila.
    """
    return (struct.pack('<HI', 0x001B, 1)
            + _entrada(char_id, ranura, item_id, cant, inst, dueno))


# ------------------------------------------------- entrega de un item
# Para entregar items se manda cont1 (contenedor 1 = inventario/mochila).
# No se manda cont2 (que movia al equipo ranura 3 y vaciaba la 20).
PLANTILLA_ENTREGA = pathlib.Path(__file__).parent / 'plantillas' / 'entrega_item.json'
_PE = None


def _plantilla_entrega():
    global _PE
    if _PE is None:
        _PE = json.loads(PLANTILLA_ENTREGA.read_text(encoding='utf-8'))
    return _PE


def entregar(char_id: int, item_id: int, ranura: int):
    """Sub-mensaje 0x001B cont1 que mete un item en la mochila del inventario."""
    p = _plantilla_entrega()
    b = bytearray(bytes.fromhex(p['cont1']))
    b[5:13] = instancia_de(char_id, item_id)
    struct.pack_into('<I', b, 13, item_id)
    struct.pack_into('<I', b, 38, char_id)
    struct.pack_into('<H', b, 42, ranura)
    dur = durabilidad(item_id)
    if es_mascota(item_id):
        nombres_elfos = {3396: b"Water Elf\x00", 3397: b"Fire Elf\x00", 3398: b"Wind Elf\x00", 3399: b"Earth Elf\x00"}
        nom_pet = nombres_elfos.get(item_id, b"Pet\x00")
        b[17:17 + len(nom_pet)] = nom_pet
        struct.pack_into('<I', b, 48, 100)
        struct.pack_into('<I', b, 52, 100)
        struct.pack_into('<I', b, 56, 100)
        struct.pack_into('<I', b, 60, 1)
    else:
        struct.pack_into('<I', b, 48, dur)
    return [struct.pack('<H', 0x001B) + bytes(b)]


def efecto_consumible(item_id: int):
    """Devuelve dict con {'hp': X, 'mp': Y} si el item es un consumible/pocion/hierba, o None."""
    import sqlite3, re
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(db)
        row = fila_item(con, '"動態資料1", "常駐法術", "物品類別", "基本名稱", "說明"', item_id)
        if not row:
            return None
        d1, mid, cat, name, desc = str(row[0] or ''), str(row[1] or ''), str(row[2] or ''), str(row[3] or ''), str(row[4] or '')
        # Un pergamino de habilidad, tarjeta, mascota, caja, etc., NUNCA es consumible de HP/MP
        import skills as _sk_check
        if _sk_check.info_pergamino(item_id):
            return None
        if es_advancement_stone(item_id) or es_skill_leveling_stone(item_id):
            return None
        if cat in ('卷軸', '卡片', '寵物', '紅包', '扭蛋', '禮物', '禮盒', '寶箱', '配方', '防禦塔', '訂單', '表情卡', '徽章', '座騎', '強化道具', '紙娃娃'):
            return None

        res = {}
        # 1. Si apunta a un registro en magic.xml via 常駐法術 o 動態資料1
        magic_id = mid if mid and mid.isdigit() else (d1 if d1 and d1.isdigit() else None)
        if magic_id:
            m_row = con.execute('select hp, mp from magic where id=?', (str(magic_id),)).fetchone()
            if m_row:
                if m_row[0] and str(m_row[0]).strip().isdigit() and int(m_row[0]) > 0:
                    res['hp'] = int(m_row[0])
                if m_row[1] and str(m_row[1]).strip().isdigit() and int(m_row[1]) > 0:
                    res['mp'] = int(m_row[1])
        # 2. Si no, parsear descripcion ("restore 40 hp", "increase 50 mp")
        if not res:
            m_mp = re.search(r'(?:increase|restore)\s*(\d+)\s*mp', desc, re.I)
            if m_mp:
                res['mp'] = int(m_mp.group(1))
            m_hp = re.search(r'(?:increase|restore)\s*(\d+)\s*hp', desc, re.I)
            if m_hp:
                res['hp'] = int(m_hp.group(1))
        # 3. Heuristica SOLO para categoria '一般' (pociones / comida comun)
        if not res and d1.isdigit() and int(d1) > 0 and cat in ('一般', ''):
            val = int(d1)
            if 'mp' in name.lower() or 'magic' in name.lower() or 'blue' in name.lower():
                res['mp'] = val
            elif 'hp' in name.lower() or 'red' in name.lower() or 'potion' in name.lower() or 'hierba' in name.lower() or 'biscuit' in name.lower():
                res['hp'] = val
        return res if res else None

    except Exception:
        return None


def es_tarjeta_coleccion(item_id: int) -> bool:
    """Si el item es una tarjeta/card de monstruo coleccionable."""
    import sqlite3
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(db)
        r = fila_item(con, '"物品類別", "基本名稱"', item_id)
        if r:
            return r[0] == '卡片' or 'Card' in str(r[1] or '')
        return False
    except Exception:
        return False


def es_advancement_stone(item_id: int):
    """Devuelve el nivel objetivo si el item es una Advancement Stone, o None."""
    con_nivel = {
        81997: 300,
        71989: 290,
        71987: 280,
        40931: 220,
        40930: 210,
    }
    if item_id in con_nivel:
        return con_nivel[item_id]
    import sqlite3, re
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if db.exists():
        try:
            con = sqlite3.connect(db)
            r = fila_item(con, '"基本名稱"', item_id)
            con.close()
            if r and r[0]:
                m = re.search(r'Lv\s*(\d+)\s+Advancement\s+Stone', str(r[0]), re.I)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    return None


def es_skill_leveling_stone(item_id: int):
    """Devuelve el nivel de habilidad objetivo si es una Skill Leveling Stone, o None."""
    con_skill = {
        81998: 300,
        71990: 290,
        71988: 280,
        52204: 270,
        52203: 260,
        46571: 250,
        48600: 250,
        48453: 240,
        43265: 240,
        43264: 230,
        40933: 220,
        40932: 210,
        72057: 200,
        47204: 180,
        49526: 180,
        53482: 180,
        44042: 170,
        28583: 100,
    }
    if item_id in con_skill:
        return con_skill[item_id]
    import sqlite3, re
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if db.exists():
        try:
            con = sqlite3.connect(db)
            r = fila_item(con, '"基本名稱"', item_id)
            con.close()
            if r and r[0]:
                m = re.search(r'Lv\s*(\d+)\s+Skill\s+Leveling\s+Stone', str(r[0]), re.I)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    return None

# ---------------------------------------------------------------------------
# Creditos de rango
# ---------------------------------------------------------------------------
_INVERSION = None


def creditos_de(item_id: int) -> int:
    """Cuantos creditos de rango da 'invertir' este objeto, o 0 si no da.

    Sale de investitem.xml, que es la lista de los objetos que se entregan a
    cambio de creditos: 103 entradas, de 5 creditos los mas baratos (Obsidian
    Brick, Viburnum Strip) a 200 los mas caros. Algunas entradas traen ademas
    experiencia y otras solo creditos, por eso se lee atributo a atributo y no
    por posicion.

    Ojo con una cosa: el objeto que se vio dar 120.000 creditos de golpe en la
    captura del 28/09/2026 NO esta aqui. Es de un parche posterior al cliente
    del que salieron estos xml, igual que los articulos de las tiendas de Edo
    City.
    """
    global _INVERSION
    if _INVERSION is None:
        _INVERSION = {}
        f = (pathlib.Path(__file__).parent.parent / 'extracted_paks' / 'data1'
             / 'setting' / 'eng' / 'investitem.xml')
        if f.exists():
            txt = f.read_text(encoding='utf-8', errors='replace')
            for trozo in re.findall(r'<投資物品[^>]*>', txt):
                mid = re.search(r'編號="(\d+)"', trozo)
                mcr = re.search(r'功勳="(\d+)"', trozo)
                if mid and mcr:
                    _INVERSION[int(mid.group(1))] = int(mcr.group(1))
    return _INVERSION.get(int(item_id), 0)

