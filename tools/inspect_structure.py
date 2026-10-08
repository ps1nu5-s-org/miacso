import sys, re, os, collections
sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
raw = open(os.path.join(ROOT, '_home_raw.html'), 'rb').read().decode('utf-8', 'replace')

print('=== h1-h6 ===')
for m in re.finditer(r'<(h[1-6])\b[^>]*>(.*?)</\1>', raw, re.S | re.I):
    t = re.sub(r'<[^>]+>', '', m.group(2)).strip()
    print(' %-3s | %s' % (m.group(1).lower(), t[:80]))

print('\n=== most common class attributes ===')
for c, n in collections.Counter(re.findall(r'class="([^"]*)"', raw)).most_common(15):
    print(' %3d  %s' % (n, c[:100]))

print('\n=== element id attributes ===')
print(collections.Counter(re.findall(r'\bid="([^"]*)"', raw)).most_common(25))

print('\n=== top-level structural tags ===')
for tag in ['header', 'nav', 'main', 'aside', 'footer', 'article', 'section', 'table', 'form', 'iframe']:
    print(' %-8s %d' % (tag, len(re.findall(r'<' + tag + r'\b', raw, re.I))))
