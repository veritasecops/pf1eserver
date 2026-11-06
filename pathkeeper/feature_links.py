"""Resolve named sheet features against their published references."""
import re
from urllib.parse import quote

from .class_catalog import class_key, class_profile
from .pf1_data import RACES
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


def sheet_feature_links(values, character, catalog):
    feats = {normalized(name): item["url"] for name, item in catalog["feats"].items()
             if safe_weapon_url(item.get("url", ""))}
    class_id = class_key(character, catalog)
    profile = class_profile(catalog, class_id) if class_id else {}
    class_url = safe_weapon_url(profile.get("url", ""))
    features = set()
    for level in profile.get("levels", [])[:character.level]:
        features.update(ability_name(name) for name in re.split(r",\s*(?![^()]*\))", level["features"]) if name)
        features.update(ability_name(name) for name in level.get("choices", []))
    race = next((key for key, item in RACES.items() if normalized(item["name"]) == normalized(character.ancestry)), None)
    racial = {normalized(name) for name in RACIAL_ABILITIES.get(race, ())}

    links = {}
    for index in range(56):
        name = values[f"feature.{index}"].strip()
        base = re.sub(r"\s+\([^)]*\)$", "", name)
        url = feats.get(normalized(name)) or feats.get(normalized(base))
        ability = ability_name(name.split(":", 1)[0])
        if not url and ability in racial:
            url = "https://www.aonprd.com/RacesDisplay.aspx?ItemName=" + quote(RACES[race]["name"])
        if not url and ability in features:
            url = class_url
        if url:
            links[str(index)] = {"name": name, "url": url}
    return links
