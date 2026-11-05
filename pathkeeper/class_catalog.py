"""Editable class definitions backed by sparse rule-catalog overrides."""
from .pf1_data import CLASSES, CLASS_PROGRESSIONS

GROUPS = ("Core", "Base", "Alternate", "Unchained", "NPC")
BONUS_FEATS = ("", "combat", "monk", "teamwork", "technique")


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
    base = CLASSES[key]
    progression = CLASS_PROGRESSIONS[key]
    return {
        **base,
        "casting_ability": progression["caster"],
        "caster_delay": progression["caster_delay"],
        "spell_swap": SPELL_SWAPS.get(key),
        "book": progression["book"],
        "starting_book": {0: 0, 1: 2, 2: 3}[progression["book"]],
        "levels": progression["levels"],
        **catalog.get("classes", {}).get(key, {}),
    }


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

