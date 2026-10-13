# Guía Metodológica: Reparación de Monstruos y Objetivos de Misiones (Para Claude y Desarrolladores)

Esta guía explica en detalle cómo funciona el sistema de cacería y objetivos de misiones en Angels Online, por qué a veces los monstruos no cuentan al matarlos, y cómo diagnosticar y reparar cualquier misión de forma rápida, robusta y definitiva.

---

## 1. Arquitectura del Sistema de Cacería

En Angels Online y en este emulador, existen dos formas principales en las que matar un monstruo interactúa con una misión:

### A. Misión de Cacería Directa (Kill Quest)
- **Texto típico en `quest.xml`**: `Defeat 30 Red Dragons`, `Drive away the following monsters: /c$9%8461%/c*/30...`, `Defeat: Ferrous Fang: /c$9%74959%/c*/ 200`.
- **Mecanismo**: Al morir el monstruo (`_matar_monstruo` en `app.py`), se invoca:
  ```python
  registrar_baja_monstruo(ses, npc_type, monster_name)
  ```
- **Almacenamiento**:
  1. Contador interno en Python: `p.quest_kills["{qid}_{paso}"] = count`.
  2. Guardado persistente en `cuentas.db` (`cuentas.guardar_quest_kills(...)`).
  3. Token en inventario oculto de misiones (ranuras `497..556`): para que el HUD del cliente reemplace `%XXXX%` por el número actual.

### B. Misión de Recolección por Drop (Gather / Quest Item Drop)
- **Texto típico en `quest.xml`**: `Gather from Ashen Crawler: Collect radioactive isotope /c$9%74957%/c*/ 3`.
- **Mecanismo**: El monstruo **NO** cuenta como baja directa; lo que hace es **soltar un item de misión** (con un % de drop). El item entra al inventario oculto de misiones (`497..556`).
- **Comprobación**: Se evalúa con `verificar_recoleccion_mision(ses, item_id, cantidad)`.

---

## 2. Las 4 Causas por las que un Mob "No Cuenta"

### Causa 1: Fallo del compilador de misiones (`compilar_misiones.py`)
El archivo `server/plantillas/misiones_completas.json` se generó automáticamente leyendo `quest.xml`. Sin embargo, las expresiones regulares del compilador no cubren todos los formatos de texto de IGG/UserJoy.

#### Ejemplo Real 1: Misión 1566 paso 4 (Rogue Guardian)
- **Texto original en `quest.xml`**:
  ```text
  4. Defeat: 
   Ferrous Fang: /c$9%74959%/c*/ 200.
  ```
- **Error del parser**: Buscó texto entre `defeat` y `:`, encontrando sólo espacios vacíos. El JSON quedó compilado así:
  ```json
  "monstruos": ["defeat"],
  "monstruo_ids": [],
  "nombre_objetivo": "defeat"
  ```
- **Consecuencia**: Cuando matas un `Ferrous Fang` (ID 23568), el servidor compara `23568 in []` (falso) y `'ferrous fang' in 'defeat'` (falso). **El mob nunca cuenta.**

#### Ejemplo Real 2: Misión 901 paso 1 (For the Wind Pinecones)
- **Texto original en `quest.xml`**:
  ```text
  1. Drive the following monsters away: /c$9%8461%/c*/30 Red/Cyan Dragon in \n River Valley\n, /c$9%8462%/c*/30 Orangutan in \n River Valley\n, /c$9%8463%/c*/30 Man eating Crocodile/Den Crocodile in \n the Secret Den\n and /c$9%8464%/c*/30 Iron-shell Worm/Fire-shell Worm in \n the Secret Den.\n
  ```
- **Error del parser**: Asumió que el monstruo era `"the following monsters away"`, y concatenó todo el texto restante como nombres de monstruos, incluyendo etiquetas `/c$9%8462%/c*`.
- **Consecuencia**: `monstruo_ids` queda vacío `[]`. En el chat se imprime el texto basura con saltos de línea y códigos de color (`Defeated drive the following monsters away / ... (5/30)`).

---

### Causa 2: Discrepancia entre nombres en `quest.xml` y `monster.xml`
- En el texto de la quest dice: `Sandcrawlers`, `Duty Pig`, `Young Witch`.
- En `monster.xml` el NPC se llama: `Sandcrawler` (singular), `Hardworking Pig`, `Trainee Witch`, `Valley Orangutanutan`.
- Si el servidor no tiene el ID numérico (`npc_type`) ni un alias en `MONSTER_NAME_ALIASES`, la comparación de cadenas falla.

---

### Causa 3: Confusión entre Kill directo y Drop de item
- Si la quest pide *"Gather 3 Radioactive Isotope from Ashen Crawler"*, el jugador está matando `Ashen Crawler` esperando que suba un contador de muertes.
- Pero el servidor espera que el monstruo suelte el item `74957`. Si ese item no está configurado en la tabla de drops de quest de ese mob, el jugador nunca obtiene el item y la misión queda atascada.

---

### Causa 4: El HUD del cliente muestra `0/30` aunque el servidor cuente
- En el cliente de Angels Online, el HUD de seguimiento de misiones (a la derecha de la pantalla) interpreta las variables `%TOKEN_ID%`:
  - `0/30 Red/Cyan Dragon`: El `0` es el valor de la variable `%8461%`.
  - El cliente obtiene ese valor leyendo cuántos items con ID `8461` tiene el personaje en su **inventario de misiones oculto** (ranuras `497..556`).
- Si el servidor solo incrementa un contador interno `quest_kills["901_1"]` pero **no envía el token de quest** a la ranura oculta del cliente, el HUD seguirá mostrando `0/30` para siempre, confundiendo al jugador.

---

## 3. Protocolo de Diagnóstico Paso a Paso

Cuando un mob no cuente para una misión, sigue estos 4 pasos exactos:

### Paso 1: Inspeccionar el texto y requisitos originales en `quest.xml`
Abre o busca en `extracted_paks/update26/setting/eng/quest.xml`:
```python
import xml.etree.ElementTree as ET
tree = ET.parse('extracted_paks/update26/setting/eng/quest.xml')
for q in tree.getroot():
    if q.attrib.get('編號') == str(QID):
        for k, v in q.attrib.items():
            if k.startswith('步驟'):
                print(f"{k}: {v}")
```
Identifica:
- El paso exacto (`步驟01` = paso 1, `步驟02` = paso 2, etc.).
- Los tokens `/c$9%XXXXX%/c*` y la cantidad requerida.
- Los nombres de los monstruos mencionados en el texto.

### Paso 2: Buscar los IDs reales de los monstruos en `monster.xml`
Busca en `extracted_paks/update26/setting/eng/monster.xml`:
```python
tree = ET.parse('extracted_paks/update26/setting/eng/monster.xml')
for m in tree.getroot().findall('npc'):
    nom = m.attrib.get('名稱', '')
    if any(k in nom.lower() for k in ['ashen crawler', 'sandcrawler', 'ferrous fang']):
        print(f"ID: {m.attrib.get('編號')} | Nombre: {nom}")
```
Anota los IDs numéricos exactos (`編號`). Por ejemplo:
- `23564`: Sandcrawler
- `23565`: Ashen Crawler
- `23568`: Ferrous Fang
- `3573`: Cyan Dragon
- `3574`: Red Dragon
- `3575`: Valley Orangutanutan

### Paso 3: Revisar cómo está en `server/plantillas/misiones_completas.json`
Verifica la entrada en `cacerias[f"{qid}_{paso}"]`. Si `monstruo_ids` está vacío `[]` o `monstruos` contiene palabras como `["defeat"]` o `["the following monsters away"]`, esa es la causa del problema.

---

## 4. Métodos de Reparación en el Servidor

Existen 3 niveles para aplicar la solución:

### Nivel 1: Registro directo en `OBJETIVOS_CACERIA` de `server/misiones.py` (Recomendado)
Es la solución más rápida, segura y 100% inmune a errores de parsing. `OBJETIVOS_CACERIA` tiene máxima prioridad sobre `misiones_completas.json`.

Ejemplo para la **Misión 1566 paso 4** (Ferrous Fang / Sandcrawler en Sandy Heights):
```python
# En server/misiones.py -> OBJETIVOS_CACERIA:
(1566, 4): {
    'monstruos': ('ferrous fang', 'sandcrawler', 'ashen crawler'),
    'monstruo_ids': (23568, 23564, 23565),
    'cantidad': 200,
    'token_id': 74959,
    'siguiente_paso': 5,
    'nombre_objetivo': 'Ferrous Fang',
    'aviso_fin': 'Quest [Rogue Guardian]: Return to Leif in Sandy Heights.',
},
```

### Nivel 2: Registro de Alias en `MONSTER_NAME_ALIASES`
Si el problema es que el monstruo tiene un nombre alternativo o plural en el cliente:
```python
# En server/misiones.py -> MONSTER_NAME_ALIASES:
MONSTER_NAME_ALIASES = {
    'sandcrawler': ['ashen crawler', 'ferrous fang', 'sandcrawlers'],
    'ashen crawler': ['sandcrawler', 'ferrous fang'],
    'ferrous fang': ['sandcrawler', 'ashen crawler'],
    'orangutan': ['valley orangutanutan', 'rage orangutan jordan'],
    'valley orangutanutan': ['orangutan'],
    # ...
}
```

### Nivel 3: Manejo de Misiones Multi-Objetivo (como Misión 901)
Cuando un paso pide **múltiples grupos de monstruos** con sus propios tokens:
- 30 Red/Cyan Dragon (token `8461`)
- 30 Orangutan (token `8462`)
- 30 Crocodile (token `8463`)
- 30 Worm (token `8464`)

En este caso, se deben registrar las tuplas de monstruos correspondientes y asociar cada grupo a su respectivo `token_id`.

Para que el HUD del cliente actualice el contador en tiempo real (`X/30`), el servidor debe depositar el token correspondiente en el inventario de misiones oculto del jugador:
```python
# Dar token de mision al inventario oculto (ranuras 497..556)
from server import inventario as _inv

def entregar_token_mision(ses, p, token_id: int):
    # Buscar si ya existe el token en el rango oculto
    for r in range(497, 557):
        if p.inventario.get(r) == token_id:
            cant = p.cantidades.get(r, 1) + 1
            p.cantidades[r] = cant
            ses.enviar(_inv.poner(p.char_id, r, token_id, cant, dueno=p.entity_id))
            return
    # Si no existe, colocar en primera ranura libre
    for r in range(497, 557):
        if r not in p.inventario or not p.inventario[r]:
            p.inventario[r] = token_id
            p.cantidades[r] = 1
            ses.enviar(_inv.poner(p.char_id, r, token_id, 1, dueno=p.entity_id))
            return
```

---

## 5. Checklist de Verificación para Claude

Antes de marcar cualquier reporte de misión como completado:

1. [ ] **Verificar `quest.xml`**: ¿Es una misión de muerte directa (`matar`) o de recolección de drop (`recolectar`)?
2. [ ] **Verificar `monster.xml`**: ¿Tienes los IDs numéricos exactos de todos los monstruos válidos?
3. [ ] **Comprobar `OBJETIVOS_CACERIA`**: ¿Están los IDs numéricos en `monstruo_ids` y los nombres en minúsculas en `monstruos`?
4. [ ] **Comprobar `nombre_objetivo`**: ¿El texto que se imprime en pantalla es limpio y claro (sin textos largos con `/c$9` ni saltos de línea `\n`)?
5. [ ] **Comprobar `token_id`**: ¿Está configurado el token correcto para que el cliente actualice el tracker visual?
6. [ ] **Ejecutar tests**: Ejecutar `python tools/test_sistema_misiones_completo.py` para asegurar que ningún flujo previo se rompió.

