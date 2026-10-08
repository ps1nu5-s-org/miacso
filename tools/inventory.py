"""Build the redesign-preparation inventory from the mirror.

Produces, under mirror/:
  inventory.json    machine-readable summary of the whole site
  INVENTORY.md      human-readable report

Captures: site map, per-page metadata, attachments per page, external links,
contacts, tables, forms, downloadable document types and totals.
"""
import os, sys, re, json, collections, html
from urllib.parse import urlsplit
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from htmllib import same_site, host_of            # noqa: E402

EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
PHONE = re.compile(r'(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-]*\d{2}[\s\-]*\d{2}')
PHONE_SHORT = re.compile(r'\b\d{3}[\s-]\d{2}[\s-]\d{2}\b')


def load_manifest():
    p = os.path.join(MIRROR, 'manifest.jsonl')
    recs = []
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    return recs


def load_doc_index():
    p = os.path.join(MIRROR, 'doc_index.jsonl')
    out = {}
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    out[r['path']] = r
                except Exception:
                    pass
    return out


def analyse_page(md_path):
    """Pull structured facts out of one extracted content markdown file."""
    if not os.path.exists(md_path):
        return None
    txt = open(md_path, encoding='utf-8').read()
    title = ''
    m = re.match(r'#\s*(.+)', txt)
    if m:
        title = m.group(1).strip()
    body = txt
    if '## Текст' in txt:
        body = txt.split('## Текст', 1)[1]

    atts = sorted(set(re.findall(r'\((https?://[^)]+\.(?:pdf|docx?|xlsx?|pptx?|odt|ods|'
                                r'odp|rtf|zip|rar|7z|csv|txt))\)', txt, re.I)))
    ext_links = sorted(set(re.findall(r'\((https?://[^)]+)\)', txt)))
    ext_links = [u for u in ext_links if not same_site(u, 'miacso.ru')]
    emails = sorted(set(EMAIL.findall(body)))
    phones = sorted(set(PHONE.findall(body)) | set(PHONE_SHORT.findall(body)))
    return {
        'title': title,
        'chars': len(body),
        'words': len(body.split()),
        'attachments': atts,
        'external_links': ext_links,
        'emails': emails,
        'phones': phones,
        'has_form': '## Формы' in txt,
    }


def load_external():
    """Host -> [urls] collected by the crawler at discovery time."""
    p = os.path.join(MIRROR, 'external_links.json')
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding='utf-8'))
        except Exception:
            return {}
    return {}


def classify(url, title):
    """Group pages into a rough content model for the redesign."""
    p = urlsplit(url).path.strip('/')
    if p in ('', 'home'):
        return 'О центре'
    top = p.split('/')[0]
    return {
        'home': 'О центре', 'novosti': 'Новости', 'dokument': 'Документы',
        'materialy': 'Материалы', 'telemed': 'Телемедицина',
        'voprosy': 'Вопросы и ответы', 'informatsionnye-sistemy': 'Информационные системы',
        'egisso': 'ЕГИССО', 'sed-pso': 'СЭД ПСО', 'raspisanie-vks': 'Расписание ВКС',
        'index.php': 'Служебные / Joomla',
    }.get(top, 'Прочее: ' + (top or 'корень'))


def main():
    recs = load_manifest()
    docs = load_doc_index()

    pages, files, failures = [], [], []
    for r in recs:
        st = r.get('status')
        if st != 200:
            failures.append(r)
            continue
        if r.get('kind') == 'html':
            pages.append(r)
        else:
            files.append(r)

    # ---- page analysis -----------------------------------------------------
    page_info = []
    att_by_page = collections.OrderedDict()
    for r in pages:
        md_rel = r.get('content_md')
        md_abs = os.path.join(MIRROR, md_rel) if md_rel else None
        info = analyse_page(md_abs) if md_abs else None
        rec = dict(r)
        rec['analysis'] = info
        page_info.append(rec)
        if info and info['attachments']:
            att_by_page[r['url']] = info['attachments']

    page_info.sort(key=lambda x: x.get('url', ''))

    # ---- documents ---------------------------------------------------------
    doc_recs = []
    for r in files:
        local = r.get('local', '')
        di = docs.get(local, {})
        e = os.path.splitext(r.get('url', ''))[1].lower()
        doc_recs.append({
            'url': r.get('url'), 'local': local,
            'ext': e, 'bytes': r.get('bytes', 0),
            'content_type': r.get('content_type', ''),
            'chars': di.get('chars', 0), 'words': di.get('words', 0),
            'text_file': di.get('text_file', ''),
            'extract_error': di.get('error', ''),
        })
    doc_recs.sort(key=lambda x: x['url'] or '')

    # ---- next, rebuild the actual inventory --------------------------------
    all_atts = []
    for rec in page_info:
        if rec.get('analysis'):
            all_atts.extend(rec['analysis']['attachments'])
    att_set = sorted(set(all_atts))

    doc_urls = {d['url'] for d in doc_recs}
    missing = [a for a in att_set if a not in doc_urls]

    exts = collections.Counter(d['ext'] for d in doc_recs)

    # Prefer the crawler's discovery-time external link set; fall back to what
    # can be recovered from the extracted content markdown.
    ext_raw = load_external()
    ext_links = collections.Counter()
    if ext_raw:
        for h, urls in ext_raw.items():
            ext_links[h] = len(urls)
    else:
        for rec in page_info:
            for u in (rec.get('analysis') or {}).get('external_links', []):
                ext_links[urlsplit(u).netloc] += 1

    emails, phones = collections.Counter(), collections.Counter()
    for rec in page_info:
        a = rec.get('analysis') or {}
        for e in a.get('emails', []):
            emails[e] += 1
        for p in a.get('phones', []):
            phones[p] += 1

    total_bytes = sum(d['bytes'] for d in doc_recs)
    pages_with_text = sum(1 for r in page_info
                          if (r.get('analysis') or {}).get('chars', 0) > 200)
    empty_pages = [r['url'] for r in page_info
                   if (r.get('analysis') or {}).get('chars', 0) <= 200]

    inv = {
        'generated_from': 'https://miacso.ru',
        'pages_ok': len(page_info),
        'pages_with_content': pages_with_text,
        'pages_near_empty': empty_pages,
        'content_model': dict(collections.Counter(
            classify(r.get('url', ''), (r.get('analysis') or {}).get('title', ''))
            for r in page_info).most_common()),
        'documents_count': len(doc_recs),
        'documents_bytes': total_bytes,
        'documents_by_ext': dict(exts.most_common()),
        'attachment_links_total': len(all_atts),
        'attachment_links_unique': len(att_set),
        'attachments_not_mirrored': missing,
        'external_hosts': dict(ext_links.most_common()),
        'emails': dict(emails.most_common()),
        'phones': dict(phones.most_common()),
        'failures': [{'url': f.get('url'), 'status': f.get('status')} for f in failures],
        'sitemap': [{'url': r.get('url'), 'title': (r.get('analysis') or {}).get('title', ''),
                     'section': classify(r.get('url', ''),
                                         (r.get('analysis') or {}).get('title', '')),
                     'chars': (r.get('analysis') or {}).get('chars', 0),
                     'attachments': len((r.get('analysis') or {}).get('attachments', [])),
                     'local': r.get('local'), 'content_md': r.get('content_md')}
                    for r in page_info],
        'documents_count': len(doc_recs),
        'documents': doc_recs,
    }
    json.dump(inv, open(os.path.join(MIRROR, 'inventory.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    # ---- markdown report ---------------------------------------------------
    L = []
    A = L.append
    A('# Инвентаризация сайта miacso.ru\n')
    A('Источник: https://miacso.ru  \nСобрано страниц: **%d**  \n'
      'Файлов/документов: **%d** (%.1f МБ)\n' % (len(page_info), len(doc_recs),
                                                 total_bytes / 1048576.0))
    A('\n## 1. Карта сайта (%d страниц)\n' % len(page_info))
    A('| # | URL | Заголовок | Символов | Вложений |')
    A('|---|-----|-----------|---------:|---------:|')
    for i, r in enumerate(page_info, 1):
        a = r.get('analysis') or {}
        A('| %d | %s | %s | %d | %d |' % (
            i, r.get('url', ''), (a.get('title') or '')[:70],
            a.get('chars', 0), len(a.get('attachments', []))))

    A('\n## 2. Контентная модель (разделы для новой архитектуры)\n')
    A('| Раздел | Страниц | Символов всего | Вложений |')
    A('|--------|--------:|---------------:|---------:|')
    groups = collections.defaultdict(lambda: [0, 0, 0])
    for r in page_info:
        a = r.get('analysis') or {}
        g = classify(r.get('url', ''), a.get('title', ''))
        groups[g][0] += 1
        groups[g][1] += a.get('chars', 0)
        groups[g][2] += len(a.get('attachments', []))
    for g, (cnt, ch, at) in sorted(groups.items(), key=lambda kv: -kv[1][0]):
        A('| %s | %d | %d | %d |' % (g, cnt, ch, at))

    A('\n## 3. Внешние ресурсы\n')
    for h, n in ext_links.most_common():
        A('- %s — %d ссылок' % (h, n))

    A('\n## 4. Контактные данные\n')
    if phones:
        A('\n### Телефоны\n')
        for p, n in phones.most_common():
            A('- %s (%d)' % (p, n))
    if emails:
        A('\n### E-mail\n')
        for e, n in emails.most_common():
            A('- %s (%d)' % (e, n))

    A('\n## 5. Документы и вложения\n')
    A('| Расширение | Файлов |')
    A('|-----------|-------:|')
    for e, n in exts.most_common():
        A('| %s | %d |' % (e or '(нет)', n))
    if missing:
        A('\n### Ссылки на вложения, которые не удалось скачать (%d)\n' % len(missing))
        for u in missing[:60]:
            A('- %s' % u)

    nos = [d for d in doc_recs if d['chars'] == 0]
    A('\n### Документы без извлечённого текста (%d из %d)\n' % (len(nos), len(doc_recs)))
    for d in nos[:50]:
        A('- %s %s' % (d['url'], ('— ' + d['extract_error']) if d['extract_error'] else ''))

    A('\n## 6. Проблемы и битые ссылки\n')
    for f in failures:
        A('- %s → HTTP %s' % (f.get('url'), f.get('status')))
    if empty_pages:
        A('\n### Страницы почти без текста (%d)\n' % len(empty_pages))
        for u in empty_pages:
            A('- %s' % u)

    open(os.path.join(MIRROR, 'INVENTORY.md'), 'w', encoding='utf-8').write('\n'.join(L))
    print('pages=%d documents=%d failures=%d' % (len(page_info), len(doc_recs), len(failures)))
    print('wrote mirror/INVENTORY.md and mirror/inventory.json')


if __name__ == '__main__':
    main()
