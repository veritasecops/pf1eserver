"""Resolve named sheet features against their published references."""
import re
from urllib.parse import quote

from .class_catalog import class_key, class_profile
from .pf1_data import RACES
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


def ability_options(character, catalog):
    class_id = class_key(character, catalog)
    profile = class_profile(catalog, class_id) if class_id else {}
    class_url = safe_weapon_url(profile.get("url", ""))
    features = {}
    for level in profile.get("levels", [])[:character.level]:
        for name in [*re.split(r",\s*(?![^()]*\))", level["features"]), *level.get("choices", [])]:
            if name:
                features[ability_name(name)] = (name, class_url)
    race = next((key for key, item in RACES.items() if normalized(item["name"]) == normalized(character.ancestry)), None)
    race_url = "https://www.aonprd.com/RacesDisplay.aspx?ItemName=" + quote(RACES[race]["name"]) if race else ""
    racial = {normalized(name): (name, race_url) for name in RACIAL_ABILITIES.get(race, ())}
    return features, racial


def automatic_class_abilities(values, character, catalog):
    features, _ = ability_options(character, catalog)
    recorded = {ability_name(values[f"feature.{row}"].split(":", 1)[0]) for row in range(56)}
    return [(name, url) for key, (name, url) in features.items()
            if key not in recorded and "feat" not in key.split()]


def feature_picker(character, catalog):
    _, racial = ability_options(character, catalog)
    feats = [{"name": name, "url": safe_weapon_url(item.get("url", "")), "choice": item.get("choice", "")}
             for name, item in catalog["feats"].items() if item.get("enabled", True)]
    return {
        "feat": sorted(feats, key=lambda item: item["name"].casefold()),
        "racial": [{"name": name, "url": url} for name, url in sorted(racial.values())],
    }


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
