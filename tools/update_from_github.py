"""Pull only the files that changed on GitHub main.

No zip, no second copy of the tree. Keeps accounts, corpus, launchers,
and local GM overlays. Re-hooks server/app.py afterwards.

    py -3 tools/update_from_github.py
    py -3 tools/update_from_github.py --check
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

REPO = 'SoulOfKarma/Angels-Online-Preservation'
BRANCH = 'main'
API = f'https://api.github.com/repos/{REPO}'
RAW = f'https://raw.githubusercontent.com/{REPO}/{BRANCH}'
UA = {'User-Agent': 'AO-Preservation-local-updater', 'Accept': 'application/vnd.github+json'}

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHA_FILE = ROOT / 'data' / '.upstream_sha'

# Never overwrite these. Prefix match for dirs.
PROTECT = (
    'corpus/',
    'data/cuentas.json',
    'data/gm.txt',
    'data/.upstream_sha',
    'content.db',
    'correr_servidor.bat',
    'server/gm.py',
    'tools/update_from_github.py',
    'tools/build_item_wiki.py',
    'update.bat',
    'share/',
)


def _protected(rel: str) -> bool:
    rel = rel.replace('\\', '/').lstrip('./')
    return any(rel == p.rstrip('/') or rel.startswith(p) for p in PROTECT)


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _json(url: str):
    return json.loads(_get(url).decode('utf-8'))


def latest_sha() -> str:
    data = _json(f'{API}/commits/{BRANCH}')
    return data['sha']


def current_sha() -> str:
    if SHA_FILE.exists():
        return SHA_FILE.read_text(encoding='utf-8').strip()
    return ''


def save_sha(sha: str):
    SHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHA_FILE.write_text(sha + '\n', encoding='utf-8')


def compare(old: str, new: str) -> dict:
    return _json(f'{API}/compare/{old}...{new}')


def fetch_raw(rel: str) -> bytes:
    url = f'{RAW}/{rel.replace(" ", "%20")}'
    req = urllib.request.Request(url, headers={'User-Agent': UA['User-Agent']})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def apply_file(rel: str, status: str) -> str:
    rel = rel.replace('\\', '/')
    dest = ROOT / rel
    if _protected(rel):
        return f'skip (local) {rel}'
    if status == 'removed':
        if dest.exists():
            dest.unlink()
            return f'deleted {rel}'
        return f'already gone {rel}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_raw(rel)
    dest.write_bytes(data)
    return f'{status} {rel} ({len(data)} B)'


def rehook() -> str:
    sys.path.insert(0, str(ROOT / 'server'))
    import gm
    if gm.apply_app_hooks(ROOT / 'server' / 'app.py'):
        return 're-applied GM hooks on server/app.py'
    return 'GM hooks already present'


def main():
    ap = argparse.ArgumentParser(description='Incremental update from GitHub main')
    ap.add_argument('--check', action='store_true', help='show pending commits, do not write')
    args = ap.parse_args()

    print(f'repo {REPO}@{BRANCH}')
    try:
        head = latest_sha()
    except urllib.error.HTTPError as e:
        print(f'GitHub API error {e.code}: {e.reason}')
        return 1
    old = current_sha()
    print(f'local  {old or "(none yet)"}')
    print(f'github {head}')
    if old == head:
        print('already up to date')
        if not args.check:
            print(rehook())
        return 0

    if not old:
        print('no saved SHA yet — fetching the file list of the latest commit only')
        print('next updates will download just the diff')
        if args.check:
            return 0
        # First pin: do not rewrite the tree we just overlaid.
        save_sha(head)
        print(rehook())
        print(f'pinned {head[:12]}')
        return 0

    try:
        info = compare(old, head)
    except urllib.error.HTTPError as e:
        print(f'compare failed {e.code}; GitHub may have rewritten history')
        print('re-run after I pin a new SHA, or tell me and we will resync')
        return 1

    files = info.get('files') or []
    ahead = info.get('ahead_by', 0)
    print(f'{ahead} commit(s), {len(files)} file(s)')
    if args.check:
        for f in files:
            print(f"  {f.get('status', '?'):8} {f.get('filename')}")
        return 0

    for f in files:
        rel = f.get('filename') or ''
        status = f.get('status') or 'modified'
        if status == 'renamed' and f.get('previous_filename'):
            prev = f['previous_filename']
            if not _protected(prev):
                oldp = ROOT / prev
                if oldp.exists():
                    oldp.unlink()
                    print(f'deleted {prev} (renamed)')
        print(' ', apply_file(rel, 'modified' if status == 'renamed' else status))

    print(rehook())
    save_sha(head)
    print(f'done. now at {head[:12]}')
    print('restart the server for the new code to load')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
