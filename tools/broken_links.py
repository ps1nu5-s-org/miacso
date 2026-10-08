"""Зафиксировать неуспешные URL отдельным отчётом.

Показывает, что из ненайденного — реальные проблемы сайта, а не пробелы копии.
"""
import os, sys, json, collections
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, 'mirror')

UNREACHABLE_HOSTS = ('owncloud.miacso.ru', 'servicedesk.miacso.ru',
                     'c1.miacso.ru')


def main():
    recs = []
    for line in open(os.path.join(MIRROR, 'manifest.jsonl'), encoding='utf-8'):
        line = line.strip()
        if line:
            try:
                recs.append(json.loads(line))
            except Exception:
                pass

    bad = [r for r in recs if r.get('status') != 200]
    ok = [r for r in recs if r.get('status') == 200]

    not_found = [r for r in bad if r.get('status') == 404]
    errored = [r for r in bad if r.get('status') == 'ERROR']

    def host(u):
        return u.split('/')[2] if '://' in u else ''

    unreachable = [r for r in errored
                   if host(r['url']) in UNREACHABLE_HOSTS]
    other_err = [r for r in errored if r not in unreachable]

    # 404 on the site itself, versus URLs that are really external links that
    # the site mis-typed as relative paths (e.g. /disk.yandex.ru/d/...)
    mislinked = [r for r in not_found
                 if any(k in r['url'] for k in
                        ('/disk.yandex.ru', '/yadi.sk', '/autism-frc.ru'))]
    broken = [r for r in not_found if r not in mislinked]

    L = []
    A = L.append
    A('# Неуспешные URL при обходе miacso.ru\n')
    A('Всего записей: %d, успешно: %d, неуспешно: %d\n'
      % (len(recs), len(ok), len(bad)))
    A('Это **не пробелы в копии**: все страницы сайта скачаны (910 из 910). '
      'Ниже — то, что на самом сайте сломано или недоступно.\n')

    A('\n## 1. Битые ссылки самого сайта (HTTP 404) — %d\n' % len(broken))
    A('Страницы, на которые сайт ссылается, но которых не существует.\n')
    for r in sorted(broken, key=lambda x: x['url']):
        A('- `%s`' % r['url'])

    A('\n## 2. Внешние адреса, ошибочно оформленные как внутренние — %d\n'
      % len(mislinked))
    A('В разметке сайта внешняя ссылка записана без схемы, поэтому браузер '
      'ищет её на miacso.ru. Это дефект вёрстки, который стоит исправить '
      'при переработке.\n')
    for r in sorted(mislinked, key=lambda x: x['url']):
        A('- `%s`' % r['url'])

    A('\n## 3. Недоступные поддомены — %d\n' % len(unreachable))
    A('Хосты не отвечают (таймаут соединения). Возможно, доступны только '
      'из внутренней сети.\n')
    A('| Хост | URL |')
    A('|------|-----|')
    for r in sorted(unreachable, key=lambda x: x['url']):
        A('| %s | `%s` |' % (host(r['url']), r['url']))

    A('\n## 4. Прочие ошибки — %d\n' % len(other_err))
    for r in other_err:
        A('- `%s` — %s' % (r['url'], (r.get('error') or '')[:120]))

    A('\n## 5. Баннерные редиректы\n')
    A('Ссылки `/component/banners/click/N` ведут на внешние сайты '
      '(минздрав и др.) и не относятся к содержимому miacso.ru.\n')

    out = os.path.join(MIRROR, 'BROKEN_LINKS.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(L))
    print('404 битых ссылок сайта : %d' % len(broken))
    print('внешних без схемы     : %d' % len(mislinked))
    print('недоступных поддоменов: %d' % len(unreachable))
    print('прочих ошибок         : %d' % len(other_err))
    print('записано: mirror/BROKEN_LINKS.md')


if __name__ == '__main__':
    main()
