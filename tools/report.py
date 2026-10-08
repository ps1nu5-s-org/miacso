"""Summarise the mirror manifest: counts, failures, biggest files."""
import sys, os, json, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
man = os.path.join(ROOT, 'mirror', 'manifest.jsonl')

recs = []
if os.path.exists(man):
    for line in open(man, encoding='utf-8'):
        line = line.strip()
        if line:
            try:
                recs.append(json.loads(line))
            except Exception:
                pass

print('records: %d' % len(recs))
print('by kind    :', dict(collections.Counter(r.get('kind', '?') for r in recs)))
print('by status  :', dict(collections.Counter(str(r.get('status')) for r in recs)))
print('by ctype   :')
for c, n in collections.Counter(
        (r.get('content_type') or '').split(';')[0] for r in recs).most_common(20):
    print('   %5d  %s' % (n, c or '(none)'))

fails = [r for r in recs if r.get('status') != 200]
print('\n=== non-200 (%d) ===' % len(fails))
for r in fails[:40]:
    print(' %-6s %-30s %s' % (r.get('status'), (r.get('content_type') or '')[:30],
                              (r.get('url') or '')[:100]))
    if r.get('error'):
        print('        error: %s' % str(r['error'])[:160])

html = [r for r in recs if r.get('kind') == 'html']
print('\n=== html pages (%d) ===' % len(html))
for r in sorted(html, key=lambda x: x.get('url', '')):
    print(' %-62s %6s  %s' % ((r.get('url') or '')[:62],
                              r.get('bytes'), (r.get('title') or '')[:60]))

blobs = [r for r in recs if r.get('kind') in ('blob', 'asset')]
print('\n=== files/assets: %d ===' % len(blobs))
byt = collections.Counter()
for r in blobs:
    e = os.path.splitext(r.get('url', ''))[1].lower()
    byt[e] += 1
print(' by ext:', dict(byt.most_common(25)))
tot = sum(r.get('bytes', 0) for r in recs)
print('\ntotal bytes: %.1f MB' % (tot / 1048576.0))
