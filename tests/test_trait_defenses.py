from types import SimpleNamespace

from pathkeeper.trait_defenses import trait_defenses


def checks(class_name, level, ancestry="Human", **values):
    character = SimpleNamespace(class_name=class_name, ancestry=ancestry, level=level, sheet_data={})
    return {(row["situation"], row["check"]): row for row in trait_defenses(character, values)}


def test_fighter_bravery_stacks_with_fearless_only_on_will():
    saves = {"save.will.total": "5", "save.reflex.total": "2"}
    assert checks("Fighter", 1, **saves) == {}
    rows = checks("Fighter", 6, "Halfling", **saves)
    assert rows["Fear", "Will"]["result"] == "+9"
    assert rows["Fear", "Reflex"]["result"] == "+4"
    assert saves["save.will.total"] == "5"


def test_hardy_stacks_with_poison_resistance_and_spell_saves_stay_separate():
    rows = checks("Alchemist", 8, "Dwarf", **{"save.fortitude.total": "7"})
    assert rows["Poison", "Fortitude"]["result"] == "+15"
    assert rows["Spells or spell-like abilities", "Fortitude"]["result"] == "+9"
    assert checks("Alchemist", 10)["Poison", "Immunity"]["result"] == "Immune"
    assert ("Poison", "Immunity") not in checks("Investigator", 10)


def test_danger_sense_and_precision_damage_use_the_selected_progression():
    values = {"ac.total": "18", "skill.perception.total": "5"}
    rows = checks("Rogue (Unchained)", 6, **values)
    assert rows["Traps", "AC"]["result"] == "+20"
    assert rows["Avoid being surprised by a foe", "Perception"]["result"] == "+7"
    assert rows["Qualifying sneak attack", "Extra damage"]["result"] == "+3d6"
    assert ("Avoid being surprised by a foe", "Perception") not in checks("Rogue", 6)
    assert checks("Slayer", 6)["Qualifying sneak attack", "Extra damage"]["result"] == "+2d6"


def test_monk_and_paladin_defenses_use_level_gates():
    assert ("Enchantment spells or effects", "Will") not in checks("Monk (Unchained)", 3)
    assert checks("Monk", 13)["Spells subject to spell resistance", "Spell resistance"]["result"] == "23"
    assert checks("Paladin", 3)["Fear while conscious", "Immunity"]["result"] == "Immune"
