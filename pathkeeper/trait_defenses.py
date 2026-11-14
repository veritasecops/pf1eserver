"""Conditional checks and effects derived from the character's ancestry and class."""
from decimal import Decimal
from urllib.parse import quote

from .class_catalog import character_classes, class_profile
from .rule_catalog import character_catalog
from .sheet_calculations import base_speed_race
from .weapons import safe_weapon_url

SAVES = ("Fortitude", "Reflex", "Will")


def trait_defenses(character, values):
    catalog = character_catalog(character)
    race = base_speed_race(character).get("name", "")
    race_url = f"https://www.aonprd.com/RacesDisplay.aspx?ItemName={quote(race)}"
    rows = {}

    def add(situation, checks, feature, url, bonus=None, result=None, formula="", class_id=None, dice=0):
        from .class_abilities import removed_class_ability
        if class_id and removed_class_ability(character, feature, class_id):
            return
        for check in checks:
            key = (situation, check)
            row = rows.setdefault(key, {"situation": situation, "check": check, "sources": [], "bonus": 0, "result": "", "formula": "", "dice": 0})
            row["sources"].append({"name": feature, "url": url, "bonus": bonus})
            if bonus is not None:
                row["bonus"] += bonus
            if result:
                row["result"] = result
            if formula:
                row["formula"] = formula
            row["dice"] += dice

    if race == "Dwarf":
        add("Poison", SAVES, "Hardy", race_url, 2)
        add("Spells or spell-like abilities", SAVES, "Hardy", race_url, 2)
        add("Bull rush or trip while standing on the ground", ("CMD",), "Stability", race_url, 4)
        add("Attacks from giants", ("AC", "Touch AC"), "Defensive Training", race_url, 4)
        add("Unusual stonework", ("Perception",), "Stonecunning", race_url, 2)
        add("Nonmagical precious metals or gemstones", ("Appraise",), "Greed", race_url, 2)
    if race == "Gnome":
        add("Attacks from giants", ("AC", "Touch AC"), "Defensive Training", race_url, 4)
        add("Illusion spells or effects", SAVES, "Illusion Resistance", race_url, 2)
    if race in {"Elf", "Half-Elf"}:
        add("Enchantment spells or effects", SAVES, "Elven Immunities", race_url, 2)
        add("Magical sleep", ("Immunity",), "Elven Immunities", race_url, result="Immune")
        if race == "Elf":
            add("Identify properties of magic items", ("Spellcraft",), "Elven Magic", race_url, 2)
            add("Overcome spell resistance", ("Caster level check",), "Elven Magic", race_url, 2)
    if race == "Halfling":
        add("Fear", SAVES, "Fearless", race_url, 2)
    for class_id, level in character_classes(character, catalog).items():
        class_url = safe_weapon_url(class_profile(catalog, class_id)["url"])
        def add_class(situation, checks, feature, url, *args, **kwargs):
            add(situation, checks, feature, url, *args, class_id=class_id, **kwargs)

        if class_id == "fighter" and level >= 2:
            add_class("Fear", ("Will",), "Bravery", class_url, 1 + (level - 2) // 4)
        if class_id in {"barbarian", "barbarian-unchained", "rogue", "rogue-unchained", "investigator"} and level >= 3:
            danger = class_id.endswith("-unchained")
            name = "Danger Sense" if danger else "Trap Sense"
            add_class("Traps", ("Reflex", "AC", "Touch AC"), name, class_url, level // 3)
            if danger:
                add_class("Avoid being surprised by a foe", ("Perception",), name, class_url, level // 3)
        if class_id in {"bard", "skald"} and level >= 2:
            add_class("Bardic performance, sonic, or language-dependent effects", SAVES, "Well-Versed", class_url, 4)
        if class_id in {"alchemist", "investigator"} and level >= 2:
            if level >= (10 if class_id == "alchemist" else 11):
                add_class("Poison", ("Immunity",), "Poison Immunity", class_url, result="Immune")
            else:
                add_class("Poison", SAVES, "Poison Resistance", class_url, min(6, 2 + 2 * ((level - 2) // 3)))
        if class_id == "druid" and level >= 9:
            add_class("Poison", ("Immunity",), "Venom Immunity", class_url, result="Immune")
        if class_id in {"monk", "monk-unchained"}:
            if level >= (3 if class_id == "monk" else 4):
                add_class("Enchantment spells or effects", SAVES, "Still Mind", class_url, 2)
            if level >= 5:
                add_class("Disease", ("Immunity",), "Purity of Body", class_url, result="Immune")
        if class_id == "monk" and level >= 13:
            add_class("Spells subject to spell resistance", ("Spell resistance",), "Diamond Soul", class_url,
                result=str(level + 10), formula="Monk level + 10")
        if class_id == "paladin" and level >= 3:
            add_class("Fear while conscious", ("Immunity",), "Aura of Courage", class_url, result="Immune")
            add_class("Disease", ("Immunity",), "Divine Health", class_url, result="Immune")
            if level >= 8:
                add_class("Charm spells or spell-like abilities while conscious", ("Immunity",), "Aura of Resolve",
                    class_url, result="Immune")
        if class_id in {"barbarian", "barbarian-unchained", "bloodrager"} and level >= 7:
            add_class("Damage reduction", ("DR",), "Damage Reduction", class_url, result=f"{1 + (level - 7) // 3}/–",
                formula="1 at level 7, plus 1 every 3 levels thereafter")
        if class_id in {"ninja", "rogue", "rogue-unchained"}:
            add_class("Qualifying sneak attack", ("Extra damage",), "Sneak Attack", class_url,
                dice=(level + 1) // 2, formula="1d6 at level 1, plus 1d6 every 2 levels")
        if class_id == "slayer" and level >= 3:
            add_class("Qualifying sneak attack", ("Extra damage",), "Sneak Attack", class_url,
                dice=level // 3, formula="1d6 at level 3, plus 1d6 every 3 levels")
        if class_id == "investigator" and level >= 4:
            add_class("Studied strike against the studied target", ("Extra damage",), "Studied Strike", class_url,
                result=f"+{(level - 2) // 2}d6", formula="1d6 at level 4, plus 1d6 every 2 levels")

    fields = {save: f"save.{save.lower()}.total" for save in SAVES}
    fields.update({"AC": "ac.total", "Touch AC": "ac.touch", "CMD": "cmd.total",
                   "Perception": "skill.perception.total", "Appraise": "skill.appraise.total",
                   "Spellcraft": "skill.spellcraft.total"})
    for row in rows.values():
        base = values.get(fields.get(row["check"], ""), "")
        if dice := row.pop("dice"):
            row["result"] = f"+{dice}d6"
            if len(row["sources"]) > 1:
                row["formula"] = "Add sneak attack dice from each class."
        if not row["result"]:
            bonus = f'{row["bonus"]:+}'
            row["result"] = f'{Decimal(base) + row["bonus"]:+f}' if base != "" else bonus
            if base != "":
                row["formula"] = f"{base} sheet total {bonus} situational bonus"
            else:
                row["formula"] = f"{bonus} to the applicable check"
    return list(rows.values())
