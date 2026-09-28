# Task for an AI: add GM item-give to Angels Online Preservation

You are editing **SoulOfKarma/Angels-Online-Preservation**, file `server/app.py` only.

Do not invent a new inventory protocol. Reuse the existing loot helpers already in `app.py`:

- `_meter(ses, item_id, n)` — put `n` units in the bag (stacks if `inventario.es_apilable`)
- `_refrescar(ses, [slot])` — S→C `0x001B` slot update (do **not** resend full `0x001A`)
- `_guardar_bolsa(ses, char_id)` — persist
- `_nombre_item(item_id)` — English name from `corpus/content.db`
- `clases.aviso(text, tipo=0, msg_id=clases.MSG_ITEM)` — obtain banner (`0x000D`, msg 492)
- `inventario.fila_item(con, columns, item_id)` — lookup across `item`…`item8`

Bag slots start at 20. Cap qty at 9999. Reject unknown IDs.

## User-facing commands (same parser)

```
item <id> [qty]
/item <id> [qty]
/give <id> [qty]
/i <id> [qty]
/help
```

Three inputs:

1. In-game: if a world C→S body is printable ASCII at offset 0, 1, 2, or 4 (NUL-terminated), treat it as a command. Chat opcode is **not** fully known; sniff those offsets. Only consume the packet if it parses as `item`/`give`/`i`/`help`.
2. Server stdin (only if `sys.stdin.isatty()`): `item 19826 10`
3. File poll every 0.5s: `data/gm.txt`, one command per line, then truncate the file.

Target the most recently connected world session that has `personaje` and `inventario`.

## Patch points in `server/app.py`

### A. After `_nombre_item`, add these functions

```python
def _item_existe(item_id: int) -> bool:
    import sqlite3
    import inventario as _iv
    db = pathlib.Path(__file__).parent.parent / 'corpus' / 'content.db'
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(db)
        r = _iv.fila_item(con, 'id', item_id)
        con.close()
        return r is not None
    except Exception:
        return False


def _gm_dar_item(ses, item_id: int, n: int = 1) -> str:
    """Mete n unidades del item en la mochila de esa sesion."""
    import clases as _cl
    if getattr(ses, 'inventario', None) is None or not getattr(ses, 'personaje', None):
        return "no character in world yet"
    item_id = int(item_id)
    n = max(1, min(9999, int(n)))
    if not _item_existe(item_id):
        return f"unknown item id {item_id}"
    ranura = _meter(ses, item_id, n)
    if ranura is None:
        return "inventory full"
    nom = _nombre_item(item_id)
    cartel = nom if n == 1 else f"{n}x {nom}"
    ses.enviar(_cl.aviso(cartel, tipo=0, msg_id=_cl.MSG_ITEM))
    ses.enviar(*_refrescar(ses, [ranura]))
    _guardar_bolsa(ses, ses.personaje.char_id)
    return f"gave {n}x {nom} ({item_id}) slot {ranura}"


def _gm_texto(cuerpo: bytes):
    """Saca un posible comando ASCII de un paquete C->S."""
    if not cuerpo:
        return None
    for off in (0, 1, 2, 4):
        if len(cuerpo) <= off:
            continue
        chunk = cuerpo[off:]
        nul = chunk.find(b'\x00')
        if nul >= 0:
            chunk = chunk[:nul]
        if not chunk or not all(32 <= b < 127 for b in chunk):
            continue
        t = chunk.decode('ascii').strip()
        if t.startswith('/') or t.lower().split()[:1] in (['item'], ['give'], ['i'], ['help']):
            return t
    return None


def _gm_parsear(texto: str):
    t = texto.strip()
    if t.startswith('/'):
        t = t[1:]
    parts = t.split()
    if not parts:
        return None
    cmd = parts[0].lower()
    if cmd == 'help':
        return ('help',)
    if cmd not in ('item', 'give', 'i'):
        return None
    if len(parts) < 2:
        return ('err', 'usage: /item <id> [qty]')
    try:
        iid = int(parts[1], 0)
    except ValueError:
        return ('err', 'item id must be a number')
    qty = 1
    if len(parts) >= 3:
        try:
            qty = int(parts[2], 0)
        except ValueError:
            return ('err', 'qty must be a number')
    return ('item', iid, qty)


def _probar_gm(ses, cuerpo, addr) -> bool:
    """True si el paquete era un comando GM y ya se contesto."""
    import clases as _cl
    texto = _gm_texto(cuerpo)
    if not texto:
        return False
    parsed = _gm_parsear(texto)
    if parsed is None:
        return False
    kind = parsed[0]
    if kind == 'help':
        msg = "GM: /item <id> [qty]"
        ses.enviar(_cl.aviso(msg, tipo=0, msg_id=_cl.MSG_ITEM))
        log.info(f"[{addr}] GM help")
        return True
    if kind == 'err':
        ses.enviar(_cl.aviso(parsed[1], tipo=0, msg_id=_cl.MSG_ITEM))
        log.info(f"[{addr}] GM {parsed[1]}")
        return True
    _, iid, qty = parsed
    msg = _gm_dar_item(ses, iid, qty)
    if not msg.startswith('gave '):
        ses.enviar(_cl.aviso(msg, tipo=0, msg_id=_cl.MSG_ITEM))
    log.info(f"[{addr}] GM {msg}")
    return True
```

### B. Track world sessions on `Servidor`

In `__init__`:

```python
self.mundos = []
```

In `cliente()`, after creating the session, if `rol == 'mundo'`:

```python
self.mundos.append(ses)
```

In `cliente()` `finally`:

```python
if ses in self.mundos:
    self.mundos.remove(ses)
```

### C. First thing in `manejar()`

```python
if (ses.rol == 'mundo' and getattr(ses, 'personaje', None)
        and _probar_gm(ses, cuerpo, addr)):
    return
```

### D. Methods on `Servidor`, then start them from `correr()`

```python
def _sesion_mundo(self):
    for s in reversed(self.mundos):
        if getattr(s, 'personaje', None) and getattr(s, 'inventario', None) is not None:
            return s
    return None

def _gm_ejecutar_linea(self, linea: str) -> str:
    import clases as _cl
    parsed = _gm_parsear(linea)
    if parsed is None:
        t = linea.strip()
        return f"GM unknown: {t}  (try: item <id> [qty])" if t else ""
    if parsed[0] == 'help':
        return "GM: item <id> [qty]"
    if parsed[0] == 'err':
        return f"GM {parsed[1]}"
    ses = self._sesion_mundo()
    if ses is None:
        return "GM: no character in world yet"
    _, iid, qty = parsed
    msg = _gm_dar_item(ses, iid, qty)
    if not msg.startswith('gave '):
        try:
            ses.enviar(_cl.aviso(msg, tipo=0, msg_id=_cl.MSG_ITEM))
        except Exception:
            pass
    return f"GM {msg}"

async def _consola_gm(self):
    loop = asyncio.get_running_loop()
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return
    except Exception:
        return
    while True:
        try:
            linea = await loop.run_in_executor(None, sys.stdin.readline)
        except Exception:
            return
        if linea == '':
            return
        msg = self._gm_ejecutar_linea(linea)
        if msg:
            log.info(msg)

async def _cola_gm(self):
    ruta = pathlib.Path(__file__).parent.parent / 'data' / 'gm.txt'
    while True:
        await asyncio.sleep(0.5)
        try:
            if not ruta.exists():
                continue
            texto = ruta.read_text(encoding='utf-8', errors='replace')
            if not texto.strip():
                continue
            ruta.write_text('', encoding='utf-8')
            for linea in texto.splitlines():
                msg = self._gm_ejecutar_linea(linea)
                if msg:
                    log.info(msg)
        except Exception as e:
            log.debug("GM queue: %s", e)
```

In `correr()`, after the listen logs:

```python
tareas.append(self._consola_gm())
tareas.append(self._cola_gm())
```

`sys`, `pathlib`, `asyncio`, and `log` are already imported in `app.py`.

## Do not

- Do not treat C→S `0x002E` as chat. In this server it is **use item**.
- Do not resend the full inventory (`0x001A`) after a grant; slot `0x001B` only.
- Do not add a new Python dependency.
- Do not implement fusion or other GM commands unless asked.

## Verify

`py -3 -m py_compile server/app.py`

In-game after login, writing `item 19826` to `data/gm.txt` should put FreshmanSabre in the bag and show the obtain banner. Unknown IDs must not create a slot.
