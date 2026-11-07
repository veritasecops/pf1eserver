"""Verified AoN destinations and the one-time conversion of stored reference URLs."""
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


@lru_cache
def reference_links():
    return json.loads((Path(__file__).parent / 'data' / 'aon_reference_links.json').read_text())


def class_reference(name):
    return reference_links()['classes'][name.lower().replace(' ', '-')]


def is_old_reference(url):
    return isinstance(url, str) and urlsplit(url).hostname in {'d20pfsrd.com', 'www.d20pfsrd.com'}


def reference_key(url):
    parts = urlsplit(url)
    return (unquote(parts.path).rstrip('/') + ('?' + parts.query if parts.query else '')
            + ('#' + parts.fragment if parts.fragment else '')).lower()


def replace_url(url):
    if not is_old_reference(url):
        return url
    key = reference_key(url)
    links = reference_links()['legacy_urls']
    for candidate in (key, key.split('#')[0]):
        if candidate in links:
            return links[candidate]
    raise ValueError(f'No verified AoN equivalent for {url}')


@lru_cache
def equipment_names():
    names = {}
    for group in ('weapons', 'armor'):
        entries = json.loads((Path(__file__).parent / 'data' / f'{group}.json').read_text())
        for key, item in entries.items():
            for name in [item['name'], *item.get('aliases', [])]:
                names.setdefault(name.casefold(), []).append((group, key))
    return names


def replace_references(value, group=None, key=None):
    """Convert links only; retain statistics, names, notes, and unrelated URLs."""
    if isinstance(value, list):
        return [replace_references(item, group) for item in value]
    if isinstance(value, dict):
        result = {k: replace_references(v, k if k in {'weapons', 'armor', 'classes'} else group, k)
                  for k, v in value.items()}
        if is_old_reference(value.get('url')):
            links = reference_links()
            candidates = equipment_names().get(str(value.get('name', '')).casefold(), [])
            kind_group = {'weapon': 'weapons', 'armor': 'armor', 'shield': 'armor'}.get(value.get('kind'))
            candidates = [candidate for candidate in candidates if not (group or kind_group)
                          or candidate[0] == (group or kind_group)]
            candidates = [(g, k) for g, k in candidates if k in links['legacy_item_urls'][g]]
            if (group in links.get('legacy_item_urls', {})
                    and links['legacy_item_urls'][group].get(key) == reference_key(value['url'])):
                result['url'] = links[group][key]
            elif (candidates and len({links[g][k] for g, k in candidates}) == 1
                  and all(links['legacy_item_urls'][g][k] == reference_key(value['url']) for g, k in candidates)):
                g, k = candidates[0]
                result['url'] = links[g][k]
        return result
    if isinstance(value, str):
        return re.sub(r'https?://(?:www\.)?d20pfsrd\.com/[^\s<>"\']*',
                      lambda match: replace_url(match[0]), value, flags=re.IGNORECASE)
    return value


def migrate_reference_links(db):
    from sqlalchemy import select
    from .models import Character, CharacterDraft, RuleCatalog

    changed = {}
    for record in db.scalars(select(RuleCatalog).with_for_update()):
        updated = replace_references(record.data)
        if updated != record.data:
            record.data = updated
    for character in db.scalars(select(Character).with_for_update()):
        sheet, play = replace_references(character.sheet_data), replace_references(character.play_data)
        if (sheet, play) != (character.sheet_data, character.play_data):
            changed[character.id] = (character.version, character)
            character.sheet_data, character.play_data = sheet, play
    db.flush()
    for draft in db.scalars(select(CharacterDraft).with_for_update()):
        updated = replace_references(draft.data)
        if updated != draft.data:
            draft.data = updated
        if draft.mode == 'edit' and draft.editing_id in changed:
            previous, character = changed[draft.editing_id]
            if draft.existing_version == previous:
                draft.existing_version = character.version
    db.info.pop('rule_catalog', None)


def remove_unreferenced_classes(db):
    from copy import deepcopy
    from sqlalchemy import select
    from .models import RuleCatalog

    removed = {'omdura', 'vampire-hunter'}
    for record in db.scalars(select(RuleCatalog).with_for_update()):
        updated = deepcopy(record.data)
        for skill in updated.get('skills', {}).values():
            if 'classes' in skill:
                skill['classes'] = [key for key in skill['classes'] if key not in removed]
        if updated != record.data:
            record.data = updated
    db.info.pop('rule_catalog', None)


def add_admin_reference_links(db):
    """Fill verified references without replacing custom or unmatched links."""
    from copy import deepcopy
    from sqlalchemy import select
    from .models import RuleCatalog

    links = reference_links()
    for record in db.scalars(select(RuleCatalog).with_for_update()):
        updated = deepcopy(record.data)
        for group in ('feats', 'skills', 'deities'):
            for key, url in links[group].items():
                item = updated.get(group, {}).get(key)
                if item is None:
                    continue
                old = item.get('url', '')
                if not old or group == 'deities' and old == links['legacy_deity_urls'][key]:
                    item['url'] = url
        if updated != record.data:
            record.data = updated
    db.info.pop('rule_catalog', None)
