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
TASA_EXP_BASE = 2.0           # Multiplicador de EXP de personaje
TASA_SKILL_EXP_BASE = 2.0     # Multiplicador de EXP de habilidades (stamina/skills)
TASA_DROP_BASE = 2.5          # Multiplicador de probabilidad de drop de items
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
BONUS_EVENTO_SKILL = 50000.0


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

