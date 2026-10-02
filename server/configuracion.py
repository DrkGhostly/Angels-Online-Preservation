"""
Configuracion del Servidor y Multiplicadores de Eventos.

Aqui puedes cambiar los multiplicadores de experiencia, habilidades y drops
sin tener que modificar la logica del servidor.
"""
import datetime


# =====================================================================
# MULTIPLICADORES BASE (Valores por defecto del servidor)
# =====================================================================
# 1.0 = Experiencia normal oficial
# 2.0 = Doble experiencia, etc.
TASA_EXP_BASE = 2000.0           # Multiplicador de EXP de personaje
TASA_SKILL_EXP_BASE = 2000.0     # Multiplicador de EXP de habilidades (stamina/skills)
TASA_DROP_BASE = 10.5          # Multiplicador de probabilidad de drop de items
TASA_ORO_BASE = 7.5           # Multiplicador de oro obtenido de monstruos

# =====================================================================
# CONFIGURACION DE EVENTOS DE FIN DE SEMANA / SEMANALES
# =====================================================================
# Si es True, activa automaticamente el bono de fin de semana (Viernes, Sabado y Domingo)
EVENTO_FIN_DE_SEMANA_AUTOMATICO = True

# Si prefieres forzar el evento encendido o apagado manualmente:
# Pon True para forzar evento activo siempre, o False para desactivarlo.
EVENTO_DOBLE_EXP_FORZADO = False

# Multiplicador adicional que se aplica durante el evento
BONUS_EVENTO_EXP = 2.0
BONUS_EVENTO_SKILL = 2.0


def es_fin_de_semana() -> bool:
    """Devuelve True si hoy es viernes (4), sabado (5) o domingo (6)."""
    if EVENTO_DOBLE_EXP_FORZADO:
        return True
    if not EVENTO_FIN_DE_SEMANA_AUTOMATICO:
        return False
    dia = datetime.datetime.now().weekday()
    return dia in (4, 5, 6)


def multiplicador_exp(buffs: dict = None) -> float:
    """Calcula el multiplicador total de EXP de personaje teniendo en cuenta:
    tasa base + evento semanal + buffs o tarjetas de doble EXP activas."""
    m = TASA_EXP_BASE
    if es_fin_de_semana():
        m *= BONUS_EVENTO_EXP
    if buffs and buffs.get('doble_exp'):
        m *= 2.0
    if buffs and buffs.get('triple_exp'):
        m *= 3.0
    return m


def multiplicador_skill_exp(buffs: dict = None) -> float:
    """Calcula el multiplicador total de EXP de habilidades teniendo en cuenta:
    tasa base + evento semanal + cartas de skill exp activas."""
    m = TASA_SKILL_EXP_BASE
    if es_fin_de_semana():
        m *= BONUS_EVENTO_SKILL
    if buffs and buffs.get('doble_skill_exp'):
        m *= 2.0
    return m


def multiplicador_drop() -> float:
    """Calcula el multiplicador total de drops."""
    m = TASA_DROP_BASE
    if es_fin_de_semana():
        m *= 1.5
    return m


# =====================================================================
# MODO PRUEBAS / DEBUG
# =====================================================================
# Si es True, cualquier compra en tiendas NPC cuesta solo 1 de oro por item.
# Si es False, se cobra el precio normal de item.xml.
COMPRAS_1_DE_ORO = True

# Creditos de rango con los que entra el personaje.
#
# La ficha muestra "Credit:" y, encima, el rango: son los nombres 1700 a 1719
# de string.xml, de "Growing Power" a "God's Mouthpiece". En la captura del
# 28/09/2026 el personaje tenia 4.610.115 creditos y la ficha decia "Order
# founder", que es el 1716, o sea el rango 17 contando "Growing Power" como
# el 1.
#
# Los CORTES entre un rango y otro no se han encontrado: no estan en ningun
# xml del cliente ni en los luas, y en la captura no se ve el salto. Por eso
# esto es un numero suelto y no una tabla: se manda el total y es el cliente
# quien decide que rango mostrar. Con 4610115 deberia salir "Order founder".
#
# En cero no se manda nada y la ficha queda como estaba.
CREDITOS_INICIALES = 0

# Objetos con los que empieza el almacen del banco, como {ranura: item_id}.
#
# Esto esta aqui por una duda que no se ha podido resolver leyendo: el paquete
# del almacen (0x004E) lleva el mismo cuerpo que el inventario -- un LE32 con
# el numero de entradas y detras las entradas, de 86 bytes las corrientes y
# 119 las equipables -- y en la captura del servidor real llevaba OCHO. El
# nuestro sale con cero porque el personaje no tiene nada guardado, y la
# ventana no se abre.
#
# Las dos funciones del cliente que crean la ventana del banco solo lo hacen
# cuando el primer LE32 dividido por 1000 vale 2 o 3, pero en la captura vale
# 8, que da 0 por esa cuenta. Asi que la ventana no la abre ese numero: o la
# abre el cliente solo al elegir la opcion del dialogo, y entonces necesita
# tener contenido que mostrar, o hay un camino que todavia no se ha visto.
#
# Con esto se prueba lo primero. Si con un objeto dentro el almacen abre, era
# la lista vacia; en cuanto se sepa, esto sobra y se quita.
ALMACEN_INICIAL = {0: 62}

# =====================================================================
# REGENERACION DE HP Y MP
# =====================================================================
# Antes era plana: +6 MP y +12 HP por tick, vinieran de donde vinieran. A
# nivel bajo se nota, pero a nivel 300, con 121.440 de MP, llenar la barra a
# seis por segundo son CINCO HORAS Y MEDIA.
#
# Ahora es un porcentaje del maximo, y el porcentaje sube con el nivel. Se
# mantiene el minimo plano de antes para que a nivel 1 no regenere menos de
# lo que regeneraba.
#
# De pie hay que llevar dos segundos quieto y fuera de combate; sentado
# (tecla Insert) el tick es cada segundo y el porcentaje mucho mayor.
#
#   por tick = maximo * (base + nivel * por_nivel) / 100
#
# A nivel 1 de pie sale 0,5% cada dos segundos y sentado 2% cada segundo. A
# nivel 300, 2% y 8%: la barra de MP se llena en unos 70 segundos de pie y en
# unos 13 sentado.
REGEN_PIE_BASE = 0.5          # % del maximo, a nivel 1
REGEN_PIE_POR_NIVEL = 0.005   # % que se suma por cada nivel
REGEN_SENTADO_BASE = 2.0
REGEN_SENTADO_POR_NIVEL = 0.02
REGEN_MINIMO_HP_PIE = 6       # los valores planos de antes, como suelo
REGEN_MINIMO_MP_PIE = 6
REGEN_MINIMO_HP_SENTADO = 12
# Sentado el MP tenia el mismo suelo que de pie, seis, asi que a nivel 1
# sentarse no servia de nada para el mana. Se sube a doce, como el HP.
REGEN_MINIMO_MP_SENTADO = 12


def regenera(maximo: int, nivel: int, sentado: bool, es_hp: bool) -> int:
    """Cuanto se recupera en un tick."""
    if sentado:
        pct = REGEN_SENTADO_BASE + nivel * REGEN_SENTADO_POR_NIVEL
        piso = REGEN_MINIMO_HP_SENTADO if es_hp else REGEN_MINIMO_MP_SENTADO
    else:
        pct = REGEN_PIE_BASE + nivel * REGEN_PIE_POR_NIVEL
        piso = REGEN_MINIMO_HP_PIE if es_hp else REGEN_MINIMO_MP_PIE
    return max(piso, int(round(maximo * pct / 100.0)))

# =====================================================================
# MEJORAS DE EQUIPO (morteros, martillos, piensos y gemas)
# =====================================================================
# Si es True, TODA mejora sale bien: morteros, piensos de montura y de
# mascota, y martillos de perforar. Es para probar sin gastar cien objetos.
#
# Con ella en False se usa mejoras.probabilidad(), que NO esta medida: no hay
# ninguna captura de un fallo. Es una curva inventada que empieza segura y
# baja hasta el 20% en la ultima mejora. En cuanto haya numeros de verdad se
# cambia ahi.
MEJORAS_SIEMPRE_EXITO = True

# Si es True, el martillo verde da el MAXIMO de todos los stats que puede dar
# en vez de sortear cada uno dentro de su rango. El cuadro del juego enseña
# esos rangos: "Attack 0 (0-210), Rigor 3 (0-54), Movement Speed 37 (0-40)".
MARTILLO_VERDE_TODOS_LOS_STATS = True

# El rango con el que entra el personaje: 1 es "Growing Power" y 20 "God's
# Mouthpiece". Viaja en el byte 93 del 0x0002, pegado a los creditos, y NO se
# calcula de ellos: los cortes entre un rango y otro no estan en los datos del
# cliente, asi que lo decide el servidor.
RANGO_INICIAL = 1



# A que nivel sale una mascota nueva. Los stats los saca de petattrib con su
# clase y este nivel, y estan comprobados: una Battlemaid (item 20012) a
# nivel 246 da 12100 de ataque, 15755 de defensa, 3137 de ataque magico,
# 4431 de defensa magica, 1947 de rigor, 1127 de agilidad, 18775 de vida y
# 9074 de mana, que es exactamente la ficha que enseñaba el juego.
#
# A nivel 1 la mascota es inservible, asi que aqui se pone a que nivel
# quieres que aparezcan las que da el comando /item.
MASCOTA_NIVEL_INICIAL = 1
