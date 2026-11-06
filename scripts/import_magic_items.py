"""Build the magic item catalog from saved Archives of Nethys index pages."""
import argparse
import html
import json
from pathlib import Path
import re
from urllib.parse import quote

from import_equipment_index import CELL, ROOT, ROW, clean

LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
INLINE = re.compile(r'<h[12] class="title">(.*?)</h[12]>(.*?)(?=<h[12] class="title">|\Z)', re.S)
ITEM_URL = re.compile(r'^[A-Za-z]+\.aspx\?(?:ItemName|FinalName)=')
TABLE_FIELDS = {'Cost', 'Price', 'Base Price Modifier', 'Source (Possible Spoilers)', 'Weight', 'Slot', 'Type', 'CL', 'Strength', 'Shape'}


def content(directory, path):
    return (directory / path).read_text().split('id="main">', 1)[1]


def table_items(page):
    headers = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        if not cells:
            continue
        if re.search(r'<th\b', row):
            headers = [clean(cell) for cell in cells]
            continue
        link = LINK.search(cells[0])
        if not link or not ITEM_URL.match(link[1]):
            continue
        fields = {label: value for label, cell in zip(headers[1:], cells[1:])
                  if label in TABLE_FIELDS and (value := clean(cell))}
        yield clean(link[2]), html.unescape(link[1]), fields


def inline_items(page, path):
    for heading, body in INLINE.findall(page):
        name = clean(heading)
        link = LINK.search(heading)
        if link and ITEM_URL.match(link[1]):
            yield name, html.unescape(link[1]), {}
            continue
        fields = {}
        for label in ('Price', 'Cost', 'Weight', 'Slot'):
            value = re.search(rf'<b>{label}</b>\s*:?\s*([^;<]+)', body)
            if value and clean(value[1]):
                fields[label] = clean(value[1])
        yield name, f'{path}#:~:text={quote(name, safe="")}', fields


def load(directory):
    entries = {}
    nav = content(directory, 'MagicItems.aspx').split('</h1>', 1)[0]
    for path, label in LINK.findall(nav):
        group = clean(label)
        page = content(directory, path)
        sections = re.findall(r'<h2 style="text-align: center">(.*?)</h2>', page, re.S)
        subcategories = [link for section in sections for link in LINK.findall(section)]
        for branch, category in subcategories or [(path, '')]:
            leaf = content(directory, branch)
            items = list(table_items(leaf))
            if not items:
                # Skip the overview heading on inline lists and the set index.
                marker = ('MainContent_DetailedOutput' if branch == 'MagicSets.aspx'
                          else 'MainContent_DataListTypes_LabelName_')
                items = list(inline_items(leaf[leaf.index(marker):], branch))
            if not items:
                raise ValueError(f'No items found in {branch}')
            category = clean(category)
            print(f'{group} / {category or group}: {len(items)}')
            for name, href, fields in items:
                url = ROOT + quote(href, safe='/?=&%#:')
                key = (group, url, fields.get("Strength"))
                entry = entries.setdefault(key, dict(name=name, group=group, categories=[], url=url, fields=fields))
                for label, value in fields.items():
                    entry['fields'].setdefault(label, value)
                if category and category not in entry['categories']:
                    entry['categories'].append(category)
    return sorted(entries.values(), key=lambda item: (item['name'].casefold(), item['group'], item['url']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    items = load(args.directory)
    args.output.write_text('[\n' + ',\n'.join(f'  {json.dumps(item, ensure_ascii=False)}' for item in items) + '\n]\n')
    print(f'{len(items)} catalog entries')
