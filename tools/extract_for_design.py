"""Извлечь реальный контент страниц для прототипов вёрстки."""
import re, os, sys, json, html as H
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def body_text(path, count=90):
    raw = open(path, encoding='utf-8', errors='replace').read()
    raw = re.sub(r'<script.*?</script>', ' ', raw, flags=re.S | re.I)
    raw = re.sub(r'<style.*?</style>', ' ', raw, flags=re.S | re.I)
    # ограничиваем областью основного контента
    m = re.search(r'<div[^>]*class="[^"]*art-postcontent[^"]*"[^>]*>', raw, re.I)
    if m:
        raw = raw[m.start():]
    raw = re.sub(r'<br\s*/?>', '\n', raw, flags=re.I)
    raw = re.sub(r'</(p|div|li|tr|h[1-6]|td)>', '\n', raw, flags=re.I)
    raw = re.sub(r'<[^>]+>', '', raw)
    txt = H.unescape(raw).replace('\u00a0', ' ')
    lines = [' '.join(l.split()) for l in txt.split('\n')]
    out, blank = [], 0
    for l in lines:
        if l:
            out.append(l); blank = 0
        elif blank == 0 and out:
            out.append(''); blank = 1
    return [l for l in out if l][:count]


for name, rel in [('КОНТАКТЫ', 'mirror/site/home/kontakty/index.html'),
                  ('НОВОСТИ', 'mirror/site/novosti/index.html'),
                  ('О ЦЕНТРЕ', 'mirror/site/home/index.html')]:
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    print('\n' + '=' * 70)
    print('=== %s ===' % name)
    print('=' * 70)
    if not os.path.exists(p):
        print('нет файла', p); continue
    for l in body_text(p, 60):
        print(l)
