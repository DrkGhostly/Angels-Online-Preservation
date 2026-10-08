"""Front-facing paper-doll layers for the item wiki.

item.原型外觀 -> doll.xml part ids -> shape/chr *_Wait.spr (EWSP of TLHS frames).
EWSP keeps a shared RGB565 palette; each TLHS frame is span-RLE with a hotspot
used to stack hat/weapon/body on one canvas.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
from pathlib import Path

from PIL import Image

from shp_icon import PAK_ORDER, rgb565

EXTRACT = Path(r"C:\Program Files (x86)\Angels Online\extracted")
DB = Path(__file__).resolve().parents[1] / "corpus" / "content.db"
WAIT_RE = re.compile(r"(\d+)_wait$", re.I)

SLOTS = (
    ("背部", "back"),
    ("身體", "body"),
    ("腳部", "feet"),
    ("手部", "hands"),
    ("頭部", "head"),
    ("主手", "main"),
    ("副手", "off"),
    ("座騎", "mount"),
    ("機甲", "mecha"),
)
DRAW = ("back", "body", "feet", "hands", "head", "main", "off", "mount", "mecha")
# 5 directions x 3 idle ticks. Index 4 is the other cardinal from the
# in-game default (usually the camera-facing view).
FRONT_DIR = 4


def ewsp_palette(data: bytes) -> list[tuple[int, int, int]]:
    pal_off = struct.unpack_from("<I", data, 16)[0]
    pal = [(0, 0, 0)] * 256
    for i in range(256):
        o = pal_off + i * 2
        if o + 2 <= len(data):
            pal[i] = rgb565(struct.unpack_from("<H", data, o)[0])
    return pal


def tlhs_chunks(data: bytes) -> list[bytes]:
    offs = []
    pos = 0
    while True:
        i = data.find(b"TLHS", pos)
        if i < 0:
            break
        offs.append(i)
        pos = i + 4
    out = []
    for i, start in enumerate(offs):
        end = offs[i + 1] if i + 1 < len(offs) else len(data)
        if end - start >= 80:
            out.append(data[start:end])
    return out


def decode_tlhs(blob: bytes, pal: list[tuple[int, int, int]]) -> tuple[Image.Image, tuple[int, int]] | None:
    if blob[:4] != b"TLHS" or len(blob) < 80:
        return None
    w, h = struct.unpack_from("<II", blob, 20)
    hx, hy = struct.unpack_from("<ii", blob, 28)
    px_off = struct.unpack_from("<I", blob, 44)[0]
    if w <= 0 or h <= 0 or w > 512 or h > 512:
        return None
    offs = [struct.unpack_from("<I", blob, 80 + i * 4)[0] for i in range(h)]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    for y in range(h):
        start = offs[y]
        end = offs[y + 1] if y + 1 < h else px_off
        p = start
        while p + 8 <= end and p + 8 <= len(blob):
            x, width = struct.unpack_from("<hh", blob, p)
            src = struct.unpack_from("<I", blob, p + 4)[0]
            p += 8
            if width < 0:
                break
            for k in range(int(width)):
                xx = x + k
                if xx < 0 or xx >= w or src + k >= len(blob):
                    continue
                idx = blob[src + k]
                if idx == 0:
                    continue
                r, g, b = pal[idx]
                pix[xx, y] = (r, g, b, 255)
    return img, (hx, hy)


def front_layer(path: Path) -> tuple[Image.Image, tuple[int, int]] | None:
    data = path.read_bytes()
    if data[:4] != b"EWSP":
        return None
    pal = ewsp_palette(data)
    chunks = tlhs_chunks(data)
    if not chunks:
        return None
    # Prefer the front cardinal; fall back to the first frame.
    for idx in (FRONT_DIR, FRONT_DIR + 5, FRONT_DIR + 10, 0):
        if idx < len(chunks):
            got = decode_tlhs(chunks[idx], pal)
            if got:
                return got
    return decode_tlhs(chunks[0], pal)


def index_wait(extract: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    by_num: dict[int, Path] = {}
    by_folder: dict[int, Path] = {}
    for pak in PAK_ORDER:
        chrdir = extract / pak / "shape" / "chr"
        if not chrdir.is_dir():
            continue
        for folder in chrdir.iterdir():
            if not folder.is_dir():
                continue
            digits = re.findall(r"\d+", folder.name)
            folder_id = int(digits[0]) if digits else None
            for path in folder.iterdir():
                if path.suffix.lower() != ".spr":
                    continue
                m = WAIT_RE.search(path.stem)
                if not m:
                    continue
                num = int(m.group(1))
                by_num[num] = path
                if folder_id is not None:
                    by_folder[folder_id] = path
    return by_num, by_folder


def resolve_part(part: int, by_num: dict[int, Path], by_folder: dict[int, Path]) -> Path | None:
    for n in (part, part + 10000, part + 20000, part + 100000, part + 200000):
        if n in by_num:
            return by_num[n]
    if part in by_folder:
        return by_folder[part]
    return None


def load_dolls(db: Path) -> dict[int, dict[str, int]]:
    dolls: dict[int, dict[str, int]] = {}
    if not db.exists():
        return dolls
    con = sqlite3.connect(db)
    cols = {c[1] for c in con.execute("pragma table_info(doll)")}
    fields = [c for c, _ in SLOTS if c in cols]
    if "id" not in cols or not fields:
        return dolls
    q = "select id," + ",".join(f'"{c}"' for c, _ in SLOTS if c in cols) + " from doll"
    for row in con.execute(q):
        try:
            did = int(row[0])
        except (TypeError, ValueError):
            continue
        parts = {}
        for name, val in zip(fields, row[1:]):
            try:
                n = int(float(val))
            except (TypeError, ValueError):
                continue
            if n:
                parts[dict(SLOTS)[name]] = n
        if parts:
            dolls[did] = parts
    return dolls


def item_looks(db: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    if not db.exists():
        return out
    con = sqlite3.connect(db)
    for table in ("item", "item2", "item3", "item4", "item5", "item6", "item7", "item8"):
        cols = {c[1] for c in con.execute(f"pragma table_info({table})")}
        if "id" not in cols or "原型外觀" not in cols:
            continue
        for iid, look in con.execute(f'select id, "原型外觀" from {table}'):
            try:
                out[int(iid)] = int(float(look))
            except (TypeError, ValueError):
                continue
    return out


def _bounds(layers: list[tuple[Image.Image, tuple[int, int]]]) -> tuple[int, int, int, int]:
    left = top = right = bot = 0
    for img, (hx, hy) in layers:
        w, h = img.size
        left = max(left, hx)
        top = max(top, hy)
        right = max(right, w - hx)
        bot = max(bot, max(0, h - hy))
    pad = 12
    return left + pad, top + pad, right + pad, bot + pad


def align(img: Image.Image, hot: tuple[int, int], ox: int, oy: int, cw: int, ch: int) -> Image.Image:
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    hx, hy = hot
    canvas.alpha_composite(img, (ox - hx, oy - hy))
    return canvas


def build_layers(extract: Path, dests: list[Path]) -> dict:
    by_num, by_folder = index_wait(extract)
    dolls = load_dolls(DB)
    looks = item_looks(DB)
    needed: set[int] = set()
    for parts in dolls.values():
        needed.update(parts.values())
    base_part = None
    for guess in (1191, 1201, 1157, 1):
        if resolve_part(guess, by_num, by_folder):
            needed.add(guess)
            base_part = guess
            break

    decoded: dict[int, tuple[Image.Image, tuple[int, int]]] = {}
    for part in sorted(needed):
        path = resolve_part(part, by_num, by_folder)
        if path is None:
            continue
        got = front_layer(path)
        if got:
            decoded[part] = got

    if not decoded:
        return {"base": None, "draw": list(DRAW), "parts": {}, "items": {}, "size": [160, 180]}

    left, top, right, bot = _bounds(list(decoded.values()))
    cw, ch = left + right, top + bot
    ox, oy = left, top

    aligned_imgs: dict[int, Image.Image] = {}
    for part, (img, hot) in decoded.items():
        aligned_imgs[part] = align(img, hot, ox, oy, cw, ch)
    # Crop to the dummy body, not the union of mounts/mecha (those blow the canvas).
    focus = aligned_imgs.get(base_part) if base_part else None
    box = list(focus.getbbox()) if focus and focus.getbbox() else None
    if box:
        pad_x, pad_y = 36, 28
        box = [
            max(0, box[0] - pad_x),
            max(0, box[1] - pad_y),
            min(cw, box[2] + pad_x),
            min(ch, box[3] + pad_y),
        ]
        aligned_imgs = {p: im.crop(box) for p, im in aligned_imgs.items()}
        cw, ch = box[2] - box[0], box[3] - box[1]

    for dest in dests:
        dest.mkdir(parents=True, exist_ok=True)
    resolved: dict[int, str] = {}
    for part, aligned in aligned_imgs.items():
        name = f"p{part}.png"
        for dest in dests:
            aligned.save(dest / name, optimize=True)
        resolved[part] = name

    dress: dict[str, dict[str, int]] = {}
    for iid, did in looks.items():
        parts = dolls.get(did)
        if not parts:
            continue
        usable = {k: v for k, v in parts.items() if v in resolved}
        if usable:
            dress[str(iid)] = usable

    base = resolved.get(base_part) if base_part else None
    return {
        "base": base,
        "draw": list(DRAW),
        "parts": resolved,
        "items": dress,
        "size": [cw, ch],
    }


def write_dress(extract: Path, dests: list[Path], json_paths: list[Path]) -> dict:
    info = build_layers(extract, dests)
    payload = {
        "base": info["base"],
        "draw": info["draw"],
        "items": info["items"],
        "size": info.get("size") or [160, 180],
    }
    text = json.dumps(payload, separators=(",", ":"))
    for path in json_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"  dress layers {len(info['parts'])}  items {len(info['items'])}  base {info['base']}")
    return info
