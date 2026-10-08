"""HTML parsing helpers built on the standard library (no external deps)."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote

_WS = re.compile(r'[ \t\r\n\f\v\u00a0]+')

# tags whose text content is never page content.
# NOTE: 'head' must NOT be listed here -- it wraps <title>, which we do want.
SKIP_TEXT = {'script', 'style', 'noscript', 'iframe', 'svg', 'template'}
# block-level elements -> newline boundaries in text extraction
BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
         'table', 'ul', 'ol', 'section', 'article', 'header', 'footer',
         'blockquote', 'td', 'th', 'hr', 'form', 'figure', 'figcaption', 'dd', 'dt'}


class Doc(HTMLParser):
    """Collects links, assets, forms, meta and de-duplicated visible text."""

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.links = []          # (href, text)
        self.assets = set()      # absolute urls of css/js/img/font/media
        self.forms = []          # (action, method, [field names])
        self.meta = {}
        self.title = ''
        self._title_parts = []
        self.headings = []       # (level, text)
        self.text_parts = []
        self._skip = 0
        self._cur_form = None
        self._cur_a = None
        self._cur_heading = None
        self._in_title = False

    # -- helpers -------------------------------------------------------------
    def _abs(self, url):
        if not url:
            return None
        url = url.strip()
        if url.startswith(('javascript:', 'mailto:', 'tel:', 'data:', '#')):
            return None
        return urljoin(self.base, url)

    # -- parser hooks --------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TEXT:
            self._skip += 1
            return
        if tag == 'title':
            self._in_title = True
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._cur_heading = [int(tag[1]), '']
        if tag == 'a' and a.get('href'):
            self._cur_a = [a['href'], '']
            u = self._abs(a['href'])
            if u:
                self.links.append((u, None, self._anchor_text_hint(a)))
        if tag == 'img':
            for k in ('src', 'data-src', 'data-original'):
                u = self._abs(a.get(k))
                if u:
                    self.assets.add(u)
                    break
            ss = a.get('srcset')
            if ss:
                for part in ss.split(','):
                    u = self._abs(part.strip().split(' ')[0])
                    if u:
                        self.assets.add(u)
        if tag == 'source':
            for k in ('src', 'srcset'):
                if a.get(k):
                    for part in a[k].split(','):
                        u = self._abs(part.strip().split(' ')[0])
                        if u:
                            self.assets.add(u)
        if tag == 'script' and a.get('src'):
            u = self._abs(a['src'])
            if u:
                self.assets.add(u)
        if tag == 'link':
            rel = (a.get('rel') or '').lower()
            if a.get('href') and any(r in rel for r in ('stylesheet', 'icon', 'font', 'preload')):
                u = self._abs(a['href'])
                if u:
                    self.assets.add(u)
        if tag == 'meta':
            key = a.get('name') or a.get('property') or a.get('http-equiv')
            if key:
                self.meta.setdefault(key.lower(), a.get('content', ''))
        if tag == 'form':
            self._cur_form = [self._abs(a.get('action')) or self.base,
                              (a.get('method') or 'get').lower(), []]
        if tag in ('input', 'select', 'textarea', 'button') and self._cur_form is not None:
            n = a.get('name')
            if n:
                self._cur_form[2].append({'name': n, 'type': a.get('type', tag)})
        if tag in BLOCK:
            self.text_parts.append('\n')

    def handle_endtag(self, tag):
        if tag in SKIP_TEXT:
            self._skip = max(0, self._skip - 1)
            return
        if tag == 'title':
            self._in_title = False
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') and self._cur_heading:
            self.headings.append((self._cur_heading[0],
                                  _WS.sub(' ', self._cur_heading[1]).strip()))
            self._cur_heading = None
        if tag == 'a' and self._cur_a:
            self._attach_anchor_text(_WS.sub(' ', self._cur_a[1]).strip())
            self._cur_a = None
        if tag == 'form' and self._cur_form:
            self.forms.append(tuple(self._cur_form))
            self._cur_form = None
        if tag in BLOCK:
            self.text_parts.append('\n')

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            # <title> lives in <head> and is metadata, not body content
            self._title_parts.append(data)
            return
        if self._cur_a is not None:
            self._cur_a[1] += data
        if self._cur_heading is not None:
            self._cur_heading[1] += data
        if data.strip():
            self.text_parts.append(data)

    # -- anchor text back-fill ----------------------------------------------
    _pending = None

    def _anchor_text_hint(self, attrs):
        return None

    def _attach_anchor_text(self, text):
        for i in range(len(self.links) - 1, -1, -1):
            if self.links[i][1] is None:
                h, _, _ = self.links[i]
                self.links[i] = (h, text, True)
                return

    # -- result --------------------------------------------------------------
    def result(self):
        # collapse whitespace but preserve paragraph breaks
        raw = ''.join(self.text_parts)
        lines = [_WS.sub(' ', ln).strip() for ln in raw.split('\n')]
        text, blank = [], 0
        for ln in lines:
            if ln:
                text.append(ln)
                blank = 0
            elif blank == 0 and text:
                text.append('')
                blank = 1
        return {
            'title': _WS.sub(' ', ''.join(self._title_parts)).strip(),
            'meta': self.meta,
            'links': [(h, t) for h, t, _ in self.links],
            'assets': sorted(self.assets),
            'forms': self.forms,
            'headings': self.headings,
            'text': '\n'.join(text).strip(),
        }


def parse_html(html_bytes, base_url):
    # the live site emits a UTF-8 BOM, which glues itself to the first tag
    # (<html>) and makes it unrecognisable to HTMLParser
    if html_bytes.startswith(b'\xef\xbb\xbf'):
        html_bytes = html_bytes[3:]
    enc = 'utf-8'
    m = re.search(rb'charset=["\']?([\w-]+)', html_bytes[:4000], re.I)
    if m:
        enc = m.group(1).decode('ascii', 'replace')
    try:
        txt = html_bytes.decode(enc, 'replace')
    except LookupError:
        txt = html_bytes.decode('utf-8', 'replace')
    d = Doc(base_url)
    try:
        d.feed(txt)
        d.close()
    except Exception:
        pass
    return d.result(), txt


def normalise(url, host=None):
    """Canonical form for de-duplication of crawl targets.

    Collapses trailing slashes, drops tracking/pagination parameters and
    normalises the host. By default the host is preserved so that links to
    other origins (e.g. pos.gosuslugi.ru) stay on their own origin; pass
    host= to force a specific one.
    """
    s = urlsplit(url)
    path = re.sub(r'/+', '/', s.path)
    if path != '/' and path.endswith('/'):
        path = path[:-1]
    if not path:
        path = '/'
    q = s.query
    if q:
        drop = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                'utm_content', 'start', 'limitstart', 'tmpl'}
        keep = [p for p in q.split('&')
                if p.split('=')[0].lower() not in drop]
        q = '&'.join(keep)
    if host is not None:
        netloc = host
    else:
        netloc = s.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
    return s._replace(scheme='https', netloc=netloc, path=path,
                      query=q, fragment='').geturl()


def host_of(url):
    return urlsplit(url).netloc.lower().split(':')[0]


def same_site(url, host):
    """True when url belongs to host or to one of its subdomains."""
    h = host_of(url)
    return h == host or h.endswith('.' + host)
