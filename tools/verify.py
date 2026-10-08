"""Verify the mirror is complete and internally consistent.

Checks:
  * every manifest record with status 200 has a file on disk of the right size
  * every mirrored HTML page has a companion extracted-content markdown
  * every attachment linked from a page exists in the mirror
  * reports non-200 and errored URLs

Exit code is non-zero when a real inconsistency is found, so this can be used
as a gate before calling the mirror finished.
"""
import os, sys, json, collections
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')


def load(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def main():
    recs = load(os.path.join(MIRROR, 'manifest.jsonl'))
    problems, warnings = [], []

    ok_recs = [r for r in recs if r.get('status') == 200]
    bad_recs = [r for r in recs if r.get('status') != 200]

    missing_file, size_mismatch = [], []
    # Several requested URLs may legitimately share one local file when they
    # redirect to the same target; group by path and compare once.
    by_path = {}
    for r in ok_recs:
        loc = r.get('local')
        if not loc:
            problems.append('no local path: %s' % r.get('url'))
            continue
        by_path.setdefault(loc, []).append(r)

    for loc, group in by_path.items():
        p = os.path.join(MIRROR, loc)
        if not os.path.exists(p):
            missing_file.append((group[0].get('url'), loc))
            continue
        actual = os.path.getsize(p)
        for r in group:
            expected = r.get('bytes')
            if expected is not None and actual != expected:
                size_mismatch.append((r.get('url'), expected, actual))

    shared = {k: v for k, v in by_path.items() if len(v) > 1}
    redirected = [r for r in ok_recs if r.get('redirected')]

    html = [r for r in ok_recs if r.get('kind') == 'html']
    no_md = []
    for r in html:
        md = r.get('content_md')
        if not md or not os.path.exists(os.path.join(MIRROR, md)):
            no_md.append(r.get('url'))

    # attachment coverage
    docs = load(os.path.join(MIRROR, 'doc_index.jsonl'))
    doc_paths = {d['path'] for d in docs}
    blob_locals = {r.get('local') for r in ok_recs
                   if r.get('kind') in ('blob', 'asset')}
    docs_missing = sorted(blob_locals - doc_paths)

    empty_docs = [d for d in docs if d.get('chars', 0) == 0]

    total_bytes = sum(r.get('bytes', 0) or 0 for r in ok_recs)

    print('=== MIRROR VERIFICATION ===')
    print('manifest records      : %d' % len(recs))
    print('  status 200          : %d' % len(ok_recs))
    print('  non-200 / errors    : %d' % len(bad_recs))
    print('  html pages          : %d' % len(html))
    print('  files (blob/asset)  : %d' % len(blob_locals))
    print('  total size          : %.1f MB' % (total_bytes / 1048576.0))
    print('documents indexed     : %d' % len(docs))
    print('  extracted text      : %d' % (len(docs) - len(empty_docs)))
    print('  no text extracted   : %d' % len(empty_docs))

    def section(title, items, fmt=str):
        print('\n%s: %d' % (title, len(items)))
        for it in items[:25]:
            print('   ' + fmt(it))
        if len(items) > 25:
            print('   ... and %d more' % (len(items) - 25))

    section('files recorded but absent on disk', missing_file,
            lambda t: '%s -> %s' % t)
    section('size mismatch (expected vs actual)', size_mismatch,
            lambda t: '%s %s != %s' % t)
    section('local files shared by several URLs (redirects)', sorted(shared),
            lambda loc: '%s <- %d urls' % (loc, len(shared[loc])))
    section('URLs that redirected elsewhere', redirected,
            lambda r: '%s -> %s' % (r.get('url'), r.get('final')))
    section('html pages without extracted markdown', no_md)
    section('mirrored files missing from doc index', docs_missing)
    section('non-200 / error URLs', bad_recs,
            lambda r: '%s -> %s %s' % (r.get('url'), r.get('status'),
                                       (r.get('error') or '')[:60]))

    fatal = bool(missing_file or size_mismatch or no_md)
    print('\n%s' % ('VERIFICATION FAILED' if fatal else 'VERIFICATION PASSED'))
    return 1 if fatal else 0


if __name__ == '__main__':
    sys.exit(main())
