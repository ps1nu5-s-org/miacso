"""Rebuild the crawl frontier from HTML already on disk (no network).

Useful after an interrupted run whose crawl_state.json was lost: re-parses
every mirrored page and reconstructs the page queue, asset queue and external
link set exactly as the crawler would have.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmllib import parse_html, normalise, same_site   # noqa: E402
from crawl import extension_of, SKIP_PREFIX            # noqa: E402
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')
HOST = 'miacso.ru'


def main():
    man_path = os.path.join(MIRROR, 'manifest.jsonl')
    done = set()
    if os.path.exists(man_path):
        for line in open(man_path, encoding='utf-8'):
            try:
                done.add(json.loads(line)['url'])
            except Exception:
                pass

    pages, assets, external = [], set(), set()
    n = 0
    for base, _d, fs in os.walk(os.path.join(MIRROR, 'site')):
        for fn in fs:
            if not fn.lower().endswith(('.html', '.htm', '.php')):
                continue
            p = os.path.join(base, fn)
            raw = open(p, 'rb').read()
            info, _ = parse_html(raw, 'https://' + HOST + '/')
            # the source URL is recorded in the companion markdown file
            n += 1
            for href, _t in info['links']:
                try:
                    h = normalise(href)
                except Exception:
                    continue
                if not same_site(h, HOST):
                    external.add(h)
                    continue
                if any(urlsplit(h).path.startswith(x) for x in SKIP_PREFIX):
                    continue
                if extension_of(h):
                    assets.add(h)
                elif h not in done:
                    pages.append(h)
            for a in info['assets']:
                try:
                    an = normalise(a)
                except Exception:
                    continue
                if same_site(an, HOST):
                    assets.add(an)

    pages = sorted(set(pages) - done)
    assets = sorted(a for a in assets if a not in done)
    st = {'queue': pages, 'assets': assets, 'external': sorted(external)}
    json.dump(st, open(os.path.join(MIRROR, 'crawl_state.json'), 'w',
                       encoding='utf-8'), ensure_ascii=False)
    print('scanned %d mirrored html files' % n)
    print('done=%d  pending pages=%d  pending assets=%d  external=%d'
          % (len(done), len(pages), len(assets), len(external)))


if __name__ == '__main__':
    main()
