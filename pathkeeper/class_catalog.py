"""Editable class definitions backed by sparse rule-catalog overrides."""
from .pf1_data import CLASSES, CLASS_PROGRESSIONS

GROUPS = ("Core", "Base", "Alternate", "Unchained", "NPC")
BONUS_FEATS = ("", "combat", "monk", "teamwork", "technique")

FEATURE_REFERENCES = {
    "investigator": {"investigator talent": "https://www.aonprd.com/InvestigatorTalents.aspx"},
}


# First eligible level, frequency, and whether the exchanged spell must be below
# the highest spell level the character can cast.
SPELL_SWAPS = {
    **dict.fromkeys(("bard", "inquisitor", "mesmerist", "skald", "spiritualist", "summoner", "summoner-unchained"), (5, 3, True)),
    **dict.fromkeys(("hunter", "medium"), (5, 3, False)),
    **dict.fromkeys(("oracle", "sorcerer"), (4, 2, False)),
    "bloodrager": (8, 3, False),
    "psychic": (4, 2, True),
}

def class_profile(catalog, key):
    from .aon_sources import source_for
    base = CLASSES[key]
    progression = CLASS_PROGRESSIONS[key]
    result = {
        **base,
        "casting_ability": progression["caster"],
        "caster_delay": progression["caster_delay"],
        "spell_swap": SPELL_SWAPS.get(key),
        "book": progression["book"],
        "starting_book": {0: 0, 1: 2, 2: 3}[progression["book"]],
        "levels": progression["levels"],
        "feature_references": FEATURE_REFERENCES.get(key, {}),
        **catalog.get("classes", {}).get(key, {}),
    }
    if 'source' not in result:
        result['source'] = source_for(result.get('url', ''))
    return result


def creation_class(catalog, key):
    if key not in CLASSES:
        return None
    profile = class_profile(catalog, key)
    return {name: profile[name] for name in CLASSES[key]}


def class_key(character, catalog):
    key = (character.sheet_data or {}).get("input", {}).get("class_id")
    if key in CLASSES:
        return key
    name = character.class_name.casefold()
    for key, default in CLASSES.items():
        profile = class_profile(catalog, key)
        if name in {value.casefold() for value in (default["name"], profile["name"], *profile.get("aliases", []))}:
            return key
    return None


def class_save_bonuses(character, catalog):
    key = class_key(character, catalog)
    if key is not None:
        levels = class_profile(catalog, key)["levels"]
        if 1 <= character.level <= len(levels):
            return levels[character.level - 1]["saves"]
    return None

