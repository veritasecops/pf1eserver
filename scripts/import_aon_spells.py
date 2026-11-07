"""Import names and structured spell-list metadata from cached AoN index HTML.

Input directory: index.html, All.html, Mythic.html, and one <Class>-schools.html
per class link, downloaded with SchoolSort=true. Supply detail-<encoded
ItemName>.html for entries missing from the class lists. Only SpellDisplay
links enter the catalog, so the separate Occult Rituals index is excluded.
"""
import argparse
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import quote


CLASS_LINK = re.compile(r'<a href="Spells\.aspx\?Class=([^"]+)">([^<]+)</a>')
INDEX_TOKEN = re.compile(
    r'<h2 class="title">([0-9])(?:st|nd|rd|th)?-Level</h2>'
    r'|<h3 class="framing">([^<]+)</h3>'
    r'|<a href="SpellDisplay\.aspx\?ItemName=([^"]+)">(.*?)</a>',
    re.S,
)
MARKER = re.compile(r'<sup>([FMRTY])</sup>')
ROOT = 'https://www.aonprd.com/SpellDisplay.aspx?ItemName='


def spell_rows(html):
    level = school = None
    for match in INDEX_TOKEN.finditer(html):
        raw_level, raw_school, item, label = match.groups()
        if raw_level is not None:
            level, school = int(raw_level), None
        elif raw_school:
            school = unescape(raw_school).strip()
        else:
            name = unescape(re.sub(r'<[^>]+>', '', MARKER.sub('', label)))
            yield unescape(item), ' '.join(name.split()), level, school, label


def fill_missing_details(spell, directory, class_names):
    item = spell['url'].removeprefix(ROOT)
    html = (directory / f'detail-{item}.html').read_text()
    school = re.search(r'<b>School</b>\s+(?:<u><a[^>]*>)?([a-z]+)', html, re.I)
    if not school:
        raise ValueError(f'Missing published school for {item}')
    spell['schools'] = [school[1].capitalize()]
    level = re.search(r'<b>School</b>(?:(?!<h3).)*?<b>Level</b>\s*([^<]+)', html, re.S)
    if level:
        for name, number in re.findall(r'([a-z -]+) ([0-9])', level[1], re.I):
            if label := class_names.get(name.strip().casefold()):
                spell['levels'].setdefault(label, []).append(int(number))


def convert(directory):
    classes = CLASS_LINK.findall((directory / 'index.html').read_text())
    spells = {}

    def add_rows(path, class_name=None, mythic=False):
        found = False
        for item, name, level, school, label in spell_rows(path.read_text()):
            found = True
            key = item.casefold()
            spell = spells.setdefault(key, {
                'name': name, 'url': ROOT + quote(item, safe=''), 'schools': [],
                'levels': {}, 'mythic': False, 'pfs_marked': False, 'markers': [],
            })
            spell['mythic'] |= mythic
            spell['pfs_marked'] |= 'PathfinderSocietySymbol.gif' in label
            spell['markers'] = sorted(set(spell['markers']) | set(MARKER.findall(label)))
            if class_name:
                if level is None:
                    raise ValueError(f'Missing spell level for {class_name}: {name}')
                levels = spell['levels'].setdefault(class_name, [])
                if level not in levels:
                    levels.append(level)
                if school and school not in spell['schools']:
                    spell['schools'].append(school)
        if not found:
            raise ValueError(f'No spell entries in {path.name}')

    add_rows(directory / 'All.html')
    add_rows(directory / 'Mythic.html', mythic=True)
    for key, label in classes:
        if key not in {'All', 'Mythic'}:
            add_rows(directory / f'{unescape(key)}-schools.html', class_name=unescape(label))
    class_names = {unescape(label).casefold(): unescape(label) for key, label in classes}
    for spell in spells.values():
        if not spell['schools']:
            fill_missing_details(spell, directory, class_names)
    return sorted(spells.values(), key=lambda item: (item['name'].casefold(), item['url']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    records = convert(args.directory)
    lines = ',\n'.join('  ' + json.dumps(record, ensure_ascii=False) for record in records)
    args.output.write_text('[\n' + lines + '\n]\n')
    print(f'Imported {len(records)} spells.')
