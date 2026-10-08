import re, io, sys

p = r'C:\Users\GlebovSD\Desktop\DS_workspace\miacso\_home_raw.html'
raw = open(p, 'rb').read()
txt = raw.decode('utf-8', 'replace')

out = []
out.append('=== LENGTH: %d bytes ===' % len(raw))
out.append('=== GENERRATOR/CMS ===')
for m in re.finditer(r'<meta[^>]+>', txt, re.I):
    out.append(m.group(0))

out.append('')
out.append('=== TITLE ===')
for m in re.finditer(r'<title[^>]*>(.*?)</title>', txt, re.I | re.S):
    out.append(m.group(1))

out.append('')
out.append('=== SCRIPT SRCs ===')
for m in re.finditer(r'<script[^>]*src=["\']([^"\']+)["\']', txt, re.I):
    out.append(m.group(1))

out.append('')
out.append('=== LINK HREFs ===')
for m in re.finditer(r'<link[^>]*href=["\']([^"\']+)["\']', txt, re.I):
    out.append(m.group(1))

out.append('')
out.append('=== IMG SRCs ===')
for m in re.finditer(r'<img[^>]*src=["\']([^"\']+)["\']', txt, re.I):
    out.append(m.group(1))

out.append('')
out.append('=== ALL HREFS on page ===')
seen = []
for m in re.finditer(r'<a[^>]*href=["\']([^"\']*)["\']', txt, re.I):
    h = m.group(1)
    if h not in seen:
        seen.append(h)
for h in seen:
    out.append(h)

open(r'C:\Users\GlebovSD\Desktop\DS_workspace\miacso\_home_links.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('written', len(out), 'lines')
