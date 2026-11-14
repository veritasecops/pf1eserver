"""Editable class definitions backed by sparse rule-catalog overrides."""
import re
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

FIRST_LEVEL_CHOICES = {
    "wizard": ("Arcane bond", "Arcane school"),
    "cleric": ("Domains", "Channel energy"),
    "druid": ("Nature bond",),
    "sorcerer": ("Bloodline",),
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
    saved = (getattr(character, "play_data", None) or {}).get("class_levels")
    if saved:
        return saved[0][0]
    key = (character.sheet_data or {}).get("input", {}).get("class_id")
    if key in CLASSES:
        return key
    return class_key_for_name(character.class_name, catalog)


def class_key_for_name(name, catalog):
    name = (name or "").strip().casefold()
    if not name:
        return None
    for key, default in CLASSES.items():
        profile = class_profile(catalog, key)
        if name in {value.casefold() for value in (default["name"], profile["name"], *profile.get("aliases", []))}:
            return key
    return None


def character_classes(character, catalog):
    """Class levels stored in order, with a fallback for older sheets."""
    saved = (getattr(character, "play_data", None) or {}).get("class_levels")
    if saved:
        return dict(saved)
    key = class_key(character, catalog)
    if key:
        return {key: getattr(character, "level", 1)}
    # Published NPCs can already carry a class breakdown in their legacy label.
    parts = (character.class_name or "").split("/")
    classes = {}
    for part in parts:
        match = re.fullmatch(r"\s*(.+?)\s+(\d{1,2})\s*", part)
        if not match:
            return {}
        name = re.split(r" of ", match[1], maxsplit=1, flags=re.I)[0]
        key = class_key_for_name(name, catalog)
        level = int(match[2])
        if not key or key in classes or not 1 <= level <= 20:
            return {}
        classes[key] = level
    return classes if sum(classes.values()) == getattr(character, "level", 1) else {}


def class_progression_row(character, catalog, key, level, *, specialization=None):
    if not level:
        return {"bab": 0, "saves": [0, 0, 0]}
    row = class_profile(catalog, key)["levels"][level - 1]
    inputs = (character.sheet_data or {}).get("input", {})
    if key == "vigilante" and (specialization or (character.play_data or {}).get(
        "vigilante_specialization", inputs.get("vigilante_specialization")
    )) == "avenger":
        return {**row, "bab": level}
    return row


def favored_class_keys(character, classes):
    saved = (getattr(character, "play_data", None) or {}).get("favored_classes")
    if saved:
        return saved
    inputs = (character.sheet_data or {}).get("input", {})
    favored = inputs.get("favored_class") or next(iter(classes), None)
    return [key for key in (favored, inputs.get("second_favored")) if key]


def first_level_favored_bonus(inputs):
    favored = inputs.get("favored_class") or inputs.get("class_id")
    second = inputs.get("second_favored") if inputs.get("race") == "half-elf" else None
    return inputs.get("favored_bonus") if inputs.get("class_id") in {favored, second} else None


def class_summary(catalog, classes):
    name = " / ".join(f"{class_profile(catalog, key)['name']} {level}" for key, level in classes.items())
    return name if len(name) <= 100 else "Multiclass character"


def combined_class_skills(character, catalog, classes=None):
    from .rule_catalog import class_skills
    classes = character_classes(character, catalog) if classes is None else classes
    inputs = (character.sheet_data or {}).get("input", {})
    return {skill for key in classes for skill in class_skills(catalog, key, inputs.get("expert_skills", ()))}


def casting_class_keys(catalog, classes):
    return [key for key in classes if class_profile(catalog, key)["casting_ability"]]


def class_save_bonuses(character, catalog):
    rows = [class_progression_row(character, catalog, key, level)["saves"]
            for key, level in character_classes(character, catalog).items() if 1 <= level <= 20]
    return [sum(values) for values in zip(*rows)] if rows else None

