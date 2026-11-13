"""Resolve named sheet features against their published references."""
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from .class_catalog import class_key, class_profile
from .pf1_data import CLASSES, RACES
from .rule_catalog import equipment
from .weapons import safe_weapon_url

RACIAL_ABILITIES = {
    "human": ("Bonus Feat", "Skilled"),
    "dwarf": ("Slow and Steady", "Darkvision", "Defensive Training", "Greed", "Hatred", "Hardy", "Stability", "Stonecunning", "Weapon Familiarity"),
    "elf": ("Low-Light Vision", "Elven Immunities", "Elven Magic", "Keen Senses", "Weapon Familiarity"),
    "gnome": ("Low-Light Vision", "Defensive Training", "Gnome Magic", "Hatred", "Illusion Resistance", "Keen Senses", "Obsessive", "Weapon Familiarity"),
    "half-elf": ("Low-Light Vision", "Adaptability", "Elf Blood", "Elven Immunities", "Keen Senses", "Multitalented"),
    "half-orc": ("Darkvision", "Intimidating", "Orc Blood", "Orc Ferocity", "Weapon Familiarity"),
    "halfling": ("Slow Speed", "Fearless", "Halfling Luck", "Keen Senses", "Sure-Footed", "Weapon Familiarity"),
}


def normalized(name):
    return " ".join(name.replace("’", "'").casefold().split())


def ability_name(name):
    return normalized(re.sub(r"\s+(?:\([^)]*\)|[+]?\d.*)$", "", name).strip())


@lru_cache(maxsize=1)
def aon_class_feature_headings():
    path = Path(__file__).with_name("data") / "aon_class_feature_headings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def class_feature_reference(class_id, profile, name):
    key = ability_name(name)
    reference = safe_weapon_url(profile.get("feature_references", {}).get(key))
    if reference:
        return reference
    class_url = safe_weapon_url(profile.get("url", "")).partition("#")[0]
    if not class_url or class_url != CLASSES[class_id]["url"]:
        return ""
    heading = aon_class_feature_headings().get(class_id, {}).get(key)
    if not heading:
        return ""
    fragment = quote(heading, safe="").replace("-", "%2D")
    return f"{class_url}#:~:text={fragment}"


def ability_options(character, catalog, include_prompts=True):
    class_id = class_key(character, catalog)
    profile = class_profile(catalog, class_id) if class_id else {}
    features = {}
    for level in profile.get("levels", [])[:character.level]:
        names = re.split(r",\s*(?![^()]*\))", level["features"])
        if include_prompts:
            names.extend(level.get("choices", []))
        for name in names:
            if name:
                features[ability_name(name)] = (name, class_feature_reference(class_id, profile, name))
        race = next((key for key, item in RACES.items()
                     if normalized(item["name"]) == normalized(character.ancestry or "")), None)
    race_url = "https://www.aonprd.com/RacesDisplay.aspx?ItemName=" + quote(RACES[race]["name"]) if race else ""
    racial = {normalized(name): (name, race_url) for name in RACIAL_ABILITIES.get(race, ())}
    return features, racial


def sheet_ability_blocks(values, character, catalog):
    from .class_abilities import class_abilities as catalog_abilities, removed_class_ability

    granted, racial = ability_options(character, catalog, include_prompts=False)
    class_choices, _ = ability_options(character, catalog)
    class_id = class_key(character, catalog)
    options, _ = catalog_abilities(catalog, [class_id] if class_id else [])
    options = {item['id']: item for item in options if item['class_id'] == class_id}
    state = (getattr(character, 'play_data', None) or {}).get('class_ability_changes', {})
    for key in set(state.get('added', [])) | set(state.get('removed', [])):
        if item := options.get(key):
            class_choices[ability_name(item['name'])] = (item['name'], item['url'])
    class_abilities = {key: item for key, item in granted.items() if "feat" not in key.split()}
    feat_names = {normalized(name) for name in catalog["feats"]}
    recorded_class, recorded_racial, slots = {}, {}, set()
    editable = {}
    for row in range(56):
        name = values.get(f"feature.{row}", "").strip()
        base = re.sub(r"\s+\([^)]*\)$", "", name)
        if normalized(name) in feat_names or normalized(base) in feat_names:
            continue
        key = ability_name(name.split(":", 1)[0])
        if key in racial:
            recorded_racial.setdefault(key, []).append((name, racial[key][1]))
        elif key in class_choices:
            recorded_class.setdefault(key, []).append((name, class_choices[key][1]))
            if ":" in name and key != "weapon training":
                label, choice = name.split(":", 1)
                editable[name] = {"row": row, "label": label.strip(), "choice": choice.strip()}
        else:
            continue
        slots.add(row)

    def entries(automatic, recorded):
        return [item for key in dict.fromkeys([*automatic, *recorded])
                for item in (recorded[key] if key in recorded else [automatic[key]])]

    visible = [(name, url) for name, url in entries(class_abilities, recorded_class)
               if not removed_class_ability(character, name.split(':', 1)[0], class_id)]
    present = {ability_name(name.split(':', 1)[0]) for name, _ in visible}
    for key in state.get('added', []):
        item = options.get(key)
        if item and key not in state.get('removed', []) and ability_name(item['name']) not in present:
            visible.append((item['name'], item['url']))
            present.add(ability_name(item['name']))
    catalog_entries = {}
    for name, _ in visible:
        key = f"{class_id}:{ability_name(name.split(':', 1)[0])}"
        if item := options.get(key):
            catalog_entries[name] = item
    visible = [(name, catalog_entries[name]['url'] if name in catalog_entries else url) for name, url in visible]
    return {"class": visible, "racial": entries(racial, recorded_racial), "slots": slots,
            "editable": editable, "catalog_entries": catalog_entries}


def feature_targets(catalog):
    return {
        "skill": {key: item["name"] for key, item in catalog["skills"].items() if item.get("enabled", True)},
        "weapon": {key: item["name"] for key, item in equipment(catalog).items()
                   if item.get("kind") == "weapon" and item.get("enabled", True)},
    }


def sheet_feature_links(values, character, catalog):
    feats = {normalized(name): item.get("url", "") for name, item in catalog["feats"].items()}
    features, racial = ability_options(character, catalog)
    links = {}
    for index in range(56):
        name = values[f"feature.{index}"].strip()
        base = re.sub(r"\s+\([^)]*\)$", "", name)
        url = safe_weapon_url(feats.get(normalized(name)) or feats.get(normalized(base)))
        ability = ability_name(name.split(":", 1)[0])
        if not url and ability in racial:
            url = racial[ability][1]
        if not url and ability in features:
            url = features[ability][1]
        if url:
            links[str(index)] = {"name": name, "url": url}
    return links
