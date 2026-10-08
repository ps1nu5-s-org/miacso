"""Regression check for the HTML parser, using the saved homepage."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
sys.stdout.reconfigure(encoding='utf-8')
from htmllib import parse_html, normalise   # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
# fixture kept in tools/; fall back to the mirrored homepage if it is absent
FIX = os.path.join(ROOT, 'tools', '_home_raw.html')
if not os.path.exists(FIX):
    FIX = os.path.join(ROOT, 'mirror', 'site', 'home', 'index.html')
raw = open(FIX, 'rb').read()
info, _ = parse_html(raw, 'https://miacso.ru/home')

checks = []
checks.append(('title extracted', 'МИАЦ Свердловской области' in info['title']))
checks.append(('exact <title> string not leaked into body',
               info['title'] not in info['text']))
checks.append(('no script/css text leaked',
               'mootools' not in info['text'].lower()))
checks.append(('base href absent from body text', 'href=' not in info['text']))
checks.append(('headings captured incl. page title h2',
               any(t.strip() == 'О центре' for _l, t in info['headings'])))
checks.append(('links found', len(info['links']) > 50))
checks.append(('search form found',
               any(f[2] and f[2][0]['name'] == 'searchword' for f in info['forms'])))
checks.append(('anchor text attached',
               any(t and 'Контакты' in t for _h, t in info['links'])))
checks.append(('content body present', 'медицинский информационно-вычислительный центр' in info['text']))
checks.append(('normalise strips trailing slash',
               normalise('https://miacso.ru/home/') == 'https://miacso.ru/home'))
checks.append(('normalise forces https + bare host',
               normalise('http://www.miacso.ru/x') == 'https://miacso.ru/x'))
checks.append(('normalise drops limitstart',
               'limitstart' not in normalise('https://miacso.ru/novosti?limitstart=20&x=1')))

ok = True
for name, res in checks:
    print(('PASS  ' if res else 'FAIL  ') + name)
    ok = ok and res
print('\nTITLE: %s' % info['title'])
print('text chars: %d  links: %d  assets: %d  forms: %d  headings: %d' % (
    len(info['text']), len(info['links']), len(info['assets']),
    len(info['forms']), len(info['headings'])))
print('\n%s' % ('ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'))
sys.exit(0 if ok else 1)
