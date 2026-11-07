"""Weapon table facts, safe reference links, and catalog-backed sheet links."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from urllib.parse import urlsplit

from .pf1_data import EQUIPMENT

WEAPON_CATEGORIES = {
    'unarmed': 'Unarmed', 'light': 'Light', 'one-handed': 'One-Handed',
    'two-handed': 'Two-Handed', 'ranged': 'Ranged', 'ammunition': 'Ammunition',
    'alchemical-weapons': 'Alchemical Weapons', 'modification': 'Modification',
    'explosive': 'Explosive', 'siege': 'Siege', 'close-assault': 'Close Assault',
    **{f'{mode.lower()}-fire-{size.lower()}': f'{mode}-Fire ({size})'
       for mode in ('Direct', 'Indirect') for size in ('Large', 'Huge', 'Gargantuan')},
}
WEAPON_GROUPS = {
    'simple': 'Simple', 'martial': 'Martial', 'exotic': 'Exotic', 'ammunition': 'Ammunition',
    'firearms': 'Firearms', 'mods': 'Mods', 'siege-engines': 'Siege Engines', 'special': 'Special',
}
WEAPON_GEAR_CATEGORIES = {'ammunition', 'modification', 'alchemical-weapons'}
PUBLISHED_WEAPON_FIELDS = {
    'cost', 'cost_text', 'weight', 'weight_text', 'small_damage', 'damage',
    'critical', 'range', 'damage_type', 'special', 'source', 'url',
}
WEAPON_CALCULATION_FLAGS = {'ranged', 'bow', 'thrown', 'two_handed', 'finesse', 'add_strength', 'strength_rating'}


@lru_cache
def table_weapons():
    return json.loads((Path(__file__).parent/'data'/'weapons.json').read_text())


def safe_weapon_url(value):
    if not isinstance(value,str) or len(value)>1000 or any(char.isspace() or ord(char)<32 for char in value): return ''
    try:
        url=urlsplit(value)
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or '\\' in value: return ''
        url.port
    except ValueError: return ''
    return value


def merge_weapon_tables(existing):
    """Enrich original defaults, preserving admin overrides and custom entries."""
    result=deepcopy(existing)
    for key,entry in table_weapons().items():
        merged=deepcopy(entry)
        old=existing.get(key)
        if old:
            original=EQUIPMENT.get(key,{})
            for field,value in old.items():
                if field not in original or value != original[field]:
                    merged[field]=deepcopy(value)
            # enabled was added with the first admin catalog, not the old data.
            merged['enabled']=old.get('enabled',True)
            merged['aliases']=list(dict.fromkeys([*entry.get('aliases',[]),*old.get('aliases',[]),old['name']]))
        result[key]=merged
    return result


def refresh_weapon_catalog(existing):
    """Apply the source refresh while retaining local overrides of weapon statistics."""
    baseline = json.loads((Path(__file__).parent / 'data' / 'weapon_refresh_baseline.json').read_text())
    result = deepcopy(existing)
    for key, published in table_weapons().items():
        previous = existing.get(key, {})
        item = {**previous, **deepcopy(published)}
        for field in ('name', 'enabled', 'notes'):
            if field in previous:
                item[field] = previous[field]
        old_defaults = baseline.get(key, {})
        for field in PUBLISHED_WEAPON_FIELDS:
            if field in previous and previous[field] != old_defaults.get(field, published[field]):
                item[field] = previous[field]
        if previous.get('kind') == published['kind']:
            for field in WEAPON_CALCULATION_FLAGS & previous.keys():
                item[field] = previous[field]
        item['aliases'] = list(dict.fromkeys([
            *published['aliases'], *previous.get('aliases', ()), published['name'],
        ]))
        item['aliases'] = [alias for alias in item['aliases'] if alias != item['name']]
        result[key] = item
    return result


def sheet_weapon_links(values,character,catalog):
    """Use live URLs, without replacing a character's frozen combat statistics."""
    weapons=catalog['weapons']
    matches={}
    for key,item in weapons.items():
        for name in [item['name'],*item.get('aliases',[])]:
            matches.setdefault(name.casefold(),key)
    snapshot=character.sheet_data or {}
    saved=(snapshot.get('catalog') or {}).get('weapons',{})
    for item in snapshot.get('computed',{}).get('equipment',[]):
        if item.get('kind')=='weapon' and item.get('id') in weapons:
            matches.setdefault(item['name'].casefold(),item['id'])
    for key,item in saved.items():
        if key in weapons: matches.setdefault(item['name'].casefold(),key)
    links={}
    for row in range(6):
        name=values.get(f'weapon.{row}.name','').strip()
        key=matches.get(name.casefold())
        item=weapons.get(key,{})
        url=safe_weapon_url(item.get('url',''))
        if url: links[str(row)]={'url':url,'name':name}
    return links
