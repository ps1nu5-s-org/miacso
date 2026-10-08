import urllib.request, ssl, sys, os

ctx = ssl.create_default_context()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': '*/*',
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        'Accept-Encoding': 'identity',
    })
    r = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return r.geturl(), r.status, r.read()

base = sys.argv[1] if len(sys.argv) > 1 else 'https://miacso.ru'
outdir = sys.argv[2] if len(sys.argv) > 2 else r'C:\Users\GlebovSD\Desktop\DS_workspace\miacso\_probe'
os.makedirs(outdir, exist_ok=True)

for path in ['/robots.txt', '/sitemap.xml', '/index.php?option=com_content', '/administrator/']:
    try:
        u, s, d = get(base + path)
        name = path.replace('/', '_').replace('?', '_').replace('&', '_').replace('=', '-')
        open(os.path.join(outdir, name + '.txt'), 'wb').write(d)
        print('OK  %-45s %s %6d -> %s' % (path, s, len(d), u))
    except Exception as e:
        print('ERR %-45s %s: %s' % (path, type(e).__name__, e))
