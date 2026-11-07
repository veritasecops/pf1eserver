"""Armor, shield, and extra facts from d20PFSRD's Armor and Shields table."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from .weapons import WEAPON_GEAR_CATEGORIES, safe_weapon_url

ARMOR_CATEGORIES={'light':'Light armor','medium':'Medium armor','heavy':'Heavy armor','shield':'Shields','extra':'Armor extras'}


@lru_cache
def table_armor():
    return json.loads((Path(__file__).parent/'data'/'armor.json').read_text())


def merge_armor_tables(existing):
    return {**deepcopy(table_armor()),**deepcopy(existing)}


def purchasable(item):
    return item.get('kind') in {'weapon','armor','shield'} or item.get('category') in WEAPON_GEAR_CATEGORIES | {'extra'}


def armor_fields(item,quantity,size):
    small=str(size).casefold()=='small'
    return {'name':item['name'],'quantity':str(quantity),'type':item.get('category',item['kind']),
            'bonus':str(item.get('shield',0) if item['kind']=='shield' else item.get('armor',0)),
            'max_dex':str(item.get('max_dex',100)) if item.get('max_dex',100)!=100 else '—',
            'penalty':str(item.get('acp',0)), 'failure':str(item['spell_failure'])+'%' if item.get('spell_failure') is not None else item.get('spell_failure_text',''),
            'weight':str(item['weight']*(.5 if small else 1)) if item.get('weight') is not None else item.get('weight_text','Special')}


def sheet_armor_links(values,character,catalog):
    entries=catalog.get('armor',{})
    matches={name.casefold():key for key,item in entries.items() for name in [item['name'],*item.get('aliases',[])]}
    for entry in (character.play_data or {}).get('weapon_inventory',[]):
        if entry.get('armor_row') is not None and entry.get('id') in entries:
            matches[entry['item']['name'].casefold()]=entry['id']
    for key,item in ((character.sheet_data or {}).get('catalog') or {}).get('armor',{}).items():
        if key in entries: matches.setdefault(item['name'].casefold(),key)
    links={}
    for row in range(6):
        name=values.get(f'armor.{row}.name','').strip()
        url=safe_weapon_url(entries.get(matches.get(name.casefold()),{}).get('url',''))
        if url: links[str(row)]={'url':url,'name':name}
    return links
