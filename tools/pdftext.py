"""Minimal, dependency-light PDF text extractor (stdlib zlib only).

Handles the two encodings that dominate this site's documents:
  * simple fonts with WinAnsiEncoding / StandardEncoding
  * subset TrueType/CID fonts using Identity-H with a /ToUnicode CMap

This is deliberately not a full PDF engine: it aims to recover readable
text for indexing and redesign research, not pixel-accurate layout.
"""
import re, zlib, sys, os, json

# ---------------------------------------------------------------- glyph maps
STD_WINANSI_HIGH = {
    0x91: '\u2018', 0x92: '\u2019', 0x93: '\u201c', 0x94: '\u201d',
    0x95: '\u2022', 0x96: '\u2013', 0x97: '\u2014', 0xa0: '\u00a0',
    0xa9: '\u00a9', 0xab: '\u00ab', 0xbb: '\u00bb', 0xb0: '\u00b0',
    0xb7: '\u00b7', 0x2116: '\u2116',
}


def winansi(b):
    """Decode a byte string as Windows-1251 (the site's Cyrillic encoding)."""
    try:
        return b.decode('cp1251')
    except Exception:
        return b.decode('latin-1', 'replace')


def _pdf_unescape(s):
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5c and i + 1 < len(s):           # backslash
            n = s[i + 1]
            simple = {0x6e: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
                      0x28: 40, 0x29: 41, 0x5c: 92}
            if n in simple:
                out.append(simple[n]); i += 2; continue
            if 0x30 <= n <= 0x37:                  # octal, up to 3 digits
                j, val = i + 1, 0
                while j < len(s) and j < i + 4 and 0x30 <= s[j] <= 0x37:
                    val = val * 8 + (s[j] - 0x30); j += 1
                out.append(val & 0xFF); i = j; continue
            i += 2; continue
        out.append(c); i += 1
    return bytes(out)


# ------------------------------------------------------------- content stream
_TEXT_SHOW = re.compile(rb'\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|\bTJ\b|\bTj\b|\bTd\b|\bTD\b|\bT\*\b|\bET\b', re.S)


def _decode_literal(tok):
    return _pdf_unescape(tok[1:-1])


def _decode_hex(tok):
    h = re.sub(rb'[^0-9A-Fa-f]', b'', tok[1:-1])
    if len(h) % 2:
        h += b'0'
    return bytes.fromhex(h.decode('ascii'))


def extract_text_from_stream(data, cmap=None):
    """Pull visible text out of a decoded PDF content stream."""
    lines, cur = [], []
    for m in _TEXT_SHOW.finditer(data):
        tok = m.group(0)
        if tok.startswith(b'('):
            raw = _decode_literal(tok)
            if cmap:
                cur.append(''.join(cmap.get(b, '') for b in raw))
            else:
                cur.append(winansi(raw))
        elif tok.startswith(b'<'):
            raw = _decode_hex(tok)
            if cmap:
                # Identity-H: two bytes per glyph
                for i in range(0, len(raw) - 1, 2):
                    code = (raw[i] << 8) | raw[i + 1]
                    cur.append(cmap.get(code, ''))
            else:
                cur.append(winansi(raw))
        elif tok in (b'Td', b'TD', b'T*', b'ET'):
            if cur:
                lines.append(''.join(cur)); cur = []
    if cur:
        lines.append(''.join(cur))
    return '\n'.join(l for l in lines if l.strip())


# ------------------------------------------------------------------- ToUnicode
def parse_tounicode(data):
    """Parse a /ToUnicode CMap into {code: char}."""
    cmap = {}
    txt = data
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar', txt, re.S):
        for src, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            code = int(src, 16)
            cmap[code] = _utf16be(dst)
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange', txt, re.S):
        for lo, hi, dst in re.findall(
                rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            a, b = int(lo, 16), int(hi, 16)
            start = _utf16be(dst)
            if len(start) == 1 and b - a < 65536:
                for k in range(a, b + 1):
                    cmap[k] = chr(ord(start) + (k - a))
            else:
                cmap[a] = start
    return cmap


def _utf16be(hexbytes):
    s = hexbytes.decode('ascii')
    if len(s) % 4:
        s = s.ljust((len(s) // 4 + 1) * 4, '0')
    try:
        raw = bytes.fromhex(s)
        return raw.decode('utf-16-be', 'ignore')
    except Exception:
        return ''


# ------------------------------------------------------------------ PDF object
_STREAM_RE = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.S)


def _inflate(chunk):
    for attempt in (chunk, chunk.strip()):
        try:
            return zlib.decompress(attempt)
        except Exception:
            pass
    try:                                   # skip a leading/truncated byte
        return zlib.decompressobj().decompress(chunk)
    except Exception:
        return None


def pdf_text(path, max_bytes=40 * 1024 * 1024):
    """Return extracted text for a PDF file, or '' when nothing is readable."""
    try:
        raw = open(path, 'rb').read(max_bytes)
    except Exception:
        return ''
    if not raw.startswith(b'%PDF'):
        return ''

    # 1. try to build a ToUnicode map from any embedded CMap
    cmap = {}
    for chunk in _STREAM_RE.findall(raw):
        if b'beginbfchar' in chunk or b'beginbfrange' in chunk:
            cmap.update(parse_tounicode(chunk))
        else:
            d = _inflate(chunk)
            if d and (b'beginbfchar' in d or b'beginbfrange' in d):
                cmap.update(parse_tounicode(d))
    use_cmap = cmap if len(cmap) > 20 else None

    # 2. decode every content stream and concatenate its text
    parts = []
    for chunk in _STREAM_RE.findall(raw):
        if b'beginbfchar' in chunk or b'beginbfrange' in chunk:
            continue
        d = chunk
        if b'BT' not in d[:4000]:
            d = _inflate(chunk)
            if d is None:
                continue
        if b'BT' not in d and b'Tj' not in d and b'TJ' not in d:
            continue
        t = extract_text_from_stream(d, use_cmap)
        if t:
            parts.append(t)
    return '\n'.join(parts)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    for p in sys.argv[1:]:
        t = pdf_text(p)
        print('=== %s (%d chars) ===' % (p, len(t)))
        print(t[:1500])
