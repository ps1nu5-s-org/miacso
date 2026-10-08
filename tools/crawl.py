"""Breadth-first crawler that mirrors miacso.ru into a local tree.

Outputs:
  mirror/site/<url-path>          HTML pages (as served)
  mirror/files/<url-path>         non-HTML blobs (pdf, doc, xls, images, css, js, fonts)
  mirror/manifest.jsonl           one JSON record per fetched URL
  mirror/content/<slug>.md        extracted readable text per HTML page

Usage:  python crawl.py [--max N] [--resume] [--host miacso.ru]
"""
import os, sys, json, time, argparse, traceback, hashlib
from urllib.parse import urlsplit, unquote, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchlib import Fetcher, is_html          # noqa: E402
from htmllib import parse_html, normalise, same_site, host_of   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')
CACHE = os.path.join(ROOT, '_cache')

# local-path -> url that owns it. Lets the crawler detect when a redirect
# would make two different bodies fight over one file.
claimed = {}

# Windows refuses paths longer than MAX_PATH (260) unless long paths are
# enabled, so every generated path is kept well under it.
MAX_PATH_LEN = 245

# File extensions that identify a downloadable blob. '.html'/'htm' are
# deliberately absent: HTML pages are detected by Content-Type at fetch time
# and routed into mirror/site, so listing them here would misroute them.
BLOB_EXT = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.rtf', '.odt',
            '.ods', '.odp', '.txt', '.csv', '.zip', '.rar', '.7z', '.tar', '.gz',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico', '.webp', '.tif',
            '.tiff', '.css', '.js', '.woff', '.woff2', '.ttf', '.eot', '.otf',
            '.mp3', '.mp4', '.avi', '.wmv', '.flv', '.swf', '.xml', '.json',
            '.sig', '.eml', '.msg', '.vsd', '.vsdx', '.djvu'}

# /component/banners/click/N are ad click-through redirects that point at
# third-party ad servers; they hang until the socket times out, so skip them.
SKIP_PREFIX = ('/administrator', '/components/com_', '/component/banners',
               '/cli/', '/tmp/', '/cache/', '/logs/')

# Some Joomla components expose an effectively infinite URL space. The events
# calendar links to a day/week view for *every* date in every year, and each of
# those links to more, so a naive breadth-first walk never terminates.
# Policy: keep the month view (it carries the actual schedule), drop the rest.
CALENDAR_DROP = ('/day.listevents/', '/week.listevents/', '/icalrepeat.detail/',
                 '/icalrepeat.detail', '/day.listevents', '/week.listevents')

# Extensions that identify downloadable files rather than HTML pages.
HTML_LIKE_EXT = {'.php', '.html', '.htm', '.asp', '.aspx', '.jsp', '.cgi', '.shtml'}


def url_allowed(url, host):
    """Apply the URL-space policy: return False to leave a URL uncrawled."""
    path = urlsplit(url).path
    if any(d in path for d in CALENDAR_DROP):
        return False
    return True


def local_path_for(url, base_dir):
    """Map a URL to a safe local file path under base_dir.

    A path with no file extension is treated as a "directory URL": it becomes
    <path>/index.html so that sub-pages such as /home/kontakty can live
    alongside the parent page /home without a name collision.

    Long URL slugs are shortened with a hash suffix: Windows refuses paths
    beyond MAX_PATH, and this site has news/registry slugs well over 150 chars.
    The authoritative URL always stays in the manifest, so nothing is lost.
    """
    s = urlsplit(url)
    path = unquote(s.path)
    segs = [p for p in path.split('/') if p not in ('', '.', '..')]

    def clean(t):
        for ch in ':*?"<>|':
            t = t.replace(ch, '_')
        return t

    segs = [clean(p) for p in segs]

    # Decide the leaf filename. A "directory URL" -- the site root, a path
    # ending in '/', or an extensionless path such as /home -- is stored as
    # <path>/index.html. This is what lets the parent page /home coexist with
    # its children (/home/kontakty) without a file/directory name collision.
    if not segs:
        segs = ['index.html']
    else:
        leaf = segs[-1]
        dot = leaf.rfind('.')
        has_ext = dot > 0 and (len(leaf) - dot) <= 6 and leaf[dot + 1:].isalnum()
        if not has_ext:
            segs.append('index.html')

    if s.query:
        # keep query-addressed pages distinct, e.g. /index.php?option=com_x
        q = s.query.replace('/', '_').replace(':', '_').replace('*', '_')
        for ch in '?"<>|&=':
            q = q.replace(ch, '_')
        stem = segs[-1]
        b, e = os.path.splitext(stem)          # 'core.js' -> ('core', '.js')
        if e:
            segs[-1] = '%s__%s%s' % (b, q[:110], e)     # core__abc123.js
        else:
            segs[-1] = '%s__%s.html' % (stem, q[:110])  # index__abc123.html

    if not segs:
        segs = ['index.html']

    # Keep the whole path inside Windows' limit. Shorten each over-long
    # segment and append a hash of the full URL so distinct URLs stay distinct.
    tag = hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]
    # base_dir + separators + leaf filename must all fit; the reserve covers
    # 'index.html' appended later plus separator slack.
    budget = MAX_PATH_LEN - len(os.path.abspath(base_dir)) - 24
    out, used = [], 0
    for i, seg in enumerate(segs):
        last = (i == len(segs) - 1)
        room = budget - used - (len(segs) - i)   # reserve separator space
        if len(seg) > room:
            base_seg, ext = os.path.splitext(seg)
            keep = max(8, room - len(ext) - len(tag) - 2)
            seg = '%s-%s%s' % (base_seg[:keep], tag, ext)
        out.append(seg)
        used += len(seg) + 1
        if last:
            break
    segs = out

    safe = os.path.join(base_dir, *segs)
    ap = os.path.abspath(safe)
    if not ap.startswith(os.path.abspath(base_dir) + os.sep):
        raise ValueError('path escape: ' + url)
    if len(ap) > MAX_PATH_LEN:
        # belt and braces: never hand Windows a path it will reject
        raise ValueError('path too long (%d): %s' % (len(ap), url))
    return ap


def save(base_dir, url, body):
    p = local_path_for(url, base_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(body)
    return p


def slug_for(url):
    s = urlsplit(url)
    t = (s.path.strip('/') or 'index')
    if s.query:
        t += '_' + s.query
    t = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in t)
    return t[:150] or 'index'


# Extensions that are entry-point scripts rather than downloadable files.
# A URL ending in one of these may return a full HTML page (Joomla's
# index.php?option=...), so it must be crawled as HTML, not stored as a blob.
SCRIPT_EXT = {'.php', '.html', '.htm', '.asp', '.aspx', '.jsp', '.cgi', '.shtml'}


def extension_of(url):
    """Return the blob extension for url, or '' if it is an HTML page.

    Script/entry-point extensions return '' so that they are fetched and
    routed by Content-Type instead of being filed away as attachments.
    """
    p = urlsplit(url).path.lower()
    for e in sorted(BLOB_EXT, key=len, reverse=True):
        if p.endswith(e):
            return '' if e in SCRIPT_EXT else e
    return ''


def process_page(url, f, record, done, args, asset_queue, queued, external,
                 skipped, dead_hosts):
    """Fetch and mirror a single URL.

    Returns (n_html_delta, n_new_links, final_url) so the caller can keep
    counting. Raises only on unexpected errors; the caller isolates them.
    """
    final, status, headers, body = f.get(url)
    if status != 200:
        record({'url': url, 'status': status, 'final': final,
                'content_type': headers.get('content-type', '')})
        done.add(url)
        return 0, [], final

    # A redirect (e.g. /component/banners/click/N -> /home) means several
    # requested URLs can share one body. Store it under the canonical final
    # URL so the manifest never advertises two different sizes for one path.
    store_at = final
    redirected = normalise(final) != normalise(url)

    # Canonical storage is the final URL; the requested URL is recorded
    # separately. If the canonical slot is already taken by different content
    # (two distinct redirect sources), fall back to the requested URL's own
    # path so no two different bodies ever overwrite each other.
    canon = os.path.normcase(local_path_for(store_at, os.path.join(MIRROR, 'site')))
    if canon in claimed and claimed[canon] != url:
        store_at = url
    claimed[canon] = url

    ct = headers.get('content-type', '')
    if not is_html(headers, body):
        p = save(os.path.join(MIRROR, 'files'), store_at, body)
        record({'url': url, 'final': final, 'status': 200, 'kind': 'blob',
                'redirected': redirected, 'content_type': ct, 'bytes': len(body),
                'local': os.path.relpath(p, MIRROR).replace('\\', '/')})
        done.add(url)
        return 0, [], final

    p = save(os.path.join(MIRROR, 'site'), store_at, body)
    info, _txt = parse_html(body, final)

    # ---- extracted readable content ----------------------------------------
    cdir = os.path.join(MIRROR, 'content')
    os.makedirs(cdir, exist_ok=True)
    slug = slug_for(final)
    md = os.path.join(cdir, slug + '.md')
    with open(md, 'w', encoding='utf-8') as fh:
        fh.write('# %s\n\n' % (info['title'] or slug))
        fh.write('> source: %s\n\n' % final)
        if info['headings']:
            fh.write('## Заголовки\n\n')
            for lvl, h in info['headings']:
                if h:
                    fh.write('%s %s\n' % ('#' * min(6, lvl + 1), h))
            fh.write('\n')
        fh.write('## Текст\n\n')
        fh.write(info['text'] + '\n')
        if info['forms']:
            fh.write('\n## Формы\n\n')
            for act, meth, fields in info['forms']:
                fh.write('- %s %s\n' % (meth.upper(), act))
                for fl in fields:
                    fh.write('    - %s (%s)\n' % (fl['name'], fl['type']))
        if info['links']:
            fh.write('\n## Ссылки\n\n')
            for h, t in info['links']:
                fh.write('- [%s](%s)\n' % ((t or '').strip() or h, h))

    # ---- discover new targets ----------------------------------------------
    new = []
    for href, _t in info['links']:
        try:
            h = normalise(href)
        except Exception:
            continue
        # External origins are recorded, never crawled: following them would
        # pull in unrelated sites (minzdrav.midural.ru, egisz, ...).
        if not same_site(h, args.host):
            external.add(h)
            continue
        if not url_allowed(h, args.host):
            skipped.add(h)
            continue
        sp = urlsplit(h)
        if any(sp.path.startswith(x) for x in SKIP_PREFIX):
            continue
        # Do not queue hosts that have already proven unreachable: sibling
        # subdomains such as owncloud.miacso.ru time out on every URL, and
        # retrying each one costs minutes of socket timeouts.
        if host_of(h) in dead_hosts:
            skipped.add(h)
            continue
        if extension_of(h):
            if not args.no_assets:
                asset_queue.add(h)
            continue
        if h not in queued and h not in done:
            queued.add(h)
            new.append(h)
    if not args.no_assets:
        for a in info['assets']:
            try:
                an = normalise(a)
            except Exception:
                continue
            if same_site(an, args.host) and url_allowed(an, args.host) \
                    and an not in queued and an not in done:
                asset_queue.add(an)

    record({'url': url, 'final': final, 'status': 200, 'kind': 'html',
            'redirected': redirected, 'content_type': ct, 'bytes': len(body),
            'local': os.path.relpath(p, MIRROR).replace('\\', '/'),
            'content_md': os.path.relpath(md, MIRROR).replace('\\', '/'),
            'title': info['title'], 'n_links': len(info['links']),
            'n_assets': len(info['assets']), 'n_new': len(new)})
    done.add(url)
    return 1, new, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=100000)
    ap.add_argument('--host', default='miacso.ru')
    ap.add_argument('--seed', action='append', default=[])
    ap.add_argument('--no-assets', action='store_true')
    ap.add_argument('--fresh', action='store_true',
                    help='ignore any existing manifest/state and start over')
    args = ap.parse_args()

    os.makedirs(MIRROR, exist_ok=True)
    man_path = os.path.join(MIRROR, 'manifest.jsonl')
    state_path = os.path.join(MIRROR, 'crawl_state.json')

    if args.fresh:
        for p in (man_path, state_path, os.path.join(MIRROR, 'external_links.json')):
            if os.path.exists(p):
                os.remove(p)
        print('fresh start: cleared manifest and state', flush=True)

    # Mirror console output to a log file. Background jobs can be terminated
    # between turns, and a file log guarantees the run stays auditable.
    log = open(os.path.join(ROOT, 'crawl.log'), 'a', encoding='utf-8')

    def say(msg):
        print(msg, flush=True)
        log.write(msg + '\n')
        log.flush()

    done = set()
    if os.path.exists(man_path):
        for line in open(man_path, encoding='utf-8'):
            try:
                done.add(json.loads(line)['url'])
            except Exception:
                pass

    f = Fetcher(CACHE)
    man = open(man_path, 'a', encoding='utf-8')

    # rebuild the path-ownership map so a resumed run does not overwrite files
    # that a previous run already wrote
    for line in open(man_path, encoding='utf-8'):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('status') == 200 and r.get('local'):
            claimed[os.path.normcase(os.path.join(MIRROR, r['local']))] = r.get('url')

    def record(rec):
        man.write(json.dumps(rec, ensure_ascii=False) + '\n')
        man.flush()

    seeds = [normalise(u) for u in
             (args.seed or ['https://%s/home' % args.host])]

    # ---- resume state -------------------------------------------------------
    # The manifest alone is not enough to resume: it only lists finished URLs,
    # so the pages discovered but not yet fetched would be lost. Persist the
    # frontier (page queue, asset queue and external links) alongside it.
    state_path = os.path.join(MIRROR, 'crawl_state.json')
    queue, asset_queue, external, skipped = [], set(), set(), set()
    dead_hosts = set()
    if os.path.exists(state_path):
        try:
            st = json.load(open(state_path, encoding='utf-8'))
            queue = [u for u in st.get('queue', []) if u not in done]
            asset_queue = set(st.get('assets', []))
            external = set(st.get('external', []))
            skipped = set(st.get('skipped', []))
            dead_hosts = set(st.get('dead_hosts', []))
            say('resume: %d pages + %d assets pending'
                % (len(queue), len(asset_queue)))
        except Exception as e:
            say('resume state unreadable (%s); starting from seeds' % e)
    if not queue and not asset_queue:
        queue = [s for s in seeds if s not in done]
    queued = set(queue)
    n_html = 0
    host_failures = {}

    def save_state():
        try:
            json.dump({'queue': queue, 'assets': sorted(asset_queue),
                       'external': sorted(external), 'skipped': sorted(skipped),
                       'dead_hosts': sorted(dead_hosts)},
                      open(state_path, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass

    while queue and n_html < args.max:
        url = queue.pop(0)
        if url in done:
            continue
        parts = urlsplit(url)
        if not same_site(url, args.host):
            continue
        if any(parts.path.startswith(x) for x in SKIP_PREFIX):
            continue
        if not url_allowed(url, args.host):
            skipped.add(url)
            continue
        # per-URL isolation: one bad page must never abort the whole mirror
        try:
            delta, new, final = process_page(url, f, record, done, args,
                                             asset_queue, queued, external,
                                             skipped, dead_hosts)
        except Exception as e:
            record({'url': url, 'status': 'ERROR',
                    'error': '%s: %s' % (type(e).__name__, e),
                    'trace': traceback.format_exc()[-800:]})
            done.add(url)
            say('  !! %-60s %s' % (url[:60], e))
            # An unreachable sibling host will fail for every one of its URLs.
            # After two failures, stop queueing that host entirely.
            if '10060' in str(e) or 'getaddrinfo' in str(e):
                host_failures[host_of(url)] = host_failures.get(host_of(url), 0) + 1
                if host_failures[host_of(url)] >= 2:
                    dead_hosts.add(host_of(url))
                    say('  -- host marked unreachable: %s' % host_of(url))
            continue
        n_html += delta
        queue.extend(new)
        if n_html % 10 == 0:
            save_state()
        if delta:
            say('[%4d] %-64s +%d  q=%d a=%d' %
                (n_html, final[:64], len(new), len(queue), len(asset_queue)))
    save_state()

    # ---- assets / blobs -----------------------------------------------------
    say('\n=== downloading %d assets ===' % len(asset_queue))
    n_a = 0
    for a in sorted(asset_queue):
        if a in done:
            continue
        try:
            final, status, headers, body = f.get(a)
            if status != 200:
                record({'url': a, 'status': status, 'kind': 'asset',
                        'content_type': headers.get('content-type', '')})
            else:
                sub = 'site' if is_html(headers, body) else 'files'
                p = save(os.path.join(MIRROR, sub), final, body)
                record({'url': a, 'final': final, 'status': 200, 'kind': 'asset',
                        'content_type': headers.get('content-type', ''),
                        'bytes': len(body),
                        'local': os.path.relpath(p, MIRROR).replace('\\', '/')})
                n_a += 1
        except Exception as e:
            record({'url': a, 'status': 'ERROR', 'error': str(e), 'kind': 'asset'})
        done.add(a)
        if n_a and n_a % 25 == 0:
            say('  assets: %d' % n_a)

    man.close()
    ext_path = os.path.join(MIRROR, 'external_links.json')
    by_host = {}
    for u in sorted(external):
        by_host.setdefault(urlsplit(u).netloc, []).append(u)
    json.dump(by_host, open(ext_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    skipped_path = os.path.join(MIRROR, 'urls_skipped.json')
    json.dump(sorted(skipped), open(skipped_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    say('\nDONE html=%d assets=%d external_hosts=%d skipped=%d  fetch=%s'
        % (n_html, n_a, len(by_host), len(skipped), f.stats))
    log.close()


if __name__ == '__main__':
    main()
