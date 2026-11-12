"""Browse class progression features using the active class catalog."""
import re
from urllib.parse import quote

from .class_catalog import class_profile
from .feature_links import ability_name, class_feature_reference
from .pf1_data import CLASSES
from .weapons import safe_weapon_url


def class_abilities(catalog, class_ids=None):
    entries = []
    classes = {}
    for class_id in CLASSES if class_ids is None else class_ids:
        profile = class_profile(catalog, class_id)
        classes[class_id] = profile
        grouped = {}
        for level, row in enumerate(profile['levels'], 1):
            for label in re.split(r',\s*(?![^()]*\))', row['features']):
                label = label.strip()
                if not label or label in {'—', '-', '–'}:
                    continue
                key = ability_name(label)
                item = grouped.setdefault(key, {'name': re.sub(r'\s+(?:\([^)]*\)|[+]?\d.*)$', '', label).strip(),
                                                'gains': []})
                item['gains'].append({'level': level, 'name': label})
        reference = safe_weapon_url(profile.get('url', ''))
        for item in grouped.values():
            feature_url = class_feature_reference(profile, item['name'])
            if not feature_url and reference:
                feature_url = reference.split('#')[0] + '#:~:text=' + quote(item['gains'][0]['name'], safe='')
            entries.append({**item, 'id': f'{class_id}:{ability_name(item["name"])}', 'class_id': class_id, 'class_name': profile['name'],
                            'group': profile['group'], 'class_url': reference,
                            'url': feature_url,
                            'source': profile.get('source', '')})
    return entries, classes
