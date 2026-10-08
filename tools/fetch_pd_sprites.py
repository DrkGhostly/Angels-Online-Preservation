"""Download angelsonline.wiki paper-doll sprite atlases next to the catalog."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs" / "pd" / "sprites"
SHARE = ROOT / "share" / "items" / "pd" / "sprites"
JSON_PATH = ROOT / "docs" / "pd" / "client_pd_preview.json"
BASE = "https://angelsonline.wiki/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    urls = sorted({v["url"] for v in data["sprites"].values() if v.get("url")})
    DEST.mkdir(parents=True, exist_ok=True)
    SHARE.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", UA)]
    ok = skip = fail = 0
    for i, rel in enumerate(urls, 1):
        name = Path(rel).name
        dest = DEST / name
        if dest.exists() and dest.stat().st_size > 0:
            skip += 1
        else:
            try:
                with opener.open(BASE + rel, timeout=30) as src:
                    dest.write_bytes(src.read())
                ok += 1
            except Exception as e:
                fail += 1
                print("fail", rel, e)
        if dest.exists():
            share = SHARE / name
            if not share.exists():
                share.write_bytes(dest.read_bytes())
        if i % 100 == 0 or i == len(urls):
            print(f"  {i}/{len(urls)} ok={ok} skip={skip} fail={fail}")
    print("done", ok, "new", skip, "kept", fail, "failed")


if __name__ == "__main__":
    main()
