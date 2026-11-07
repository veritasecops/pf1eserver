"""Update the weapon catalog from cached AoN index memberships and detail HTML.

The manifest maps detail URLs to [filename, index groups]. Existing IDs and
priced variants remain stable. Only fields before Description are extracted.
"""
from decimal import Decimal
from fractions import Fraction
from html import unescape
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote


DETAIL = re.compile(r'id="MainContent_DataListTypes_LabelName_\d+">(.*?)</span>\s*</td>', re.S)
FIELDS = re.compile(r'<b>([^<]+)</b>')
COINS = {'cp': 1, 'sp': 10, 'gp': 100, 'pp': 1000}


def clean(html):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', html)).split())


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.casefold()).strip('-')


def numeric_cost(value):
    match = re.fullmatch(r'([\d,]+(?:\.\d+)?)\s+(cp|sp|gp|pp)', value)
    return int(Decimal(match[1].replace(',', '')) * COINS[match[2]]) if match else 0 if value == '—' else None


def numeric_weight(value):
    match = re.fullmatch(r'([\d./]+)\s+lbs?\.?', value)
    return float(Fraction(match[1])) if match else 0 if value == '—' else None


def parse(html):
    detail, = DETAIL.findall(html)
    facts = re.split(r'<h3[^>]*>Description</h3>', detail, maxsplit=1)[0]
    title = clean(re.search(r'<h1[^>]*>(.*?)</h1>', facts, re.S)[1])
    facts = re.sub(r'<h3[^>]*>Statistics</h3>', '', facts)
    fields = FIELDS.split(facts)
    stats = {label: clean(value).rstrip(';') for label, value in zip(fields[1::2], fields[2::2])}
    category = slug(stats.pop('Category'))
    proficiency = stats.pop('Proficiency', '')
    price = stats.pop('Cost', '') or stats.pop('Price', '')
    weight = stats.pop('Weight')
    damage = stats.pop('Damage', '')
    sizes = re.fullmatch(r'(.+?)\s*\(small\),\s*(.+?)\s*\(medium\)', damage, re.I)
    item = {
        'category': category, 'detail_proficiency': proficiency,
        'cost': numeric_cost(price), 'cost_text': price,
        'weight': numeric_weight(weight), 'weight_text': weight,
        'small_damage': sizes[1] if sizes else '', 'damage': sizes[2] if sizes else damage,
        'critical': stats.pop('Critical', ''), 'range': stats.pop('Range', ''),
        'damage_type': stats.pop('Type', ''), 'special': stats.pop('Special', ''),
        'source': re.sub(r'\s+,', ',', stats.pop('Source')),
        'weapon_groups': [group.strip() for group in stats.pop('Weapon Groups', '').split(';') if group.strip()],
        'detail_stats': stats,
    }
    if 'PathfinderSocietySymbol.gif' in facts:
        stats['PFS'] = 'Legal'
    elif 'PathfinderSocietySymbolN.gif' in facts:
        stats['PFS'] = 'Gunsmithing required; never Always Available'
    return title, item


def url_key(url):
    return unquote(url).casefold()


def convert(existing, directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    details = {}
    for url, (filename, groups) in manifest.items():
        name, item = parse((directory / filename).read_text())
        category = item['category']
        detail_group = slug(item['detail_proficiency'])
        group = detail_group if detail_group in groups else next(iter(groups), '')
        if not group:
            group = 'ammunition' if category in {'ammunition', 'alchemical-weapons'} else detail_group or 'special'
        details[url_key(url)] = (name, {**item, 'url': url, 'group': group, 'proficiencies': groups or [group]})

    result = {}
    used = set()
    for key, old in existing.items():
        link = url_key(old['url'])
        if key == 'unarmed-strike':
            link = next(url for url in details if url.endswith('?itemname=unarmed strike'))
        name, item = details[link]
        used.add(link)
        entry = {**old, **item, 'aliases': list(dict.fromkeys([*old['aliases'], *([name] if name != old['name'] else [])]))}
        if entry['category'] == 'ammunition':
            entry.update(kind='gear', ranged=False, bow=False, thrown=False, two_handed=False, finesse=False, add_strength=False)
        # The detail page covers the base bow. Preserve each priced Strength variant.
        if old['strength_rating'] is not None:
            for field in ('cost', 'cost_text'):
                entry[field] = old[field]
        if key == 'darts-featherweight-10':
            entry['cost'] = old['cost']
        if key.startswith('sabre-sawtooth-'):
            for field in ('group', 'cost', 'cost_text', 'critical', 'special'):
                entry[field] = old[field]
            entry['proficiencies'] = [entry['group']]
        result[key] = entry

    for link, (name, item) in details.items():
        if link in used:
            continue
        key = slug(name)
        if key in result:
            raise ValueError(f'Identifier already used: {key}')
        category = item['category']
        group = item['group']
        ranged = category in {'ranged', 'siege', 'explosive'} or category.startswith(('direct-fire-', 'indirect-fire-'))
        ranged |= group == 'firearms' and category in {'one-handed', 'two-handed'}
        gear = category in {'ammunition', 'modification'}
        bow = ranged and bool(re.search(r'(?:^|\s)(?:longbow|shortbow|bow)(?:$|[,\s])', name.casefold()))
        thrown = ranged and group not in {'firearms', 'siege-engines'} and not bow and not re.search(
            r'bow|blowgun|sling|launcher|flask thrower', name, re.I
        )
        result[key] = {
            'name': name, 'kind': 'gear' if gear else 'weapon', 'enabled': True, **item,
            'aliases': [], 'notes': '', 'ranged': ranged, 'bow': bow, 'thrown': thrown,
            'two_handed': category == 'two-handed' and not ranged,
            'finesse': category in {'light', 'unarmed'} and not ranged,
            'add_strength': bool(thrown or (ranged and re.search(r'\bsling\b', name, re.I))),
            'strength_rating': 0 if bow and 'composite' in name.casefold() else None,
        }
    return result


if __name__ == '__main__':
    catalog = Path(sys.argv[1])
    result = convert(json.loads(catalog.read_text()), Path(sys.argv[2]))
    catalog.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'Imported {len(result)} weapon records.')
