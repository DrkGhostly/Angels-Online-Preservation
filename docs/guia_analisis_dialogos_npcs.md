# Guía Metodológica: Análisis y Restauración de NPCs y Diálogos en Angels Online

Esta guía documenta la metodología exacta de ingeniería inversa para analizar, restaurar y enlazar correctamente NPCs, diálogos y misiones a partir de los datos originales del cliente oficial (IGG cliente 8.5.1.0) y del emulador.

---

## 1. Fuentes de Datos Oficiales

Todo el contenido de Angels Online proviene de los archivos XML empaquetados en los `.pak` del cliente. Nunca se inventa ningún texto, ID ni posición:

| Archivo / Base de datos | Contenido | Uso principal |
|---|---|---|
| `extracted_paks/update26/setting/eng/msg.xml` | Más de 42.000 cadenas de texto indexadas por `mid` numérico. | Textos de diálogos, opciones, avisos del sistema y nombres de habilidades. |
| `extracted_paks/data1/setting/npc.xml` / `corpus/content.db` (tabla `npc`) | Registros de NPCs: `id`, `name`, `sprite_id`, `faction`, `level`. | Obtener `npc_type` canónico y `sprite` oficial de cada NPC. |
| `extracted_paks/data1/setting/quest.xml` / `corpus/content.db` (tabla `quest`) | Definición de misiones: `id`, `name`, `NPC_Inicio`, `pasos`, recompensas. | Requisitos de nivel, NPCs de entrega y cadena de misiones. |
| `server/plantillas/<mapa>.json` | Spawns de cada mapa: `entity_id`, `nombre`, `npc_type`, `sprite`, `tile: [x, y]`, `klass`. | Posición física en el mapa y atributos de red. |
| `server/plantillas/misiones_completas.json` | Catálogo compilado de 1.489 misiones estructurado en JSON. | Relación de `npc_inicio`, `pasos`, `cacerias` y `recolecciones`. |
| `server/plantillas/dialogos_npc.json` | Diálogos por defecto / idle para NPCs cuando no tienen misiones activas. | Frase inicial que dice el NPC al cliquearlo si no ofrece misiones. |

---

## 2. Estructura del Paquete de Diálogo (`0x0012`) en `Angel.exe`

El cliente procesa las ventanas de diálogo mediante el sub-mensaje `0x0012` (función `sub_5FBD30` / `sub_4A5390` del ejecutable).

### Formato Binario:
```
[Offset 0..1]  U16 LE  0x0012          (Opcode del sub-mensaje)
[Offset 2..5]  U32 LE  msg_id          (ID del texto del PROMPT en msg.xml)
[Offset 6..7]  U16 LE  val             (ID del RETRATO gráfico en el cliente)
[Offset 8]     U8      n_opciones      (Número de botones de respuesta)
[Offset 9]     U8      0x00            (Byte de relleno obligatorio)
[Offset 10..]  Array de U32 LE         (msg_id de cada opción cliqueable)
[Offset ..]    Array de U32 LE         (Opcional: códigos de acción, ej. 1000000+)
[Offset ..]    Strings                 (Opcional: parámetros %s terminados en NUL)
```

### Fórmula de Retratos (`val`):
El número de retrato se deriva del `sprite` del NPC:
- Si `40200 <= sprite < 41000`: `val = 1000 + (sprite - 40200)`
  - *Ejemplo*: Nark Paul (`sprite: 40246`) -> `val = 1046` (Retrato del gato rojo).
  - *Ejemplo*: Green Forest Scholar (`sprite: 40211`) -> `val = 1011` (Retrato del búho).
  - *Ejemplo*: Bassil Archeologist (`sprite: 40331`) -> `val = 1131` (Retrato del explorador).
- Si `40000 <= sprite < 50000`: `val = sprite - 40000`
- Otros: valor directo del sprite.

---

## 3. La Regla de Oro: PROMPT vs OPCIONES

Un error recurrente al armar diálogos es confundir el **bocadillo del NPC** (Prompt) con los **botones cliqueables** (Opciones).

### Concepto:
1. **Prompt (`mid`)**: Es lo que **dice el NPC**. Aparece en el cuadro superior de texto.
2. **Opciones (`opts`)**: Son las respuestas que **el jugador puede elegir**. Aparecen como lista de texto interactivo con viñetas.

### Regla de Orden de Opciones:
En Angels Online, el servidor espera que la primera opción (`índice 0`) sea la opción positiva o de continuación, y la última sea la de salida o cancelación.
- **Opción 0 (Arriba / Positiva)**:
  - Continuar con la misión ("What is your cunning plan?", "Tell me how I can help", "OK", "Set out!").
- **Opción 1 o última (Abajo / Salida)**:
  - Salir o rechazar ("Leave", "You take care. Bye.", "How about another day...", "Quit", "See you!").

> [!WARNING]
> Si se invierten las opciones (ej. poniendo "You take care. Bye." como opción 0), el cuadro de diálogo aparece con el texto al revés y al hacer clic en "Bye" el servidor interpretará que el jugador aceptó la misión (`_i == 0`).

---

## 4. Patrones Estructurales de Misiones en `msg.xml`

Cada misión tiene reservado un bloque de 100 IDs en `msg.xml`: `base = qid * 100`.

### Patrón A: Conversación de 2 Pasos (ej. Quest 852 - Nark Paul)
1. **Paso 1 (Introducción / Interés)**:
   - `base + 1` (85201): Saludo del NPC ("Shhh! Keep your voice down...").
   - Opción 0 (`base + 2`, 85202): Pregunta del jugador ("What is your cunning plan?").
   - Opción 1 (`base + 3`, 85203): Despedida ("You take care. Bye.").
2. **Paso 2 (Propuesta / Aceptación)**:
   - Si nivel insuficiente: `base + 7` (85207) ("You are foolishly daring... below Level 70").
   - Si cumple nivel: `base + 4` (85204): Propuesta de la misión ("Recently I heard that many young girls have vanished...").
   - Opción 0 (`base + 5`, 85205): Aceptar ("OK.").
   - Opción 1 (`base + 6`, 85206): Rechazar ("It's too dangerous. You can go alone.").
3. **Paso 3 (Aceptada / Éxito)**:
   - `base + 8` (85208): Despedida con instrucciones ("According to our information...").
4. **Paso 4 (En progreso)**:
   - `base + 9` (85209): Diálogo de recordatorio ("Those Gloomy Smokers must know something...").

### Patrón B: Misiones de Capital / Expedición (ej. Quest 366 - Bassil Archeologist)
1. **Paso 1 (Presentación y Requisito)**:
   - `base + 1` (36601): Saludo del arqueólogo ("Traveler, I am pleased to meet you...").
   - Si nivel < 90: `base + 2` (36602) ("If you are at least Level 90, I shall consider you...").
   - Si nivel >= 90: `base + 3` (36603) ("Presently, we require an astute adventurer... Want to give it a try?").
   - Opción 0 (`base + 4`, 36604): Aceptar ("Set out for the Bassil Kingdom!").
   - Opción 1 (`base + 5`, 36605): Posponer ("How about another day...").
2. **Paso 2 (Aceptada)**:
   - `base + 6` (36606): Instrucciones de viaje hacia Nel en Karang Desert.
3. **Paso 3 (En progreso)**:
   - `base + 7` (36607): Recordatorio.

### Patrón C: Misiones Multiciudad (ej. Quest 901 - Green Forest Scholar)
El NPC existe en las 4 ciudades (Aurora, Breeze, Dark, Iron):
- `base + 1` (90101): Saludo ("Oh, I would like to return to the forest...").
- Opciones:
  - `base + 2` (90102): "¿Quién eres?" -> Responde con el texto de su ciudad (`90105` Aurora, `90106` Breeze, `90107` Dark, `90108` Iron).
  - `base + 3` (90103): "¿Puedo ayudarte?" -> Requisito de nivel (`90109` nv. 70) o propuesta (`90111`).
  - `base + 4` (90104): "Leave."
- Opciones de propuesta (`90111`):
  - Opción 0 (`base + 12`, 90112): "I will take care of everything." (Acepta).
  - Opción 1 (`base + 13`, 90113): "I may help you next time." (Rechaza).

---

## 5. Configuración Correcta de NPCs en `server/plantillas/<mapa>.json`

Al restaurar o añadir NPCs a un mapa, se deben respetar estos campos estrictos:

```json
{
  "entity_id": 121987,
  "nombre": "Green Forest Sch",
  "nombre_completo": "Green Forest Scholar",
  "npc_type": 2439,
  "sprite": 40211,
  "klass": 199,
  "monstruo": false,
  "tile": [180, 128],
  "direccion": 6,
  "visible": 1
}
```

### Reglas críticas de los campos:
1. **`nombre`**: Máximo 16 caracteres. El paquete de red del cliente trunca nombres largos (`Green Forest Sch`, `Bassil Archeolog`).
2. **`nombre_completo`**: Nombre canónico completo de `npc.xml`. Sirve para búsquedas internas de misiones y diálogos.
3. **`npc_type`**: Debe ser el ID de `npc.xml` (ej. `2439` para Green Forest Scholar, `8863` para Bassil Archeologist).
   > [!CAUTION]
   > **NO** usar los dígitos del sprite como `npc_type` (ej. usar `331` de `40331`). Eso rompe la identificación del NPC.
4. **`klass`**: Siempre `199` para NPCs amistosos con diálogo.
   - `200`: Totems de portal / cambio de mapa.
   - `400`: Tablones o carteles estáticos de texto.
5. **`entity_id`**: Debe estar dentro del rango asignado a ese mapa en `server/app.py` (ej. Breeze Woods: `121920..121999`). Si se usa un ID fuera de rango (como `90029001`), el servidor no reconocerá en qué mapa está el NPC.
6. **`_descartados`**: Si un NPC fue puesto en `_descartados` por un script antiguo creyendo erróneamente que era una invocación (`klass: 199` vs summons), debe sacarse de `_descartados` y restaurarse en `spawns`.

---

## 6. Normalización de Nombres en `server/misiones.py`

Dado que `quest.xml` escribe los nombres de inicio de forma variable (ej. `Level 90 - Bassil Archeologist` o `Dr. Fleming`), la función [`normalizar_nombre_npc`](file:///f:/Ao%20Proyect/AO%202/server/misiones.py#L128) debe:
1. Eliminar prefijos de nivel: `re.sub(r'^(?:level|lvl)\s*\d+\s*[-–:]\s*', '', n)`.
2. Eliminar prefijos de título: `Mr.`, `Dr.`, `Elder`, `Master`, `Sage`.
3. Mapear alias truncados de la red a nombres canónicos:
   - `'green forest sch'` -> `'green forest scholar'`
   - `'bassil archeolog'` -> `'bassil archeologist'`
   - `'adventure guild '` -> `'adventure guild admin'`

---

## 7. Checklist Rápido de Verificación para Cada NPC

Antes de dar por completado un NPC, verificar:
- [ ] ¿El NPC tiene `klass: 199` y `entity_id` dentro del rango del mapa?
- [ ] ¿El `npc_type` coincide con `npc.xml` y no es el sufijo del sprite?
- [ ] ¿`misiones_disponibles_npc` devuelve la quest correcta en esa ciudad?
- [ ] ¿El Prompt inicial es el saludo del NPC y no la pregunta del jugador?
- [ ] ¿La opción positiva/misión es la opción 0 y la opción de salida/despedida es la última?
- [ ] ¿El NPC tiene diálogo idle en `dialogos_npc.json` para cuando no haya quests disponibles?
- [ ] ¿Se ejecutó `python tools/test_sistema_misiones_completo.py` sin errores?

