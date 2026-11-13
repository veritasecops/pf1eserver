"""Conditional checks and effects derived from the character's ancestry and class."""
from decimal import Decimal
from urllib.parse import quote

from .class_catalog import class_key, class_profile
from .rule_catalog import character_catalog
from .sheet_calculations import base_speed_race
from .weapons import safe_weapon_url

SAVES = ("Fortitude", "Reflex", "Will")


def trait_defenses(character, values):
    catalog = character_catalog(character)
    class_id = class_key(character, catalog)
    class_url = safe_weapon_url(class_profile(catalog, class_id)["url"]) if class_id else ""
    race = base_speed_race(character).get("name", "")
    race_url = f"https://www.aonprd.com/RacesDisplay.aspx?ItemName={quote(race)}"
    level = character.level
    rows = {}

    def add(situation, checks, feature, url, bonus=None, result=None, formula=""):
        from .class_abilities import removed_class_ability
        if class_id and url == class_url and removed_class_ability(character, feature, class_id):
            return
        for check in checks:
            key = (situation, check)
            row = rows.setdefault(key, {"situation": situation, "check": check, "sources": [], "bonus": 0, "result": "", "formula": ""})
            row["sources"].append({"name": feature, "url": url, "bonus": bonus})
            if bonus is not None:
                row["bonus"] += bonus
            if result:
                row["result"] = result
            if formula:
                row["formula"] = formula

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
    if class_id == "fighter" and level >= 2:
        add("Fear", ("Will",), "Bravery", class_url, 1 + (level - 2) // 4)
    if class_id in {"barbarian", "barbarian-unchained", "rogue", "rogue-unchained", "investigator"} and level >= 3:
        danger = class_id.endswith("-unchained")
        name = "Danger Sense" if danger else "Trap Sense"
        add("Traps", ("Reflex", "AC", "Touch AC"), name, class_url, level // 3)
        if danger:
            add("Avoid being surprised by a foe", ("Perception",), name, class_url, level // 3)
    if class_id in {"bard", "skald"} and level >= 2:
        add("Bardic performance, sonic, or language-dependent effects", SAVES, "Well-Versed", class_url, 4)
    if class_id in {"alchemist", "investigator"} and level >= 2:
        if level >= (10 if class_id == "alchemist" else 11):
            add("Poison", ("Immunity",), "Poison Immunity", class_url, result="Immune")
        else:
            add("Poison", SAVES, "Poison Resistance", class_url, min(6, 2 + 2 * ((level - 2) // 3)))
    if class_id == "druid" and level >= 9:
        add("Poison", ("Immunity",), "Venom Immunity", class_url, result="Immune")
    if class_id in {"monk", "monk-unchained"}:
        if level >= (3 if class_id == "monk" else 4):
            add("Enchantment spells or effects", SAVES, "Still Mind", class_url, 2)
        if level >= 5:
            add("Disease", ("Immunity",), "Purity of Body", class_url, result="Immune")
    if class_id == "monk" and level >= 13:
        add("Spells subject to spell resistance", ("Spell resistance",), "Diamond Soul", class_url,
            result=str(level + 10), formula="Monk level + 10")
    if class_id == "paladin" and level >= 3:
        add("Fear while conscious", ("Immunity",), "Aura of Courage", class_url, result="Immune")
        add("Disease", ("Immunity",), "Divine Health", class_url, result="Immune")
        if level >= 8:
            add("Charm spells or spell-like abilities while conscious", ("Immunity",), "Aura of Resolve",
                class_url, result="Immune")
    if class_id in {"barbarian", "barbarian-unchained", "bloodrager"} and level >= 7:
        add("Damage reduction", ("DR",), "Damage Reduction", class_url, result=f"{1 + (level - 7) // 3}/–",
            formula="1 at level 7, plus 1 every 3 levels thereafter")
    if class_id in {"ninja", "rogue", "rogue-unchained"}:
        add("Qualifying sneak attack", ("Extra damage",), "Sneak Attack", class_url,
            result=f"+{(level + 1) // 2}d6", formula="1d6 at level 1, plus 1d6 every 2 levels")
    if class_id == "slayer" and level >= 3:
        add("Qualifying sneak attack", ("Extra damage",), "Sneak Attack", class_url,
            result=f"+{level // 3}d6", formula="1d6 at level 3, plus 1d6 every 3 levels")
    if class_id == "investigator" and level >= 4:
        add("Studied strike against the studied target", ("Extra damage",), "Studied Strike", class_url,
            result=f"+{(level - 2) // 2}d6", formula="1d6 at level 4, plus 1d6 every 2 levels")

    fields = {save: f"save.{save.lower()}.total" for save in SAVES}
    fields.update({"AC": "ac.total", "Touch AC": "ac.touch", "CMD": "cmd.total",
                   "Perception": "skill.perception.total", "Appraise": "skill.appraise.total",
                   "Spellcraft": "skill.spellcraft.total"})
    for row in rows.values():
        base = values.get(fields.get(row["check"], ""), "")
        if not row["result"]:
            bonus = f'{row["bonus"]:+}'
            row["result"] = f'{Decimal(base) + row["bonus"]:+f}' if base != "" else bonus
            if base != "":
                row["formula"] = f"{base} sheet total {bonus} situational bonus"
            else:
                row["formula"] = f"{bonus} to the applicable check"
    return list(rows.values())
