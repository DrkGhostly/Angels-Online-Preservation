"""Genera server/plantillas/drops_monstruos.json desde serv_drop.xml, drop.xml y content.db."""
import json
import pathlib
import sqlite3
import xml.etree.ElementTree as ET

RAIZ = pathlib.Path(__file__).parent.parent


def main():
    serv_drops = {}
    rutas_xml = (
        'extracted_paks/update3/setting/eng/serv_drop.xml',
        'extracted_paks/UPDATE4/setting/eng/serv_drop.xml',
        'extracted_paks/UPDATE6/setting/eng/serv_drop.xml',
        'extracted_paks/UPDATE9/setting/eng/serv_drop.xml',
        'extracted_paks/update26/setting/eng/drop.xml',
    )
    for rel in rutas_xml:
        p = RAIZ / rel
        if not p.exists():
            continue
        tree = ET.parse(p)
        for e in tree.getroot():
            did = e.attrib.get('編號')
            if not did or not did.isdigit():
                continue
            items = []
            for idx in range(1, 21):
                it = e.attrib.get('item%d' % idx)
                cnt = e.attrib.get('count%d' % idx, '1')
                if it and it.isdigit() and int(it) > 0:
                    items.append([int(it), int(cnt) if cnt.isdigit() else 1])
            if items:
                serv_drops[str(int(did))] = items

    con = sqlite3.connect(RAIZ / 'corpus' / 'content.db')
    by_name = {}
    for mid, name, lv, did in con.execute('select id, name, level, drop_id from monster'):
        d_str = str(did or mid).strip()
        if d_str in serv_drops and name:
            nl = name.strip().lower()
            if nl not in by_name:
                by_name[nl] = serv_drops[d_str]

    por_nivel = {}
    tablas = ('item', 'item2', 'item3', 'item4', 'item5', 'item6', 'item7', 'item8', 'item9')
    cats_validas = (
        '劍', '刀', '斧', '錘', '锤', '槍', '弓', '弓箭', '彈弓', '杖', '影刃', '盾',
        '衣服', '頭飾', '手套', '鞋子', '披風', '飾品', '一般', '藥水', '食物'
    )
    excluidos = ('gm', 'test', 'voucher', 'stone', 'card', 'ticket', 'token', 'box', 'bag', 'egg', 'scroll')
    for t in tablas:
        try:
            rows = con.execute(
                'select id, 物品類別, 物品等級, 基本名稱 from %s where id glob "[0-9]*"' % t
            ).fetchall()
        except Exception:
            continue
        for iid, cat, lv, nom in rows:
            if not str(lv or '').isdigit():
                continue
            lv_i = int(lv)
            if lv_i < 1 or lv_i > 300:
                continue
            nom_s = str(nom or '')
            if cat not in cats_validas:
                continue
            if any(k in nom_s.lower() for k in excluidos):
                continue
            bucket = str((lv_i // 10) * 10)
            por_nivel.setdefault(bucket, [])
            if len(por_nivel[bucket]) < 40:
                por_nivel[bucket].append([int(iid), 1])

    out = {'drops': serv_drops, 'por_nombre': by_name, 'por_nivel': por_nivel}
    dest = RAIZ / 'server' / 'plantillas' / 'drops_monstruos.json'
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('Escrito:', dest, 'bytes:', dest.stat().st_size,
          'drops:', len(serv_drops), 'por_nombre:', len(by_name),
          'por_nivel:', len(por_nivel))


if __name__ == '__main__':
    main()
