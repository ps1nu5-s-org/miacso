"""Extract readable text from every downloaded document/attachment.

Supports PDF (custom extractor), OOXML (docx/xlsx/pptx via stdlib zip+XML),
ODF (odt/ods/odp), plain text/csv, and falls back to a binary sniff that
reports what the file actually is.

Outputs:
  mirror/doc_text/<mirror-relative-path>.txt   extracted text
  mirror/doc_index.jsonl                       one record per document
"""
import os, sys, re, json, zipfile, html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdftext import pdf_text                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')
FILES = os.path.join(MIRROR, 'files')
OUT = os.path.join(MIRROR, 'doc_text')

TEXT_EXT = {'.txt', '.csv', '.json', '.xml', '.md', '.html', '.htm', '.log'}
OOXML = {'.docx': ('word/document.xml',),
         '.xlsx': ('xl/sharedStrings.xml',),
         '.pptx': ('ppt/slides/',)}
ODF = {'.odt': 'content.xml', '.ods': 'content.xml', '.odp': 'content.xml'}


def _clean(t):
    t = html.unescape(t)
    t = t.replace('\u00a0', ' ')
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n\s*\n\s*\n+', '\n\n', t)
    return t.strip()


def _xml_text(data):
    """Strip tags from XML, inserting breaks at paragraph-ish boundaries."""
    s = data.decode('utf-8', 'replace') if isinstance(data, bytes) else data
    s = re.sub(r'<(?:w:p|w:tr|a:p|text:p|text:h|table:table-row)[^>]*>', '\n', s)
    s = re.sub(r'<w:tab[^>]*/>', '\t', s)
    s = re.sub(r'<[^>]+>', '', s)
    return _clean(s)


def extract_ooxml(path, ext):
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return '', 'zip error: %s' % e
    parts, names = [], z.namelist()
    if ext == '.pptx':
        targets = sorted(n for n in names if re.match(r'ppt/slides/slide\d+\.xml$', n))
    elif ext == '.docx':
        targets = [n for n in names if n == 'word/document.xml']
    else:
        targets = [n for n in names if n == 'xl/sharedStrings.xml']
    for t in targets:
        try:
            parts.append(_xml_text(z.read(t)))
        except Exception:
            pass
    return _clean('\n\n'.join(parts)), ''


def extract_odf(path, member):
    try:
        z = zipfile.ZipFile(path)
        return _xml_text(z.read(member)), ''
    except Exception as e:
        return '', 'odf error: %s' % e


def extract_any(path, ext):
    ext = ext.lower()
    if ext == '.pdf':
        return _clean(pdf_text(path)), ''
    if ext in OOXML:
        return extract_ooxml(path, ext)
    if ext in ODF:
        return extract_odf(path, ODF[ext])
    if ext in TEXT_EXT:
        raw = open(path, 'rb').read()
        for enc in ('utf-8-sig', 'utf-8', 'cp1251', 'latin-1'):
            try:
                return _clean(raw.decode(enc)), ''
            except Exception:
                continue
        return '', 'decode failed'
    return '', 'unsupported type'


def sniff(path, n=8):
    try:
        head = open(path, 'rb').read(n)
    except Exception:
        return ''
    return head.hex()


def main():
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(MIRROR, 'doc_index.jsonl')
    done = set()
    if os.path.exists(idx_path):
        for line in open(idx_path, encoding='utf-8'):
            try:
                done.add(json.loads(line)['path'])
            except Exception:
                pass
    out = open(idx_path, 'a', encoding='utf-8')
    n_ok = n_empty = n_skip = 0

    targets = []
    for base, _d, fs in os.walk(FILES):
        for fn in fs:
            targets.append(os.path.join(base, fn))
    targets.sort()
    print('documents found: %d' % len(targets))

    for p in targets:
        rel = os.path.relpath(p, MIRROR).replace('\\', '/')
        if rel in done:
            continue
        ext = os.path.splitext(p)[1].lower()
        size = os.path.getsize(p)
        txt, err = '', ''
        try:
            txt, err = extract_any(p, ext)
        except Exception as e:
            err = '%s: %s' % (type(e).__name__, e)

        if txt:
            dst = os.path.join(OUT, rel + '.txt')
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'w', encoding='utf-8').write(txt)
            n_ok += 1
        else:
            n_empty += 1
        rec = {'path': rel, 'ext': ext, 'bytes': size,
               'chars': len(txt), 'words': len(txt.split()),
               'text_file': (rel + '.txt') if txt else '',
               'error': err, 'magic': sniff(p)}
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        if (n_ok + n_empty) % 25 == 0:
            print('  processed %d (text %d, empty %d)' % (n_ok + n_empty, n_ok, n_empty),
                  flush=True)
        n_skip += 1

    out.close()
    print('\nDONE documents=%d extracted=%d empty=%d' % (n_skip, n_ok, n_empty))


if __name__ == '__main__':
    main()
