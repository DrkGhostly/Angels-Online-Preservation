"""Extract pet.xml + petskill.xml from the client into server/plantillas/pets.json.

Last-pak-wins, the same semantics as extract_content.py: a later pak replaces
a whole file, and inside the merged view a later row with the same id wins.

    py -3 tools/extract_pets.py [--extract "C:/Program Files (x86)/Angels Online/extracted"]

The server never reads the client folder at runtime: it loads the JSON this
writes, so the pack can be shared without the client install.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / 'tools'))
from shp_icon import PAK_ORDER  # noqa: E402

SALIDA = RAIZ / 'server' / 'plantillas' / 'pets.json'
EXTRACT = pathlib.Path(r"C:\Program Files (x86)\Angels Online\extracted")

REC = re.compile(r'<(pet|petskill)\s([^>]*?)/>', re.S)
ATR = re.compile(r'([^\s=]+)="([^"]*)"')

STAT_KEYS = {
    'HP': 'hp', 'MP': 'mp', '平均攻擊': 'atk', '防禦': 'def', '魔攻': 'matk',
    '魔防': 'mdef', '精準': 'acc', '靈敏': 'agi',
}


def _files(name: str):
    out = []
    for pak in PAK_ORDER:
        for folder in ('setting', 'SETTING'):
            for sub in ('eng', 'ENG'):
                for cand in (EXTRACT / pak / folder / sub / name,
                             EXTRACT / pak / folder / sub / name.upper()):
                    if cand.is_file() and cand not in out:
                        out.append(cand)
    return out


def _rows(path: pathlib.Path):
    txt = path.read_text(encoding='utf-8', errors='replace')
    for m in REC.finditer(txt):
        yield m.group(1), dict(ATR.findall(m.group(2)))


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def pet_row(a: dict) -> dict:
    stats, caps = {}, {}
    for zh, en in STAT_KEYS.items():
        if a.get(zh):
            stats[en] = _int(a[zh])
        if a.get(zh + '上限'):
            caps[en] = _int(a[zh + '上限'])
    skills = []
    for i in (1, 2, 3):
        v = _int(a.get(f'技能{i}階級表'))
        if v:
            skills.append(v)
    nxt = [v for v in (_int(a.get('升階變化1')), _int(a.get('升階變化2'))) if v]
    return {
        'name': a.get('名稱', ''),
        'sprite': _int(a.get('圖號1')),
        'portrait': _int(a.get('頭像編號')),
        'stage': a.get('階段', ''),
        'type': a.get('寵物類型', ''),
        'element': a.get('系別', ''),
        'exp_table': a.get('經驗等級表', ''),
        'next': nxt,
        'cond': _int(a.get('條件成長值')),
        'skills': skills,
        'stats': stats,
        'caps': caps,
        'move_speed': _int(a.get('移動速度'), 75),
        'atk_speed': _int(a.get('攻擊速度'), 100),
        'atk_range': _int(a.get('攻擊範圍'), 1),
        'crit': _int(a.get('重擊機率'), 5),
        'proj_ef': _int(a.get('投射特效')),
    }


def skill_row(a: dict) -> dict:
    ranks = []
    for i in range(1, 40):
        v = a.get(f'技能{i}級')
        if not v:
            break
        ranks.append(_int(v))
    return {'name': a.get('名稱', ''), 'type': a.get('技能類型', ''), 'ranks': ranks}


def main():
    global EXTRACT
    ap = argparse.ArgumentParser()
    ap.add_argument('--extract', default=str(EXTRACT))
    args = ap.parse_args()
    EXTRACT = pathlib.Path(args.extract)

    pets, skills, fuentes = {}, {}, []
    for f in _files('pet.xml'):
        fuentes.append(str(f.relative_to(EXTRACT)))
        for tag, a in _rows(f):
            if tag == 'pet' and a.get('編號'):
                pets[a['編號']] = pet_row(a)
    for f in _files('petskill.xml'):
        fuentes.append(str(f.relative_to(EXTRACT)))
        for tag, a in _rows(f):
            if tag == 'petskill' and a.get('編號'):
                skills[a['編號']] = skill_row(a)

    # Caught pets: a monster is capturable if some pet form uses its sprite.
    por_sprite = {}
    for pid, p in pets.items():
        if p['sprite']:
            por_sprite.setdefault(str(p['sprite']), []).append(int(pid))
    for k in por_sprite:
        por_sprite[k].sort()

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        'fuentes': fuentes,
        'pets': pets,
        'skills': skills,
        'por_sprite': por_sprite,
    }, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"{len(pets)} pets, {len(skills)} skill tables, "
          f"{len(por_sprite)} sprites -> {SALIDA} ({SALIDA.stat().st_size // 1024} KB)")


if __name__ == '__main__':
    main()
