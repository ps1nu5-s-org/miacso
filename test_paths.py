"""Unit checks for URL -> local path mapping."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.crawl import local_path_for, slug_for, extension_of   # noqa: E402

BASE = r'C:\tmp\site'
cases = [
    'https://miacso.ru/home',
    'https://miacso.ru/home/kontakty',
    'https://miacso.ru/',
    'https://miacso.ru/novosti',
    'https://miacso.ru/novosti/video-novosti',
    'https://miacso.ru/index.php?option=com_content&view=article&id=5',
    'https://miacso.ru/Documents/files/otchet%202024.pdf',
    'https://miacso.ru/media/system/js/core.js?5afb64205f8b5f85ba3c4448aac10969',
    'https://miacso.ru/raspisanie-vks/month.calendar/2026/10/07/-',
    'https://miacso.ru/a/b/c/',
    'https://miacso.ru/templates/x/css/template.css',
]
seen = {}
ok = True
for u in cases:
    p = local_path_for(u, BASE)
    rel = os.path.relpath(p, BASE)
    assert os.path.abspath(p).startswith(os.path.abspath(BASE)), u
    clash = seen.get(p.lower())
    flag = 'CLASH with ' + clash if clash else ''
    if clash:
        ok = False
    seen[p.lower()] = u
    print('%-95s -> %s %s' % (u[:95], rel, flag))

print('\n=== extension detection ===')
for u, exp in [('https://miacso.ru/a/b.pdf', '.pdf'),
               ('https://miacso.ru/a/b.DOCX', '.docx'),
               ('https://miacso.ru/home', ''),
               ('https://miacso.ru/x.zip?y=1', '.zip'),
               # .html must NOT be a blob extension: HTML pages are routed
               # into mirror/site by Content-Type, not by filename
               ('https://miacso.ru/a/b.html', '')]:
    got = extension_of(u)
    print('%-40s %-8s %s' % (u, got, 'ok' if got == exp else 'EXPECTED ' + exp))
    ok = ok and got == exp

print('\n%s' % ('PATH MAPPING OK' if ok else 'PROBLEMS FOUND'))
sys.exit(0 if ok else 1)
