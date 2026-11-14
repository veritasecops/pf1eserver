"""PF1e ancestry and class effects that can be evaluated from a play sheet."""
from decimal import Decimal
import json
from pathlib import Path
from math import floor

# Core Rulebook, Carrying Capacity and Encumbrance.
LOAD_LIMITS = (
    (0, 0), (3, 6), (6, 13), (10, 20), (13, 26), (16, 33), (20, 40),
    (23, 46), (26, 53), (30, 60), (33, 66), (38, 76), (43, 86), (50, 100),
    (58, 116), (66, 133), (76, 153), (86, 173), (100, 200), (116, 233),
    (133, 266), (153, 306), (173, 346), (200, 400), (233, 466), (266, 533),
    (306, 613), (346, 693), (400, 800), (466, 933),
)
SIZE_LOAD = {
    "fine": Decimal("0.125"), "diminutive": Decimal("0.25"), "tiny": Decimal("0.5"),
    "small": Decimal("0.75"), "medium": 1, "large": 2, "huge": 4, "gargantuan": 8, "colossal": 16,
}
FAST_MOVEMENT = {"barbarian", "barbarian-unchained", "bloodrager"}
MONKS = {"monk", "monk-unchained"}

# Archives of Nethys Fighter Weapon Groups, keyed by published weapon names.
FIGHTER_WEAPON_GROUPS = {
    group: frozenset(names)
    for group, names in json.loads((Path(__file__).parent / "data" / "fighter_weapon_groups.json").read_text()).items()
}
WEAPON_GROUP_NAMES = {name.casefold().replace(",", ""): name for name in FIGHTER_WEAPON_GROUPS}


def racial_skill_bonus(race, skill):
    if skill == "perception" and race in {"elf", "half-elf", "gnome", "halfling"}:
        return 2
    if skill == "intimidate" and race == "half-orc":
        return 2
    if skill in {"acrobatics", "climb"} and race == "halfling":
        return 2
    return 0


def class_skill_bonus(class_id, level, skill):
    if class_id in {"bard", "skald"} and skill.startswith("knowledge-"):
        return max(1, level // 2)
    if class_id == "inquisitor" and skill in {"intimidate", "sense-motive"}:
        return max(1, level // 2)
    if class_id == "mesmerist" and skill == "bluff":
        return max(1, level // 2)
    if class_id in {"rogue", "rogue-unchained", "investigator"} and skill == "disable-device":
        return max(1, level // 2)
    return 0


def load_category(strength, size, weight):
    if strength is None or weight is None or strength < 1 or strength >= 100:
        return "unknown"
    strength = floor(strength)
    tens = max(0, (strength - 20) // 10)
    light, medium = LOAD_LIMITS[strength - tens * 10]
    scale = SIZE_LOAD.get(size, 1) * 4 ** tens
    if weight <= light * scale:
        return "light"
    return "medium" if weight <= medium * scale else "heavy"


def armor_training(class_id, level):
    return min(4, (level + 1) // 4) if class_id == "fighter" else 0


def nimble(class_id, level, armor, load):
    if armor not in {None, "light"} or load in {"medium", "heavy"}:
        return 0
    if class_id == "gunslinger":
        return (level + 2) // 4
    if class_id == "swashbuckler":
        return (level + 1) // 4
    if class_id == "brawler":
        return sum(level >= threshold for threshold in (4, 9, 13, 18))
    return 0


def fighter_weapon_groups():
    return FIGHTER_WEAPON_GROUPS


def weapon_group_name(name):
    key = " ".join(name.casefold().replace(",", "").split())
    aliases = {"heavy blades": "blades heavy", "light blades": "blades light"}
    return WEAPON_GROUP_NAMES.get(aliases.get(key, key))


def trained_weapon_groups(character):
    from .class_abilities import removed_class_ability
    if removed_class_ability(character, 'Weapon Training', 'fighter'):
        return {}
    groups = {}
    for entry in (character.play_data or {}).get("advancement_history", []):
        for choice in entry["choices"]:
            if choice["feature"].casefold().startswith("weapon training"):
                group = weapon_group_name(choice["choice"])
                if group:
                    groups.setdefault(group, entry.get("class_level", entry["level"]))
    return groups


def fighter_weapon_bonus(groups, item, level):
    names = {name.casefold() for name in [item.get("name", ""), *item.get("aliases", [])]}
    return max((1 + (level - earned) // 4 for group, earned in groups.items()
                if earned <= level and names & FIGHTER_WEAPON_GROUPS[group]), default=0)
