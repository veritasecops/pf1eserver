"""Deity and belief names with their current description links."""
from functools import lru_cache
import json
from pathlib import Path

from fastapi import HTTPException
from .weapons import safe_weapon_url


@lru_cache
def table_deities():
    return json.loads((Path(__file__).parent/'data'/'deities.json').read_text())


def deity_key(value,entries):
    if value in entries: return value
    match=str(value).casefold()
    return next((key for key,item in entries.items() if match in {name.casefold() for name in [item['name'],*item.get('aliases',[])]}),None)


def choose_deity(value,entries,previous=''):
    if not value: return ''
    key=deity_key(value,entries)
    old=deity_key(previous,entries)
    if key and (entries[key].get('enabled',True) or key==old): return key
    if not key and value==previous: return value
    raise HTTPException(422,'Choose an available deity or Atheism from the catalog.')


def deity_choices(entries,current=''):
    selected=deity_key(current,entries)
    choices=[dict(id=key,name=item['name']+(' (archived)' if not item.get('enabled',True) else ''),url=safe_weapon_url(item.get('url','')))
             for key,item in entries.items() if item.get('enabled',True) or key==selected]
    if current and not selected: choices.append(dict(id=current,name=current+' (existing selection)',url=''))
    return sorted(choices,key=lambda item:item['name'].casefold()),selected or current
