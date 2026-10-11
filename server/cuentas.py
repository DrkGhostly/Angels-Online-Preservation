"""
Cuentas y personajes con base de datos SQLite local (cuentas.db).

Proteccion contra cortes de luz:
  - SQLite con modo WAL (Write-Ahead Logging) y PRAGMA synchronous = FULL.
  - Las transacciones son ACID y atomicas; un corte de suministro electrico o
    cierre inesperado del proceso NUNCA deja archivos truncados ni corrompidos.
  - Copias de seguridad automaticas y rotativas en data/backups/ mediante la
    API nativa de SQLite (con.backup).
  - Mantiene un espejo en data/cuentas.json para compatibilidad e inspeccion manual.
"""
import sqlite3
import json
import pathlib
import datetime
import hashlib
import os
import tempfile
import threading
import time
import logging
import asyncio

log = logging.getLogger('cuentas')

BASE = pathlib.Path(__file__).parent.parent / 'data'
DB_PATH = BASE / 'cuentas.db'
BACKUPS_DIR = BASE / 'backups'
ARCHIVO = BASE / 'cuentas.json'
MUESTRAS = pathlib.Path(__file__).parent.parent / 'logs' / 'auth_muestras'

_LOCK = threading.RLock()
GUARDAR_AUTH_CRUDO = os.environ.get('AO_GUARDAR_AUTH_CRUDO', '0') == '1'
REGISTRAR_HASH_PRIMER_LOGIN = os.environ.get('AO_REGISTRAR_PRIMER_HASH', '0') == '1'
VALIDAR_PASSWORD = os.environ.get('AO_VALIDAR_PASSWORD', '0') == '1'
OFF_HASH = 21
LARGO_HASH = 32

_CAMBIOS_DESDE_BACKUP = 0
_ULTIMO_BACKUP = time.time()
MAX_BACKUPS_CONSERVADOS = 10


def _get_conn():
    """Abre conexion a SQLite con protecciones contra cortes de luz."""
    BASE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15.0)
    con.execute('PRAGMA journal_mode = WAL;')
    con.execute('PRAGMA synchronous = FULL;')
    con.execute('PRAGMA foreign_keys = ON;')
    con.execute('PRAGMA busy_timeout = 10000;')
    return con


def _init_db():
    with _LOCK:
        BASE.mkdir(parents=True, exist_ok=True)
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        con = _get_conn()
        try:
            con.execute('''
            CREATE TABLE IF NOT EXISTS cuentas (
                usuario TEXT PRIMARY KEY COLLATE NOCASE,
                password TEXT NOT NULL DEFAULT '',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''')
            con.execute('''
            CREATE TABLE IF NOT EXISTS personajes (
                usuario TEXT NOT NULL COLLATE NOCASE,
                char_id INTEGER NOT NULL,
                ranura INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                datos TEXT NOT NULL,
                actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (usuario, ranura),
                FOREIGN KEY (usuario) REFERENCES cuentas(usuario) ON DELETE CASCADE
            );
            ''')
            con.execute('CREATE INDEX IF NOT EXISTS idx_pj_char_id ON personajes(usuario, char_id);')
            con.commit()

            cur = con.cursor()
            cur.execute('SELECT COUNT(*) FROM cuentas')
            cant_cuentas = cur.fetchone()[0]
            if cant_cuentas == 0:
                _migrar_desde_json(con)
        finally:
            con.close()


def _migrar_desde_json(con):
    """Importa cuentas existentes de archivos JSON a SQLite."""
    candidatos = [
        ARCHIVO,
        BASE / 'cuentas_backup_karmav3_lv408.json',
        BASE / 'cuentas.json base',
        ARCHIVO.with_suffix('.json.bak'),
        BASE / 'cuentas.json2',
    ]
    datos_cargados = None
    for cand in candidatos:
        if cand.exists():
            try:
                txt = cand.read_text(encoding='utf-8')
                d = json.loads(txt)
                if d and isinstance(d.get('cuentas'), dict) and len(d['cuentas']) > 0:
                    datos_cargados = d
                    log.info(f"Migrando cuentas a SQLite desde {cand.name}")
                    break
            except Exception:
                continue

    if not datos_cargados:
        datos_cargados = {
            "cuentas": {
                "karma": {"password": "123456", "personajes": []}
            }
        }

    proximo_char_id = 1001
    cur = con.cursor()
    cur.execute("SELECT MAX(char_id) FROM personajes")
    row_m = cur.fetchone()
    if row_m and row_m[0]:
        proximo_char_id = row_m[0] + 1

    for u, c in datos_cargados.get('cuentas', {}).items():
        con.execute("INSERT OR REPLACE INTO cuentas (usuario, password) VALUES (?, ?)", (u, c.get('password', '')))
        for idx, p in enumerate(c.get('personajes', [])):
            r = int(p.get('ranura') if p.get('ranura') is not None else idx)
            cid = int(p.get('char_id') or 0)
            if not cid:
                cid = proximo_char_id
                proximo_char_id += 1
            p['char_id'] = cid
            con.execute(
                "INSERT OR REPLACE INTO personajes (usuario, char_id, ranura, nombre, datos) VALUES (?, ?, ?, ?, ?)",
                (u, cid, r, p.get('nombre', ''), json.dumps(p, ensure_ascii=False))
            )
    con.commit()
    log.info("Migracion automatica a SQLite completada exitosamente.")
    hacer_backup(motivo="migracion_inicial")




def hacer_backup(motivo="auto") -> pathlib.Path:
    """Copia de seguridad en caliente garantizada por la API nativa de SQLite."""
    global _CAMBIOS_DESDE_BACKUP, _ULTIMO_BACKUP
    with _LOCK:
        try:
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = BACKUPS_DIR / f"cuentas_auto_{ts}.db"
            src = sqlite3.connect(str(DB_PATH))
            dst = sqlite3.connect(str(backup_file))
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
            _CAMBIOS_DESDE_BACKUP = 0
            _ULTIMO_BACKUP = time.time()
            log.info(f"Backup automatico creado en {backup_file.name} (motivo: {motivo})")
            _limpiar_backups_antiguos()
            _exportar_json_disco()
            return backup_file
        except Exception:
            log.exception("Error al crear backup automatico de SQLite")
            return None


def _limpiar_backups_antiguos():
    """Mantiene los ultimos N backups y purga los mas viejos para no llenar disco."""
    try:
        backups = sorted(BACKUPS_DIR.glob("cuentas_auto_*.db"), key=os.path.getmtime)
        if len(backups) > MAX_BACKUPS_CONSERVADOS:
            sobrantes = backups[:-MAX_BACKUPS_CONSERVADOS]
            for b in sobrantes:
                try:
                    b.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _exportar_json_disco():
    """Escribe data/cuentas.json de forma atomica para inspeccion externa."""
    try:
        datos = cargar()
        fd, temporal = tempfile.mkstemp(prefix='cuentas_mirror_', suffix='.tmp', dir=str(BASE))
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temporal), str(ARCHIVO))
    except Exception:
        log.exception("Error al sincronizar cuentas.json espejo")


def _notificar_cambio(inmediato=False):
    global _CAMBIOS_DESDE_BACKUP
    _CAMBIOS_DESDE_BACKUP += 1
    if inmediato or _CAMBIOS_DESDE_BACKUP >= 25 or (time.time() - _ULTIMO_BACKUP > 300):
        hacer_backup(motivo="cambios_frecuentes")
    else:
        _exportar_json_disco()


async def tarea_backup_periodico(intervalo_segundos=300):
    """Tarea asincrona de fondo que respalda la base de datos periodicamente."""
    while True:
        try:
            await asyncio.sleep(intervalo_segundos)
            if _CAMBIOS_DESDE_BACKUP > 0:
                hacer_backup(motivo="intervalo_periodico")
        except asyncio.CancelledError:
            hacer_backup(motivo="cierre_servidor")
            break
        except Exception:
            log.exception("Error en tarea_backup_periodico")


def cargar() -> dict:
    """Devuelve el arbol completo de cuentas y personajes desde SQLite."""
    with _LOCK:
        con = _get_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT usuario, password FROM cuentas ORDER BY usuario ASC")
            cuentas_dict = {}
            for u, pw in cur.fetchall():
                cuentas_dict[u] = {'password': pw, 'personajes': []}

            cur.execute("SELECT usuario, ranura, datos FROM personajes ORDER BY ranura ASC")
            for u, ranura, datos_json in cur.fetchall():
                # Encontrar cuenta coincidente (case-insensitive)
                cta = cuentas_dict.get(u)
                if cta is None:
                    for k in cuentas_dict:
                        if k.lower() == u.lower():
                            cta = cuentas_dict[k]
                            break
                if cta is not None:
                    try:
                        p_dict = json.loads(datos_json)
                        cta['personajes'].append(p_dict)
                    except Exception:
                        pass
            return {'cuentas': cuentas_dict}
        finally:
            con.close()


def guardar_documento(datos: dict):
    """Guarda un documento completo en SQLite y sincroniza el espejo."""
    with _LOCK:
        con = _get_conn()
        try:
            for u, c in datos.get('cuentas', {}).items():
                con.execute("INSERT OR REPLACE INTO cuentas (usuario, password) VALUES (?, ?)", (u, c.get('password', '')))
                p_list = c.get('personajes', [])
                ranuras_activas = set()
                for idx, p in enumerate(p_list):
                    r = int(p.get('ranura') if p.get('ranura') is not None else idx)
                    ranuras_activas.add(r)
                    cid = int(p.get('char_id') or (1001 + r))
                    con.execute(
                        "INSERT OR REPLACE INTO personajes (usuario, char_id, ranura, nombre, datos) VALUES (?, ?, ?, ?, ?)",
                        (u, cid, r, p.get('nombre', ''), json.dumps(p, ensure_ascii=False))
                    )
                # Borrar personajes eliminados en esta cuenta
                cur = con.cursor()
                cur.execute("SELECT ranura FROM personajes WHERE usuario = ?", (u,))
                for (r_db,) in cur.fetchall():
                    if r_db not in ranuras_activas:
                        con.execute("DELETE FROM personajes WHERE usuario = ? AND ranura = ?", (u, r_db))
            con.commit()
            _notificar_cambio(inmediato=True)
        finally:
            con.close()


def _guardar(datos: dict):
    guardar_documento(datos)


def guardar_personaje_nuevo(usuario: str, p: dict):
    """Inserta o actualiza un personaje directamente en SQLite."""
    with _LOCK:
        con = _get_conn()
        try:
            r = int(p.get('ranura', 0))
            cid = int(p.get('char_id') or (1001 + r))
            con.execute("INSERT OR IGNORE INTO cuentas (usuario, password) VALUES (?, '')", (usuario,))
            con.execute(
                "INSERT OR REPLACE INTO personajes (usuario, char_id, ranura, nombre, datos) VALUES (?, ?, ?, ?, ?)",
                (usuario, cid, r, p.get('nombre', ''), json.dumps(p, ensure_ascii=False))
            )
            con.commit()
            _notificar_cambio(inmediato=True)
        finally:
            con.close()


def _actualizar_personaje(usuario: str, char_id: int, mutador_fn):
    """Modifica un personaje en SQLite bajo una transaccion atomica protegida."""
    with _LOCK:
        con = _get_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT ranura, datos FROM personajes WHERE usuario = ? AND char_id = ?", (usuario, char_id))
            row = cur.fetchone()
            if not row:
                # Fallback: si char_id no coincide o hay 1 solo personaje para ese usuario
                cur.execute("SELECT ranura, datos FROM personajes WHERE usuario = ?", (usuario,))
                row = cur.fetchone()
                if not row:
                    return
            ranura, datos_json = row
            p = json.loads(datos_json)
            mutador_fn(p)
            con.execute(
                "UPDATE personajes SET nombre = ?, datos = ?, actualizado_en = CURRENT_TIMESTAMP WHERE usuario = ? AND ranura = ?",
                (p.get('nombre', ''), json.dumps(p, ensure_ascii=False), usuario, ranura)
            )
            con.commit()
            _notificar_cambio()
        finally:
            con.close()


def hash_de_auth(cuerpo: bytes) -> str:
    return (cuerpo[OFF_HASH:OFF_HASH + LARGO_HASH].hex()
            if len(cuerpo) >= OFF_HASH + LARGO_HASH else '')


def validar(usuario: str, cuerpo_auth: bytes = b'') -> tuple:
    """Valida la cuenta en SQLite. La crea en el primer ingreso si no existe."""
    with _LOCK:
        con = _get_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT password FROM cuentas WHERE usuario = ?", (usuario,))
            row = cur.fetchone()
            if row is None:
                con.execute("INSERT INTO cuentas (usuario, password) VALUES (?, '')", (usuario,))
                con.commit()
                _notificar_cambio(inmediato=True)
                cta = {'password': '', 'personajes': []}
                if VALIDAR_PASSWORD and not REGISTRAR_HASH_PRIMER_LOGIN:
                    return None, "cuenta nueva: requiere registro inicial controlado"
                return cta, f"cuenta '{usuario}' creada en el primer ingreso"

            pw = row[0]
            # Obtener los personajes de la cuenta
            cur.execute("SELECT datos FROM personajes WHERE usuario = ? ORDER BY ranura ASC", (usuario,))
            pjs = [json.loads(d_row[0]) for d_row in cur.fetchall()]
            cta = {'password': pw, 'personajes': pjs}

            h = hash_de_auth(cuerpo_auth)
            if VALIDAR_PASSWORD and (not h or set(h) == {'0'}):
                return None, "contrasena vacia"

            guardado = pw
            if VALIDAR_PASSWORD and guardado and guardado != h:
                return None, "contrasena incorrecta"
            return cta, "ok"
        finally:
            con.close()


def guardar_muestra_auth(bloque: bytes, nota: str = ""):
    MUESTRAS.mkdir(parents=True, exist_ok=True)
    marca = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    digest = hashlib.sha256(bloque).hexdigest()
    (MUESTRAS / f"auth_{marca}.sha256").write_text(digest, encoding='ascii')
    if GUARDAR_AUTH_CRUDO:
        (MUESTRAS / f"auth_{marca}.bin").write_bytes(bloque)
    if nota:
        (MUESTRAS / f"auth_{marca}.txt").write_text(nota, encoding='utf-8')


def _ahora():
    return time.time()


def personaje_de(cuenta, indice=0):
    from login import Personaje
    if not cuenta or indice >= len(cuenta.get('personajes', [])):
        return None
    p = cuenta['personajes'][indice]
    return Personaje(
        entity_id=1000 + p['char_id'] % 1000,
        char_id=p['char_id'],
        nombre=p['nombre'],
        tile_x=p['tile_x'], tile_y=p['tile_y'],
        habilidades=[tuple(x) for x in p['habilidades']],
        barra=list(p['barra']),
        quests=[tuple(x) for x in p['quests']],
        hp=p.get('hp', 205), hp_max=p.get('hp_max', 205),
        mp=p.get('mp', 154), mp_max=p.get('mp_max', 154),
        inventario={int(k): v for k, v in p.get('inventario', {}).items()},
        sp=max(0, min(int(p.get('sp') or 0), 10 * 1000)),
        mejoras={int(k): v for k, v in (p.get('mejoras') or {}).items()},
        checkpoint_stage=int((p.get('checkpoint') or {}).get('stage', 0)),
        checkpoint_x=int(((p.get('checkpoint') or {}).get('tile') or [0, 0])[0]),
        checkpoint_y=int(((p.get('checkpoint') or {}).get('tile') or [0, 0])[1]),
        cantidades={int(k): int(v) for k, v in p.get('cantidades', {}).items()},
        tutorial=p.get('tutorial', 0),
        oro=p.get('oro', 0),
        stage=p.get('stage_id', 51),
        faction=p.get('faction', 'Heaven'),
        nivel=p.get('nivel', 1),
        exp=p.get('exp', 0),
        banco={int(k): v for k, v in p.get('banco', {}).items()},
        banco_oro=int(p.get('banco_oro', 0)),
        album={str(k): int(v) for k, v in (p.get('album') or {}).items()},
        logros=[int(x) for x in (p.get('logros') or [])],
        cartas=[int(x) for x in (p.get('cartas') or [])],
        estrellas=[tuple(x) for x in (p.get('estrellas') or [])
                   if isinstance(x, (list, tuple)) and len(x) >= 2],
        casa={'muebles': [int(x) for x in
                          ((p.get('casa') or {}).get('muebles') or [])]},
        buffs={int(k): v for k, v in (p.get('buffs') or {}).items()
               if isinstance(v, dict) and v.get('fin', 0) > _ahora()},
        class_id=p.get('class_id', 0),
        creditos=int(p.get('creditos', 0) or 0),
        rango=max(1, min(20, int(p.get('rango', 1) or 1))),
        banco_habilidades={int(k): list(v) for k, v in p.get('banco_habilidades', {}).items()},
        hechizos_aprendidos=set(p.get('hechizos_aprendidos', [])),
        mascota=_cargar_mascota(p.get('mascota')),
        mascotas=_cargar_mascotas(p),
        apariencia=list(p.get('apariencia') or [0, 0, 0, 8, 8]),
    )


def _cargar_mascotas(p: dict) -> dict:
    res = {}
    for k, v in (p.get('mascotas') or {}).items():
        if isinstance(v, dict) and v.get('sprite'):
            res[str(k)] = _cargar_mascota(v)
    if p.get('mascota') and isinstance(p.get('mascota'), dict) and p['mascota'].get('sprite'):
        m_act = _cargar_mascota(p['mascota'])
        r_k = str(m_act.get('ranura') if m_act.get('ranura') is not None else m_act.get('item', '0'))
        if r_k not in res:
            res[r_k] = m_act
    return res


def _cargar_mascota(m) -> dict:
    if not isinstance(m, dict) or not m.get('sprite'):
        return {}
    import mascotas as _ms
    f = dict(m)
    f['fuera'] = False
    f['entidad'] = None
    sp = int(f.get('sprite') or 0)
    nv = max(1, int(f.get('nivel') or 1))
    d = _ms.ficha_de_sprite(sp)
    if d.get('tipo'):
        f['tipo'] = d['tipo']
    st = _ms.stats_de(sp, nv)
    for k, v in st.items():
        if k in ('hp', 'mp') and f.get(k, 0) > 0:
            continue
        f[k] = v
    f.setdefault('saciedad', 100)
    f.setdefault('intimidad', 60)
    f.setdefault('estrellas', 1)
    return f


def borrar_personaje(usuario: str, ranura: int):
    """Borra el personaje de esa ranura en SQLite. Devuelve su char_id o None."""
    with _LOCK:
        con = _get_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT char_id FROM personajes WHERE usuario = ? AND ranura = ?", (usuario, ranura))
            row = cur.fetchone()
            if not row:
                return None
            char_id = row[0]
            con.execute("DELETE FROM personajes WHERE usuario = ? AND ranura = ?", (usuario, ranura))
            con.commit()
            _notificar_cambio(inmediato=True)
            return char_id
        finally:
            con.close()


def guardar_inventario(usuario: str, char_id: int, bolsa: dict,
                       cantidades=None, mejoras=None):
    def _mut(p):
        p['inventario'] = {str(k): v for k, v in sorted(bolsa.items())}
        if mejoras is not None:
            p['mejoras'] = {str(k): v
                            for k, v in sorted(mejoras.items())
                            if v and (v.get('veces') or v.get('gemas')
                                      or v.get('extra') or v.get('vinculacion'))}
        if cantidades is not None:
            p['cantidades'] = {str(k): int(v)
                               for k, v in sorted(cantidades.items())
                               if int(v) > 1 and int(k) in bolsa}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_mejoras(usuario: str, char_id: int, mejoras: dict):
    if not usuario:
        return
    def _mut(p):
        p['mejoras'] = {str(k): v for k, v in sorted((mejoras or {}).items())
                        if v and (v.get('veces') or v.get('gemas')
                                  or v.get('extra') or v.get('vinculacion'))}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_checkpoint(usuario: str, char_id: int, stage: int, tx: int, ty: int):
    def _mut(p):
        p['checkpoint'] = {'stage': int(stage), 'tile': [int(tx), int(ty)]}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_habilidades(usuario: str, char_id: int, habilidades):
    def _mut(p):
        p['habilidades'] = [list(h) for h in habilidades]
        banco = p.setdefault('banco_habilidades', {})
        for h in habilidades:
            if isinstance(h, (list, tuple)) and len(h) >= 2:
                banco[str(h[0])] = [int(h[1]), int(h[2]) if len(h) > 2 else 0]
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_hechizos(usuario: str, char_id: int, hechizos):
    def _mut(p):
        p['hechizos_aprendidos'] = list(hechizos)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_banco_habilidades(usuario: str, char_id: int, banco: dict):
    def _mut(p):
        p['banco_habilidades'] = {str(k): list(v) for k, v in banco.items()}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_clase(usuario: str, char_id: int, class_id: int):
    def _mut(p):
        p['class_id'] = class_id
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_posicion(usuario: str, char_id: int, tile_x: int, tile_y: int):
    def _mut(p):
        p['tile_x'], p['tile_y'] = int(tile_x), int(tile_y)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_tutorial(usuario: str, char_id: int, etapa: int):
    def _mut(p):
        p['tutorial'] = int(etapa)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_quests(usuario: str, char_id: int, quests: list):
    if not usuario:
        return
    def _mut(p):
        p['quests'] = [list(q) for q in (quests or [])]
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_oro(usuario: str, char_id: int, oro: int):
    def _mut(p):
        p['oro'] = int(oro)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_barra(usuario: str, char_id: int, barra: list):
    def _mut(p):
        p['barra'] = list(barra)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_mapa(usuario: str, char_id: int, stage: int, tile_x: int, tile_y: int):
    def _mut(p):
        p['stage_id'] = int(stage)
        p['tile_x'], p['tile_y'] = int(tile_x), int(tile_y)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_faccion(usuario: str, char_id: int, faccion: str):
    def _mut(p):
        p['faction'] = faccion
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_progreso(usuario: str, char_id: int, nivel: int, exp: int,
                     hp: int = None, mp: int = None, habilidades: list = None,
                     hp_max: int = None, mp_max: int = None, sp: int = None,
                     buffs: dict = None):
    def _mut(p):
        p['nivel'] = int(nivel)
        p['exp'] = int(exp)
        if sp is not None:
            p['sp'] = max(0, int(sp))
        if buffs is not None:
            p['buffs'] = {str(k): v for k, v in (buffs or {}).items()
                          if isinstance(v, dict) and v.get('fin', 0) > 0}
        if hp is not None:
            p['hp'] = int(hp)
        if hp_max is not None:
            p['hp_max'] = int(hp_max)
        if mp is not None:
            p['mp'] = int(mp)
        if mp_max is not None:
            p['mp_max'] = int(mp_max)
        if habilidades is not None:
            p['habilidades'] = [list(h) for h in habilidades]
            banco = p.setdefault('banco_habilidades', {})
            for h in habilidades:
                if isinstance(h, (list, tuple)) and len(h) >= 2:
                    banco[str(h[0])] = [int(h[1]), int(h[2]) if len(h) > 2 else 0]
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_sistemas(usuario: str, char_id: int, p):
    def _mut(fila):
        fila['album'] = {str(k): int(v)
                         for k, v in (getattr(p, 'album', None) or {}).items()}
        fila['logros'] = sorted({int(x) for x in (getattr(p, 'logros', None) or [])})
        fila['cartas'] = sorted({int(x) for x in (getattr(p, 'cartas', None) or [])})
        fila['estrellas'] = [list(x) for x in (getattr(p, 'estrellas', None) or [])]
        fila['casa'] = {'muebles': [int(x) for x in
                                    ((getattr(p, 'casa', None) or {}).get('muebles') or [])]}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_banco(usuario: str, char_id: int, banco: dict):
    def _mut(p):
        p['banco'] = {str(k): v for k, v in sorted(banco.items())}
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_banco_oro(usuario: str, char_id: int, oro: int):
    def _mut(p):
        p['banco_oro'] = int(oro)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_buffs(usuario: str, char_id: int, buffs: dict):
    def _mut(p):
        p['buffs'] = buffs
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_mascota(usuario: str, char_id: int, mascota: dict, mascotas: dict = None):
    if not usuario:
        return
    def _mut(p):
        m_dict = p.setdefault('mascotas', {})
        if mascotas and isinstance(mascotas, dict):
            for k, v in mascotas.items():
                if isinstance(v, dict) and v.get('sprite'):
                    clean_v = {ck: cv for ck, cv in v.items() if ck not in ('entidad',)}
                    clean_v['fuera'] = False
                    m_dict[str(k)] = clean_v
        if mascota and isinstance(mascota, dict) and mascota.get('sprite'):
            limpia = {k: v for k, v in mascota.items() if k not in ('entidad',)}
            limpia['fuera'] = False
            p['mascota'] = limpia
            r_key = str(limpia.get('ranura') if limpia.get('ranura') is not None else limpia.get('item', '0'))
            m_dict[r_key] = limpia
        else:
            p.pop('mascota', None)
    _actualizar_personaje(usuario, char_id, _mut)


def guardar_rango(usuario: str, char_id: int, rango: int, creditos: int = None):
    if not usuario:
        return
    def _mut(p):
        p['rango'] = max(1, min(20, int(rango or 1)))
        if creditos is not None:
            p['creditos'] = int(creditos or 0)
    _actualizar_personaje(usuario, char_id, _mut)


# Inicializar base de datos y migrar si es necesario al importar el modulo
_init_db()
