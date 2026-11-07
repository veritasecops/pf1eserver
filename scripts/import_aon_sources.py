"""Cache AoN detail pages and import their primary Source citation.

Run from the repository root. Re-running reuses successful cached responses.
Only source metadata is retained in the app, never rule descriptions.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote_plus, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'pathkeeper' / 'data'


def url_key(url):
    parts = urlsplit(url)
    return (parts.hostname or '').lower() + unquote_plus(parts.path + ('?' + parts.query if parts.query else '') + ('#' + parts.fragment if parts.fragment else '')).casefold()


def parse_source(html, url=''):
    # A feat/spell can have later Mythic or Combat Trick sections. The first
    # Source belongs to the record linked from the app.
    fragment = unquote_plus(urlsplit(url).fragment)
    if fragment.startswith(':~:text='):
        title = fragment.removeprefix(':~:text=').casefold()
        headings = list(re.finditer(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', html, re.I | re.S))
        for heading in headings:
            label = ' '.join(unescape(re.sub(r'<[^>]*>', '', heading[1])).split()).casefold()
            if label == title:
                html = html[heading.end():]
                # Do not borrow the next item's source if this item has none.
                html = re.split(r'<h[1-6]\b', html, maxsplit=1, flags=re.I)[0]
                break
        else:
            return ''
    elif fragment:
        return ''
    match = re.search(r'<b>\s*Sources?\s*</b>\s*(.*?)(?:<br\s*/?>|<h[1-6]\b|<b>)', html, re.I | re.S)
    if not match:
        return ''
    return re.sub(r'\s+,', ',', ' '.join(unescape(re.sub(r'<[^>]*>', ' ', match[1])).split()))


def urls():
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in {'legacy_urls', 'legacy_item_urls', 'legacy_deity_urls'}:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and value.startswith('https://www.aonprd.com/'):
            found.add(value)

    for path in DATA.glob('*.json'):
        if path.name not in {'aon_sources.json', 'aon_source_baseline.json', 'weapon_refresh_baseline.json'}:
            walk(json.loads(path.read_text()))
    for path in (ROOT / 'pathkeeper').glob('*.py'):
        found.update(re.findall(r'https://www\.aonprd\.com/[^\s\"\'<>}]+', path.read_text()))
    found = {url for url in found if not url.endswith('=') and '{' not in url}
    for race in ('Human', 'Dwarf', 'Elf', 'Gnome', 'Half-Elf', 'Half-Orc', 'Halfling'):
        found.add('https://www.aonprd.com/RacesDisplay.aspx?ItemName=' + race)
    return {url_key(url): url for url in sorted(found)}


def fetch(url, cache):
    url = url.split('#')[0]
    path = cache / (sha256(url_key(url).encode()).hexdigest() + '.html')
    if path.exists():
        return path.read_text()
    for attempt in range(4):
        try:
            request = Request(url, headers={'User-Agent': 'Pathkeeper source citation import'})
            with urlopen(request, timeout=45) as response:
                html = response.read().decode('utf-8-sig')
            if 'Archives of Nethys' not in html:
                raise ValueError('Unexpected response')
            path.write_text(html)
            return html
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    targets = urls()
    sources, missing, errors = {}, [], {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, url, args.cache): (key, url) for key, url in targets.items()}
        for count, future in enumerate(as_completed(futures), 1):
            key, url = futures[future]
            try:
                source = parse_source(future.result(), url)
                sources[key] = source
                if not source:
                    missing.append(url)
            except Exception as error:
                errors[url] = str(error)
            if count % 250 == 0:
                print(f'{count}/{len(targets)} citations={sum(bool(source) for source in sources.values())} missing={len(missing)} errors={len(errors)}', flush=True)
    (args.cache / 'missing.json').write_text(json.dumps(sorted(missing), indent=2))
    (args.cache / 'errors.json').write_text(json.dumps(errors, indent=2))
    (DATA / 'aon_sources.json').write_text(json.dumps(dict(sorted(sources.items())), ensure_ascii=False, indent=2) + '\n')
    if not errors:
        update_records(sources)
    print(f'Finished {len(targets)} URLs: {sum(bool(source) for source in sources.values())} citations, {len(missing)} without Source, {len(errors)} errors', flush=True)
    if errors:
        raise SystemExit(1)


def update_records(sources):
    """Store the citation on each shipped record as well as the URL index."""
    for name in ('weapons', 'armor', 'feats', 'spells', 'magic_items', 'equipment_index', 'deities', 'class_progressions'):
        path = DATA / (name + '.json')
        data = json.loads(path.read_text())
        entries = data.values() if isinstance(data, dict) else data
        for item in entries:
            if source := sources.get(url_key(item.get('url', ''))):
                item['source'] = source
        encode = lambda value: json.dumps(value, ensure_ascii=False)
        if name in {'spells', 'magic_items'}:
            text = '[\n' + ',\n'.join('  ' + encode(item) for item in data) + '\n]\n'
        elif name == 'equipment_index':
            text = '{\n' + ',\n'.join('  ' + encode(key) + ': ' + encode(item) for key, item in data.items()) + '\n}\n'
        elif name == 'class_progressions':
            rows = []
            for key, item in data.items():
                header = {key: value for key, value in item.items() if key != 'levels'}
                rows.append('  ' + encode(key) + ': ' + encode(header)[:-1] + ', "levels": [\n'
                            + ',\n'.join('    ' + encode(level) for level in item['levels']) + '\n  ]}')
            text = '{\n' + ',\n'.join(rows) + '\n}\n'
        else:
            text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        path.write_text(text)


if __name__ == '__main__':
    main()
