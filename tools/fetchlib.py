"""Simple fetch layer: rate-limited, retrying HTTPS client for the miacso.ru mirror."""
import urllib.request, urllib.error, ssl, time, os, hashlib, json, threading

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

_ctx = ssl.create_default_context()

# --- rate limiting -----------------------------------------------------------
_lock = threading.Lock()
_last = [0.0]
MIN_INTERVAL = 0.6          # seconds between requests to the same host


def _throttle():
    with _lock:
        now = time.time()
        wait = MIN_INTERVAL - (now - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


class Fetcher:
    def __init__(self, cache_dir, retries=3, timeout=45, verbose=True):
        self.cache_dir = cache_dir
        self.retries = retries
        self.timeout = timeout
        self.verbose = verbose
        os.makedirs(cache_dir, exist_ok=True)
        self.stats = {'hit': 0, 'ok': 0, 'fail': 0, 'bytes': 0}

    def _cache_path(self, url):
        h = hashlib.sha1(url.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, h[:2], h + '.bin')

    def get(self, url, force=False):
        """Return (final_url, status, headers_dict, body_bytes) or raise."""
        cp = self._cache_path(url)
        mp = cp + '.json'
        if not force and os.path.exists(cp) and os.path.exists(mp):
            meta = json.load(open(mp, encoding='utf-8'))
            self.stats['hit'] += 1
            return meta['url'], meta['status'], meta['headers'], open(cp, 'rb').read()

        last_err = None
        for attempt in range(self.retries):
            _throttle()
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': UA,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                              'image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'identity',
                })
                r = urllib.request.urlopen(req, timeout=self.timeout, context=_ctx)
                body = r.read()
                final, status = r.geturl(), r.status
                headers = {k.lower(): v for k, v in r.headers.items()}
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                open(cp, 'wb').write(body)
                json.dump({'url': final, 'status': status, 'headers': headers},
                          open(mp, 'w', encoding='utf-8'))
                self.stats['ok'] += 1
                self.stats['bytes'] += len(body)
                return final, status, headers, body
            except urllib.error.HTTPError as e:
                last_err = e
                # client errors other than 429 are final: keep the response body
                if e.code not in (429, 500, 502, 503, 504):
                    body = b''
                    try:
                        body = e.read()
                    except Exception:
                        pass
                    headers = {k.lower(): v for k, v in (e.headers or {}).items()}
                    os.makedirs(os.path.dirname(cp), exist_ok=True)
                    open(cp, 'wb').write(body)
                    json.dump({'url': url, 'status': e.code, 'headers': headers},
                              open(mp, 'w', encoding='utf-8'))
                    self.stats['fail'] += 1
                    return url, e.code, headers, body
                time.sleep(2 + attempt * 3)
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt * 2)
        self.stats['fail'] += 1
        raise RuntimeError('fetch failed: %s (%s)' % (url, last_err))


def is_html(headers, body=b''):
    ct = (headers or {}).get('content-type', '').lower()
    if 'html' in ct or 'xml' in ct:
        return True
    if not ct or 'octet-stream' in ct:
        head = body[:400].lstrip().lower()
        return head.startswith(b'<!doctype html') or head.startswith(b'<html')
    return False
